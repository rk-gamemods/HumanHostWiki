"""Hub documents, search and counts use each snapshot's player context."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_reader
import test_guide_queries
from wikibuild import guide_queries, packs, reader
from wikibuild.storage import ContractError, digest, json_bytes


class HubProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_reader.ReaderTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.setUp()
        self.root = self.fixture.root
        self.project = self.fixture.project
        self.project["relationships"] = [{"from": "items", "to": "loot", "label": "Found in"}]
        self.site = {"guides": ["second", "broken", "first"], "topics": {"items": {"short": "Items"}}}
        self.site_path = self.root / "presentation/site.json"
        self.site_path.write_bytes(json_bytes(self.site))
        (self.root / "guides").mkdir()
        for identity in self.site["guides"]:
            spec = {"id": identity, "title": identity.title(), "dek": "A fixture guide", "sections": [
                {"id": "list", "heading": "Entries", "blocks": [
                    {"type": "list", "query": "missing" if identity == "broken" else "fixture", "item": "{link}"}]},
                {"id": "sources", "heading": "Sources", "blocks": [
                    {"type": "sources", "template": "Captured {build_id}; {game_version}."}]}]}
            (self.root / "guides" / (identity + ".json")).write_bytes(json_bytes(spec))
        self.dangling = "e-" + "f" * 32
        def query(context, scope):
            return [{"link": {"text": name["name"], "entity": key}} for key, name in context["names"].items()] + [
                {"link": {"text": "Unavailable source", "entity": self.dangling}}]
        self.queries = patch.dict(guide_queries.QUERIES, {"fixture": query})
        self.queries.start()
        self.addCleanup(self.queries.stop)

    def build(self, **kwargs):
        return self.fixture.build(**kwargs)

    def index(self, site, run):
        return self.fixture.index(site, "hub", run)

    def test_hub_contract_guides_errors_drops_and_markdown(self):
        with patch.object(guide_queries, "build_context", wraps=guide_queries.build_context) as spy:
            site, _ = self.build()
        self.assertEqual(spy.call_count, 1)
        config = json.loads((site / "hub/reader.json").read_bytes())
        self.assertEqual(config["site"], self.site)
        self.assertEqual(config["relationships"], self.project["relationships"])
        receipt = reader.verify(site)
        self.assertEqual(receipt["inputs"]["site"], digest(self.site_path.read_bytes()))
        for run, version in zip(self.fixture.runs, receipt["versions"]):
            index = self.index(site, run)
            self.assertEqual([ref["id"] for ref in index["guides"]], ["second", "first"])
            self.assertEqual(version["guides"]["count"], 2)
            self.assertEqual(version["guides"]["dropped_links"], 2)
            # ADR-0002 §5: the normal build reports scenery no harvest rule names.
            self.assertEqual(version["guides"]["other_scenery"], sorted(set(version["guides"]["other_scenery"])))
            self.assertEqual(len(version["guides"]["errors"]), 1)
            self.assertEqual(version["guides"]["errors"][0]["id"], "broken")
            self.assertIn("unknown query 'missing'", version["guides"]["errors"][0]["error"])
            search = reader.load_maps(site / "hub", index["search"])
            expected = {self.fixture.a, self.fixture.c if run is self.fixture.new else self.fixture.b}
            self.assertEqual(search.keys(), expected)
            self.assertTrue(all(set(row) == {"entity_key", "name", "kind", "topic"} for row in search.values()))
            self.assertEqual(sum(value["total"] for value in index["topic_counts"].values()), 2)
            for ref in index["guides"]:
                self.assertEqual(set(ref), {"id", "title", "dek", "path", "sha256", "bytes"})
                raw = (site / "hub" / ref["path"]).read_bytes()
                self.assertEqual((digest(raw), len(raw)), (ref["sha256"], ref["bytes"]))
                pack = json.loads(raw)
                self.assertEqual(set(pack), {"document", "links"})
                self.assertEqual(pack["links"].keys(), expected)
                runs = list(reader.document_runs(pack["document"]))
                self.assertIn({"text": "Unavailable source"}, runs)
                self.assertNotIn(self.dangling, {value.get("entity") for value in runs})
                self.assertEqual(pack["document"]["snapshot"]["build_id"], run["snapshot_id"].split("-")[1])
        newest = self.index(site, self.fixture.new)
        self.assertEqual(newest["biomes"], [])
        # The fixture's captures record no game version, so none can be placed among versions.
        self.assertEqual(newest["history"], [])
        self.assertEqual(newest["topic_counts"], {"hub": {"total": 0, "kinds": {}},
            "items": {"total": 1, "kinds": {"item": 1}}, "loot": {"total": 1, "kinds": {"loot-source": 1}}})
        markdown = (site / "hub/reference/guides/second.md").read_text()
        self.assertIn("/loot/entry/" + self.fixture.c + "/)", markdown)
        self.assertNotIn("snapshot=", markdown)
        self.assertIn("Unavailable source", markdown)
        self.assertNotIn(self.dangling, markdown)
        self.assertFalse((site / "hub/reference/guides/broken.md").exists())

    def test_cross_topic_search_names_ranges_and_absent_entries(self):
        keys = ["e-" + f"{number:032x}" for number in range(20)]
        observations = [self.fixture.observation(key, "Named_Item " + str(number),
                        "loot-source" if number % 2 else "item", "loot" if number % 2 else "items")
                        for number, key in enumerate(keys)]
        run = self.fixture.make_run("300", observations, absent={self.fixture.b: "not-present"})
        self.fixture.runs = [run]
        site, _ = self.build(max_pack_bytes=1024)
        index = self.index(site, run)
        self.assertGreater(len(index["search"]), 1)
        search = reader.load_maps(site / "hub", index["search"])
        self.assertEqual(set(search), set(keys))
        for key, row in search.items():
            self.assertNotEqual(row["name"], row["source_name"])
            self.assertEqual(row["entity_key"], key)
        index["search"][0]["first"] = "bad"
        with self.assertRaisesRegex(ContractError, "membership differs"):
            reader.load_maps(site / "hub", index["search"])

    def set_version(self, run, version):
        path = self.root / "snapshots" / (run["snapshot_id"] + ".json")
        receipt = json.loads(path.read_bytes())
        receipt["game_version"] = version
        path.write_bytes(json_bytes(receipt))

    def entry(self, snapshot, version, build, count=1, previous=None, added=0, changed=0, removed=0, captured=None):
        row = lambda number: {"entity_key": f"e-{number:032x}", "name": "Row", "kind": "item"}
        return {"snapshot_id": snapshot, "game_version": version, "build_id": str(build), "count": count,
                **({"captured": captured} if captured else {}), "previous": previous,
                **({"added": [row(n) for n in range(added)], "changed": [row(n) for n in range(changed)],
                    "removed": [{**row(n), "status": "not-present"} for n in range(removed)]} if previous else {})}

    def write_logs(self, logs):
        folder = self.root / "changes"
        folder.mkdir(exist_ok=True)
        for topic, versions in logs.items():
            (folder / (topic + ".json")).write_bytes(json_bytes({"schema_version": 1, "topic": topic, "versions": versions}))

    def test_history_comes_from_change_logs_and_repeats_identically(self):
        self.set_version(self.fixture.new, "0.8.316")
        previous = {"snapshot_id": self.fixture.old["snapshot_id"], "game_version": "0.8.315", "build_id": "100"}
        self.write_logs({"items": [self.entry(self.fixture.new["snapshot_id"], "0.8.316", 200, previous=previous, changed=1, removed=1),
                                   self.entry(self.fixture.old["snapshot_id"], "0.8.315", 100, count=2)]})
        site, result = self.build()
        index = self.index(site, self.fixture.new)
        self.assertEqual(["200", "100"], [row["build_id"] for row in index["history"]])
        # The current row counts its own state, not the logged count.
        self.assertEqual(2, index["history"][0]["total"])
        self.assertEqual({"new": 0, "changed": 1, "removed": 1},
                         {field: index["history"][0]["changes"][field] for field in ("new", "changed", "removed")})
        self.assertEqual({"hub": 0, "items": 2, "loot": 0}, index["history"][1]["topics"])
        self.assertIsNone(index["history"][1]["changes"])
        self.assertFalse(any("history" in self.fixture.index(site, topic, self.fixture.new) for topic in ("items", "loot")))
        before = {path.relative_to(site): path.read_bytes() for path in site.rglob("*") if path.is_file()}
        repeated, again = self.build()
        self.assertTrue(again["reused"])
        self.assertEqual(result["candidate_id"], again["candidate_id"])
        self.assertEqual(before, {path.relative_to(repeated): path.read_bytes() for path in repeated.rglob("*") if path.is_file()})

    def test_four_version_history_keeps_newest_capture_per_version_and_skips_unversioned(self):
        self.set_version(self.fixture.new, "0.8.320")
        entries, previous = [], None
        for build in (10, 11, 12, 20, 21, 30, 31, 40, 41):
            snapshot = f"build-{build}-{'b' * 12}"
            version = None if build == 12 else f"0.8.{310 + build // 10}"
            entries.insert(0, self.entry(snapshot, version, build, previous=previous, added=1,
                                         captured="2026-09-0" + str(build // 10)))
            previous = {"snapshot_id": snapshot, "game_version": version, "build_id": str(build)}
        self.write_logs({"items": entries, "loot": [dict(entries[0], count=4)]})
        site, _ = self.build()
        history_rows = self.index(site, self.fixture.new)["history"]
        self.assertEqual(["200", "41", "31", "21"], [row["build_id"] for row in history_rows])
        self.assertEqual([None, "2026-09-04", "2026-09-03", "2026-09-02"], [row["captured"] for row in history_rows])
        self.assertEqual({"hub": 0, "items": 1, "loot": 4}, history_rows[1]["topics"])
        self.assertEqual({"new": 2, "changed": 0, "removed": 0}, {field: history_rows[1]["changes"][field]
                                                                 for field in ("new", "changed", "removed")})
        self.assertIsNone(history_rows[0]["changes"])

    def test_unversioned_current_capture_is_left_out_of_history(self):
        self.write_logs({"items": [self.entry("build-50-" + "c" * 12, "0.8.300", 50)]})
        site, _ = self.build()
        self.assertEqual(["50"], [row["build_id"] for row in self.index(site, self.fixture.new)["history"]])

    def test_biome_counts_match_complete_progression_queries(self):
        context = test_guide_queries.context()
        rows = reader.biome_rows(context)
        rings = guide_queries.QUERIES["rings"](context, {})
        self.assertEqual([(row["number"], row["index"]) for row in rows], [(1, 0), (2, 1)])
        for row, ring in zip(rows, rings):
            self.assertEqual(row["biome"], {"entity": ring["biome"]["entity"], "name": ring["biome"]["text"]})
            for field in ("new_materials", "new_recipes", "new_benches", "exclusive_loot"):
                self.assertEqual(row[field], len(guide_queries.QUERIES["ring." + field](context, ring)))
        self.assertGreater(rows[0]["new_materials"], 3)
        combined = [{**rings[0], "biome": [rings[0]["biome"], rings[1]["biome"]]}]
        with patch.dict(guide_queries.QUERIES, {"rings": lambda context, scope: combined}):
            multi = reader.biome_rows(context)
        self.assertEqual(multi[0]["biome"], [
            {"entity": rings[0]["biome"]["entity"], "name": rings[0]["biome"]["text"]},
            {"entity": rings[1]["biome"]["entity"], "name": rings[1]["biome"]["text"]}])

    def test_design_relationships_and_specs_invalidate_candidate(self):
        _, previous = self.build()
        for change in ("site", "relationships", "spec"):
            if change == "site":
                self.site["home"] = {"title": "Changed"}
                self.site_path.write_bytes(json_bytes(self.site))
            elif change == "relationships":
                self.project["relationships"][0]["label"] = "Changed"
            else:
                path = self.root / "guides/first.json"
                spec = json.loads(path.read_bytes())
                spec["title"] = "Changed title"
                path.write_bytes(json_bytes(spec))
            _, changed = self.build()
            self.assertNotEqual(previous["candidate_id"], changed["candidate_id"])
            previous = changed

    def test_changed_design_during_generation_does_not_promote(self):
        original = reader.project_snapshot
        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            self.site_path.write_bytes(json_bytes({**self.site, "changed": True}))
            return result
        with patch.object(reader, "project_snapshot", side_effect=mutate):
            with self.assertRaisesRegex(ContractError, "inputs changed during generation"):
                self.build()
        self.assertFalse((self.root / ".local/reader-latest.json").exists())


if __name__ == "__main__":
    unittest.main()
