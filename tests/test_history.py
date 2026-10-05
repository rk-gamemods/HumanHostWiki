"""Filesystem transaction tests; real-source rehearsal complements the mock catalog."""

import json
from contextlib import contextmanager
import os
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

from tests._support import fixture_dir

from test_identity import observation, skill_capture
from wikibuild import extraction, history, identity, model
from wikibuild.source import Source
from wikibuild.storage import ContractError, json_bytes, writer_lock


class HistoryTests(unittest.TestCase):
    def test_normal_run_never_reads_ancestor_runs_or_retained_models(self):
        first, _ = self.run_history()
        self.set_input([observation(name="Different", value=9)], build="200")
        second, _ = self.run_history()
        (self.root / second["models"]["path"]).unlink()
        reader = history.read
        def without_ancestry(root, run_id, **kwargs):
            self.assertNotEqual(first["run_id"], run_id)
            return reader(root, run_id, **kwargs)
        with patch.object(history, "read", side_effect=without_ancestry), patch.object(history, "contract", return_value="next-contract"):
            third, _ = self.run_history()
        self.assertEqual(second["run_id"], third["parent_run"])
        self.assertNotIn("continuity_aliases", third)
        before, after = history.load_state(self.root, second), history.load_state(self.root, third)
        self.assertEqual({key for key, state in before.items() if state["status"] == "present"},
                         {key for key, state in after.items() if state["status"] == "present"})


    def test_native_nested_extra_ownership_is_unrecognized_and_kept(self):
        from wikibuild import staging
        unknown = self.root / ".local/history/staging" / ("f" * 32)
        unknown.mkdir(parents=True)
        value = {"schema_version": 1, "stage": "history", "attempt_id": unknown.name,
                 "created_utc": "2026-01-01T00:00:00+00:00", "state": "materializing"}
        data = (json.dumps(value, separators=(",", ":")).encode()[:-1]
                + b',"extra":' + b"[" * 500 + b"0" + b"]" * 500 + b"}")
        self.assertLess(len(data), staging.MAX_RECORD_BYTES)
        self.assertIsInstance(json.loads(data)["extra"], list)  # Native decoder, no substitutions.
        marker = unknown / staging.OWNER
        marker.write_bytes(data)
        self.run_history()
        self.assertEqual(marker.stat().st_size, len(data))
        self.assertEqual(marker.read_bytes(), data)
        with self.assertRaisesRegex(ContractError, "Unrecognized staging ownership record"):
            staging.record(unknown, "history")
        report = json.loads(unknown.parent.with_name(unknown.parent.name + "-retention.json").read_bytes())
        self.assertTrue(any(row["stage"] == unknown.name and "Unrecognized staging ownership record" in row["reason"]
                            for row in report["retained"]))
        completed = [path for path in unknown.parent.iterdir() if path != unknown
                     and staging.record(path, "history")[0]["state"] == "completed"]
        self.assertTrue(completed)
        self.assertTrue(all((path / staging.OWNER).stat().st_size <= staging.MAX_RECORD_BYTES for path in completed))

    def test_redirected_staging_root_is_refused_without_touching_target(self):
        from wikibuild import staging
        folder = self.root / ".local/history/staging"
        outside = self.root / "unrelated"
        outside.mkdir()
        for index in range(2):
            victim = outside / (str(index) * 32)
            victim.mkdir()
            (victim / staging.OWNER).write_bytes(json_bytes({
                "schema_version": 1, "stage": "history", "attempt_id": victim.name,
                "created_utc": f"2026-01-0{index + 1}T00:00:00+00:00", "state": "abandoned"}))
            (victim / "payload").write_bytes(b"outside the literal stage root")
        before = {path.relative_to(outside): path.read_bytes() for path in outside.rglob("*") if path.is_file()}
        folder.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(folder), str(outside)],
                                    capture_output=True, text=True)
            if result.returncode:
                self.skipTest("Cannot create staging root junction: " + result.stderr)
            self.addCleanup(folder.rmdir)
        else:
            try:
                folder.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Cannot create staging root symlink: {exc}")
            self.addCleanup(folder.unlink)
        with self.assertRaisesRegex(ContractError, "Redirected staging path"):
            self.run_history()
        after = {path.relative_to(outside): path.read_bytes() for path in outside.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        report = json.loads(folder.with_name(folder.name + "-retention.json").read_bytes())
        self.assertTrue(any("Redirected staging path" in row["reason"] for row in report["retained"]))


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

    def test_uneven_renumbering_keeps_keys_revisions_and_raw_relationship_provenance(self):
        def capture(ids):
            self.metadata = {source: {"type": "MonoBehaviour", "class": "Icon_Info", "assembly": "Item_Info", "name": name}
                             for source, name in zip(ids, ("Tool", "Rock", "Metal"))}
            rows = [{**observation(source=source, name=name), "component": {"assembly": "Item_Info", "class": "Icon_Info"}}
                    for source, name in zip(ids, ("Tool", "Rock", "Metal"))]
            rows[0]["relationships"] = [{"predicate": "produces-item", "source_field": f"/materials/{i}",
                                         "target_source_id": target, "status": "resolved"}
                                        for i, target in enumerate(ids[1:])]
            return rows

        self.set_input(capture(("bundle#10", "bundle#20", "bundle#30")))
        first, _ = self.run_history()
        before = {state["descriptor"]["name"]: state for state in history.load_state(self.root, first).values()}
        self.set_input(capture(("bundle#8", "bundle#16", "bundle#31")), build="200")
        original = history.write_changed
        def fail_pointer(path, data):
            if path == self.root / "identity/latest.json":
                raise OSError("renumbered pointer interrupted")
            return original(path, data)
        with patch.object(history, "write_changed", side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, "renumbered pointer interrupted"):
                self.run_history()
        self.assertEqual(first["run_id"], history.latest(self.root)["run_id"])
        second, recovered = self.run_history()
        self.assertTrue(recovered["reused"])
        self.assertEqual({"unchanged": 3}, second["counts"])
        after = {state["descriptor"]["name"]: state for state in history.load_state(self.root, second).values()}
        for name in before:
            for field in ("entity_key", "revision_id", "first_seen", "last_changed"):
                self.assertEqual(before[name][field], after[name][field])
            self.assertEqual(before[name]["descriptor"]["facts_hash"], after[name]["descriptor"]["facts_hash"])
            self.assertEqual("unique-typed-anchor", after[name]["decision"]["rule"])
        tool = next(row for row in model.rows(extraction.artifact(self.root, second["models"])) if row["semantic"]["name"] == "Tool")
        self.assertEqual(["bundle#16", "bundle#31"], [link["target_source_id"] for link in tool["provenance"]["relationships"]])
        self.assertEqual({before["Rock"]["entity_key"], before["Metal"]["entity_key"]},
                         {target for link in tool["semantic"]["relationships"] for target in link["targets"]})
        pointer = self.root / "identity/latest.json"
        stamp = pointer.stat().st_mtime_ns
        repeated, metrics = self.run_history()
        self.assertEqual(second, repeated)
        self.assertEqual({"reused": True, "source_bytes_read": 0}, metrics)
        self.assertEqual(stamp, pointer.stat().st_mtime_ns)
        self.assertEqual(first, history.read(self.root, first["run_id"]))

    def test_changed_value_revises_only_affected_entity(self):
        self.metadata["bundle#2"] = self.metadata["bundle#1"]
        self.set_input([observation(), observation(source="bundle#2", name="B")])
        self.run_history()
        self.set_input([observation(value=8), observation(source="bundle#2", name="B")], build="200")
        result, _ = self.run_history()
        self.assertEqual(1, result["counts"]["changed"])
        self.assertEqual(1, result["counts"]["unchanged"])

    def test_reordered_definitions_keep_parent_keys_revisions_and_provenance_after_retry(self):
        def capture(source, order, targets):
            rows, self.metadata = skill_capture(source, order, targets)
            for name, target in zip(order, targets):
                rows.append({**observation(source=target, name=name), "kind": "configuration", "topic": "technical-reference",
                             "component": {"assembly": "Language", "class": "Language_Text"}, "facts": {"text": name}})
            return rows
        self.set_input(capture("bundle#10", ("Forestry", "Gunsmith"), ("bundle#100", "bundle#200")))
        first, _ = self.run_history()
        before = {(row["descriptor"]["kind"], row["descriptor"]["name"]): row for row in history.load_state(self.root, first).values()}
        self.set_input(capture("bundle#8", ("Gunsmith", "Forestry"), ("bundle#202", "bundle#101")), build="200")
        original = history.write_changed
        def fail_pointer(path, data):
            if path == self.root / "identity/latest.json":
                raise OSError("definition pointer interrupted")
            return original(path, data)
        with patch.object(history, "write_changed", side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, "definition pointer interrupted"):
                self.run_history()
        self.assertEqual(first["run_id"], history.latest(self.root)["run_id"])
        second, recovered = self.run_history()
        self.assertTrue(recovered["reused"])
        self.assertEqual({"unchanged": 5}, second["counts"])
        after = {(row["descriptor"]["kind"], row["descriptor"]["name"]): row for row in history.load_state(self.root, second).values()}
        for key, state in before.items():
            self.assertEqual(state["entity_key"], after[key]["entity_key"])
            self.assertEqual(state["revision_id"], after[key]["revision_id"])
            self.assertEqual(state["last_changed"], after[key]["last_changed"])
        skill = next(row for row in model.rows(extraction.artifact(self.root, second["models"]))
                     if row["semantic"]["kind"] == "skill" and row["semantic"]["name"] == "Gunsmith")
        self.assertEqual("bundle#8", skill["provenance"]["parent_source_id"])
        self.assertEqual("/_SurviveSkills/0", skill["provenance"]["source_field_base"])
        self.assertIn("/_SurviveSkills/0/_skill/maxLv", skill["provenance"]["evidence"][0]["fields"])
        self.assertEqual(before[("survival-rule", "PlayerSkills")]["entity_key"],
                         next(link["targets"][0] for link in skill["semantic"]["relationships"] if link["predicate"] == "defined-by"))
        self.assertEqual(second, self.run_history()[0])
        self.assertEqual(first, history.read(self.root, first["run_id"]))

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


class MetadataTests(unittest.TestCase):
    def test_scope_coverage_and_unselected_context_counterpart_are_pinned(self):
        index = [{"id": "bundle#1", "type": "GameObject", "name": "Snow_Heavy"},
                 {"id": "bundle#8", "type": "GameObject", "name": "Fog_Heavy"}]
        class PinnedSource:
            bytes_read = 0
            blobs = {"Catalog/objects/bundle.jsonl": {}}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def records(self, path):
                return iter(index)
        fog = identity.typed_anchor("bundle#1", index[1])
        with patch.object(history, "Source", return_value=PinnedSource()) as source:
            source.object_path.side_effect = Source.object_path
            metadata, _ = history.relevant_metadata("source", "revision", {"bundle#1", "missing#1", "catalog-type/summary"}, [fog])
        self.assertEqual({"bundle#1", "bundle#8"}, set(metadata))
        self.assertEqual({"bundle"}, metadata.captured_scopes)
        self.assertEqual(fog, identity.target_anchors(metadata)["bundle#8"])

    def test_pinned_hierarchy_and_raw_callers_supply_context_anchors(self):
        records, catalog = {}, []
        def add(key, name, engine_type, fields, refs, assembly=None, cls=None):
            catalog.append({"id": key, "name": name, "type": engine_type, "assembly": assembly, "class": cls})
            records[key] = {"id": key, "type": engine_type, "fields": fields, "references": refs}
            if engine_type == "MonoBehaviour":
                records[key]["script"] = {"assembly": assembly, "class": cls}
        def ref(field, target):
            return {"field": field, "target": target, "status": "resolved"}
        def node(number, name, father, children, component=None):
            owner, transform = f"bundle#{number}", f"bundle#{number + 100}"
            refs = [ref("/m_Component/0/component", transform)]
            if component:
                refs.append(ref("/m_Component/1/component", component))
            add(owner, name, "GameObject", {"m_Name": name}, refs)
            fields = {"m_Father": {"m_FileID": 0, "m_PathID": 0 if father is None else father + 100}}
            refs = [ref("/m_GameObject", owner), *[ref(f"/m_Children/{i}", f"bundle#{child + 100}") for i, child in enumerate(children)]]
            if father is not None:
                refs.append(ref("/m_Father", f"bundle#{father + 100}"))
            add(transform, name, "RectTransform", fields, refs)
        node(100, "Canvas", None, [101, 103])
        node(101, "Bag", 100, [102])
        node(102, "Icon", 101, [], "bundle#10")
        node(103, "Crafting", 100, [104])
        node(104, "Icon", 103, [], "bundle#20")
        for source, owner in (("bundle#10", "bundle#102"), ("bundle#20", "bundle#104")):
            add(source, "Icon", "MonoBehaviour", {"_slotIndex": 0}, [ref("/m_GameObject", owner)], "UI", "Slot_Info")
        for source in ("bundle#30", "bundle#31"):
            add(source, "Backpack", "MonoBehaviour", {"_Infos": [{"languageType": 2, "text": "Backpack"}]}, [], "Language", "Language_Text")
        add("bundle#40", "HotKeys", "MonoBehaviour", {}, [ref("/_BagText", "bundle#30")], "UI", "Player_HotKeys")
        add("bundle#41", "Save", "MonoBehaviour", {}, [ref("/_DeadBagIconTitle", "bundle#31")], "SaveData", "Save_Player_Data")
        class PinnedSource:
            def records(self, path):
                return iter(catalog)
            @contextmanager
            def lines(self, path):
                yield (json.dumps(row, sort_keys=True).encode() + b"\n" for row in records.values())
        metadata = {row["id"]: {**row, "anchor_count": 2} for row in catalog if row["id"] in {"bundle#10", "bundle#20", "bundle#30", "bundle#31"}}
        history.contextual_metadata(PinnedSource(), metadata)
        self.assertEqual(["Canvas", "Bag", "Icon"], metadata["bundle#10"]["hierarchy"])
        self.assertEqual(["Canvas", "Crafting", "Icon"], metadata["bundle#20"]["hierarchy"])
        self.assertEqual([None, 0, 0], metadata["bundle#10"]["hierarchy_ordinals"])
        self.assertEqual([None, 1, 0], metadata["bundle#20"]["hierarchy_ordinals"])
        anchors = identity.target_anchors(metadata)
        self.assertNotEqual(anchors["bundle#10"], anchors["bundle#20"])
        self.assertNotEqual(anchors["bundle#30"], anchors["bundle#31"])
        self.assertEqual("/_DeadBagIconTitle", anchors["bundle#31"]["callers"][0]["role"])
        # A missing parent-child corroboration cannot become a complete hierarchy.
        records["bundle#201"]["references"] = [ref("/m_GameObject", "bundle#101"), ref("/m_Father", "bundle#200")]
        fresh = {row["id"]: {**row, "anchor_count": 2} for row in catalog if row["id"] in {"bundle#10", "bundle#20"}}
        history.contextual_metadata(PinnedSource(), fresh)
        self.assertNotIn("hierarchy", fresh["bundle#10"])
        self.assertNotIn("bundle#10", identity.target_anchors(fresh))

    def test_target_anchor_uniqueness_counts_unselected_catalog_objects(self):
        index = [{"id": f"bundle#{i}", "type": "GameObject", "name": "Owner" if i == 1 else "Target"}
                 for i in (1, 2, 3)]
        class PinnedSource:
            bytes_read = 0
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def records(self, path):
                self.bytes_read += 120
                return iter(index)
        with patch.object(history, "Source", return_value=PinnedSource()) as source:
            metadata, source_bytes = history.relevant_metadata("source", "pinned-revision", {"bundle#1", "bundle#2"})
        source.assert_called_once_with("source", "pinned-revision")
        self.assertEqual(240, source_bytes)
        self.assertEqual({"bundle#1", "bundle#2"}, set(metadata))
        self.assertEqual("Owner", metadata["bundle#1"]["name"])
        self.assertEqual(2, metadata["bundle#2"]["anchor_count"])
        self.assertEqual({"bundle#1"}, set(identity.target_anchors(metadata)))
        self.assertIsNone(identity.describe(observation(source="bundle#2"), metadata)["anchor"])


if __name__ == "__main__":
    unittest.main()
