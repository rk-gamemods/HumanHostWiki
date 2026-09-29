"""Acquisition joins and reachable least fixed points on model-shaped rows."""

import copy
import json
import random
import unittest

from wikibuild.gameplay import graph


def link(predicate, target, field=""):
    return {"predicate": predicate, "field": field, "targets": [target] if target else []}


def row(key, kind, facts=None, links=(), name=None, **provenance):
    return {"entity_key": key, "semantic": {"kind": kind, "topic": "fixture",
            "name": name or key, "facts": facts or {}, "relationships": list(links)},
            "provenance": provenance}


def recipe(key, output, ingredients, bench="hand"):
    return row(key, "recipe", {"craftNum": 1, "matsData": [{"matNeedCount": count} for _, count in ingredients]},
               [link("produces-item", output), link("defined-by", bench),
                *[link("consumes-item-asset", item, f"/matsData/{index}/matIcon")
                  for index, (item, _) in enumerate(ingredients)]])


def fixture():
    rows = [row(key, "item") for key in ("wood", "ore", "loot", "stock", "station", "gun", "scrap",
                                       "cycle-a", "cycle-b", "seed-a", "seed-b", "missing", "blocked", "fiber")]
    rows += [
        row("forest", "biome", name="Forest"), row("desert", "biome", name="Desert"),
        row("world", "world-rule", {"BigTerraWidth": 100, "_BiomesWidthNum": 2,
                                    "_BiomesLayers": [{"BigTerraNames": ["Start"]}, {"BigTerraNames": ["Desert"]}]},
            [link("biome-terrain-prefab", "terrain0", "/_BiomesLayers/0/terrainTops/0"),
             link("biome-terrain-prefab", "terrain1", "/_BiomesLayers/1/terrainTops/0")]),
        row("terrain0", "asset", links=[link("cataloged-component", "top0")]),
        row("terrain1", "asset", links=[link("cataloged-component", "top1")]),
        row("top0", "resource-distribution", links=[link("biome", "forest"), link("vegetation", "tree-prefab")]),
        row("top1", "resource-distribution", links=[link("biome", "desert"), link("terrain-block-set", "blocks")]),
        row("blocks", "resource-distribution", {"_BlockInfo": [{"CollectableItems": [
            {"RandomRate": 0.2}, {"RandomRate": 0.3}]}]},
            [link("mineable-item", "ore", "/_BlockInfo/0/CollectableItems/0"),
             link("mineable-item", None, "/_BlockInfo/0/CollectableItems/1")]),
        row("tree-prefab", "asset", links=[link("cataloged-component", "tree")]),
        row("tree", "building-piece", {"_Collectable_Info": {"_Items": [{"_RandomRate": 0.6}]}},
            [link("collectible-item", "wood", "/_Collectable_Info/_Items/0/_IconRef")]),
        row("tools", "combat-rule", links=[link("gathered-item", "fiber", "/_PlantFiberIconRef")]),
        row("box", "loot-source", links=[link("uses-loot-table", "table")],
            source_id="bundles/shc_crates_desert_assets_all.bundle::serialized-0#1"),
        row("unknown-box", "loot-source", links=[link("uses-loot-table", "table")],
            source_id="bundles/generic_assets_all.bundle::serialized-0#2"),
        row("table", "loot-table", {"rates": [{"_spawnLootTag": "gun-loot", "_spawnRateRange": 0.5}]}),
        row("tag", "loot-tag", {"tag": "gun-loot"}, [link("eligible-item", "loot")]),
        row("merchant", "loot-table", {"BiomeName": "Forest"},
            [link("merchant-stock-item", "stock"), link("merchant-stock-item", "seed-a")]),
        row("hand", "workbench", {"_workbenchType": 0}),
        row("bench", "workbench", {"_workbenchType": 5}, game_objects=["prefab#1"]),
        row("bench-prefab", "asset", source_id="prefab#1"),
        row("unknown-bench", "workbench", {"_workbenchType": 2}),
        recipe("build-bench", "station", [("wood", 2)]),
        recipe("build-gun", "gun", [("ore", 3), ("wood", 1)], "bench"),
        recipe("build-blocked", "blocked", [("missing", 2)]),
        recipe("cycle-a-recipe", "cycle-a", [("cycle-b", 1)]),
        recipe("cycle-b-recipe", "cycle-b", [("cycle-a", 1)]),
        recipe("seed-a-recipe", "seed-a", [("seed-b", 1)]),
        recipe("seed-b-recipe", "seed-b", [("seed-a", 1)]),
        row("disassemble", "processing-rule", links=[link("yields-item-asset", "scrap")]),
    ]
    by_key = {r["entity_key"]: r for r in rows}
    by_key["station"]["semantic"]["relationships"] = [link("model", "bench-prefab")]
    by_key["gun"]["semantic"]["relationships"] = [link("disassembly", "disassemble")]
    return rows


def near_spawn_fixture():
    """Three cyclic layers plus a separate Base patch, with rare ore nearby."""
    rows = fixture()
    by_key = {r["entity_key"]: r["semantic"] for r in rows}
    by_key["world"]["facts"]["_BiomesLayers"].append({"BigTerraNames": ["Mountain"]})
    by_key["world"]["relationships"] += [
        link("biome-terrain-prefab", "terrain2", "/_BiomesLayers/2/terrainTops/0"),
        link("base-terrain-prefab", "base-terrain", "/_BaseBigTerrains/baseBigTerraTops/0")]
    by_key["top1"]["relationships"] = [link("biome", "desert")]
    rows += [
        row("mountain", "biome", name="Mountain"), row("base", "biome", name="Base"),
        row("unused-base-definition", "biome", name="Base"),
        row("terrain2", "asset", links=[link("cataloged-component", "top2")]),
        row("top2", "resource-distribution", links=[link("biome", "mountain"), link("terrain-block-set", "blocks")]),
        row("base-terrain", "asset", links=[link("cataloged-component", "base-top")]),
        row("base-top", "resource-distribution", links=[link("biome", "base"),
            link("terrain-block-set", "base-blocks"), link("vegetation", "base-tree"),
            link("vegetation", "tree-prefab")]),
        row("base-blocks", "resource-distribution", {"_BlockInfo": [
            {"CollectableItems": [{"RandomRate": 0.01}, {"RandomRate": 0.2}]},
            {"CollectableItems": [{"RandomRate": 0.005}]}]},
            [link("mineable-item", "ore", "/_BlockInfo/0/CollectableItems/0"),
             link("mineable-item", "patch-item", "/_BlockInfo/0/CollectableItems/1"),
             link("mineable-item", "ore", "/_BlockInfo/1/CollectableItems/0")]),
        row("base-box", "loot-source", links=[link("uses-loot-table", "base-table")],
            source_id="bundles/zb_baseterrain_assets_all.bundle::0#1"),
        row("base-table", "loot-table", {"rates": [{"_spawnLootTag": "patch", "_spawnRateRange": 1}]}),
        row("base-tag", "loot-tag", {"tag": "patch"}, [link("eligible-item", "patch-loot")]),
        row("base-tree", "building-piece", {"_Collectable_Info": {"_Items": [{"_RandomRate": 1}]}},
            [link("collectible-item", "patch-harvest", "/_Collectable_Info/_Items/0/_IconRef")]),
        *[row(key, "item") for key in ("patch-item", "patch-loot", "patch-harvest", "patch-product")],
        recipe("patch-recipe", "patch-product", [("patch-item", 1)]),
    ]
    return rows


class GameplayTests(unittest.TestCase):
    def test_disabled_merchant_source_does_not_seed_reachability(self):
        rows = fixture()
        active = graph(rows)
        inactive = graph(rows, disabled_source_types={"merchant"})
        self.assertEqual([source["type"] for source in active["items"]["stock"]["sources"]], ["merchant"])
        self.assertEqual(inactive["items"]["stock"]["sources"], [])
        self.assertIsNone(inactive["items"]["stock"]["main_ring"])
        self.assertEqual(inactive["disabled_sources"]["merchant"],
                         [{"item": "seed-a", "via": "merchant"}, {"item": "stock", "via": "merchant"}])

    def test_every_output_field(self):
        result = graph(fixture())
        self.assertEqual(set(result), {"rings", "near_spawn", "biomes", "items", "recipes", "benches", "gaps"})
        self.assertEqual(result["near_spawn"], {"biome": None, "mined": [], "container_loot": [], "harvest": []})
        self.assertEqual(result["rings"], [
            {"index": 0, "layer": 0, "biome_keys": ["forest"], "start_distance": 12, "end_distance": 212},
            {"index": 1, "layer": 1, "biome_keys": ["desert"], "start_distance": 212, "end_distance": 412}])
        self.assertEqual(result["biomes"]["forest"], {
            "name": "Forest", "ring": 0, "mined": [], "container_loot": [],
            "merchant": [{"item": "seed-a"}, {"item": "stock"}],
            "harvest": [{"item": "wood", "source": "tree"}]})
        self.assertEqual(result["biomes"]["desert"], {
            "name": "Desert", "ring": 1,
            "mined": [{"item": "ore", "chance_per_hit": 0.2, "block_set": "blocks"}],
            "container_loot": [{"item": "loot", "container": "box"}], "merchant": [], "harvest": []})
        self.assertEqual(result["items"]["gun"], {
            "sources": [{"type": "crafted", "via": "build-gun", "biome": None,
                         "bench": "bench", "evidence": "extracted"}], "earliest_ring": 1, "main_ring": 1, "used_in": [],
            "near_spawn": False, "near_spawn_chance_per_hit": None,
            "biomes": [], "loot_biomes": [], "has_unmapped_loot": False})
        self.assertEqual(result["items"]["ore"], {
            "sources": [{"type": "mined", "via": "blocks", "biome": "desert",
                         "bench": None, "evidence": "extracted"}], "earliest_ring": 1, "main_ring": 1, "used_in": ["build-gun"],
            "near_spawn": False, "near_spawn_chance_per_hit": None,
            "biomes": ["desert"], "loot_biomes": [], "has_unmapped_loot": False})
        self.assertEqual(result["items"]["loot"], {
            "sources": [{"type": "looted", "via": "box", "biome": "desert", "bench": None,
                         "evidence": "inferred-from-bundle-name"},
                        {"type": "looted", "via": "unknown-box", "biome": None, "bench": None,
                         "evidence": "extracted"}], "earliest_ring": 1, "main_ring": 1, "used_in": [],
            "near_spawn": False, "near_spawn_chance_per_hit": None,
            "biomes": ["desert"], "loot_biomes": ["desert"], "has_unmapped_loot": True})
        self.assertEqual(result["recipes"]["build-gun"], {"output": "gun", "count": 1, "bench": "bench",
            "ingredients": [{"item": "ore", "count": 3}, {"item": "wood", "count": 1}],
            "earliest_ring": 1, "main_ring": 1, "blocked_by": []})
        self.assertEqual(result["recipes"]["build-bench"], {"output": "station", "count": 1, "bench": None,
            "ingredients": [{"item": "wood", "count": 2}], "earliest_ring": 0, "main_ring": 0, "blocked_by": []})
        self.assertEqual(result["benches"], {"bench": {"built_by_recipe": "build-bench", "earliest_ring": 0, "main_ring": 0,
            "construction_item": "station", "model": "bench-prefab", "evidence": "extracted", "gap_reason": None},
            "hand": {"built_by_recipe": None, "earliest_ring": 0, "main_ring": 0, "construction_item": None,
                     "model": None, "evidence": "hand-crafting", "gap_reason": None},
            "unknown-bench": {"built_by_recipe": None, "earliest_ring": None, "main_ring": None, "construction_item": None,
                              "model": None, "evidence": None, "gap_reason": "no-construction-item-join"}})
        self.assertEqual(result["gaps"], {"items_without_source": ["missing"],
            "unresolved_benches": ["unknown-bench"], "unmapped_container_bundles": ["generic_assets_all.bundle"]})
        self.assertEqual(result["items"]["fiber"], {"sources": [
            {"type": "harvested", "via": "tools", "biome": None, "bench": None,
             "evidence": "biome-independent-grass-cutting"}],
            "earliest_ring": None, "main_ring": None, "used_in": [], "biomes": [], "loot_biomes": [],
            "has_unmapped_loot": False, "near_spawn": False, "near_spawn_chance_per_hit": None})
        for key in ("seed-a", "seed-b", "stock", "wood"):
            self.assertEqual(result["items"][key]["earliest_ring"], 0, key)
            self.assertEqual(result["items"][key]["main_ring"], 0, key)
        for key in ("cycle-a", "cycle-b", "missing", "blocked"):
            self.assertIsNone(result["items"][key]["earliest_ring"], key)
            self.assertIsNone(result["items"][key]["main_ring"], key)
        self.assertEqual(result["recipes"]["build-blocked"]["blocked_by"], ["missing"])
        self.assertEqual(result["items"]["scrap"], {"sources": [
            {"type": "dismantled", "via": "gun", "biome": None, "bench": None, "evidence": "extracted"}],
            "earliest_ring": 1, "main_ring": 1, "used_in": [], "biomes": [], "loot_biomes": [],
            "has_unmapped_loot": False, "near_spawn": False, "near_spawn_chance_per_hit": None})
        self.assertEqual(result["items"]["wood"]["used_in"], ["build-bench", "build-gun"])

    def test_determinism_iterable_and_no_mutation(self):
        rows = near_spawn_fixture()
        before = copy.deepcopy(rows)
        expected = json.dumps(graph(iter(rows)), sort_keys=True, allow_nan=False)
        self.assertEqual(rows, before)
        for seed in range(5):
            random.Random(seed).shuffle(rows)
            for value in rows:
                random.Random(seed).shuffle(value["semantic"]["relationships"])
            self.assertEqual(json.dumps(graph(rows), sort_keys=True, allow_nan=False), expected)

    def test_base_patch_stays_outside_rings_and_retains_acquisition_details(self):
        rows = near_spawn_fixture()
        result = graph(rows)
        self.assertEqual([ring["biome_keys"] for ring in result["rings"]],
                         [["forest"], ["desert"], ["mountain"]])
        self.assertEqual(result["rings"][2], {"index": 2, "layer": 2, "biome_keys": ["mountain"],
                                            "start_distance": 412, "end_distance": 612})
        self.assertIsNone(result["biomes"]["base"]["ring"])
        self.assertEqual(result["near_spawn"]["biome"], "base")
        self.assertCountEqual(result["near_spawn"]["mined"], [
            {"item": "ore", "chance_per_hit": 0.01, "block_set": "base-blocks"},
            {"item": "ore", "chance_per_hit": 0.005, "block_set": "base-blocks"},
            {"item": "patch-item", "chance_per_hit": 0.2, "block_set": "base-blocks"}])
        self.assertEqual(result["near_spawn"]["container_loot"], [{"item": "patch-loot", "container": "base-box"}])
        self.assertCountEqual(result["near_spawn"]["harvest"], [
            {"item": "patch-harvest", "source": "base-tree"}, {"item": "wood", "source": "tree"}])
        ore = result["items"]["ore"]
        self.assertEqual((ore["earliest_ring"], ore["main_ring"]), (2, 2))
        self.assertTrue(ore["near_spawn"])
        self.assertEqual(ore["near_spawn_chance_per_hit"], 0.01)
        self.assertEqual(ore["biomes"], ["base", "mountain"])
        self.assertEqual({source["biome"] for source in ore["sources"]}, {"base", "mountain"})
        for key in ("patch-item", "patch-loot", "patch-harvest"):
            item = result["items"][key]
            self.assertTrue(item["near_spawn"], key)
            self.assertIsNone(item["earliest_ring"], key)
            self.assertIsNone(item["main_ring"], key)
            self.assertNotIn(key, result["gaps"]["items_without_source"])
        self.assertIsNone(result["items"]["patch-loot"]["near_spawn_chance_per_hit"])
        self.assertEqual(result["items"]["patch-loot"]["loot_biomes"], ["base"])
        self.assertFalse(result["items"]["patch-product"]["near_spawn"])
        self.assertIsNone(result["recipes"]["patch-recipe"]["earliest_ring"])
        self.assertIsNone(result["recipes"]["patch-recipe"]["main_ring"])
        self.assertEqual(result["recipes"]["patch-recipe"]["blocked_by"], ["patch-item"])

        # A bench's only ingredient remains near spawn, but loses its ring source.
        next(r for r in rows if r["entity_key"] == "top0")["semantic"]["relationships"] = [link("biome", "forest")]
        result = graph(rows)
        self.assertTrue(result["items"]["wood"]["near_spawn"])
        self.assertEqual(result["benches"]["bench"]["built_by_recipe"], "build-bench")
        self.assertIsNone(result["benches"]["bench"]["earliest_ring"])
        self.assertIsNone(result["benches"]["bench"]["main_ring"])
        self.assertEqual(result["benches"]["bench"]["gap_reason"], "construction-item-unreachable")

    def test_strongest_mining_site_propagates_separately_through_benches_and_cycles(self):
        rows = near_spawn_fixture()
        by_key = {r["entity_key"]: r["semantic"] for r in rows}
        by_key["top0"]["relationships"].append(link("terrain-block-set", "early-blocks"))
        rows += [row("early-blocks", "resource-distribution", {"_BlockInfo": [
            {"CollectableItems": [{"RandomRate": 0.02}]}]},
            [link("mineable-item", "ore", "/_BlockInfo/0/CollectableItems/0")]),
            recipe("seed-cycle", "cycle-a", [("ore", 1)])]
        rows = [r for r in rows if r["entity_key"] not in {"build-bench", "build-gun"}]
        rows += [recipe("build-bench", "station", [("ore", 2)]),
                 recipe("build-gun", "gun", [("wood", 1)], "bench")]
        result = graph(rows)
        for key in ("ore", "station", "gun", "scrap", "cycle-a", "cycle-b"):
            self.assertEqual(result["items"][key]["earliest_ring"], 0, key)
            self.assertEqual(result["items"][key]["main_ring"], 2, key)
        for key in ("build-bench", "build-gun", "seed-cycle", "cycle-a-recipe", "cycle-b-recipe"):
            self.assertEqual(result["recipes"][key]["earliest_ring"], 0, key)
            self.assertEqual(result["recipes"][key]["main_ring"], 2, key)
        self.assertEqual(result["benches"]["bench"]["earliest_ring"], 0)
        self.assertEqual(result["benches"]["bench"]["main_ring"], 2)
        self.assertEqual(result["benches"]["hand"]["main_ring"], 0)

    def test_mining_main_ring_uses_normalized_chances_and_earliest_tie(self):
        rows = near_spawn_fixture()
        by_key = {r["entity_key"]: r["semantic"] for r in rows}
        by_key["top1"]["relationships"].append(link("terrain-block-set", "middle-blocks"))
        rows += [row("middle-blocks", "resource-distribution", {"_BlockInfo": [
            {"CollectableItems": [{"RandomRate": 0.2}]}]},
            [link("mineable-item", "ore", "/_BlockInfo/0/CollectableItems/0")])]
        # Home's raw weight 2 becomes 20%; it ties the middle biome at 20%.
        by_key["blocks"]["facts"]["_BlockInfo"][0]["CollectableItems"] = [{"RandomRate": 2}, {"RandomRate": 8}]
        # Even a guaranteed Base drop must not change either ring.
        by_key["base-blocks"]["facts"]["_BlockInfo"][0]["CollectableItems"] = [{"RandomRate": 1}, {"RandomRate": 0}]
        ore = graph(rows)["items"]["ore"]
        self.assertEqual((ore["earliest_ring"], ore["main_ring"]), (1, 1))
        self.assertEqual(ore["near_spawn_chance_per_hit"], 1)

    def test_non_mining_alternatives_can_lower_main_ring(self):
        for kind in ("looted", "merchant", "harvested", "crafted"):
            with self.subTest(kind=kind):
                rows = near_spawn_fixture()
                by_key = {r["entity_key"]: r["semantic"] for r in rows}
                if kind == "looted":
                    by_key["tag"]["relationships"].append(link("eligible-item", "ore"))
                elif kind == "merchant":
                    by_key["merchant"]["facts"]["BiomeName"] = "Desert"
                    by_key["merchant"]["relationships"].append(link("merchant-stock-item", "ore"))
                elif kind == "harvested":
                    by_key["top1"]["relationships"].append(link("vegetation", "ore-prop"))
                    rows.append(row("ore-prop", "building-piece", {"_Collectable_Info": {"_Items": [{"_RandomRate": 1}]}},
                        [link("collectible-item", "ore", "/_Collectable_Info/_Items/0/_IconRef")]))
                else:
                    rows.append(recipe("other-ore", "ore", [("loot", 1)]))
                result = graph(rows)
                for key in ("ore", "gun", "scrap"):
                    self.assertEqual(result["items"][key]["earliest_ring"], 1, key)
                    self.assertEqual(result["items"][key]["main_ring"], 1, key)

    def test_unlocated_sources_remain_listed_without_seeding_either_ring(self):
        rows = fixture()
        by_key = {r["entity_key"]: r["semantic"] for r in rows}
        by_key["top0"]["relationships"] = [link("biome", "forest")]
        by_key["top1"]["relationships"] = [link("biome", "desert")]
        by_key["merchant"]["facts"]["BiomeName"] = "Unknown"
        next(r for r in rows if r["entity_key"] == "box")["provenance"]["source_id"] = "generic.bundle::0#1"
        result = graph(rows)
        for key in ("wood", "ore", "loot", "stock", "fiber"):
            item = result["items"][key]
            self.assertTrue(item["sources"], key)
            self.assertEqual({source["biome"] for source in item["sources"]}, {None}, key)
            self.assertIsNone(item["earliest_ring"], key)
            self.assertIsNone(item["main_ring"], key)
            self.assertFalse(item["near_spawn"], key)
        for key in ("station", "gun", "scrap", "seed-a", "seed-b"):
            self.assertIsNone(result["items"][key]["earliest_ring"], key)
            self.assertIsNone(result["items"][key]["main_ring"], key)

    def test_mining_normalizes_each_block_and_counts_unresolved_weights(self):
        rows = fixture()
        blocks = next(r for r in rows if r["entity_key"] == "blocks")["semantic"]
        blocks["facts"]["_BlockInfo"] = [
            {"CollectableItems": [{"RandomRate": 2}, {"RandomRate": 6}]},
            {"CollectableItems": [{"RandomRate": 0.3}, {"RandomRate": 0.2}]}]
        blocks["relationships"] += [link("mineable-item", "ore", "/_BlockInfo/1/CollectableItems/0"),
                                     link("mineable-item", "ore", "/_BlockInfo/1/CollectableItems/1")]
        result = graph(rows)
        self.assertEqual({r["chance_per_hit"] for r in result["biomes"]["desert"]["mined"]}, {0.25, 0.5})

    def test_unknown_owner_and_missing_ingredient_never_become_free_recipes(self):
        rows = fixture() + [recipe("ownerless", "missing", [], "absent-owner")]
        gun = next(r for r in rows if r["entity_key"] == "build-gun")
        gun["semantic"]["relationships"] = [r for r in gun["semantic"]["relationships"]
                                                  if r["field"] != "/matsData/0/matIcon"]
        result = graph(rows)
        self.assertIsNone(result["items"]["missing"]["earliest_ring"])
        self.assertIsNone(result["items"]["gun"]["earliest_ring"])
        self.assertIsNone(result["items"]["scrap"]["earliest_ring"])

    def test_bench_name_fallback_is_labelled_and_exact_link_takes_precedence(self):
        rows = fixture()
        by_key = {r["entity_key"]: r for r in rows}
        by_key["bench"]["provenance"]["game_objects"] = ["child#2"]
        by_key["bench-prefab"]["semantic"]["name"] = "bench"
        result = graph(rows)
        self.assertNotIn("bench", result["gaps"]["unresolved_benches"])
        self.assertEqual(result["items"]["gun"]["earliest_ring"], 1)
        self.assertEqual(result["benches"]["bench"]["evidence"], "name-matched")
        self.assertEqual(result["benches"]["bench"]["model"], "bench-prefab")
        by_key["bench-prefab"]["semantic"]["relationships"] = [link("cataloged-component", "bench")]
        self.assertEqual(graph(rows)["benches"]["bench"]["evidence"], "extracted")

    def test_bench_name_ambiguity_scope_and_unreachable_material_reasons(self):
        rows = fixture()
        by_key = {r["entity_key"]: r for r in rows}
        by_key["bench"]["provenance"] = {"source_id": "bundle-a::1#2"}
        by_key["bench-prefab"]["semantic"]["name"] = "bench"
        by_key["bench-prefab"]["provenance"] = {"source_id": "bundle-b::1#3"}
        self.assertEqual(graph(rows)["benches"]["bench"]["gap_reason"], "no-construction-item-join")
        by_key["bench-prefab"]["provenance"]["source_id"] = "bundle-a::1#3"
        self.assertEqual(graph(rows)["benches"]["bench"]["evidence"], "name-matched")
        rows += [row("station2", "item", links=[link("model", "bench-prefab")]),
                 recipe("build-bench2", "station2", [("wood", 1)])]
        self.assertEqual(graph(rows)["benches"]["bench"]["gap_reason"], "ambiguous-construction-item")
        rows = fixture()
        next(r for r in rows if r["entity_key"] == "tree")["semantic"]["relationships"] = []
        bench = graph(rows)["benches"]["bench"]
        self.assertEqual(bench["built_by_recipe"], "build-bench")
        self.assertEqual(bench["gap_reason"], "construction-item-unreachable")

    def test_bench_output_item_name_fallback_and_recipe_selection(self):
        rows = fixture()
        by_key = {r["entity_key"]: r for r in rows}
        by_key["station"]["semantic"].update(name="bench", relationships=[])
        rows += [recipe("a-late-bench", "station", [("ore", 1)])]
        bench = graph(rows)["benches"]["bench"]
        self.assertEqual(bench["built_by_recipe"], "build-bench")
        self.assertEqual(bench["evidence"], "name-matched")
        self.assertIsNone(bench["model"])

    def test_grass_coverage_and_missing_coverage_code_fallback(self):
        rows = fixture()
        rows += [row("grass0", "asset", name="PlantsGrass_B"), row("grass1", "asset", name="GrassVar1"),
                 recipe("fiber-product", "missing", [("fiber", 1)])]
        by_key = {r["entity_key"]: r for r in rows}
        by_key["top0"]["semantic"]["relationships"].append(link("vegetation", "grass0"))
        by_key["top1"]["semantic"]["relationships"].append(link("vegetation", "grass1"))
        result = graph(rows)
        fiber = result["items"]["fiber"]
        self.assertEqual(fiber["earliest_ring"], 0)
        self.assertEqual(fiber["biomes"], ["desert", "forest"])
        self.assertEqual({source["evidence"] for source in fiber["sources"]}, {"grass in every biome's vegetation"})
        self.assertEqual(result["items"]["missing"]["earliest_ring"], 0)
        by_key["top0"]["semantic"]["relationships"] = [link("biome", "forest")]
        fiber = graph(rows)["items"]["fiber"]
        self.assertEqual(fiber["earliest_ring"], 1)
        self.assertEqual(fiber["main_ring"], 1)
        self.assertEqual(fiber["biomes"], ["desert"])
        self.assertEqual({source["evidence"] for source in fiber["sources"]},
                         {"grass in biome's vegetation", "biome-independent-grass-cutting"})
        by_key["tools"]["semantic"]["relationships"] = []
        self.assertIsNone(graph(rows)["items"]["fiber"]["earliest_ring"])

    def test_shared_and_exclusive_loot_keep_distinct_biome_lists(self):
        rows = fixture() + [row("common", "item"), row("solar", "item"), row("disabled", "item")]
        rows += [row("forest-box", "loot-source", links=[link("uses-loot-table", "shared")],
                     source_id="bundles/forest_crate_assets_all.bundle::0#1"),
                 row("desert-box", "loot-source", links=[link("uses-loot-table", "shared"), link("uses-loot-table", "special")],
                     source_id="bundles/desert_crate_assets_all.bundle::0#1"),
                 row("shared", "loot-table", {"rates": [{"_spawnLootTag": "Shared", "_spawnRateRange": 0.2}]}),
                 row("special", "loot-table", {"rates": [{"_spawnLootTag": "Desert", "_spawnRateRange": 0.3},
                                                          {"_spawnLootTag": "Zero", "_spawnRateRange": 0}]}),
                 row("shared-tag", "loot-tag", {"tag": "Shared"}, [link("eligible-item", "common")]),
                 row("special-tag", "loot-tag", {"tag": "Desert"}, [link("eligible-item", "solar")]),
                 row("zero-tag", "loot-tag", {"tag": "Zero"}, [link("eligible-item", "disabled")])]
        result = graph(rows)["items"]
        self.assertEqual(result["common"]["loot_biomes"], ["desert", "forest"])
        self.assertEqual(result["solar"]["loot_biomes"], ["desert"])
        self.assertEqual(result["solar"]["biomes"], ["desert"])
        self.assertFalse(result["solar"]["has_unmapped_loot"])
        self.assertTrue(result["loot"]["has_unmapped_loot"])
        self.assertEqual(result["disabled"]["sources"], [])

    def test_six_bundle_aliases_and_longest_token_precedence(self):
        names = ("Forest", "Base", "Winter_Forest", "Winter_Town", "Desert", "Desert_Rocky", "Mountain")
        rows = [row(name, "biome") for name in names]
        rows += [row("part", "item"), row("tag", "loot-tag", {"tag": "part"}, [link("eligible-item", "part")]),
                 row("table", "loot-table", {"rates": [{"_spawnLootTag": "part", "_spawnRateRange": 1}]})]
        bundles = {"sh_forest_ab_airport": "Forest", "sh_forest_dinner": "Forest", "zb_baseterrain": "Base",
                   "zb_forest": "Forest", "zb_winterforest": "Winter_Forest", "zb_wintertown": "Winter_Town",
                   "shc_desert_rocky": "Desert_Rocky", "sh_mountain_forest": "Mountain"}
        for bundle in bundles:
            rows.append(row(bundle, "loot-source", links=[link("uses-loot-table", "table")],
                            source_id=f"bundles/{bundle}_assets_all.bundle::0#1"))
        result = graph(rows)
        self.assertEqual(result["gaps"]["unmapped_container_bundles"], [])
        self.assertEqual({source["via"]: source["biome"] for source in result["items"]["part"]["sources"]}, bundles)

    def test_terrain_bundle_places_harvest_but_ground_debris_and_other_bundles_do_not(self):
        rows = fixture() + [row("warzone", "biome", name="Warzone"), row("rebar", "item")]
        bundles = {
            "standing": "terrain_war_zone_assets_all",
            "collapse": "ground_debris_assets_all",
            "other": "props_war_zone_assets_all",
            "generic": "terrain_unknown_assets_all",
        }
        for identity, bundle in bundles.items():
            rows.append(row(identity, "building-piece", {"_Collectable_Info": {"_Items": [{"_RandomRate": 1}]}},
                            [link("collectible-item", "rebar", "/_Collectable_Info/_Items/0/_IconRef")],
                            source_id=f"bundles/{bundle}.bundle::0#1"))
        result = graph(rows)
        sources = {source["via"]: source for source in result["items"]["rebar"]["sources"]}
        self.assertEqual({via: source["biome"] for via, source in sources.items()},
                         {"standing": "warzone", "collapse": None, "other": None, "generic": None})
        self.assertEqual(sources["standing"]["evidence"], "inferred-from-bundle-name")
        self.assertEqual(result["biomes"]["warzone"]["harvest"], [{"item": "rebar", "source": "standing"}])

    def test_zero_chances_and_unknown_biome_do_not_seed_cycles(self):
        rows = fixture()
        by_key = {r["entity_key"]: r for r in rows}
        by_key["merchant"]["semantic"]["facts"]["BiomeName"] = "Unknown"
        by_key["blocks"]["semantic"]["facts"]["_BlockInfo"][0]["CollectableItems"][0]["RandomRate"] = 0
        by_key["tree"]["semantic"]["facts"]["_Collectable_Info"]["_Items"][0]["_RandomRate"] = 0
        result = graph(rows)
        for key in ("seed-a", "seed-b", "ore", "wood", "gun"):
            self.assertIsNone(result["items"][key]["earliest_ring"], key)
        self.assertEqual(result["items"]["ore"]["sources"], [])

    def test_lower_alternative_propagates_through_cycles_and_benches(self):
        rows = fixture() + [recipe("alternate-ore", "ore", [("seed-a", 1)])]
        result = graph(rows)
        for key in ("ore", "gun", "scrap"):
            self.assertEqual(result["items"][key]["earliest_ring"], 0)
            self.assertEqual(result["items"][key]["main_ring"], 0)

    def test_empty_duplicate_and_conflicting_worlds(self):
        result = graph([])
        self.assertEqual(result, {"rings": [], "biomes": {}, "items": {}, "recipes": {}, "benches": {},
            "near_spawn": {"biome": None, "mined": [], "container_loot": [], "harvest": []},
            "gaps": {"items_without_source": [], "unresolved_benches": [], "unmapped_container_bundles": []}})
        with self.assertRaisesRegex(ValueError, "Duplicate snapshot entity"):
            graph([row("a", "item"), row("a", "item")])
        rows = fixture()
        world = copy.deepcopy(next(r for r in rows if r["entity_key"] == "world"))
        world["entity_key"] = "world2"
        self.assertEqual(graph(rows + [world]), graph(rows))
        world["semantic"]["facts"]["BigTerraWidth"] = 50
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            graph(rows + [world])


if __name__ == "__main__":
    unittest.main()
