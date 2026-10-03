"""Real independent Git repos exercise release history and interrupted commits."""

import copy
import json
import os
import subprocess
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from tests._support import cache_git_queries, fixture_dir

import test_reader
from wikibuild import git_transaction, reader, release, workspace
from wikibuild.storage import ContractError, git, json_bytes
from tools.check_release import check as independent_check


class _ModuleFixtures:
    """Imported release fixtures live until the current unittest module finishes."""
    addCleanup = staticmethod(unittest.addModuleCleanup)


_CHILD_TEMPLATE = None
_RELEASE_TEMPLATE = None
_PREPARED_TEMPLATE = None


class _FixtureCheckpoint(OSError):
    pass


def clone_fixture(test, template, label):
    """Copy a complete local release baseline, including independent Git objects."""
    target = ReleaseTests()
    target.root = fixture_dir(test, label)
    shutil.copytree(template.root, target.root, dirs_exist_ok=True)
    target.project = copy.deepcopy(template.project)
    target.candidate = copy.deepcopy(template.candidate)
    target.candidate['path'] = str(target.root / Path(template.candidate['path']).relative_to(template.root))
    target.fixture = test_reader.ReaderTests()
    target.fixture.root = target.root
    target.fixture.registry_path = target.root / 'presentation/fields.json'
    target.fixture.__dict__.update(copy.deepcopy({name: getattr(template.fixture, name)
        for name in ('project', 'a', 'b', 'c', 'old', 'new', 'runs')}))
    cache_git_queries(test, target.root)
    return target


def copy_children(root, project):
    global _CHILD_TEMPLATE
    if _CHILD_TEMPLATE is None or not _CHILD_TEMPLATE.exists():
        template = fixture_dir(_ModuleFixtures(), "children")
        workspace.initialize(template, project)
        for repo in project['repositories']:
            path = template / repo['path']
            git(path, 'config', 'user.name', 'Wiki fixture')
            git(path, 'config', 'user.email', 'wiki@example.invalid')
            git(path, 'add', '.')
            git(path, 'commit', '-m', 'Initialize fixture')
        # Publish the cache only after every child has been initialized.
        _CHILD_TEMPLATE = template
    shutil.copytree(_CHILD_TEMPLATE / 'repositories', root / 'repositories')


class ReleaseTests(unittest.TestCase):
    def test_native_nested_extra_ownership_is_unrecognized_and_kept(self):
        from wikibuild import staging
        unknown = self.root / ".local/rs" / ("f" * 32)
        unknown.mkdir(parents=True)
        value = {"schema_version": 1, "stage": "release", "attempt_id": unknown.name,
                 "created_utc": "2026-01-01T00:00:00+00:00", "state": "materializing"}
        data = (json.dumps(value, separators=(",", ":")).encode()[:-1]
                + b',"extra":' + b"[" * 500 + b"0" + b"]" * 500 + b"}")
        self.assertLess(len(data), staging.MAX_RECORD_BYTES)
        self.assertIsInstance(json.loads(data)["extra"], list)  # Native decoder, no substitutions.
        marker = unknown / staging.OWNER
        marker.write_bytes(data)
        self.run_release()
        self.assertEqual(marker.stat().st_size, len(data))
        self.assertEqual(marker.read_bytes(), data)
        with self.assertRaisesRegex(ContractError, "Unrecognized staging ownership record"):
            staging.record(unknown, "release")
        report = json.loads(unknown.parent.with_name(unknown.parent.name + "-retention.json").read_bytes())
        self.assertTrue(any(row["stage"] == unknown.name and "Unrecognized staging ownership record" in row["reason"]
                            for row in report["retained"]))
        completed = [path for path in unknown.parent.iterdir() if path != unknown
                     and staging.record(path, "release")[0]["state"] == "completed"]
        self.assertTrue(completed)
        self.assertTrue(all((path / staging.OWNER).stat().st_size <= staging.MAX_RECORD_BYTES for path in completed))

    def test_redirected_staging_root_is_refused_without_touching_target(self):
        from wikibuild import staging
        folder = self.root / ".local/rs"
        outside = self.root / "unrelated"
        outside.mkdir()
        for index in range(2):
            victim = outside / (str(index) * 32)
            victim.mkdir()
            (victim / staging.OWNER).write_bytes(json_bytes({
                "schema_version": 1, "stage": "release", "attempt_id": victim.name,
                "created_utc": f"2026-01-0{index + 1}T00:00:00+00:00", "state": "abandoned"}))
            (victim / "payload").write_bytes(b"outside the literal stage root")
        before = {path.relative_to(outside): path.read_bytes() for path in outside.rglob("*") if path.is_file()}
        folder.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(folder), str(outside)],
                                    capture_output=True, text=True)
            if result.returncode:
                self.skipTest("Cannot create staging root junction: " + result.stderr)
            self.addCleanup(folder.rmdir)
        else:
            try:
                folder.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Cannot create staging root symlink: {exc}")
            self.addCleanup(folder.unlink)
        with self.assertRaisesRegex(ContractError, "Redirected staging path"):
            self.run_release()
        after = {path.relative_to(outside): path.read_bytes() for path in outside.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        report = json.loads(folder.with_name(folder.name + "-retention.json").read_bytes())
        self.assertTrue(any("Redirected staging path" in row["reason"] for row in report["retained"]))


    def test_owned_preparation_crash_keeps_one_diagnostic_after_recovery(self):
        from wikibuild import release_output, staging
        original = release_output.Writer.add
        def crash(writer, *args, **kwargs):
            original(writer, *args, **kwargs)
            raise SystemExit("preparation crash")
        with patch.object(release_output.Writer, "add", crash):
            with self.assertRaises(SystemExit):
                self.run_release()
        folder = self.root / ".local/rs"
        failed = next(folder.iterdir())
        self.assertEqual(staging.record(failed, "release")[0]["state"], "materializing")
        self.assertTrue(any(path.is_file() and path.name != staging.OWNER for path in failed.rglob("*")))
        unknown = folder / "unknown"
        unknown.mkdir()
        result, _ = self.run_release()
        self.assertEqual(staging.record(failed, "release")[0]["state"], "abandoned")
        completed = next(path for path in folder.iterdir() if (path / staging.OWNER).exists()
                         and staging.record(path, "release")[0]["state"] == "completed")
        self.assertEqual(staging.record(completed, "release")[0]["state"], "completed")
        self.assertTrue((completed / "plan.json").exists())
        self.assertTrue(unknown.exists())
        self.assertEqual(self.run_release()[0], result)
        self.assertTrue(completed.exists())

    def test_post_preparation_failure_abandons_before_pending_journal(self):
        from wikibuild import staging
        original = reader.verify
        def fail_validation(*args, **kwargs):
            folder = self.root / ".local/rs"
            if folder.exists() and any((path / staging.OWNER).exists() for path in folder.iterdir()):
                raise SystemExit("post preparation crash")
            return original(*args, **kwargs)
        with patch.object(reader, "verify", side_effect=fail_validation):
            with self.assertRaises(SystemExit):
                self.run_release()
        folder = self.root / ".local/rs"
        failed = next(folder.iterdir())
        self.assertEqual(staging.record(failed, "release")[0]["state"], "materializing")
        self.assertFalse((self.root / ".local/releases/pending.json").exists())
        self.run_release()
        self.assertEqual(staging.record(failed, "release")[0]["state"], "abandoned")

    def test_consecutive_preparation_failures_leave_exactly_one_retained(self):
        from wikibuild import release_output, staging
        original = release_output.Writer.add
        def fail(writer, *args, **kwargs):
            original(writer, *args, **kwargs)
            raise OSError("preparation failed")
        folder = self.root / ".local/rs"
        previous = None
        for _ in range(5):
            with patch.object(release_output.Writer, "add", fail):
                with self.assertRaisesRegex(OSError, "preparation failed"):
                    self.run_release()
            failures = list(folder.iterdir())
            self.assertEqual(len(failures), 1)
            if previous is not None:
                self.assertFalse(previous.exists())
            previous = failures[0]
        failures = list(folder.iterdir())
        self.assertTrue(all(staging.record(path, "release")[0]["state"] == "abandoned" for path in failures))
        self.run_release()
        self.assertTrue(all(path.exists() for path in failures))

    def test_consecutive_post_preparation_failures_leave_exactly_one_retained(self):
        from wikibuild import staging
        original = reader.verify
        folder = self.root / ".local/rs"
        def fail(*args, **kwargs):
            if folder.exists() and any(staging.record(path, "release")[0]["state"] == "materializing"
                                       for path in folder.iterdir()):
                raise OSError("post preparation failed")
            return original(*args, **kwargs)
        previous = None
        for _ in range(5):
            with patch.object(reader, "verify", side_effect=fail):
                with self.assertRaisesRegex(OSError, "post preparation failed"):
                    self.run_release()
            failures = list(folder.iterdir())
            self.assertEqual(len(failures), 1)
            self.assertEqual(staging.record(failures[0], "release")[0]["state"], "abandoned")
            if previous is not None:
                self.assertFalse(previous.exists())
            previous = failures[0]


    def setUp(self, *, build_candidate=True):
        global _RELEASE_TEMPLATE, _PREPARED_TEMPLATE
        prepared = {'test_failure_after_ref_update_is_detected_as_completed_on_retry',
                    'test_failure_during_file_promotion_resumes_exact_prepared_commit',
                    'test_interrupted_transaction_refuses_unexpected_edits_and_modified_journal',
                    'test_resume_preserves_unrelated_staged_edits'}
        if self._testMethodName in prepared:
            if _PREPARED_TEMPLATE is None or not _PREPARED_TEMPLATE.root.exists():
                template = ReleaseTests()
                template.addCleanup = _ModuleFixtures().addCleanup
                template.setUp()
                with patch.object(git_transaction, 'promote', side_effect=_FixtureCheckpoint('prepared fixture')):
                    try:
                        template.run_release()
                    except _FixtureCheckpoint:
                        pass
                    else:
                        raise AssertionError('Fixture did not stop before promotion')
                _PREPARED_TEMPLATE = template
            cloned = clone_fixture(self, _PREPARED_TEMPLATE, 'prepared')
            self.root, self.project = cloned.root, cloned.project
            self.candidate, self.fixture = cloned.candidate, cloned.fixture
            return
        baselines = {'test_font_links_and_exact_bytes_survive_release_and_repeat',
                     'test_prior_release_data_and_runtime_remain_available_without_pack_duplication',
                     'test_reviewed_explanation_after_published_baseline_preserves_old_release_and_repeats',
                     'test_reviewed_successor_cannot_change_generated_outputs',
                     'test_failure_between_children_preserves_previous_release_then_resumes'}
        if self._testMethodName in baselines:
            if _RELEASE_TEMPLATE is None or not _RELEASE_TEMPLATE.root.exists():
                template = ReleaseTests()
                template.addCleanup = _ModuleFixtures().addCleanup
                template.setUp()
                template.run_release()
                _RELEASE_TEMPLATE = template
            cloned = clone_fixture(self, _RELEASE_TEMPLATE, 'released')
            self.root, self.project = cloned.root, cloned.project
            self.candidate, self.fixture = cloned.candidate, cloned.fixture
            return
        self.fixture = test_reader.ReaderTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.setUp()
        test_reader.install_guide(self.fixture)
        self.root = self.fixture.root
        cache_git_queries(self, self.root)
        self.project = copy.deepcopy(self.fixture.project)
        self.project['github_owner'] = 'wiki-fixture'
        for repo in self.project['repositories']:
            repo.update(path='repositories/' + repo['id'], role='hub' if repo['id'] == 'hub' else 'topic', github_name='Wiki-' + repo['id'])
        copy_children(self.root, self.project)
        self.candidate = None
        if build_candidate:
            workspace.checkout_lock(self.root, self.project)
            self.candidate = reader.build(self.root, self.project, self.fixture.runs, bases=release.bases(self.project))

    def run_release(self):
        return release.run(self.root, self.project, self.candidate)

    def heads(self):
        return {repo['id']: git(self.root / repo['path'], 'rev-parse', 'HEAD') for repo in self.project['repositories']}

    def test_cached_children_have_private_worktrees_and_git_objects(self):
        second = fixture_dir(self, 'copy')
        before = self.heads()
        with patch.object(workspace, 'initialize', side_effect=AssertionError('rebuilt template')):
            copy_children(second, self.project)
        path = self.root / 'repositories/items'
        (path / 'private.md').write_text('Private mutable fixture')
        git(path, 'add', '.')
        git(path, 'commit', '-m', 'Private mutation')
        for repo in self.project['repositories']:
            self.assertEqual(git(second / repo['path'], 'rev-parse', 'HEAD'), before[repo['id']])
            self.assertEqual(git(_CHILD_TEMPLATE / repo['path'], 'rev-parse', 'HEAD'), before[repo['id']])
        self.assertFalse((second / 'repositories/items/private.md').exists())
        commit = git(path, 'rev-parse', 'HEAD')
        obj = Path('.git/objects') / commit[:2] / commit[2:]
        self.assertTrue((path / obj).exists())
        self.assertFalse((second / 'repositories/items' / obj).exists())

    def new_candidate(self):
        self.project['official_links'] = [{'title': 'Fixture', 'url': 'https://example.invalid/'}]
        workspace.checkout_lock(self.root, self.project)
        self.candidate = reader.build(self.root, self.project, self.fixture.runs, bases=release.bases(self.project))

    def test_commits_are_exact_repeat_is_noop_and_authored_files_survive(self):
        (self.root / 'repositories/items/notes.md').write_text('Authored explanation')
        git(self.root / 'repositories/items', 'add', 'notes.md')
        git(self.root / 'repositories/items', 'commit', '-m', 'Author notes')
        workspace.checkout_lock(self.root, self.project)
        before = self.heads()
        result, metrics = self.run_release()
        self.assertFalse(metrics['reused'])
        self.assertNotEqual(before, self.heads())
        self.assertEqual(result['publication'], 'not-published')
        release.verify(self.root, result)
        audit = independent_check(self.root)
        self.assertEqual(audit['repositories'], len(self.project['repositories']))
        workspace.checkout_lock(self.root, self.project, check=True)
        latest = self.root / 'releases/latest.json'
        stamp = latest.stat().st_mtime_ns
        heads = self.heads()
        again, metrics = self.run_release()
        self.assertTrue(metrics['reused'])
        self.assertEqual(again, result)
        self.assertEqual(heads, self.heads())
        self.assertEqual(stamp, latest.stat().st_mtime_ns)
        self.assertEqual((self.root / 'repositories/items/notes.md').read_text(), 'Authored explanation')
        candidate_index = json.loads((Path(self.candidate['path']) / 'items/snapshots' /
                                      (self.fixture.new['snapshot_id'] + '.json')).read_bytes())
        self.assertIn('guides/capture.md', (self.root / 'repositories/hub/reference/index.md').read_text())
        self.assertTrue((self.root / 'repositories/hub/reference/guides/capture.md').is_file())
        for kind, topic in (('cards', 'items'), ('player', 'loot'), ('guides', 'hub')):
            with self.subTest(kind=kind):
                candidate_index = json.loads((Path(self.candidate['path']) / topic / 'snapshots' /
                                              (self.fixture.new['snapshot_id'] + '.json')).read_bytes())
                pack = self.root / 'repositories' / topic / 'site' / candidate_index[kind][0]['path']
                original = pack.read_bytes()
                pack.write_bytes(original + b' ')
                with self.assertRaises(AssertionError):
                    independent_check(self.root)
                pack.write_bytes(original)

    def test_font_links_and_exact_bytes_survive_release_and_repeat(self):
        result, _ = self.run_release()
        candidate = Path(self.candidate["path"])
        fonts = json.loads((candidate / "hub/reader.json").read_bytes())["fonts"]
        folder = fonts["base"].removeprefix(release.bases(self.project)["hub"])
        for name in fonts["files"]:
            original = (Path(reader.__file__).parent / "web/fonts" / name).read_bytes()
            self.assertEqual((self.root / "repositories/hub/site" / folder / name).read_bytes(),
                             original if name.endswith(".woff2") else original.replace(b"\r\n", b"\n"))
        for repo in self.project["repositories"]:
            for shell in (self.root / repo["path"] / "site").rglob("*.html"):
                self.assertIn('href="' + fonts["base"] + 'fonts.css"', shell.read_text())
        self.assertEqual(independent_check(self.root)["status"], "passed")
        before = self.heads()
        again, metrics = self.run_release()
        self.assertTrue(metrics["reused"])
        self.assertEqual(again, result)
        self.assertEqual(self.heads(), before)

    def test_issue_templates_are_hub_only_byte_exact_and_reconcile_removals(self):
        source = self.root / "presentation/issue-templates"
        source.mkdir()
        accuracy = source / "accuracy.yml"
        accuracy.write_bytes(b"name: Accuracy\r\ndescription: Wrong fact\r\nbody:\r\n  - type: input\r\n")
        config = source / "config.yml"
        config.write_bytes(b"blank_issues_enabled: true\r\n")
        self.candidate = reader.build(self.root, self.project, self.fixture.runs, bases=release.bases(self.project))
        first, _ = self.run_release()
        hub = self.root / "repositories/hub/.github/ISSUE_TEMPLATE"
        self.assertEqual((hub / "accuracy.yml").read_bytes(), accuracy.read_bytes())
        self.assertEqual((hub / "config.yml").read_bytes(), config.read_bytes())
        self.assertIn(b"/.github/ISSUE_TEMPLATE/*.yml -text", (self.root / "repositories/hub/.gitattributes").read_bytes())
        for topic in ("items", "loot"):
            self.assertFalse((self.root / "repositories" / topic / ".github/ISSUE_TEMPLATE").exists())
        self.assertIn(".github/ISSUE_TEMPLATE/accuracy.yml", release.owned(self.root / "repositories/hub"))
        accuracy.write_bytes(accuracy.read_bytes().replace(b"Accuracy", b"Correction"))
        site_problem = source / "site-problem.yml"
        site_problem.write_bytes(b"name: Site problem\ndescription: Broken page\nbody:\n  - type: textarea\n")
        self.candidate = reader.build(self.root, self.project, self.fixture.runs, bases=release.bases(self.project))
        second, _ = self.run_release()
        self.assertNotEqual(first["release_id"], second["release_id"])
        self.assertEqual((hub / "accuracy.yml").read_bytes(), accuracy.read_bytes())
        self.assertEqual((hub / "site-problem.yml").read_bytes(), site_problem.read_bytes())
        accuracy.unlink()
        self.candidate = reader.build(self.root, self.project, self.fixture.runs, bases=release.bases(self.project))
        third, _ = self.run_release()
        self.assertNotEqual(second["release_id"], third["release_id"])
        self.assertFalse((hub / "accuracy.yml").exists())
        self.assertNotIn(".github/ISSUE_TEMPLATE/accuracy.yml", release.owned(self.root / "repositories/hub"))
        heads = self.heads()
        self.assertTrue(self.run_release()[1]["reused"])
        self.assertEqual(self.heads(), heads)
        self.assertEqual(independent_check(self.root)["status"], "passed")

    def test_issue_template_change_after_reader_build_refuses_release(self):
        source = self.root / "presentation/issue-templates"
        source.mkdir()
        template = source / "accuracy.yml"
        template.write_bytes(b"name: Accuracy\ndescription: Wrong fact\nbody:\n")
        self.candidate = reader.build(self.root, self.project, self.fixture.runs, bases=release.bases(self.project))
        template.write_bytes(template.read_bytes().replace(b"Accuracy", b"Correction"))
        with self.assertRaisesRegex(ContractError, "Issue template inputs changed after reader build"):
            self.run_release()
        self.assertFalse((self.root / "releases/latest.json").exists())

    def test_prior_release_data_and_runtime_remain_available_without_pack_duplication(self):
        first, _ = self.run_release()
        folder = self.root / 'repositories/items/site'
        data = {p.name: p.read_bytes() for p in (folder / 'data').iterdir()}
        old_config = (folder / 'releases' / (first['release_id'] + '.json')).read_bytes()
        self.new_candidate()
        second, _ = self.run_release()
        self.assertNotEqual(first['release_id'], second['release_id'])
        self.assertEqual(old_config, (folder / 'releases' / (first['release_id'] + '.json')).read_bytes())
        self.assertEqual(data, {p.name: p.read_bytes() for p in (folder / 'data').iterdir()})
        config = json.loads(old_config)
        self.assertTrue((folder / config['runtime']['js']).is_file())
        for record in config['snapshots'].values():
            self.assertTrue((folder / record['path']).is_file())
        self.assertEqual(independent_check(self.root)['historical_configs'], 2 * len(self.project['repositories']))

    def test_reviewed_explanation_after_published_baseline_preserves_old_release_and_repeats(self):
        first, _ = self.run_release()
        repo = self.root / 'repositories/items'
        path = repo / 'curated/weight.json'
        path.parent.mkdir()
        path.write_bytes(json_bytes({'schema_version': 1, 'entity': self.fixture.a,
            'title': 'Configured weight', 'since': self.fixture.old['snapshot_id'],
            'scope': 'selected-data', 'facts': {'weight': {'path': '/weight', 'type': 'integer'}},
            'text': ['Configured weight: ', {'fact': 'weight'}], 'code': []}))
        git(repo, 'add', 'curated')
        git(repo, 'commit', '-qm', 'Reviewed explanation')
        authored_commit = git(repo, 'rev-parse', 'HEAD')
        self.candidate = reader.build(self.root, self.project, self.fixture.runs, bases=release.bases(self.project))
        with self.assertRaises(ContractError):
            self.run_release()  # An unadopted child commit remains drift.
        workspace.checkout_lock(self.root, self.project)
        with self.assertRaisesRegex(ContractError, 'Release checkout differs'):
            release.verify(self.root, first)  # Publication of the old release stays strict.
        second, _ = self.run_release()
        self.assertNotEqual(first['release_id'], second['release_id'])
        self.assertEqual(git(repo, 'rev-parse', 'HEAD^'), authored_commit)
        release.verify(self.root, first, check_checkout=False)
        release.verify(self.root, second)
        self.assertEqual(self.run_release()[0], second)
        self.assertEqual(independent_check(self.root)['historical_configs'], 2 * len(self.project['repositories']))

    def test_reviewed_successor_cannot_change_generated_outputs(self):
        first, _ = self.run_release()
        repo = self.root / 'repositories/items'
        path = repo / 'README.md'
        path.write_text('Changed generated content')
        git(repo, 'add', 'README.md')
        git(repo, 'commit', '-qm', 'Generated output drift')
        workspace.checkout_lock(self.root, self.project)
        with self.assertRaises(ContractError):
            release.verify(self.root, first, reviewed_project=self.project)
        self.assertEqual(path.read_text(), 'Changed generated content')

    def test_failure_between_children_preserves_previous_release_then_resumes(self):
        first, _ = self.run_release()
        self.new_candidate()
        original = git_transaction.promote
        count = 0

        def fail_second(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('interrupted between repositories')
            return original(*args)

        with patch.object(git_transaction, 'promote', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                self.run_release()
        self.assertEqual(json.loads((self.root / 'releases/latest.json').read_text())['release_id'], first['release_id'])
        result, _ = self.run_release()
        self.assertNotEqual(result['release_id'], first['release_id'])
        release.verify(self.root, result)

    def test_failure_after_ref_update_is_detected_as_completed_on_retry(self):
        original = git_transaction.git
        failed = False

        def fail_after_ref(path, *args):
            nonlocal failed
            value = original(path, *args)
            if args[0] == 'update-ref' and not failed:
                failed = True
                raise OSError('after ref update')
            return value

        with patch.object(git_transaction, 'git', side_effect=fail_after_ref):
            with self.assertRaisesRegex(OSError, 'after ref'):
                self.run_release()
        before = self.heads()
        result, _ = self.run_release()
        self.assertEqual(before['items'], result['repositories']['items']['commit'])
        release.verify(self.root, result)

    def test_failure_during_file_promotion_resumes_exact_prepared_commit(self):
        original = git_transaction.os.replace
        count = 0

        def fail_once(src, dst):
            nonlocal count
            if 'release-writes' in str(src):
                count += 1
                if count == 3:
                    raise OSError('during file promotion')
            return original(src, dst)

        with patch.object(git_transaction.os, 'replace', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'during file'):
                self.run_release()
        self.assertFalse((self.root / 'releases/latest.json').exists())
        result, _ = self.run_release()
        release.verify(self.root, result)

    def test_unknown_ignored_file_and_dirty_checkout_are_preserved(self):
        folder = self.root / 'repositories/items/site'
        folder.mkdir()
        unknown = folder / 'authored.local.json'
        unknown.write_text('private authored data')
        before = self.heads()
        with self.assertRaisesRegex(ContractError, 'Unknown file'):
            self.run_release()
        self.assertEqual(before, self.heads())
        self.assertEqual(unknown.read_text(), 'private authored data')
        unknown.unlink()
        note = self.root / 'repositories/items/README.md'
        note.write_text('User editing')
        with self.assertRaisesRegex(ContractError, 'dirty'):
            self.run_release()
        self.assertEqual(note.read_text(), 'User editing')

    def test_interrupted_transaction_refuses_unexpected_edits_and_modified_journal(self):
        with patch.object(git_transaction, 'promote', side_effect=OSError('stop')):
            with self.assertRaises(OSError):
                self.run_release()
        pointer = json.loads((self.root / '.local/releases/pending.json').read_text())
        plan = self.root / pointer['stage'] / 'plan.json'
        plan.write_bytes(plan.read_bytes() + b' ')
        with self.assertRaisesRegex(ContractError, 'journal was modified'):
            self.run_release()
        self.assertFalse((self.root / 'releases/latest.json').exists())

    def test_resume_preserves_unrelated_staged_edits(self):
        with patch.object(git_transaction, 'promote', side_effect=OSError('stop')):
            with self.assertRaises(OSError):
                self.run_release()
        path = self.root / 'repositories/items'
        before = self.heads()
        note = path / 'README.md'
        note.write_text('User change while stopped')
        git(path, 'add', 'README.md')
        with self.assertRaisesRegex(ContractError, 'index changed'):
            self.run_release()
        self.assertEqual(before, self.heads())
        self.assertEqual(note.read_text(), 'User change while stopped')


if __name__ == '__main__':
    unittest.main()
