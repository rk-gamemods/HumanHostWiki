"""Small released-site fixtures for the standalone readability audit."""

import json
from pathlib import Path
import tempfile
import unittest

from tools import audit_readability


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def site(root, topic, entries, semantics, provenance, backlinks, directory=False):
    folder = root / topic / "site"
    snapshot = "snap-1"
    write(folder / "reader.json", {"default_snapshot": snapshot,
                                   "snapshots": {snapshot: {"path": "snapshots/snap-1.json"}}})
    index = {}
    for section, value in (("entries", entries), ("semantics", semantics),
                           ("provenance", provenance), ("backlinks", backlinks),
                           ("search", {})):
        path = f"data/{section}.json"
        write(folder / path, value)
        ref = {"path": path, "first": "a", "last": "z"}
        if directory and section == "entries":
            write(folder / "data/entry-directory.json", {"shards": [ref]})
            ref = {"kind": "wiki-shard-directory", "path": "data/entry-directory.json",
                   "first": "a", "last": "z"}
        index[section] = [ref]
    write(folder / "snapshots/snap-1.json", index)


class ReadabilityAuditTests(unittest.TestCase):
    def test_fixture_flags_labels_and_repeat_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repositories = root / "repositories"
            entries = {
                "e-aaaa": {"name": "M1891", "kind": "item", "topic": "items",
                           "status": "present", "revision_id": "r1", "provenance_id": "p1"},
                "e-bbbb": {"name": "M1891", "kind": "item", "topic": "items",
                           "status": "present", "revision_id": "r2", "provenance_id": "p2"},
                "e-cccc": {"name": "G_Mode Debug", "kind": "item", "topic": "items",
                           "status": "present", "revision_id": "r3", "provenance_id": "p3"},
                "e-old": {"name": "Old", "kind": "item", "topic": "items",
                          "status": "removed", "revision_id": "r4", "provenance_id": "p4"},
            }
            semantics = {
                "r1": {"facts": {"_Infos": [{"_ItemName": "M1891"}],
                                  "_Chance": 0.07999999821186066, "_Tag": "中文",
                                  "_Code": "00", "_Empty": ""},
                       "relationships": [{"predicate": "uses", "field": "/_Target",
                                          "targets": ["e-missing"]}]},
                "r2": {"facts": {"_Infos": [{"_ItemName": "M1891"}],
                                  "_Code": "AB", "_Empty": "filled"}, "relationships": []},
                "r3": {"facts": {"_AssetPath": "bundles/items/foo.prefab::serialized"},
                       "relationships": []},
            }
            provenance = {"p1": {"source_id": "s1"}, "p2": {"source_id": "s2"},
                          "p3": {"source_id": "s3"}}
            backlinks = {"e-aaaa/0": {"entity": "e-bbbb", "predicate": "produces-item",
                                        "field": "/_Output"}}
            site(repositories, "items", entries, semantics, provenance, backlinks, directory=True)
            site(repositories, "world", {"e-world": {"name": "Zone", "kind": "biome",
                 "topic": "world", "status": "present", "revision_id": "rw", "provenance_id": "pw"}},
                 {"rw": {"facts": {"_BiomeName": "Zone"}, "relationships": []}},
                 {"pw": {"source_id": "world"}}, {})
            out = root / "out"
            args = ["--repositories", str(repositories), "--out", str(out)]
            audit_readability.main(args)
            first = [(out / name).read_bytes() for name in ("readability.json", "readability.md")]
            report = json.loads(first[0])
            totals = report["summary"]["flag_totals"]
            self.assertEqual(report["summary"]["entries"], 4)
            self.assertEqual(totals["float_noise"], 1)
            self.assertEqual(totals["cjk_text"], 1)
            self.assertEqual(totals["duplicate_names"], 1)
            self.assertEqual(totals["no_source_items"], 2)
            self.assertEqual(totals["debug_names"], 1)
            self.assertEqual(totals["sentinel_string"], 1)
            self.assertEqual(totals["empty_text"], 1)
            self.assertEqual(totals["identifier_value"], 1)
            self.assertEqual(totals["unreadable_targets"], 1)
            self.assertEqual(report["flags"]["duplicate_names"]["examples"][0]["keys"],
                             ["e-aaaa", "e-bbbb"])
            self.assertEqual(report["no_source_predicates"], sorted(audit_readability.SOURCE_PREDICATES))
            field = next(row for row in report["field_inventory"]
                         if row["field"] == "/_Infos/*/_ItemName")
            self.assertEqual(field["current_label"], "Item Name")
            self.assertTrue(field["label_is_identifier"])
            self.assertEqual(field["fill_count"], 2)
            self.assertTrue(field["constant"])
            self.assertEqual(audit_readability.field_label("_DuraCostPerAttack"),
                             "Dura Cost Per Attack")
            audit_readability.main(args)
            self.assertEqual(first, [(out / name).read_bytes()
                                     for name in ("readability.json", "readability.md")])

    def test_reject_output_inside_repositories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repositories"
            root.mkdir()
            with self.assertRaises(SystemExit):
                audit_readability.main(["--repositories", str(root), "--out", str(root / "audit")])


if __name__ == "__main__":
    unittest.main()
