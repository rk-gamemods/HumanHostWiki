"""External processes stop at their deadline even when a descendant keeps the output pipe open."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from tests._support import fixture_dir
from wikibuild import bounded, steam_build, storage
from wikibuild.storage import ContractError, process_running, writer_lock


# The grandchild inherits stdout, like git-remote-https under git.
HOLDS_PIPE = ("import os, subprocess, sys, time; from pathlib import Path; "
              "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
              "Path(sys.argv[1]).write_text(str(os.getpid()) + '\\n' + str(child.pid)); "
              "time.sleep(120) if '--exit-parent' not in sys.argv[2:] else None")


def alive(pid):
    # An orphan zombie is already terminated and belongs to the OS reaper.
    status = Path(f"/proc/{pid}/stat")
    if os.name != "nt" and status.exists():
        try:
            if status.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                return False
        except (FileNotFoundError, ProcessLookupError):
            # The process exited between the existence check and the read (ESRCH).
            return False
    return process_running(pid)


def stop_recorded(path):
    if path.exists():
        for row in path.read_text().splitlines():
            pid = int(row)
            if not alive(pid):
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as error:
                # Windows reports an already exited PID as invalid.
                if not isinstance(error, ProcessLookupError) and getattr(error, "winerror", None) != 87:
                    raise


class BoundedRunTests(unittest.TestCase):
    def test_parent_exit_does_not_leave_a_descendant_holding_the_pipe(self):
        folder = fixture_dir(self, "bounded")
        pids = Path(folder) / "pids.txt"
        started = time.monotonic()
        try:
            try:
                bounded.run([sys.executable, "-c", HOLDS_PIPE, str(pids), "--exit-parent"], cwd=folder, timeout=2)
            except subprocess.TimeoutExpired:
                pass
            self.assertLess(time.monotonic() - started, 15)
            self.assertTrue(pids.exists())
            self.assertTrue(all(not alive(pid) for pid in map(int, pids.read_text().splitlines())))
        finally:
            stop_recorded(pids)

    def test_completed_process_matches_subprocess_run(self):
        result = bounded.run([sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"],
                             timeout=60, input=b"ok")
        self.assertEqual((result.returncode, result.stdout), (0, b"OK"))

    def test_descendant_holding_the_pipe_cannot_outlast_the_deadline(self):
        folder = fixture_dir(self, "bounded")
        pids = Path(folder) / "pids.txt"
        started = time.monotonic()
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                bounded.run([sys.executable, "-c", HOLDS_PIPE, str(pids)], cwd=folder, timeout=2)
            self.assertLess(time.monotonic() - started, 10)
            self.assertTrue(all(not alive(pid) for pid in map(int, pids.read_text().splitlines())))
        finally:
            stop_recorded(pids)

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
    def test_launch_interruption_reaps_suspended_child(self):
        def registry_available():
            acquired = []
            def probe():
                available = bounded._children_lock.acquire(timeout=1)
                acquired.append(available)
                if available:
                    bounded._children_lock.release()
            observer = threading.Thread(target=probe)
            observer.start()
            observer.join(2)
            self.assertEqual(acquired, [True], "Launch and reap must leave the registry available")
        for boundary in ("assign", "resume"):
            with self.subTest(boundary=boundary):
                folder = fixture_dir(self, "bounded")
                processes = []
                original, original_wait = subprocess.Popen, subprocess.Popen.wait
                def launch(*args, **kwargs):
                    registry_available()
                    process = original(*args, **kwargs)
                    processes.append(process)
                    return process
                def wait(process, *args, **kwargs):
                    registry_available()
                    return original_wait(process, *args, **kwargs)
                def interrupt(*args):
                    registry_available()
                    raise KeyboardInterrupt(f"{boundary} interrupted")
                sentinel = Path(folder) / "must-not-exist"
                try:
                    with patch.object(bounded.subprocess, "Popen", side_effect=launch), \
                            patch.object(original, "wait", new=wait), \
                            patch.object(bounded._WindowsJob, boundary, side_effect=interrupt):
                        with self.assertRaises(KeyboardInterrupt):
                            bounded.start([sys.executable, "-c", f"from pathlib import Path; Path({str(sentinel)!r}).touch()"])
                    self.assertEqual(len(processes), 1)
                    self.assertFalse(alive(processes[0].pid))
                    self.assertFalse(sentinel.exists())
                finally:
                    for process in processes:
                        if hasattr(process, "_wiki_owned"):
                            bounded.kill_tree(process)
                        else:
                            process.kill()
                            process.wait(timeout=5)

    @unittest.skipUnless(os.name == "nt", "Windows owned-job retry")
    def test_failed_cleanup_retains_queryable_job_until_confirmed_retry(self):
        for failure in ("reap", "query"):
            for retry_fails in (False, True):
                with self.subTest(failure=failure, retry_fails=retry_fails):
                    process = bounded.start([sys.executable, "-c", "import time; time.sleep(120)"])
                    owned, job = process._wiki_owned, process._wiki_owned.job
                    method, error = (("wait", subprocess.TimeoutExpired(process.args, 0.2)) if failure == "reap"
                                     else ("QueryInformationJobObject", OSError("job query failed")))
                    target = process if failure == "reap" else job.kernel
                    original = getattr(target, method)
                    calls = 0
                    def fail_then_retry(*args, **kwargs):
                        nonlocal calls
                        calls += 1
                        if calls == 1 or retry_fails:
                            raise error
                        return original(*args, **kwargs)
                    try:
                        with patch.object(target, method, side_effect=fail_then_retry), patch.object(bounded, "REAP_SECONDS", 0.2):
                            with self.assertRaises(type(error)):
                                bounded.kill_tree(process)
                            self.assertIsNotNone(job.handle)
                            self.assertFalse(owned.done)
                            self.assertEqual(owned.state, "unresolved")
                            self.assertIn(owned, bounded._children)
                            if retry_fails:
                                with self.assertRaises(type(error)):
                                    bounded.kill_tree(process)
                                self.assertIsNotNone(job.handle)
                                self.assertFalse(owned.done)
                                self.assertIn(owned, bounded._children)
                            else:
                                bounded.kill_tree(process)
                                self.assertTrue(owned.done)
                                self.assertIsNone(job.handle)
                                self.assertNotIn(owned, bounded._children)
                        if retry_fails:
                            # The retained handle still supports a real OS query.
                            job.wait(time.monotonic() + 2)
                    finally:
                        bounded.kill_tree(process)

    def test_shutdown_sees_a_launch_before_process_creation(self):
        processes, errors = [], []
        entered, release = threading.Event(), threading.Event()
        original = subprocess.Popen
        def launch(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Launch was not released")
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        def start():
            try:
                bounded.start([sys.executable, "-c", "import time; time.sleep(120)"])
            except BaseException as exc:
                errors.append(exc)
        starter = threading.Thread(target=start)
        previous = bounded._stopping.is_set()
        try:
            with patch.object(bounded.subprocess, "Popen", side_effect=launch):
                starter.start()
                self.assertTrue(entered.wait(2))
                bounded.begin_shutdown()
                with bounded._children_lock:
                    pending = [child for child in bounded._children if child.process is None]
                self.assertEqual(len(pending), 1)
                release.set()
                self.assertEqual(bounded.terminate_all(), [])
                starter.join(2)
                self.assertFalse(starter.is_alive())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], RuntimeError)
                self.assertEqual(len(processes), 1)
                self.assertFalse(alive(processes[0].pid))
                self.assertNotIn(pending[0], bounded._children)
        finally:
            release.set()
            starter.join(5)
            for process in processes:
                bounded.kill_tree(process)
            bounded.end_shutdown(previous)

    @unittest.skipUnless(os.name == "nt", "Windows suspended launch")
    def test_job_setup_failure_reaps_child_before_it_can_run(self):
        processes = []
        original = subprocess.Popen
        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process
        folder = fixture_dir(self, "bounded")
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
        # Keep both parent-exit variants: Python returns, or cmd uses start /b.
        for parent in ("python", "batch"):
            for detached in (False, True):
                with self.subTest(parent=parent, detached=detached):
                    temp = fixture_dir(self, "steam")
                    pid_file = temp / "standin.pids"
                    helper = temp / "standin.py"
                    if parent == "python":
                        helper.write_text("import os, subprocess\nfrom pathlib import Path\n"
                                          "child = subprocess.Popen(['ping', '-n', '120', '127.0.0.1'])\n"
                                          f"Path({str(pid_file)!r}).write_text(str(child.pid) + '\\n' + str(os.getpid()))\n"
                                          + ("" if detached else "child.wait()\n"))
                    else:
                        helper.write_text("import os, time\nfrom pathlib import Path\n"
                                          f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(120)\n")
                    self.addCleanup(stop_recorded, pid_file)
                    steamcmd = temp / "steamcmd.cmd"
                    prefix = 'start "" /b ' if parent == "batch" and detached else ""
                    steamcmd.write_text('@echo Loading Steam API...OK\r\n'
                                        f'@{prefix}"{sys.executable}" "{helper}"\r\n')
                    popen = subprocess.Popen
                    processes = []

                    def reap(process):
                        bounded.kill_tree(process)
                        process.wait(timeout=5)

                    def record(*args, **kwargs):
                        process = popen(*args, **kwargs)
                        processes.append(process)
                        self.addCleanup(reap, process)
                        return process

                    started = time.monotonic()
                    with patch.object(steam_build.subprocess, "Popen", side_effect=record), \
                            patch.object(steam_build, "DEADLINE", 2), self.assertRaisesRegex(ContractError, "timed out"):
                        steam_build.fetch(steamcmd, "2393970", "public")
                    self.assertLess(time.monotonic() - started, 10)
                    self.assertTrue(pid_file.exists())
                    self.assertTrue(all(not alive(pid) for pid in map(int, pid_file.read_text().splitlines())))
                    self.assertTrue(all(process.poll() is not None for process in processes))


@unittest.skipIf(os.name == "nt", "Windows waits for the job object instead of the process group")
class ProcessGroupExitTests(unittest.TestCase):
    def start_group(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.wait(timeout=10)))
        return process

    def test_live_group_holds_cleanup_until_its_deadline(self):
        process = self.start_group()
        self.assertFalse(bounded._group_exited(process.pid))
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded._wait_group(process.pid, time.monotonic() + 0.2)

    def test_unreaped_member_keeps_the_group_open_until_reaped(self):
        process = self.start_group()
        os.killpg(process.pid, signal.SIGKILL)
        # WNOWAIT confirms the exit while leaving the child unreaped.
        deadline = time.monotonic() + 10
        while os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG) is None:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        # Without positive proof from the OS, cleanup stays unresolved.
        self.assertFalse(bounded._group_exited(process.pid))
        process.wait(timeout=10)
        bounded._wait_group(process.pid, time.monotonic() + 5)

    def start_owned(self):
        process = bounded.start([sys.executable, "-c", "import time; time.sleep(120)"], stdout=subprocess.DEVNULL)
        self.addCleanup(bounded.kill_tree, process)
        return process

    def test_kill_tree_waits_until_the_group_is_reported_empty(self):
        process = self.start_owned()
        with patch.object(bounded, "_group_exited", side_effect=[False, False, True]) as observed:
            bounded.kill_tree(process)
        self.assertEqual(observed.call_count, 3)
        self.assertNotIn(process._wiki_owned, bounded._children)

    def test_group_that_outlives_the_reap_budget_stays_owned(self):
        process = self.start_owned()
        with patch.object(bounded, "REAP_SECONDS", 0.3), \
                patch.object(bounded, "_group_exited", return_value=False) as observed:
            with self.assertRaises(subprocess.TimeoutExpired) as raised:
                bounded.kill_tree(process)
        # The group wait, not the parent wait, spent the budget.
        self.assertTrue(observed.called)
        self.assertIn("process group", str(raised.exception.cmd))
        self.assertIn(process._wiki_owned, bounded._children)
        self.assertEqual(process._wiki_owned.state, "unresolved")

    def test_kill_tree_returns_after_the_whole_group_exits(self):
        folder = fixture_dir(self, "bounded")
        pids = Path(folder) / "pids.txt"
        process = bounded.start([sys.executable, "-c", HOLDS_PIPE, str(pids)], cwd=folder,
                                stdout=subprocess.DEVNULL)
        self.addCleanup(bounded.kill_tree, process)
        try:
            deadline = time.monotonic() + 30
            while not (pids.exists() and len(pids.read_text().splitlines()) == 2):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.05)
            bounded.kill_tree(process)
            self.assertTrue(bounded._group_exited(process.pid))
            self.assertTrue(all(not alive(pid) for pid in map(int, pids.read_text().splitlines())))
        finally:
            stop_recorded(pids)


class UpdateDeadlineTests(unittest.TestCase):
    def test_held_recorder_lock_cannot_block_timeout_exit(self):
        for main_returns in (False, True):
            with self.subTest(main_returns=main_returns):
                folder = fixture_dir(self, "bounded")
                script = "import sys, time, wiki\nfrom pathlib import Path\nfrom wikibuild import run_timing\n"
                if main_returns:
                    script += ("wiki.TIMING_CLAIM_SECONDS = 0.5\nwiki.CLEANUP_GRACE = 1\n"
                               "wiki.UPDATE_DEADLINE = 0.1\n"
                               "def execute(root, args, timing):\n"
                               "    timing.lock.acquire()\n    time.sleep(0.25)\n    return {}\n"
                               f"wiki.__file__ = {str(Path(folder) / 'wiki.py')!r}\nwiki._run = execute\n"
                               "sys.argv = ['wiki.py', 'update']\nraise SystemExit(wiki.main())\n")
                else:
                    script += ("wiki.TIMING_CLAIM_SECONDS = 0.1\nwiki.CLEANUP_GRACE = 0.5\n"
                               f"timing = run_timing.Recorder(Path({str(folder)!r}), 'update')\n"
                               "timing.lock.acquire()\nwiki.deadline(0.1, 'update', timing=timing)\ntime.sleep(120)\n")
                started = time.monotonic()
                code, _, errors = self.harness(script, cwd=folder)
                self.assertEqual(code, 124, errors.decode(errors="replace"))
                # The blocked path sleeps 120 s; 10 s proves the exit without timing a loaded runner.
                self.assertLess(time.monotonic() - started, 10)
                self.assertIn(b"recorder lock", errors)
                self.assertIn(b"timing could not be recorded", errors)
                self.assertIn(b"exceeded its", errors)

    @unittest.skipUnless(os.name == "nt", "Windows unresolved-job diagnostics")
    def test_watchdog_reports_unresolved_child_and_retains_job(self):
        import io
        import wiki
        process = bounded.start([sys.executable, "-c", "import time; time.sleep(120)"])
        owned, job = process._wiki_owned, process._wiki_owned.job
        stopped, diagnostics = [], io.StringIO()
        try:
            with patch.object(job.kernel, "QueryInformationJobObject", side_effect=OSError("job query failed")), \
                    patch.object(wiki.sys, "stderr", diagnostics), patch.object(bounded, "REAP_SECONDS", 0.2):
                timer = wiki.deadline(0.01, "update", stop=stopped.append)
                timer.join(3)
                self.assertEqual(stopped, [124])
                self.assertIn(f"unresolved child PID {process.pid}: job query failed", diagnostics.getvalue())
                self.assertIsNotNone(job.handle)
                self.assertFalse(owned.done)
                self.assertEqual(owned.state, "unresolved")
                self.assertIn(owned, bounded._children)
        finally:
            bounded.kill_tree(process)

    def test_metadata_cleanup_preserves_os_lock_and_foreign_metadata(self):
        folder = fixture_dir(self, "bounded")
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

    def harness(self, code, *, cwd=None):
        cwd = fixture_dir(self, "watchdog") if cwd is None else cwd
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(Path(__file__).resolve().parents[1]), environment.get("PYTHONPATH", "")])
        process = subprocess.Popen([sys.executable, "-c", code], cwd=cwd, env=environment,
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
            with self.subTest(command=command, unwind=unwind):
                folder = fixture_dir(self, "bounded")
                root = Path(folder)
                pids = root / "pids.txt"
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
                          f"        bounded.run([{sys.executable!r}, '-c', {HOLDS_PIPE!r}, {str(pids)!r}], timeout=120)\n"
                          + ("" if unwind else "        time.sleep(120)\n")
                          + "    return {}\n"
                          # Actual CLI/watchdog control flow, wholly fake command work.
                          f"wiki.__file__ = {str(root / 'wiki.py')!r}\nwiki._run = execute\n"
                          f"wiki.UPDATE_DEADLINE = 2\nsys.argv = {argv!r}\nraise SystemExit(wiki.main())\n")
                try:
                    code, _, errors = self.harness(script, cwd=folder)
                    self.assertEqual(code, 124, errors.decode(errors="replace"))
                    self.assertTrue(all(not alive(pid) for pid in map(int, pids.read_text().splitlines())))
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
                    stop_recorded(pids)

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
