"""Identity rules must retain ambiguity instead of inventing continuity."""

import copy
import unittest

from wikibuild import identity, model
from wikibuild.storage import ContractError


def observation(source="bundle#1", name="A", value=1, key=None):
    return {"source_id": source, "name": name, "facts": {"value": value}, "kind": "item", "topic": "items-equipment",
            "observation_key": key or identity.fingerprint(["item", source])[:32], "relationships": [],
            "evidence_level": "extracted", "evidence": [{"path": "Catalog/views/items.jsonl", "object": source, "fields": ["value"]}]}


def descriptor(row, paths=()):
    row = {**row, "asset_paths": list(paths)}
    return identity.describe(row, {})


def state(row, entity="e-old", paths=()):
    return {"entity_key": entity, "status": "present", "descriptor": descriptor(row, paths),
            "decision": {"status": "new", "candidates": []}}


def match(current, previous, **kwargs):
    return identity.reconcile({row["observation_key"]: row for row in current}, previous, "build-200", "request-200", **kwargs)


class IdentityTests(unittest.TestCase):
    def test_uneven_bundle_renumbering_preserves_named_objects_and_relationships(self):
        def capture(ids):
            names = ("Sound_Mgr", "Rock", "Metal")
            metadata = {source: {"type": "MonoBehaviour", "assembly": "Sound_FX",
                                 "class": "Sound_Mgr" if index == 0 else "Sound_Mat", "name": name}
                        for index, (source, name) in enumerate(zip(ids, names))}
            rows = [observation(source=source, name=name) for source, name in zip(ids, names)]
            rows[0]["relationships"] = [{"predicate": "material", "source_field": f"/_All_Sound_Mats/{i}",
                                         "target_source_id": target, "status": "resolved"}
                                        for i, target in enumerate(ids[1:])]
            for row in rows:
                row["component"] = {key: metadata[row["source_id"]][key] for key in ("assembly", "class")}
            return [identity.describe(row, metadata) for row in rows]

        before = capture(("bundle#10", "bundle#20", "bundle#30"))
        after = capture(("bundle#8", "bundle#16", "bundle#31"))
        previous = {f"e-{i}": {"descriptor": row, "status": "present"} for i, row in enumerate(before)}
        keys, decisions = match(after, previous)
        for i, row in enumerate(after):
            self.assertEqual(f"e-{i}", keys[row["observation_key"]])
            self.assertEqual(before[i]["facts_hash"], row["facts_hash"])
            self.assertEqual("unique-typed-anchor", decisions[row["observation_key"]]["rule"])

    def test_empty_biome_marker_uses_unique_scoped_catalog_name(self):
        def marker(source, display="Forest"):
            row = {**observation(source=source, name=display), "kind": "biome", "facts": {},
                   "component": {"assembly": "Build_System", "class": "Big_Terra_Bio_Type"}}
            metadata = {source: {"type": "MonoBehaviour", "name": "Forest", **row["component"]}}
            return identity.describe(row, metadata)
        old, moved = marker("bundle#10"), marker("bundle#8", "Forest label corrected")
        keys, decisions = match([moved], {"e-forest": {"descriptor": old, "status": "present"}})
        self.assertFalse(moved["has_facts"])
        self.assertEqual("e-forest", keys[moved["observation_key"]])
        self.assertEqual("unique-typed-anchor", decisions[moved["observation_key"]]["rule"])
        elsewhere = marker("other-bundle#8")
        keys, _ = match([elsewhere], {"e-forest": {"descriptor": old, "status": "present"}})
        self.assertNotEqual("e-forest", keys[elsewhere["observation_key"]])

    def test_duplicate_anchors_on_either_side_remain_ambiguous(self):
        def named(source):
            row = {**observation(source=source), "facts": {}}
            return identity.describe(row, {source: {"type": "GameObject", "name": "Same"}})
        a, b, c, d = [named(f"bundle#{i}") for i in (1, 2, 8, 9)]
        for before, after in (([a, b], [c]), ([a], [c, d]), ([a, b], [c, d])):
            with self.subTest(before=len(before), after=len(after)):
                previous = {f"e-{i}": {"descriptor": row, "status": "present"} for i, row in enumerate(before)}
                keys, decisions = match(after, previous)
                self.assertTrue(set(keys.values()).isdisjoint(previous))
                self.assertTrue(all(value["status"] == "ambiguous" for value in decisions.values()))

    def test_anchor_requires_catalog_evidence_and_engine_type(self):
        row = {**observation(), "facts": {}}
        self.assertIsNone(identity.describe(row, {})["anchor"])
        old = identity.describe(row, {row["source_id"]: {"type": "GameObject", "name": "A"}})
        moved = {**row, "source_id": "bundle#8", "observation_key": "moved"}
        new = identity.describe(moved, {"bundle#8": {"type": "Texture2D", "name": "A"}})
        keys, decisions = match([new], {"e-old": {"descriptor": old, "status": "present"}})
        self.assertNotEqual("e-old", keys["moved"])
        self.assertEqual("ambiguous", decisions["moved"]["status"])

    def test_relationship_resolution_and_missing_targets_are_not_equal(self):
        row = observation()
        metadata = {"bundle#2": {"type": "GameObject", "name": "Target"}}
        link = {"predicate": "model", "source_field": "/ModelRef", "target_source_id": "bundle#2", "status": "resolved"}
        row["relationships"] = [link]
        resolved = identity.describe(row, metadata)["facts_hash"]
        self.assertNotEqual(resolved, identity.describe(row, {})["facts_hash"])
        row["relationships"] = [{**link, "status": "unresolved"}]
        self.assertNotEqual(resolved, identity.describe(row, metadata)["facts_hash"])
        unresolved = identity.describe(row, metadata)["facts_hash"]
        row["relationships"] = []
        self.assertNotEqual(unresolved, identity.describe(row, metadata)["facts_hash"])
        row["relationships"] = [{**link, "guid": "stable-guid"}]
        by_guid = identity.describe(row, metadata)["facts_hash"]
        row["relationships"] = [{**link, "guid": "stable-guid", "target_source_id": "bundle#99"}]
        self.assertEqual(by_guid, identity.describe(row, metadata)["facts_hash"])
        row["relationships"][0]["status"] = "unresolved"
        self.assertNotEqual(by_guid, identity.describe(row, metadata)["facts_hash"])
        row["relationships"] = [{"predicate": "model", "source_field": "/ModelRef", "guid": "stable-guid"}]
        self.assertNotEqual(by_guid, identity.describe(row, metadata)["facts_hash"])

    def test_relationship_fingerprint_preserves_relative_field_role_and_predicate(self):
        metadata = {"bundle#2": {"type": "GameObject", "name": "Target"}}
        row = {**observation(), "source_field_base": "/definitions/0",
               "relationships": [{"predicate": "model", "source_field": "/definitions/0/model", "target_source_id": "bundle#2"}]}
        before = identity.describe(row, metadata)["facts_hash"]
        row["source_field_base"] = "/definitions/3"
        row["relationships"][0]["source_field"] = "/definitions/3/model"
        self.assertEqual(before, identity.describe(row, metadata)["facts_hash"])
        row["relationships"][0]["source_field"] = "/definitions/3/other"
        self.assertNotEqual(before, identity.describe(row, metadata)["facts_hash"])
        row["relationships"][0].update(source_field="/definitions/3/model", predicate="headless-prefab")
        self.assertNotEqual(before, identity.describe(row, metadata)["facts_hash"])

    def test_duplicate_target_names_cannot_hide_relationship_changes(self):
        metadata = {f"bundle#{i}": {"type": "GameObject", "name": "Duplicate"} for i in (2, 3)}
        row = observation()
        row["relationships"] = [{"predicate": "model", "source_field": "/model", "target_source_id": "bundle#2"}]
        before = identity.describe(row, metadata)["facts_hash"]
        row["relationships"][0]["target_source_id"] = "bundle#3"
        self.assertNotEqual(before, identity.describe(row, metadata)["facts_hash"])

    def test_script_relationship_uses_assembly_and_class_not_unity_id_or_name(self):
        row = observation()
        def describe_script(source, assembly="Game", cls="Marker", name="Marker"):
            row["relationships"] = [{"predicate": "script-binding", "source_field": "/script", "target_source_id": source}]
            return identity.describe(row, {source: {"type": "MonoScript", "assembly": assembly, "class": cls, "name": name}})["facts_hash"]
        before = describe_script("bundle#2")
        self.assertEqual(before, describe_script("bundle#99", name="Incidental script label"))
        self.assertNotEqual(before, describe_script("bundle#99", assembly="Other"))
        self.assertNotEqual(before, describe_script("bundle#99", cls="Other"))

    def test_known_source_with_changed_facts_keeps_key(self):
        old = state(observation())
        new = descriptor(observation(value=2))
        keys, decisions = match([new], {"e-old": old})
        self.assertEqual("e-old", keys[new["observation_key"]])
        self.assertEqual("matched", decisions[new["observation_key"]]["status"])

    def test_renamed_source_needs_unchanged_facts(self):
        old = state(observation())
        renamed = descriptor(observation(name="Renamed"))
        keys, _ = match([renamed], {"e-old": old})
        self.assertEqual("e-old", keys[renamed["observation_key"]])
        reused = descriptor(observation(name="New feature", value=9))
        keys, decisions = match([reused], {"e-old": old})
        self.assertNotEqual("e-old", keys[reused["observation_key"]])
        self.assertEqual(["e-old"], decisions[reused["observation_key"]]["candidates"])

    def test_id_change_uses_corroborated_path(self):
        old = state(observation(), paths=["Assets/Item.prefab"])
        moved = descriptor(observation(source="other#9", value=4), ["Assets/Item.prefab"])
        keys, decisions = match([moved], {"e-old": old})
        self.assertEqual("e-old", keys[moved["observation_key"]])
        self.assertIn("asset-path", decisions[moved["observation_key"]]["evidence"])

    def test_conflicting_paths_veto_reused_source_with_changed_content(self):
        old = state(observation(), paths=["Assets/Old.prefab"])
        moved = descriptor(observation(value=9), ["Assets/Unrelated.prefab"])
        keys, decisions = match([moved], {"e-old": old})
        self.assertNotEqual("e-old", keys[moved["observation_key"]])
        self.assertEqual("ambiguous", decisions[moved["observation_key"]]["status"])

    def test_split_and_merge_never_choose_arbitrary_winner(self):
        old = state(observation(), paths=["Assets/Item.prefab"])
        a = descriptor(observation(source="bundle#2"), ["Assets/Item.prefab"])
        b = descriptor(observation(source="bundle#3"), ["Assets/Item.prefab"])
        keys, decisions = match([a, b], {"e-old": old})
        self.assertNotIn("e-old", keys.values())
        self.assertTrue(all(item["status"] == "ambiguous" for item in decisions.values()))
        old2 = state(observation(source="bundle#4"), "e-other", ["Assets/Item.prefab"])
        keys, decisions = match([a], {"e-old": old, "e-other": old2})
        self.assertEqual(["e-old", "e-other"], decisions[a["observation_key"]]["candidates"])

    def test_new_weak_candidate_does_not_break_independent_known_match(self):
        old = state(observation())
        known, new = descriptor(observation()), descriptor(observation(source="bundle#2"))
        keys, decisions = match([known, new], {"e-old": old})
        self.assertEqual("e-old", keys[known["observation_key"]])
        self.assertNotEqual("e-old", keys[new["observation_key"]])
        self.assertEqual("ambiguous", decisions[new["observation_key"]]["status"])

    def test_kind_or_component_collision_cannot_match(self):
        old = state(observation())
        changed = descriptor({**observation(), "kind": "creature", "component": {"assembly": "AI", "class": "Agent"}})
        keys, _ = match([changed], {"e-old": old}, same_capture=True)
        self.assertNotEqual("e-old", keys[changed["observation_key"]])

    def test_extractor_correction_on_same_input_preserves_identity(self):
        changed = descriptor(observation(name="Corrected name", value=99))
        keys, decisions = match([changed], {"e-old": state(observation())}, same_capture=True)
        self.assertEqual("e-old", keys[changed["observation_key"]])
        self.assertEqual("same-observation-in-capture", decisions[changed["observation_key"]]["rule"])

    def test_reviewed_classification_preserves_the_existing_technical_type_identity(self):
        old = {**observation(source="catalog-type/reporter", name="Reporter", key="unknown"),
               "kind": "unclassified", "topic": "technical-reference", "fact_scope": "catalog-type-summary",
               "facts": {"class": "Reporter", "coverage": "uninterpreted-component"}}
        corrected = {**old, "kind": "component", "observation_key": "reviewed",
                     "facts": {"class": "Reporter", "coverage": "technical-component"}}
        new = descriptor(corrected)
        assignments, decisions = match([new], {"e-old": state(old)}, same_capture=True)
        self.assertEqual("e-old", assignments[new["observation_key"]])
        self.assertEqual("matched", decisions[new["observation_key"]]["status"])

    def test_provisional_identity_and_ambiguity_survive_reprocessing(self):
        old = state(observation())
        changed = descriptor(observation(name="New feature", value=99))
        keys, decisions = match([changed], {"e-old": old})
        new_key = keys[changed["observation_key"]]
        prior = {"e-old": {**old, "status": "unresolved"}, new_key: {"status": "present", "descriptor": changed,
                  "decision": decisions[changed["observation_key"]]}}
        repeated, decisions = match([changed], prior, same_capture=True)
        self.assertEqual(new_key, repeated[changed["observation_key"]])
        self.assertEqual("ambiguous", decisions[changed["observation_key"]]["status"])

    def test_recipe_output_reference_prevents_same_numbers_becoming_a_rename(self):
        old_row = observation(name="Sword")
        old_row["relationships"] = [{"predicate": "produces-item", "guid": "sword", "source_field": "/output"}]
        new_row = observation(name="Axe")
        new_row["relationships"] = [{"predicate": "produces-item", "guid": "axe", "source_field": "/output"}]
        new = descriptor(new_row)
        _, decisions = match([new], {"e-old": state(old_row)})
        self.assertEqual("ambiguous", decisions[new["observation_key"]]["status"])

    def test_reviewed_mapping_is_explicit_and_conflicts_fail(self):
        new = descriptor(observation(source="bundle#2"))
        correction = {"snapshot_id": "build-200", "observation_key": new["observation_key"], "entity_key": "e-old", "reviewer": "fixture", "reason": "Verified rename"}
        keys, decisions = match([new], {"e-old": state(observation())}, corrections=[correction])
        self.assertEqual("e-old", keys[new["observation_key"]])
        self.assertEqual("reviewed", decisions[new["observation_key"]]["status"])
        with self.assertRaisesRegex(ContractError, "duplicate"):
            match([new], {"e-old": state(observation())}, corrections=[correction, correction])

    def test_absence_separates_removal_from_uncaptured_or_unresolved(self):
        old = state(observation())
        self.assertEqual("not-present", model.absent_status(old, ["item"], {}))
        self.assertEqual("unresolved", model.absent_status(old, ["item"], {"bundle#1": {}}))
        self.assertEqual("uncaptured", model.absent_status(old, [], {}))
        self.assertEqual("uncaptured", model.absent_status(old, ["item"], {}, captured=False))

    def test_reviewed_new_allocation_survives_rule_changes(self):
        new = descriptor(observation())
        key = new["observation_key"]
        correction = {"snapshot_id": "build-200", "observation_key": key, "entity_key": "new",
                      "reviewer": "fixture", "reason": "Verified distinct identity"}
        first, decisions = identity.reconcile({key: new}, {}, "build-200", "rules-one", corrections=[correction])
        previous = {first[key]: {"descriptor": new, "status": "present", "decision": decisions[key]}}
        repeated, _ = identity.reconcile({key: new}, previous, "build-200", "rules-two", corrections=[correction])
        self.assertEqual(first, repeated)


if __name__ == "__main__":
    unittest.main()
