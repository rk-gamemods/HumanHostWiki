"""Player names use snapshot joins and resolve same-kind collisions stably."""

import copy
import random
from pathlib import Path
import unittest

from wikibuild.names import player_names
from wikibuild.presentation import load


REGISTRY = load(Path(__file__).resolve().parents[1] / "presentation" / "fields.json")


def row(key, kind, name, *, topic=None, facts=None, links=(), source=None, component=None,
        evidence=()):
    return {"entity_key": key,
            "semantic": {"kind": kind, "topic": topic or kind, "name": name,
                         "facts": facts or {}, "relationships": list(links)},
            "provenance": {"source_id": source or key, "component": component,
                           "evidence": [{"object": value} for value in evidence]}}


def link(predicate, target, field=""):
    return {"predicate": predicate, "field": field, "targets": [target]}


def fixture():
    rows = [
        row("crafted", "item", "M1891", topic="items", facts={"_Tag": "Gun"}),
        row("loot", "item", "M1891", topic="items", facts={"_Tag": "Gun"}),
        row("block-quarter", "item", "Obsidian", topic="items", facts={"_Tag": "BuildMat"},
            evidence=["tooltip-quarter"]),
        row("block-half", "item", "Obsidian", topic="items", facts={"_Tag": "BuildMat"},
            evidence=["tooltip-half"]),
        row("tooltip-quarter-row", "configuration", "7_5_Block_1.4_Obsidian_Tooltip",
            source="tooltip-quarter", component={"assembly": "Language", "class": "Tooltip_Text"},
            facts={"_ItemName": "Obsidian"}),
        row("tooltip-half-row", "configuration", "7_5_Block_1.2_Obsidian_Tooltip",
            source="tooltip-half", component={"assembly": "Language", "class": "Tooltip_Text"},
            facts={"_ItemName": "Obsidian"}),
        row("helmet-500", "item", "Military Helmet", topic="items", facts={"_BaseMaxDurability": 500}),
        row("helmet-600", "item", "Military Helmet", topic="items", facts={"_BaseMaxDurability": 600}),
        row("same-a", "item", "Steel Pipe", topic="items", facts={"_BaseMaxDurability": 100}),
        row("same-b", "item", "Steel Pipe", topic="items", facts={"_BaseMaxDurability": 100}),
        row("bench", "workbench", "WB_Campfire"),
        row("furnace", "workbench", "WB_Furnace", links=[link("title", "furnace-title")]),
        row("furnace-title", "configuration", "FurnaceTitle",
            component={"assembly": "Language", "class": "Language_Text"},
            facts={"text": "Smelting Furnace"}),
        row("biome", "biome", "Desert_Rocky"),
        row("creature", "creature", "Z_Man_15"),
        row("ore", "item", "Iron Ore", topic="items"),
        row("scrap", "item", "Scrap Iron", topic="items"),
        row("ingot", "item", "Iron Ingot", topic="items"),
        row("recipe-ore", "recipe", "Recipe_Internal", topic="crafting",
            links=[link("consumes-item-asset", "ore", "/matsData/0/matIcon")]),
        row("recipe-scrap", "recipe", "Recipe_Internal", topic="crafting",
            links=[link("consumes-item-asset", "scrap", "/matsData/0/matIcon")]),
        row("body", "loot-source", "DeadBodyLoot",
            source="bundles/zb_baseterrain_assets_all.bundle::serialized-0#1"),
        row("container", "loot-source", "Wooden_Crate", evidence=["crate-tip"]),
        row("crate-tip-row", "configuration", "Wooden_Crate_Tooltip", source="crate-tip",
            component={"assembly": "Language", "class": "Tooltip_Text"},
            facts={"_ItemName": "Wooden crate"}),
        row("numeric-table", "loot-table", "0", links=[]),
        row("axe", "item", "Crude Axe", topic="items", links=[link("uses-combat", "axe-combat")]),
        row("axe-combat", "combat-rule", "Axe_Combo_2"),
        row("attack", "combat-rule", "Z_Attack_01"),
        row("hit-set", "combat-rule", "Knife_Iron_Hit_Set"),
        row("ammo", "combat-rule", "Tool_Interact_Mgr"),
    ]
    next(r for r in rows if r["entity_key"] == "container")["semantic"]["relationships"].append(
        link("uses-loot-table", "numeric-table"))
    graph = {"items": {
        "crafted": {"sources": [{"type": "crafted"}]},
        "loot": {"sources": [{"type": "looted"}]},
        "block-quarter": {"sources": [{"type": "crafted"}]},
        "block-half": {"sources": [{"type": "crafted"}]},
    }, "recipes": {
        "recipe-ore": {"output": "ingot", "bench": "furnace"},
        "recipe-scrap": {"output": "ingot", "bench": "furnace"},
    }}
    return rows, graph


class PlayerNamesTests(unittest.TestCase):
    def test_rules_and_sources(self):
        rows, graph = fixture()
        names = player_names(rows, REGISTRY, {}, graph)
        expected = {
            "crafted": ("M1891 (crafted)", "acquisition"),
            "loot": ("M1891 (loot)", "acquisition"),
            "block-quarter": ("Obsidian (Block 1/4)", "building-shape"),
            "block-half": ("Obsidian (Block 1/2)", "building-shape"),
            "helmet-500": ("Military Helmet (Durability 500)", "distinguishing-stat"),
            "helmet-600": ("Military Helmet (Durability 600)", "distinguishing-stat"),
            "same-a": ("Steel Pipe (variant 1)", "ordinal"),
            "same-b": ("Steel Pipe (variant 2)", "ordinal"),
            "bench": ("Campfire", "workbench-fallback"),
            "furnace": ("Smelting Furnace", "workbench-title"),
            "biome": ("Rocky Desert", "biome"),
            "creature": ("Male zombie (type 15)", "creature"),
            "recipe-ore": ("Iron Ingot from Iron Ore", "recipe-ingredient"),
            "recipe-scrap": ("Iron Ingot from Scrap Iron", "recipe-ingredient"),
            "body": ("Dead body", "loot-family"),
            "container": ("Wooden crate", "loot-source"),
            "numeric-table": ("Wooden crate", "loot-table-container"),
            "axe-combat": ("Crude Axe combat", "combat-user"),
            "attack": ("Zombie attack 1", "combat-pattern"),
            "hit-set": ("Knife iron", "combat-humanize"),
            "ammo": ("Handmade ammo", "combat-handmade-ammo"),
        }
        for key, pair in expected.items():
            with self.subTest(key=key):
                self.assertEqual((names[key]["name"], names[key]["rule"]), pair)
        self.assertEqual(names["ore"], {"name": "Iron Ore", "source": "game", "rule": None})
        self.assertEqual(names["bench"]["source"], "wiki")
        self.assertEqual(names["furnace"]["source"], "game")
        self.assertEqual(names["body"]["family"], "dead bodies")
        self.assertNotIn("family", names["container"])
        self.assertEqual(set(names), {row["entity_key"] for row in rows})

    def test_shuffle_and_no_mutation(self):
        rows, graph = fixture()
        before = copy.deepcopy(rows)
        expected = player_names(rows, REGISTRY, {}, graph)
        self.assertEqual(rows, before)
        for seed in range(5):
            shuffled = copy.deepcopy(rows)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(player_names(shuffled, REGISTRY, {}, graph), expected)

    def test_partial_stat_and_structured_display_fall_back_to_ordinal(self):
        rows = [row("a", "item", "Helmet", facts={"_BaseMaxDurability": 100}),
                row("b", "item", "Helmet", facts={"_BaseMaxDurability": 100}),
                row("c", "item", "Helmet", facts={"_BaseMaxDurability": 200}),
                row("x", "combat-rule", "Tool_Interact_Mgr"),
                row("y", "combat-rule", "Tool_Interact_Mgr",
                    facts={"_HandCraftBullet": [{"BulletMat": "Cop_Bullet", "Damage_F": 0.7,
                                                  "Range_F": 1, "Recoil_F": 1,
                                                  "Dummy_Rate": 0, "Stuck_Rate": 0}]})]
        names = player_names(rows, REGISTRY, {}, {"items": {}, "recipes": {}})
        self.assertEqual(names["c"]["name"], "Helmet (Durability 200)")
        self.assertEqual([names[key]["name"] for key in ("a", "b")],
                         ["Helmet (variant 1)", "Helmet (variant 2)"])
        self.assertEqual([names[key]["name"] for key in ("x", "y")],
                         ["Handmade ammo (variant 1)", "Handmade ammo (variant 2)"])

    def test_biome_registry_uses_record_names(self):
        expected = {"Mountain": "Mountain Forest", "Forest": "Mossy Forest",
                    "Warzone": "War Zone", "Tropical": "Tropical Jungle",
                    "Swamp": "Tropical Swamp", "Base": "Spawn area"}
        rows = [row(key, "biome", key) for key in expected]
        names = player_names(rows, REGISTRY, {}, {})
        self.assertEqual({key: value["name"] for key, value in names.items()}, expected)
        self.assertTrue(all(value["source"] == "wiki" for value in names.values()))

    def test_container_families_biomes_ordinals_and_numeric_table(self):
        rows = [row(key, "biome", name) for key, name in
                (("forest", "Forest"), ("desert", "Desert"), ("base", "Base"),
                 ("warzone", "Warzone"), ("winter-forest", "Winter_Forest"),
                 ("winter-town", "Winter_Town"))]
        bundles = {"crate-a": "shc_crates_desert", "crate-b": "shc_crates_desert",
                   "car": "cars_desert", "body": "zb_baseterrain",
                   "airport": "props_ab_airport", "factory": "props_factoryzone",
                   "diner": "props_dinner", "house": "props_countryhouse"}
        rows += [row(key, "loot-source", "DeadBodyLoot" if key == "body" else "0",
                     source=f"bundles/{bundle}_assets_all.bundle::serialized-0#{key}")
                 for key, bundle in bundles.items()]
        rows += [row("merchant", "loot-source", "TravelingMechanic", source="level1#4"),
                 row("misleading", "loot-source", "Hunter",
                     source="bundles/other_assets_all.bundle::serialized-0#cars_desert"),
                 row("table", "loot-table", "0"),
                 row("item", "item", "Crate", source="bundles/shc_crates_desert_assets_all.bundle::0#1")]
        next(r for r in rows if r["entity_key"] == "crate-a")["semantic"]["relationships"] = [
            link("uses-loot-table", "table")]
        # The graph, rather than another bundle-name inference here, owns geography.
        edges = [("crate-a", "forest"), ("crate-a", "forest"), ("crate-b", "forest"),
                 ("car", "desert"), ("body", "base"), ("factory", "warzone"),
                 ("house", "winter-town"), ("house", "winter-forest")]
        graph = {"items": {"item": {"sources": [
            {"type": "looted", "via": container, "biome": biome} for container, biome in edges] + [
            {"type": "merchant", "via": "airport", "biome": "desert"}]}}}
        before = copy.deepcopy((rows, graph, REGISTRY))
        names = player_names(rows, REGISTRY, {}, graph)
        expected = {
            "crate-a": ("Crate, Mossy Forest (variant 1)", "crates"),
            "crate-b": ("Crate, Mossy Forest (variant 2)", "crates"),
            "car": ("Car, Desert", "cars"), "body": ("Dead body, Spawn area", "dead bodies"),
            "airport": ("Abandoned airport container", "the abandoned airport"),
            "factory": ("Factory zone container, War Zone", "the factory zone"),
            "diner": ("Diner container", "the diner"),
            "house": ("Country house container, Winter Forest and Winter Town", "country houses"),
        }
        for key, (name, family) in expected.items():
            with self.subTest(key=key):
                self.assertEqual(names[key]["name"], name)
                self.assertEqual(names[key]["family"], family)
                self.assertEqual(names[key]["source"], "wiki")
        self.assertEqual(names["crate-a"]["rule"], "ordinal")
        self.assertEqual(names["table"]["name"], names["crate-a"]["name"])
        self.assertEqual(names["merchant"]["name"], "Traveling mechanic")
        for key in ("merchant", "misleading", "item", "table"):
            self.assertNotIn("family", names[key])
        self.assertEqual((rows, graph, REGISTRY), before)
        for seed in range(4):
            random.Random(seed).shuffle(rows)
            random.Random(seed).shuffle(graph["items"]["item"]["sources"])
            self.assertEqual(player_names(rows, REGISTRY, {}, graph), names)

    def test_ordered_family_regexes_and_registry_templates(self):
        registry = copy.deepcopy(REGISTRY)
        spec = registry["names"]["sources"]["loot-source"]
        spec["families"].insert(0, {"match": "_assets_all$", "family": "supplies", "singular": "Supply"})
        spec["record_name"] = "{biome}: {singular}"
        spec["no_biome_name"] = "Unplaced {singular}"
        rows = [row("forest", "biome", "Forest"),
                row("car", "loot-source", "0", source="bundles/cars_desert_assets_all.bundle::0#1"),
                row("crate", "loot-source", "0", source="bundles/shc_crates_assets_all.bundle::0#2")]
        graph = {"items": {"item": {"sources": [{"type": "looted", "via": "car", "biome": "forest"}]}}}
        names = player_names(rows, registry, {}, graph)
        self.assertEqual(names["car"], {"name": "Mossy Forest: Supply", "source": "wiki",
                                       "rule": "loot-family", "family": "supplies"})
        self.assertEqual(names["crate"]["name"], "Unplaced Supply")


if __name__ == "__main__":
    unittest.main()
