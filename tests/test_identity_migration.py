"""One-time migration transactions and chronological identity repair."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests._support import fixture_dir
from test_identity import observation, skill_capture
from wikibuild import history, identity, identity_migration as migration, model
from wikibuild.exceptions import Exceptions
from wikibuild.storage import ContractError, json_bytes, writer_lock


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "migrate")
        self.source = self.root / "source"
        self.metadata = {}
        self.parent = None
        self.keys = ["e-" + letter * 32 for letter in "abcd"]

    def capture(self, number, records):
        rows, allocation, metadata = [], {}, {}
        snapshot = "build-" + str(number) + "-" + "a" * 12
        for source, name, key in records:
            row = {**observation(source=source, name=name), "component": {"assembly": "Item_Info", "class": "Icon_Info"}}
            rows.append(row)
            allocation[row["observation_key"]] = key
            metadata[source] = {"type": "MonoBehaviour", "name": name, **row["component"]}
        self.metadata[str(number)] = metadata
        projected, states = [], []
        indexes = model.targets_index(rows, allocation)
        for row in rows:
            key = allocation[row["observation_key"]]
            frozen = model.project(row, key, indexes, metadata,
                {"Catalog/views/items.jsonl": {"git_blob": "a" * 40}}, Exceptions())
            frozen["snapshot_id"] = snapshot
            projected.append(frozen)
            states.append({"entity_key": key, "descriptor": identity.describe(row, metadata), "status": "present",
                           "revision_id": frozen["revision_id"], "first_seen": snapshot, "last_seen": snapshot,
                           "last_changed": snapshot, "last_data_checked": snapshot, "last_verified": None,
                           "decision": {"status": "ambiguous", "candidates": []}})
        request = identity.fingerprint(number)
        run = {"schema_version": 1, "request_key": request, "parent_run": self.parent, "snapshot_id": snapshot,
               "input_identity": {"steam": {"build_id": str(number)}, "inventory": "inventory-" + str(number)},
               "source_commit": str(number), "run_id": identity.fingerprint([request, self.parent])}
        for label, values in (("models", projected), ("state", states)):
            temporary = self.root / (label + ".jsonl")
            temporary.write_bytes(b"".join(json.dumps(value, sort_keys=True).encode() + b"\n" for value in values))
            run[label] = history.install(self.root, temporary, "fixtures/" + label)
        history.immutable(self.root / "identity/runs" / (run["run_id"] + ".json"), json_bytes(run))
        (self.root / "identity/latest.json").write_bytes(json_bytes({"run_id": run["run_id"]}))
        self.parent = run["run_id"]
        return run

    def plan(self):
        with patch.object(history, "relevant_metadata", side_effect=lambda source, revision, *args: (self.metadata[revision], 0)):
            return migration.plan(self.root, self.source)

    def test_three_captures_reserve_redirect_source_for_new_live_object(self):
        a, provisional, later, _ = self.keys
        self.capture(1, [("bundle#1", "A", a)])
        self.capture(2, [("bundle#2", "A", provisional)])
        self.capture(3, [("bundle#3", "A", later), ("bundle#8", "B", provisional)])
        record, states = self.plan()
        self.assertEqual(a, record["redirects"][provisional]["entity_key"])
        self.assertEqual(a, record["redirects"][later]["entity_key"])
        self.assertNotIn(provisional, states)
        live = {state["descriptor"]["name"]: key for key, state in states.items() if state["status"] == "present"}
        self.assertEqual(a, live["A"])
        self.assertNotEqual(provisional, live["B"])
        self.assertEqual(record, self.plan()[0])

    def test_fog_snow_identical_facts_repair_reused_key_chronologically(self):
        fog, snow, provisional, _ = self.keys
        first = self.capture(1, [("bundle#10", "Fog_Heavy", fog), ("bundle#11", "Snow_Heavy", snow)])
        last = self.capture(2, [("bundle#9", "Fog_Heavy", provisional), ("bundle#10", "Snow_Heavy", fog)])
        before = {path: path.read_bytes() for path in (self.root / "identity/runs").glob("*.json")}
        record, states = self.plan()
        self.assertEqual("Fog_Heavy", states[fog]["descriptor"]["name"])
        self.assertEqual("Snow_Heavy", states[snow]["descriptor"]["name"])
        self.assertEqual(fog, record["redirects"][provisional]["entity_key"])
        self.assertNotIn(fog, record["redirects"])
        self.assertTrue(any(proof["old_key"] == fog and proof["entity_key"] == snow for proof in record["repairs"]))
        self.assertEqual([first["run_id"], last["run_id"]], record["runs"])
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_coexisting_identical_objects_never_merge_even_without_unique_anchor(self):
        a, b, _, _ = self.keys
        self.capture(1, [("bundle#1", "Same", a), ("bundle#2", "Same", b)])
        self.capture(2, [("bundle#3", "Same", self.keys[2]), ("bundle#4", "Same", self.keys[3])])
        record, states = self.plan()
        self.assertEqual({}, record["redirects"])
        self.assertEqual(2, sum(state["status"] == "present" for state in states.values()))

    def test_separate_extractor_runs_over_one_capture_do_not_merge_equal_objects(self):
        component = {"assembly": "Item_Info", "class": "Icon_Info"}
        metadata = {source: {"type": "MonoBehaviour", "name": "Same", **component} for source in ("bundle#1", "bundle#2")}
        rows = [{**observation(source=source, name="Same"), "component": component} for source in metadata]
        run = {"snapshot_id": "same-capture", "run_id": "first"}
        first, *_ = migration.repair_capture(run, [({"entity_key": self.keys[0], "revision_id": "same"}, rows[0])], metadata, {}, {})
        second, assignments, decisions, *_ = migration.repair_capture({**run, "run_id": "second"},
            [({"entity_key": self.keys[1], "revision_id": "same"}, rows[1])], metadata, first, {})
        self.assertEqual(self.keys[1], assignments[rows[1]["observation_key"]])
        self.assertEqual("new", decisions[rows[1]["observation_key"]]["status"])
        self.assertEqual("present", second[self.keys[1]]["status"])
        self.assertEqual("unresolved", second[self.keys[0]]["status"])

    def test_migration_is_immutable_idempotent_and_used_as_previous(self):
        a, provisional, _, _ = self.keys
        self.capture(1, [("bundle#1", "A", a)])
        last = self.capture(2, [("bundle#2", "A", provisional)])
        record, states = self.plan()
        with patch.object(migration, "require_clean"), patch.object(migration, "plan", return_value=(record, states)) as planner:
            first = migration.run(self.root, self.source, {})
            path = self.root / "identity/migration.json"
            stamp, data = path.stat().st_mtime_ns, path.read_bytes()
            second = migration.run(self.root, self.source, {})
            self.assertEqual(1, planner.call_count)
        self.assertEqual(first["migration"], second["migration"])
        self.assertTrue(second["reused"])
        self.assertEqual((stamp, data), (path.stat().st_mtime_ns, path.read_bytes()))
        corrected = migration.previous_state(self.root, last, first["migration"])
        self.assertIn(a, corrected)
        self.assertNotIn(provisional, corrected)
        self.assertIn(provisional, history.load_state(self.root, last))
        path.write_bytes(data.replace(b'"schema_version": 1', b'"schema_version": 2'))
        with self.assertRaises(ContractError):
            migration.read(self.root)

    def test_dirty_workspace_refused_before_planning(self):
        with patch.object(migration, "git", return_value=" M dirty"), patch.object(migration, "plan") as planner:
            with self.assertRaisesRegex(ContractError, "clean workspace"):
                migration.run(self.root, self.source, {})
            planner.assert_not_called()
        self.assertFalse((self.root / "identity/migration.json").exists())

    def test_writer_lock_refused_before_planning(self):
        with writer_lock(self.root), patch.object(migration, "plan") as planner:
            with self.assertRaisesRegex(ContractError, "writer"):
                migration.run(self.root, self.source, {})
            planner.assert_not_called()

    def test_conflicts_and_live_redirect_sources_are_invalid(self):
        a, b, _, _ = self.keys
        proof = {"entity_key": b, "evidence": {"anchor": "name"}}
        with self.assertRaisesRegex(ContractError, "intersect"):
            migration.validate_redirects({a: proof}, {a: {}, b: {}})
        with self.assertRaisesRegex(ContractError, "Conflicting"):
            migration.validate_redirects({a: proof, b: {**proof, "entity_key": a}}, {})

    def test_activation_failure_keeps_previous_pointer_and_retry_uses_same_baseline(self):
        self.capture(1, [("bundle#1", "A", self.keys[0])])
        record, states = self.plan()
        pointer = (self.root / "identity/latest.json").read_bytes()
        install = history.immutable
        def fail_activation(path, data):
            if path.name == "migration.json":
                raise OSError("activation interrupted")
            return install(path, data)
        with patch.object(migration, "require_clean"), patch.object(migration, "plan", return_value=(record, states)):
            with patch.object(history, "immutable", side_effect=fail_activation):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    migration.run(self.root, self.source, {})
            self.assertIsNone(migration.read(self.root))
            self.assertEqual(pointer, (self.root / "identity/latest.json").read_bytes())
            result = migration.run(self.root, self.source, {})
            self.assertEqual(record["base_run"], result["migration"]["base_run"])

    def test_normal_update_uses_corrected_baseline_without_retained_model_reads(self):
        a, provisional, _, _ = self.keys
        self.capture(1, [("bundle#1", "A", a)])
        last = self.capture(2, [("bundle#2", "A", provisional)])
        record, states = self.plan()
        with patch.object(migration, "require_clean"), patch.object(migration, "plan", return_value=(record, states)):
            migration.run(self.root, self.source, {})
        (self.root / last["models"]["path"]).unlink()
        row = {**observation(source="bundle#20", name="A"), "component": {"assembly": "Item_Info", "class": "Icon_Info"}}
        temporary = self.root / "observations.jsonl"
        temporary.write_text(json.dumps(row) + "\n", encoding="utf-8")
        receipt = {"snapshot_id": "build-3-" + "a" * 12, "source_commit": "3", "steam": {"build_id": "3"},
                   "input_inventory_git_blob": "inventory-3"}
        extracted = {**receipt, "run_id": identity.fingerprint("extraction"), "supported_kinds": ["item"],
                     "records": history.install(self.root, temporary, "fixtures/observations"),
                     "dependencies": {"Catalog/views/items.jsonl": {"git_blob": "a" * 40}}}
        metadata = {"bundle#20": {"type": "MonoBehaviour", "name": "A", **row["component"]}}
        with patch("wikibuild.extraction.ensure_source"), patch.object(history, "relevant_metadata", return_value=(metadata, 0)), \
                patch.object(migration, "retained_runs", side_effect=AssertionError("unexpected replay")), writer_lock(self.root):
            result, _ = history.run(self.root, self.source, receipt, extracted)
        after = history.load_state(self.root, result)
        self.assertEqual("present", after[a]["status"])
        self.assertNotIn(provisional, after)
        self.assertEqual(record["base_run"], result["parent_run"])
        self.assertEqual(migration.read(self.root)["migration_id"], result["migration_id"])

    def test_missing_historical_skill_parent_matches_later_extracted_parent(self):
        rows, metadata = skill_capture()
        children = [row for row in rows if row.get("parent_source_id")]
        frozen = [({"entity_key": key, "revision_id": "revision"}, row) for key, row in zip(self.keys, children)]
        first, *_ = migration.repair_capture({"snapshot_id": "first", "run_id": "first"}, frozen, metadata, {}, {})
        parent = next(key for key, row in first.items() if not row["descriptor"].get("definition"))
        self.assertEqual("survival-rule", first[parent]["descriptor"]["kind"])
        changed, current_metadata = skill_capture(source="bundle#12", order=("Gunsmith", "Forestry"), targets=("bundle#200", "bundle#100"))
        frozen = [({"entity_key": "e-provisional-" + str(index), "revision_id": "revision"}, row) for index, row in enumerate(changed)]
        second, *_ = migration.repair_capture({"snapshot_id": "second", "run_id": "second"}, frozen, current_metadata, first, {})
        self.assertEqual("present", second[parent]["status"])
        for key in self.keys[:2]:
            self.assertEqual("present", second[key]["status"])
            self.assertEqual(first[key]["descriptor"]["name"], second[key]["descriptor"]["name"])

    def test_existing_reviewed_supersession_is_preserved_in_baseline(self):
        a, b, _, _ = self.keys
        self.capture(1, [("bundle#1", "A", a), ("bundle#2", "B", b)])
        last = self.capture(2, [("bundle#2", "B", b)])
        old = history.load_state(self.root, last)
        retired = {"entity_key": a, "status": "superseded", "superseded_by": b,
                   "descriptor": {"name": "A", "kind": "item", "topic": "items-equipment"},
                   "decision": {"status": "reviewed", "reviewer": "Coordinator"}}
        values = [*old.values(), retired]
        temporary = self.root / "reviewed.jsonl"
        temporary.write_bytes(b"".join(json.dumps(value).encode() + b"\n" for value in values))
        last["state"] = history.install(self.root, temporary, "fixtures/reviewed")
        # Build an immutable synthetic receipt before the migration reads it.
        (self.root / "identity/runs" / (last["run_id"] + ".json")).write_bytes(json_bytes(last))
        _, states = self.plan()
        self.assertEqual(retired, states[a])

    def test_dry_run_has_no_filesystem_writes(self):
        self.capture(1, [("bundle#1", "A", self.keys[0])])
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with patch.object(history, "relevant_metadata", return_value=(self.metadata["1"], 0)):
            migration.run(self.root, self.source, {}, dry_run=True)
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})
