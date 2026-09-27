"""Run the actual small loader with native URL, hashing and fetch-shaped responses."""

from pathlib import Path
import shutil
import subprocess
import unittest


class ReleaseBrowserTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the browser-loader boundary check")
    def test_release_loader_references_and_coordinated_selection(self):
        result = subprocess.run([shutil.which("node"), str(Path(__file__).with_name("release_bootstrap.test.js"))],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("6 release loader scenarios passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
