"""Resolve referenced objects without exporting unrelated catalog objects."""

import unittest
from types import SimpleNamespace

from wikibuild.adapters import prefabs
from wikibuild import model
from wikibuild.exceptions import Exceptions


class PrefabTests(unittest.TestCase):
    def source(self, index):
        source = SimpleNamespace(records=lambda path: iter(index))
        prefabs.prepare(source, Exceptions())
        return source

    def link(self, target, predicate="model"):
        return {"relationships": [{"predicate": predicate, "target_source_id": target}]}

    def test_only_selected_references_export_identity_and_inverse_component_evidence(self):
        source = self.source([
            {"id": "b#1", "type": "GameObject", "name": "Motor", "paths": ["motor.prefab"]},
            {"id": "b#2", "type": "GameObject", "name": "Unselected private object"},
        ])
        prefabs.observe(source, self.link("b#1"))
        prefabs.observe(source, {"source_id": "b#3", "component": {"class": "Build_Info"},
            "game_objects": ["b#1"], "evidence": [{"path": "Catalog/objects/b.jsonl", "object": "b#3",
                                                   "fields": ["/_origHP_All"], "record_sha256": "hash"}]})
        issues = Exceptions()
        rows = list(prefabs.extract(source, issues))
        self.assertEqual(["b#1"], [row["source_id"] for row in rows])
        self.assertEqual({"engine_type": "GameObject"}, rows[0]["facts"])
        self.assertEqual(["motor.prefab"], rows[0]["asset_paths"])
        self.assertEqual("b#3", rows[0]["relationships"][0]["target_source_id"])
        self.assertEqual("inverse", rows[0]["relationships"][0]["direction"])
        self.assertEqual(["/m_GameObject"], rows[0]["evidence"][1]["fields"])
        self.assertEqual(0, issues.report()["occurrences"])

    def test_prefab_identity_resolves_models_with_several_components_and_corpses_without_ai(self):
        source = self.source([{"id": "b#1", "type": "GameObject", "name": "Model"},
                              {"id": "b#2", "type": "GameObject", "name": "Corpse"}])
        prefabs.observe(source, self.link("b#1"))
        prefabs.observe(source, self.link("b#2", "headless-prefab"))
        issues = Exceptions()
        rows = list(prefabs.extract(source, issues))
        for key, kind in (("engine", "vehicle-rule"), ("build", "building-piece")):
            rows.append({"observation_key": key, "source_id": "b#" + key, "kind": kind, "game_objects": ["b#1"]})
        assignments = {row["observation_key"]: row["observation_key"] for row in rows}
        index = model.targets_index(rows, assignments)
        for target, predicate in (("b#1", "model"), ("b#2", "headless-prefab")):
            row = {**self.link(target, predicate), "topic": "items-equipment", "source_id": "b#9"}
            semantic, _ = model.relationships(row, index, {}, issues)
            self.assertEqual([next(r["observation_key"] for r in rows if r["source_id"] == target)], semantic[0]["targets"])
            self.assertNotIn("gaps", semantic[0])
        self.assertEqual(0, issues.report()["occurrences"])

    def test_new_type_or_missing_target_is_reported_without_losing_supported_identity(self):
        source = self.source([{"id": "b#1", "type": "GameObject"}, {"id": "b#2", "type": "Mesh"}])
        for target in ("b#1", "b#2", "b#3"):
            prefabs.observe(source, self.link(target))
        issues = Exceptions()
        rows = list(prefabs.extract(source, issues))
        self.assertEqual(["b#1"], [row["source_id"] for row in rows])
        self.assertEqual({"prefab-target-type", "missing-prefab"}, {row["code"] for row in issues.report()["groups"]})

    def test_no_reference_does_not_read_the_index(self):
        source = self.source([])
        def unexpected(path):
            raise AssertionError("Unnecessary catalog read")
        source.records = unexpected
        prefabs.observe(source, {"relationships": []})
        self.assertEqual([], list(prefabs.extract(source, Exceptions())))

    def test_generic_domain_reference_prefers_exact_object_over_attached_components(self):
        source = self.source([{"id": "b#1", "type": "GameObject", "name": "Tree"},
                              {"id": "b#4", "type": "MonoBehaviour", "name": "Other"}])
        prefabs.observe(source, self.link("b#1", "vegetation"))
        prefabs.observe(source, self.link("b#4", "configuration"))
        issues = Exceptions()
        rows = list(prefabs.extract(source, issues))
        self.assertEqual(1, len(rows))
        prefab = rows[0]["observation_key"]
        for key in ("build", "sound"):
            rows.append({"observation_key": key, "source_id": "b#" + key,
                         "kind": "construction-rule", "game_objects": ["b#1"]})
        indexes = model.targets_index(rows, {row["observation_key"]: row["observation_key"] for row in rows})
        semantic, _ = model.relationships({**self.link("b#1", "vegetation"), "topic": "biomes-resources",
                                           "source_id": "b#source"}, indexes, {}, issues)
        self.assertEqual([prefab], semantic[0]["targets"])
        self.assertNotIn("gaps", semantic[0])
        self.assertEqual(0, issues.report()["occurrences"])


if __name__ == "__main__":
    unittest.main()
