"""Snapshot validation, public imports and reader source fingerprints."""

import ast
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import weakref

from tests._support import fixture_dir
from wikibuild import packs, reader, reader_validation
from wikibuild.storage import ContractError, digest, json_bytes


class GuideTargetTests(unittest.TestCase):
    def test_targets_require_exact_present_names_topics_and_membership(self):
        present = {"a": {"name": "A", "topic": "items", "kind": "item"},
                   "b": {"name": "B", "topic": "loot"}}
        cases = [
            (set(), {}, False),
            ({"a"}, {"a": {"name": "A", "topic": "items"}}, False),
            ({"a", "b"}, {"b": {"topic": "loot", "name": "B"},
                          "a": {"name": "A", "topic": "items"}}, False),
            ({"a"}, {}, True),
            (set(), {"a": {"name": "A", "topic": "items"}}, True),
            ({"missing"}, {"missing": {"name": "Missing", "topic": "items"}}, True),
            ({"a"}, {"a": {"name": "Old A", "topic": "items"}}, True),
            ({"a"}, {"a": {"name": "A", "topic": "loot"}}, True),
            ({"a"}, {"a": {"name": "A"}}, True),
            ({"a"}, {"a": {"name": "A", "topic": "items", "extra": True}}, True),
        ]
        for linked, links, expected in cases:
            with self.subTest(linked=linked, links=links):
                before = json_bytes([sorted(linked), links, present])
                self.assertIs(reader_validation.guide_targets_leave_snapshot(linked, links, present), expected)
                self.assertEqual(json_bytes([sorted(linked), links, present]), before)

    def test_membership_and_unknown_targets_short_circuit_field_access(self):
        self.assertTrue(reader_validation.guide_targets_leave_snapshot(set(), {"a": {}}, {"a": {}}))
        self.assertTrue(reader_validation.guide_targets_leave_snapshot({"a"}, {"a": {}}, {}))
        with self.assertRaises(KeyError) as raised:
            reader_validation.guide_targets_leave_snapshot({"a"}, {"a": {}}, {"a": {}})
        self.assertEqual(raised.exception.args, ("name",))


class ReaderValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "reader-v")

    def shard(self, values):
        data = json_bytes(values)
        sha = digest(data)
        path = self.root / "data" / (sha + ".json")
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        keys = sorted(values)
        return {"path": f"data/{sha}.json", "sha256": sha, "bytes": len(data),
                "first": keys[0] if keys else "", "last": keys[-1] if keys else "", "count": len(keys)}

    def test_load_maps_merges_shards_and_accepts_no_shards(self):
        refs = [self.shard({"b": 2, "a": 1}), self.shard({"c": 3})]
        self.assertEqual(reader_validation.load_maps(self.root, refs), {"a": 1, "b": 2, "c": 3})
        self.assertEqual(reader_validation.load_maps(self.root, []), {})

    def test_load_maps_preserves_hash_and_membership_errors(self):
        ref = self.shard({"a": 1, "b": 2})
        cases = [([{**ref, "bytes": ref["bytes"] + 1}], "Reader shard hash differs"),
                 ([{**ref, "sha256": "0" * 64}], "Reader shard hash differs"),
                 ([{**ref, "first": "b"}], "Reader shard membership differs"),
                 ([{**ref, "last": "c"}], "Reader shard membership differs"),
                 ([{**ref, "count": 1}], "Reader shard membership differs"),
                 ([ref, ref], "Reader shard membership differs"),
                 ([self.shard({})], "Reader shard membership differs")]
        for refs, expected in cases:
            with self.subTest(refs=refs), self.assertRaises(ContractError) as raised:
                reader_validation.load_maps(self.root, refs)
            self.assertEqual(str(raised.exception), expected)

    def test_document_runs_preserves_order_and_treats_text_runs_as_leaves(self):
        first, second = {"text": "Heading", "entity": "a"}, {"text": "Cell"}
        leaf = {"text": "", "nested": {"text": "not visited"}}
        document = {"heading": first, "table": [[second, None, 5, "ignored"]],
                    "group": {"text": 5, "child": leaf}}
        runs = list(reader_validation.document_runs(document))
        self.assertEqual(runs, [first, second, leaf])
        self.assertIs(runs[0], first)
        self.assertIs(runs[2], leaf)
        self.assertEqual(list(reader_validation.document_runs(None)), [])

    def test_empty_snapshot_and_search_coverage_error(self):
        folder = self.root / "items/snapshots"
        folder.mkdir(parents=True)
        index = {kind: [] for kind in ("entries", "semantics", "provenance", "search", "backlinks")}
        path = folder / "fixture.json"
        path.write_bytes(json_bytes(index))
        self.assertEqual(reader_validation.validate_snapshot(self.root, "fixture", ["items"]), 0)
        self.assertEqual(reader_validation.validate_snapshot(self.root, "fixture", []), 0)
        ref = self.shard({"a": {}})
        data = (self.root / ref["path"]).read_bytes()
        (self.root / "items/data").mkdir()
        (self.root / "items" / ref["path"]).write_bytes(data)
        index["search"] = [ref]
        path.write_bytes(json_bytes(index))
        with self.assertRaises(ContractError) as raised:
            reader_validation.validate_snapshot(self.root, "fixture", ["items"])
        self.assertEqual(str(raised.exception), "Search coverage differs from snapshot entries")


class SnapshotPhaseTests(unittest.TestCase):
    setUp = ReaderValidationTests.setUp
    shard = ReaderValidationTests.shard

    def snapshot(self, change=None, change_index=None, change_guide=None):
        self.a, self.b, self.c = ("e-" + digit * 32 for digit in "abc")
        provenance = {"source": "fixture"}
        provenance_id = digest(packs.compact(provenance))
        item = {"relationships": [{"targets": [self.c], "technical_targets": [self.c]}]}
        biome = {"relationships": []}
        item_id, biome_id = digest(json_bytes(item)), digest(json_bytes(biome))
        player = {"name": "Wiki A", "how": [[{"text": "Biome", "entity": self.c}]],
                  "used_in": {"items": []}, "links": {self.c: {"name": "Biome", "topic": "hub"}}}
        player_id = digest(packs.compact(player))
        entry = {"topic": "items", "status": "present", "name": "Raw A", "kind": "item",
                 "revision_id": item_id, "provenance_id": provenance_id, "card_id": "card", "player_id": player_id,
                 "links": {self.c: {"topic": "hub"}}}
        hub_entry = {"topic": "hub", "status": "present", "name": "Biome", "kind": "biome",
                     "revision_id": biome_id, "provenance_id": provenance_id, "links": {}}
        present = {self.a: {"entity_key": self.a, "name": "Wiki A", "source_name": "Raw A", "kind": "item", "topic": "items"},
                   self.c: {"entity_key": self.c, "name": "Biome", "kind": "biome", "topic": "hub"}}
        maps = {"items": {"entries": {self.a: entry, self.b: {"topic": "items", "status": "not-present"}},
                          "semantics": {item_id: item}, "provenance": {provenance_id: provenance},
                          "search": {self.a: {}, self.b: {}}, "backlinks": {}, "cards": {"card": {}},
                          "player": {player_id: player}},
                "hub": {"entries": {self.c: hub_entry}, "semantics": {biome_id: biome},
                        "provenance": {provenance_id: provenance}, "search": present,
                        "backlinks": {self.c + "/back": {"entity": self.a, "topic": "items"}}, "cards": {}, "player": {}}}
        if change:
            change(maps)
        guide = {"document": {"id": "guide", "title": "Guide", "dek": "Facts", "runs": [{"text": "Biome", "entity": self.c}]},
                 "links": {self.c: {"name": "Biome", "topic": "hub"}}}
        if change_guide:
            change_guide(guide)
        guide_data = packs.compact(guide)
        guide_sha = digest(guide_data)
        for topic, values in maps.items():
            site = self.root / topic
            (site / "data").mkdir(parents=True, exist_ok=True)
            index = {}
            for kind, records in values.items():
                index[kind] = [self.shard(records)] if records else []
                for ref in index[kind]:
                    (site / ref["path"]).write_bytes((self.root / ref["path"]).read_bytes())
            if topic == "hub":
                (site / "data" / (guide_sha + ".json")).write_bytes(guide_data)
                index.update(topic_counts={"hub": {"total": 1, "kinds": {"biome": 1}},
                                           "items": {"total": 1, "kinds": {"item": 1}}},
                             guides=[{"id": "guide", "title": "Guide", "dek": "Facts", "path": f"data/{guide_sha}.json",
                                      "sha256": guide_sha, "bytes": len(guide_data)}])
                if change_index:
                    change_index(index)
            (site / "snapshots").mkdir(exist_ok=True)
            (site / "snapshots/fixture.json").write_bytes(json_bytes(index))
        return maps

    def test_complete_snapshot_preserves_inputs_and_counts_present_entries(self):
        self.snapshot()
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(reader_validation.validate_snapshot(self.root, "fixture", ["items", "hub"]), 2)
        self.assertEqual(reader_validation.validate_snapshot(self.root, "fixture", ["hub", "items"]), 2)
        self.assertEqual(before, {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_topic_maps_are_released_before_loading_the_next_topic(self):
        class TrackedMap(dict):
            pass

        self.snapshot()
        load = reader_validation.load_maps
        kinds = ("entries", "semantics", "provenance", "search", "backlinks", "cards", "player")
        for topics in (("items", "hub"), ("hub", "items")):
            references, positions, observed = {}, {}, []

            def tracked_load(site, shards):
                topic = site.name
                position = positions.get(topic, 0)
                kind = kinds[position]
                positions[topic] = position + 1
                retained = {key for key, reference in references.items()
                            if key[0] != topic and reference() is not None}
                observed.append((topic, kind, retained))
                values = TrackedMap(load(site, shards))
                references[topic, kind] = weakref.ref(values)
                return values

            with self.subTest(topics=topics), patch.object(reader_validation, "load_maps", side_effect=tracked_load):
                self.assertEqual(reader_validation.validate_snapshot(self.root, "fixture", topics), 2)
                self.assertEqual([(topic, kind) for topic, kind, _ in observed],
                                 [(topic, kind) for topic in topics for kind in kinds])
                expected = {("hub", "search")} if topics[0] == "hub" else set()
                for topic, kind, retained in observed:
                    if topic == topics[1]:
                        with self.subTest(kind=kind):
                            self.assertEqual(retained, expected)

    def test_map_and_entry_phases_return_complete_records(self):
        expected = self.snapshot()
        index = json.loads((self.root / "items/snapshots/fixture.json").read_bytes())
        entries, semantics, provenance, searches, backlinks, players, targets = reader_validation.load_snapshot_maps(self.root / "items", index)
        self.assertEqual((entries, semantics, provenance, searches, backlinks, players, targets),
                         (expected["items"]["entries"], expected["items"]["semantics"], expected["items"]["provenance"],
                          expected["items"]["search"], expected["items"]["backlinks"], expected["items"]["player"], [(self.c, "hub")]))
        membership, present = {}, {}
        self.assertEqual(reader_validation.validate_entries("items", "fixture", entries, semantics, provenance, backlinks,
                                                           players, membership, present, targets), (1, {"total": 1, "kinds": {"item": 1}}))
        self.assertEqual(membership, {self.a: "items", self.b: "items"})
        self.assertEqual(present, {self.a: expected["hub"]["search"][self.a]})
        self.assertEqual(targets, [(self.c, "hub")] * 3)
        hub_index = json.loads((self.root / "hub/snapshots/fixture.json").read_bytes())
        self.assertIsNone(reader_validation.validate_guides(self.root, hub_index, expected["hub"]["search"]))
        self.assertIsNone(reader_validation.validate_explanations(self.a, "items", "fixture", []))

    def test_snapshot_map_entry_and_backlink_errors_are_exact(self):
        cases = [
            (lambda maps: maps["items"].update(cards={}), "Reader entry card_id is missing from cards"),
            (lambda maps: maps["items"]["cards"].update(orphan={}), "Reader card has no owning entry"),
            (lambda maps: maps["items"].update(player={}), "Reader entry player_id is missing from player"),
            (lambda maps: maps["items"]["player"].update(orphan={}), "Reader player has no owning entry"),
            (lambda maps: next(iter(maps["items"]["player"].values())).update(name="changed"), "Reader player hash differs"),
            (lambda maps: maps["items"]["entries"][self.a].update(topic="hub"), "Reader has duplicate or invalid canonical ownership"),
            (lambda maps: next(iter(maps["items"]["semantics"].values())).update(extra=True), "Reader semantic revision hash differs"),
            (lambda maps: next(iter(maps["items"]["provenance"].values())).update(extra=True), "Reader provenance hash differs"),
            (lambda maps: maps["items"]["entries"][self.a].update(links={}), "Reader relationship lacks a route"),
            (lambda maps: maps["items"]["entries"][self.a]["links"][self.c].update(topic="items"), "Reader relationship leaves its selected snapshot"),
            (lambda maps: maps["items"]["backlinks"].update({"missing/back": {"entity": self.c, "topic": "hub"}}), "Reader backlink has no owning entry"),
        ]
        for change, expected in cases:
            self.snapshot(change)
            with self.subTest(error=expected), self.assertRaises(ContractError) as raised:
                reader_validation.validate_snapshot(self.root, "fixture", ["items", "hub"])
            self.assertEqual(str(raised.exception), expected)

    def test_player_run_membership_error_is_exact_after_valid_hash(self):
        def change(maps):
            old, player = next(iter(maps["items"]["player"].items()))
            player["how"] = []
            identity = digest(packs.compact(player))
            maps["items"]["player"] = {identity: player}
            maps["items"]["entries"][self.a]["player_id"] = identity
        self.snapshot(change)
        with self.assertRaises(ContractError) as raised:
            reader_validation.validate_snapshot(self.root, "fixture", ["items", "hub"])
        self.assertEqual(str(raised.exception), "Reader player links differ from its runs")

    def test_explanation_errors_and_successful_checks_are_exact(self):
        for changes, error in [({"topic": "hub"}, "Explanation leaves its owning entry or snapshot"),
                               ({"last_verified": None}, "Passed explanation lacks its successful check"),
                               ({"status": "unverified", "text": None}, "Failed explanation lacks its reason"),
                               ({}, None), ({"status": "unverified", "text": None, "reasons": ["unknown"]}, None)]:
            def change(maps):
                note = {"entity": self.a, "topic": "items", "snapshot_id": "fixture", "status": "passed",
                        "text": "Checked", "last_verified": {"snapshot_id": "fixture"}, "reasons": []}
                maps["items"]["entries"][self.a]["explanations"] = [{**note, **changes}]
            self.snapshot(change)
            with self.subTest(changes=changes):
                if error:
                    with self.assertRaises(ContractError) as raised:
                        reader_validation.validate_snapshot(self.root, "fixture", ["items", "hub"])
                    self.assertEqual(str(raised.exception), error)
                else:
                    self.assertEqual(reader_validation.validate_snapshot(self.root, "fixture", ["items", "hub"]), 2)

    def test_hub_and_guide_errors_are_exact(self):
        cases = [(lambda index: index["topic_counts"]["hub"].update(total=0), None, "Hub search or topic counts differ from present entries"),
                 (lambda index: index["guides"][0].update(bytes=0), None, "Guide pack hash differs"),
                 (lambda index: index["guides"][0].update(title="changed"), None, "Guide metadata differs"),
                 (lambda index: index["guides"].append(dict(index["guides"][0])), None, "Guide metadata differs"),
                 (None, lambda guide: guide["links"][self.c].update(topic="items"), "Guide links leave their present snapshot entries")]
        for index_change, guide_change, expected in cases:
            self.snapshot(change_index=index_change, change_guide=guide_change)
            with self.subTest(error=expected), self.assertRaises(ContractError) as raised:
                reader_validation.validate_snapshot(self.root, "fixture", ["items", "hub"])
            self.assertEqual(str(raised.exception), expected)


class ReaderContractTests(unittest.TestCase):
    def test_existing_reader_imports_still_resolve(self):
        for name in ("ENTITY", "document_runs", "load_maps", "validate_snapshot"):
            self.assertIs(getattr(reader, name), getattr(reader_validation, name))

    def test_contract_covers_every_direct_wikibuild_import(self):
        source = Path(reader.__file__)
        modules = set()
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                if node.level == 1:
                    modules.update([node.module] if node.module else [alias.name for alias in node.names])
                elif node.module == "wikibuild":
                    modules.update(alias.name for alias in node.names)
                elif node.module and node.module.startswith("wikibuild."):
                    modules.add(node.module.removeprefix("wikibuild."))
            elif isinstance(node, ast.Import):
                modules.update(alias.name.removeprefix("wikibuild.") for alias in node.names
                               if alias.name.startswith("wikibuild."))
        contract = reader.contract()
        self.assertTrue(modules)
        for module in sorted(modules):
            path = module.replace(".", "/") + ".py"
            with self.subTest(module=module):
                self.assertIn(path, contract)
                data = (source.parent / path).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(contract[path], digest(data))


if __name__ == "__main__":
    unittest.main()
