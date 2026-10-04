"""Measure exported history, including deleted objects, in a small real Git repo."""

import copy
import unittest

from tests._support import fixture_dir

from wikibuild import capacity_inventory, ownership
from wikibuild.capacity_inventory import history_size
from wikibuild.storage import ContractError, digest, git, json_bytes


class HistorySizeTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "capacity")
        git(self.root, "init", "--initial-branch=main")
        git(self.root, "config", "user.name", "Capacity fixture")
        git(self.root, "config", "user.email", "wiki@example.invalid")

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


class InventoryRecordTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "inv")
        self.path = self.root / "repositories/items"
        self.path.mkdir(parents=True)
        self.repo = {"id": "items", "github_name": "Wiki-items", "role": "topic",
                     "path": "repositories/items"}
        self.project = {"repositories": [self.repo]}
        git(self.path, "init", "--initial-branch=main")
        git(self.path, "config", "user.name", "Inventory fixture")
        git(self.path, "config", "user.email", "wiki@example.invalid")
        (self.path / "README.md").write_text("Initial")
        git(self.path, "add", ".")
        git(self.path, "commit", "-m", "Initial")
        self.initial = git(self.path, "rev-parse", "HEAD")

    def released(self):
        data = b"immutable object"
        self.name = "site/data/" + digest(data) + ".json"
        target = self.path / self.name
        target.parent.mkdir(parents=True)
        target.write_bytes(data)
        self.files = {self.name: {"sha256": digest(data), "bytes": len(data)}}
        (self.path / ownership.OWNER_FILE).write_bytes(json_bytes({
            "schema_version": 1, "kind": "generated-wiki-output",
            "files": self.files, "capacity_objects": [self.name]}))
        git(self.path, "add", ".")
        git(self.path, "commit", "-m", "Owned output")
        return {"release_id": "a" * 64,
                "physical": {"items": {"topic": "items", "ordinal": 0, "sealed": False}},
                "repositories": {"items": dict(self.repo)}}

    def test_explicit_unreleased_baseline_repeats_without_writes(self):
        before = git(self.path, "rev-parse", "HEAD")
        first = capacity_inventory.read(self.root, self.project, None, None)
        self.assertEqual(first, capacity_inventory.read(self.root, self.project, None, None))
        self.assertIsNone(first.release_id)
        self.assertEqual(first.stored, ())
        self.assertEqual(first.partitions[0].history_bytes,
                         history_size(self.path, [before])["history_bytes"])
        self.assertEqual(git(self.path, "rev-parse", "HEAD"), before)
        self.assertEqual(git(self.path, "status", "--porcelain"), "")

    def test_supplied_committed_records_ignore_coordinator_files_and_repeat(self):
        manifest = self.released()
        published = {"repositories": {"items": {"name": "Wiki-items", "pages": self.initial}}}
        records = copy.deepcopy((manifest, published))
        # Neither pointer is an allocation input. The coordinator owns loading
        # and validating them before it supplies the records to this layer.
        (self.root / "releases").mkdir()
        (self.root / "releases/latest.json").write_text("invalid release pointer")
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        first = capacity_inventory.read(self.root, self.project, manifest, published)
        self.assertEqual(first, capacity_inventory.read(self.root, self.project, manifest, published))
        self.assertEqual(first.release_id, manifest["release_id"])
        self.assertEqual(first.stored[0].partition, "items")
        self.assertEqual(first.stored[0].artifact.path, self.name)
        self.assertEqual(first.stored[0].artifact.sha256, self.files[self.name]["sha256"])
        self.assertEqual(first.partitions[0].site_bytes, self.files[self.name]["bytes"])
        head = git(self.path, "rev-parse", "HEAD")
        self.assertEqual(first.partitions[0].history_bytes,
                         history_size(self.path, [head, self.initial])["history_bytes"])
        self.assertEqual((manifest, published), records)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes()
                                  for p in self.root.rglob("*") if p.is_file()})

    def test_missing_baseline_and_mismatched_records_keep_errors(self):
        manifest = self.released()
        with self.assertRaisesRegex(ContractError, "Owned outputs exist without a release baseline"):
            capacity_inventory.read(self.root, self.project, None, None)
        manifest["repositories"]["items"]["github_name"] = "Other"
        with self.assertRaisesRegex(ContractError, "Released repository differs from its physical identity"):
            capacity_inventory.read(self.root, self.project, manifest, None)
        manifest["repositories"]["items"] = dict(self.repo)
        published = {"repositories": {"items": {"name": "Other", "pages": self.initial}}}
        with self.assertRaisesRegex(ContractError, "Published repository differs from capacity inventory"):
            capacity_inventory.read(self.root, self.project, manifest, published)


if __name__ == "__main__":
    unittest.main()
