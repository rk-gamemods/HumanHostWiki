"""Player joins remain snapshot-local and independent of semantic revisions."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_reader
from wikibuild import guide_queries, model, packs, presentation, reader
from wikibuild.storage import ContractError, digest, json_bytes


class PlayerProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_reader.ReaderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.project = self.fixture.root, self.fixture.project
        self.project["repositories"][0]["owns"] = ["recipe", "workbench", "biome", "world-rule",
                                                   "resource-distribution", "combat-rule"]
        registry = json.loads(self.fixture.registry_path.read_bytes())
        registry["glossaries"]["item-category"] = {}
        self.fixture.registry_path.write_bytes(json_bytes(registry))

    def key(self, name):
        return "e-" + digest(name.encode())[:32]

    def link(self, predicate, target, field=""):
        return {"predicate": predicate, "targets": [self.key(target)], "field": field}

    def row(self, identity, name, kind="item", facts=None, links=()):
        row = self.fixture.observation(self.key(identity), name, kind, "items" if kind == "item" else "hub")
        row["semantic"].update(facts=facts or {}, relationships=list(links))
        row["revision_id"] = digest(json_bytes(row["semantic"]))
        return row

    def rows(self, count=13):
        rows = [self.row("ore", "Iron Ore"), self.row("plain", "Stone"),
                self.row("axe", "Stone Axe", links=[self.link("combat", "combat")]),
                self.row("combat", "Axe_Combo_2", "combat-rule"),
                self.row("biome", "Warzone", "biome"),
                self.row("hand", "Hand crafting", "workbench", {"_workbenchType": 0}),
                self.row("world", "Terrain", "world-rule", {"BigTerraWidth": 1000, "_BiomesWidthNum": 1,
                         "_BiomesLayers": [{}, {}, {}]}, [self.link("biome-terrain-prefab", "ground", "/_BiomesLayers/2/terrainTops/0")]),
                self.row("ground", "Ground", "resource-distribution",
                         {"_BlockInfo": [{"CollectableItems": [{"RandomRate": .2}]}]},
                         [self.link("biome", "biome"), self.link("mineable-item", "ore", "/_BlockInfo/0/CollectableItems/0")])]
        rows += [self.row(f"recipe-{n}", f"Axe Recipe {n}", "recipe",
                          {"craftNum": 1, "matsData": [{"matNeedCount": 1}]},
                          [self.link("produces-item", "axe"), self.link("defined-by", "hand"),
                           self.link("consumes-item-asset", "ore", "/matsData/0/matIcon")]) for n in range(count)]
        return rows

    def build(self, runs, **kwargs):
        return Path(reader.build(self.root, self.project, runs, **kwargs)["path"])

    def maps(self, site, run, topic="items"):
        index = self.fixture.index(site, topic, run)
        return index, {kind: reader.load_maps(site / topic, index[kind]) for kind in ("entries", "player", "search")}

    def test_player_payload_names_rings_links_limits_and_omission(self):
        observations = self.rows()
        run = self.fixture.make_run("300", observations)
        build_context = guide_queries.build_context
        with patch.object(guide_queries, "build_context", wraps=build_context) as context_spy:
            site = self.build([run])
        self.assertEqual(context_spy.call_count, 1)
        _, maps = self.maps(site, run)
        record = maps["entries"][self.key("ore")]
        player = maps["player"][record["player_id"]]
        self.assertEqual(record["player_id"], digest(packs.compact(player)))
        self.assertEqual(player["name"], "Iron Ore")
        self.assertEqual((player["name_source"], player["name_rule"]), ("game", None))
        self.assertEqual(player["ring"], {"earliest": 2, "main": 2, "label": "Biome 3 (War Zone)"})
        self.assertEqual(player["how"], [[{"text": "mined in "}, {"entity": self.key("biome"), "text": "War Zone"},
                                          {"text": " (20% of dig hits)"}]])
        self.assertEqual(player["used_in"]["count"], 13)
        self.assertEqual(len(player["used_in"]["items"]), 12)
        linked = {value["entity"] for value in [*(run for phrase in player["how"] for run in phrase),
                                                *player["used_in"]["items"]] if "entity" in value}
        self.assertEqual(set(player["links"]), linked)
        self.assertTrue(all(link["topic"] == "hub" for link in player["links"].values()))
        self.assertEqual(player["links"][self.key("biome")]["name"], "War Zone")
        self.assertNotIn("player_id", maps["entries"][self.key("plain")])
        self.assertNotIn("source_name", maps["search"][self.key("ore")])
        _, hub = self.maps(site, run, "hub")
        combat = hub["search"][self.key("combat")]
        self.assertEqual((combat["name"], combat["source_name"], combat["kind"]),
                         ("Stone Axe combat", "Axe_Combo_2", "combat-rule"))
        named = hub["player"][hub["entries"][self.key("combat")]["player_id"]]
        self.assertEqual((named["name_source"], named["name_rule"]), ("wiki", "combat-user"))
        for name in ("gameplay.py", "names.py", "guide_queries.py", "lint.py"):
            self.assertIn(name, reader.contract())

    def test_merchant_only_item_and_stock_packs_follow_snapshot_activity(self):
        registry = json.loads(self.fixture.registry_path.read_text(encoding="utf-8"))
        registry["features"] = {"about": "Capture switches", "merchants": {
            "manager_object": "Merchant_Mgr", "source_types": ["merchant"],
            "label": "Merchants", "evidence": "Merchant.My_Start"}}
        self.fixture.registry_path.write_bytes(json_bytes(registry))
        self.project["repositories"][2]["owns"].append("loot-table")

        def observations(active=None):
            stock = self.row("stock", "Flux")
            table = self.row("stock-table", "Forest merchant stock", "loot-table", {"BiomeName": "Forest"},
                             [self.link("merchant-stock-item", "stock"), self.link("defined-by", "config")])
            config = self.row("config", "Merchant config", "loot-source")
            rows = [stock, table, config, self.row("forest", "Forest", "biome")]
            if active is not None:
                rows.append(self.row("manager", "Merchant_Mgr", "loot-source",
                                     {"manager_object": "Merchant_Mgr", "manager_active": active}))
            for value in (table, config, *rows[4:]):
                value["semantic"]["topic"] = "loot"
                value["revision_id"] = digest(json_bytes(value["semantic"]))
            return rows

        inactive = self.fixture.make_run("300", observations(False))
        active = self.fixture.make_run("400", observations(True))
        missing = self.fixture.make_run("500", observations())
        site = self.build([inactive, active, missing])
        for run, expected in ((inactive, "merchants"), (active, None), (missing, "merchants")):
            _, items = self.maps(site, run)
            _, loot = self.maps(site, run, "loot")
            self.assertIn(self.key("stock"), items["search"])
            self.assertIn(self.key("stock-table"), loot["search"])
            for maps, name in ((items, "stock"), (loot, "stock-table"), (loot, "config")):
                entry = maps["entries"][self.key(name)]
                if expected is None and "player_id" not in entry:
                    continue
                player = maps["player"][entry["player_id"]]
                self.assertEqual(player.get("unreleased"), expected)
            if expected:
                self.assertEqual(items["player"][items["entries"][self.key("stock")]["player_id"]]["how"], [])
            else:
                self.assertTrue(items["player"][items["entries"][self.key("stock")]["player_id"]]["how"])
        manifest = json.loads((site / "candidate.json").read_bytes())
        reports = {version["build_id"]: version["guides"]["features"]["merchants"]
                   for version in manifest["versions"]}
        self.assertEqual(reports["300"]["status"], "inactive")
        self.assertEqual(reports["400"]["status"], "active")
        self.assertEqual(reports["500"]["status"], "manager-object-missing")

    def test_history_existing_kinds_and_repeat_bytes(self):
        old = self.fixture.make_run("300", self.rows(1))
        def legacy(models, registry, text, snapshot, **kwargs):
            return ({row["entity_key"]: {"name": row["semantic"]["name"]}
                     for row in model.rows(models)}, {})
        with patch.object(reader, "player_projection", side_effect=legacy):
            baseline = self.build([old], cache_root=self.root / ".local/legacy")
        first = self.build([old])
        new = self.fixture.make_run("400", self.rows(2))
        with patch.object(guide_queries, "build_context", wraps=guide_queries.build_context) as spy:
            second = self.build([new, old])
        self.assertEqual(spy.call_count, 2)
        for topic in ("hub", "items", "loot"):
            original = self.fixture.index(baseline, topic, old)
            earlier = self.fixture.index(first, topic, old)
            retained = self.fixture.index(second, topic, old)
            self.assertEqual(earlier, retained)
            for kind in ("semantics", "provenance", "cards", "backlinks"):
                self.assertEqual(original[kind], retained[kind])
                for ref in original[kind]:
                    self.assertEqual((baseline / topic / ref["path"]).read_bytes(), (second / topic / ref["path"]).read_bytes())
            before = reader.load_maps(baseline / topic, original["entries"])
            after = reader.load_maps(second / topic, retained["entries"])
            self.assertEqual(before, {key: {k: v for k, v in row.items() if k != "player_id"} for key, row in after.items()})
        _, old_maps = self.maps(second, old)
        _, new_maps = self.maps(second, new)
        ore = self.key("ore")
        self.assertEqual(old_maps["entries"][ore]["revision_id"], new_maps["entries"][ore]["revision_id"])
        self.assertNotEqual(old_maps["entries"][ore]["player_id"], new_maps["entries"][ore]["player_id"])
        before = {p.relative_to(second): p.read_bytes() for p in second.rglob("*") if p.is_file()}
        repeated = reader.build(self.root, self.project, [new, old])
        self.assertTrue(repeated["reused"])
        self.assertEqual(before, {p.relative_to(second): p.read_bytes() for p in second.rglob("*") if p.is_file()})

    def test_unchanged_player_reuses_one_shard_without_removed_owners(self):
        rows = self.rows(1) + [self.row("named", "Some_Internal")]
        old = self.fixture.make_run("300", rows)
        new = self.fixture.make_run("400", self.rows(1), absent={self.key("named"): "not-present"})
        site = self.build([new, old])
        old_index, old_maps = self.maps(site, old)
        new_index, new_maps = self.maps(site, new)
        removed = old_maps["entries"][self.key("named")]["player_id"]
        self.assertEqual({key: value for key, value in old_maps["player"].items() if key != removed}, new_maps["player"])
        self.assertEqual([ref for ref in old_index["player"] if ref["first"] != removed], new_index["player"])
        self.assertNotIn("player_id", new_maps["entries"][self.key("named")])

    def test_projection_rejects_construction_name_with_different_item_model(self):
        base = "7_5_Triangle_Small_1.4_Obsidian"
        item = self.row("material", "Obsidian", facts={"_Tag": "BuildMat"})
        item["provenance"]["evidence"] = [{"object": "tooltip-source"}]
        item["provenance"]["relationships"] = [
            {"predicate": "model", "target_source_ids": ["model-object"], "source_field": "/ModelRef"},
            {"predicate": "other", "target_source_id": "unrelated-object"}]
        tooltip = self.row("tooltip", base + "_Tooltip", "configuration")
        tooltip["provenance"].update(source_id="tooltip-source",
                                     component={"assembly": "Language", "class": "Tooltip_Text"})
        piece = self.row("piece", base, "building-piece")
        piece["semantic"]["name_status"] = "internal"
        piece["provenance"]["game_objects"] = ["different-object"]
        matching = self.row("matching-piece", base, "building-piece")
        matching["semantic"]["name_status"] = "internal"
        matching["provenance"]["game_objects"] = ["model-object"]
        run = self.fixture.make_run("300", [item, tooltip, piece, matching])
        registry = presentation.load(Path(reader.__file__).resolve().parents[1] / "presentation/fields.json")
        names, players = reader.player_projection(self.root / run["models"]["path"], registry, {}, run["snapshot_id"])
        self.assertNotEqual(names[piece["entity_key"]]["name"], "Obsidian")
        self.assertNotEqual(names[piece["entity_key"]]["rule"], "construction-item")
        self.assertEqual(names[matching["entity_key"]],
                         {"name": "Obsidian", "source": "wiki", "rule": "construction-item"})
        self.assertEqual(json.loads(players[piece["entity_key"]])["name"], names[piece["entity_key"]]["name"])

    def test_validation_requires_player_owners_and_references(self):
        run = self.fixture.make_run("300", self.rows(1))
        site = self.build([run])
        index, maps = self.maps(site, run)
        path = site / "items/snapshots" / (run["snapshot_id"] + ".json")
        for absent in (False, True):
            broken = {**index, "player": []}
            if absent:
                del broken["player"]
            path.write_bytes(packs.compact(broken))
            with self.assertRaisesRegex(ContractError, "player_id is missing"):
                reader.validate_snapshot(site, run["snapshot_id"], ["items", "hub", "loot"])
        for entry in maps["entries"].values():
            entry.pop("player_id", None)
        index["entries"] = packs.write({key: packs.compact(value) for key, value in maps["entries"].items()},
                                        reader.DEFAULT_PACK_BYTES, lambda name, data: (site / "items" / name).write_bytes(data))
        path.write_bytes(packs.compact(index))
        with self.assertRaisesRegex(ContractError, "player has no owning entry"):
            reader.validate_snapshot(site, run["snapshot_id"], ["items", "hub", "loot"])
        del index["player"]
        path.write_bytes(packs.compact(index))
        reader.validate_snapshot(site, run["snapshot_id"], ["items", "hub", "loot"])
