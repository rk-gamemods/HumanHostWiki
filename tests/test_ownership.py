"""Bound ownership receipts without losing file or allocation membership."""

import json
import unittest

from wikibuild import ownership
from wikibuild.storage import ContractError, digest, json_bytes


class OwnershipTests(unittest.TestCase):
    def receipt(self, count):
        files = {f"site/data/{i:064x}.json": {"sha256": f"{i:064x}", "bytes": i + 1}
                 for i in range(count)}
        return {"schema_version": 1, "kind": "generated-wiki-output", "repository_id": "items",
                "release_id": "a" * 64, "files": files, "capacity_objects": sorted(files)[::2]}

    def encode(self, value, limit=2048):
        parts = {}
        def emit(name, data):
            self.assertLessEqual(len(data), limit)
            self.assertEqual(name, ".wiki-ownership/" + digest(data) + ".json")
            parts[name] = data
        raw, metadata = ownership.encode(value, limit, emit)
        self.assertLessEqual(len(raw), limit)
        self.assertEqual(set(parts), set(metadata))
        return raw, parts, metadata

    def test_small_receipt_preserves_legacy_bytes_and_needs_no_parts(self):
        value = self.receipt(1)
        raw, parts, metadata = self.encode(value)
        self.assertEqual(raw, json_bytes(value))
        self.assertEqual((parts, metadata), ({}, {}))
        self.assertEqual(ownership.decode(raw, lambda _: self.fail()), (value, {}))

    def test_multilevel_receipt_preserves_membership_and_repeats_identically(self):
        value = self.receipt(400)
        raw, parts, metadata = self.encode(value)
        self.assertEqual(json.loads(raw)["schema_version"], 2)
        self.assertTrue(any(json.loads(data).get("kind") == "wiki-shard-directory" for data in parts.values()))
        self.assertEqual(ownership.decode(raw, parts.__getitem__), (value, metadata))
        self.assertEqual(self.encode(value), (raw, parts, metadata))
        from tools.audit_ownership import expand
        actual, names = expand(json.loads(raw), parts.__getitem__)
        self.assertEqual(actual, value)
        self.assertEqual(set(names), set(parts))

    def test_changed_missing_escaped_and_duplicated_parts_fail(self):
        raw, parts, _ = self.encode(self.receipt(40))
        name = json.loads(raw)["file_index"][0]["path"]
        corrupt = {**parts, name: parts[name] + b" "}
        with self.assertRaisesRegex(ContractError, "ownership page"):
            ownership.decode(raw, corrupt.__getitem__)
        with self.assertRaisesRegex(ContractError, "ownership page"):
            ownership.decode(raw, lambda _: (_ for _ in ()).throw(FileNotFoundError()))
        value = json.loads(raw)
        value["file_index"][0]["path"] = "../unknown.json"
        with self.assertRaisesRegex(ContractError, "ownership page"):
            ownership.decode(json_bytes(value), lambda _: self.fail("escaped read"))
        value = json.loads(raw)
        value["file_index"].append(value["file_index"][0])
        with self.assertRaisesRegex(ContractError, "range|duplicate"):
            ownership.decode(json_bytes(value), parts.__getitem__)

    def test_invalid_membership_and_indivisible_record_are_rejected(self):
        value = self.receipt(2)
        value["capacity_objects"].append("site/missing.json")
        with self.assertRaisesRegex(ContractError, "allocation"):
            self.encode(value)
        value = self.receipt(1)
        value["files"]["site/" + "x" * 5000] = {"sha256": "b" * 64, "bytes": 1}
        with self.assertRaisesRegex(ContractError, "record exceeds"):
            self.encode(value)

    def test_malformed_roots_and_changed_summaries_fail_without_hidden_type_errors(self):
        for raw in (b"null", b"[]", b"{", b'{"schema_version":2,"kind":"generated-wiki-output"}'):
            with self.assertRaises(ContractError):
                ownership.decode(raw, lambda _: self.fail())
        raw, parts, _ = self.encode(self.receipt(40))
        value = json.loads(raw)
        value["file_count"] += 1
        with self.assertRaisesRegex(ContractError, "membership summary"):
            ownership.decode(json_bytes(value), parts.__getitem__)


if __name__ == "__main__":
    unittest.main()
