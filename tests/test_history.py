"""Filesystem transaction tests; real-source rehearsal complements the mock catalog."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests._support import fixture_dir

from test_identity import observation
from wikibuild import extraction, history, identity, model
from wikibuild.storage import ContractError, json_bytes, writer_lock


class HistoryTests(unittest.TestCase):
    def test_owned_staging_crash_and_prepared_reuse_keep_only_newest_failure(self):
        from wikibuild import staging
        with patch.object(history, "write_row", side_effect=SystemExit("materialization crash")):
            with self.assertRaises(SystemExit):
                self.run_history()
        folder = self.root / ".local/history/staging"
        failed = next(folder.iterdir())
        self.assertEqual(staging.record(failed, "history")[0]["state"], "materializing")
        self.assertTrue((failed / "models.jsonl").exists())
        unknown = folder / "unknown"
        unknown.mkdir()
        result, _ = self.run_history()
        self.assertEqual(staging.record(failed, "history")[0]["state"], "abandoned")
        completed = next(path for path in folder.iterdir() if (path / staging.OWNER).exists()
                         and staging.record(path, "history")[0]["state"] == "completed")
        self.assertEqual(staging.record(completed, "history")[0]["state"], "completed")
        self.assertTrue(unknown.exists())
        self.set_input([observation(value=2)], build="200")
        original = history.write_changed
        def fail_pointer(path, data):
            if path == self.root / "identity/latest.json":
                raise OSError("pointer interrupted")
            return original(path, data)
        with patch.object(history, "write_changed", side_effect=fail_pointer):
            with self.assertRaises(OSError):
                self.run_history()
        abandoned = [path for path in folder.iterdir() if path != unknown
                     and staging.record(path, "history")[0]["state"] == "abandoned"]
        self.assertEqual(len(abandoned), 1)
        recovered, metrics = self.run_history()
        self.assertTrue(metrics["reused"])
        self.assertTrue(all(staging.record(path, "history")[0]["state"] == "abandoned" for path in abandoned))
        self.assertFalse(failed.exists())
        self.assertTrue(completed.exists())
        self.assertEqual(recovered["parent_run"], result["run_id"])

    def test_consecutive_materialization_failures_leave_exactly_one_retained(self):
        from wikibuild import staging
        folder = self.root / ".local/history/staging"
        original = history.write_row
        def fail(*args):
            original(*args)
            raise OSError("materialization failed")
        previous = None
        for _ in range(5):
            with patch.object(history, "write_row", side_effect=fail):
                with self.assertRaisesRegex(OSError, "materialization failed"):
                    self.run_history()
            failures = list(folder.iterdir())
            self.assertEqual(len(failures), 1)
            self.assertEqual(staging.record(failures[0], "history")[0]["state"], "abandoned")
            self.assertTrue((failures[0] / "models.jsonl").stat().st_size)
            if previous is not None:
                self.assertFalse(previous.exists())
            previous = failures[0]
        self.run_history()
        self.assertTrue(previous.exists())

    def setUp(self):
        self.root = fixture_dir(self, "history")
        self.source = self.root / "source"
        self.metadata = {"bundle#1": {"type": "MonoBehaviour", "class": "Icon_Info", "assembly": "Item_Info", "paths": []}}
        self.check_source = patch("wikibuild.extraction.ensure_source")
        self.check_source.start()
        self.catalog = patch("wikibuild.history.relevant_metadata", side_effect=lambda *args: (self.metadata, 120))
        self.catalog.start()
        self.addCleanup(self.check_source.stop)
        self.addCleanup(self.catalog.stop)
        self.set_input([observation()])

    def set_input(self, rows, build="100", inventory=None):
        data = b"".join(json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows)
        sha = identity.fingerprint([build, data.decode()])
        self.receipt = {"snapshot_id": "build-" + build + "-" + sha[:12], "source_commit": sha[:40],
                        "steam": {"app_id": "2393970", "build_id": build}, "input_inventory_git_blob": inventory or "inventory-" + build}
        temporary = self.root / "observations.tmp"
        temporary.write_bytes(data)
        self.extracted = {"run_id": sha, "snapshot_id": self.receipt["snapshot_id"], "source_commit": self.receipt["source_commit"],
                          "records": extraction.store_file(self.root, temporary, "jsonl"), "supported_kinds": ["item", "loot-source"],
                          "dependencies": {"Catalog/views/items.jsonl": {"git_blob": "a" * 40, "sha256": "b" * 64, "bytes": 100}}}

    def run_history(self):
        with writer_lock(self.root):
            return history.run(self.root, self.source, self.receipt, self.extracted)

    def test_repeat_preserves_result_bytes_and_pointer_timestamp(self):
        first, _ = self.run_history()
        pointer = self.root / "identity/latest.json"
        stamp, data = pointer.stat().st_mtime_ns, pointer.read_bytes()
        repeated, metrics = self.run_history()
        self.assertEqual(first, repeated)
        self.assertEqual(data, pointer.read_bytes())
        self.assertEqual(stamp, pointer.stat().st_mtime_ns)
        self.assertEqual({"reused": True, "source_bytes_read": 0}, metrics)

    def test_unchanged_facts_new_build_keep_revision_and_last_changed(self):
        first, _ = self.run_history()
        before = next(iter(history.load_state(self.root, first).values()))
        self.set_input([observation()], build="200")
        second, _ = self.run_history()
        after = next(iter(history.load_state(self.root, second).values()))
        self.assertEqual(before["entity_key"], after["entity_key"])
        self.assertEqual(before["revision_id"], after["revision_id"])
        self.assertEqual(before["last_changed"], after["last_changed"])
        self.assertNotEqual(before["last_data_checked"], after["last_data_checked"])
        self.assertIsNone(after["last_verified"])
        self.assertEqual("game-input-change", second["change_origin"])

    def test_changed_value_revises_only_affected_entity(self):
        self.metadata["bundle#2"] = self.metadata["bundle#1"]
        self.set_input([observation(), observation(source="bundle#2", name="B")])
        self.run_history()
        self.set_input([observation(value=8), observation(source="bundle#2", name="B")], build="200")
        result, _ = self.run_history()
        self.assertEqual(1, result["counts"]["changed"])
        self.assertEqual(1, result["counts"]["unchanged"])

    def test_duplicate_observations_fail_without_replacing_last_success(self):
        first, _ = self.run_history()
        self.set_input([observation(), observation()], build="200")
        with self.assertRaisesRegex(ContractError, "Duplicate observation"):
            self.run_history()
        self.assertEqual(first["run_id"], history.latest(self.root)["run_id"])

    def test_removal_and_capture_gap_are_different_states(self):
        self.run_history()
        self.metadata = {}
        self.set_input([], build="200")
        result, _ = self.run_history()
        self.assertEqual("not-present", next(iter(history.load_state(self.root, result).values()))["status"])
        self.set_input([], build="300")
        self.extracted["supported_kinds"] = []
        result, _ = self.run_history()
        self.assertEqual("uncaptured", next(iter(history.load_state(self.root, result).values()))["status"])

    def test_pointer_failure_retry_reuses_prepared_decisions(self):
        first, _ = self.run_history()
        self.set_input([observation(value=2)], build="200")
        original = history.write_changed

        def fail_pointer(path, data):
            if path == self.root / "identity/latest.json":
                raise OSError("injected interruption")
            return original(path, data)

        with patch("wikibuild.history.write_changed", side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, "injected"):
                self.run_history()
        self.assertEqual(first["run_id"], history.latest(self.root)["run_id"])
        result, metrics = self.run_history()
        self.assertTrue(metrics["reused"])
        self.assertEqual(first["run_id"], result["parent_run"])
        self.assertEqual(2, len(list((self.root / "identity/runs").glob("*.json"))))

    def test_missing_staging_rebuilds_from_frozen_decisions(self):
        first, _ = self.run_history()
        path = self.root / first["models"]["path"]
        saved = path.read_bytes()
        path.unlink()
        with patch("wikibuild.identity.reconcile", side_effect=AssertionError("Must not rematch")):
            repeated, metrics = self.run_history()
        self.assertEqual(first, repeated)
        self.assertEqual(saved, path.read_bytes())
        self.assertGreater(metrics["source_bytes_read"], 0)

    def test_modified_staging_and_ledger_are_preserved_and_refused(self):
        result, _ = self.run_history()
        path = self.root / result["models"]["path"]
        saved = path.read_bytes()
        path.write_text("investigation")
        with self.assertRaisesRegex(ContractError, "modified"):
            self.run_history()
        self.assertEqual("investigation", path.read_text())
        path.write_bytes(saved)
        state_path = self.root / result["state"]["path"]
        state_path.write_text("investigation")
        with self.assertRaisesRegex(ContractError, "modified"):
            self.run_history()
        self.assertEqual("investigation", state_path.read_text())

    def test_older_request_cannot_rewind_later_decisions(self):
        self.run_history()
        self.set_input([observation(value=3)], build="200")
        latest, _ = self.run_history()
        self.set_input([observation()])
        with self.assertRaisesRegex(ContractError, "rewind"):
            self.run_history()
        self.assertEqual(latest["run_id"], history.latest(self.root)["run_id"])

    def test_reviewed_correction_preserves_old_runs_and_supersedes_provisional_key(self):
        first, _ = self.run_history()
        original_key = next(iter(history.load_state(self.root, first)))
        row = observation(name="Renamed", value=99)
        self.set_input([row], build="200")
        ambiguous, _ = self.run_history()
        self.assertEqual(1, ambiguous["counts"]["ambiguous"])
        correction = {"schema_version": 1, "mappings": [{"snapshot_id": self.receipt["snapshot_id"],
                      "observation_key": row["observation_key"], "entity_key": original_key,
                      "reviewer": "fixture", "reason": "Verified identity"}]}
        (self.root / "identity/corrections.json").write_bytes(json_bytes(correction))
        fixed, _ = self.run_history()
        states = history.load_state(self.root, fixed)
        self.assertEqual("present", states[original_key]["status"])
        self.assertEqual(1, sum(state["status"] == "superseded" for state in states.values()))
        self.assertEqual(ambiguous, history.read(self.root, ambiguous["run_id"]))
        self.set_input([row], build="300")
        next_run, _ = self.run_history()
        self.assertEqual(1, sum(state["status"] == "superseded" for state in history.load_state(self.root, next_run).values()))

    def test_reviewed_reclassification_retires_only_exact_component_and_repeats(self):
        old_row = {**observation(), "component": {"assembly": "Creature", "class": "Zombie_Input"}}
        self.set_input([old_row])
        first, _ = self.run_history()
        original = next(iter(history.load_state(self.root, first)))
        receipt = self.receipt
        new_row = {**old_row, "kind": "ai-rule", "observation_key": "new-controller"}
        self.set_input([new_row])
        self.receipt = receipt  # Extractor correction, same captured source.
        self.extracted.update(snapshot_id=receipt["snapshot_id"], source_commit=receipt["source_commit"])
        second, _ = self.run_history()
        self.assertEqual(1, second["exceptions"]["occurrences"])
        self.assertEqual("unresolved-observation", second["exceptions"]["groups"][0]["code"])
        current = next(key for key, value in history.load_state(self.root, second).items() if value["status"] == "present")
        correction = {"snapshot_id": receipt["snapshot_id"], "observation_key": "new-controller",
                      "entity_key": current, "reviewer": "fixture", "reason": "Corrected controller category",
                      "supersedes": [original]}
        (self.root / "identity/corrections.json").write_bytes(json_bytes({"schema_version": 1, "mappings": [correction]}))
        fixed, _ = self.run_history()
        retired = history.load_state(self.root, fixed)[original]
        self.assertEqual("superseded", retired["status"])
        self.assertEqual(current, retired["superseded_by"])
        self.assertEqual(0, fixed["exceptions"]["group_count"])
        self.assertEqual(fixed, self.run_history()[0])
        with patch("wikibuild.history.contract", return_value="changed-matcher"):
            rerun, _ = self.run_history()
        self.assertEqual("superseded", history.load_state(self.root, rerun)[original]["status"])
        self.assertEqual(first, history.read(self.root, first["run_id"]))

    def test_reviewed_reclassification_rejects_different_source_component(self):
        descriptor = identity.describe({**observation(), "component": {"assembly": "A", "class": "C"}}, {})
        current = {**descriptor, "kind": "ai-rule", "source_id": "bundle#different"}
        previous = {"old": {"descriptor": descriptor, "last_seen": "snapshot", "status": "unresolved"}}
        with self.assertRaisesRegex(ContractError, "same captured component"):
            identity.reviewed_supersessions({"new": current}, previous, {"new": "target"}, "snapshot",
                [{"snapshot_id": "snapshot", "observation_key": "new", "supersedes": ["old"]}])


if __name__ == "__main__":
    unittest.main()
