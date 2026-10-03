"""External processes stop at their deadline even when a descendant keeps the output pipe open."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from wikibuild import bounded, steam_build, storage
from wikibuild.storage import ContractError, process_running, writer_lock

ROOT = Path(__file__).resolve().parents[1]


def alive(pid):
    # An orphan zombie is already terminated and belongs to the OS reaper.
    status = Path(f"/proc/{pid}/stat")
    if os.name != "nt" and status.exists():
        try:
            if status.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                return False
        except FileNotFoundError:
            return False
    return process_running(pid)


def cleanup_pids(path):
    if path.exists():
        for pid in json.loads(path.read_text()):
            if alive(pid):
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=5)
                else:
                    import signal
                    os.kill(pid, signal.SIGKILL)


def tree_code(pids, *, exit_parent=False):
    return ("import json, os, subprocess, sys, time; from pathlib import Path; "
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
            f"Path({str(pids)!r}).write_text(json.dumps([os.getpid(), child.pid])); "
            + ("" if exit_parent else "time.sleep(120)"))

class BoundedRunTests(unittest.TestCase):
    def test_parent_exit_does_not_leave_a_descendant_holding_the_pipe(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            pids = Path(folder) / "pids.json"
            started = time.monotonic()
            try:
                try:
                    bounded.run([sys.executable, "-c", tree_code(pids, exit_parent=True)], timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                self.assertLess(time.monotonic() - started, 15)
                self.assertTrue(pids.exists())
                self.assertTrue(all(not alive(pid) for pid in json.loads(pids.read_text())))
            finally:
                cleanup_pids(pids)
    def test_completed_process_matches_subprocess_run(self):
        result = bounded.run([sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"],
                             timeout=60, input=b"ok")
        self.assertEqual((result.returncode, result.stdout), (0, b"OK"))

    def test_descendant_holding_the_pipe_cannot_outlast_the_deadline(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            pids = Path(folder) / "pids.json"
            started = time.monotonic()
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    bounded.run([sys.executable, "-c", tree_code(pids)], timeout=2)
                self.assertLess(time.monotonic() - started, 10)
                self.assertTrue(all(not alive(pid) for pid in json.loads(pids.read_text())))
            finally:
                cleanup_pids(pids)

    def test_registry_cleanup_is_idempotent_and_refuses_new_launches(self):
        process = bounded.start([sys.executable, "-c", "import time; time.sleep(120)"])
        previous = bounded.begin_shutdown()
        try:
            with self.assertRaisesRegex(RuntimeError, "launch refused"):
                bounded.start([sys.executable, "-c", "raise AssertionError('must not run')"])
            self.assertEqual(bounded.terminate_all(), [])
            self.assertEqual(bounded.terminate_all(), [])
            bounded.kill_tree(process)
            self.assertIsNotNone(process.returncode)
            self.assertFalse(alive(process.pid))
        finally:
            bounded.kill_tree(process)
            bounded.end_shutdown(previous)

    def test_pipe_worker_start_failure_does_not_leak_child(self):
        processes = []
        original = bounded.start
        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        with patch.object(bounded, "start", side_effect=launch), \
                patch.object(bounded.threading.Thread, "start", side_effect=RuntimeError("worker failed")):
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                bounded.run([sys.executable, "-c", "import time; time.sleep(120)"], timeout=2)
        self.assertEqual(len(processes), 1)
        self.assertFalse(alive(processes[0].pid))
        self.assertTrue(processes[0].stdout.closed)
        self.assertTrue(processes[0].stderr.closed)

    @unittest.skipUnless(os.name == "nt", "Windows suspended launch")
    def test_job_setup_failure_reaps_child_before_it_can_run(self):
        processes = []
        original = subprocess.Popen
        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            sentinel = Path(folder) / "must-not-exist"
            with patch.object(bounded.subprocess, "Popen", side_effect=launch), \
                    patch.object(bounded, "_WindowsJob", side_effect=OSError("job setup failed")):
                with self.assertRaisesRegex(OSError, "job setup failed"):
                    bounded.run([sys.executable, "-c", f"from pathlib import Path; Path({str(sentinel)!r}).touch()"], timeout=2)
            self.assertEqual(len(processes), 1)
            self.assertFalse(alive(processes[0].pid))
            self.assertFalse(sentinel.exists())

    def test_child_that_never_reads_input_cannot_block_the_write(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded.run([sys.executable, "-c", "import time; time.sleep(120)"], timeout=2, input=b"x" * (8 << 20))
        self.assertLess(time.monotonic() - started, 30)

    def test_orphan_output_is_capped(self):
        with patch.object(bounded, "MAX_CAPTURE", 1000):
            result = bounded.run([sys.executable, "-c", "import sys; sys.stdout.write('y' * 100000)"], timeout=60)
        self.assertEqual(len(result.stdout), 1000)

    @unittest.skipUnless(os.name == "nt", "The SteamCMD stand-ins are Windows batch files")
    def test_stalled_steamcmd_reports_unavailable_metadata(self):
        # The second batch parent exits first. Kill only recorded fixture PIDs.
        for detached in (False, True):
            with self.subTest(detached=detached), tempfile.TemporaryDirectory(dir=ROOT) as temp:
                pids = Path(temp) / "pids.json"
                child = Path(temp) / "child.py"
                child.write_text("import json, os, sys, time\nfrom pathlib import Path\n"
                                 "Path(sys.argv[1]).write_text(json.dumps([os.getpid()]))\ntime.sleep(120)\n")
                steamcmd = Path(temp) / "steamcmd.cmd"
                body = ('@echo Loading Steam API...OK\n@' + ('start "" /b ' if detached else '')
                        + f'"{sys.executable}" "{child}" "{pids}"\n')
                steamcmd.write_text(body)
                started = time.monotonic()
                try:
                    with patch.object(steam_build, "DEADLINE", 2), self.assertRaisesRegex(ContractError, "timed out"):
                        steam_build.fetch(steamcmd, "2393970", "public")
                    self.assertLess(time.monotonic() - started, 10)
                    self.assertTrue(all(not alive(pid) for pid in json.loads(pids.read_text())))
                finally:
                    cleanup_pids(pids)


class UpdateDeadlineTests(unittest.TestCase):
    def test_metadata_cleanup_preserves_os_lock_and_foreign_metadata(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            owner = root / ".local/writer.lock.owner.json"
            with writer_lock(root):
                self.assertEqual(storage.cleanup_writer_owners(), [])
                self.assertFalse(owner.exists())
                with self.assertRaisesRegex(ContractError, "Another wiki writer"):
                    with writer_lock(root):
                        self.fail("Metadata cleanup must not release the OS lock")
                self.assertEqual(storage.cleanup_writer_owners(), [])
                owner.write_bytes(b"foreign owner metadata")
            self.assertEqual(owner.read_bytes(), b"foreign owner metadata")

    def harness(self, code):
        process = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            stdout, stderr = process.communicate(timeout=10)
            return process.returncode, stdout, stderr
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()

    def test_real_timeout_cleans_tree_metadata_and_registered_file(self):
        for command, unwind in (("update", True), ("publish", True), ("update", False)):
            with self.subTest(command=command, unwind=unwind), tempfile.TemporaryDirectory(dir=ROOT) as folder:
                root = Path(folder)
                pids = root / "pids.json"
                temporary = root / "command.tmp"
                staging = root / "journaled-stage"
                argv = ["wiki.py", command] + (["--release", "fixture"] if command == "publish" else [])
                script = ("from pathlib import Path\nimport sys, time, wiki\n"
                          "from wikibuild import bounded, run_timing\nfrom wikibuild.storage import writer_lock\n"
                          "def execute(root, args, timing):\n"
                          "    timing.enter('fixture')\n"
                          "    with writer_lock(root):\n"
                          f"        temporary = wiki.register_cleanup({str(temporary)!r})\n"
                          "        temporary.write_text('owned temporary')\n"
                          f"        Path({str(staging)!r}).mkdir()\n"
                          f"        bounded.run([{sys.executable!r}, '-c', {tree_code(pids)!r}], timeout=120)\n"
                          + ("" if unwind else "        time.sleep(120)\n")
                          + "    return {}\n"
                          # Actual CLI/watchdog control flow, wholly fake command work.
                          f"wiki.__file__ = {str(root / 'wiki.py')!r}\nwiki._run = execute\n"
                          f"wiki.UPDATE_DEADLINE = 2\nsys.argv = {argv!r}\nraise SystemExit(wiki.main())\n")
                try:
                    code, _, errors = self.harness(script)
                    self.assertEqual(code, 124, errors.decode(errors="replace"))
                    self.assertTrue(all(not alive(pid) for pid in json.loads(pids.read_text())))
                    self.assertFalse((root / ".local/writer.lock.owner.json").exists())
                    self.assertTrue((root / ".local/writer.lock").exists())
                    self.assertFalse(temporary.exists())
                    self.assertTrue(staging.exists(), "Journaled staging is recovery evidence")
                    records = list((root / ".local/runs").glob("*.json"))
                    self.assertEqual(len(records), 1)
                    record = json.loads(records[0].read_bytes())
                    self.assertEqual(record["outcome"], "timed-out")
                    self.assertEqual(record["stages"][0]["outcome"], "timed-out")
                    self.assertIn(b"exceeded its", errors)
                    self.assertIn(b"abandon-publication" if command == "publish" else b"rerun the normal command", errors)
                finally:
                    cleanup_pids(pids)

    def test_hanging_cleanup_still_exits_within_grace(self):
        script = ("import time, wiki\nwiki.CLEANUP_GRACE = 0.25\n"
                  "def hang():\n    time.sleep(120)\n"
                  "wiki.cleanup_registered_files = hang\n"
                  "wiki.deadline(0.1, 'update')\ntime.sleep(120)\n")
        started = time.monotonic()
        code, _, errors = self.harness(script)
        self.assertEqual(code, 124, errors.decode(errors="replace"))
        self.assertLess(time.monotonic() - started, 3)
        self.assertIn(b"registered temporary files: cleanup did not finish within 0.25s", errors)
        self.assertIn(b"exceeded its", errors)

    def test_overdue_update_is_stopped(self):
        import wiki
        stopped = []
        timer = wiki.deadline(0.1, "update", stop=stopped.append)
        timer.join(10)
        self.assertEqual(stopped, [124])

    def test_finished_update_cancels_its_deadline(self):
        import wiki
        stopped = []
        timer = wiki.deadline(0.5, "update", stop=stopped.append)
        timer.cancel()
        time.sleep(1)
        self.assertEqual(stopped, [])


if __name__ == "__main__":
    unittest.main()
