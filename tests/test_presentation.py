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

    def test_glossary_gives_wiki_wording_for_internal_enums(self):
        gun = record("combat-rule", {"_GunType": 4}, fact_labels={"/_GunType": "Single S Shotgun"})
        stats = presentation.card(self.registry, "combat-rule", gun, {})["stats"]
        self.assertEqual([(stat["label"], stat["display"]) for stat in stats], [("Type", "Pump-action shotgun")])
        broken = copy.deepcopy(json.loads(REGISTRY.read_text(encoding="utf-8")))
        broken["kinds"]["combat-rule"]["fields"]["/_GunType"]["glossary"] = "missing"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fields.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown glossary"):
                presentation.load(path)

    def test_harvest_family_registry_requires_exact_string_rules_and_valid_regex(self):
        base = json.loads(REGISTRY.read_text(encoding="utf-8"))
        invalid = [None, {}, ["trees"], [{"match": "tree"}],
                   [{"match": "tree", "family": "trees", "priority": 1}],
                   [{"match": 5, "family": "trees"}],
                   [{"match": "tree", "family": None}],
                   [{"match": "(", "family": "trees"}]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fields.json"
            for rules in invalid:
                registry = copy.deepcopy(base)
                registry["guides"]["harvest_families"] = rules
                path.write_text(json.dumps(registry), encoding="utf-8")
                with self.subTest(rules=rules), self.assertRaisesRegex(ValueError, "guides.harvest_families"):
                    presentation.load(path)

    def test_every_player_tier_value_has_a_label_and_format(self):
        """A31: a player sees no field without a label or with a raw value."""
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        gaps, checked = [], 0

        def walk(entry, key, inherited):
            nonlocal checked
            own = {name: value for name, value in entry.items() if name not in ("cases", "positional", "when")}
            effective = {**inherited, **own}
            if effective.get("tier") == "player" and "positional" not in entry:
                checked += 1
                gaps.extend(f"{key}: no {name}" for name in ("label", "format") if name not in effective)
            for index, case in enumerate(entry.get("cases", [])):
                walk(case, f"{key}.cases[{index}]", effective)
            for index, value in enumerate(entry.get("positional", [])):
                walk(value, f"{key}.positional[{index}]", {"tier": effective.get("tier")})

        for kind, spec in registry["kinds"].items():
            for field, entry in spec.get("fields", {}).items():
                walk(entry, f"{kind}{field}", {})
        self.assertGreater(checked, 30)
        self.assertEqual(gaps, [])

    def test_language_keys_are_their_own_english_labels(self):
        food = record("item", {"_Tag": "Food", "_Tags": ["+20", "+5", "", ""]})
        result = presentation.card(self.registry, "item", food, {})
        self.assertEqual([stat["label"] for stat in result["stats"] if stat["order"] in (90, 91)],
                         ["Food", "Water"])
        self.assertEqual(result["missing_game_text"], [])

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

    def test_handmade_ammo_effects(self):
        ammo = record("combat-rule", {"_HandCraftBullet": [
            {"BulletMat": "Cop_Bullet", "Damage_F": 1, "Range_F": 1,
             "Recoil_F": 1, "Dummy_Rate": 0, "Stuck_Rate": 0},
            {"BulletMat": "Steel_Bullet", "Damage_F": 0.87345, "Range_F": 0.8,
             "Recoil_F": 1.12555, "Dummy_Rate": 0.01234, "Stuck_Rate": 0.025},
            {"BulletMat": "Ti_Bullet", "Damage_F": 1, "Range_F": 1,
             "Recoil_F": 1, "Dummy_Rate": 0, "Stuck_Rate": 0},
            {"BulletMat": "Chro_Bullet", "Damage_F": 1, "Range_F": 1,
             "Recoil_F": 1, "Dummy_Rate": 0, "Stuck_Rate": 0},
            {"BulletMat": "Tung_Bullet", "Damage_F": 1, "Range_F": 1,
             "Recoil_F": 1, "Dummy_Rate": 0, "Stuck_Rate": 0},
            {"BulletMat": "Extra_Bullet", "Damage_F": 1, "Range_F": 1,
             "Recoil_F": 1, "Dummy_Rate": 0, "Stuck_Rate": 0},
        ]})
        text = {**GAME_TEXT, "_ShootRange_Title": "Range: ",
                "_Recoil_Title": "Recoil: ", "_DummyRound_Title": "Dud chance: "}
        result = presentation.card(self.registry, "combat-rule", ammo, text)
        self.assertEqual(result["stats"][0]["display"], [
            {"material": "Copper", "effects": []},
            {"material": "Steel", "effects": [
                {"label": "Damage", "value": "-12.66%"},
                {"label": "Range", "value": "-20%"},
                {"label": "Recoil", "value": "+12.56%"},
                {"label": "Dud chance", "value": "1.23%"},
                {"label": "Jam rate", "value": "2.5%"},
            ]},
            {"material": "Titanium", "effects": []},
            {"material": "Chrome", "effects": []},
            {"material": "Tungsten", "effects": []},
            {"material": "Material 6", "effects": []},
        ])
        self.assertEqual(result["missing_game_text"], ["_Jam_Title"])
        self.assertNotIn("pending", result)

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

    def test_m1891_recipe_ingredients(self):
        # M1891 in build 25548639; amounts and links from its extracted record.
        ingredients = [
            ("f739d2433cb36ed4ab87c9ba69a7a193", 1, "e-77bb72f728767343e6357ca500db2067", "Rifle Parts"),
            ("7cdd1222de58be149815c0d6647bb151", 8, "e-9d402ed7dc3d50909f7145b32019b7cf", "Iron Ingot"),
            ("0ddbabcee7601a149be867215cf5c2f7", 6, "e-df8e84f3d486ad265038daac0b34d9bf", "Wood"),
            ("d4ba8c34406374e478452b2a2e2bdc49", 12, "e-b6db28444d6529e0fe27b9edc9ed4e71", "Waste plastic"),
            ("e0233852a8ff00642ba77bfb8f46203a", 10, "e-9b5858d6176076264aa4e1ceae8ca514", "Tape"),
            ("d2f5eb8d492179647a448f98ff62adf8", 8, "e-69100e9633eeac8d54ad9ac303f6d0a5", "Spring"),
        ]
        recipe = record("recipe", {"craftNum": 1, "craftSeconds": 20.0,
                                   "matsData": [{"matIcon": icon, "matNeedCount": count}
                                                for icon, count, _, _ in ingredients]},
                        [{"predicate": "consumes-item-asset", "field": f"/matsData/{index}/matIcon",
                          "targets": [target]}
                         for index, (_, _, target, _) in enumerate(ingredients)])
        recipe["relationships"].reverse()  # The facts, not relationship order, set display order.
        links = {target: {"name": name, "topic": "items-equipment"}
                 for _, _, target, name in ingredients}
        result = presentation.card(self.registry, "recipe", recipe, GAME_TEXT, links)
        self.assertEqual(result["stats"][2]["display"], [
            {"name": name, "count": count, "target": target}
            for _, count, target, name in ingredients
        ])
        self.assertNotIn("pending", result)

        # A relationship without a linked name cannot provide a usable target.
        links.pop(ingredients[3][2])
        gap = presentation.card(self.registry, "recipe", recipe, GAME_TEXT, links)["stats"][2]["display"]
        self.assertEqual(gap[3], {"name": None, "count": 12, "target": None, "gap": True})
        self.assertEqual(gap[:3], result["stats"][2]["display"][:3])
        self.assertEqual(gap[4:], result["stats"][2]["display"][4:])

    def test_missing_ingredient_target_and_technical_kind(self):
        recipe = record("recipe", {"craftNum": 2, "craftSeconds": 20,
                                   "matsData": [{"matNeedCount": 1}]})
        result = presentation.card(self.registry, "recipe", recipe, GAME_TEXT)
        self.assertNotIn("pending", result)
        self.assertEqual(result["stats"][1]["display"], "20 s")
        self.assertEqual(result["stats"][2]["display"], [
            {"name": None, "count": 1, "target": None, "gap": True}])
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
