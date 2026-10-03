"""Release cleanup must prove an independent committed copy before unlinking."""

import json
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tests._support import fixture_dir

from wikibuild import release_retention
from wikibuild.storage import digest, git, json_bytes


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "release")
        self.repo = self.root / "repositories/topic"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Retention fixture")
        git(self.repo, "config", "user.email", "wiki@example.invalid")
        git(self.repo, "config", "core.autocrlf", "false")
        self.stage = self.root / ".local/rs/0123456789ab"
        self.stage.mkdir(parents=True)
        self.payloads = {"site/a.json": b'a' * 1048581, "site/b.json": b'b\n'}
        files = {}
        for name, data in self.payloads.items():
            for base in [self.repo, self.stage / "topic"]:
                path = base / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            files[name] = {"old": None, "new": digest(data), "bytes": len(data)}
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "Committed payloads")
        commit, tree = git(self.repo, "rev-parse", "HEAD"), git(self.repo, "rev-parse", "HEAD^{tree}")
        inputs = {"test": "retention"}
        result = {"schema_version": 1, "release_id": digest(json_bytes(inputs)), "inputs": inputs,
                  "repositories": {"topic": {"path": "repositories/topic", "commit": commit, "tree": tree}}}
        result["manifest_sha256"] = digest(json_bytes(result))
        (self.root / "releases").mkdir()
        (self.root / "releases" / (result["release_id"] + ".json")).write_bytes(json_bytes(result))
        self.plan = {"stage": ".local/rs/0123456789ab", "result": result,
                     "plans": {"topic": {"path": "repositories/topic",
                                         "git": {"commit": commit, "tree": tree, "files": files}}}}
        self.save_plan()
        self.pending = self.root / ".local/releases/pending.json"
        self.pending.parent.mkdir(parents=True)
        self.pending.write_bytes(json_bytes({"stage": self.plan["stage"], "complete": True}))

    def save_plan(self):
        (self.stage / "plan.json").write_bytes(json_bytes(self.plan))

    def test_committed_payloads_removed_unknown_and_diagnostics_preserved_repeat_has_no_git_reads(self):
        unknown = self.stage / "topic/notes.txt"
        unknown.write_text("User investigation")
        index = self.stage / "topic/commit.index"
        index.write_bytes(b"diagnostic index")
        head = git(self.repo, "rev-parse", "HEAD")
        result = release_retention.run(self.root)
        self.assertEqual(result["retained"], [])
        self.assertEqual(result["removed_bytes"], sum(map(len, self.payloads.values())))
        self.assertEqual(result["removed_files"], 2)
        for name, data in self.payloads.items():
            self.assertFalse((self.stage / "topic" / name).exists())
            self.assertEqual((self.repo / name).read_bytes(), data)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(unknown.read_text(), "User investigation")
        self.assertEqual(index.read_bytes(), b"diagnostic index")
        marker = self.root / ".local/releases/retention/0123456789ab.json"
        stamp = marker.stat().st_mtime_ns
        with patch.object(release_retention.git_transaction, "command", side_effect=AssertionError("Unexpected Git read")):
            again = release_retention.run(self.root)
        self.assertTrue(again["reused"])
        self.assertEqual(again["removed_files"], 0)
        self.assertEqual(marker.stat().st_mtime_ns, stamp)

    def test_changed_payload_is_retained_even_when_journal_hash_was_changed_to_match(self):
        path = self.stage / "topic/site/b.json"
        path.write_bytes(b'c\n')
        self.plan["plans"]["topic"]["git"]["files"]["site/b.json"]["new"] = digest(path.read_bytes())
        self.save_plan()
        result = release_retention.run(self.root)
        self.assertIn("committed copy", result["retained"][0]["reason"])
        self.assertTrue((self.stage / "topic/site/a.json").exists())
        self.assertEqual(path.read_bytes(), b'c\n')

    def test_pending_transaction_and_uncommitted_attempts_are_retained(self):
        self.pending.write_bytes(json_bytes({"stage": self.plan["stage"], "complete": False}))
        result = release_retention.run(self.root)
        self.assertIn("pending", result["retained"][0]["reason"])
        self.assertEqual(result["removed_files"], 0)
        self.pending.unlink()
        (self.root / "releases" / (self.plan["result"]["release_id"] + ".json")).unlink()
        result = release_retention.run(self.root)
        self.assertTrue(result["retained"])
        self.assertTrue((self.stage / "topic/site/a.json").exists())

    def test_partial_unlink_failure_retries_without_overriding_protection(self):
        original = Path.unlink
        target = self.stage / "topic/site/b.json"

        def protected(path, *args, **kwargs):
            if path == target:
                raise PermissionError("protected fixture payload")
            return original(path, *args, **kwargs)

        with patch.object(Path, "unlink", protected):
            first = release_retention.run(self.root)
        self.assertIn("protected fixture payload", first["retained"][0]["reason"])
        self.assertEqual(first["removed_files"], 1)
        self.assertEqual(first["removed_bytes"], len(self.payloads["site/a.json"]))
        self.assertFalse((self.stage / "topic/site/a.json").exists())
        self.assertTrue(target.exists())
        result = release_retention.run(self.root)
        self.assertEqual(result["retained"], [])
        self.assertEqual(result["removed_files"], 1)

    def test_path_escape_and_changed_destination_are_preserved(self):
        self.plan["plans"]["topic"]["git"]["files"]["../../outside"] = {"old": None, "new": "x", "bytes": 1}
        self.save_plan()
        result = release_retention.run(self.root)
        self.assertIn("Invalid staging path", result["retained"][0]["reason"])
        self.assertTrue((self.stage / "topic/site/a.json").exists())
        self.plan["plans"]["topic"]["path"] = "repositories/other"
        self.save_plan()
        result = release_retention.run(self.root)
        self.assertIn("destination differs", result["retained"][0]["reason"])

    def test_missing_committed_blob_prevents_removal(self):
        oid = git(self.repo, "rev-parse", "HEAD:site/b.json")
        original = release_retention.bounded.stream
        missing_seen = []

        @contextmanager
        def missing(command, **kwargs):
            with original(command, **kwargs) as child:
                if "cat-file" in command:
                    readline = child.stdout.readline
                    def reply(*args):
                        line = readline(*args)
                        if line.split()[:1] == [oid.encode()]:
                            missing_seen.append(oid)
                            return (oid + " missing\n").encode()
                        return line
                    with patch.object(child.stdout, "readline", new=reply):
                        yield child
                else:
                    yield child

        with patch.object(release_retention.bounded, "stream", new=missing):
            result = release_retention.run(self.root)
        self.assertEqual(missing_seen, [oid])
        self.assertIn("object is missing", result["retained"][0]["reason"])
        self.assertTrue((self.stage / "topic/site/a.json").exists())

    def test_redirected_stage_is_preserved(self):
        original = self.stage
        moved = original.with_name("saved-investigation")
        original.rename(moved)
        if os.name == "nt":
            # Directory junctions need no symlink privilege on this host.
            created = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(original), str(moved)], capture_output=True)
            self.assertEqual(created.returncode, 0, created.stderr.decode(errors="replace"))
        else:
            original.symlink_to(moved, target_is_directory=True)
        try:
            result = release_retention.run(self.root)
            self.assertTrue(any("Redirected staging path" in row["reason"] for row in result["retained"]))
            self.assertTrue((moved / "topic/site/a.json").exists())
        finally:
            if os.name == "nt":
                original.rmdir()  # Remove only this junction, never its target.
            else:
                original.unlink()


if __name__ == "__main__":
    unittest.main()
