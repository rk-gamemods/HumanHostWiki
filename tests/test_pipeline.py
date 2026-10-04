"""Run the actual local stages against a small committed source fixture."""

import json
import io
import itertools
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_extraction
import wiki
from wikibuild import extraction, github_pages, history, model, pipeline, publication, workspace
from wikibuild.adapters import items_loot
from wikibuild.storage import ContractError, git, json_bytes, writer_lock


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_extraction.ExtractionTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.setUp()
        self.root, self.source = self.fixture.wiki, self.fixture.source
        registry = self.root / "presentation/fields.json"
        registry.parent.mkdir()
        registry.write_bytes((test_extraction.ROOT / "presentation/fields.json").read_bytes())
        (registry.parent / "site.json").write_text('{"guides": []}', encoding="utf-8")
        self.article_patch = patch.object(pipeline.external_links.mediawiki, 'Client',
                                          side_effect=AssertionError('Unexpected live article provider in fixture'))
        self.article_patch.start()
        self.addCleanup(self.article_patch.stop)
        # Release transaction failures have their own real-Git tests. Keep these
        # stage-recovery cases focused on capture, extraction, identity and reader.
        self.release_patch = patch.object(pipeline.release, 'run', side_effect=lambda root, project, candidate: (
            {'release_id': candidate['candidate_id'], 'publication': 'not-published'}, {'reused': True}))
        self.release_patch.start()
        self.addCleanup(self.release_patch.stop)

    def run_pipeline(self):
        return pipeline.run(self.root, test_extraction.PROJECT, self.source)

    def latest(self):
        return self.root / ".local/pipeline/latest.json"

    def modify(self, **fields):
        self.fixture.item["fields"].update(fields)
        self.fixture.put(items_loot.INPUTS[0], [self.fixture.item])
        self.fixture.commit()

    def test_rule_change_during_run_is_reread_at_verify_and_preserves_success(self):
        first = self.run_pipeline()
        pointer = self.latest().read_bytes()
        self.modify(_Weight=8)
        original = pipeline.release_retention.contract()
        pipeline.release.run.reset_mock()

        with patch.object(pipeline.release_retention, "contract", return_value=original) as rules:
            def change_rule(stage):
                if stage == "verify":
                    rules.return_value = {"fixture_rule": "changed"}

            with self.assertRaises(ContractError) as raised:
                pipeline.run(self.root, test_extraction.PROJECT, self.source, progress=change_rule)
            self.assertEqual(rules.call_count, 2)

        self.assertEqual(str(raised.exception.__cause__), "Pipeline rules changed during processing")
        self.assertTrue(str(raised.exception).startswith("Wiki stage verify failed: Pipeline rules changed during processing. Failure report: "))
        self.assertEqual(self.latest().read_bytes(), pointer)
        pipeline.release.run.assert_not_called()
        failure = json.loads(next((self.root / ".local/pipeline/failures").glob("*.json")).read_text())
        self.assertEqual(failure["failed_stage"], "verify")
        self.assertEqual(failure["error"]["type"], "ContractError")
        self.assertEqual(failure["error"]["message"], "Pipeline rules changed during processing")
        self.assertEqual(set(failure["completed"]), {"register", "normalize", "identity", "project"})
        request = json.loads((self.root / f".local/pipeline/requests/{failure['request_key']}.json").read_text())
        self.assertEqual(request["previous_run"], first["run_id"])
        retried = self.run_pipeline()
        result = pipeline.read(self.root, retried["run_id"])
        self.assertEqual(result["request_key"], failure["request_key"])
        self.assertEqual(result["previous_run"], first["run_id"])
        self.assertEqual(result["contracts"]["retention"], original)

    def test_contract_failure_journal_names_helper_and_preserves_shape(self):
        first = self.run_pipeline()
        previous = pipeline.read(self.root, first["run_id"])
        pointer = self.latest().read_bytes()
        with patch.object(pipeline.release_retention, "contract", side_effect=OSError("contract fault")):
            with self.assertRaises(ContractError) as raised:
                self.run_pipeline()

        path = next((self.root / ".local/pipeline/failures").glob("*.json"))
        failure = json.loads(path.read_text())
        location = failure["error"]["location"]
        self.assertEqual(failure, {
            "schema_version": 1, "kind": "execution-failure", "request_key": None,
            "snapshot_id": previous["snapshot_id"], "failed_stage": "external-articles",
            "completed": {"register": {"snapshot_id": previous["snapshot_id"],
                                      "source_commit": previous["source_commit"]}},
            "error": {"type": "OSError", "message": "contract fault",
                      "location": {"path": "wikibuild/pipeline.py", "function": "contracts", "line": location["line"]}},
            "content_exceptions": {"schema_version": 1, "kind": "unresolved-wiki-content", "groups": [],
                                   "group_count": 0, "occurrences": 0, "resolved_since_previous": [],
                                   "next_action": "No unresolved content in the implemented scope."},
            "next_action": "Report the execution failure separately; diagnose and repair, then rerun the normal command."})
        lines = {line for _, _, line in pipeline.contracts.__code__.co_lines() if line is not None}
        self.assertIn(location["line"], lines)
        self.assertEqual(path.name, pipeline.digest(json_bytes(failure)) + ".json")
        self.assertEqual(str(raised.exception.__cause__), "contract fault")
        self.assertEqual(str(raised.exception),
                         f"Wiki stage external-articles failed: contract fault. Failure report: {path}")
        self.assertEqual(self.latest().read_bytes(), pointer)

    def test_timings_are_append_only_and_do_not_change_run_or_request_identity(self):
        first = self.run_pipeline()
        stages = {"register", "availability", "external-articles", "normalize", "identity", "project",
                  "verify", "release", "retention", "reader-retention", "promote"}
        self.assertEqual(set(first["timings"]), stages)
        self.assertTrue(all(seconds >= 0 for seconds in first["timings"].values()))
        self.assertGreaterEqual(first["total_seconds"], sum(first["timings"].values()))
        saved = pipeline.read(self.root, first["run_id"])
        self.assertNotIn("timings", saved)
        self.assertNotIn("timing", json.dumps(saved))
        request_path = self.root / f".local/pipeline/requests/{saved['request_key']}.json"
        request = request_path.read_bytes()
        files = list((self.root / ".local/pipeline/timings").glob("*.json"))
        before = files[0].read_bytes()
        with patch.object(pipeline, "perf_counter", side_effect=itertools.count(0, 1)):
            second = self.run_pipeline()
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertNotEqual(first["timings"], second["timings"])
        self.assertEqual(request_path.read_bytes(), request)
        self.assertEqual(files[0].read_bytes(), before)
        files = list((self.root / ".local/pipeline/timings").glob("*.json"))
        self.assertEqual(len(files), 2)
        for path in files:
            timing = json.loads(path.read_text())
            self.assertTrue(path.name.endswith("-git-release-ready.json"))
            self.assertEqual(set(timing["stages"]), stages)
            self.assertLessEqual(timing["started_utc"], timing["finished_utc"])
            self.assertIsNone(timing["failed_stage"])
            self.assertIn("publication", timing)

    def test_failure_has_partial_timings_and_innermost_repository_location(self):
        def fail_reader(*args, **kwargs):
            raise RuntimeError("reader fault")

        with patch.object(pipeline.reader, "build", side_effect=fail_reader):
            with self.assertRaises(ContractError) as raised:
                self.run_pipeline()
        stages = {"register", "availability", "external-articles", "normalize", "identity", "project"}
        self.assertEqual(set(raised.exception.timings), stages)
        self.assertTrue(all(seconds >= 0 for seconds in raised.exception.timings.values()))
        failure = json.loads(next((self.root / ".local/pipeline/failures").glob("*.json")).read_text())
        self.assertEqual(failure["error"]["location"], {"path": "tests/test_pipeline.py", "function": "fail_reader",
                                                       "line": fail_reader.__code__.co_firstlineno + 1})
        self.assertNotIn("timings", failure)
        timing = json.loads(next((self.root / ".local/pipeline/timings").glob("*-execution-failure.json")).read_text())
        self.assertEqual(timing["stages"], raised.exception.timings)
        self.assertEqual(timing["failed_stage"], "project")
        self.assertGreaterEqual(timing["total_seconds"], sum(timing["stages"].values()))

    def test_timing_write_failure_does_not_change_success_or_execution_failure(self):
        original = Path.open

        def protected(path, *args, **kwargs):
            if args and args[0] == "xb" and path.parent.name == "timings":
                raise OSError("protected timing directory")
            return original(path, *args, **kwargs)

        stderr = io.StringIO()
        with patch.object(Path, "open", protected), patch.object(pipeline.sys, "stderr", stderr):
            result = self.run_pipeline()
            self.assertEqual(result["status"], "git-release-ready")
            with patch.object(pipeline.reader, "build", side_effect=RuntimeError("reader fault")):
                with self.assertRaisesRegex(ContractError, "stage project failed"):
                    self.run_pipeline()
        self.assertEqual(stderr.getvalue().count("Wiki timing could not be saved"), 2)

    def test_update_never_publishes_or_constructs_a_live_host(self):
        (self.root / "project.json").write_bytes(json_bytes(test_extraction.PROJECT))
        with patch.object(publication, "run", side_effect=AssertionError("Unexpected publication")), \
                patch.object(github_pages, "GitHubPages", side_effect=AssertionError("Unexpected live host")):
            result = wiki.run(self.root, SimpleNamespace(command="update", source=str(self.source)))
            self.assertEqual(result["run_id"], self.run_pipeline()["run_id"])
        self.assertEqual(result["release_id"], result["wiki_release"])
        self.assertIn(f"py -3 wiki.py publish --release {result['release_id']}", result["next_step"])
        self.assertIn("After successful rehearsal", pipeline.operator_report(self.root, result))
        self.assertNotIn("publish", result["timings"])

    def test_operator_time_section_preserves_existing_text_and_labels_parallel_sums(self):
        result = self.run_pipeline()
        legacy = dict(result)
        legacy.pop("timings")
        original = pipeline.operator_report(self.root, legacy)
        result["metrics"]["publish"] = {"timing": {
            "repositories": {"items": {"push_main": 2, "push_pages": 3, "configure": 1,
                                        "pages_build": 8, "verify": 4, "total": 18}},
            "phases": {"topics-1": 18}, "prepare": 2, "resume": 18}}
        text = pipeline.operator_report(self.root, result)
        self.assertTrue(text.startswith(original + "\nTime\n"))
        for stage in result["timings"]:
            self.assertIn(f"- {stage}:", text)
        for label in ("Upload (pushes)", "GitHub Pages processing", "Public verification", "Other publish work"):
            self.assertIn(label, text)
        self.assertIn("slowest repository: items, 8.00 s", text)
        self.assertIn("parallel phases: 18.00 s wall-clock", text)
        self.assertIn("when parallel workers overlap", text)

    def test_supported_update_completes_with_unknown_content(self):
        self.modify(MaxStack=19, NewUnparsedFeature="DO NOT EXPORT")
        result = self.run_pipeline()
        saved = pipeline.read(self.root, result["run_id"])
        self.assertEqual(saved["status"], "git-release-ready")
        self.assertEqual(saved["completed"]["release"]["publication"], "not-published")
        self.assertTrue(any(group["code"] == "new-field" for group in saved["exceptions"]["groups"]))
        extracted = extraction.read(self.root, saved["completed"]["normalize"]["run_id"])
        facts = extraction.artifact(self.root, extracted["records"]).read_text(encoding="utf-8")
        self.assertIn('"MaxStack":19', facts)
        self.assertNotIn("DO NOT EXPORT", facts)
        self.assertIn("new-field", pipeline.operator_report(self.root, result))
        self.assertEqual(result['remaining'], ['content-exceptions', 'publish'])

    def test_repeat_keeps_same_receipt_pointer_and_reuses_all_stages(self):
        first = self.run_pipeline()
        pointer = (self.latest().read_bytes(), self.latest().stat().st_mtime_ns)
        second = self.run_pipeline()
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(pointer, (self.latest().read_bytes(), self.latest().stat().st_mtime_ns))
        self.assertTrue(all(value["reused"] for value in second["metrics"].values()))
        self.assertEqual(sum(value.get("source_bytes_read", 0) for value in second["metrics"].values()), 0)
        self.assertEqual(first['remaining'], ['publish'])
        self.assertEqual(second['remaining'], ['publish'])
        self.assertFalse(pipeline.read(self.root, second['run_id'])['completed']['verify']['gameplay_verified'])
        self.assertNotIn('unfinished', pipeline.operator_report(self.root, second))

    def test_authored_failure_reaches_operator_after_supported_stages_and_correction_has_new_baseline(self):
        first = self.run_pipeline()
        captured = history.latest(self.root)
        entry = next(row for row in model.rows(extraction.artifact(self.root, captured['models']))
                     if row['semantic']['kind'] == 'item')
        repo = self.root / 'repositories/items-equipment'
        repo.mkdir(parents=True)
        git(repo, 'init', '-q')
        git(repo, 'config', 'user.name', 'Wiki fixture')
        git(repo, 'config', 'user.email', 'wiki@example.invalid')
        path = repo / 'curated/stack.json'
        path.parent.mkdir()
        definition = {'schema_version': 1, 'entity': entry['entity_key'], 'title': 'Stack configuration',
                      'since': captured['snapshot_id'], 'scope': 'selected-data', 'code': [],
                      'text': ['Configured maximum stack: ', {'fact': 'stack'}],
                      'facts': {'stack': {'path': '/MaxStack', 'type': 'integer', 'max': 1}}}

        def commit():
            path.write_bytes(json_bytes(definition))
            git(repo, 'add', 'curated')
            git(repo, 'commit', '-qm', 'Change declared check')

        commit()
        failed = self.run_pipeline()
        saved = pipeline.read(self.root, failed['run_id'])
        self.assertEqual(saved['status'], 'git-release-ready')
        self.assertEqual(saved['previous_run'], first['run_id'])
        self.assertIn('release', saved['completed'])
        self.assertIn('curated-check-failed', pipeline.operator_report(self.root, failed))
        self.assertIn('ask how to proceed', pipeline.operator_report(self.root, failed))
        groups = [group for group in saved['exceptions']['groups'] if group['stage'] == 'curation']
        self.assertEqual(len(groups), 1)
        definition['facts']['stack']['max'] = 10
        commit()
        corrected = self.run_pipeline()
        resolved = pipeline.read(self.root, corrected['run_id'])
        self.assertEqual(resolved['previous_run'], failed['run_id'])
        self.assertIn(groups[0]['key'], resolved['exceptions']['resolved_since_previous'])
        self.assertFalse(any(group['stage'] == 'curation' for group in resolved['exceptions']['groups']))
        self.assertEqual(self.run_pipeline()['run_id'], corrected['run_id'])

    def test_cleanup_issue_is_reported_separately_after_supported_work(self):
        retained = {"reused": False, "removed_files": 0, "removed_bytes": 0,
                    "retained": [{"stage": "0123456789ab", "reason": "protected payload"}]}
        with patch.object(pipeline.release_retention, "run", return_value=retained):
            result = self.run_pipeline()
        saved = pipeline.read(self.root, result["run_id"])
        self.assertEqual(saved["status"], "git-release-ready")
        self.assertNotIn("protected payload", json.dumps(saved["exceptions"]))
        self.assertIn("Staging cleanup issue [0123456789ab]: protected payload", pipeline.operator_report(self.root, result))

    def test_reader_cache_issue_is_reported_after_supported_work_without_content_escalation(self):
        with patch.object(pipeline.reader_retention.os, "link", side_effect=OSError("protected reader cache")):
            result = self.run_pipeline()
        saved = pipeline.read(self.root, result["run_id"])
        self.assertEqual(saved["status"], "git-release-ready")
        self.assertNotIn("publish", saved["completed"])
        self.assertNotIn("protected reader cache", json.dumps(saved["exceptions"]))
        self.assertIn("Reader cache cleanup issue", pipeline.operator_report(self.root, result))
        self.assertIn("protected reader cache", pipeline.operator_report(self.root, result))

    def test_unowned_reader_staging_is_reported_by_name(self):
        retire = pipeline.reader_retention.staging.retire

        def unowned(folder, stage, current=None):
            if stage != "reader":
                return retire(folder, stage, current)
            return {"removed": [], "retained": [{"stage": "952369e7", "reason": "ownership record missing"}]}

        with patch.object(pipeline.reader_retention.staging, "retire", side_effect=unowned):
            result = self.run_pipeline()
        self.assertIn("Reader cache cleanup issue [952369e7]: ownership record missing",
                      pipeline.operator_report(self.root, result))

    def test_failure_preserves_last_success_and_reuses_completed_stages_on_retry(self):
        first = self.run_pipeline()
        before = self.latest().read_bytes()
        self.modify(MaxStack=19)
        with patch.object(pipeline.reader, "build", side_effect=RuntimeError("reader fault")):
            with self.assertRaisesRegex(ContractError, "stage project failed"):
                self.run_pipeline()
        self.assertEqual(before, self.latest().read_bytes())
        failure = json.loads(next((self.root / ".local/pipeline/failures").glob("*.json")).read_text())
        self.assertEqual(failure["kind"], "execution-failure")
        self.assertEqual(failure["failed_stage"], "project")
        self.assertEqual(set(failure["completed"]), {"register", "normalize", "identity"})
        retry = self.run_pipeline()
        saved = pipeline.read(self.root, retry["run_id"])
        self.assertEqual(saved["previous_run"], first["run_id"])
        self.assertEqual(saved["diff_base"], pipeline.read(self.root, first["run_id"])["source_commit"])
        self.assertTrue(retry["metrics"]["normalize"]["reused"])
        self.assertTrue(retry["metrics"]["identity"]["reused"])

    def test_failed_and_skipped_captures_keep_last_successful_diff_base(self):
        self.modify(NewUnparsedFeature=1)
        first = self.run_pipeline()
        self.modify(MaxStack=19)
        with patch.object(pipeline.reader, "build", side_effect=RuntimeError("reader fault")):
            with self.assertRaises(ContractError):
                self.run_pipeline()
        self.modify(MaxStack=20)
        result = pipeline.read(self.root, self.run_pipeline()["run_id"])
        self.assertEqual(result["diff_base"], pipeline.read(self.root, first["run_id"])["source_commit"])
        self.assertTrue(any(row["change"] == "unchanged" for row in result["exceptions"]["groups"]))

    def test_failure_at_final_promotion_reuses_prepared_receipt(self):
        first = self.run_pipeline()
        before = self.latest().read_bytes()
        self.modify(MaxStack=20)
        original = pipeline.write_changed

        def fail_pointer(path, data):
            if path == self.latest():
                raise OSError("pointer fault")
            return original(path, data)

        with patch.object(pipeline, "write_changed", side_effect=fail_pointer):
            with self.assertRaisesRegex(ContractError, "stage promote failed"):
                self.run_pipeline()
        self.assertEqual(before, self.latest().read_bytes())
        runs = list((self.root / ".local/pipeline/runs").glob("*.json"))
        self.assertEqual(len(runs), 2)
        prepared = next(path.stem for path in runs if path.stem != first["run_id"])
        self.assertEqual(self.run_pipeline()["run_id"], prepared)
        self.assertEqual(len(list((self.root / ".local/pipeline/runs").glob("*.json"))), 2)

    def test_corrupt_stage_output_is_not_hidden_by_pipeline_receipt(self):
        first = self.run_pipeline()
        before = self.latest().read_bytes()
        saved = pipeline.read(self.root, first["run_id"])
        extracted = extraction.read(self.root, saved["completed"]["normalize"]["run_id"])
        path = extraction.artifact(self.root, extracted["records"])
        path.write_bytes(b"modified")
        with self.assertRaisesRegex(ContractError, "artifact missing or modified"):
            self.run_pipeline()
        self.assertEqual(path.read_bytes(), b"modified")
        self.assertEqual(before, self.latest().read_bytes())

    def test_older_request_cannot_rewind_success(self):
        first = self.run_pipeline()
        old = pipeline.read(self.root, first["run_id"])["source_commit"]
        self.modify(MaxStack=20)
        self.run_pipeline()
        before = self.latest().read_bytes()
        git(self.source, "checkout", "--detach", old)
        with self.assertRaisesRegex(ContractError, "cannot rewind"):
            self.run_pipeline()
        self.assertEqual(before, self.latest().read_bytes())

    def test_dirty_source_is_execution_failure_before_any_content_work(self):
        (self.source / "unexpected.txt").write_text("user data")
        with self.assertRaisesRegex(ContractError, "stage register failed"):
            self.run_pipeline()
        self.assertFalse(self.latest().exists())
        failure = json.loads(next((self.root / ".local/pipeline/failures").glob("*.json")).read_text())
        self.assertEqual(failure["completed"], {})

    def test_update_entrypoint_rejects_a_concurrent_writer(self):
        (self.root / "project.json").write_bytes(json_bytes(test_extraction.PROJECT))
        with writer_lock(self.root):
            with self.assertRaisesRegex(ContractError, "Another wiki writer"):
                wiki.run(self.root, SimpleNamespace(command="update", source=str(self.source)))
        self.assertFalse(self.latest().exists())

    def test_changed_request_baseline_is_not_accepted_on_repeat(self):
        self.run_pipeline()
        self.modify(MaxStack=20)
        result = pipeline.read(self.root, self.run_pipeline()["run_id"])
        before = self.latest().read_bytes()
        path = self.root / f".local/pipeline/requests/{result['request_key']}.json"
        request = json.loads(path.read_text())
        request["previous_run"] = None
        path.write_bytes(json_bytes(request))
        with self.assertRaisesRegex(ContractError, "baseline differs"):
            self.run_pipeline()
        self.assertEqual(before, self.latest().read_bytes())

    def test_full_pipeline_commits_all_topics_despite_content_exceptions(self):
        self.release_patch.stop()
        workspace.initialize(self.root, test_extraction.PROJECT)
        for repo in test_extraction.PROJECT['repositories']:
            path = self.root / repo['path']
            git(path, 'config', 'user.name', 'Wiki fixture')
            git(path, 'config', 'user.email', 'wiki@example.invalid')
            git(path, 'add', '.')
            git(path, 'commit', '-m', 'Seed fixture')
        workspace.checkout_lock(self.root, test_extraction.PROJECT)
        self.modify(NewUnparsedFeature=1)
        project = json.loads(json.dumps(test_extraction.PROJECT))
        project['publication']['enabled'] = True
        workspace.checkout_lock(self.root, project)
        with patch.object(publication, 'run', side_effect=AssertionError('Unexpected publication')), \
                patch.object(github_pages, 'GitHubPages', side_effect=AssertionError('Unexpected live host')):
            result = pipeline.run(self.root, project, self.source)
        saved = pipeline.read(self.root, result['run_id'])
        released = pipeline.release.read(self.root, saved['wiki_release'])
        self.assertEqual(len(released['repositories']), 13)
        self.assertGreater(result['exception_groups'], 0)
        self.assertEqual(result['status'], 'git-release-ready')
        self.assertIsNone(publication.published(self.root))
        self.assertGreater(result['metrics']['retention']['removed_files'], 0)
        self.assertFalse(result['metrics']['retention']['retained'])
        self.assertTrue((self.root / 'repositories/items-equipment/site/reader.json').is_file())
        pipeline.release.verify(self.root, released)
        with patch.object(publication, 'run', side_effect=AssertionError('Unexpected publication')), \
                patch.object(github_pages, 'GitHubPages', side_effect=AssertionError('Unexpected live host')):
            repeated = pipeline.run(self.root, project, self.source)
            self.assertEqual(result['run_id'], repeated['run_id'])
            self.assertTrue(repeated['metrics']['retention']['reused'])


if __name__ == "__main__":
    unittest.main()
