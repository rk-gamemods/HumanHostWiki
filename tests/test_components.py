"""Prove nested selection, explicit gaps and bounded catalog accounting."""

import json
import unittest

from wikibuild.adapters import components, crafting, entries
from wikibuild.adapters.schema import NUMBER, OMIT, Ref, Selection, component
from wikibuild.exceptions import Exceptions
from wikibuild.source import Source
from wikibuild.storage import ContractError


class CatalogFixture:
    object_path = staticmethod(Source.object_path)

    def __init__(self, index, objects):
        self.index, self.data = index, objects
        self.dependencies, self.locations = {}, {}
        self.requested = []

    def records(self, path):
        if path == components.INPUTS[0]:
            yield from self.index
        else:
            yield from (value for key, value in sorted(self.data.items()) if self.object_path(key) == path)
        self.dependencies[path] = {"sha256": "fixture"}

    def objects(self, identities):
        self.requested.extend(identities)
        return {key: self.data[key] for key in identities if key in self.data}


class ComponentTests(unittest.TestCase):
    def test_nested_recipe_selects_quantities_and_evidenced_targets_only(self):
        record = {"id": "fixture#1", "references": [
            {"field": "/_CraftItemsData/0/perIconData/0/iconRef", "guid": "abc", "status": "resolved", "targets": ["fixture#9"]},
            {"field": "/_CraftItemsData/0/perIconData/0/iconInfo", "status": "null"},
            {"field": "/_CraftItemsData/0/perIconData/0/matsData/0/matIcon", "status": "unresolved", "guid": "def"},
        ]}
        data = {"_workbenchType": 6, "_mustKeepOpen": 1, "_CraftItemsData": [{"BigCategory": "PRIVATE UI",
            "perIconData": [{"craftNum": 2, "craftSeconds": 60.0, "iconInfo": {"m_FileID": 0, "m_PathID": 0}, "iconRef": {"m_AssetGUID": "abc"},
                "matsData": [{"matNeedCount": 3, "matIcon": {"m_AssetGUID": "def"}, "future": "DO NOT EXPORT"}]}]}]}
        issues = Exceptions()
        selected = Selection(record, crafting.SPECS[0], issues)
        facts = selected.select(data, crafting.SPECS[0].fields)
        recipe = facts["_CraftItemsData"][0]["perIconData"][0]
        self.assertEqual({"craftNum": 2, "craftSeconds": 60.0, "matsData": [{"matNeedCount": 3}]}, recipe)
        self.assertNotIn("PRIVATE", json.dumps(facts))
        self.assertNotIn("DO NOT EXPORT", json.dumps(facts))
        self.assertEqual("fixture#9", selected.links[0]["target_source_ids"][0])
        self.assertEqual("unresolved", selected.links[1]["status"])
        self.assertEqual({"new-field", "unresolved-reference"}, {entry["code"] for entry in issues.report()["groups"]})
        self.assertTrue(any("/*/" in entry["pattern"] for entry in issues.report()["groups"]))

    def test_bad_list_entry_retains_positions_and_independent_values(self):
        spec = component("test", "Test", "world-rule", "world-systems", {"values": [NUMBER], "other": int})
        issues = Exceptions()
        selector = Selection({"id": "fixture#1"}, spec, issues)
        facts = selector.select({"values": [1, True, float("nan"), 4], "other": 7}, spec.fields)
        self.assertEqual({"values": [1, None, None, 4], "other": 7}, facts)
        self.assertEqual(2, issues.report()["group_count"])

    def test_null_reference_needs_no_reference_index_entry(self):
        spec = component("test", "Test", "vehicle", "vehicles", {"seat": Ref("seat")})
        issues = Exceptions()
        selector = Selection({"id": "fixture#1"}, spec, issues)
        self.assertEqual({}, selector.select({"seat": {"m_FileID": 0, "m_PathID": 0}}, spec.fields))
        self.assertEqual([], selector.links)
        self.assertEqual(0, issues.report()["group_count"])

    def test_recipe_entries_keep_source_positions_quantities_and_parent_evidence(self):
        parent = {"source_id": "fixture#1", "name": "Bench", "kind": "workbench", "component": {"class": "Craft_Items", "assembly": "UI"},
                  "notes": "Serialized", "facts": {"_workbenchType": 6, "_CraftItemsData": [
                      {"perIconData": [{"craftNum": 2, "craftSeconds": 10, "matsData": [{"matNeedCount": 3}]}]}]},
                  "relationships": [{"predicate": "produces-item", "target_source_ids": ["fixture#2"],
                                     "source_field": "/_CraftItemsData/0/perIconData/0/iconInfo"}],
                  "evidence": [{"path": "Catalog/objects/fixture.jsonl", "object": "fixture#1", "record_sha256": "sha",
                                "fields": ["/_workbenchType", "/_CraftItemsData/0/perIconData/0/craftNum"]}]}
        recipe, bench = list(entries.expand(parent, {"fixture#2": "Engine"}, {}))
        self.assertEqual("recipe", recipe["kind"])
        self.assertEqual("Engine", recipe["name"])
        self.assertEqual(3, recipe["facts"]["matsData"][0]["matNeedCount"])
        self.assertEqual("fixture#1", recipe["evidence"][0]["object"])
        self.assertEqual(["/_CraftItemsData/0/perIconData/0/craftNum"], recipe["evidence"][0]["fields"])
        self.assertEqual({"_workbenchType": 6}, bench["facts"])
        self.assertEqual([], bench["relationships"])
        self.assertEqual("defined-by", recipe["relationships"][-1]["predicate"])

    def test_technical_policy_accounts_known_engine_and_flags_new_assembly(self):
        from wikibuild.adapters.catalog_policy import category
        self.assertEqual("technical-component", category({"type": "MonoBehaviour", "class": "UnityEngine.UI.Image", "assembly": "UnityEngine.UI"}, False, set(), set()))
        self.assertEqual("uninterpreted-component", category({"type": "MonoBehaviour", "class": "Icon_Info", "assembly": "Future"}, False, components.VIEW_CLASSES, set()))

    def test_definition_labels_reject_wrong_assembly_and_report_missing_records(self):
        pending = [{"relationships": [{"predicate": "localized-name", "target_source_ids": ["fixture#1", "fixture#2"]}]}]
        record = {"id": "fixture#1", "script": {"assembly": "Other", "class": "Language_Text"},
                  "fields": {"_Infos": [{"languageType": 2, "text": "Wrong definition"}]}}
        source = CatalogFixture([], {"fixture#1": record})
        issues = Exceptions()
        self.assertEqual({}, entries.english_labels(source, pending, issues))
        self.assertEqual(2, issues.report()["occurrences"])

    def test_catalog_accounts_every_object_and_bounds_unknown_examples(self):
        rows = [{"id": f"fixture#{i:04}", "class": "FutureFeature", "assembly": "Game", "type": "MonoBehaviour"} for i in range(100)]
        rows += [{"id": "fixture#1000", "type": "Texture2D"}]
        source = CatalogFixture(rows, {})
        issues = Exceptions()
        components.prepare(source, issues)
        source.catalog["coverage"]["decode_gaps"] = [{"id": "fixture#0001", "reason": "missing layout",
                                                     "script": {"assembly": "Game", "class": "FutureFeature"}}]
        results = list(components.extract(source, issues))
        self.assertEqual(101, source.catalog["coverage"]["objects"])
        self.assertEqual(1, source.catalog["coverage"]["accounting"]["payload-omitted"])
        self.assertEqual(1, len(results))
        self.assertEqual(100, results[0]["facts"]["record_count"])
        self.assertEqual(8, len(results[0]["examples"]))
        self.assertEqual("missing layout", results[0]["decode_gaps"][0]["reason"])
        self.assertEqual([], source.requested)
        self.assertEqual(100, issues.report()["occurrences"])

    def test_known_pattern_new_objects_processed_despite_unknown_component(self):
        rows = [
            {"id": "fixture#1", "name": "Engine", "type": "MonoBehaviour", "assembly": "Item_Info", "class": "ItemInfo_Engine", "record": {"sha256": "verified"}},
            {"id": "fixture#2", "name": "New", "type": "MonoBehaviour", "assembly": "Game", "class": "FutureFeature"},
        ]
        record = {"id": "fixture#1", "script": {"assembly": "Item_Info", "class": "ItemInfo_Engine"},
                  "fields": {"EnginePower": 30, "EngineSpeedFactor": 80, "FuelMax": 1000, "FuelLeft": 200}}
        source = CatalogFixture(rows, {"fixture#1": record})
        issues = Exceptions()
        components.prepare(source, issues)
        results = list(components.extract(source, issues))
        self.assertEqual("vehicle-rule", results[0]["kind"])
        self.assertEqual(30, results[0]["facts"]["EnginePower"])
        self.assertNotIn("FuelLeft", results[0]["facts"])
        self.assertEqual("verified", results[0]["evidence"][0]["record_sha256"])
        self.assertEqual(["fixture#1"], source.requested)
        self.assertEqual(1, issues.report()["group_count"])

    def test_class_name_reuse_in_another_assembly_cannot_select_wrong_contract(self):
        row = {"id": "fixture#1", "type": "MonoBehaviour", "assembly": "Future", "class": "ItemInfo_Engine"}
        self.assertIsNone(components.spec_for(row))
        # Old index may select by class, but raw assembly must match before extraction.
        del row["assembly"]
        source = CatalogFixture([row], {"fixture#1": {"id": "fixture#1", "script": {"assembly": "Future", "class": "ItemInfo_Engine"}}})
        issues = Exceptions()
        components.prepare(source, issues)
        results = list(components.extract(source, issues))
        self.assertFalse(any(row["kind"] == "vehicle-rule" for row in results))
        self.assertEqual("component-identity", issues.report()["groups"][0]["code"])

    def test_duplicate_index_identity_is_failure(self):
        row = {"id": "fixture#1", "type": "Texture2D"}
        with self.assertRaisesRegex(ContractError, "unique sorted"):
            components.prepare(CatalogFixture([row, row], {}), Exceptions())


if __name__ == "__main__":
    unittest.main()
