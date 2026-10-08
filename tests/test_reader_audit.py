"""Independent reader audit accepts current artifacts and rejects plausible tampering."""

import copy
import hashlib
import json
import unittest

from tests._support import fixture_dir
from tools import check_reader


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ReaderAuditTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "read-aud")
        self.site = self.root / "candidate"
        self.files = {}
        self.old, self.other, self.new = ["e-" + digit * 32 for digit in "123"]
        self.run_id = "f" * 64
        self.snapshot = "build-200-fixture"

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def output(self, name, value):
        data = value if isinstance(value, bytes) else encoded(value)
        self.write(self.site / name, data)
        self.files[name] = {"bytes": len(data), "sha256": digest(data)}

    def pack(self, topic, kind, values):
        if not values:
            return []
        name = f"{topic}/data/{kind}.json"
        self.output(name, values)
        return [{"path": f"data/{kind}.json", **self.files[name]}]

    def finalize(self):
        self.write(self.site / "candidate.json", encoded({
            "candidate_id": digest(encoded(self.inputs)), "inputs": self.inputs,
            "versions": [{"snapshot_id": self.snapshot, "identity_run": self.run_id}],
            "files": self.files, "total_bytes": sum(meta["bytes"] for meta in self.files.values())}))

    def fixture(self, migrated=False):
        first = {"entity_key": self.old,
                 "semantic": {"name": "Source item", "kind": "item", "topic": "items",
                              "facts": {"stack": 1}, "relationships": []},
                 "provenance": {"source_id": "bundle#1", "observation_key": "observation-a",
                                "resolved_targets": []}}
        second = {"entity_key": self.other,
                  "semantic": {"name": "Other item", "kind": "item", "topic": "items",
                               "facts": {}, "relationships": [{"predicate": "references", "field": "/item",
                                  "targets": [self.old], "technical_targets": []}]},
                  "provenance": {"source_id": "bundle#2", "observation_key": "observation-b",
                                 "resolved_targets": [{"status": "resolved", "target_entity": self.old}]}}
        for row in (first, second):
            row["revision_id"] = digest(encoded(row["semantic"]))
        model_data = b"".join(encoded(row).replace(b"\n", b" ") + b"\n" for row in (first, second))
        self.write(self.root / "models.jsonl", model_data)
        self.write(self.root / f"identity/runs/{self.run_id}.json", encoded({
            "run_id": self.run_id, "snapshot_id": self.snapshot,
            "models": {"path": "models.jsonl", "bytes": len(model_data), "sha256": digest(model_data)}}))
        self.inputs = {"project": {"repositories": [{"id": "hub"}, {"id": "items"}]}}
        canonical = self.new if migrated else self.old
        if migrated:
            proof = {"old_key": self.old, "entity_key": self.new, "run_id": self.run_id,
                     "snapshot_id": self.snapshot, "source_id": "bundle#1",
                     "observation_key": "observation-a", "topic": "items"}
            record = {"schema_version": 1, "repairs": [proof],
                      "redirects": {self.old: {"entity_key": self.new, "topic": "items"}}}
            record["migration_id"] = digest(encoded(record))
            self.write(self.root / "identity/migration.json", encoded(record))
            self.inputs["identity_migration"] = record["migration_id"]

        # Consumer expectation is authored separately from the checker's repair code.
        consumer = copy.deepcopy([first, second])
        consumer[0]["entity_key"] = canonical
        consumer[1]["semantic"]["relationships"][0]["targets"] = [canonical]
        consumer[1]["provenance"]["resolved_targets"][0]["target_entity"] = canonical
        consumer[1]["revision_id"] = digest(encoded(consumer[1]["semantic"]))
        entries, semantics, provenance, search = {}, {}, {}, {}
        players = {"player-a": {"name": "Player item"}}
        for row in consumer:
            key, semantic = row["entity_key"], row["semantic"]
            provenance_id = digest(encoded(row["provenance"]))
            entries[key] = {"entity_key": key, "status": "present", "name": semantic["name"],
                            "kind": "item", "topic": "items", "revision_id": row["revision_id"],
                            "provenance_id": provenance_id, "last_verified": None}
            semantics[row["revision_id"]] = semantic
            provenance[provenance_id] = row["provenance"]
            search[key] = {"entity_key": key, "name": semantic["name"], "kind": "item", "topic": "items"}
        entries[canonical]["player_id"] = "player-a"
        search[canonical].update(name="Player item", source_name="Source item")
        reverse = {canonical + "/edge": {"entity": self.other, "predicate": "references",
                                          "field": "/item", "topic": "items"}}
        topic_values = {"entries": entries, "semantics": semantics, "provenance": provenance,
                        "search": search, "backlinks": reverse, "player": players}
        for topic in ("hub", "items"):
            index = {kind: self.pack(topic, kind, search if topic == "hub" and kind == "search"
                                   else values if topic == "items" else {})
                     for kind, values in topic_values.items()}
            index["redirects"] = {self.old: self.new} if migrated and topic == "items" else {}
            if topic == "hub":
                index["topic_counts"] = {"hub": {"total": 0, "kinds": {}},
                                         "items": {"total": 2, "kinds": {"item": 2}}}
            self.output(f"{topic}/snapshots/{self.snapshot}.json", index)
        self.output("hub/fonts/fixture/font.woff2", b"font bytes")
        self.output("hub/fonts/fixture/OFL-fixture.txt", b"license bytes")
        self.finalize()

    def audit(self):
        return check_reader.check(self.root, self.site)

    def change(self, path, mutation):
        value = json.loads((self.site / path).read_bytes())
        mutation(value)
        self.output(path, value)
        self.finalize()

    def test_current_fonts_hub_search_and_player_names_pass_unchanged_repeat(self):
        self.fixture()
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        first = self.audit()
        self.assertEqual(first["observations_checked"], 2)
        self.assertEqual(first, self.audit())
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_reviewed_migration_preserves_source_and_repairs_identity_edges(self):
        self.fixture(migrated=True)
        frozen = (self.root / "models.jsonl").read_bytes()
        self.assertEqual(self.audit()["status"], "passed")
        self.assertEqual((self.root / "models.jsonl").read_bytes(), frozen)

    def test_font_tampering_and_manifested_dll_remain_rejected(self):
        self.fixture()
        font = self.site / "hub/fonts/fixture/font.woff2"
        original = font.read_bytes()
        font.write_bytes(original + b"tampered")
        with self.assertRaises(AssertionError):
            self.audit()
        font.write_bytes(original)
        self.output("items/game.dll", b"not wiki content")
        self.finalize()
        with self.assertRaises(AssertionError):
            self.audit()

    def test_rehashed_hub_search_disassociation_is_rejected(self):
        self.fixture()
        self.change("hub/data/search.json", lambda rows: rows[self.old].update(name="Wrong item"))
        with self.assertRaises(AssertionError):
            self.audit()

    def test_consistently_rehashed_search_route_cannot_change_source_ownership(self):
        self.fixture()
        for topic in ("items", "hub"):
            self.change(f"{topic}/data/search.json", lambda rows: rows[self.old].update(topic="different-topic"))
        with self.assertRaises(AssertionError):
            self.audit()

    def test_rehashed_migration_edge_and_provenance_tampering_are_rejected(self):
        self.fixture(migrated=True)
        for kind, mutation in [
            ("semantics", lambda rows: next(row for row in rows.values() if row["relationships"])
             ["relationships"][0].update(targets=[self.old])),
            ("provenance", lambda rows: next(row for row in rows.values() if row["resolved_targets"])
             ["resolved_targets"][0].update(target_entity=self.old))]:
            with self.subTest(kind=kind):
                path = f"items/data/{kind}.json"
                original = json.loads((self.site / path).read_bytes())
                self.change(path, mutation)
                with self.assertRaises(AssertionError):
                    self.audit()
                self.output(path, original)
                self.finalize()
                self.assertEqual(self.audit()["status"], "passed")

    def test_retired_url_redirect_tampering_is_rejected(self):
        self.fixture(migrated=True)
        self.change(f"items/snapshots/{self.snapshot}.json",
                    lambda index: index["redirects"].update({self.old: self.other}))
        with self.assertRaises(AssertionError):
            self.audit()

    def test_changed_pinned_migration_and_frozen_source_are_rejected(self):
        self.fixture(migrated=True)
        path = self.root / "identity/migration.json"
        original = path.read_bytes()
        record = json.loads(original)
        record["repairs"][0]["source_id"] = "different-source"
        self.write(path, encoded(record))
        with self.assertRaises(AssertionError):
            self.audit()
        path.write_bytes(original)
        source = self.root / "models.jsonl"
        # Valid, semantically identical JSON with a changed byte must still fail its receipt hash.
        source.write_bytes(source.read_bytes().replace(b" ", b"\t", 1))
        with self.assertRaises(AssertionError):
            self.audit()


if __name__ == "__main__":
    unittest.main()
