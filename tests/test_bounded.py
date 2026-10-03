"""External processes stop at their deadline even when a descendant keeps the output pipe open."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from wikibuild import bounded, steam_build
from wikibuild.storage import ContractError

# The child starts a grandchild that inherits stdout and outlives it, like git-remote-https under git.
HOLDS_PIPE = ("import subprocess, sys, time; "
              "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); time.sleep(120)")


class BoundedRunTests(unittest.TestCase):
    def test_completed_process_matches_subprocess_run(self):
        result = bounded.run([sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"],
                             timeout=60, input=b"ok")
        self.assertEqual((result.returncode, result.stdout), (0, b"OK"))

    def test_descendant_holding_the_pipe_cannot_outlast_the_deadline(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded.run([sys.executable, "-c", HOLDS_PIPE], timeout=2)
        self.assertLess(time.monotonic() - started, 30)

    @unittest.skipUnless(os.name == "nt", "The SteamCMD stand-in is a Windows batch file")
    def test_stalled_steamcmd_reports_unavailable_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            steamcmd = Path(temp) / "steamcmd.cmd"
            steamcmd.write_text("@echo Loading Steam API...OK\r\n@ping -n 120 127.0.0.1 >nul\r\n")
            started = time.monotonic()
            with patch.object(steam_build, "DEADLINE", 2), self.assertRaisesRegex(ContractError, "timed out"):
                steam_build.fetch(steamcmd, "2393970", "public")
            self.assertLess(time.monotonic() - started, 30)


if __name__ == "__main__":
    unittest.main()
