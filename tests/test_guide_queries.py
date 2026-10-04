"""Guide contracts using real graph, names, cards, joins and renderer."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from tests._support import fixture_dir

from tools import render_guides
from wikibuild import guide_queries as queries
from wikibuild.game_text import labels
from wikibuild.guides import GuideError, load_spec, render, render_markdown, text_runs
from wikibuild.lint import jargon
from wikibuild.presentation import load
from wikibuild import reader


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = load(ROOT / "presentation" / "fields.json")
SNAPSHOT = {"game_version": "0.8.316", "build_id": "25587699"}
GUIDES = ("getting-started", "progression-by-biome", "choosing-a-weapon", "crafting-stations")


def key(name):
    return "e-" + hashlib.md5(name.encode("utf-8")).hexdigest()


def link(predicate, target, field=""):
    return {"predicate": predicate, "targets": [key(target)], "field": field}


def row(identity, kind, name, facts=None, links=(), **provenance):
    return {"entity_key": key(identity), "semantic": {"kind": kind, "topic": kind,
            "name": name, "facts": facts or {}, "relationships": list(links)}, "provenance": provenance}


def recipe(identity, output, ingredients, bench="hand"):
    return row(identity, "recipe", identity, {"craftNum": 1,
               "matsData": [{"matNeedCount": count} for _, count in ingredients]},
               [link("produces-item", output), link("defined-by", bench),
                *[link("consumes-item-asset", item, f"/matsData/{index}/matIcon")
                  for index, (item, _) in enumerate(ingredients)]])


def mining(identity, amounts):
    return row(identity, "resource-distribution", "Ore deposits", {"_BlockInfo": [
        {"CollectableItems": [{"RandomRate": chance} for _, chance in amounts]}]},
        [link("mineable-item", item, f"/_BlockInfo/0/CollectableItems/{index}")
         for index, (item, _) in enumerate(amounts)])


def harvest_source(identity, name, item, **provenance):
    return row(identity, "building-piece", name,
               {"_Collectable_Info": {"_Items": [{"_RandomRate": 1}]}},
               [link("collectible-item", item, "/_Collectable_Info/_Items/0/_IconRef")], **provenance)


def fixture():
    """Two main rings, a separate Base patch, and an ingredient/bench chain."""
    items = [
        ("wood", "Wood", "BuildMat"), ("ore", "Iron Ore", "BuildMat"),
        ("stone", "Stone", "BuildMat"), ("fiber", "Plant Fiber", ""),
        ("part", "Spare Part", "废旧材料"), ("stock", "Flux", "废旧材料"),
        ("plank", "Planks", "BuildMat"), ("station1", "Workbench", "BuildMat"),
        ("station2", "Forge", "BuildMat"), ("axe", "Stone Axe", "MeleeWeapon"),
        ("gun", "Rifle", "Gun"), ("ammo", "Cartridges", "9x19"),
        ("saw", "Saw", "工具"), ("torch", "Torch", "工具"),
    ]
    rows = [row(identity, "item", name, {"_Tag": tag}) for identity, name, tag in items]
    rows += [
        row("forest", "biome", "Forest"), row("desert", "biome", "Desert"), row("base", "biome", "Base"),
        row("world", "world-rule", "Terrain", {"BigTerraWidth": 1000, "_BiomesWidthNum": 2,
            "_BiomesLayers": [{}, {}]}, [link("biome-terrain-prefab", "top0", "/_BiomesLayers/0/terrainTops/0"),
            link("biome-terrain-prefab", "top1", "/_BiomesLayers/1/terrainTops/0"),
            link("base-terrain-prefab", "base-top", "/_BaseBigTerrains/baseBigTerraTops/0")]),
        row("top0", "resource-distribution", "Forest ground", links=[link("biome", "forest"),
            link("terrain-block-set", "stone-blocks"), link("vegetation", "tree"), link("vegetation", "grass")]),
        row("top1", "resource-distribution", "Desert ground", links=[link("biome", "desert"), link("terrain-block-set", "ore-blocks")]),
        row("base-top", "resource-distribution", "Spawn ground", links=[link("biome", "base"), link("terrain-block-set", "base-blocks")]),
        mining("stone-blocks", [("stone", 0.2)]), mining("ore-blocks", [("ore", 0.2)]), mining("base-blocks", [("ore", 0.01)]),
        row("tree", "building-piece", "Oak", {"_Collectable_Info": {"_Items": [{"_RandomRate": 1}]}},
            [link("collectible-item", "wood", "/_Collectable_Info/_Items/0/_IconRef")]),
        row("grass", "asset", "Grass"),
        row("tools", "combat-rule", "Tool_Interact_Mgr", links=[link("gathered-item", "fiber", "/_PlantFiberIconRef")]),
        row("crate", "loot-source", "Crate", links=[link("uses-loot-table", "table")],
            source_id="bundles/shc_crates_forest_assets_all.bundle::serialized#1"),
        row("table", "loot-table", "Parts", {"rates": [{"_spawnLootTag": "Parts", "_spawnRateRange": 1}]}),
        row("tag", "loot-tag", "Parts", {"tag": "Parts"}, [link("eligible-item", "part")]),
        row("merchant", "loot-table", "Merchant", {"BiomeName": "Forest"}, [link("merchant-stock-item", "stock")]),
        row("merchant-manager", "loot-source", "Merchant_Mgr",
            {"manager_object": "Merchant_Mgr", "manager_active": True}),
        row("hand", "workbench", "Hand crafting", {"_workbenchType": 0}),
        row("bench1", "workbench", "Workbench", {"_workbenchType": 1}),
        row("bench2", "workbench", "Forge", {"_workbenchType": 2}),
        row("prefab1", "asset", "Workbench model", links=[link("cataloged-component", "bench1")]),
        row("prefab2", "asset", "Forge model", links=[link("cataloged-component", "bench2")]),
        recipe("build-first", "station1", [("wood", 2)]),
        recipe("planks-wood", "plank", [("wood", 2)], "bench1"),
        recipe("planks-part", "plank", [("part", 1)], "bench1"),
        recipe("build-second", "station2", [("plank", 3)]),
        recipe("axe-recipe", "axe", [("wood", 2), ("fiber", 1), ("stone", 1)]),
        recipe("gun-recipe", "gun", [("plank", 1), ("part", 2), ("ore", 1)], "bench2"),
        recipe("ammo-recipe", "ammo", [("ore", 1)], "bench2"),
        recipe("saw-recipe", "saw", [("plank", 1)], "bench2"),
        recipe("torch-recipe", "torch", [("stock", 1)]),
        row("salvage", "processing-rule", "Salvage", links=[link("yields-item-asset", "part")]),
        row("gun-model", "asset", "Rifle model", links=[link("cataloged-component", "gun-combat")]),
        row("gun-combat", "combat-rule", "Rifle combat", {"_GunType": 2, "_AmmoType": 0, "_Damage": 999},
            [link("coded-value", "ammo-type", "/_AmmoType")]),
        row("ammo-type", "configuration", "Cartridge type", links=[link("ammunition-item", "ammo")]),
    ]
    by = {r["entity_key"]: r["semantic"] for r in rows}
    by[key("station1")]["relationships"].append(link("model", "prefab1"))
    by[key("station2")]["relationships"].append(link("model", "prefab2"))
    by[key("axe")]["facts"].update(_baseDamage=12.345, _BaseMaxDurability=200)
    by[key("gun")]["facts"].update(_baseDamage=40, _fireRate="240", _ammoType="9x19", _maxMagCount=5)
    by[key("gun")]["relationships"].extend([link("disassembly", "salvage"), link("model", "gun-model")])
    by[key("gun-combat")]["fact_labels"] = {"/_GunType": "Bolt Rifle", "/_AmmoType": "9x19"}
    return rows


def weapon_fixture():
    rows = fixture() + [
        row("bow", "item", "Wooden Bow", {"_Tag": "Bow", "_baseDamage": 1.25,
            "_fireRate": "999", "_BaseMaxDurability": 75}, [link("combat-record", "bow-combat")]),
        row("bow-combat", "combat-rule", "Bow combat", {"_ArrowSpeed": 80.4}),
        recipe("bow-recipe", "bow", [("wood", 3)]),
        row("loot-gun", "item", "Rifle", {"_Tag": "Gun", "_baseDamage": 60}, [link("model", "gun-model")]),
    ]
    by = {r["entity_key"]: r["semantic"] for r in rows}
    by[key("axe")]["facts"].update(_baseBladeHitProb=0.025, _baseHitDownProb=0.05)
    by[key("tag")]["relationships"].append(link("eligible-item", "loot-gun"))
    return rows


def context(rows=None):
    rows = fixture() if rows is None else rows
    return queries.build_context(rows, REGISTRY, labels(rows), SNAPSHOT)


def entity(identity, name):
    return {"text": name, "entity": key(identity)}


def query(ctx, name, index=None):
    return queries.QUERIES[name](ctx, {} if index is None else {"index": str(index)})


def words(runs):
    return "".join(run["text"] for run in runs)


def rich(*parts):
    return {"runs": [{"text": part} if isinstance(part, str) else part for part in parts]}


def payloads(ctx):
    result = {}
    for guide in GUIDES:
        document = render(load_spec(ROOT / "guides" / f"{guide}.json"), queries.QUERIES, ctx)
        result[guide + ".json"] = json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")
        result[guide + ".md"] = render_markdown(document, lambda k: "/entry/" + k).encode("utf-8")
    return result


class GuideQueryModuleTests(unittest.TestCase):
    def test_all_guide_query_modules_are_fingerprinted(self):
        folder = ROOT / "wikibuild"
        modules = {"guide_queries.py", *(path.name for path in folder.glob("guide_query_*.py"))}
        self.assertLessEqual(modules, reader.contract().keys())

    def test_family_edits_and_additions_change_renderer_contract(self):
        folder = fixture_dir(self, "guide_fp")
        original = reader.contract()
        for name in original:
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"renderer input\n")
        with patch.object(reader, "__file__", str(folder / "reader.py")):
            baseline = reader.contract()
            self.assertEqual(reader.contract(), baseline)
            for name in original:
                if name == "guide_queries.py" or name.startswith("guide_query_"):
                    with self.subTest(module=name):
                        before = reader.contract()
                        path = folder / name
                        path.write_bytes(path.read_bytes() + b"# changed query\n")
                        after = reader.contract()
                        self.assertEqual({key for key in before if before[key] != after[key]}, {name})
            future = folder / "guide_query_future.py"
            future.write_bytes(b"# additional query family\n")
            self.assertIn(future.name, reader.contract())

    def test_query_registry_preserves_family_and_entry_order(self):
        self.assertEqual(list(queries.QUERIES), [
            "start.first_biome", "start.materials", "start.gathering_intro",
            "start.hand_intro", "start.benches_intro", "start.hand_recipes", "start.benches",
            "start.tools_and_weapons", "world.rings", "world.near_spawn", "world.zombie_scaling",
            "world.loot_quality_scaling", "rings", "ring.span", "ring.new_materials",
            "ring.easier_gathering", "ring.new_recipes", "ring.new_benches", "ring.exclusive_loot",
            "ring.merchant_summary", "weapons.stat_labels", "weapons.melee", "weapons.guns",
            "weapons.bows", "weapons.ammo_sources", "weapons.variants", "benches.overview",
            "benches", "bench.summary", "bench.cost", "bench.recipes",
        ])


class GuideQueryTests(unittest.TestCase):
    def setUp(self):
        self.ctx = context()

    def test_distance_and_percent_formatting(self):
        distances = {0: "0 m", 12: "12 m", 999: "999 m", 1000: "1 km", 2000: "2 km",
                     2048: "2 km", 2060: "2.1 km", 18444: "18.4 km", 18550: "18.6 km"}
        for value, expected in distances.items():
            self.assertEqual(queries.format_distance(value), expected)
        for value, expected in [(0, "0%"), (0.2, "20%"), (0.05, "5%"), (0.01, "1%"),
                                (0.025, "2.5%"), (0.01235, "1.24%"), (0.00005, "0.01%")]:
            self.assertEqual(queries.format_percent(value), expected)

    def test_public_helpers_links_and_wording(self):
        expected = {"ore": "mined in Desert (20% of dig hits)", "fiber": "cut from grass",
                    "wood": "gathered from trees", "plank": "crafted at the Workbench",
                    "axe": "crafted by hand", "stock": "sold by merchants in Mossy Forest",
                    "part": "found in crates in Mossy Forest; salvaged from Rifle"}
        for identity, wording in expected.items():
            self.assertEqual(words(queries.how_runs(self.ctx, key(identity))), wording)
        self.assertEqual(queries.how_runs(self.ctx, key("ore")), [
            {"text": "mined in "}, entity("desert", "Desert"), {"text": " (20% of dig hits)"}])
        self.assertEqual(queries.how_runs(self.ctx, key("ore"), ring=0), queries.how_runs(self.ctx, key("ore")))
        self.assertEqual(queries.how_runs(self.ctx, key("ore"), limit=0), [])
        self.assertEqual(words(queries.how_runs(self.ctx, key("part"), limit=1)), "found in crates in Mossy Forest")
        self.assertEqual(queries.ring_label(self.ctx, 0), "Biome 1 (Mossy Forest)")
        self.assertEqual(self.ctx["names"][key("base")]["name"], "Spawn area")
        self.assertEqual(queries.used_in(self.ctx, key("wood")), [entity("planks-wood", "Planks from Wood"),
                         entity("axe-recipe", "Stone Axe"), entity("build-first", "Workbench")])
        self.assertEqual([queries.method(self.ctx, key(k)) for k in ("stone", "fiber", "part", "stock")],
                         ["Mining", "Gathering", "Scavenging", "Buying"])
        with self.assertRaises(ValueError):
            queries.method(self.ctx, key("axe"))

    def test_start_golden_rows(self):
        self.assertEqual(query(self.ctx, "start.first_biome"), {"first_biome": entity("forest", "Mossy Forest")})
        self.assertEqual(query(self.ctx, "start.materials"), [
            {"item": entity("stone", "Stone"), "method": "Mining", "how": rich("mined in ", entity("forest", "Mossy Forest"), " (20% of dig hits)")},
            {"item": entity("wood", "Wood"), "method": "Gathering", "how": rich("gathered from ", "trees")},
            {"item": entity("fiber", "Plant Fiber"), "method": "Gathering", "how": rich("cut from grass")},
            {"item": entity("part", "Spare Part"), "method": "Scavenging", "how": rich("found in ", "crates", " in ", entity("forest", "Mossy Forest"))},
            {"item": entity("stock", "Flux"), "method": "Buying", "how": rich("sold by merchants in ", entity("forest", "Mossy Forest"))},
        ])
        self.assertEqual(query(self.ctx, "start.hand_recipes"), [
            {"output": entity("axe", "Stone Axe"), "ingredients": [entity("fiber", "1 × Plant Fiber"), entity("stone", "1 × Stone"), entity("wood", "2 × Wood")], "category": "Melee weapon"},
            {"output": entity("torch", "Torch"), "ingredients": [entity("stock", "1 × Flux")], "category": "Tool"},
        ])
        self.assertEqual(query(self.ctx, "start.benches"), [
            {"bench": entity("bench1", "Workbench"), "ingredients": [entity("wood", "2 × Wood")], "unlock_count": "2"},
            {"bench": entity("bench2", "Forge"), "ingredients": [entity("plank", "3 × Planks")], "unlock_count": "3"},
        ])
        self.assertEqual(query(self.ctx, "start.tools_and_weapons"), [
            {"Item": entity("axe", "Stone Axe"), "Damage": "12.35", "Durability": "200", "Made at": "By hand",
             "Ingredients": [entity("fiber", "1 × Plant Fiber"), entity("stone", "1 × Stone"), entity("wood", "2 × Wood")]},
            {"Item": entity("saw", "Saw"), "Damage": "", "Durability": "", "Made at": entity("bench2", "Forge"),
             "Ingredients": [entity("plank", "1 × Planks")]},
        ])
        self.assertEqual(query(self.ctx, "start.hand_intro"), {})
        self.assertEqual(query(self.ctx, "start.benches_intro"), {})
        empty = context([])
        self.assertIsNone(query(empty, "start.hand_intro"))
        self.assertIsNone(query(empty, "start.benches_intro"))

    def test_world_and_ring_golden_rows(self):
        self.assertEqual(query(self.ctx, "world.rings"), {"ring_width": "2 km", "ring_count": "2"})
        self.assertEqual(query(self.ctx, "world.near_spawn"), {"near_spawn_chance": "1%"})
        self.assertIsNone(query(self.ctx, "world.zombie_scaling"))
        self.assertIsNone(query(self.ctx, "world.loot_quality_scaling"))
        rings = [{"index": "0", "number": "1", "biome": entity("forest", "Mossy Forest"), "start_distance": "12 m", "end_distance": "2 km"},
                 {"index": "1", "number": "2", "biome": entity("desert", "Desert"), "start_distance": "2 km", "end_distance": "4 km"}]
        self.assertEqual(query(self.ctx, "rings"), rings)
        for scope in rings:
            self.assertEqual(queries.QUERIES["ring.span"](self.ctx, scope), scope)
        self.assertEqual(query(self.ctx, "ring.new_materials", 0), query(self.ctx, "start.materials"))
        self.assertEqual(query(self.ctx, "ring.new_materials", 1), [{"item": entity("ore", "Iron Ore"),
                         "method": "Mining", "how": rich("mined in ", entity("desert", "Desert"), " (20% of dig hits)")}])
        self.assertEqual(query(self.ctx, "ring.new_recipes", 0), [
            {"output": entity("planks-part", "Planks from Spare Part"), "made": rich("at the ", entity("bench1", "Workbench")), "category": "Building material"},
            {"output": entity("planks-wood", "Planks from Wood"), "made": rich("at the ", entity("bench1", "Workbench")), "category": "Building material"},
            {"output": entity("axe-recipe", "Stone Axe"), "made": rich("by hand"), "category": "Melee weapon"},
            {"output": entity("saw-recipe", "Saw"), "made": rich("at the ", entity("bench2", "Forge")), "category": "Tool"},
            {"output": entity("torch-recipe", "Torch"), "made": rich("by hand"), "category": "Tool"},
        ])
        self.assertEqual(query(self.ctx, "ring.new_recipes", 1), [
            {"output": entity("ammo-recipe", "Cartridges"), "made": rich("at the ", entity("bench2", "Forge")), "category": "Ammo"},
            {"output": entity("gun-recipe", "Rifle"), "made": rich("at the ", entity("bench2", "Forge")), "category": "Gun"}])
        self.assertEqual(query(self.ctx, "ring.new_benches", 0), [{"bench": entity("bench1", "Workbench")}, {"bench": entity("bench2", "Forge")}])
        self.assertEqual(query(self.ctx, "ring.new_benches", 1), [])
        self.assertEqual(query(self.ctx, "ring.exclusive_loot", 0), [{"item": entity("part", "Spare Part"),
                         "how": rich("found in ", "crates", " in ", entity("forest", "Mossy Forest"))}])
        self.assertEqual(query(self.ctx, "ring.exclusive_loot", 1), [])
        self.assertEqual(query(self.ctx, "ring.merchant_summary", 0),
                         {"merchant_count": "1", "merchant_plural": "kind of item"})
        self.assertIsNone(query(self.ctx, "ring.merchant_summary", 1))

    def test_inactive_and_missing_manager_hide_merchant_acquisition(self):
        rows = fixture()
        manager = next(row for row in rows if row["entity_key"] == key("merchant-manager"))
        manager["semantic"]["facts"]["manager_active"] = False
        inactive = context(rows)
        self.assertEqual(inactive["features"]["merchants"]["status"], "inactive")
        self.assertEqual(queries.how_runs(inactive, key("stock")), [])
        self.assertNotIn(key("stock"), [entry["item"]["entity"] for entry in query(inactive, "start.materials")])
        self.assertNotIn(key("stock"), [entry["item"]["entity"] for entry in query(inactive, "ring.new_materials", 0)])
        self.assertIsNone(query(inactive, "ring.merchant_summary", 0))
        self.assertEqual(inactive["unreleased"][key("stock")], "merchants")
        self.assertEqual(inactive["unreleased"][key("merchant")], "merchants")
        missing = context([row for row in rows if row is not manager])
        self.assertEqual(missing["features"]["merchants"]["status"], "manager-object-missing")
        self.assertIsNone(query(missing, "ring.merchant_summary", 0))
        manager["semantic"]["facts"]["manager_active"] = True
        active = context(rows)
        self.assertIn("sold by merchants", words(queries.how_runs(active, key("stock"))))
        guide = render(load_spec(ROOT / "guides/progression-by-biome.json"), queries.QUERIES, active)
        self.assertIn("Merchants here sell 1 kind of item.", render_markdown(guide, lambda value: "/entry/" + value))
        next_item = row("second-stock", "item", "Second stock", {"_Tag": "废旧材料"})
        rows.append(next_item)
        stock_table = next(row for row in rows if row["entity_key"] == key("merchant"))
        stock_table["semantic"]["relationships"].append(link("merchant-stock-item", "second-stock"))
        plural = context(rows)
        self.assertEqual(query(plural, "ring.merchant_summary", 0),
                         {"merchant_count": "2", "merchant_plural": "kinds of items"})
        guide = render(load_spec(ROOT / "guides/progression-by-biome.json"), queries.QUERIES, plural)
        self.assertIn("Merchants here sell 2 kinds of items.", render_markdown(guide, lambda value: "/entry/" + value))

    def test_easier_gathering_uses_first_located_ring_and_excludes_new_materials(self):
        rows = fixture() + [row("mountain", "biome", "Mountain"),
                            row("top2", "resource-distribution", "Mountain ground", links=[link("biome", "mountain")]),
                            row("rebar", "item", "Rebar", {"_Tag": "BuildMat"}),
                            row("cement", "item", "Cement", {"_Tag": "BuildMat"}),
                            recipe("make-rebar", "rebar", [("wood", 1)]),
                            recipe("make-cement", "cement", [("wood", 1)])]
        world = next(row for row in rows if row["entity_key"] == key("world"))["semantic"]
        world["facts"]["_BiomesLayers"].append({})
        world["relationships"].append(link("biome-terrain-prefab", "top2", "/_BiomesLayers/2/terrainTops/0"))
        for identity, name, item, bundle in [
            ("rebar-desert", "ConBrick Debris 01", "rebar", "terrain_desert_assets_all"),
            ("rebar-mountain", "Cactus 02", "rebar", "terrain_mountain_assets_all"),
            ("rebar-collapse", "Rock 01", "rebar", "ground_debris_assets_all"),
            ("cement-desert", "ConBrick Debris 03", "cement", "terrain_desert_assets_all"),
            ("ore-desert", "ConBrick Debris 04", "ore", "terrain_desert_assets_all"),
            ("wood-desert", "ConBrick Debris 05", "wood", "terrain_desert_assets_all"),
        ]:
            rows.append(harvest_source(identity, name, item,
                                       source_id=f"bundles/{bundle}.bundle::0#1"))
        ctx = context(rows)
        self.assertEqual(query(ctx, "ring.easier_gathering", 0), [])
        self.assertEqual(query(ctx, "ring.easier_gathering", 1), [
            {"item": entity("cement", "Cement"), "how": rich("gathered from ", "rubble")},
            {"item": entity("rebar", "Rebar"), "how": rich("gathered from ", "rubble")},
        ])
        self.assertEqual(query(ctx, "ring.easier_gathering", 2), [])
        markdown = render_markdown(render(load_spec(ROOT / "guides/progression-by-biome.json"),
                                          queries.QUERIES, ctx), lambda k: "/entry/" + k)
        self.assertIn("Easier to get here", markdown)
        self.assertIn(f"[Rebar](/entry/{key('rebar')}): gathered from rubble", markdown)

    def test_all_checkpoint_specs_render_without_jargon(self):
        ctx = context(weapon_fixture())
        for guide in GUIDES:
            spec = load_spec(ROOT / "guides" / f"{guide}.json")
            self.assertLessEqual(render_guides.query_names(spec), queries.QUERIES.keys())
            document = render(spec, queries.QUERIES, ctx)
            self.assertEqual(len(document["sections"]), {"getting-started": 5, "progression-by-biome": 4,
                             "choosing-a-weapon": 6, "crafting-stations": 4}[guide])
            self.assertEqual([(path, hit) for path, text in text_runs(document) for hit in jargon(text)], [])
            self.assertIn("Steam build 25587699", render_markdown(document, lambda k: "/entry/" + k))

    def test_shuffled_inputs_repeat_bytes_and_do_not_mutate(self):
        rows = weapon_fixture()
        before = copy.deepcopy(rows)
        expected = payloads(queries.build_context(iter(rows), REGISTRY, labels(rows), SNAPSHOT))
        self.assertEqual(rows, before)
        for seed in (1, 7):
            random.Random(seed).shuffle(rows)
            for record in rows:
                random.Random(seed).shuffle(record["semantic"]["relationships"])
            self.assertEqual(payloads(context(rows)), expected)
        ctx = context(rows)
        before_context = copy.deepcopy(ctx)
        self.assertEqual(payloads(ctx), payloads(ctx))
        self.assertEqual(ctx, before_context)

    def test_cache_reused_across_query_calls(self):
        with patch.object(queries, "graph", wraps=queries.graph) as graph_spy, \
                patch.object(queries, "player_names", wraps=queries.player_names) as names_spy, \
                patch.object(queries, "card", wraps=queries.card) as card_spy:
            ctx = context(weapon_fixture())
            payloads(ctx)
            payloads(ctx)
        self.assertEqual(graph_spy.call_count, 1)
        self.assertEqual(names_spy.call_count, 1)
        self.assertEqual(card_spy.call_count, len(ctx["graph"]["items"]) + 2)

    def test_crafting_closure_rejects_loot_and_checks_building_bench(self):
        rows = [r for r in fixture() if r["entity_key"] != key("planks-wood")]
        self.assertEqual([r["Item"]["text"] for r in query(context(rows), "start.tools_and_weapons")], ["Stone Axe"])
        # Forge's ingredients are natural, but it must now be built at a bench
        # whose own build cost needs a merchant item.
        rows = [r for r in fixture() if r["entity_key"] != key("build-first")]
        rows += [recipe("build-first", "station1", [("stock", 1)])]
        for record in rows:
            if record["entity_key"] == key("build-second"):
                record["semantic"] = recipe("build-second", "station2", [("wood", 1)], "bench1")["semantic"]
        self.assertEqual([r["Item"]["text"] for r in query(context(rows), "start.tools_and_weapons")], ["Stone Axe"])

    def test_cycles_and_unresolved_recipe_owner_are_not_hand_crafting(self):
        rows = fixture() + [row("cycle", "item", "Cycle tool", {"_Tag": "工具"}),
                            recipe("cycle-recipe", "cycle", [("cycle", 1)]),
                            row("orphan", "item", "Orphan tool", {"_Tag": "工具"}),
                            recipe("orphan-recipe", "orphan", [("wood", 1)], "absent")]
        ctx = context(rows)
        self.assertEqual([r["Item"]["text"] for r in query(ctx, "start.tools_and_weapons")], ["Stone Axe", "Saw"])
        self.assertEqual(queries.how_runs(ctx, key("orphan")), [])
        self.assertNotIn(key("orphan"), {r["output"]["entity"] for r in query(ctx, "start.hand_recipes")})

    def test_main_ring_not_earliest_and_ring_scoped_mining(self):
        rows = fixture() + [mining("early-ore", [("ore", 0.02)])]
        next(r for r in rows if r["entity_key"] == key("top0"))["semantic"]["relationships"].append(link("terrain-block-set", "early-ore"))
        ctx = context(rows)
        self.assertEqual(ctx["graph"]["items"][key("ore")]["earliest_ring"], 0)
        self.assertEqual(ctx["graph"]["items"][key("ore")]["main_ring"], 1)
        self.assertNotIn(key("ore"), {r["item"]["entity"] for r in query(ctx, "start.materials")})
        self.assertEqual(words(queries.how_runs(ctx, key("ore"), ring=0)), "mined in Mossy Forest (2% of dig hits)")
        self.assertEqual(words(queries.how_runs(ctx, key("ore"))), "mined in Desert (20% of dig hits)")

    def test_optional_scaling_requires_unambiguous_captured_values(self):
        captured = {"_MutantLvDisInterval": 1000, "_Z_Mutant_F": 2, "_QualityCapDistanceInterval": 2000}
        rows = fixture() + [row("scaling", "world-rule", "Scaling", captured)]
        ctx = context(rows)
        self.assertEqual(query(ctx, "world.zombie_scaling"), {"zombie_level_step": "500 m"})
        self.assertEqual(query(ctx, "world.loot_quality_scaling"), {"quality_step": "2 km"})
        for invalid in (0, -1, True, float("inf"), "2000", 4000):
            ctx = context(rows + [row("conflict", "world-rule", "Other scaling", {"_QualityCapDistanceInterval": invalid})])
            self.assertIsNone(query(ctx, "world.loot_quality_scaling"))
        rows = fixture()
        next(r for r in rows if r["entity_key"] == key("world"))["semantic"]["relationships"] = [
            rel for rel in next(r for r in rows if r["entity_key"] == key("world"))["semantic"]["relationships"]
            if rel["predicate"] != "base-terrain-prefab"]
        self.assertIsNone(query(context(rows), "world.near_spawn"))

    def test_loot_families_order_limits_scope_and_unknown_exclusivity(self):
        rows = fixture()
        for identity, bundle in [("car-a", "cars_forest"), ("car-b", "cars_forest"),
                                 ("body", "zb_forest"), ("airport", "world_ab_airport_forest"),
                                 ("desert-crate", "shc_crates_desert")]:
            rows.append(row(identity, "loot-source", "Loot source", links=[link("uses-loot-table", "table")],
                            source_id=f"bundles/{bundle}_assets_all.bundle::serialized#1"))
        ctx = context(rows)
        self.assertEqual(words(queries.how_runs(ctx, key("part"), limit=1)),
                         "found in cars, crates, dead bodies and 1 other place in Mossy Forest and Desert")
        self.assertEqual(words(queries.how_runs(ctx, key("part"), ring=1, limit=1)), "found in crates in Desert")
        self.assertEqual(query(ctx, "ring.exclusive_loot", 0), [])
        self.assertEqual(query(ctx, "ring.exclusive_loot", 1), [])
        rows = fixture() + [row("unknown-box", "loot-source", "Hidden Cache", links=[link("uses-loot-table", "table")],
                                source_id="bundles/unmapped_assets_all.bundle::serialized#1")]
        ctx = context(rows)
        self.assertEqual(query(ctx, "ring.exclusive_loot", 0), [])
        runs = queries.how_runs(ctx, key("part"), limit=1)
        self.assertEqual(words(runs), "found in crates and Hidden cache in Mossy Forest")
        self.assertIn(entity("unknown-box", "Hidden cache"), runs)

    def test_loot_in_eight_ring_biomes_is_almost_everywhere(self):
        rows = fixture()
        world = next(r for r in rows if r["entity_key"] == key("world"))["semantic"]
        for index, name, token in [(2, "Mountain", "mountain"), (3, "Warzone", "warzone"),
                                   (4, "Wasteland", "wasteland"), (5, "Tropical", "rainforest"),
                                   (6, "Swamp", "swamp"), (7, "Desert_Rocky", "desert_rocky")]:
            world["facts"]["_BiomesLayers"].append({})
            world["relationships"].append(link("biome-terrain-prefab", f"top{index}", f"/_BiomesLayers/{index}/terrainTops/0"))
            rows += [row(f"biome{index}", "biome", name),
                     row(f"top{index}", "resource-distribution", name + " ground", links=[link("biome", f"biome{index}")]),
                     row(f"crate{index}", "loot-source", "Crate", links=[link("uses-loot-table", "table")],
                         source_id=f"bundles/shc_crates_{token}_assets_all.bundle::serialized#1")]
        rows.append(row("crate1", "loot-source", "Crate", links=[link("uses-loot-table", "table")],
                        source_id="bundles/shc_crates_desert_assets_all.bundle::serialized#1"))
        self.assertEqual(words(queries.how_runs(context(rows), key("part"), limit=1)), "found in crates, almost everywhere")
        self.assertEqual(words(queries.how_short(context(rows), key("part"))), "Loot, almost everywhere · Salvage")

    def test_harvest_names_limit_and_source_priority(self):
        rows = fixture()
        for identity, name in [("ash", "Ash"), ("birch", "Birch"), ("cedar", "Cedar")]:
            rows.append(row(identity, "building-piece", name, {"_Collectable_Info": {"_Items": [{"_RandomRate": 1}]}},
                            [link("collectible-item", "wood", "/_Collectable_Info/_Items/0/_IconRef")]))
        ctx = context(rows)
        self.assertEqual(words(queries.how_runs(ctx, key("wood"))), "gathered from trees and other scenery")
        self.assertEqual(words(queries.how_runs(ctx, key("wood"), ring=0)), "gathered from trees and other scenery")
        self.assertEqual(words(queries.how_runs(ctx, key("wood"), ring=1)), "gathered from trees and other scenery")
        # A crafted recipe must not invent a fifth material grouping, and the
        # public limit cannot expose more than two acquisition phrases.
        ctx = context(fixture() + [recipe("make-part", "part", [("wood", 2)])])
        self.assertEqual(queries.method(ctx, key("part")), "Scavenging")
        self.assertEqual(words(queries.how_runs(ctx, key("part"), limit=20)),
                         "crafted by hand; found in crates in Mossy Forest")

    def test_registry_harvest_kinds_cover_each_rule_without_model_names(self):
        examples = [
            ("car", "AM165_002_VRay", "wrecked cars"),
            ("beech-source", "Beech_tree_03", "trees"),
            ("branch", "Mountain_branch_03", "fallen branches"),
            ("plant", "Cactus_Bush_var1", "plants"),
            ("bone", "Skull_01", "bones"),
            ("rubble", "ConBrick_Debris_S_04", "rubble"),
            ("metal", "Metal_Debris_S_03", "scrap metal"),
            ("debris", "Wood_Trash_L_06", "debris"),
            ("rock", "Ground_rock_var1", "rocks"),
            ("mushroom", "Mushroom_Pennybun_02", "mushrooms"),
            ("mineral", "Limestone_03", "mineral deposits"),
            ("wall", "Bastion_Wall_B_02", "ruined walls"),
            ("supplies", "Soda_Can_01", "abandoned supplies"),
            ("packaging", "Packaging_Grp_D", "packaging"),
            ("household", "Bedroom_Cupboard", "household clutter"),
        ]
        ctx = context(fixture() + [harvest_source(identity, name, "wood")
                                   for identity, name, _ in examples])
        for identity, _, expected in examples:
            self.assertEqual(queries._harvest_kind(ctx, key("wood"), key(identity))[0], expected)
        phrase = words(queries.how_runs(ctx, key("wood")))
        self.assertEqual(phrase, "gathered from trees, abandoned supplies, bones and 12 more kinds")
        for _, name, _ in examples:
            self.assertNotIn(queries._scenery_family(name), phrase)

    def test_real_family_collisions_take_the_plain_kind(self):
        examples = [
            ("tree-rubble", "Concrete_Debris_Big_01_Tree", "rubble"),
            ("tree-rock", "beech_forest_stones_01_3", "rocks"),
            ("tree-mushroom", "mushroom_birch_bolete_03", "mushrooms"),
            ("tree-branch", "pine_broken_branch_01", "fallen branches"),
            ("stones", "SM_StonesPile01", "rocks"),
        ]
        ctx = context(fixture() + [harvest_source(identity, name, "wood")
                                   for identity, name, _ in examples])
        for identity, _, expected in examples:
            self.assertEqual(queries._harvest_kind(ctx, key("wood"), key(identity))[0], expected)

    def test_minerals_come_from_rules_and_a_same_named_source_is_the_item_itself(self):
        rows = fixture() + [
            row("copper", "item", "Ore_Copper"),
            row("wax", "item", "Chrismatite_Icon"),
            row("marble", "item", "Marble"),
            row("wrong", "item", "Wood"),
            row("torch-item", "item", "Torch"),
            row("cactus-item", "item", "Cactus"),
            harvest_source("copper-source", "Ore_Copper", "copper"),
            harvest_source("wax-source", "Chrismatite", "wax"),
            harvest_source("marble-source", "Marble", "marble"),
            harvest_source("wrong-source", "Wood_Trash_03", "wrong"),
            harvest_source("torch-source", "Torch", "torch-item"),
            harvest_source("cactus-source", "Cactus_02", "cactus-item"),
        ]
        ctx = context(rows)
        for item in ("copper", "wax", "marble"):
            self.assertEqual(words(queries.how_runs(ctx, key(item))), "gathered from mineral deposits")
        self.assertEqual(words(queries.how_runs(ctx, key("wrong"))), "gathered from debris")
        # Review finding: a torch or a cactus is not a mineral because the source shares its name.
        self.assertEqual(words(queries.how_runs(ctx, key("torch-item"))), "gathered from ones found in the world")
        self.assertEqual(words(queries.how_runs(ctx, key("cactus-item"))), "gathered from plants")
        self.assertNotIn(key("torch-source"), queries.other_scenery_sources(ctx))

    def test_other_scenery_stays_last_and_remainder_counts_kinds(self):
        rows = fixture() + [harvest_source("duct-1", "Terra_Block_01", "wood"),
                            harvest_source("duct-2", "Terra_Block_02", "wood")]
        ctx = context(rows)
        self.assertEqual(words(queries.how_runs(ctx, key("wood"))),
                         "gathered from trees and other scenery")
        self.assertEqual(set(queries.other_scenery_sources(ctx)), {key("duct-1"), key("duct-2")})
        rows += [harvest_source("skull", "Skull_01", "wood"),
                 harvest_source("brick", "ConBrick_Debris_01", "wood"),
                 harvest_source("rock", "Ground_rock_var1", "wood")]
        self.assertEqual(words(queries.how_runs(context(rows), key("wood"))),
                         "gathered from bones, rocks, rubble and 2 more kinds")
        rows = fixture() + rows[-3:]
        self.assertEqual(words(queries.how_runs(context(rows), key("wood"))),
                         "gathered from bones, rocks, rubble and 1 more kind")

    def test_tool_stats_use_card_fields_and_localized_labels(self):
        ctx = queries.build_context(fixture(), REGISTRY, {"_Damage_Title": "Impact: ", "_Dura_Title": "Lifetime: "}, SNAPSHOT)
        stats = {stat["field"]: stat for stat in ctx["cards"][key("axe")]["stats"]}
        self.assertEqual(stats["/_baseDamage"]["label"], "Impact")
        self.assertEqual(stats["/_BaseMaxDurability"]["label"], "Lifetime")
        self.assertEqual(query(ctx, "start.tools_and_weapons")[0]["Damage"], "12.35")
        self.assertEqual(query(ctx, "start.tools_and_weapons")[0]["Durability"], "200")

    def test_recipe_choice_uses_shallower_bench_and_unknown_depth_stays_unknown(self):
        rows = fixture() + [recipe("saw-by-hand", "saw", [("wood", 1)])]
        ctx = context(rows)
        self.assertEqual(query(ctx, "start.tools_and_weapons")[0]["Item"], entity("saw", "Saw"))
        self.assertEqual(query(ctx, "start.tools_and_weapons")[0]["Made at"], "By hand")
        self.assertEqual(ctx["bench_depths"][key("bench1")], 1)
        self.assertEqual(ctx["bench_depths"][key("bench2")], 2)
        rows = fixture() + [row("unbuilt", "workbench", "Unknown bench", {"_workbenchType": 8})]
        ctx = context(rows)
        self.assertNotIn(key("unbuilt"), ctx["bench_depths"])
        self.assertNotIn(key("unbuilt"), {r["bench"]["entity"] for r in query(ctx, "start.benches")})

    def test_scenery_families_deduplicate_rank_and_remove_repeated_suffixes(self):
        rows = fixture()
        names = ["Ground rock var1", "Ground rock var2 lod0", "Ground rock 03 a",
                 "Air duct 01 turn lod0", "Wood trash l 04", "Debris burned a", "Beech tree 03"]
        for index, name in enumerate(names):
            rows.append(row(f"prop-{index}", "building-piece", name,
                            {"_Collectable_Info": {"_Items": [{"_RandomRate": 1}]}},
                            [link("collectible-item", "wood", "/_Collectable_Info/_Items/0/_IconRef")]))
        ctx = context(rows)
        self.assertEqual(words(queries.how_runs(ctx, key("wood"))),
                         "gathered from rocks, debris, trees and 1 more kind")
        for source, family in zip(names, ["ground rock"] * 3 + ["air duct", "wood trash", "debris burned", "beech tree"]):
            self.assertEqual(queries._scenery_family(source), family)
        # Unlocated scenery belongs in every ring's harvesting phrase.
        self.assertEqual(words(queries.how_runs(ctx, key("wood"), ring=0)),
                         "gathered from rocks, debris, trees and 1 more kind")
        self.assertEqual(queries._scenery_family("Prefab mountain branch 03 lod0"), "mountain branch")

    def test_scenery_model_tokens_anywhere_and_leading_prefixes_deduplicate(self):
        rows = weapon_fixture()
        names = ["Concrete debris big 01 tree", "Prefab concrete var2 debris lod3 big tree",
                 "SM concrete debris big tree 04", "sm rock", "Prefab rock lod0", "SM var1 rock 02"]
        for index, name in enumerate(names):
            rows.append(row(f"prop-{index}", "building-piece", name,
                            {"_Collectable_Info": {"_Items": [{"_RandomRate": 1}]}},
                            [link("collectible-item", "wood", "/_Collectable_Info/_Items/0/_IconRef")]))
        ctx = context(rows)
        for source, family in zip(names, ["concrete debris big tree"] * 3 + ["rock"] * 3):
            self.assertEqual(queries._scenery_family(source), family)
        self.assertEqual(words(queries.how_runs(ctx, key("wood"), ring=0)),
                         "gathered from rocks, rubble and trees")
        self.assertEqual(words(queries.how_runs(ctx, key("wood"), ring=1)),
                         "gathered from rocks and rubble")
        self.assertEqual(payloads(ctx), payloads(context(list(reversed(rows)))))

    def test_unknown_biome_harvest_survives_ring_scope_alongside_crafting(self):
        rows = fixture()
        for identity, name in [("scenery", "Wood trash 01"), ("desert-prop", "Desert cactus")]:
            rows.append(row(identity, "building-piece", name,
                            {"_Collectable_Info": {"_Items": [{"_RandomRate": 1}]}},
                            [link("collectible-item", "plank", "/_Collectable_Info/_Items/0/_IconRef")]))
        next(r for r in rows if r["entity_key"] == key("top1"))["semantic"]["relationships"].append(
            link("vegetation", "desert-prop"))
        ctx = context(rows)
        expected = rich("gathered from ", "debris", "; ", "crafted at the ", entity("bench1", "Workbench"))
        self.assertEqual(queries.how_runs(ctx, key("plank"), ring=0), expected["runs"])
        self.assertEqual(words(queries.how_runs(ctx, key("plank"), ring=1)),
                         "gathered from debris and plants")
        for name, index in [("start.materials", None), ("ring.new_materials", 0)]:
            result = next(r for r in query(ctx, name, index) if r["item"]["entity"] == key("plank"))
            self.assertEqual(result, {"item": entity("plank", "Planks"), "method": "Gathering", "how": expected})

    def test_short_how_preserves_links_order_and_three_part_limit(self):
        ctx = context(fixture() + [recipe("make-part", "part", [("wood", 1)])])
        expected = {
            "ore": ["Mined in ", entity("desert", "Desert")], "axe": ["By hand"],
            "plank": [entity("bench1", "Workbench")], "stock": ["Merchants"],
            "part": ["By hand", " · ", "Loot in ", entity("forest", "Mossy Forest"), " · ", "Salvage"],
        }
        for identity, parts in expected.items():
            self.assertEqual(queries.how_short(ctx, key(identity)), rich(*parts)["runs"])
        # Full list text keeps the source details and lowercase phrases.
        self.assertEqual(words(queries.how_runs(ctx, key("part"))), "crafted by hand; found in crates in Mossy Forest")
        rows = fixture() + [recipe("make-part", "part", [("wood", 1)]), mining("part-block", [("part", 0.1)])]
        next(r for r in rows if r["entity_key"] == key("top0"))["semantic"]["relationships"].append(link("terrain-block-set", "part-block"))
        self.assertEqual(words(queries.how_short(context(rows), key("part"))),
                         "Mined in Mossy Forest · By hand · Loot in Mossy Forest")

    def test_source_less_weapon_is_absent_from_tables_and_variants(self):
        rows = fixture() + [row("ghost", "item", "Rifle", {"_Tag": "Gun", "_baseDamage": 1000})]
        ctx = context(rows)
        self.assertEqual([r["Weapon"]["entity"] for r in query(ctx, "weapons.guns")], [key("gun")])
        self.assertEqual(query(ctx, "weapons.variants"), [])

    def test_bow_speed_uses_combat_card_direct_model_or_shared_object_join(self):
        for join in ("direct", "model", "shared"):
            rows = weapon_fixture()
            bow = next(r for r in rows if r["entity_key"] == key("bow"))
            combat = next(r for r in rows if r["entity_key"] == key("bow-combat"))
            if join == "model":
                bow["semantic"]["relationships"] = [link("model", "bow-model")]
                rows.append(row("bow-model", "asset", "Bow model", links=[link("cataloged-component", "bow-combat")]))
            elif join == "shared":
                bow["semantic"]["relationships"] = []
                bow["provenance"]["game_objects"] = ["bow-instance"]
                combat["provenance"]["game_objects"] = ["bow-instance"]
            ctx = context(rows)
            self.assertEqual(ctx["names"][key("bow-combat")]["rule"], "combat-user")
            self.assertEqual(query(ctx, "weapons.bows")[0]["Speed"], "80 m/s", join)
            rows.remove(combat)
            self.assertEqual(query(context(rows), "weapons.bows")[0]["Speed"], "", join)

    def test_scoped_sources_and_rich_phrase_links_survive_rendering(self):
        rows = fixture() + [recipe("make-part", "part", [("ore", 1)])]
        ctx = context(rows)
        self.assertEqual(words(queries.how_runs(ctx, key("part"), ring=0)), "found in crates in Mossy Forest")
        self.assertEqual(words(queries.how_runs(ctx, key("part"), ring=1)), "crafted by hand; salvaged from Rifle")
        self.assertEqual(words(queries.how_runs(ctx, key("stock"), ring=1)), "sold by merchants in Mossy Forest")
        document = render(load_spec(ROOT / "guides/getting-started.json"), queries.QUERIES, ctx)
        markdown = render_markdown(document, lambda k: "/entry/" + k)
        self.assertIn(f"mined in [Mossy Forest](/entry/{key('forest')})", markdown)
        self.assertLess(markdown.index("Break rocks, trees and rubble with a melee weapon or your bare hands. With a gun or bow out, nothing drops."),
                        markdown.index("Everything below can be had in the first biome"))
        self.assertIn("Gathering needs a melee weapon or bare hands.", markdown)
        document = render(load_spec(ROOT / "guides/progression-by-biome.json"), queries.QUERIES, ctx)
        self.assertIn(f"at the [Workbench](/entry/{key('bench1')})", render_markdown(document, lambda k: "/entry/" + k))

    def test_weapon_golden_rows(self):
        ctx = context(weapon_fixture())
        self.assertEqual(query(ctx, "weapons.melee"), [{
            "Weapon": entity("axe", "Stone Axe"), "Damage": "12.35", "Execute": "2.5%", "Knockdown": "5%",
            "Durability": "200", "How to get it": rich("By hand")}])
        self.assertEqual(query(ctx, "weapons.guns"), [
            {"Weapon": entity("loot-gun", "Rifle (loot)"), "Type": "Bolt-action rifle", "Damage": "60", "Fire rate": "",
             "Capacity": "", "Ammo": entity("ammo", "Cartridges"),
             "How to get it": rich("Loot in ", entity("forest", "Mossy Forest"))},
            {"Weapon": entity("gun", "Rifle (crafted)"), "Type": "Bolt-action rifle", "Damage": "40", "Fire rate": "240",
             "Capacity": "5", "Ammo": entity("ammo", "Cartridges"),
             "How to get it": rich(entity("bench2", "Forge"))}])
        self.assertEqual(query(ctx, "weapons.bows"), [{
            "Weapon": entity("bow", "Wooden Bow"), "Arrow Damage": "125%", "Speed": "80 m/s",
            "Durability": "75", "How to get it": rich("By hand")}])
        self.assertEqual(query(ctx, "weapons.ammo_sources"), [
            {"ammo": entity("ammo", "Cartridges"), "how": rich("crafted at the ", entity("bench2", "Forge"))}])
        self.assertEqual(query(ctx, "weapons.variants"), [{
            "name": [entity("gun", "Rifle (crafted)"), entity("loot-gun", "Rifle (loot)")],
            "difference": rich("one is ", "crafted at the ", entity("bench2", "Forge"), "; ",
                               "the other is ", "only found as loot")}])

    def test_weapon_stat_meanings_card_notes_labels_and_flags(self):
        rows = weapon_fixture()
        ctx = context(rows)
        expected = [
            ("Damage", "Base damage before quality bonuses."),
            ("Execute", "Chance for a hit to trigger an execute attack."),
            ("Knockdown", "Chance for a hit to knock the target down."),
            ("Durability", "Maximum durability before quality bonuses."),
            ("Type", "The gun's weapon class."), ("Fire rate", "Shots per minute."),
            ("Capacity", "Rounds held before reloading."), ("Ammo", "Ammunition the gun uses."),
            ("Arrow Damage", "Arrow damage as a percentage of the arrow's base damage."),
            ("Speed", "Arrow launch speed in metres per second."),
        ]
        self.assertEqual(query(ctx, "weapons.stat_labels"), [{"label": label, "meaning": meaning} for label, meaning in expected])
        self.assertEqual(queries.weapon_column_labels(ctx), {label: [label] for label, _ in expected})
        note = "A sharp hit can deal an additional 100 damage."
        next(r for r in rows if r["entity_key"] == key("gun"))["semantic"]["facts"]["_fireRate"] = "00"
        ctx = queries.build_context(rows, REGISTRY, {"_Damage_Title": "Impact: ",
                    "_BladeHit_Title": "Sharp hit: ", "_BladeHit_Instruct": "Sharp hit: " + note}, SNAPSHOT)
        definitions = query(ctx, "weapons.stat_labels")
        self.assertIn({"label": "Sharp hit", "meaning": note}, definitions)
        self.assertIn({"label": "Single Shot", "meaning": "Fires one shot at a time."}, definitions)
        self.assertEqual(query(ctx, "weapons.guns")[1]["Fire rate"], "Single Shot")
        self.assertEqual(query(ctx, "weapons.guns")[1]["Damage"], "40")
        self.assertEqual(query(ctx, "weapons.melee")[0]["Execute"], "2.5%")
        self.assertEqual(queries.weapon_column_labels(ctx)["Damage"], ["Impact"])

    def test_weapon_sort_ring_damage_name_and_omit_source_less(self):
        rows = weapon_fixture()
        for identity, name, damage, ingredient in [("alpha", "Alpha", 70, "wood"), ("zulu", "Zulu", 70, "wood"),
                                                  ("late", "Late", 900, "ore"), ("lost", "Lost", 1000, None)]:
            rows.append(row(identity, "item", name, {"_Tag": "Gun", "_baseDamage": damage}))
            if ingredient:
                rows.append(recipe(identity + "-recipe", identity, [(ingredient, 1)]))
        ctx = context(rows)
        self.assertEqual([r["Weapon"]["text"] for r in query(ctx, "weapons.guns")],
                         ["Alpha", "Zulu", "Rifle (loot)", "Late", "Rifle (crafted)"])
        self.assertTrue(all("Ring" not in entry for entry in query(ctx, "weapons.guns")))
        # The graph's main ring wins even when a rarer source is earlier.
        ctx["graph"]["items"][key("late")]["earliest_ring"] = 0
        self.assertEqual(query(ctx, "weapons.guns")[3]["Weapon"], entity("late", "Late"))

    def test_ammo_joins_are_explicit_deduplicated_and_do_not_match_names(self):
        rows = weapon_fixture() + [row("ammo2", "item", "Handmade Cartridges", {"_Tag": "9x19"}),
                                  recipe("ammo2-recipe", "ammo2", [("ore", 1)], "bench2"),
                                  row("decoy-ammo", "item", "9x19", {"_Tag": "9x19"})]
        next(r for r in rows if r["entity_key"] == key("ammo-type"))["semantic"]["relationships"] += [
            link("ammunition-item", "ammo2"), link("ammunition-item", "ammo")]
        ctx = context(rows)
        self.assertEqual(query(ctx, "weapons.guns")[0]["Ammo"], entity("ammo", "Cartridges"))
        self.assertEqual([r["ammo"] for r in query(ctx, "weapons.ammo_sources")], [entity("ammo", "Cartridges")])
        rows = [r for r in rows if r["entity_key"] != key("ammo-type")]
        ctx = context(rows)
        self.assertEqual(query(ctx, "weapons.guns")[0]["Ammo"], "")
        self.assertEqual(query(ctx, "weapons.ammo_sources"), [])

    def test_same_source_variants_explain_a_stat_difference(self):
        rows = fixture() + [row("axe2", "item", "Stone Axe", {"_Tag": "MeleeWeapon", "_baseDamage": 20}),
                            recipe("axe2-recipe", "axe2", [("wood", 1)])]
        variants = query(context(rows), "weapons.variants")
        self.assertEqual(len(variants), 1)
        self.assertEqual(words(variants[0]["difference"]["runs"]), "one has Damage 12.35; the other has Damage 20")

    def test_base_ammo_prefers_uncrafted_and_groups_material_links_in_game_order(self):
        for materials in [("Copper", "Steel", "Titanium", "Chrome", "Tungsten"), ("Steel", "Chrome")]:
            rows = [r for r in weapon_fixture() if r["entity_key"] != key("ammo-recipe")]
            by = {r["entity_key"]: r["semantic"] for r in rows}
            by[key("ammo")]["name"] = "Standard Cartridges"
            by[key("tag")]["relationships"].append(link("eligible-item", "ammo"))
            for material in reversed(materials):
                identity = "ammo-" + material
                rows += [row(identity, "item", f"Cartridges ({material})", {"_Tag": "9x19"}),
                         recipe(identity + "-recipe", identity, [("ore", 1)], "bench2")]
                by[key("ammo-type")]["relationships"].append(link("ammunition-item", identity))
            # A linked but source-less ammo record must not become the base.
            rows.append(row("empty-ammo", "item", "A cartridge", {"_Tag": "9x19"}))
            by[key("ammo-type")]["relationships"].append(link("ammunition-item", "empty-ammo"))
            ctx = context(rows)
            self.assertEqual([r["Ammo"] for r in query(ctx, "weapons.guns")], [entity("ammo", "Standard Cartridges")] * 2)
            result = query(ctx, "weapons.ammo_sources")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["ammo"], entity("ammo", "Standard Cartridges"))
            material_text = ", ".join(materials[:-1]) + " and " + materials[-1]
            self.assertEqual(words(result[0]["how"]["runs"]),
                             "found in crates in Mossy Forest; handmade " + material_text + " rounds at the Forge")
            self.assertEqual([run for run in result[0]["how"]["runs"] if run.get("entity", "") in {key("ammo-" + m) for m in materials}],
                             [entity("ammo-" + m, m) for m in materials])
            random.Random(14).shuffle(rows)
            self.assertEqual(query(context(rows), "weapons.ammo_sources"), result)

    def test_exclusions_apply_to_all_guide_lists_and_nested_links(self):
        rows = weapon_fixture()
        for identity, name in [("wip", "WIP"), ("test-weapon", "Test Rifle"),
                               ("god-weapon", "G_Mode"), ("preview-weapon", "PreviewContent")]:
            rows += [row(identity, "item", name, {"_Tag": "Gun"}),
                     recipe(identity + "-recipe", identity, [("wood", 1)], "bench1")]
        by = {r["entity_key"]: r["semantic"] for r in rows}
        by[key("preview-weapon")]["name_status"] = "internal"
        # Test exact player-name exclusions on a bench with a different original name.
        by[key("bench2")]["name"] = "WB_Gunsmith"
        registry = copy.deepcopy(REGISTRY)
        registry["guides"]["exclude_names"] += ["Gunsmith Workbench", "Flux"]
        registry["guides"]["exclude_patterns"].append("^Preview content$")
        ctx = queries.build_context(rows, registry, labels(rows), SNAPSHOT)
        forbidden = {key(k) for k in ("wip", "test-weapon", "god-weapon", "preview-weapon", "bench2", "stock")}

        def entities(value):
            if isinstance(value, dict):
                if "entity" in value:
                    yield value["entity"]
                for child in value.values():
                    yield from entities(child)
            elif isinstance(value, list):
                for child in value:
                    yield from entities(child)

        for name, function in queries.QUERIES.items():
            scopes = query(ctx, "rings") if name.startswith("ring.") else query(ctx, "benches") if name.startswith("bench.") else [{}]
            for scope in scopes:
                self.assertFalse(forbidden & set(entities(function(ctx, scope))), name)
        self.assertEqual(query(ctx, "ring.merchant_summary", 0), None)
        self.assertEqual(query(ctx, "benches"), [{"bench": entity("bench1", "Workbench")}])
        self.assertEqual(query(ctx, "benches.overview")[0]["Recipes"], "2")
        self.assertEqual(query(ctx, "start.benches")[0]["unlock_count"], "2")
        self.assertNotIn(key("wip-recipe"), {r["entity"] for r in queries.used_in(ctx, key("wood"))})
        for guide in GUIDES:
            document = render(load_spec(ROOT / "guides" / (guide + ".json")), queries.QUERIES, ctx)
            self.assertFalse(forbidden & set(entities(document)), guide)
            self.assertEqual([hit for _, text in text_runs(document) for hit in jargon(text)], [])

    def test_excluded_ingredients_do_not_create_partial_build_costs(self):
        registry = copy.deepcopy(REGISTRY)
        registry["guides"]["exclude_names"].append("Planks")
        rows = fixture()
        ctx = queries.build_context(rows, registry, labels(rows), SNAPSHOT)
        self.assertEqual(query(ctx, "benches"), [{"bench": entity("bench1", "Workbench")}])
        self.assertEqual(queries.QUERIES["bench.cost"](ctx, {"bench": entity("bench2", "Forge")}), [])
        self.assertEqual(query(ctx, "ring.new_recipes", 0), [
            {"output": entity("axe-recipe", "Stone Axe"), "made": rich("by hand"), "category": "Melee weapon"},
            {"output": entity("torch-recipe", "Torch"), "made": rich("by hand"), "category": "Tool"}])

    def test_bench_golden_rows(self):
        benches = [{"bench": entity("bench1", "Workbench")}, {"bench": entity("bench2", "Forge")}]
        self.assertEqual(query(self.ctx, "benches"), benches)
        self.assertEqual(query(self.ctx, "benches.overview"), [
            {"Bench": entity("bench1", "Workbench"), "Recipes": "2", "Build cost": [entity("wood", "2 × Wood")]},
            {"Bench": entity("bench2", "Forge"), "Recipes": "3", "Build cost": [entity("plank", "3 × Planks")]}])
        for bench in benches:
            self.assertEqual(queries.QUERIES["bench.summary"](self.ctx, bench), {"ring": "Biome 1 (Mossy Forest)", "built_at": rich("by hand")})
        self.assertEqual(queries.QUERIES["bench.cost"](self.ctx, benches[0]), [
            {"count": "2", "item": entity("wood", "Wood"), "how": rich("gathered from ", "trees")}])
        self.assertEqual(queries.QUERIES["bench.cost"](self.ctx, benches[1]), [
            {"count": "3", "item": entity("plank", "Planks"), "how": rich("crafted at the ", entity("bench1", "Workbench"))}])
        self.assertEqual(queries.QUERIES["bench.recipes"](self.ctx, benches[0]), [
            {"output": entity("planks-part", "Planks from Spare Part"), "category": "Building material"},
            {"output": entity("planks-wood", "Planks from Wood"), "category": "Building material"}])
        self.assertEqual(queries.QUERIES["bench.recipes"](self.ctx, benches[1]), [
            {"output": entity("ammo-recipe", "Cartridges"), "category": "Ammo"},
            {"output": entity("gun-recipe", "Rifle"), "category": "Gun"},
            {"output": entity("saw-recipe", "Saw"), "category": "Tool"}])

    def test_bench_built_at_link_and_construction_recipe_exclusion(self):
        rows = [r for r in fixture() if r["entity_key"] != key("build-second")]
        rows.append(recipe("build-second", "station2", [("plank", 3)], "bench1"))
        ctx = context(rows)
        bench1, bench2 = query(ctx, "benches")
        self.assertEqual(queries.QUERIES["bench.summary"](ctx, bench2),
                         {"ring": "Biome 1 (Mossy Forest)", "built_at": rich("at the ", entity("bench1", "Workbench"))})
        self.assertEqual(len(queries.QUERIES["bench.recipes"](ctx, bench1)), 2)
        self.assertEqual(query(ctx, "benches.overview")[0]["Recipes"], "2")
        for name in ("start.hand_recipes", "ring.new_recipes"):
            self.assertNotIn(key("build-second"), {r["output"]["entity"] for r in query(ctx, name, 0)})

    def test_all_query_numbers_are_strings_and_entity_links_resolve(self):
        ctx = context(weapon_fixture())

        def check(value):
            if isinstance(value, dict):
                if "entity" in value:
                    self.assertIn(value["entity"], ctx["names"])
                    self.assertIsInstance(value["text"], str)
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
            else:
                self.assertTrue(value is None or isinstance(value, str), repr(value))

        for name, function in queries.QUERIES.items():
            scopes = query(ctx, "rings") if name.startswith("ring.") else query(ctx, "benches") if name.startswith("bench.") else [{}]
            for scope in scopes:
                check(function(ctx, scope))


class RenderGuidesToolTests(unittest.TestCase):
    def test_report_lists_distinct_unmatched_source_families(self):
        ctx = context(fixture() + [harvest_source("duct-1", "Terra_Block_01", "wood"),
                                   harvest_source("duct-2", "Terra_Block_02", "wood")])
        directory = str(fixture_dir(self, "guide_qu"))
        with patch.object(render_guides, "load_context", return_value=ctx), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(render_guides.main(["--out", directory, "--guides", "getting-started"]), 0)
        self.assertIn("Other scenery sources: 2\n", output.getvalue())
        self.assertIn('Other scenery families: ["terra block"]\n', output.getvalue())

    def test_reader_guide_receipt_reports_unmatched_scenery(self):
        ctx = context(fixture() + [harvest_source("terra-1", "Terra_Block_01", "wood"),
                                   harvest_source("terra-2", "Terra_Block_02", "wood")])
        _, receipt = reader.project_guides(Path("."), [], ctx, lambda path, data: None)
        self.assertEqual(receipt["other_scenery"], ["terra block"])

    def test_default_selection_files_repeat_bytes_and_explicit_selection(self):
        directory = str(fixture_dir(self, "guide_qu"))
        out = Path(directory) / "guides"
        with patch.object(render_guides, "load_context", return_value=context(weapon_fixture())), redirect_stdout(io.StringIO()):
            self.assertEqual(render_guides.main(["--out", str(out)]), 0)
            first = {path.name: path.read_bytes() for path in out.iterdir()}
            self.assertEqual(set(first), {guide + ext for guide in GUIDES for ext in (".json", ".md")})
            self.assertEqual(render_guides.main(["--out", str(out), "--guides", ",".join(GUIDES)]), 0)
            self.assertEqual({path.name: path.read_bytes() for path in out.iterdir()}, first)

    def test_render_failure_does_not_promote_partial_output(self):
        directory = str(fixture_dir(self, "guide_qu"))
        out = Path(directory) / "guides"
        out.mkdir()
        previous = out / "getting-started.md"
        previous.write_bytes(b"previous reviewed output\n")
        ctx = context(weapon_fixture())
        with patch.object(render_guides, "load_context", return_value=ctx), \
                patch.dict(queries.QUERIES, {"ring.span": lambda context, scope: {}}):
            with self.assertRaises(GuideError):
                render_guides.main(["--out", str(out)])
        self.assertEqual(list(out.iterdir()), [previous])
        self.assertEqual(previous.read_bytes(), b"previous reviewed output\n")

    def test_jargon_fails_and_reports_the_actual_visible_string(self):
        ctx = context()
        ctx["names"][key("wood")]["name"] = "Wood_Internal"
        directory = str(fixture_dir(self, "guide_qu"))
        with patch.object(render_guides, "load_context", return_value=ctx), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(render_guides.main(["--out", directory, "--guides", "getting-started"]), 1)
        self.assertIn('"match": "Wood_Internal"', output.getvalue())

    def test_unsupported_selection_fails_before_read_or_write(self):
        for selection in ("unknown", "getting-started,getting-started"):
            directory = str(fixture_dir(self, "guide_qu"))
            with patch.object(render_guides, "load_context") as loader, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    render_guides.main(["--out", directory, "--guides", selection])
                loader.assert_not_called()
                self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
