"""Player text lint checks against ordinary names and stored identifiers."""

from pathlib import Path
import unittest

from wikibuild import presentation
from wikibuild.lint import card_findings, jargon


class JargonTests(unittest.TestCase):
    def test_examples(self):
        examples = (
            ("M1891_01", "identifier"), ("Z_Man_15", "identifier"),
            ("_baseDamage", "identifier"), ("BuildMat", "identifier"),
            ("MeleeWeapon", "identifier"), ("HarvestTool", "identifier"),
            ("ShowBI_Dura", "identifier"), ("Cop_Bullet", "identifier"),
            ("e-045871a35c62b6aa04edaddb21311d64", "hex"),
            ("deadbeef", "hex"), ("bundles/items/axe.prefab", "path"),
            ("item::serialized", "path"), ("assets/axe.png", "path"),
            ("0.07999999821186066", "raw_float"),
        )
        for value, rule in examples:
            with self.subTest(value=value):
                self.assertEqual([row["rule"] for row in jargon(value)], [rule])
        clean = ("Execute: 8%", "7.62 x 54mm", "M1891 (crafted)",
                 "Male zombie (type 15)", "HP", "AKM", "M1891", "WB",
                 ".45 ACP", "12 x 70mm", "3.1415", "5", "_", "M1A", "M4A1", "AK74M",
                 "Steam build 25587699")
        for value in clean:
            with self.subTest(value=value):
                self.assertEqual(jargon(value), [])
        self.assertEqual(jargon("5", coded=True), [{"rule": "raw_enum", "match": "5"}])
        self.assertEqual(jargon("Execute: 8%", coded=True), [])

    def test_crude_axe_card_and_nested_displays(self):
        registry = presentation.load(Path(__file__).resolve().parents[1] / "presentation" / "fields.json")
        axe = {"kind": "item", "facts": {"_Tag": "MeleeWeapon", "_baseDamage": 10,
               "_baseBladeHitProb": 0.07999999821186066, "_BaseMaxDurability": 165,
               "_Tags": ["HarvestTool"]}, "relationships": [], "fact_labels": {}}
        game_text = {"_Damage_Title": "Damage:", "_BladeHit_Title": "Execute:",
                     "_BladeHit_Instruct": "Sharp hits may execute.",
                     "_Dura_Title": "Durability:", "_GatheringTool": "Can harvest."}
        card = presentation.card(registry, "item", axe, game_text)
        self.assertIn(("Execute", "8%"), [(stat["label"], stat["display"]) for stat in card["stats"]])
        self.assertEqual(card_findings(card), [])

        card["stats"].append({"field": "/_GunType", "label": "Ammo", "display": "5",
                              "order": 500})
        card["stats"].append({"field": "/matsData", "label": "Ingredients", "display": [
            {"name": "Cop_Bullet", "count": 2, "target": "e-0123456789abcdef"}]})
        card["stats"].append({"field": "/_HandCraftBullet", "label": "Effects", "display": [
            {"material": "BuildMat", "effects": [{"label": "Damage", "value": "0.07999999821186066"}]}]})
        card["notes"].append({"field": "/_Tag", "text": "Use HarvestTool"})
        found = {(row["field"], row["rule"], row["match"]) for row in card_findings(
            card, coded_fields={"/_GunType"})}
        self.assertEqual(found, {
            ("/stats/4/display", "raw_enum", "5"),
            ("/stats/5/display/0/name", "identifier", "Cop_Bullet"),
            ("/stats/6/display/0/material", "identifier", "BuildMat"),
            ("/stats/6/display/0/effects/0/value", "raw_float", "0.07999999821186066"),
            ("/notes/2/text", "identifier", "HarvestTool"),
        })


if __name__ == "__main__":
    unittest.main()
