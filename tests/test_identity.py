"""Identity rules must retain ambiguity instead of inventing continuity."""

import copy
import unittest

from wikibuild import identity, model
from wikibuild.adapters import entries
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


def skill_capture(source="bundle#10", order=("Forestry", "Gunsmith"), targets=("bundle#100", "bundle#200")):
    parent = {**observation(source=source, name="PlayerSkills"), "kind": "skill", "topic": "skills-survival",
              "component": {"assembly": "Creature", "class": "All_Skills_Set"}, "notes": "Serialized",
              "facts": {"_CraftSkills": [], "_FightSkills": [], "_SurviveSkills": [{"_skill": {"maxLv": 4}} for _ in order]},
              "relationships": [{"predicate": "localized-name", "source_field": f"/_SurviveSkills/{i}/_skill/_name",
                                 "target_source_ids": [target], "status": "resolved"} for i, target in enumerate(targets)]}
    parent["evidence"][0]["fields"] = [f"/_SurviveSkills/{i}/_skill/maxLv" for i in range(len(order))]
    labels = {target: {"name": name, "evidence": {"path": "Catalog/views/items.jsonl", "object": target,
                                                "fields": ["/_Infos/0/text"]}} for name, target in zip(order, targets)}
    metadata = {source: {"type": "MonoBehaviour", "name": "PlayerSkills", **parent["component"]},
                **{target: {"type": "MonoBehaviour", "assembly": "Language", "class": "Language_Text", "name": name}
                   for name, target in zip(order, targets)}}
    rows = list(entries.expand(parent, {}, labels))
    for row in rows:
        row["topic"] = "skills-survival"  # Extraction normally assigns the kind's topic.
    return rows, metadata


class IdentityTests(unittest.TestCase):
    def test_equal_fog_and_snow_facts_do_not_make_reused_ids_renames(self):
        def capture(ids):
            rows = [{**observation(source=source, name=name), "kind": "world-rule",
                     "component": {"assembly": "Enviro", "class": "EnviroWeatherType"}}
                    for source, name in zip(ids, ("Fog_Heavy", "Snow_Heavy"))]
            metadata = {row["source_id"]: {"type": "MonoBehaviour", "name": row["name"], **row["component"]} for row in rows}
            return [identity.describe(row, metadata) for row in rows]
        before, after = capture(("bundle#1", "bundle#2")), capture(("bundle#2", "bundle#1"))
        keys, decisions = match(after, {f"e-{i}": {"status": "present", "descriptor": row} for i, row in enumerate(before)})
        self.assertEqual(["e-0", "e-1"], [keys[row["observation_key"]] for row in after])
        self.assertEqual(before[0]["facts_hash"], before[1]["facts_hash"])
        self.assertTrue(all(value["status"] == "matched" for value in decisions.values()))

    def test_commit_warning_is_new_when_the_old_id_occupant_continues_elsewhere(self):
        def text(source, name):
            row = {**observation(source=source, name=name), "kind": "configuration", "facts": {"text": name},
                   "component": {"assembly": "Language", "class": "Language_Text"}}
            return identity.describe(row, {source: {"type": "MonoBehaviour", "name": name, **row["component"]}})
        old, continuing, warning = text("bundle#1", "PICK"), text("bundle#7", "PICK"), text("bundle#1", "Commit exhaustion will case")
        keys, decisions = match([continuing, warning], {"e-pick": {"status": "present", "descriptor": old}})
        self.assertEqual("e-pick", keys[continuing["observation_key"]])
        self.assertNotEqual("e-pick", keys[warning["observation_key"]])
        self.assertEqual("new", decisions[warning["observation_key"]]["status"])
        self.assertEqual([], decisions[warning["observation_key"]]["candidates"])

    def test_strong_anchor_re_evaluates_a_provisional_decision(self):
        row = observation()
        described = identity.describe(row, {row["source_id"]: {"type": "GameObject", "name": "A"}})
        prior = {"e-provisional": {"status": "present", "descriptor": described,
                                  "decision": {"status": "ambiguous", "candidates": ["e-older"]}}}
        keys, decisions = match([described], prior, same_capture=True)
        self.assertEqual("e-provisional", keys[described["observation_key"]])
        self.assertEqual("matched", decisions[described["observation_key"]]["status"])

    def test_continuity_replays_original_keys_and_provisional_aliases_chronologically(self):
        captures = []
        for i, source in enumerate(("bundle#10", "bundle#8", "bundle#6")):
            row = observation(source=source)
            described = identity.describe(row, {source: {"type": "GameObject", "name": "A"}})
            captures.append({"run_id": str(i), "parent_run": str(i - 1) if i else None, "snapshot_id": str(i), "capture_id": str(i),
                             "descriptors": {row["observation_key"]: described},
                             "records": {row["observation_key"]: {"entity_key": "e-original" if not i else f"e-provisional-{i}",
                                         "decision": {"status": "new" if not i else "ambiguous", "candidates": [] if not i else ["e-original"]}}}})
        before = copy.deepcopy(captures)
        states, aliases = identity.continuity(captures)
        self.assertEqual({"e-provisional-1", "e-provisional-2"}, set(aliases))
        self.assertTrue(all(proof["entity_key"] == "e-original" and proof["origin_run"] == "0" for proof in aliases.values()))
        self.assertEqual("bundle#6", states["e-original"]["descriptor"]["source_id"])
        self.assertEqual((states, aliases), identity.continuity(captures))
        self.assertEqual(before, captures)
        with self.assertRaisesRegex(ContractError, "chronology"):
            identity.continuity(list(reversed(captures)))

    def test_continuity_never_aliases_keys_that_represented_coexisting_equal_objects(self):
        captures = []
        for i, ids in enumerate((("bundle#1", "bundle#2"), ("bundle#8", "bundle#9"))):
            rows = [observation(source=source, name=name) for source, name in zip(ids, ("One", "Two"))]
            metadata = {row["source_id"]: {"type": "GameObject", "name": row["name"]} for row in rows}
            captures.append({"run_id": str(i), "parent_run": "0" if i else None, "snapshot_id": str(i), "capture_id": str(i),
                             "descriptors": {row["observation_key"]: identity.describe(row, metadata) for row in rows},
                             "records": {row["observation_key"]: {"entity_key": f"e-{1 - n if i else n}",
                                          "decision": {"status": "ambiguous" if i else "new", "candidates": []}}
                                         for n, row in enumerate(rows)}})
        states, aliases = identity.continuity(captures)
        self.assertEqual({}, aliases)
        self.assertEqual({"One", "Two"}, {row["descriptor"]["name"] for row in states.values()})
        self.assertEqual(2, sum(row["status"] == "present" for row in states.values()))

    def test_chronological_replay_separates_a_legacy_fog_key_incorrectly_used_for_snow(self):
        captures = []
        for i, ids in enumerate((("bundle#1", "bundle#2"), ("bundle#8", "bundle#1"), ("bundle#6", "bundle#8"))):
            rows = [observation(source=source, name=name) for source, name in zip(ids, ("Fog_Heavy", "Snow_Heavy"))]
            metadata = {row["source_id"]: {"type": "GameObject", "name": row["name"]} for row in rows}
            captures.append({"run_id": str(i), "parent_run": str(i - 1) if i else None, "snapshot_id": str(i), "capture_id": str(i),
                             "descriptors": {row["observation_key"]: identity.describe(row, metadata) for row in rows},
                             "records": {row["observation_key"]: {"entity_key": ("e-fog", "e-snow")[n] if not i else ("e-provisional-fog", "e-fog")[n],
                                          "decision": {"status": "new" if not i else "matched" if n else "ambiguous", "candidates": ["e-fog"] if i else []}}
                                         for n, row in enumerate(rows)}})
        states, aliases = identity.continuity(captures)
        self.assertEqual("Fog_Heavy", states["e-fog"]["descriptor"]["name"])
        self.assertEqual("Snow_Heavy", states["e-snow"]["descriptor"]["name"])
        self.assertEqual({"e-provisional-fog"}, set(aliases))
        self.assertEqual("e-fog", aliases["e-provisional-fog"]["entity_key"])
        self.assertEqual(2, sum(row["status"] == "present" for row in states.values()))

    def test_same_capture_match_with_nonunique_anchor_cannot_prove_an_alias(self):
        captures = []
        for i in range(2):
            rows = [observation(source=f"bundle#{n}") for n in (1, 2)]
            descriptors = {row["observation_key"]: identity.describe(row, {row["source_id"]: {"type": "GameObject", "name": "Same"}}) for row in rows}
            captures.append({"run_id": str(i), "parent_run": "0" if i else None, "snapshot_id": "same", "capture_id": "same",
                             "descriptors": descriptors,
                             "records": {row["observation_key"]: {"entity_key": f"e-provisional-{n}" if i else f"e-{n}",
                                          "decision": {"status": "ambiguous" if i else "new", "candidates": [f"e-{n}"] if i else []}}
                                         for n, row in enumerate(rows)}})
        states, aliases = identity.continuity(captures)
        self.assertEqual({}, aliases)
        self.assertEqual(2, sum(row["status"] == "present" for row in states.values()))

    def test_slot_hierarchy_separates_bag_and_crafting_icons(self):
        def capture(ids):
            rows, metadata = [], {}
            for source, owner in zip(ids, ("Bag", "Crafting")):
                row = {**observation(source=source, name="Icon"), "kind": "equipment", "facts": {"_slotIndex": 0},
                       "component": {"assembly": "UI", "class": "Slot_Info"}}
                rows.append(row)
                metadata[source] = {"type": "MonoBehaviour", "name": "Icon", **row["component"], "slot_index": 0,
                                    "hierarchy": ["Canvas", owner, "Icon"], "hierarchy_ordinals": [None, 0, 2]}
            return [identity.describe(row, metadata) for row in rows]
        before, after = capture(("bundle#10", "bundle#20")), capture(("bundle#11", "bundle#23"))
        previous = {f"e-{i}": {"descriptor": row, "status": "present"} for i, row in enumerate(before)}
        keys, decisions = match(after, previous)
        for i, row in enumerate(after):
            self.assertEqual(f"e-{i}", keys[row["observation_key"]])
            self.assertEqual("slot-owner-and-index", decisions[row["observation_key"]]["rule"])

    def test_slot_ordinal_change_requires_review_even_at_same_source_and_path(self):
        row = {**observation(name="Icon"), "kind": "equipment", "facts": {"_slotIndex": 0},
               "component": {"assembly": "UI", "class": "Slot_Info"}, "asset_paths": ["Assets/Bag.prefab"]}
        metadata = {row["source_id"]: {"type": "MonoBehaviour", "name": "Icon", **row["component"], "slot_index": 0,
                                      "hierarchy": ["Bag", "Icon"], "hierarchy_ordinals": [None, 2]}}
        old = identity.describe(row, metadata)
        metadata[row["source_id"]]["hierarchy_ordinals"] = [None, 3]
        moved = identity.describe(row, metadata)
        for same_capture in (False, True):
            with self.subTest(same_capture=same_capture):
                keys, decisions = match([moved], {"e-old": {"descriptor": old, "status": "present"}}, same_capture=same_capture)
                self.assertNotEqual("e-old", keys[moved["observation_key"]])
                self.assertEqual("ambiguous", decisions[moved["observation_key"]]["status"])
                self.assertEqual(["e-old"], decisions[moved["observation_key"]]["candidates"])

    def test_duplicate_backpack_texts_follow_distinct_caller_roles(self):
        def capture(ids, callers):
            metadata = {caller: {"type": "MonoBehaviour", "assembly": "UI", "class": cls, "name": "Services"}
                        for caller, cls in zip(callers, ("Player_HotKeys", "Save_Player_Data"))}
            rows = []
            for source, caller, role in zip(ids, callers, ("/_BackpackText", "/_DeadBagIconTitle")):
                row = {**observation(source=source, name="Backpack"), "kind": "configuration", "facts": {"text": "Backpack"},
                       "component": {"assembly": "Language", "class": "Language_Text"}}
                rows.append(row)
                metadata[source] = {"type": "MonoBehaviour", "name": "Backpack", **row["component"], "text": "Backpack",
                                    "callers": [{"source_id": caller, "source_field": role}]}
            return [identity.describe(row, metadata) for row in rows]
        before = capture(("bundle#10", "bundle#20"), ("bundle#30", "bundle#40"))
        after = capture(("bundle#11", "bundle#23"), ("bundle#32", "bundle#37"))
        keys, decisions = match(after, {f"e-{i}": {"descriptor": row, "status": "present"} for i, row in enumerate(before)})
        for i, row in enumerate(after):
            self.assertEqual(f"e-{i}", keys[row["observation_key"]])
            self.assertEqual("caller-role-and-text", decisions[row["observation_key"]]["rule"])

    def test_pick_tooltip_and_language_manager_survive_list_index_changes(self):
        def capture(ids, index):
            metadata = {"bundle#30": {"type": "MonoBehaviour", "assembly": "UI", "class": "BuildTooltip", "name": "BuildTooltip"},
                        "bundle#40": {"type": "MonoBehaviour", "assembly": "Language", "class": "Language_Mgr", "name": "Language_Mgr"}}
            rows = []
            for source, caller, role in zip(ids, ("bundle#30", "bundle#40"), ("/_PickTitle", f"/_AllTexts/{index}")):
                row = {**observation(source=source, name="PICK"), "kind": "configuration", "facts": {"text": "PICK"},
                       "component": {"assembly": "Language", "class": "Language_Text"}}
                rows.append(row)
                metadata[source] = {"type": "MonoBehaviour", "name": "PICK", **row["component"], "text": "PICK",
                                    "callers": [{"source_id": caller, "source_field": role}]}
            return [identity.describe(row, metadata) for row in rows]
        before, after = capture(("bundle#10", "bundle#20"), 0), capture(("bundle#11", "bundle#23"), 8)
        keys, _ = match(after, {f"e-{i}": {"descriptor": row, "status": "present"} for i, row in enumerate(before)})
        self.assertEqual(["e-0", "e-1"], [keys[row["observation_key"]] for row in after])

    def test_normalized_caller_role_cannot_merge_identical_list_texts(self):
        metadata = {"bundle#30": {"type": "MonoBehaviour", "assembly": "Language", "class": "Language_Mgr", "name": "Language_Mgr"}}
        rows = []
        for i, source in enumerate(("bundle#10", "bundle#20")):
            row = {**observation(source=source, name="Backpack"), "kind": "configuration", "facts": {"text": "Backpack"},
                   "component": {"assembly": "Language", "class": "Language_Text"}}
            rows.append(row)
            metadata[source] = {"type": "MonoBehaviour", "name": "Backpack", **row["component"], "text": "Backpack",
                                "callers": [{"source_id": "bundle#30", "source_field": f"/_AllTexts/{i}"}]}
        before = [identity.describe(row, metadata) for row in rows]
        after = [identity.describe(row, metadata) for row in rows]
        _, decisions = match(after, {f"e-{i}": {"descriptor": row, "status": "present"} for i, row in enumerate(before)})
        self.assertTrue(all(decision["status"] == "ambiguous" for decision in decisions.values()))

    def test_duplicate_speed_targets_keep_caller_relationship_fingerprints(self):
        def capture(ids):
            metadata = {"bundle#30": {"type": "MonoBehaviour", "assembly": "UI", "class": "DynamicToolTipSet", "name": "DynamicToolTipSet"}}
            for target, role in zip(ids, ("/data/_ArrowSpeed", "/data/_MoveSpeed")):
                metadata[target] = {"type": "MonoBehaviour", "assembly": "Language", "class": "Language_Text", "name": "Speed",
                                    "text": "Speed", "callers": [{"source_id": "bundle#30", "source_field": role}]}
            row = observation(source="bundle#30")
            row["relationships"] = [{"predicate": "tooltip-text", "source_field": role, "target_source_id": target}
                                    for target, role in zip(ids, ("/data/_ArrowSpeed", "/data/_MoveSpeed"))]
            return identity.describe(row, metadata)
        self.assertEqual(capture(("bundle#10", "bundle#20"))["facts_hash"], capture(("bundle#11", "bundle#23"))["facts_hash"])

    def test_incomplete_caller_list_cannot_claim_unique_normalized_text_role(self):
        metadata = {"bundle#30": {"type": "MonoBehaviour", "assembly": "Language", "class": "Language_Mgr", "name": "Language_Mgr",
                                   "reference_roles": [{"source_field": "/_AllTexts/0", "status": "resolved", "targets": ["bundle#10"]},
                                                       {"source_field": "/_AllTexts/1", "status": "unresolved", "targets": []}]},
                    "bundle#10": {"type": "MonoBehaviour", "assembly": "Language", "class": "Language_Text", "name": "PICK", "text": "PICK", "anchor_count": 2,
                                   "callers": [{"source_id": "bundle#30", "source_field": "/_AllTexts/0"}]}}
        self.assertNotIn("bundle#10", identity.target_anchors(metadata))

    def test_reordered_skill_array_uses_reconciled_parent_and_localized_name(self):
        rows, metadata = skill_capture()
        before = [identity.describe(row, metadata) for row in rows]
        first, _ = match(before, {})
        previous = {first[row["observation_key"]]: {"descriptor": row, "status": "present"} for row in before}
        rows, metadata = skill_capture("bundle#8", ("Gunsmith", "Forestry"), ("bundle#202", "bundle#101"))
        after = [identity.describe(row, metadata) for row in rows]
        keys, decisions = match(after, previous)
        by_name = {row["name"]: first[row["observation_key"]] for row in before}
        for row in after:
            self.assertEqual(by_name[row["name"]], keys[row["observation_key"]])
            if row["kind"] == "skill":
                self.assertEqual("parent-relative-definition", decisions[row["observation_key"]]["rule"])
                self.assertEqual(by_name["PlayerSkills"], row["anchor"]["parent_entity"])

    def test_status_effect_uses_member_name_when_localized_label_changes(self):
        def capture(source, label, member="_Bleeding_Debuff"):
            parent = {**observation(source=source, name="Skill_Mgr"), "kind": "survival-rule", "topic": "skills-survival",
                      "component": {"assembly": "Creature", "class": "Skill_Mgr"}, "notes": "Serialized",
                      "facts": {member: {"buffPeriod": 5}, "_MaxLevel": 4},
                      "relationships": [{"predicate": "localized-name", "source_field": f"/{member}/_name", "target_source_ids": ["bundle#100"]}]}
            parent["evidence"][0]["fields"] = [f"/{member}/buffPeriod", "/_MaxLevel"]
            localized = {"bundle#100": {"name": label, "evidence": {"path": "Catalog/views/items.jsonl", "object": "bundle#100", "fields": ["/_Infos/0/text"]}}}
            metadata = {source: {"type": "MonoBehaviour", "name": "Skill_Mgr", **parent["component"]},
                        "bundle#100": {"type": "MonoBehaviour", "assembly": "Language", "class": "Language_Text", "name": label}}
            return [identity.describe({**row, "topic": "skills-survival"}, metadata) for row in entries.expand(parent, {}, localized)]
        before = capture("bundle#10", "Bleeding")
        first, _ = match(before, {})
        previous = {first[row["observation_key"]]: {"descriptor": row, "status": "present"} for row in before}
        after = capture("bundle#8", "Bleeding label corrected")
        keys, _ = match(after, previous)
        old = next(row for row in before if row["kind"] == "status-effect")
        new = next(row for row in after if row["kind"] == "status-effect")
        self.assertEqual(first[old["observation_key"]], keys[new["observation_key"]])
        self.assertEqual("/_Bleeding_Debuff", new["anchor"]["member"])
        renamed_member = next(row for row in capture("bundle#8", "Bleeding", "_Other_Debuff") if row["kind"] == "status-effect")
        # Retain the same parent descriptor, but changing the member is a new definition.
        changed = [after[-1], renamed_member]
        keys, _ = match(changed, previous)
        self.assertNotEqual(first[old["observation_key"]], keys[renamed_member["observation_key"]])

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

    def test_renamed_source_needs_an_independent_asset_anchor(self):
        old = state(observation(), paths=["Assets/Item.prefab"])
        unanchored = descriptor(observation(name="Renamed"))
        keys, decisions = match([unanchored], {"e-old": old})
        self.assertNotEqual("e-old", keys[unanchored["observation_key"]])
        self.assertEqual("ambiguous", decisions[unanchored["observation_key"]]["status"])
        renamed = descriptor(observation(name="Renamed"), ["Assets/Item.prefab"])
        keys, _ = match([renamed], {"e-old": old})
        self.assertEqual("e-old", keys[renamed["observation_key"]])
        reused = descriptor(observation(name="New feature", value=9))
        keys, decisions = match([reused], {"e-old": old})
        self.assertNotEqual("e-old", keys[reused["observation_key"]])
        self.assertEqual(["e-old"], decisions[reused["observation_key"]]["candidates"])

    def test_shared_asset_path_cannot_corroborate_a_reused_id_rename(self):
        previous = {"e-fog": state(observation(name="Fog_Heavy"), paths=["Assets/Weather.asset"]),
                    "e-snow": state(observation(source="bundle#2", name="Snow_Heavy"), paths=["Assets/Weather.asset"])}
        current = descriptor(observation(name="Snow_Heavy"), ["Assets/Weather.asset"])
        keys, decisions = match([current], previous)
        self.assertNotEqual("e-fog", keys[current["observation_key"]])
        self.assertEqual("ambiguous", decisions[current["observation_key"]]["status"])

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
