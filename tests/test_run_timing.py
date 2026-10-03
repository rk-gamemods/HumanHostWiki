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
from wikibuild import manifest, pipeline, publication, release, run_timing, workspace
from wikibuild.storage import ContractError, git, json_bytes


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = {"schema": "humanhost.capture-timing.v1", "started_at": "2026-10-03T00:00:00Z",
           "finished_at": "2026-10-03T00:00:08Z", "seconds": 8, "outcome": "reused", "error": None,
           "output_path": "source", "output_commit": "a" * 40, "game": "HumanHost",
           "phases": [{"name": "capture", "seconds": 8, "outcome": "reused"}], "assemblies": []}


class ObservedLock:
    """Expose contending attempts without sleeps or relying on thread scheduling."""
    def __init__(self):
        self.lock = threading.RLock()
        self.attempted = threading.Event()

    def __enter__(self):
        if threading.current_thread().name == "transition":
            self.attempted.set()
        self.lock.acquire()
        return self

    def __exit__(self, *args):
        self.lock.release()


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

    def test_snapshot_serializes_observation_start_and_stop(self):
        for action in ("start", "stop"):
            with self.subTest(action=action):
                values = run_timing.Values({"stage": 0.0})
                values.lock = ObservedLock()
                sampled, release_snapshot, entered, release_stage = (threading.Event() for _ in range(4))
                counter = itertools.count()
                rows, failures = [], []
                def clock():
                    seconds = next(counter)
                    if threading.current_thread().name == "snapshot":
                        sampled.set()
                        if not release_snapshot.wait(5):
                            raise AssertionError("Snapshot was not released")
                    return seconds
                def start():
                    try:
                        with publication.measure(values, "stage"):
                            entered.set()
                            if not release_stage.wait(5):
                                raise AssertionError("Stage was not released")
                    except BaseException as exc:
                        failures.append(exc)
                def snapshot():
                    try:
                        rows.extend(values.rows())
                    except BaseException as exc:
                        failures.append(exc)
                stage = threading.Thread(target=start, name="transition")
                observer = threading.Thread(target=snapshot, name="snapshot")
                with patch.object(run_timing, "perf_counter", side_effect=clock), \
                        patch.object(publication, "perf_counter", side_effect=clock):
                    try:
                        if action == "stop":
                            stage.start()
                            self.assertTrue(entered.wait(2))
                            values.lock.attempted.clear()
                        observer.start()
                        self.assertTrue(sampled.wait(2))
                        if action == "start":
                            stage.start()
                        else:
                            release_stage.set()
                        self.assertTrue(values.lock.attempted.wait(2), "Transition must contend on the snapshot lock")
                        release_snapshot.set()
                        observer.join(2)
                        self.assertFalse(observer.is_alive())
                        if action == "start":
                            self.assertTrue(entered.wait(2))
                        self.assertGreaterEqual(rows[0]["seconds"], 0)
                        self.assertEqual(rows[0]["seconds"], 0 if action == "start" else 1)
                    finally:
                        release_snapshot.set()
                        release_stage.set()
                        observer.join(2)
                        if stage.ident is not None:
                            stage.join(2)
                    self.assertFalse(failures, failures)
                    self.assertEqual(values.rows()[0]["seconds"], 1 if action == "start" else 2)

    def test_pipeline_transition_cannot_race_final_snapshot(self):
        sampled, release_snapshot = threading.Event(), threading.Event()
        lock = ObservedLock()
        counter = itertools.count()
        failures = []
        def clock():
            seconds = next(counter)
            if threading.current_thread().name == "snapshot":
                sampled.set()
                if not release_snapshot.wait(5):
                    raise AssertionError("Final snapshot was not released")
            return seconds
        def finalize():
            try:
                recorder.finish("succeeded")
            except BaseException as exc:
                failures.append(exc)
        with patch.object(run_timing, "perf_counter", side_effect=clock):
            recorder = run_timing.Recorder(self.root, "update")
            recorder.lock = recorder.stages.lock = lock
            recorder.enter("register")
            observer = threading.Thread(target=finalize, name="snapshot")
            transition = threading.Thread(target=lambda: recorder.enter("normalize"), name="transition")
            try:
                observer.start()
                self.assertTrue(sampled.wait(2))
                transition.start()
                self.assertTrue(lock.attempted.wait(2), "Stage transition must use the finalization lock")
            finally:
                release_snapshot.set()
                observer.join(2)
                if transition.ident is not None:
                    transition.join(2)
            self.assertFalse(failures, failures)
            self.assertEqual([row["name"] for row in recorder.record["stages"]], ["register"])
            self.assertTrue(all(row["seconds"] >= 0 for row in recorder.record["stages"]))

    def test_success_claim_prevents_timeout_even_while_save_is_blocked(self):
        saving, release_save = threading.Event(), threading.Event()
        recorder = run_timing.Recorder(self.root, "update")
        original = run_timing.save
        def blocked_save(*args):
            saving.set()
            if not release_save.wait(5):
                raise AssertionError("Save was not released")
            return original(*args)
        finalizer = threading.Thread(target=lambda: recorder.finish("succeeded"))
        with patch.object(run_timing, "save", side_effect=blocked_save), patch.object(wiki.threading, "Timer") as timer, \
                patch.object(wiki.sys, "stderr", io.StringIO()):
            stop = unittest.mock.Mock()
            wiki.deadline(2, "update", stop=stop, timing=recorder)
            try:
                finalizer.start()
                self.assertTrue(saving.wait(2))
                timer.call_args.args[1]()
                stop.assert_not_called()
                self.assertTrue(finalizer.is_alive())
            finally:
                release_save.set()
                finalizer.join(2)
        self.assertEqual(json.loads(self.records()[0].read_bytes())["outcome"], "succeeded")

    def test_expiry_claim_wins_before_delayed_writer_and_concurrent_completion(self):
        writer_ready, release_writer, saving, release_save, stopped = (threading.Event() for _ in range(5))
        recorder = run_timing.Recorder(self.root, "update")
        original_save, original_thread = run_timing.save, threading.Thread
        writers = []
        def blocked_save(*args):
            saving.set()
            if not release_save.wait(5):
                raise AssertionError("Save was not released")
            return original_save(*args)
        class DelayedWriter(original_thread):
            def run(self):
                writer_ready.set()
                release_writer.wait(5)
                super().run()
        def writer(*args, **kwargs):
            thread = DelayedWriter(*args, **kwargs)
            writers.append(thread)
            return thread
        with patch.object(run_timing, "save", side_effect=blocked_save), patch.object(wiki.threading, "Timer") as timer, \
                patch.object(wiki.threading, "Thread", side_effect=writer), patch.object(wiki.sys, "stderr", io.StringIO()):
            stop = unittest.mock.Mock(side_effect=lambda code: stopped.set())
            wiki.deadline(2, "update", stop=stop, timing=recorder)
            expiry = original_thread(target=timer.call_args.args[1])
            finalizer = original_thread(target=lambda: recorder.finish("succeeded"))
            try:
                expiry.start()
                self.assertTrue(writer_ready.wait(2))
                finalizer.start()
                self.assertTrue(saving.wait(2))
                release_writer.set()
                self.assertTrue(stopped.wait(2), "The watchdog must exit while finalization is still blocked")
                stop.assert_called_once_with(124)
                self.assertTrue(finalizer.is_alive())
                self.assertEqual(recorder.record["outcome"], "timed-out")
            finally:
                release_writer.set()
                release_save.set()
                expiry.join(2)
                if finalizer.ident is not None:
                    finalizer.join(2)
                for thread in writers:
                    thread.join(2)
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(json.loads(self.records()[0].read_bytes())["outcome"], "timed-out")

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

    def test_main_returns_timeout_when_expiry_claim_precedes_completion(self):
        output = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        def execute(root, args, timing):
            self.assertTrue(timing.claim("timed-out"))
            return {"release_id": "r"}
        with patch.object(wiki.sys, "argv", ["wiki.py", "publish", "--release", "r"]), \
                patch.object(wiki, "__file__", str(self.root / "wiki.py")), \
                patch.object(wiki.sys, "stdout", output), patch.object(wiki, "_run", side_effect=execute):
            self.assertEqual(wiki.main(), 124)
        self.assertEqual(json.loads(self.records()[0].read_bytes())["outcome"], "timed-out")

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
        # Exercise the actual coordinated release rather than the pipeline
        # fixture's candidate-ID stand-in for a release identity.
        self.fixture.release_patch.stop()
        workspace.initialize(self.root, PROJECT)
        for repository in PROJECT["repositories"]:
            path = self.root / repository["path"]
            git(path, "config", "user.name", "Wiki fixture")
            git(path, "config", "user.email", "wiki@example.invalid")
            git(path, "add", ".")
            git(path, "commit", "-m", "Seed timing fixture")
        workspace.checkout_lock(self.root, PROJECT)
        (self.root / "project.json").write_bytes(json_bytes(PROJECT))

    def test_capture_and_timing_do_not_change_request_run_or_release_identity(self):
        receipt = self.root / "capture.json"
        receipt.write_bytes(json_bytes(CAPTURE))
        args = SimpleNamespace(command="update", source=str(self.source), capture_timing=receipt)
        first = wiki.run(self.root, args)
        saved = pipeline.read(self.root, first["run_id"])
        released = release.read(self.root, first["release_id"])
        release.verify(self.root, released)
        release_path = self.root / f"releases/{first['release_id']}.json"
        release_bytes = release_path.read_bytes()
        request = self.root / f".local/pipeline/requests/{saved['request_key']}.json"
        before = request.read_bytes()
        receipt.write_bytes(json_bytes({**CAPTURE, "seconds": 500, "phases": []}))
        second = wiki.run(self.root, args)
        third = wiki.run(self.root, SimpleNamespace(command="update", source=str(self.source)))
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["run_id"], third["run_id"])
        self.assertEqual(first["release_id"], second["release_id"])
        self.assertEqual(first["release_id"], third["release_id"])
        self.assertEqual(release_path.read_bytes(), release_bytes)
        release.verify(self.root, release.read(self.root, third["release_id"]))
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

    def test_failed_worker_marks_topic_phase_failed(self):
        self.fixture.host.fail_name = "Wiki-items"
        with self.assertRaisesRegex(ContractError, "Topic publication failed"):
            self.invoke()
        record = json.loads(next((self.root / ".local/runs").glob("*.json")).read_bytes())
        phases = {row["name"]: row for row in record["stages"]}
        self.assertEqual(phases["topics-1"]["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
