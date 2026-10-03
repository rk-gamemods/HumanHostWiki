"""Open Git cache streams must not prevent Windows baseline snapshots."""
# HHWIKI-PLATFORMS: win32

from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from tests import _support
from tests._support import fixture_dir


class WindowsFixtureTests(unittest.TestCase):
    def test_baseline_copy_excludes_open_git_cache_streams(self):
        source = fixture_dir(self, "baseline")
        target = fixture_dir(self, "cloned")

        def git(*arguments, **options):
            return subprocess.run(["git", "-C", str(source), *arguments],
                                  capture_output=True, check=True, **options).stdout

        git("init", "-q")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        (source / "note.txt").write_bytes(b"Private baseline\n")
        git("add", ".")
        git("commit", "-qm", "Baseline")
        _support.cache_git_queries(self, source)
        with patch.object(_support.tempfile, "TemporaryFile", wraps=_support.tempfile.TemporaryFile) as streams:
            # Force both stderr and stdin streams to remain open during copytree.
            tree = git("rev-parse", "HEAD^{tree}").decode().strip()
            git("commit-tree", tree, input=b"Cache input fixture\n")
        self.assertEqual(streams.call_count, 2)
        for call in streams.call_args_list:
            self.assertFalse(Path(call.kwargs["dir"]).is_relative_to(source))
        before = sorted(path.relative_to(source) for path in source.rglob("*") if path.is_file())
        shutil.copytree(source, target, dirs_exist_ok=True)
        self.assertEqual(before, sorted(path.relative_to(target) for path in target.rglob("*") if path.is_file()))
        self.assertEqual((target / "note.txt").read_bytes(), b"Private baseline\n")
        copied = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD^{tree}"],
                                capture_output=True, check=True).stdout.decode().strip()
        self.assertEqual(copied, tree)


if __name__ == "__main__":
    unittest.main()
