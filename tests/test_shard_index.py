"""Bounded directories conserve ordered pack references without filesystem access."""

import json
import unittest

from wikibuild import packs, shard_index
from wikibuild.storage import ContractError, digest


class ShardIndexTests(unittest.TestCase):
    def index(self, count):
        refs = [{"path": f"data/{number:064x}.json", "sha256": f"{number:064x}",
                 "bytes": 10, "first": f"key-{number:06d}", "last": f"key-{number:06d}", "count": 1}
                for number in range(count)]
        return {"schema_version": 1, "snapshot_id": "build-100-aaaaaaaaaaaa",
                **{kind: [] for kind in shard_index.FIELDS}, "entries": refs}

    def test_small_index_keeps_exact_bytes_without_allocating(self):
        data = json.dumps(self.index(1), indent=2).encode()
        def unexpected(_):
            self.fail("An unchanged index allocated a directory")
        self.assertEqual(shard_index.compact({("items", "one"): data}, 2048, unexpected),
                         {("items", "one"): data})

    def test_multilevel_split_keeps_order_ranges_and_repeats_identically(self):
        original = self.index(400)
        # Reused packs may overlap ranges. Parent bounds must cover every child,
        # not just the first/last list entries.
        original["entries"][0]["last"] = "zzzz"
        original["entries"][-1]["first"] = "aaaa"
        outputs, calls = {}, []
        def emit(batch):
            calls.append(len(batch))
            refs = []
            for topic, data in batch:
                self.assertEqual(topic, "items")
                self.assertLessEqual(len(data), 2048)
                path = "objects/" + digest(data) + ".json"
                outputs[path] = data
                refs.append({"path": path, "sha256": digest(data), "bytes": len(data)})
            return refs
        request = {("items", "one"): packs.compact(original)}
        result = shard_index.compact(request, 2048, emit)
        self.assertLessEqual(len(result[("items", "one")]), 2048)
        self.assertGreater(len(calls), 1)
        def flatten(refs):
            for ref in refs:
                if ref.get("kind") != "wiki-shard-directory":
                    yield ref
                    continue
                value = json.loads(outputs[ref["path"]])
                leaves = list(flatten(value["shards"]))
                self.assertEqual(ref["first"], min(row["first"] for row in leaves))
                self.assertEqual(ref["last"], max(row["last"] for row in leaves))
                self.assertEqual(ref["count"], sum(row["count"] for row in leaves))
                yield from leaves
        self.assertEqual(list(flatten(json.loads(result[("items", "one")])["entries"])), original["entries"])
        before = dict(outputs)
        self.assertEqual(shard_index.compact(request, 2048, emit), result)
        self.assertEqual(outputs, before)

    def test_indivisible_metadata_fails_without_an_infinite_split(self):
        value = self.index(1)
        value["unknown_metadata"] = "x" * 5000
        with self.assertRaisesRegex(ContractError, "metadata.*budget"):
            shard_index.compact({("items", "one"): packs.compact(value)}, 2048, lambda _: self.fail())


if __name__ == "__main__":
    unittest.main()
