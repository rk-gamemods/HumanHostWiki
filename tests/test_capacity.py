"""Placement behavior without Git, filesystem writes, network or game payloads."""

from dataclasses import replace
import hashlib
import unittest
from unittest.mock import patch

from wikibuild import capacity
from wikibuild.storage import ContractError, json_bytes


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.topic = capacity.Topic("items", "Wiki-Items")
        self.budgets = capacity.Budgets(file_bytes=600, site_bytes=1000, history_bytes=2000,
                                       site_reserve_bytes=100, history_reserve_bytes=100)
        self.empty = capacity.partition(self.topic, 0)

    def artifact(self, label, size=400, *, topic="items", kind="data"):
        sha = hashlib.sha256(label.encode()).hexdigest()
        return capacity.Artifact(topic, f"site/{kind}/{sha}.json", sha, size)

    def allocate(self, objects, partitions=None, stored=(), topics=None, budgets=None):
        return capacity.allocate(topics or [self.topic], partitions or [self.empty], stored, objects,
                                 budgets or self.budgets)

    def test_overflow_preserves_topic_and_existing_object_location(self):
        old = self.artifact("old", 500)
        base = replace(self.empty, site_bytes=800, history_bytes=850)
        stored = capacity.Placement(old, base.id)
        result = self.allocate([old, self.artifact("new")], [base], [stored])
        self.assertEqual(result.created, ("items-part-0001",))
        by_key = {p.artifact.key: p.partition for p in result.placements}
        self.assertEqual(by_key[old.key], "items")
        self.assertEqual(by_key[self.artifact("new").key], "items-part-0001")
        self.assertEqual(result.partitions[0], base)
        self.assertEqual(result.partitions[1].topic, "items")
        self.assertEqual(result.partitions[1].github_name, "Wiki-Items-Part-0001")

    def test_history_budget_rolls_over_even_when_site_has_space(self):
        base = replace(self.empty, history_bytes=1800)
        result = self.allocate([self.artifact("new", 200)], [base])
        self.assertEqual(result.created, ("items-part-0001",))
        self.assertEqual(result.partitions[0], base)

    def test_sealed_and_over_budget_partitions_allow_reuse_only(self):
        old = self.artifact("old")
        for base in (replace(self.empty, site_bytes=400, history_bytes=400, sealed=True),
                     replace(self.empty, site_bytes=1500, history_bytes=2400)):
            with self.subTest(base=base):
                result = self.allocate([old, self.artifact("new")], [base], [capacity.Placement(old, base.id)])
                self.assertEqual(result.reused, (old.key,))
                self.assertEqual(result.partitions[0], base)
                self.assertEqual(result.created, ("items-part-0001",))

    def test_reserve_boundary_and_decreasing_size_reduce_partition_count(self):
        values = [self.artifact("small-a", 300), self.artifact("small-b", 300),
                  self.artifact("large-a", 600), self.artifact("large-b", 600)]
        result = self.allocate(values)
        self.assertEqual(len(result.partitions), 2)
        self.assertTrue(all(p.site_bytes == 900 for p in result.partitions))
        overflow = self.allocate([self.artifact("one-byte", 1)], list(result.partitions), result.placements)
        self.assertEqual(overflow.created, ("items-part-0002",))

    def test_input_order_and_duplicates_do_not_change_plan(self):
        values = [self.artifact(str(i), 400) for i in range(8)]
        forward = self.allocate(values)
        reverse = self.allocate(reversed(values))
        duplicates = self.allocate(values + values)
        self.assertEqual(forward.record(), reverse.record())
        self.assertEqual(forward.record(), duplicates.record())

    def test_replayed_applied_plan_allocates_nothing_and_keeps_locations(self):
        values = [self.artifact(str(i), 400) for i in range(7)]
        first = self.allocate(values)
        again = self.allocate(values, list(first.partitions), first.placements)
        self.assertEqual(again.created, ())
        self.assertEqual(again.partitions, first.partitions)
        self.assertEqual(again.placements, first.placements)
        self.assertEqual(set(again.reused), {v.key for v in values})

    def test_git_blob_reuse_counts_site_paths_but_charges_history_once(self):
        first = self.artifact("same", 400)
        second = replace(first, path=first.path.replace("/data/", "/objects/"))
        result = self.allocate([first, second])
        self.assertEqual(result.partitions[0].site_bytes, 800)
        self.assertEqual(result.partitions[0].history_bytes, 400)

    def test_partition_names_skip_configured_logical_repository_collisions(self):
        reserved = capacity.Topic("items-part-0001", "Wiki-Items-Part-0001")
        base = replace(self.empty, sealed=True)
        result = self.allocate([self.artifact("new")], [base, capacity.partition(reserved, 0)],
                               topics=[self.topic, reserved])
        self.assertEqual(result.created, ("items-part-0002",))

    def test_different_logical_topics_never_share_physical_ownership(self):
        loot = capacity.Topic("loot", "Wiki-Loot")
        result = self.allocate([self.artifact("items"), self.artifact("loot", topic="loot")],
                               [self.empty, capacity.partition(loot, 0)], topics=[self.topic, loot])
        for placed in result.placements:
            self.assertEqual(placed.partition, placed.artifact.topic)

    def test_invalid_sizes_reserves_or_paths_fail_without_mutating_inputs(self):
        before = json_bytes(self.allocate([]).record())
        for budgets in (replace(self.budgets, file_bytes=True), replace(self.budgets, site_reserve_bytes=900),
                        replace(self.budgets, file_bytes=50 * capacity.MIB)):
            with self.subTest(budgets=budgets), self.assertRaises(ContractError):
                self.allocate([], budgets=budgets)
        for artifact in (replace(self.artifact("bad"), path="site/../private.json"),
                         replace(self.artifact("bad"), bytes=-1),
                         replace(self.artifact("bad"), sha256="0" * 64),
                         self.artifact("oversize", 601)):
            with self.subTest(artifact=artifact), self.assertRaises(ContractError):
                self.allocate([artifact])
        self.assertEqual(before, json_bytes(self.allocate([]).record()))

    def test_conflicting_hash_sizes_or_immutable_replacements_are_rejected(self):
        artifact = self.artifact("same")
        for values in ([artifact, replace(artifact, bytes=399)],
                       [artifact, replace(artifact, path=artifact.path.replace("/data/", "/objects/"), bytes=399)]):
            with self.subTest(values=values), self.assertRaisesRegex(ContractError, "inconsistent byte sizes"):
                self.allocate(values)
        # Release IDs name input contracts, not content hashes. Even here, the
        # placement owner rejects changed bytes at an existing immutable path.
        old = replace(artifact, path="site/releases/" + "a" * 64 + ".json")
        new = replace(self.artifact("changed"), path=old.path)
        with self.assertRaisesRegex(ContractError, "Immutable capacity object changed"):
            self.allocate([new], [replace(self.empty, site_bytes=400, history_bytes=400)],
                          [capacity.Placement(old, "items")])

    def test_duplicate_ownership_and_understated_measurements_are_rejected(self):
        artifact = self.artifact("same")
        owned = capacity.Placement(artifact, "items")
        with self.assertRaisesRegex(ContractError, "duplicate physical ownership"):
            self.allocate([], stored=[owned, owned])
        with self.assertRaisesRegex(ContractError, "smaller than stored"):
            self.allocate([], stored=[owned])
        with self.assertRaisesRegex(ContractError, "outside its logical topic"):
            self.allocate([], stored=[replace(owned, partition="missing")])

    def test_planning_has_no_filesystem_process_or_network_effects(self):
        with patch("builtins.open", side_effect=AssertionError("filesystem")), \
                patch("subprocess.run", side_effect=AssertionError("process")), \
                patch("socket.socket", side_effect=AssertionError("network")):
            result = self.allocate([self.artifact("new")])
        self.assertEqual(len(result.placements), 1)


if __name__ == "__main__":
    unittest.main()
