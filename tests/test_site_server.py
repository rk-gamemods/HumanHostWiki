"""Execute the standalone Node server contract through the component runner."""

import os
from pathlib import Path
import shutil
import subprocess
import unittest

from tests._support import fixture_dir


class SiteServerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is unavailable")
    def test_static_server_contract(self):
        root = fixture_dir(self, "server")
        environment = os.environ.copy()
        environment["HHWIKI_TEST_ROOT"] = str(root)
        result = subprocess.run([shutil.which("node"), "--test",
                                 str(Path(__file__).with_name("site_server.test.js"))],
                                env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
