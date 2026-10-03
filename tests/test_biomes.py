"""Mineable terrain entries resolve to captured items or explicit gaps."""

from pathlib import Path
import unittest
from unittest.mock import patch

from wikibuild import extraction
from wikibuild.adapters import components
from wikibuild.exceptions import Exceptions
from wikibuild.source import Source


class MineableFixture:
    object_path = staticmethod(Source.object_path)

    def __init__(self, entries):
        self.terrain = "terrain#1"
        self.prefab = "world#2"
        self.build_info = "world#3"
        self.icon_object = "icons#4"
        self.nitrate = "icons#5"
        self.chrismatite = "icons#6"
        self.index = [{"id": self.terrain, "name": "Desert_Set", "type": "MonoBehaviour",
                       "assembly": "Build_System", "class": "Terrain_Block_Info"}]
        self.data = {
            self.terrain: {"id": self.terrain, "script": {"assembly": "Build_System", "class": "Terrain_Block_Info"},
                           "fields": {"_BlockInfo": [{"CollectableItems": entries}]}},
            self.prefab: {"id": self.prefab, "type": "GameObject", "references": [
                {"field": "/m_Component/0/component", "status": "resolved", "target": self.build_info}]},
            self.build_info: {"id": self.build_info, "script": {"assembly": "Build_System", "class": "Build_Info"},
                              "references": [{"field": "/_Collectable_Info/_Items/0/_IconRef", "status": "resolved",
                                              "targets": [self.icon_object]}]},
        }
        self.items = [{"id": self.nitrate, "name": "Ore_Nitrate_Icon", "game_objects": [self.icon_object]},
                      {"id": self.chrismatite, "name": "Chrismatite_Icon", "game_objects": ["icons#7"]}]
        self.addresses = [{"entry": 42, "keys": ["BO_Ore_Nitrate"], "targets": [self.prefab],
                           "resource_type": {"m_ClassName": "UnityEngine.GameObject"}}]
        self.dependencies, self.locations = {}, {}
        self.active = False

    def records(self, path):
        if self.active:
            raise AssertionError("nested source stream")
        self.active = True
        try:
            if path == components.INPUTS[0]:
                yield from self.index
            elif path == "Catalog/views/items.jsonl":
                yield from self.items
            elif path == "Catalog/addressables.jsonl":
                yield from self.addresses
            else:
                yield from (row for identity, row in self.data.items() if self.object_path(identity) == path)
            self.dependencies[path] = {"sha256": "fixture"}
        finally:
            self.active = False

    def objects(self, identities):
        return {identity: self.data[identity] for identity in identities if identity in self.data}


class MineableTests(unittest.TestCase):
    def extract(self, entries):
        source = MineableFixture(entries)
        issues = Exceptions()
        components.prepare(source, issues)
        row = next(row for row in components.extract(source, issues) if row.get("source_id") == source.terrain)
        return source, row, issues

    def test_address_path_precedes_name_and_preserves_rate(self):
        source, row, issues = self.extract([
            {"ItemBI_refKey": "BO_Ore_Nitrate", "Name": "Chrismatite_Icon", "RandomRate": 0.2}])
        self.assertEqual(0.2, row["facts"]["_BlockInfo"][0]["CollectableItems"][0]["RandomRate"])
        self.assertEqual(source.nitrate, row["relationships"][0]["target_source_ids"][0])
        self.assertEqual("address", row["relationships"][0]["resolution"])
        self.assertEqual("/_BlockInfo/0/CollectableItems/0", row["relationships"][0]["source_field"])
        self.assertTrue(any(e["path"] == "Catalog/addressables.jsonl" and e["entry"] == 42 for e in row["evidence"]))
        self.assertEqual(0, issues.report()["group_count"])
        repeated = next(row for row in components.extract(source, Exceptions()) if row.get("source_id") == source.terrain)
        self.assertEqual(row["relationships"], repeated["relationships"])
        self.assertEqual(row["evidence"], repeated["evidence"])

    def test_exact_name_fallback(self):
        source, row, issues = self.extract([
            {"ItemBI_refKey": "BO_Missing", "Name": "Chrismatite_Icon", "RandomRate": 0.05}])
        self.assertEqual([source.chrismatite], row["relationships"][0]["target_source_ids"])
        self.assertEqual("name", row["relationships"][0]["resolution"])
        self.assertFalse(any(e["path"] == "Catalog/addressables.jsonl" for e in row["evidence"]))
        self.assertEqual(0, issues.report()["group_count"])

    def test_unresolved_entry_is_an_explicit_gap(self):
        _, row, issues = self.extract([
            {"ItemBI_refKey": "BO_Missing", "Name": "Missing_Icon", "RandomRate": 0.1}])
        self.assertEqual("unresolved", row["relationships"][0]["status"])
        self.assertEqual([], row["relationships"][0]["target_source_ids"])
        self.assertEqual("mineable-item-gap", issues.report()["groups"][0]["code"])

    def test_adapter_edit_changes_extraction_contract_hash(self):
        original = Path.read_bytes
        project = {"repositories": []}
        with patch.object(extraction, "runtime", return_value={"fixture": "parser"}):
            baseline = extraction.contract(Path.cwd(), project)
            def changed(path):
                content = original(path)
                return content + b"\n# changed contract\n" if path.name == "biomes.py" else content
            with patch.object(Path, "read_bytes", changed):
                self.assertNotEqual(baseline, extraction.contract(Path.cwd(), project))


if __name__ == "__main__":
    unittest.main()
