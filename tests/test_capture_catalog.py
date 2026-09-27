"""Capture catalogs preserve chronology and exact selection within file budgets."""

import json
import unittest
from unittest.mock import patch

from wikibuild import capture_catalog, packs
from wikibuild.storage import ContractError, digest
from tools.audit_capture_catalog import expand


class CaptureCatalogTests(unittest.TestCase):
    def config(self, count):
        versions = [{"snapshot_id": f"build-{100 + i}-aaaaaaaaaaaa", "build_id": str(100 + i)}
                    for i in reversed(range(count))]
        return {"schema_version": 1, "features": ["paged-captures-v1"], "topic": "items",
                "default_snapshot": versions[0]["snapshot_id"], "versions": versions,
                "snapshots": {v["snapshot_id"]: {"path": f"objects/{i:064x}.json",
                              "sha256": f"{i:064x}", "bytes": 20} for i, v in enumerate(versions)}}

    def project(self, value, limit=2048):
        files = {}
        def emit(batch):
            refs = []
            for topic, data in batch:
                self.assertEqual(topic, "items")
                self.assertLessEqual(len(data), limit)
                name = "objects/" + digest(data) + ".json"
                files[name] = data
                refs.append({"path": name, "sha256": digest(data), "bytes": len(data)})
            return refs
        result = capture_catalog.compact({"items": packs.compact(value)}, limit, emit)
        return json.loads(result["items"]), files

    def test_small_configuration_retains_exact_bytes_and_needs_no_allocation(self):
        raw = json.dumps(self.config(1), indent=2).encode()
        self.assertEqual(capture_catalog.compact({"items": raw}, 4096, lambda _: self.fail()), {"items": raw})

    def test_multilevel_catalog_conserves_records_order_and_default_on_repeat(self):
        original = self.config(400)
        with patch("builtins.open", side_effect=AssertionError("producer must not access files")):
            result, files = self.project(original)
        self.assertLessEqual(len(packs.compact(result)), 2048)
        self.assertNotIn("versions", result)
        self.assertNotIn("snapshots", result)
        self.assertTrue(any(json.loads(data).get("kind") == "wiki-shard-directory" for data in files.values()))
        def fetch(ref):
            data = files[ref["path"]]
            self.assertEqual((digest(data), len(data)), (ref["sha256"], ref["bytes"]))
            return json.loads(data)
        self.assertEqual(expand(result, fetch), original)
        self.assertEqual(self.project(original), (result, files))
        forged = {**result, "default_capture": {**result["default_capture"], "ordinal": 0}}
        with self.assertRaises(AssertionError):
            expand(forged, fetch)

    def test_unsupported_runtime_and_indivisible_records_fail_explicitly(self):
        old = self.config(30)
        old["features"] = []
        with self.assertRaisesRegex(ContractError, "runtime does not support"):
            self.project(old)
        huge = self.config(2)
        huge["versions"][1]["notes"] = "x" * 5000
        with self.assertRaisesRegex(ContractError, "record exceeds"):
            self.project(huge)
        fixed = self.config(30)
        fixed["fixed_metadata"] = "x" * 5000
        with self.assertRaisesRegex(ContractError, "configuration.*budget"):
            self.project(fixed)


if __name__ == "__main__":
    unittest.main()
