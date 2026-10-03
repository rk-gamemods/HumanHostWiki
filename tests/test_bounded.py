"""External processes stop at their deadline even when a descendant keeps the output pipe open."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from tests._support import fixture_dir

from wikibuild import bounded, steam_build
from wikibuild.storage import ContractError

# The child starts a grandchild that inherits stdout and outlives it, like git-remote-https under git.
HOLDS_PIPE = ("import subprocess, sys, time; from pathlib import Path; "
              "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
              "Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(120)")


def stop_recorded(path):
    if path.exists():
        for pid in path.read_text().splitlines():
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError as error:
                # Windows reports an already exited PID as invalid.
                if not isinstance(error, ProcessLookupError) and getattr(error, "winerror", None) != 87:
                    raise


class BoundedRunTests(unittest.TestCase):
    def test_completed_process_matches_subprocess_run(self):
        result = bounded.run([sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"],
                             timeout=60, input=b"ok")
        self.assertEqual((result.returncode, result.stdout), (0, b"OK"))

    def test_descendant_holding_the_pipe_cannot_outlast_the_deadline(self):
        folder = fixture_dir(self, "bounded")
        pid_file = folder / "child.pid"
        self.addCleanup(stop_recorded, pid_file)
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded.run([sys.executable, "-c", HOLDS_PIPE, str(pid_file)], timeout=2, cwd=folder)
        self.assertLess(time.monotonic() - started, 30)

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
        # The second stand-in exits at once and leaves a detached child holding stdout.
        for detached in (False, True):
            temp = fixture_dir(self, "bounded")
            with self.subTest(detached=detached):
                pid_file = temp / "standin.pids"
                helper = temp / "standin.py"
                helper.write_text("import os, subprocess\nfrom pathlib import Path\n"
                                  "child = subprocess.Popen(['ping', '-n', '120', '127.0.0.1'])\n"
                                  f"Path({str(pid_file)!r}).write_text(str(child.pid) + '\\n' + str(os.getpid()))\n"
                                  + ("" if detached else "child.wait()\n"))

                self.addCleanup(stop_recorded, pid_file)
                steamcmd = temp / "steamcmd.cmd"
                steamcmd.write_text('@echo Loading Steam API...OK\r\n'
                                    f'@"{sys.executable}" "{helper}"\r\n')
                popen = subprocess.Popen

                def reap(process):
                    if process.poll() is None:
                        bounded.kill_tree(process)
                    process.wait(timeout=5)

                def record(*args, **kwargs):
                    process = popen(*args, **kwargs)
                    self.addCleanup(reap, process)
                    return process

                started = time.monotonic()
                with patch.object(steam_build.subprocess, "Popen", side_effect=record), \
                        patch.object(steam_build, "DEADLINE", 2), self.assertRaisesRegex(ContractError, "timed out"):
                    steam_build.fetch(steamcmd, "2393970", "public")
                self.assertLess(time.monotonic() - started, 30)


class UpdateDeadlineTests(unittest.TestCase):
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
