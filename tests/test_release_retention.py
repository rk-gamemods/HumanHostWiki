"""Release cleanup must prove an independent committed copy before unlinking."""

import json
from contextlib import contextmanager
import os
import stat
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests._support import fixture_dir

from wikibuild import release_retention, staging
from wikibuild.storage import ContractError, digest, git, json_bytes


STAGING_CHILD = r'''
import os
from pathlib import Path
import sys
from wikibuild import staging
from wikibuild.storage import json_bytes, write_changed

root, point, stage = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
folder = root / "stages"
def terminate(reached):
    if reached == point:
        (root / "death-point").write_text(reached)
        os._exit(73)
staging._checkpoint = terminate  # Test-only hook; production has no exit switch.
if point == "ownership-renamed":
    directory_sync = staging._sync_directory
    def after_ownership_rename(directory):
        if directory.parent == folder and (directory / staging.OWNER).is_file():
            terminate("ownership-renamed")  # Rename happened; attempt-directory fsync has not.
        directory_sync(directory)
    staging._sync_directory = after_ownership_rename
try:
    if point in {"retirement-recorded", "owner-removed", "directory-removed"}:
        staging.retire(folder, stage)
    else:
        with staging.attempt(folder, stage, short=stage == "release", deferred=True) as path:
            payload = path / "payload"
            payload.mkdir()
            (payload / "data").write_bytes(b"new output")
            if point in {"promoted", "promotion-completed"}:
                os.rename(payload, root / "promoted")
                terminate("promoted")
                staging.finish(path, stage, "completed")
                terminate("promotion-completed")
            elif point in {"pending", "pending-completed"}:
                write_changed(root / "pending.json", json_bytes({"stage": path.name, "complete": False}))
                terminate("pending")
                staging.finish(path, stage, "completed")
                terminate("pending-completed")
finally:
    (root / "finally-ran").write_text("unexpected graceful exit")
'''


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

    def legacy_completed(self):
        self.assertEqual(release_retention.run(self.root)["retained"], [])
        (self.stage / staging.OWNER).unlink()
        for name in ("commit.index", "commit.paths"):
            (self.stage / "topic" / name).write_bytes(b"retained preparation metadata")

    def test_completed_legacy_metadata_is_preserved_without_warning_or_fabricated_owner(self):
        self.legacy_completed()
        before = {path.relative_to(self.stage): (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.stage.rglob("*") if path.is_file()}
        for _ in range(2):
            result = release_retention.run(self.root)
            self.assertEqual(result["retained"], [])
            self.assertTrue(result["reused"])
            self.assertEqual(result["removed_files"], 0)
            self.assertFalse((self.stage / staging.OWNER).exists())
            self.assertEqual(before, {path.relative_to(self.stage): (path.read_bytes(), path.stat().st_mtime_ns)
                                      for path in self.stage.rglob("*") if path.is_file()})

    def test_new_release_attempt_preserves_validated_legacy_completion(self):
        self.legacy_completed()
        before = {path: path.read_bytes() for path in self.stage.rglob("*") if path.is_file()}
        callback = lambda path: release_retention.completed_legacy(self.root, path)
        with staging.attempt(self.stage.parent, "release", short=True, retained_completed=callback) as current:
            self.assertTrue((current / staging.OWNER).is_file())
            report = json.loads(self.stage.parent.with_name("rs-retention.json").read_bytes())
            self.assertEqual(report["retained"], [])
        self.assertEqual(json.loads(self.stage.parent.with_name("rs-retention.json").read_bytes())["retained"], [])
        self.assertEqual(before, {path: path.read_bytes() for path in self.stage.rglob("*") if path.is_file()})
        self.assertFalse((self.stage / staging.OWNER).exists())

    def test_legacy_completion_planning_does_not_stat_absent_payloads(self):
        self.legacy_completed()
        original = Path.lstat
        missing = {self.stage / "topic" / name for name in self.payloads}
        def metadata_only(path, *args, **kwargs):
            if path in missing:
                raise AssertionError("Deleted payload must not be statted during metadata planning")
            return original(path, *args, **kwargs)
        with patch.object(Path, "lstat", new=metadata_only):
            self.assertTrue(release_retention.completed_legacy(self.root, self.stage))

    def test_rehashed_legacy_plan_cannot_add_escaping_payload_paths(self):
        self.legacy_completed()
        marker = self.root / ".local/releases/retention" / (self.stage.name + ".json")
        original = dict(self.plan["plans"]["topic"]["git"]["files"])
        for name in ("../../outside", "/absolute", "site\\outside", "C:/outside"):
            with self.subTest(name=name):
                self.plan["plans"]["topic"]["git"]["files"] = {**original, name: {"old": None, "new": "x", "bytes": 1}}
                self.save_plan()
                receipt = json.loads(marker.read_bytes())
                receipt["plan_sha256"] = digest((self.stage / "plan.json").read_bytes())
                marker.write_bytes(json_bytes(receipt))
                with self.assertRaisesRegex(ContractError, "Invalid staging path"):
                    release_retention.completed_legacy(self.root, self.stage)

    def test_legacy_completion_rejects_redirected_existing_directory(self):
        self.legacy_completed()
        redirect = self.stage / "topic/site"
        redirect.rmdir()
        investigation = self.root / "investigation"
        investigation.mkdir()
        (investigation / "notes.txt").write_text("preserve external investigation")
        if os.name == "nt":
            created = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(redirect), str(investigation)], capture_output=True)
            self.assertEqual(created.returncode, 0, created.stderr.decode(errors="replace"))
        else:
            redirect.symlink_to(investigation, target_is_directory=True)
        try:
            with self.assertRaisesRegex(ContractError, "Redirected staging path"):
                release_retention.completed_legacy(self.root, self.stage)
            self.assertEqual((investigation / "notes.txt").read_text(), "preserve external investigation")
        finally:
            if os.name == "nt":
                redirect.rmdir()
            else:
                redirect.unlink()

    def test_legacy_journal_receipt_and_stage_mismatches_remain_warned_and_preserved(self):
        self.legacy_completed()
        journal = self.stage / "plan.json"
        marker = self.root / ".local/releases/retention" / (self.stage.name + ".json")
        receipt = self.root / "releases" / (self.plan["result"]["release_id"] + ".json")
        originals = {path: path.read_bytes() for path in (journal, marker, receipt)}
        cases = [(journal, {**self.plan, "unknown": "changed journal"}),
                 (journal, {**self.plan, "stage": ".local/rs/ffffffffffff"}),
                 (marker, {**json.loads(originals[marker]), "release_id": "f" * 64}),
                 (receipt, {**self.plan["result"], "manifest_sha256": "f" * 64})]
        for changed, value in cases:
            with self.subTest(path=changed.name, value=value):
                for path, original in originals.items():
                    path.write_bytes(original)
                changed.write_bytes(json_bytes(value))
                before = {path: path.read_bytes() for path in self.stage.rglob("*") if path.is_file()}
                result = release_retention.run(self.root)
                self.assertTrue(result["retained"])
                self.assertEqual(result["removed_files"], 0)
                self.assertEqual(before, {path: path.read_bytes() for path in self.stage.rglob("*") if path.is_file()})

    def test_uncompleted_legacy_and_unknown_stages_keep_their_warnings(self):
        self.legacy_completed()
        receipt = self.root / "releases" / (self.plan["result"]["release_id"] + ".json")
        receipt.unlink()
        unknown = self.stage.with_name("ffffffffffff")
        unknown.mkdir()
        (unknown / "operator-notes.txt").write_text("preserve ambiguous work")
        result = release_retention.run(self.root)
        self.assertEqual({row["stage"] for row in result["retained"]}, {self.stage.name, unknown.name})
        self.assertEqual(result["removed_files"], 0)
        self.assertEqual((unknown / "operator-notes.txt").read_text(), "preserve ambiguous work")

    def test_extra_legacy_files_cannot_be_hidden_by_completed_journal_evidence(self):
        self.legacy_completed()
        unknown = self.stage / "topic/operator-notes.txt"
        unknown.write_text("preserve ambiguous work")
        result = release_retention.run(self.root)
        self.assertTrue(result["retained"])
        self.assertEqual(result["removed_files"], 0)
        self.assertEqual(unknown.read_text(), "preserve ambiguous work")

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



class OwnedAttemptsTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "attempts")

    def crash(self, point, *, stage="reader"):
        root = fixture_dir(self, "death")
        folder = root / "stages"
        with staging.attempt(folder, stage) as completed:
            (completed / "output").write_bytes(b"completed output")
        completed_bytes = {path.name: path.read_bytes() for path in completed.iterdir()}
        unknown = folder / "unknown"
        unknown.mkdir()
        (unknown / "evidence").write_bytes(b"unrecognized output")
        target = None
        if point in {"retirement-recorded", "owner-removed", "directory-removed"}:
            with staging.attempt(folder, stage, deferred=True) as target:
                (target / "payload").write_bytes(b"partial")
            # A newer failure makes target eligible without invoking retirement yet.
            newest = folder / ("e" * 32)
            newest.mkdir()
            staging.write_record(newest, stage, {"schema_version": 1, "stage": stage,
                "attempt_id": newest.name, "created_utc": "2099-01-01T00:00:00+00:00", "state": "abandoned"})
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        process = subprocess.run([sys.executable, "-B", "-c", STAGING_CHILD, str(root), point, stage],
                                 cwd=root, env=environment, capture_output=True, text=True)
        self.assertEqual(process.returncode, 73, process.stdout + process.stderr)
        self.assertEqual((root / "death-point").read_text(), point)
        self.assertFalse((root / "finally-ran").exists())
        if point == "registration-intent":
            owner = json.loads(self.recovery_records(folder)[0].read_bytes())["owner"]
            self.assertFalse((folder / owner["attempt_id"]).exists())
        if target is None and point != "registration-intent":
            target = next(path for path in folder.iterdir() if path not in (completed, unknown))
        return root, folder, target, completed, completed_bytes

    def recovery_records(self, folder):
        records = folder.with_name(folder.name + "-records")
        return list(records.iterdir()) if records.exists() else []

    def assert_completed_and_unknown(self, folder, completed, completed_bytes):
        self.assertEqual({path.name: path.read_bytes() for path in completed.iterdir()}, completed_bytes)
        self.assertEqual((folder / "unknown/evidence").read_bytes(), b"unrecognized output")

    def test_process_death_during_creation_promotion_and_pending_persistence(self):
        for point in ("registration-intent", "directory-created", "registered", "owned",
                      "promoted", "promotion-completed", "pending", "pending-completed"):
            with self.subTest(point=point):
                stage = "release" if point.startswith("pending") else "reader"
                root, folder, target, completed, completed_bytes = self.crash(point, stage=stage)
                pending_bytes = (root / "pending.json").read_bytes() if point.startswith("pending") else None
                first = staging.retire(folder, stage)
                second = staging.retire(folder, stage)
                self.assert_completed_and_unknown(folder, completed, completed_bytes)
                self.assertEqual(second["removed"], [])
                if point == "registered":
                    self.assertFalse(target.exists())
                    self.assertEqual(first["removed"], [target.name])
                else:
                    self.assertEqual(first["removed"], [])
                    if target is not None:
                        self.assertTrue(target.exists())
                        if point != "directory-created":
                            state = "completed" if point.endswith("completed") else "abandoned"
                            self.assertEqual(staging.record(target, stage)[0]["state"], state)
                self.assertEqual(len(self.recovery_records(folder)), int(point == "directory-created"))
                if point.startswith("promot"):
                    self.assertEqual((root / "promoted/data").read_bytes(), b"new output")
                if pending_bytes is not None:
                    self.assertEqual((root / "pending.json").read_bytes(), pending_bytes)
                    self.assertEqual(json.loads(pending_bytes)["stage"], target.name)
                    self.assertEqual((target / "payload/data").read_bytes(), b"new output")

    def test_process_death_during_final_removal_finishes_tombstone_cleanup(self):
        for point in ("retirement-recorded", "owner-removed", "directory-removed"):
            with self.subTest(point=point):
                root, folder, target, completed, completed_bytes = self.crash(point)
                receipts = self.recovery_records(folder)
                self.assertEqual(len(receipts), 1)
                self.assertEqual(json.loads(receipts[0].read_bytes())["kind"], "retirement")
                self.assertEqual(target.exists(), point != "directory-removed")
                if target.exists():
                    self.assertEqual((target / staging.OWNER).exists(), point == "retirement-recorded")
                staging.retire(folder, "reader")
                self.assertFalse(target.exists())
                self.assertEqual(self.recovery_records(folder), [])
                self.assertEqual(staging.retire(folder, "reader")["removed"], [])
                self.assert_completed_and_unknown(folder, completed, completed_bytes)

    def test_record_consumption_syncs_stage_root_and_retries_after_fsync_failure(self):
        for point in ("registered", "owned", "retirement-recorded", "owner-removed",
                      "directory-removed", "registration-intent"):
            with self.subTest(point=point):
                root, folder, target, completed, completed_bytes = self.crash(point)
                receipt = self.recovery_records(folder)[0]
                receipt_bytes = receipt.read_bytes()
                syncs, consumed, persisted = [], [], []
                unlink = Path.unlink

                def sync(directory):
                    syncs.append(directory)
                    if directory == folder and not consumed:
                        self.assertTrue(receipt.exists())
                        if syncs.count(folder) == 1:
                            raise OSError("stage root fsync failed")
                    elif directory == receipt.parent and not receipt.exists():
                        persisted.append(directory)

                def consume(path, *args, **kwargs):
                    if path == receipt:
                        self.assertTrue(syncs, "stage root must be synced before record removal")
                        self.assertEqual(syncs[-1], folder)
                        self.assertGreater(syncs.count(folder), 1)
                        self.assertEqual(path.read_bytes(), receipt_bytes)
                        consumed.append(path)
                    return unlink(path, *args, **kwargs)

                with patch.object(staging, "_sync_directory", side_effect=sync), \
                        patch.object(Path, "unlink", new=consume):
                    first = staging.retire(folder, "reader")
                    self.assertTrue(any("stage root fsync failed" in row["reason"]
                                        for row in first["retained"]))
                    self.assertEqual(receipt.read_bytes(), receipt_bytes)
                    self.assertEqual(consumed, [])
                    if target is not None:
                        self.assertEqual(target.exists(), point == "owned")
                    staging.retire(folder, "reader")
                self.assertEqual(consumed, [receipt])
                self.assertEqual(persisted, [receipt.parent])
                self.assertEqual(self.recovery_records(folder), [])
                self.assertEqual(staging.retire(folder, "reader")["removed"], [])
                self.assert_completed_and_unknown(folder, completed, completed_bytes)

    def test_new_attempt_syncs_stage_root_before_consuming_registration(self):
        folder = self.root / "stages"
        records = folder.with_name(folder.name + "-records")
        syncs, consumed = [], []
        unlink = Path.unlink

        def consume(path, *args, **kwargs):
            if path.parent == records and path.suffix == ".json":
                self.assertIn(folder / path.stem, syncs)
                self.assertEqual(syncs[-1], folder)
                self.assertEqual(staging.record(folder / path.stem, "reader")[0],
                                 json.loads(path.read_bytes())["owner"])
                consumed.append(path)
            return unlink(path, *args, **kwargs)

        with patch.object(staging, "_sync_directory", side_effect=syncs.append), \
                patch.object(Path, "unlink", new=consume):
            with staging.attempt(folder, "reader") as target:
                self.assertEqual(consumed, [records / (target.name + ".json")])
                self.assertEqual(self.recovery_records(folder), [])
        self.assertEqual(staging.record(target, "reader")[0]["state"], "completed")

    def test_registration_recovery_syncs_ownership_before_consumption(self):
        for point in ("ownership-renamed", "owned"):
            with self.subTest(point=point):
                root, folder, target, completed, completed_bytes = self.crash(point)
                receipt = self.recovery_records(folder)[0]
                receipt_bytes = receipt.read_bytes()
                marker_bytes = (target / staging.OWNER).read_bytes()
                syncs, consumed = [], []
                unlink = Path.unlink

                def sync(directory):
                    syncs.append(directory)
                    if directory == target and not consumed:
                        self.assertEqual(receipt.read_bytes(), receipt_bytes)
                        self.assertEqual((target / staging.OWNER).read_bytes(), marker_bytes)
                        if syncs.count(target) == 1:
                            raise OSError("ownership directory fsync failed")

                def consume(path, *args, **kwargs):
                    if path == receipt:
                        self.assertGreater(syncs.count(target), 1)
                        self.assertEqual(syncs[-1], folder)
                        self.assertEqual((target / staging.OWNER).read_bytes(), marker_bytes)
                        consumed.append(path)
                    return unlink(path, *args, **kwargs)

                with patch.object(staging, "_sync_directory", side_effect=sync), \
                        patch.object(Path, "unlink", new=consume):
                    first = staging.retire(folder, "reader")
                    self.assertTrue(any("ownership directory fsync failed" in row["reason"]
                                        for row in first["retained"]))
                    self.assertEqual(consumed, [])
                    self.assertEqual(receipt.read_bytes(), receipt_bytes)
                    self.assertEqual((target / staging.OWNER).read_bytes(), marker_bytes)
                    staging.retire(folder, "reader")
                self.assertEqual(consumed, [receipt])
                self.assertEqual(self.recovery_records(folder), [])
                self.assertEqual(staging.record(target, "reader")[0]["state"], "abandoned")
                self.assertEqual(staging.retire(folder, "reader")["removed"], [])
                self.assert_completed_and_unknown(folder, completed, completed_bytes)

    def test_record_consumption_preserves_redirected_records_and_replaced_receipts(self):
        for change in ("redirected-directory", "replaced-directory", "replaced-receipt", "redirected-during-sync"):
            with self.subTest(change=change):
                root, folder, target, completed, completed_bytes = self.crash("retirement-recorded")
                receipt = self.recovery_records(folder)[0]
                records = receipt.parent
                receipt_bytes = receipt.read_bytes()
                saved = root / "saved-records"
                outside = root / "outside"
                outside.mkdir()
                unrelated = outside / receipt.name
                unrelated.write_bytes(b"unrelated outside file")
                changed, armed = [], []
                directory_sync = staging._sync_directory

                def replace(point):
                    if point == "directory-removed" and change == "redirected-during-sync":
                        armed.append(point)
                    if point != "retirement-recorded" or change == "redirected-during-sync" and not armed:
                        return
                    changed.append(point)
                    if change == "replaced-receipt":
                        receipt.rename(root / "saved-receipt.json")
                        receipt.write_bytes(receipt_bytes)
                    else:
                        records.rename(saved)
                        if change == "replaced-directory":
                            records.mkdir()
                            receipt.write_bytes(receipt_bytes)
                        elif os.name == "nt":
                            created = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(records), str(outside)],
                                                     capture_output=True)
                            self.assertEqual(created.returncode, 0, created.stderr.decode(errors="replace"))
                        else:
                            records.symlink_to(outside, target_is_directory=True)

                def sync(directory):
                    directory_sync(directory)
                    if directory == folder and armed:
                        replace("retirement-recorded")
                        armed.clear()

                try:
                    with patch.object(staging, "_checkpoint", side_effect=replace), \
                            patch.object(staging, "_sync_directory", side_effect=sync):
                        summary = staging.retire(folder, "reader")
                    self.assertEqual(changed, ["retirement-recorded"])
                    self.assertTrue(any("Redirected" in row["reason"] or "recovery record changed" in row["reason"]
                                        for row in summary["retained"]))
                    self.assertEqual(unrelated.read_bytes(), b"unrelated outside file")
                    if change == "replaced-receipt":
                        self.assertEqual((root / "saved-receipt.json").read_bytes(), receipt_bytes)
                    else:
                        self.assertEqual((saved / receipt.name).read_bytes(), receipt_bytes)
                    if not change.startswith("redirected-"):
                        self.assertEqual(receipt.read_bytes(), receipt_bytes)
                    self.assert_completed_and_unknown(folder, completed, completed_bytes)
                finally:
                    if change.startswith("redirected-") and changed:
                        if os.name == "nt":
                            records.rmdir()  # Remove only this junction, never its target.
                        else:
                            records.unlink()

    def test_first_use_registration_death_recovers_without_a_stage_root(self):
        root = fixture_dir(self, "first-use")
        folder = root / "stages"
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        process = subprocess.run([sys.executable, "-B", "-c", STAGING_CHILD, str(root), "registration-intent", "reader"],
                                 cwd=root, env=environment, capture_output=True, text=True)
        self.assertEqual(process.returncode, 73, process.stdout + process.stderr)
        self.assertEqual((root / "death-point").read_text(), "registration-intent")
        self.assertFalse((root / "finally-ran").exists())
        self.assertFalse(folder.exists())
        receipt = self.recovery_records(folder)[0]
        receipt_bytes = receipt.read_bytes()
        self.assertEqual(json.loads(receipt_bytes)["kind"], "registration")
        self.assertIsNone(json.loads(receipt_bytes)["directory"])
        syncs, consumed = [], []
        unlink = Path.unlink

        def sync(directory):
            syncs.append(directory)
            if not directory.is_dir():  # Simulate POSIX's missing-directory error on Windows too.
                raise FileNotFoundError(directory)

        def consume(path, *args, **kwargs):
            if path == receipt:
                self.assertEqual(syncs[-1], receipt.parent.parent)
                self.assertEqual(path.read_bytes(), receipt_bytes)
                consumed.append(path)
            return unlink(path, *args, **kwargs)

        with patch.object(staging, "_sync_directory", side_effect=sync), \
                patch.object(Path, "unlink", new=consume):
            for _ in range(2):
                self.assertEqual(staging.retire(folder, "reader"), {"removed": [], "retained": []})
        self.assertEqual(consumed, [receipt])
        self.assertEqual(syncs, [receipt.parent.parent, receipt.parent])
        self.assertFalse(folder.exists())
        self.assertEqual(self.recovery_records(folder), [])

    def test_recovery_records_never_remove_replaced_directories_even_with_valid_ownership(self):
        for point in ("registered", "owner-removed"):
            with self.subTest(point=point):
                root, folder, target, completed, completed_bytes = self.crash(point)
                receipt = self.recovery_records(folder)[0]
                data = receipt.read_bytes()
                owner = json.loads(data)["owner"]
                target.rename(root / "original-directory")
                target.mkdir()
                (target / "evidence").write_bytes(b"replacement")
                staging.write_record(target, "reader", owner)
                newest = folder / ("d" * 32)
                newest.mkdir()
                staging.write_record(newest, "reader", {**owner, "attempt_id": newest.name,
                    "created_utc": "2099-02-01T00:00:00+00:00", "state": "abandoned"})
                for _ in range(2):
                    summary = staging.retire(folder, "reader")
                    self.assertTrue(any("identity does not match" in row["reason"] for row in summary["retained"]))
                    self.assertEqual((target / "evidence").read_bytes(), b"replacement")
                    self.assertEqual(receipt.read_bytes(), data)
                    self.assert_completed_and_unknown(folder, completed, completed_bytes)

    def test_retirement_recovery_rechecks_identity_before_deleting_replacement_payload(self):
        root, folder, target, completed, completed_bytes = self.crash("retirement-recorded")
        receipt = self.recovery_records(folder)[0]
        receipt_bytes = receipt.read_bytes()
        owner_bytes = (target / staging.OWNER).read_bytes()
        remove = staging.remove
        swapped = []

        def replace_before_removal(path, stage, owner, **kwargs):
            self.assertEqual(path, target)
            path.rename(root / "original-directory")
            path.mkdir()
            (path / staging.OWNER).write_bytes(owner_bytes)
            (path / "payload").write_bytes(b"replacement payload")
            swapped.append(path)
            return remove(path, stage, owner, **kwargs)

        with patch.object(staging, "remove", side_effect=replace_before_removal):
            summary = staging.retire(folder, "reader")
        self.assertEqual(swapped, [target])
        self.assertTrue(any("changed" in row["reason"] for row in summary["retained"]))
        for _ in range(2):
            self.assertEqual((target / "payload").read_bytes(), b"replacement payload")
            self.assertEqual((target / staging.OWNER).read_bytes(), owner_bytes)
            self.assertEqual(receipt.read_bytes(), receipt_bytes)
            self.assert_completed_and_unknown(folder, completed, completed_bytes)
            staging.retire(folder, "reader")

    def test_markerless_recovery_only_rmdirs_recreated_directory_with_reused_identity(self):
        for point in ("registered", "owner-removed"):
            with self.subTest(point=point):
                root, folder, target, completed, completed_bytes = self.crash(point)
                receipt = self.recovery_records(folder)[0]
                value = json.loads(receipt.read_bytes())
                value["directory"][2] = None  # Linux stat has no stable birth time.
                receipt.write_bytes(json_bytes(value))
                receipt_bytes = receipt.read_bytes()
                target.rmdir()  # Release the original inode, rather than keeping it allocated by rename.
                target.mkdir()
                (target / "evidence").write_bytes(b"replacement content")
                target.chmod(stat.S_IREAD | stat.S_IEXEC)
                self.addCleanup(target.chmod, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
                identity = staging._directory_identity
                rmdir = Path.rmdir
                rmdir_calls = []

                def recycled(path):
                    return value["directory"] if path == target else identity(path)

                def empty_only(path):
                    rmdir_calls.append(path)
                    return rmdir(path)

                with patch.object(staging, "_directory_identity", side_effect=recycled), \
                        patch.object(staging, "remove", side_effect=AssertionError("markerless recovery must not recurse")), \
                        patch.object(Path, "chmod", side_effect=AssertionError("markerless recovery must not change protection")), \
                        patch.object(Path, "rmdir", new=empty_only):
                    for _ in range(2):
                        summary = staging.retire(folder, "reader")
                        self.assertEqual(summary["removed"], [])
                self.assertEqual(rmdir_calls, [target, target])
                self.assertEqual((target / "evidence").read_bytes(), b"replacement content")
                self.assertEqual(receipt.read_bytes(), receipt_bytes)
                self.assert_completed_and_unknown(folder, completed, completed_bytes)

    def test_records_directory_parent_is_synced_before_tombstone_and_on_retry(self):
        folder = self.root / "stages"
        target = folder / ("a" * 32)
        target.mkdir(parents=True)
        owner = {"schema_version": 1, "stage": "reader", "attempt_id": target.name,
                 "created_utc": "2026-01-01T00:00:00+00:00", "state": "abandoned"}
        staging.write_record(target, "reader", owner)
        marker_bytes = (target / staging.OWNER).read_bytes()
        (target / "payload").write_bytes(b"owned payload")
        records = folder.with_name(folder.name + "-records")
        receipt = records / (target.name + ".json")
        self.assertFalse(records.exists())
        syncs, checkpoints = [], []

        def sync(directory):
            syncs.append(directory)
            if directory == records.parent:
                self.assertTrue(records.is_dir())
                self.assertEqual((target / staging.OWNER).read_bytes(), marker_bytes)
                self.assertEqual((target / "payload").read_bytes(), b"owned payload")
                if syncs.count(records.parent) == 1:
                    self.assertFalse(receipt.exists())
                    raise OSError("records parent fsync failed")
            elif directory == records and syncs.count(records) == 1:
                self.assertTrue(receipt.exists())
                raise OSError("records entry fsync failed")

        def checkpoint(point):
            checkpoints.append(point)
            if point == "retirement-recorded":
                self.assertEqual(json.loads(receipt.read_bytes())["kind"], "retirement")
                self.assertEqual((target / staging.OWNER).read_bytes(), marker_bytes)
                self.assertEqual((target / "payload").read_bytes(), b"owned payload")

        with patch.object(staging, "_sync_directory", side_effect=sync), \
                patch.object(staging, "_checkpoint", side_effect=checkpoint):
            with self.assertRaisesRegex(OSError, "records parent fsync failed"):
                staging.remove(target, "reader", owner, folder=folder)
            self.assertFalse(receipt.exists())
            self.assertEqual((target / "payload").read_bytes(), b"owned payload")
            with self.assertRaisesRegex(OSError, "records entry fsync failed"):
                staging.remove(target, "reader", owner, folder=folder)
            self.assertTrue(receipt.exists())
            self.assertEqual((target / "payload").read_bytes(), b"owned payload")
            staging.remove(target, "reader", owner, folder=folder)
        self.assertEqual(syncs[:5], [records.parent, records.parent, records, records.parent, records])
        self.assertEqual(checkpoints, ["retirement-recorded", "owner-removed", "directory-removed"])
        self.assertFalse(target.exists())
        self.assertEqual(self.recovery_records(folder), [])

    def test_recovery_records_preserve_completed_invalid_and_unexpected_contents(self):
        for point in ("registered", "owner-removed"):
            for change in ("completed", "invalid-owner", "unexpected-file", "invalid-record", "oversized-record"):
                with self.subTest(point=point, change=change):
                    root, folder, target, completed, completed_bytes = self.crash(point)
                    receipt = self.recovery_records(folder)[0]
                    if change == "completed":
                        owner = json.loads(receipt.read_bytes())["owner"]
                        staging.write_record(target, "reader", {**owner, "state": "completed"})
                    elif change == "invalid-owner":
                        (target / staging.OWNER).write_bytes(b"{}")
                    elif change == "unexpected-file":
                        (target / "evidence").write_bytes(b"keep")
                    else:
                        receipt.write_bytes(b"{}" if change == "invalid-record" else b" " * (staging.MAX_RECORD_BYTES + 1))
                    before = {path.name: path.read_bytes() for path in target.iterdir()}
                    staging.retire(folder, "reader")
                    staging.retire(folder, "reader")
                    self.assertTrue(target.exists())
                    self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)
                    self.assertEqual(len(self.recovery_records(folder)), int(change != "completed"))
                    self.assert_completed_and_unknown(folder, completed, completed_bytes)

    def test_fsync_failure_prevents_creation_and_marker_removal(self):
        folder = self.root / "stages"
        with patch.object(staging.os, "fsync", side_effect=OSError("fsync denied")):
            with self.assertRaisesRegex(OSError, "fsync denied"):
                with staging.attempt(folder, "reader"):
                    self.fail("unsynced registration must not create an attempt")
        self.assertFalse(folder.exists())
        self.assertEqual(self.recovery_records(folder), [])
        root, folder, target, completed, completed_bytes = self.crash("retirement-recorded")
        receipt = self.recovery_records(folder)[0]
        receipt.unlink()  # Exercise a fresh tombstone write, rather than its identical no-op.
        with patch.object(staging.os, "fsync", side_effect=OSError("fsync denied")):
            summary = staging.retire(folder, "reader")
        self.assertTrue(any("fsync denied" in row["reason"] for row in summary["retained"]))
        self.assertTrue((target / staging.OWNER).exists())
        staging.retire(folder, "reader")
        self.assertFalse(target.exists())
        self.assertEqual(self.recovery_records(folder), [])
        self.assert_completed_and_unknown(folder, completed, completed_bytes)

    def test_exact_schema_rejects_invalid_reads_and_writes_without_replacement(self):
        with staging.attempt(self.root / "stages", "reader", deferred=True) as path:
            pass
        marker = path / staging.OWNER
        owner = json.loads(marker.read_bytes())
        cases = [{**owner, "extra": "scalar"}, {**owner, "extra": {"nested": []}},
                 {key: value for key, value in owner.items() if key != "created_utc"},
                 {**owner, "schema_version": True}, {**owner, "schema_version": 1.0},
                 {**owner, "created_utc": "not a timestamp"}]
        for field in owner:
            cases.extend({**owner, field: value} for value in (None, [], {}))
        for index, value in enumerate(cases):
            with self.subTest(case=index):
                data = json.dumps(value, separators=(",", ":")).encode()
                marker.write_bytes(data)
                with self.assertRaises(ContractError):
                    staging.record(path, "reader")
                with self.assertRaises(ContractError):
                    staging.finish(path, "reader", "abandoned")
                with self.assertRaises(ContractError):
                    staging.write_record(path, "reader", value)
                self.assertEqual(marker.read_bytes(), data)
        marker.write_bytes(json_bytes(owner))
        for state in (None, [], {}):
            with self.subTest(terminal_state=state):
                with self.assertRaises(ContractError):
                    staging.finish(path, "reader", state)
                self.assertEqual(json.loads(marker.read_bytes()), owner)

    def test_finish_refuses_terminal_encoding_above_read_limit(self):
        with staging.attempt(self.root / "stages", "reader", deferred=True) as path:
            pass
        marker = path / staging.OWNER
        owner = json.loads(marker.read_bytes())
        owner["created_utc"] = "2026-01-01T00:00:00.0+00:00"
        spare = staging.MAX_RECORD_BYTES - len(json.dumps(owner, separators=(",", ":")).encode())
        owner["created_utc"] = "2026-01-01T00:00:00." + "0" * (spare + 1) + "+00:00"
        data = json.dumps(owner, separators=(",", ":")).encode()
        self.assertEqual(len(data), staging.MAX_RECORD_BYTES)
        marker.write_bytes(data)
        self.assertEqual(staging.record(path, "reader")[0], owner)
        with self.assertRaisesRegex(ContractError, "write bound"):
            staging.finish(path, "reader", "completed")
        self.assertEqual(marker.read_bytes(), data)
        self.assertEqual(staging.record(path, "reader")[0]["state"], "materializing")

    def test_terminal_records_round_trip_with_exact_scalar_fields_within_limit(self):
        fields = {"schema_version", "stage", "attempt_id", "created_utc", "state"}
        for stage in ("extraction", "history", "reader", "release"):
            for state in ("completed", "abandoned"):
                with self.subTest(stage=stage, state=state):
                    with staging.attempt(self.root / (stage + "-" + state), stage, deferred=True) as path:
                        initial = json.loads((path / staging.OWNER).read_bytes())
                        self.assertEqual(initial["state"], "materializing")
                        self.assertEqual(set(initial), fields)
                    staging.finish(path, stage, state)
                    data = (path / staging.OWNER).read_bytes()
                    value = json.loads(data)
                    self.assertLessEqual(len(data), staging.MAX_RECORD_BYTES)
                    self.assertEqual(set(value), fields)
                    self.assertIs(type(value["schema_version"]), int)
                    self.assertTrue(all(type(value[key]) is str for key in fields - {"schema_version"}))
                    self.assertEqual(staging.record(path, stage)[0], value)
                    self.assertEqual(value, {**initial, "state": state})
                    staging.finish(path, stage, state)
                    self.assertEqual((path / staging.OWNER).read_bytes(), data)

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
        def changed(path, stage, owner, **kwargs):
            staging.finish(path, stage, "completed")
            return original(path, stage, owner, **kwargs)
        with patch.object(staging, "remove", side_effect=changed):
            with self.assertRaises(OSError):
                with staging.attempt(folder, "reader"):
                    raise OSError("new failure")
        self.assertEqual(staging.record(failed, "reader")[0]["state"], "completed")
        self.assertEqual((failed / "payload").read_text(), "keep")

    def test_nonchild_and_redirected_candidate_cannot_authorize_retirement(self):
        folder = self.root / "stages"
        folder.mkdir()
        with staging.attempt(self.root / "elsewhere", "reader", deferred=True) as outside:
            (outside / "payload").write_bytes(b"keep outside")
        owner = staging.record(outside, "reader")[0]
        with self.assertRaisesRegex(ContractError, "not a direct child"):
            staging.remove(outside, "reader", owner, folder=folder)
        link = folder / outside.name
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                    capture_output=True, text=True)
            if result.returncode:
                self.skipTest("Cannot create candidate junction: " + result.stderr)
            self.addCleanup(link.rmdir)
        else:
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Cannot create candidate symlink: {exc}")
            self.addCleanup(link.unlink)
        summary = staging.retire(folder, "reader")
        self.assertTrue(any(row["stage"] == link.name and "Redirected staging path" in row["reason"]
                            for row in summary["retained"]))
        self.assertEqual(staging.record(outside, "reader")[0], owner)
        self.assertEqual((outside / "payload").read_bytes(), b"keep outside")

    def test_denied_hardlink_unlink_keeps_attempt_without_chmod(self):
        folder = self.root / "stages"
        completed = self.root / "completed"
        completed.write_bytes(b"completed bytes")
        completed.chmod(stat.S_IREAD)
        with self.assertRaises(OSError):
            with staging.attempt(folder, "reader") as failed:
                shared = failed / "payload"
                os.link(completed, shared)
                raise OSError("first failure")
        original = Path.unlink

        def denied(path, *args, **kwargs):
            if path == shared:
                raise PermissionError("protected hard link")
            return original(path, *args, **kwargs)

        with patch.object(Path, "unlink", denied), \
                patch.object(Path, "chmod", side_effect=AssertionError("must not chmod shared file")):
            with self.assertRaisesRegex(OSError, "next failure"):
                with staging.attempt(folder, "reader"):
                    raise OSError("next failure")
        self.assertTrue(shared.exists())
        self.assertTrue((failed / staging.OWNER).exists())
        self.assertEqual(completed.read_bytes(), b"completed bytes")
        self.assertFalse(completed.stat().st_mode & stat.S_IWRITE)
        report = json.loads(folder.with_name("stages-retention.json").read_bytes())
        self.assertTrue(any(row["stage"] == failed.name and "multiply linked" in row["reason"]
                            for row in report["retained"]))

    def test_value_error_from_parser_is_an_unrecognized_record(self):
        folder = self.root / "stages"
        with staging.attempt(folder, "reader", deferred=True) as failed:
            pass
        with patch.object(staging.json, "loads", side_effect=ValueError("parser limit")):
            with self.assertRaisesRegex(ContractError, "invalid JSON"):
                staging.record(failed, "reader")
            summary = staging.retire(folder, "reader")
        self.assertTrue(failed.exists())
        self.assertTrue(any(row["stage"] == failed.name and "invalid JSON" in row["reason"]
                            for row in summary["retained"]))

if __name__ == "__main__":
    unittest.main()
