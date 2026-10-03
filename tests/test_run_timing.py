"""Command receipts cover failures, watchdog exits and isolated fake publication."""

import copy
import io
import itertools
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_pipeline
import test_publication
import wiki
from wikibuild import manifest, pipeline, publication, run_timing
from wikibuild.storage import ContractError, json_bytes


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = {"schema": "humanhost.capture-timing.v1", "started_at": "2026-10-03T00:00:00Z",
           "finished_at": "2026-10-03T00:00:08Z", "seconds": 8, "outcome": "reused", "error": None,
           "output_path": "source", "output_commit": "a" * 40, "game": "HumanHost",
           "phases": [{"name": "capture", "seconds": 8, "outcome": "reused"}], "assemblies": []}


class TimingTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".local/t"
        parent.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def records(self):
        return list((self.root / ".local/runs").glob("*.json"))

    def test_success_failure_and_repeat_are_exclusive_records(self):
        args = SimpleNamespace(command="update", source="fixture", capture_timing=None)

        def succeed(root, project, source, **kwargs):
            kwargs["timing_sink"].enter("register")
            kwargs["timing_sink"].enter("release")
            return {"release_id": "a" * 64}

        with patch.object(manifest, "load", return_value={}), patch.object(pipeline, "run", side_effect=succeed):
            first = wiki.run(self.root, args)
            before = self.records()[0].read_bytes()
            self.assertEqual(wiki.run(self.root, args), first)
        self.assertEqual(len(self.records()), 2)
        self.assertEqual(self.records()[0].read_bytes(), before)
        saved = json.loads(before)
        self.assertEqual(saved["outcome"], "succeeded")
        self.assertEqual([row["outcome"] for row in saved["stages"]], ["succeeded", "succeeded"])

        def fail(root, project, source, **kwargs):
            kwargs["timing_sink"].enter("register")
            kwargs["timing_sink"].enter("normalize")
            raise ContractError("fixture failure")

        with patch.object(manifest, "load", return_value={}), patch.object(pipeline, "run", side_effect=fail):
            with self.assertRaisesRegex(ContractError, "fixture failure"):
                wiki.run(self.root, args)
        failed = json.loads(self.records()[-1].read_bytes())
        self.assertEqual(failed["outcome"], "failed")
        self.assertEqual(failed["stages"][-1]["outcome"], "failed")
        self.assertFalse(list((self.root / ".local/runs").glob("*.tmp")))

    def test_capture_validates_required_fields_types_and_warns_once(self):
        receipt = self.root / "capture.json"
        receipt.write_bytes(json_bytes(CAPTURE))
        self.assertEqual(run_timing.capture(receipt)["seconds"], 8)
        invalid = []
        for key in CAPTURE:
            missing = copy.deepcopy(CAPTURE)
            missing.pop(key)
            invalid.append(missing)
        for key, value in (("schema", "wrong"), ("seconds", True), ("seconds", -1),
                           ("seconds", float("nan")), ("phases", {}), ("game", []), ("error", {}),
                           ("output_commit", 3), ("outcome", "unknown"), ("started_at", "yesterday"),
                           ("assemblies", [{"name": "x", "seconds": False, "outcome": "succeeded"}])):
            wrong = copy.deepcopy(CAPTURE)
            wrong[key] = value
            invalid.append(wrong)
        for value in invalid:
            with self.subTest(value=value):
                receipt.write_bytes(json_bytes(value))
                stderr = io.StringIO()
                with patch.object(run_timing.sys, "stderr", stderr):
                    self.assertIsNone(run_timing.capture(receipt))
                self.assertEqual(stderr.getvalue().count("WARNING:"), 1)

    def test_invalid_or_missing_capture_continues_update(self):
        for data in (None, "{broken"):
            receipt = self.root / "bad.json"
            if data:
                receipt.write_text(data)
            stderr = io.StringIO()
            with patch.object(manifest, "load", return_value={}), patch.object(pipeline, "run", return_value={"release_id": "r"}), \
                    patch.object(run_timing.sys, "stderr", stderr):
                result = wiki.run(self.root, SimpleNamespace(command="update", source="fixture", capture_timing=receipt))
            self.assertEqual(result["release_id"], "r")
            self.assertEqual(stderr.getvalue().count("WARNING:"), 1)
            self.assertIsNone(json.loads(self.records()[-1].read_bytes())["capture"])

    def test_write_failure_and_exclusive_collision_do_not_change_outcome(self):
        recorder = run_timing.Recorder(self.root, "update")
        with patch.object(run_timing.os, "link", side_effect=OSError("protected")), \
                patch.object(run_timing.sys, "stderr", io.StringIO()) as stderr:
            recorder.finish("succeeded")
        self.assertEqual(recorder.record["outcome"], "succeeded")
        self.assertEqual(stderr.getvalue().count("WARNING:"), 1)
        self.assertFalse(self.records())
        self.assertFalse(list((self.root / ".local/runs").glob("*.tmp")))
        record = recorder.record
        with patch.object(run_timing.uuid, "uuid4", return_value=SimpleNamespace(hex="12345678")), \
                patch.object(run_timing, "datetime") as clock:
            clock.now.return_value.strftime.return_value = "20261003T000000.000000Z"
            path = run_timing.save(self.root, record)
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                run_timing.save(self.root, {**record, "outcome": "failed"})
            self.assertEqual(path.read_bytes(), before)

    def test_watchdog_keeps_active_stage_and_only_one_record(self):
        recorder = run_timing.Recorder(self.root, "update")
        recorder.enter("normalize")
        with patch.object(wiki.threading, "Timer") as timer, patch.object(wiki.sys, "stderr", io.StringIO()):
            stop = unittest.mock.Mock()
            wiki.deadline(2, "update", stop=stop, timing=recorder)
            timer.call_args.args[1]()
        stop.assert_called_once_with(124)
        recorder.finish("failed")
        self.assertEqual(len(self.records()), 1)
        saved = json.loads(self.records()[0].read_bytes())
        self.assertEqual(saved["outcome"], "timed-out")
        self.assertEqual(saved["stages"][0]["outcome"], "timed-out")

    def test_blocked_timing_cannot_defeat_watchdog_exit(self):
        release = threading.Event()
        entered = threading.Event()
        def blocked(*args):
            entered.set()
            release.wait(5)
        recorder = run_timing.Recorder(self.root, "update")
        try:
            with patch.object(recorder, "finish", side_effect=blocked), patch.object(wiki.threading, "Timer") as timer, \
                    patch.object(wiki.sys, "stderr", io.StringIO()):
                stop = unittest.mock.Mock()
                wiki.deadline(2, "update", stop=stop, timing=recorder)
                timer.call_args.args[1]()
                self.assertTrue(entered.is_set())
                stop.assert_called_once_with(124)
        finally:
            release.set()

    def test_timing_cli_is_read_only_and_orders_commands_together(self):
        run_timing.Recorder(self.root, "update").finish("succeeded")
        run_timing.Recorder(self.root, "publish", "r").finish("failed")
        before = {path: path.read_bytes() for path in self.records()}
        output = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with patch.object(wiki.sys, "argv", ["wiki.py", "timing", "--last", "2"]), \
                patch.object(wiki, "__file__", str(self.root / "wiki.py")), \
                patch.object(wiki.sys, "stdout", output), patch.object(manifest, "load", side_effect=AssertionError("Read-only")):
            self.assertEqual(wiki.main(), 0)
        output.flush()
        text = output.buffer.getvalue().decode()
        self.assertLess(text.index("Run timing: publish"), text.index("Run timing: update"))
        self.assertIn("Combined total", text)
        self.assertIn("Largest items", text)
        self.assertEqual({path: path.read_bytes() for path in self.records()}, before)
        with self.assertRaisesRegex(ValueError, "positive"):
            run_timing.latest(self.root, 0)

    def test_command_end_prints_one_table_for_success_and_failure(self):
        receipt = self.root / "capture.json"
        receipt.write_bytes(json_bytes(CAPTURE))
        for command in ("update", "publish"):
            for failure in (False, True):
                with self.subTest(command=command, failure=failure):
                    output = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
                    argv = (["wiki.py", "update", "--operator-report", "--capture-timing", str(receipt)]
                            if command == "update" else ["wiki.py", "publish", "--release", "r"])
                    def execute(root, args, timing):
                        timing.enter("fixture")
                        if failure:
                            raise ContractError("fixture failure")
                        return {"release_id": "r", "timings": {"fixture": 2}}
                    with patch.object(wiki.sys, "argv", argv), patch.object(wiki, "__file__", str(self.root / "wiki.py")), \
                            patch.object(wiki.sys, "stdout", output), patch.object(wiki.sys, "stderr", io.StringIO()), \
                            patch.object(wiki, "_run", side_effect=execute), \
                            patch.object(pipeline, "operator_report", return_value="Operator report\n"):
                        self.assertEqual(wiki.main(), 1 if failure else 0)
                    output.flush()
                    rendered = output.buffer.getvalue().decode()
                    self.assertEqual(rendered.count("Run timing:"), 1)
                    self.assertIn("Combined total", rendered)
                    if command == "update":
                        self.assertIn("capture: capture", rendered)

    def test_publish_watchdog_includes_active_pages_wait(self):
        recorder = run_timing.Recorder(self.root, "publish", "r")
        row = publication.repository_timing()
        recorder.publication = run_timing.Values({"repositories": {"items": row}, "rollback": {},
                                                  "phases": run_timing.Values()})
        with publication.measure(recorder.publication, "gate"):
            pass
        with publication.measure(recorder.publication["phases"], "topics-1"), publication.measure(row, "pages_build"):
            record = recorder.finish("timed-out")
        rows = {row["name"]: row for row in record["stages"]}
        self.assertEqual(rows["gate"]["outcome"], "succeeded")
        self.assertEqual(rows["topics-1"]["outcome"], "timed-out")
        self.assertEqual(rows["items: Pages wait"]["outcome"], "timed-out")
        self.assertGreaterEqual(rows["items: Pages wait"]["seconds"], 0)


class PipelineTimingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_pipeline.PipelineTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.source = self.fixture.root, self.fixture.source
        from test_extraction import PROJECT
        (self.root / "project.json").write_bytes(json_bytes(PROJECT))

    def test_capture_and_timing_do_not_change_request_run_or_release_identity(self):
        receipt = self.root / "capture.json"
        receipt.write_bytes(json_bytes(CAPTURE))
        args = SimpleNamespace(command="update", source=str(self.source), capture_timing=receipt)
        first = wiki.run(self.root, args)
        saved = pipeline.read(self.root, first["run_id"])
        request = self.root / f".local/pipeline/requests/{saved['request_key']}.json"
        before = request.read_bytes()
        receipt.write_bytes(json_bytes({**CAPTURE, "seconds": 500, "phases": []}))
        second = wiki.run(self.root, args)
        third = wiki.run(self.root, SimpleNamespace(command="update", source=str(self.source)))
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["run_id"], third["run_id"])
        self.assertEqual(first["release_id"], second["release_id"])
        self.assertEqual(request.read_bytes(), before)
        self.assertNotIn("capture", saved)
        files = sorted((self.root / ".local/runs").glob("*.json"))
        self.assertEqual(len(files), 3)
        self.assertEqual(json.loads(files[0].read_bytes())["capture"]["seconds"], 8)
        self.assertEqual(json.loads(files[1].read_bytes())["capture"]["seconds"], 500)


class PublishTimingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_publication.PublicationTests()
        parent = ROOT / ".local/t"
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory
        with patch.object(tempfile, "TemporaryDirectory", side_effect=lambda **kwargs: temporary(dir=parent, **kwargs)):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def invoke(self):
        original = publication.run
        def fake(*args, **kwargs):
            return original(*args, **kwargs, host=self.fixture.host)
        with patch.object(manifest, "load", return_value=self.fixture.project), \
                patch.object(publication, "run", side_effect=fake), \
                patch.object(publication.github_pages, "GitHubPages", side_effect=AssertionError("Live host forbidden")):
            return wiki.run(self.root, SimpleNamespace(command="publish", release=self.fixture.manifest["release_id"]))

    def test_publish_record_has_gate_wall_phases_and_repository_sums(self):
        with patch.object(publication, "perf_counter", side_effect=itertools.count()):
            result = self.invoke()
        record = json.loads(next((self.root / ".local/runs").glob("*.json")).read_bytes())
        rows = {row["name"]: row for row in record["stages"]}
        self.assertEqual(rows["gate"]["seconds"], result["metrics"]["timing"]["gate"])
        self.assertIn("prepare", rows)
        self.assertIn("topics-1", rows)
        self.assertIn("hub", rows)
        for name, timing in result["metrics"]["timing"]["repositories"].items():
            self.assertEqual(rows[f"{name}: Pages wait"]["seconds"], timing["pages_build"])
            self.assertEqual(rows[f"{name}: push"]["seconds"], timing["push_main"] + timing["push_pages"])
            self.assertEqual(rows[f"{name}: verify"]["seconds"], timing["verify"])
            self.assertEqual(rows[f"{name}: Pages wait"]["basis"], "repository-sum")
        self.assertEqual(record["release_id"], result["release_id"])
        self.assertNotIn("timing", json.dumps(publication.published(self.root)))

    def test_failed_gate_still_records_without_constructing_host(self):
        with patch.object(publication.publish_gate, "check", side_effect=ContractError("gate refused")):
            with self.assertRaisesRegex(ContractError, "gate refused"):
                self.invoke()
        record = json.loads(next((self.root / ".local/runs").glob("*.json")).read_bytes())
        self.assertEqual(record["outcome"], "failed")
        self.assertEqual(record["stages"][0]["name"], "gate")
        self.assertEqual(record["stages"][0]["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
