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
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
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
        self.assertEqual(spy.call_count, 2)
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
        self.assertIn("/loot/entry/" + self.fixture.c + "/?snapshot=" + self.fixture.new["snapshot_id"], markdown)
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

    def test_history_existing_packs_and_repeat_identity(self):
        # History rows need a recorded game version; unversioned captures are left out.
        for run, version in ((self.fixture.old, "0.8.315"), (self.fixture.new, "0.8.316")):
            path = self.root / "snapshots" / (run["snapshot_id"] + ".json")
            receipt = json.loads(path.read_bytes())
            receipt["game_version"] = version
            path.write_bytes(json_bytes(receipt))
        self.fixture.runs = [self.fixture.old]
        old_site, _ = self.build()
        old_index = self.index(old_site, self.fixture.old)
        self.assertEqual(len(old_index["history"]), 1)
        self.assertIsNone(old_index["history"][0]["changes"])
        self.fixture.runs = [self.fixture.new, self.fixture.old]
        site, result = self.build()
        self.assertEqual(old_index, self.index(site, self.fixture.old))
        for topic in ("hub", "items", "loot"):
            old = self.fixture.index(old_site, topic, self.fixture.old)
            new = self.fixture.index(site, topic, self.fixture.old)
            for kind in ("entries", "semantics", "provenance", "cards", "player", "backlinks", "search"):
                self.assertEqual(old[kind], new[kind])
                for ref in old[kind]:
                    self.assertEqual((old_site / topic / ref["path"]).read_bytes(), (site / topic / ref["path"]).read_bytes())
        before = {path.relative_to(site): path.read_bytes() for path in site.rglob("*") if path.is_file()}
        repeated, again = self.build()
        self.assertTrue(again["reused"])
        self.assertEqual(result["candidate_id"], again["candidate_id"])
        self.assertEqual(before, {path.relative_to(repeated): path.read_bytes() for path in repeated.rglob("*") if path.is_file()})

    def test_multiversion_hub_index_repeats_identically(self):
        runs = []
        for build in (100, 110, 200, 210, 300, 310, 400, 410):
            run = self.fixture.make_run(str(build), [self.fixture.observation(self.fixture.a, "Item")])
            path = self.root / "snapshots" / (run["snapshot_id"] + ".json")
            receipt = json.loads(path.read_bytes())
            receipt["game_version"] = f"0.8.{310 + build // 100}"
            path.write_bytes(json_bytes(receipt))
            runs.append(run)
        self.fixture.runs = list(reversed(runs))
        site, first = self.build()
        index = self.index(site, runs[-1])
        self.assertEqual([row["build_id"] for row in index["history"]], ["410", "310", "210", "110"])
        self.assertTrue(all(row["changes"] == {"new": 0, "changed": 0, "removed": 0,
            "topics": {"hub": {"new": 0, "changed": 0, "removed": 0},
                       "items": {"new": 0, "changed": 0, "removed": 0},
                       "loot": {"new": 0, "changed": 0, "removed": 0}}}
            for row in index["history"][:-1]))
        self.assertIsNone(index["history"][-1]["changes"])
        self.assertFalse(any("history" in self.fixture.index(site, topic, runs[-1])
                             for topic in ("items", "loot")))
        index_bytes = (site / "hub/snapshots" / (runs[-1]["snapshot_id"] + ".json")).read_bytes()
        self.assertLess(len(index_bytes), reader.DEFAULT_PACK_BYTES)
        without_charts = {key: value for key, value in index.items() if key not in {"history", "biomes"}}
        self.assertLess(len(index_bytes) - len(packs.compact(without_charts)), 4096)
        before = {path.relative_to(site): path.read_bytes() for path in site.rglob("*") if path.is_file()}
        repeated, second = self.build()
        self.assertTrue(second["reused"])
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(before, {path.relative_to(repeated): path.read_bytes() for path in repeated.rglob("*") if path.is_file()})

    def test_history_skips_captures_without_a_game_version(self):
        receipts = {"new": {"game_version": "0.8.316", "steam": {"build_id": "300"}},
                    "unknown": {"game_version": None, "steam": {"build_id": "200"}},
                    "old": {"game_version": "0.8.315", "steam": {"build_id": "200"}}}
        runs = [{"snapshot_id": name} for name in ("new", "unknown", "old")]
        state = {"e-" + "a" * 32: {"status": "present", "descriptor": {"topic": "items"}, "revision_id": "r"}}
        with patch.object(reader.snapshots, "read", side_effect=lambda root, key: receipts[key]),                 patch.object(reader.history, "load_state", side_effect=lambda root, run: state):
            rows = reader.history_rows(self.root, runs, state, ("items",))
        self.assertEqual([row["snapshot_id"] for row in rows], ["new", "old"])

    def test_four_version_history_uses_latest_build_then_capture_order(self):
        keys = {letter: "e-" + letter * 32 for letter in "abcdef"}
        captures = [
            ("v0-a", "0.8.310", 10, None, None), ("v0-b", "0.8.310", 11, None, None),
            ("v1-a", "0.8.311", 100, None, None),
            ("v1-b", "0.8.311", 110, "2026-09-01", {"a": ("items", "a1"), "b": ("items", "b1"), "c": ("loot", "c1")}),
            ("v2-a", "0.8.312", 200, None, None),
            ("v2-b", "0.8.312", 210, None, {"a": ("items", "a2"), "c": ("loot", "c1"), "d": ("loot", "d1")}),
            ("v3-a", "0.8.313", 300, None, None),
            ("v3-b", "0.8.313", 310, "2026-09-03T14:00:00Z", {"a": ("items", "a2"), "d": ("loot", "d2"), "e": ("items", "e1")}),
            ("v4-a", "0.8.314", 400, None, None),
            ("v4-b", "0.8.314", 410, None, None),
            ("v4-c", "0.8.314", 410, "2026-09-04", {"a": ("items", "a3"), "e": ("items", "e1"), "f": ("loot", "f1")}),
        ]
        runs = [{"snapshot_id": name} for name, *_ in reversed(captures)]
        receipts, states = {}, {}
        for name, version, build, captured, present in captures:
            receipts[name] = {"game_version": version, "steam": {"build_id": str(build)}}
            if captured:
                receipts[name]["captured_at" if name == "v3-b" else "captured"] = captured
            states[name] = {keys[key]: {"status": "present", "descriptor": {"topic": topic}, "revision_id": revision}
                            for key, (topic, revision) in (present or {"b": ("items", "decoy")}).items()}
            states[name]["e-" + "0" * 32] = {"status": "not-present", "descriptor": {"topic": "items"}, "revision_id": "old"}
        with patch.object(reader.snapshots, "read", side_effect=lambda root, key: receipts[key]), \
                patch.object(reader.history, "load_state", side_effect=lambda root, run: states[run["snapshot_id"]]):
            rows = reader.history_rows(self.root, runs, states[runs[0]["snapshot_id"]], ("items", "loot"))
            older_rows = reader.history_rows(self.root, runs[3:], states[runs[3]["snapshot_id"]], ("items", "loot"))
        self.assertEqual([row["snapshot_id"] for row in rows], ["v4-c", "v3-b", "v2-b", "v1-b"])
        self.assertEqual([row["snapshot_id"] for row in older_rows], ["v3-b", "v2-b", "v1-b", "v0-b"])
        self.assertEqual([row["captured"] for row in rows], ["2026-09-04", "2026-09-03", None, "2026-09-01"])
        self.assertEqual([row["total"] for row in rows], [3, 3, 3, 3])
        self.assertEqual([row["topics"] for row in rows], [
            {"items": 2, "loot": 1}, {"items": 2, "loot": 1},
            {"items": 1, "loot": 2}, {"items": 2, "loot": 1}])
        self.assertEqual([row["changes"] for row in rows], [
            {"new": 1, "changed": 1, "removed": 1, "topics": {
                "items": {"new": 0, "changed": 1, "removed": 0},
                "loot": {"new": 1, "changed": 0, "removed": 1}}},
            {"new": 1, "changed": 1, "removed": 1, "topics": {
                "items": {"new": 1, "changed": 0, "removed": 0},
                "loot": {"new": 0, "changed": 1, "removed": 1}}},
            {"new": 1, "changed": 1, "removed": 1, "topics": {
                "items": {"new": 0, "changed": 1, "removed": 1},
                "loot": {"new": 1, "changed": 0, "removed": 0}}}, None])

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
