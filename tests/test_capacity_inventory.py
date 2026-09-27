"""Measure exported history, including deleted objects, in a small real Git repo."""

from pathlib import Path
import shutil
import tempfile
import unittest

from wikibuild.capacity_inventory import history_size
from wikibuild.storage import ContractError, git


class HistorySizeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="hcap-"))
        git(self.root, "init", "--initial-branch=main")
        git(self.root, "config", "user.name", "Capacity fixture")
        git(self.root, "config", "user.email", "wiki@example.invalid")
        self.addCleanup(self.cleanup)

    def cleanup(self):
        try:
            shutil.rmtree(self.root)
        except PermissionError:
            print(f"Retained protected capacity fixture: {self.root}")

    def commit(self, message):
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", message)
        return git(self.root, "rev-parse", "HEAD")

    def test_deleted_blobs_are_counted_once_and_unrelated_branch_is_excluded(self):
        for name in ("first.md", "duplicate.md"):
            (self.root / name).write_text("same content" * 100)
        first = self.commit("Initial")
        (self.root / "first.md").unlink()
        (self.root / "duplicate.md").unlink()
        (self.root / "current.md").write_text("current")
        selected = self.commit("Replace content")
        before = history_size(self.root, [selected, first])
        self.assertEqual(before["blobs"], 2)
        self.assertEqual(before["largest_blob_bytes"], len("same content" * 100))
        # Independent per-object reads verify the streaming aggregate, with no
        # production history-measurement code in the expected result.
        ids = git(self.root, "rev-list", "--objects", "--no-object-names", selected).splitlines()
        sizes = [int(git(self.root, "cat-file", "-s", oid)) for oid in ids]
        self.assertEqual(before["history_bytes"], sum(sizes))
        self.assertEqual(before["objects"], len(ids))
        git(self.root, "switch", "-c", "unrelated")
        (self.root / "unrelated.md").write_text("unrelated" * 1000)
        unrelated = self.commit("Unrelated local work")
        self.assertEqual(history_size(self.root, [selected]), before)
        self.assertGreater(history_size(self.root, [unrelated])["history_bytes"], before["history_bytes"])

    def test_invalid_revision_does_not_return_zero_usage(self):
        (self.root / "current.md").write_text("current")
        self.commit("Initial")
        with self.assertRaisesRegex(ContractError, "Cannot measure Git history"):
            history_size(self.root, ["missing-reference"])
        for refs in ([], ["--all"]):
            with self.subTest(refs=refs), self.assertRaisesRegex(ContractError, "explicit Git revisions"):
                history_size(self.root, refs)


if __name__ == "__main__":
    unittest.main()
