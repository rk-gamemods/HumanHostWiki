"""Hub documents, search and counts use each snapshot's player context."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_reader
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
        self.fixture.runs = [self.fixture.old]
        old_site, _ = self.build()
        old_index = self.index(old_site, self.fixture.old)
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
