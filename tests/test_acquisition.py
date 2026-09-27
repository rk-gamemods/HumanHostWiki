"""Keep stock quantities/targets together without copying unrelated bindings."""

import json
import unittest

from wikibuild.adapters import acquisition, components, entries
from wikibuild.adapters.schema import Selection
from wikibuild.exceptions import Exceptions


class AcquisitionTests(unittest.TestCase):
    def test_merchant_stock_keeps_biome_order_and_nested_reference_evidence(self):
        spec = acquisition.SPECS[0]
        data = {name: 0 for name in spec.fields.selected}
        data.update(_BuyPriceFactorGroups=[], _SellPriceFactorGroups=[], _BiomeItemSet=[
            {"BiomeName": "Forest", "MerchantPrefabs": [{"merchantRef": {"m_AssetGUID": "merchant"},
                 "voiceRefs": ["PRIVATE AUDIO"], "voiceTexts": ["DIALOG"]}], "Items": [
                {"typeNameLangu": {"m_PathID": 0, "m_FileID": 0}, "priceFactor": 1.5, "typeItems": [
                    {"iconRef": {"m_AssetGUID": "item"}, "randomSampleCount": 2.5,
                     "countRange": {"x": 3, "y": 8}, "future": "DO NOT EXPORT"}]}]},
            "CHANGED SHAPE", {"BiomeName": "Desert", "MerchantPrefabs": [], "Items": []}])
        record = {"id": "fixture#1", "references": [
            {"field": "/_BiomeItemSet/0/MerchantPrefabs/0/merchantRef", "status": "resolved", "targets": ["fixture#2"]},
            {"field": "/_BiomeItemSet/0/Items/0/typeItems/0/iconRef", "status": "resolved", "targets": ["fixture#3"]}]}
        issues = Exceptions()
        selector = Selection(record, spec, issues)
        facts = selector.select(data, spec.fields)
        parent = {"source_id": "fixture#1", "name": "Merchant", "kind": "loot-source",
                  "component": {"assembly": "Merchant", "class": "Merchant_Mgr"}, "notes": "Serialized",
                  "facts": facts, "relationships": selector.links,
                  "evidence": [{"path": "Catalog/objects/fixture.jsonl", "object": "fixture#1", "fields": selector.evidence}]}
        forest, desert, manager = list(entries.expand(parent, {}, {}))
        self.assertEqual("Forest merchant stock", forest["name"])
        self.assertEqual("/_BiomeItemSet/2", desert["source_field_base"])
        self.assertEqual({"x": 3, "y": 8}, forest["facts"]["Items"][0]["typeItems"][0]["countRange"])
        stock_link = next(link for link in forest["relationships"] if link["predicate"] == "merchant-stock-item")
        self.assertEqual(["fixture#3"], stock_link["target_source_ids"])
        self.assertEqual("/_BiomeItemSet/0/Items/0/typeItems/0/iconRef", stock_link["source_field"])
        self.assertFalse(any(link["source_field"].startswith("/_BiomeItemSet") for link in manager["relationships"]))
        serialized = json.dumps([forest, desert, manager])
        for forbidden in ("PRIVATE AUDIO", "DIALOG", "DO NOT EXPORT", "CHANGED SHAPE"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual({"new-field", "unsupported-field-type"}, {g["code"] for g in issues.report()["groups"]})

    def test_initial_inventory_retains_quantity_when_item_reference_is_unresolved(self):
        spec = acquisition.SPECS[2]
        issues = Exceptions()
        selector = Selection({"id": "fixture#1"}, spec, issues)
        facts = selector.select({"_InitItemsRef": [{"IconRef": {"m_AssetGUID": "unresolved"}, "itemName": "Bandage", "stack": 20}],
                                 "_allSlots": ["PRIVATE SAVE"]}, spec.fields)
        self.assertEqual(20, facts["_InitItemsRef"][0]["stack"])
        self.assertNotIn("PRIVATE", json.dumps(facts))
        self.assertEqual("initial-item", selector.links[0]["predicate"])
        self.assertEqual("unresolved-reference", issues.report()["groups"][0]["code"])

    def test_quality_tier_gaps_do_not_shift_later_factors_or_copy_save_state(self):
        spec = components.BY_CLASS[("UI", "Item_Slot_Mgr")]
        data = {name: [] for name in spec.fields.selected}
        data.update(_MaxCraftLevel=100, _MaxLootLevel=100, _qualityDamageFactors=[1, "unknown", 2],
                    _saveID="PRIVATE SAVE", _randomItemQualityIndex=4)
        issues = Exceptions()
        facts = Selection({"id": "fixture#1"}, spec, issues).select(data, spec.fields)
        self.assertEqual([1, None, 2], facts["_qualityDamageFactors"])
        self.assertNotIn("_saveID", facts)
        self.assertNotIn("_randomItemQualityIndex", facts)
        self.assertEqual(1, issues.report()["group_count"])


if __name__ == "__main__":
    unittest.main()
