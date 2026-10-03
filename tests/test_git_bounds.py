"""Converted callers time out actual owned stand-ins without network or repo writes."""

from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from tests._support import fixture_dir
from tools import (benchmark_release, check_coded_values, check_components,
                   check_extraction, check_history, check_release)
from wikibuild import (bounded, capacity_inventory, git_transaction, ownership,
                      publication_git, source, storage)


class GitBoundsTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "gitbound")
        self.children = []
        self.launches = []
        self.original = bounded.start
        self.addCleanup(self.reap)

    def reap(self):
        for child in self.children:
            bounded.kill_tree(child)

    def standin(self, command, **options):
        self.launches.append(command)
        # The replacement is an actual local child, using the production owner.
        child = self.original([sys.executable, "-c", "import time; time.sleep(120)"], **options)
        self.children.append(child)
        return child

    def assert_bound(self, module, constant, action, exception=subprocess.TimeoutExpired):
        started = time.monotonic()
        with patch.object(module, constant, 0.4), patch.object(bounded, "start", side_effect=self.standin):
            with self.assertRaises(exception):
                action()
        self.assertLess(time.monotonic() - started, 5)
        self.assertTrue(self.children)
        for child in self.children:
            self.assertIsNotNone(child.poll())
            self.assertFalse(storage.process_running(child.pid))
            self.assertNotIn(child._wiki_owned, bounded._children)

    def test_storage_plumbing(self):
        self.assert_bound(storage, "GIT_TIMEOUT", lambda: storage.git(self.root, "rev-parse", "HEAD"))

    def test_storage_tree_scan(self):
        self.assert_bound(storage, "GIT_TREE_TIMEOUT", lambda: storage.git(self.root, "status", "--porcelain"))

    def test_git_transaction_writer(self):
        self.assert_bound(git_transaction, "GIT_TIMEOUT", lambda: git_transaction.command(self.root, "hash-object", "-w", "--stdin", data=b"data"))

    def test_git_transaction_writer_obeys_shutdown_fence(self):
        previous = bounded.begin_shutdown()
        try:
            with self.assertRaisesRegex(RuntimeError, "launch refused"):
                git_transaction.command(self.root, "hash-object", "-w", "--stdin", data=b"data")
        finally:
            bounded.end_shutdown(previous)

    def test_git_transaction_tree_writer(self):
        self.assert_bound(git_transaction, "GIT_TREE_TIMEOUT", lambda: git_transaction.command(self.root, "read-tree", "HEAD"))

    def test_source_tree(self):
        with patch.object(source, "git", return_value="a" * 40):
            self.assert_bound(source, "GIT_TREE_TIMEOUT", lambda: source.Source(self.root, "HEAD"))

    def test_source_stream(self):
        reader = object.__new__(source.Source)
        reader.path = self.root
        def read():
            with reader:
                reader.process.stdout.readline()
        self.assert_bound(source, "GIT_STREAM_TIMEOUT", read)

    def test_ownership_batch(self):
        self.assert_bound(ownership, "GIT_STREAM_TIMEOUT", lambda: ownership.committed(self.root, "a" * 40))

    def test_capacity_inventory_pipeline_reaps_both_children(self):
        self.assert_bound(capacity_inventory, "GIT_HISTORY_TIMEOUT", lambda: capacity_inventory.history_size(self.root, ["HEAD"]))
        self.assertEqual(len(self.children), 2)

    def test_publication_git_plumbing(self):
        self.assert_bound(publication_git, "GIT_TIMEOUT", lambda: publication_git.bounded_git(self.root, "rev-list", "HEAD"), storage.ContractError)

    def test_publication_git_audit(self):
        with patch.object(publication_git, "git", return_value="a" * 40), \
                patch.object(publication_git, "command", return_value=b"100644 blob " + b"b" * 40 + b"\tsite/index.html\0"):
            self.assert_bound(publication_git, "GIT_AUDIT_TIMEOUT", lambda: publication_git.audit(self.root, "a" * 40))

    def test_check_components_inventory(self):
        self.assert_bound(check_components, "GIT_TIMEOUT", lambda: check_components.git_output(self.root, "ls-files", "-z"))

    def test_check_history_index(self):
        self.assert_bound(check_history, "GIT_STREAM_TIMEOUT", lambda: list(check_history.object_index(self.root, "a" * 40)))

    def test_benchmark_release_git(self):
        self.assert_bound(benchmark_release, "GIT_TIMEOUT", lambda: benchmark_release.git(self.root, "rev-parse", "HEAD"))

    def test_benchmark_release_child(self):
        self.assert_bound(benchmark_release, "UPDATE_TIMEOUT", lambda: benchmark_release.run_update(self.root))
        self.assertEqual(self.launches[0][0], sys.executable)
        self.assertEqual(Path(self.launches[0][1]).parent, self.root)

    def test_check_release_blob(self):
        self.assert_bound(check_release, "GIT_TIMEOUT", lambda: check_release.git(self.root, "show", "HEAD:site/index.html"))

    def test_check_extraction_raw_records(self):
        self.assert_bound(check_extraction, "GIT_STREAM_TIMEOUT", lambda: list(check_extraction.raw_records(self.root, "a" * 40, "Catalog/view.jsonl")))

    def test_check_extraction_tree(self):
        self.assert_bound(check_extraction, "GIT_TREE_TIMEOUT", lambda: check_extraction.pinned_objects(self.root, "a" * 40, ["world#1"]))

    def test_check_coded_values_source_text(self):
        rows = [{"fact_scope": "source-enumeration", "evidence": [{"path": "enum.cs"}]}]
        self.assert_bound(check_coded_values, "GIT_TIMEOUT", lambda: check_coded_values.check(self.root, "a" * 40, rows))

    def test_git_command_input_environment_and_output_are_preserved(self):
        index, tree = self.root / "index", self.root / "tree"
        original = bounded.start
        def launch(command, **options):
            self.assertEqual(command, ["git", "-C", str(self.root), "--literal-pathspecs", "hash-object", "-w", "--stdin"])
            self.assertEqual(options["env"]["GIT_INDEX_FILE"], str(index))
            self.assertEqual(options["env"]["GIT_WORK_TREE"], str(tree))
            return original([sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"], **options)
        with patch.object(bounded, "start", side_effect=launch):
            self.assertEqual(git_transaction.command(self.root, "hash-object", "-w", "--stdin", data=b"a\0b\n", index=index, work_tree=tree), b"a\0b\n")

    def test_capacity_pipeline_preserves_measurements(self):
        original = bounded.start
        def launch(command, **options):
            script = ("import sys; sys.stdout.buffer.write(b'a\\nb\\nc\\n')" if "rev-list" in command else
                      "import sys; rows=sys.stdin.buffer.read().splitlines(); assert rows == [b'a',b'b',b'c']; "
                      "sys.stdout.buffer.write(b'commit 10\\nblob 20\\nblob 30\\n')")
            return original([sys.executable, "-c", script], **options)
        with patch.object(bounded, "start", side_effect=launch):
            self.assertEqual(capacity_inventory.history_size(self.root, ["HEAD"]),
                             {"history_bytes": 60, "objects": 3, "blobs": 2, "largest_blob_bytes": 30})
