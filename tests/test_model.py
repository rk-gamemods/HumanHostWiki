"""Canonical relationships must preserve source evidence and explicit gaps."""

import copy
import unittest

from test_identity import observation
from wikibuild import model
from wikibuild.exceptions import Exceptions


class ModelTests(unittest.TestCase):
    def test_spawn_prefab_resolves_creature_separately_from_its_controller(self):
        from wikibuild.adapters.components import BY_CLASS
        rows = []
        for source, key in (("bundle#2", ("AI", "Zombie_Agent")), ("bundle#3", ("Creature", "Zombie_Input"))):
            row = observation(source=source)
            row.update(kind=BY_CLASS[key].kind, game_objects=["bundle#9"])
            rows.append(row)
        assignments = {row["observation_key"]: row["source_id"] for row in rows}
        indexes = model.targets_index(rows, assignments)
        source = observation()
        source["relationships"] = [{"predicate": "spawns-prefab", "target_source_id": "bundle#9"}]
        issues = Exceptions()
        semantic, resolved = model.relationships(source, indexes, {}, issues)
        self.assertEqual(["bundle#2"], semantic[0]["targets"])
        self.assertEqual("resolved", resolved[0]["status"])
        self.assertEqual(0, issues.report()["group_count"])

    def project(self, row, indexes, metadata=None, blob="a"):
        issues = Exceptions()
        projected = model.project(row, "e-source", (*indexes, {}), metadata or {},
                                  {"Catalog/views/items.jsonl": {"git_blob": blob * 40, "sha256": blob * 64}}, issues)
        return projected, issues.report()

    def test_source_id_and_evidence_change_does_not_change_semantic_revision(self):
        first = observation()
        first["relationships"] = [{"predicate": "repair-item", "source_field": "/repair", "target_source_id": "bundle#2"}]
        indexes = ({"bundle#2": {"e-target"}}, {}, {"e-target": "item"})
        before, _ = self.project(first, indexes)
        second = observation(source="changed#9")
        second["relationships"] = [{"predicate": "repair-item", "source_field": "/repair", "target_source_id": "changed#8"}]
        indexes = ({"changed#8": {"e-target"}}, {}, {"e-target": "item"})
        after, _ = self.project(second, indexes, blob="b")
        self.assertEqual(before["revision_id"], after["revision_id"])
        self.assertNotEqual(before["provenance"], after["provenance"])

    def test_multiple_targets_are_explicit_and_known_values_survive(self):
        row = observation()
        row["relationships"] = [{"predicate": "repair-item", "source_field": "/repair", "target_source_id": "bundle#2"}]
        result, report = self.project(row, ({"bundle#2": {"e-a", "e-b"}}, {}, {"e-a": "item", "e-b": "item"}))
        self.assertEqual({"value": 1}, result["semantic"]["facts"])
        self.assertEqual("ambiguous-target", result["semantic"]["relationships"][0]["gaps"][0]["status"])
        self.assertEqual(1, report["occurrences"])

    def test_technical_fallback_does_not_claim_domain_resolution(self):
        row = observation()
        row["relationships"] = [{"predicate": "repair-item", "source_field": "/repair", "target_source_id": "bundle#2"}]
        index = ({}, {("GameObject", None, None): "e-summary"}, {"e-summary": "asset"})
        result, report = self.project(row, index, {"bundle#2": {"type": "GameObject"}})
        self.assertEqual("technical-summary", result["provenance"]["resolved_targets"][0]["status"])
        self.assertEqual("domain-target-not-cataloged", result["semantic"]["relationships"][0]["gaps"][0]["status"])
        self.assertEqual(1, report["occurrences"])

    def test_unresolved_guid_without_explicit_status_still_records_gap(self):
        row = observation()
        row["relationships"] = [{"predicate": "eligible-item", "source_field": "/items", "guid": "unresolved-guid", "target_source_ids": []}]
        result, report = self.project(row, ({}, {}, {}))
        self.assertEqual("unresolved", result["semantic"]["relationships"][0]["gaps"][0]["status"])
        self.assertEqual(1, report["occurrences"])


if __name__ == "__main__":
    unittest.main()
