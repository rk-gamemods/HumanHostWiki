"""Release cleanup must prove an independent committed copy before unlinking."""

import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tests._support import fixture_dir

from wikibuild import release_retention, staging
from wikibuild.storage import ContractError, digest, git, json_bytes


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
        (self.stage / staging.OWNER).write_bytes(json_bytes({"schema_version": 1, "stage": "release",
            "attempt_id": self.stage.name, "created_utc": "2026-01-01T00:00:00+00:00", "state": "completed"}))
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
        original = release_retention.git_transaction.command

        def missing(path, *args, **kwargs):
            if args[0] == "cat-file":
                return (oid + " missing\n").encode()
            return original(path, *args, **kwargs)

        with patch.object(release_retention.git_transaction, "command", side_effect=missing):
            result = release_retention.run(self.root)
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



class OwnedAttemptsTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "attempts")

    def test_stage_crash_retry_completion_and_unknown_directory(self):
        for stage in ("extraction", "history", "reader", "release"):
            with self.subTest(stage=stage):
                folder = self.root / stage
                unknown = folder / "unknown"
                unknown.mkdir(parents=True)
                (unknown / "evidence").write_text("keep")
                with self.assertRaises(SystemExit):
                    with staging.attempt(folder, stage) as failed:
                        (failed / "payload").write_bytes(b"partial")
                        owner = json.loads((failed / staging.OWNER).read_bytes())
                        self.assertEqual(owner["stage"], stage)
                        self.assertEqual(owner["attempt_id"], failed.name)
                        self.assertTrue(owner["created_utc"].endswith("+00:00"))
                        self.assertEqual(staging.record(failed, stage)[0]["state"], "materializing")
                        raise SystemExit("crash")
                self.assertEqual(staging.record(failed, stage)[0]["state"], "materializing")
                with staging.attempt(folder, stage) as completed:
                    self.assertEqual(staging.record(failed, stage)[0]["state"], "abandoned")
                    (completed / "payload").write_bytes(b"complete")
                    summary = staging.retire(folder, stage, current=completed)
                    self.assertTrue(completed.exists())
                    self.assertTrue(any(row["stage"] == "unknown" for row in summary["retained"]))
                self.assertEqual(staging.record(failed, stage)[0]["state"], "abandoned")
                self.assertEqual((completed / "payload").read_bytes(), b"complete")
                self.assertEqual(staging.record(completed, stage)[0]["state"], "completed")
                self.assertEqual(staging.retire(folder, stage)["removed"], [])
                with self.assertRaises(OSError):
                    with staging.attempt(folder, stage) as newest:
                        (newest / "payload").write_bytes(b"new failure")
                        raise OSError("failure")
                self.assertFalse(failed.exists())
                self.assertTrue(newest.exists())
                self.assertTrue(completed.exists())
                self.assertEqual((unknown / "evidence").read_text(), "keep")

    def test_n_consecutive_failures_leave_exactly_one_retained_per_stage(self):
        for stage in ("extraction", "history", "reader", "release"):
            for baseline in (False, True):
                for crash in (False, True):
                    with self.subTest(stage=stage, baseline=baseline, crash=crash):
                        folder = self.root / f"{stage}-{baseline}-{crash}"
                        completed = None
                        if baseline:
                            with staging.attempt(folder, stage) as completed:
                                (completed / "payload").write_bytes(b"success")
                        previous = None
                        for _ in range(6):
                            error = SystemExit if crash else OSError
                            with self.assertRaises(error):
                                with staging.attempt(folder, stage) as newest:
                                    (newest / "payload").write_bytes(b"partial")
                                    raise error("failure")
                            if crash:
                                self.assertEqual(staging.record(newest, stage)[0]["state"], "materializing")
                                staging.retire(folder, stage)  # Next locked recovery after the process exits.
                            failures = [path for path in folder.iterdir()
                                        if staging.record(path, stage)[0]["state"] != "completed"]
                            self.assertEqual(failures, [newest])
                            self.assertEqual(staging.record(newest, stage)[0]["state"], "abandoned")
                            if previous is not None:
                                self.assertFalse(previous.exists())
                            previous = newest
                            if completed is not None:
                                self.assertEqual((completed / "payload").read_bytes(), b"success")
                        self.assertEqual(staging.retire(folder, stage)["removed"], [])

    def test_current_foreign_invalid_and_completed_attempts_are_preserved(self):
        folder = self.root / "stages"
        with staging.attempt(folder, "reader") as completed:
            pass
        with staging.attempt(folder, "reader", deferred=True) as older:
            pass
        with staging.attempt(folder, "reader", deferred=True) as current:
            pass
        with staging.attempt(folder, "history", deferred=True) as foreign:
            pass
        bad = folder / ("b" * 32)
        bad.mkdir()
        (bad / staging.OWNER).write_text("{}")
        summary = staging.retire(folder, "reader", current=current)
        self.assertTrue(all(path.exists() for path in (completed, older, current, foreign, bad)))
        self.assertEqual(staging.record(current, "reader")[0]["state"], "materializing")
        self.assertTrue(any(row["stage"] == foreign.name for row in summary["retained"]))
        self.assertTrue(any(row["stage"] == bad.name for row in summary["retained"]))
        staging.retire(folder, "reader")
        self.assertEqual(staging.record(current, "reader")[0]["state"], "abandoned")
        self.assertFalse(older.exists())
        self.assertTrue(all(path.exists() for path in (completed, current, foreign, bad)))

    def test_bounded_read_only_retirement_and_interrupted_retry(self):
        folder = self.root / "stages"
        with self.assertRaises(OSError):
            with staging.attempt(folder, "reader") as failed:
                leaf = failed / "nested/data"
                leaf.parent.mkdir()
                leaf.write_text("partial")
                leaf.chmod(0o444)
                raise OSError("failure")
        with staging.attempt(folder, "reader", deferred=True) as newest:
            staging.finish(newest, "reader", "abandoned")
            with patch.object(staging, "MAX_ENTRIES", 2):
                summary = staging.retire(folder, "reader", current=newest)
                self.assertTrue(failed.exists())
                self.assertTrue(any("entry bound" in row["reason"] for row in summary["retained"]))
            original = Path.unlink
            def interrupt(path, *args, **kwargs):
                if path == leaf:
                    raise OSError("interrupted deletion")
                return original(path, *args, **kwargs)
            with patch.object(Path, "unlink", interrupt):
                summary = staging.retire(folder, "reader", current=newest)
            self.assertTrue(any("interrupted deletion" in row["reason"] for row in summary["retained"]))
            self.assertEqual(staging.record(failed, "reader")[0]["state"], "abandoned")
        self.assertFalse(failed.exists())
        self.assertTrue(newest.exists())

    def test_oversized_record_and_redirected_payload_are_preserved(self):
        folder = self.root / "stages"
        with self.assertRaises(OSError):
            with staging.attempt(folder, "reader") as failed:
                (failed / "payload").write_text("partial")
                raise OSError("failure")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "evidence").write_text("keep")
        redirect = failed / "redirect"
        if os.name == "nt":
            made = subprocess.run(["cmd", "/c", "mklink", "/J", str(redirect), str(outside)], capture_output=True)
            self.assertEqual(made.returncode, 0, made.stderr.decode(errors="replace"))
            self.addCleanup(redirect.rmdir)
        else:
            redirect.symlink_to(outside, target_is_directory=True)
            self.addCleanup(redirect.unlink)
        with staging.attempt(folder, "reader", deferred=True) as newest:
            staging.finish(newest, "reader", "abandoned")
            summary = staging.retire(folder, "reader", current=newest)
            self.assertTrue(any("Redirected" in row["reason"] for row in summary["retained"]))
            self.assertTrue((failed / "payload").exists())
            self.assertEqual((outside / "evidence").read_text(), "keep")
        oversized = folder / ("c" * 32)
        oversized.mkdir()
        (oversized / staging.OWNER).write_bytes(b" " * (staging.MAX_RECORD_BYTES + 1))
        summary = staging.retire(folder, "reader")
        self.assertTrue(any("read bound" in row["reason"] for row in summary["retained"]))
        self.assertTrue(oversized.exists())

    def test_ownership_becoming_completed_before_deletion_is_preserved(self):
        folder = self.root / "stages"
        with self.assertRaises(OSError):
            with staging.attempt(folder, "reader") as failed:
                (failed / "payload").write_text("keep")
                raise OSError("failure")
        original = staging.remove
        def changed(path, stage, owner):
            staging.finish(path, stage, "completed")
            return original(path, stage, owner)
        with patch.object(staging, "remove", side_effect=changed):
            with self.assertRaises(OSError):
                with staging.attempt(folder, "reader"):
                    raise OSError("new failure")
        self.assertEqual(staging.record(failed, "reader")[0]["state"], "completed")
        self.assertEqual((failed / "payload").read_text(), "keep")

if __name__ == "__main__":
    unittest.main()
