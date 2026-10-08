"""Converted callers time out actual owned stand-ins without network or repo writes."""

from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tests._support import fixture_dir
from tools import (benchmark_release, check_coded_values, check_components,
                   check_extraction, check_history, check_release)
from wikibuild import (bounded, capacity_inventory, git_transaction, ownership,
                      publication_git, source, storage)


class GitBoundsTests(unittest.TestCase):
    def test_lineage_expiry_stops_lookups_inside_one_buffered_block(self):
        revisions = [f"{number:040x}" for number in range(1, 5)]
        lookups, pins, timeouts = [], [], []
        elapsed = 0
        # Keep the virtual deadline arithmetic exact, independent of host uptime.
        started = 100.0
        clock = SimpleNamespace(monotonic=lambda: started + elapsed, sleep=time.sleep)

        def command(argv, **options):
            nonlocal elapsed
            args = argv[3:]
            timeouts.append(options["timeout"])
            if args[0] == "rev-parse":
                lookups.append(args[1].removesuffix("^{tree}"))
                elapsed += min(3, max(0, 5 - elapsed))
                output = args[1].encode()
            elif args[0] == "show-ref":
                pins.append(args[-1].rsplit("/", 1)[-1])
                output = pins[-1].encode()
            else:
                self.assertEqual(args[0], "cat-file")
                output = b""
            return subprocess.CompletedProcess(argv, 0, output, b"")

        def launch(argv, **options):
            self.assertEqual(argv[3:], ["rev-list", "--reverse", revisions[-1]])
            # All revisions fit in one stdout block; advancing the iterator
            # cannot enforce the deadline between these buffered records.
            data = "\n".join(revisions).encode() + b"\n"
            child = self.original([sys.executable, "-c", f"import sys; sys.stdout.buffer.write({data!r})"], **options)
            self.children.append(child)
            return child

        with patch.object(publication_git, "GIT_LINEAGE_TIMEOUT", 5), \
                patch.object(publication_git, "time", clock), \
                patch.object(bounded, "time", clock), patch.object(bounded, "run", side_effect=command), \
                patch.object(bounded, "start", side_effect=launch):
            with self.assertRaises(subprocess.TimeoutExpired):
                publication_git.owned_lineage(self.root, None, revisions[-1], provenance=set(revisions))
        self.assertEqual(lookups, revisions[:2])
        self.assertEqual(pins, revisions[:1])
        self.assertEqual(timeouts, [5, 5, 2, 2])
        self.assertFalse(storage.process_running(self.children[0].pid))
        self.assertEqual(bounded._children, set())

    def test_long_owned_lineage_has_a_whole_history_budget(self):
        revisions = [f"{number:040x}" for number in range(1, 257)]
        checked = []
        elapsed = 0
        started = time.monotonic()
        clock = SimpleNamespace(monotonic=lambda: started + elapsed, sleep=time.sleep)

        def command(argv, **options):
            nonlocal elapsed
            self.assertEqual(options["timeout"], publication_git.GIT_TIMEOUT)
            args = argv[3:]
            if args[0] == "rev-parse":
                checked.append(args[1].removesuffix("^{tree}"))
                # Each valid per-commit lookup costs a virtual second. This
                # exceeds the plumbing budget without a slow test or network.
                elapsed += 1
                output = args[1].encode()
            else:
                self.assertIn(args[0], {"cat-file", "show-ref"})
                output = args[-1].rsplit("/", 1)[-1].encode() if args[0] == "show-ref" else b""
            return subprocess.CompletedProcess(argv, 0, output, b"")

        def launch(argv, **options):
            self.assertEqual(argv[3:], ["rev-list", "--reverse", revisions[-1]])
            script = "import sys; sys.stdout.buffer.write(" + repr("\n".join(revisions).encode() + b"\n") + ")"
            child = self.original([sys.executable, "-c", script], **options)
            self.children.append(child)
            return child

        with patch.object(bounded, "run", side_effect=command), \
                patch.object(bounded, "start", side_effect=launch), patch.object(bounded, "time", clock), \
                patch.object(publication_git, "time", clock):
            self.assertTrue(publication_git.owned_lineage(self.root, None, revisions[-1], provenance=set(revisions)))
        self.assertEqual(checked, revisions)
        self.assertGreater(elapsed, publication_git.GIT_TIMEOUT)
        self.assertFalse(storage.process_running(self.children[0].pid))
        self.assertEqual(bounded._children, set())

    def test_valid_public_tree_and_source_are_complete_beyond_capture_limit(self):
        storage.git(self.root, "init", "-q")
        storage.git(self.root, "config", "user.name", "Fixture")
        storage.git(self.root, "config", "user.email", "fixture@example.invalid")
        oid = git_transaction.command(self.root, "hash-object", "-w", "--stdin", data=b"public\n").decode().strip()
        entries = b"".join(f"100644 blob {oid}\t{name}\0".encode() for name in (".gitattributes", "README.md"))
        tree = git_transaction.command(self.root, "mktree", "-z", data=entries).decode().strip()
        commit = git_transaction.command(self.root, "commit-tree", tree, data=b"Valid fixture\n").decode().strip()
        with patch.object(bounded, "MAX_CAPTURE", 64):
            self.assertEqual(publication_git.audit(self.root, commit), {"commits": 1, "blobs": 1})
            reader = source.Source(self.root, commit)
        self.assertEqual(set(reader.blobs), {".gitattributes", "README.md"})

    def test_public_audit_rejects_forbidden_path_beyond_capture_limit(self):
        storage.git(self.root, "init", "-q")
        storage.git(self.root, "config", "user.name", "Fixture")
        storage.git(self.root, "config", "user.email", "fixture@example.invalid")
        oid = git_transaction.command(self.root, "hash-object", "-w", "--stdin", data=b"public\n").decode().strip()
        approved = f"100644 blob {oid}\tREADME.md\0".encode()
        entries = approved + f"100644 blob {oid}\tzz-private.txt\0".encode()
        tree = git_transaction.command(self.root, "mktree", "-z", data=entries).decode().strip()
        commit = git_transaction.command(self.root, "commit-tree", tree, data=b"Audit fixture\n").decode().strip()
        with patch.object(bounded, "MAX_CAPTURE", len(approved)):
            with self.assertRaisesRegex(storage.ContractError, "Unapproved public history path: zz-private.txt"):
                publication_git.audit(self.root, commit)

    def test_real_interrupted_git_writer_recovers_without_deleting_foreign_index_lock(self):
        storage.git(self.root, "init", "-q")
        storage.git(self.root, "config", "user.name", "Fixture")
        storage.git(self.root, "config", "user.email", "fixture@example.invalid")
        (self.root / ".gitignore").write_bytes(b".local/\n")
        old, new = b"old\n", b"new\n"
        (self.root / "note.txt").write_bytes(old)
        storage.git(self.root, "add", ".gitignore", "note.txt")
        storage.git(self.root, "commit", "-qm", "Fixture baseline")
        lock = self.root / ".git/index.lock"
        lock.write_bytes(b"foreign client owns this lock\n")
        ready = threading.Event()
        original = bounded.start

        def launch(*args, **kwargs):
            child = original(*args, **kwargs)
            self.children.append(child)
            return child

        def partial_input(pipe, data):
            try:
                pipe.write(data)
                pipe.flush()
                ready.set()
                # Keep real Git inside its stdin write operation until the
                # command bound kills it. The feeder then closes its own pipe.
                self.children[-1].wait(timeout=5)
            finally:
                pipe.close()

        with patch.object(git_transaction, "GIT_TIMEOUT", 0.5), \
                patch.object(bounded, "start", new=launch), patch.object(bounded, "_feed", new=partial_input):
            with self.assertRaises(subprocess.TimeoutExpired):
                git_transaction.command(self.root, "hash-object", "-w", "--stdin", data=b"x" * (1 << 20))
        self.assertTrue(ready.is_set(), "Git must have received partial input before interruption")
        self.assertFalse(storage.process_running(self.children[-1].pid))
        self.assertEqual(bounded._children, set())
        self.assertEqual(lock.read_bytes(), b"foreign client owns this lock\n")
        stage = fixture_dir(self, "recovery")
        (stage / "note.txt").write_bytes(new)
        files = {"note.txt": {"old": storage.digest(old), "new": storage.digest(new), "bytes": len(new)}}
        plan = git_transaction.prepare(self.root, stage, files, "Recovered fixture")
        with self.assertRaisesRegex(storage.ContractError, "index.lock"):
            git_transaction.promote(self.root, stage, plan)
        self.assertEqual(lock.read_bytes(), b"foreign client owns this lock\n")
        # Simulate the foreign owner releasing its fixture-owned lock, then
        # retry the same recorded transaction twice to prove safe recovery.
        lock.unlink()
        git_transaction.promote(self.root, stage, plan)
        git_transaction.promote(self.root, stage, plan)
        self.assertEqual(storage.git(self.root, "rev-parse", "HEAD"), plan["commit"])
        self.assertEqual(storage.git(self.root, "status", "--porcelain=v1"), "")

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

    def test_check_extraction_rejects_partial_output_with_silent_nonzero_exit(self):
        original = bounded.start

        def launch(command, **options):
            self.assertEqual(command, ["git", "-C", str(self.root), "show", "a" * 40 + ":Catalog/view.jsonl"])
            script = "import sys; sys.stdout.buffer.write(b'{\"id\":\"fixture#1\"}\\n'); sys.stdout.buffer.flush(); sys.exit(17)"
            child = original([sys.executable, "-c", script], **options)
            self.children.append(child)
            return child

        with patch.object(bounded, "start", side_effect=launch):
            records = check_extraction.raw_records(self.root, "a" * 40, "Catalog/view.jsonl")
            self.assertEqual(next(records)[0], {"id": "fixture#1"})
            with self.assertRaisesRegex(ValueError, "Raw source read failed: Catalog/view.jsonl: Git exit 17"):
                next(records)
        self.assertEqual(self.children[0].returncode, 17)
        self.assertFalse(storage.process_running(self.children[0].pid))
        self.assertEqual(bounded._children, set())

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
