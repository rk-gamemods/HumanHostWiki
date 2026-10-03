"""Real filesystem conservation, sharing, retry and rejection boundaries."""

import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tests._support import fixture_dir

from wikibuild import reader, reader_retention as retention
from wikibuild.storage import digest, json_bytes, writer_lock


class ReaderRetentionTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "retain")
        self.payloads = {"items/data/shared.json": b"facts\n" * 200000,
                         "items/app.js": b"runtime\n", "items/.nojekyll": b""}
        self.first = self.candidate("first")
        self.second = self.candidate("second")
        self.marker = self.root / ".local/reader-retention/completed.json"

    def candidate(self, label):
        inputs = {"fixture": label}
        identity = digest(json_bytes(inputs))
        path = self.root / ".local/readers" / identity[:24]
        files = dict(self.payloads, **{"items/reader.json": json_bytes(inputs)})
        for name, data in files.items():
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        manifest = {"schema_version": 1, "candidate_id": identity, "inputs": inputs,
                    "files": {name: {"sha256": digest(data), "bytes": len(data)} for name, data in files.items()}}
        (path / "candidate.json").write_bytes(json_bytes(manifest))
        return path

    def run_cleanup(self):
        with writer_lock(self.root):
            return retention.run(self.root)

    def assert_intact(self, candidates=None):
        for path in candidates or [self.first, self.second]:
            reader.verify(path)
            for name, data in self.payloads.items():
                self.assertEqual((path / name).read_bytes(), data)

    def test_identical_bytes_share_storage_preserving_every_path_and_receipt(self):
        manifests = [(path / "candidate.json").read_bytes() for path in [self.first, self.second]]
        result = self.run_cleanup()
        self.assertEqual(result["retained"], [])
        self.assertEqual(result["linked_files"], len(self.payloads))
        self.assertEqual(result["released_file_bytes"], sum(map(len, self.payloads.values())))
        self.assert_intact()
        for name in self.payloads:
            self.assertTrue(os.path.samefile(self.first / name, self.second / name))
        self.assertFalse(os.path.samefile(self.first / "items/reader.json", self.second / "items/reader.json"))
        self.assertEqual(manifests, [(path / "candidate.json").read_bytes() for path in [self.first, self.second]])
        stamp = self.marker.stat().st_mtime_ns
        with patch.object(retention, "verified_files", side_effect=AssertionError("Repeat scanned payloads")):
            repeated = self.run_cleanup()
        self.assertTrue(repeated["reused"])
        self.assertEqual(repeated["verified_bytes"], 0)
        self.assertEqual(repeated["linked_files"], 0)
        self.assertEqual(self.marker.stat().st_mtime_ns, stamp)

    def test_new_candidate_invalidates_receipt_and_reuses_shared_inodes(self):
        self.run_cleanup()
        third = self.candidate("third")
        result = self.run_cleanup()
        self.assertFalse(result["reused"])
        self.assertEqual(result["retained"], [])
        self.assert_intact([self.first, self.second, third])
        for name in self.payloads:
            self.assertTrue(os.path.samefile(self.first / name, third / name))
        # Three copies require only two content reads after earlier sharing.
        logical = sum(path.stat().st_size for base in [self.first, self.second, third]
                      for path in base.rglob("*") if path.is_file() and path.name != "candidate.json")
        self.assertEqual(result["verified_bytes"], logical - sum(map(len, self.payloads.values())))

    def test_modified_or_unknown_files_preserve_the_whole_candidate(self):
        for failure in ["modified", "unknown"]:
            with self.subTest(failure=failure):
                damaged = self.first / "items/app.js"
                if failure == "modified":
                    damaged.write_bytes(b"changed\n")  # Same size; a stat-only check cannot catch it.
                else:
                    damaged.write_bytes(self.payloads["items/app.js"])
                    (self.first / "investigation.txt").write_text("user notes")
                before = (self.first / "items/data/shared.json").stat().st_ino
                result = self.run_cleanup()
                self.assertTrue(result["retained"])
                self.assertEqual(result["linked_files"], 0)
                self.assertEqual((self.first / "items/data/shared.json").stat().st_ino, before)
                self.assertFalse(self.marker.exists())

    def test_corrupt_old_source_is_checked_again_before_sharing_with_new_candidate(self):
        self.run_cleanup()
        (self.first / "items/data/shared.json").write_bytes(b"x" * len(self.payloads["items/data/shared.json"]))
        third = self.candidate("third")
        result = self.run_cleanup()
        self.assertTrue(any("hash changed" in row["reason"] for row in result["retained"]))
        self.assert_intact([third])
        self.assertFalse(os.path.samefile(self.first / "items/data/shared.json", third / "items/data/shared.json"))

    def test_interrupted_replace_preserves_original_and_retry_finishes(self):
        original = retention.os.replace
        calls = []

        def fail_once(source, target):
            if str(source).endswith(".link"):
                calls.append(target)
                if len(calls) == 2:
                    raise PermissionError("protected duplicate")
            return original(source, target)

        with patch.object(retention.os, "replace", side_effect=fail_once):
            result = self.run_cleanup()
        self.assertTrue(any("protected duplicate" in row["reason"] for row in result["retained"]))
        self.assert_intact()
        self.assertFalse(self.marker.exists())
        repeated = self.run_cleanup()
        self.assertEqual(repeated["retained"], [])
        self.assert_intact()
        self.assertTrue(self.run_cleanup()["reused"])

    def test_crash_after_replacement_is_a_safe_fixed_point_on_retry(self):
        original = retention.os.replace

        def crash(source, target):
            original(source, target)
            if str(source).endswith(".link"):
                raise KeyboardInterrupt("after atomic replacement")

        with patch.object(retention.os, "replace", side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.run_cleanup()
        self.assert_intact()
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.run_cleanup()["retained"], [])
        self.assert_intact()

    def test_missing_hardlink_support_preserves_files_and_reports_issue(self):
        with patch.object(retention.os, "link", side_effect=OSError("hard links unavailable")):
            result = self.run_cleanup()
        self.assertTrue(result["retained"])
        self.assertEqual(result["linked_files"], 0)
        self.assert_intact()
        self.assertEqual(self.run_cleanup()["retained"], [])

    def test_leftover_temporary_requires_verified_source_inode(self):
        source, target = sorted([self.first, self.second])
        relative = (target / "items/app.js").relative_to(self.root).as_posix()
        temporary = self.root / ".local/reader-retention/links" / (digest(relative.encode()) + ".link")
        temporary.parent.mkdir(parents=True)
        temporary.write_bytes(b"user notes")
        result = self.run_cleanup()
        self.assertTrue(any("Unknown reader sharing temporary" in row["reason"] for row in result["retained"]))
        self.assertEqual(temporary.read_bytes(), b"user notes")
        self.assert_intact()
        temporary.unlink()  # Test-owned notes, never an implementation cleanup.
        os.link(source / "items/app.js", temporary)
        self.assertEqual(self.run_cleanup()["retained"], [])
        self.assertFalse(temporary.exists())
        self.assertTrue(os.path.samefile(source / "items/app.js", target / "items/app.js"))

    def test_metadata_read_is_bounded_and_missing_payload_is_retained(self):
        with patch.object(retention, "MAX_MANIFEST_BYTES", 20):
            result = self.run_cleanup()
        self.assertTrue(result["retained"])
        self.assertEqual(result["linked_files"], 0)
        (self.first / "items/app.js").unlink()
        result = self.run_cleanup()
        self.assertTrue(any("missing or unknown" in row["reason"] for row in result["retained"]))
        self.assertEqual(result["linked_files"], 0)

    def test_changed_file_between_verification_and_replacement_is_preserved(self):
        original = retention.replace_duplicate
        changed = []

        def change(root, source, target, expected):
            if not changed:
                target[0].write_bytes(b"user change")
                changed.append(target[0])
            return original(root, source, target, expected)

        with patch.object(retention, "replace_duplicate", side_effect=change):
            result = self.run_cleanup()
        self.assertTrue(any("changed before sharing" in row["reason"] for row in result["retained"]))
        self.assertEqual(changed[0].read_bytes(), b"user change")

    def test_invalid_identity_and_escaping_path_are_preserved(self):
        path = self.first / "candidate.json"
        manifest = json.loads(path.read_bytes())
        manifest["inputs"]["fixture"] = "changed"
        path.write_bytes(json_bytes(manifest))
        self.assertIn("identity differs", self.run_cleanup()["retained"][0]["reason"])
        manifest["candidate_id"] = digest(json_bytes(manifest["inputs"]))
        manifest["inputs"]["fixture"] = "first"
        manifest["candidate_id"] = digest(json_bytes(manifest["inputs"]))
        manifest["files"]["../../outside"] = {"sha256": digest(b"x"), "bytes": 1}
        path.write_bytes(json_bytes(manifest))
        self.assertIn("Invalid reader file record", self.run_cleanup()["retained"][0]["reason"])

    def test_redirected_candidate_is_not_traversed(self):
        moved = self.root / "investigation"
        self.first.rename(moved)
        if os.name == "nt":
            result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(self.first), str(moved)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        else:
            self.first.symlink_to(moved, target_is_directory=True)
        try:
            result = self.run_cleanup()
            self.assertTrue(any("Redirected reader cache path" in row["reason"] for row in result["retained"]))
            self.assertEqual(result["linked_files"], 0)
            self.assert_intact([moved, self.second])
        finally:
            self.first.rmdir() if os.name == "nt" else self.first.unlink()


if __name__ == "__main__":
    unittest.main()
