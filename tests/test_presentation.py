"""Player-card examples from the reviewed item and combat records."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from wikibuild import presentation


REGISTRY = Path(__file__).resolve().parents[1] / "presentation" / "fields.json"
GAME_TEXT = {
    "_Damage_Title": "Damage: ", "_ArrowDamage": "Arrow Damage:",
    "_ArrowSpeed": "Speed: ", "_GunFireRate_Title": "Fire rate:",
    "_GunMaxMag_Title": "Capacity:", "_GunAmmoType_Title": "Ammo:",
    "_HeadShot_Instruct": "Head Damage:", "_BladeHit_Title": "Execute:",
    "_BladeHit_Instruct": "Sharp hits may execute.", "_HitDown_Title": "Knockdown:",
    "_Dura_Title": "Durability:", "_BlockDura": "Durability:",
    "_GatheringTool": "Can harvest.", "Food": "Food:", "Water": "Water:",
    "Stamina": "Stamina:", "HP": "HP:", "_BowAmmoType_Str": "Arrow:",
}


def record(kind, facts, relationships=None, fact_labels=None):
    return {"kind": kind, "name": "Fixture", "facts": facts,
            "relationships": relationships or [], "fact_labels": fact_labels or {}}


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = presentation.load(REGISTRY)

    def test_crude_axe(self):
        axe = record("item", {
            "_baseDamage": 10.0, "_BaseMaxDurability": 165.0,
            "_baseBladeHitProb": 0.07999999821186066, "_baseHitDownProb": 0.0,
            "_headShotFactor": 4.0, "_maxMagCount": 0, "_ammoType": "",
            "_fireRate": "", "_Tag": "MeleeWeapon", "_Tags": ["HarvestTool"],
            "_SlotType": 1, "_Can_Repair": 1, "MaxStack": 1,
            "_LootCountRange": {"x": 1, "y": 1}, "_noiseDistance": 0.0,
            "_DuraCostPerAttack": -5.0, "_BuySellValue": 0,
            "_blockDurability": 0.0, "_newField": 42,
        }, [{"predicate": "repair-item", "field": "/_Can_Repair", "targets": ["kit"]}],
            {"/_SlotType": "Hand R"})
        result = presentation.card(self.registry, "item", axe, GAME_TEXT,
                                   {"kit": {"name": "Tool Kit", "topic": "items"}})
        self.assertEqual(result["eyebrow"], ["Melee weapon"])
        self.assertEqual([(stat["label"], stat["display"]) for stat in result["stats"]], [
            ("Damage", "10"), ("Head Damage", "× 4"), ("Execute", "8%"),
            ("Durability", "165"), ("Harvest", None), ("Repair with", "Tool Kit"),
            ("Stack size", "1"),
        ])
        self.assertEqual(result["notes"], [
            {"field": "/_Tags/0", "text": "Can harvest."},
            {"field": "/_baseBladeHitProb", "text": "Sharp hits may execute."},
        ])
        self.assertEqual(result["hidden"], ["/_DuraCostPerAttack", "/_noiseDistance"])
        self.assertEqual(result["technical"], ["/_BuySellValue", "/_SlotType", "/_Tag", "/_newField"])
        self.assertEqual(result["missing_game_text"], [])
        self.assertEqual(json.dumps(result, sort_keys=True), json.dumps(
            presentation.card(self.registry, "item", axe, GAME_TEXT,
                              {"kit": {"name": "Tool Kit", "topic": "items"}}), sort_keys=True))
        self.assertFalse(any(stat["field"] in {"/_baseHitDownProb", "/_maxMagCount", "/_ammoType",
                                                   "/_fireRate", "/_LootCountRange", "/_blockDurability"}
                             for stat in result["stats"]))

    def test_gun_bow_and_missing_text(self):
        gun = record("item", {"_Tag": "Gun", "_fireRate": "40 / min", "_maxMagCount": 5,
                              "_ammoType": "7.62 x 54mm"})
        result = presentation.card(self.registry, "item", gun, GAME_TEXT)
        self.assertEqual(result["eyebrow"], ["Gun"])
        self.assertEqual([(stat["label"], stat["display"]) for stat in result["stats"]], [
            ("Fire rate", "40 / min"), ("Capacity", "5"), ("Ammo", "7.62 x 54mm")])

        bow = record("item", {"_Tag": "Bow", "_baseDamage": 1.3,
                              "_fireRate": "50", "_ammoType": "Wood arrow"})
        result = presentation.card(self.registry, "item", bow, GAME_TEXT)
        self.assertEqual(result["eyebrow"], ["Bow"])
        self.assertEqual([(stat["label"], stat["display"]) for stat in result["stats"]], [
            ("Arrow Damage", "130%"), ("Speed", "50 m/s"), ("Arrow", "Wood arrow")])
        result = presentation.card(self.registry, "item", bow, {
            key: text for key, text in GAME_TEXT.items() if key != "_BowAmmoType_Str"})
        self.assertEqual(result["missing_game_text"], ["_BowAmmoType_Str"])
        self.assertEqual(result["stats"][2]["label"], "Arrow")
        bow["facts"]["_fireRate"] = "00"
        self.assertEqual([stat["label"] for stat in presentation.card(
            self.registry, "item", bow, GAME_TEXT)["stats"]], ["Arrow Damage", "Arrow"])

    def test_food_and_building_block(self):
        food = record("item", {"_Tag": "Food", "_Tags": ["+10", "+5", "", ""]})
        self.assertEqual([(stat["label"], stat["display"]) for stat in presentation.card(
            self.registry, "item", food, GAME_TEXT)["stats"]], [("Food", "+10"), ("Water", "+5")])
        block = record("item", {"_Tag": "BuildMat", "_Tags": ["ShowBI_Dura"],
                                "_blockDurability": 1800.0})
        self.assertEqual(presentation.card(self.registry, "item", block, GAME_TEXT)["stats"][0]["display"], "1,800")
        block["facts"]["_Tags"] = []
        block["facts"]["_blockDurability"] = 100
        self.assertEqual(presentation.card(self.registry, "item", block, GAME_TEXT)["stats"], [])

    def test_combat_rule_formats_and_coded_labels(self):
        combat = record("combat-rule", {"_FireRate": 0.1, "_StaminaCost": -12,
                                        "_ComboDmgFactors": [1.1, 1.3], "_GunType": 1,
                                        "_BladeHitProb": 0.025, "_AutoFire": 1,
                                        "_BulletSpeed": 250}, fact_labels={"/_GunType": "Rifle"})
        result = presentation.card(self.registry, "combat-rule", combat, GAME_TEXT)
        self.assertEqual([(stat["field"], stat["display"]) for stat in result["stats"]], [
            ("/_GunType", "Rifle"), ("/_FireRate", "600 / min"),
            ("/_AutoFire", "Yes"), ("/_BulletSpeed", "250 m/s"),
            ("/_StaminaCost", "12"), ("/_ComboDmgFactors", "× 1.1, × 1.3"),
            ("/_BladeHitProb", "2.5%"),
        ])

    def test_case_can_match_fact_label_and_rounding_is_away_from_zero(self):
        bow = record("item", {"_Tag": 9, "_baseDamage": 1.005},
                     fact_labels={"/_Tag": "Bow"})
        result = presentation.card(self.registry, "item", bow, GAME_TEXT)
        self.assertEqual(result["eyebrow"], ["Bow"])
        self.assertEqual(result["stats"][0]["display"], "100.5%")
        item = record("item", {"_baseDamage": -1.005, "_BaseMaxDurability": 2.5,
                               "_Can_Repair": 1})
        self.assertEqual([(stat["field"], stat["display"]) for stat in presentation.card(
            self.registry, "item", item, GAME_TEXT)["stats"]], [
                ("/_baseDamage", "-1.01"), ("/_BaseMaxDurability", "3")])

    def test_note_uses_raw_value_case(self):
        item = record("item", {"_Tag": "MeleeWeapon", "_Tags": ["StoneAxeHarvest"]})
        text = {**GAME_TEXT, "_GatheringToolSmallAxe": "Small axe harvest note."}
        result = presentation.card(self.registry, "item", item, text)
        self.assertEqual(result["notes"], [{"field": "/_Tags/0", "text": "Small axe harvest note."}])

    def test_pending_and_technical_kind(self):
        recipe = record("recipe", {"craftNum": 2, "craftSeconds": 20,
                                   "matsData": [{"matNeedCount": 1}]})
        result = presentation.card(self.registry, "recipe", recipe, GAME_TEXT)
        self.assertEqual(result["pending"], ["/matsData"])
        self.assertEqual(result["stats"][1]["display"], "20 s")
        self.assertIsNone(result["stats"][2]["display"])
        self.assertIsNone(presentation.card(self.registry, "creature", recipe, GAME_TEXT))

    def test_registry_rejects_bad_keys(self):
        mutations = [
            ("format", lambda r: r["kinds"]["item"]["fields"]["/_baseDamage"].update(format="unknown")),
            ("tier", lambda r: r["kinds"]["item"]["fields"]["/_baseDamage"].update(tier="unknown")),
            ("omit", lambda r: r["kinds"]["item"]["fields"]["/_baseDamage"].update(omit=["unknown"])),
            ("cases", lambda r: r["kinds"]["item"]["fields"]["/_baseDamage"].update(cases=[{"when": []}])),
        ]
        for key, mutate in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                data = copy.deepcopy(self.registry)
                mutate(data)
                path = Path(folder) / "fields.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, key):
                    presentation.load(path)


if __name__ == "__main__":
    unittest.main()
