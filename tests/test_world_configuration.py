"""Configuration additions preserve order, privacy and independent valid facts."""

import json
import unittest

from wikibuild.adapters.components import BY_CLASS
from wikibuild.adapters.schema import Selection
from wikibuild.exceptions import Exceptions


class WorldConfigurationTests(unittest.TestCase):
    def select(self, key, data, references=()):
        spec = BY_CLASS[key]
        issues = Exceptions()
        selector = Selection({"id": "fixture#1", "fields": data, "references": references}, spec, issues)
        return selector.select(data, spec.fields), selector, issues.report()

    def test_terrain_layer_gap_preserves_later_reference_position(self):
        facts, selector, report = self.select(("Terrain", "Terrain_Loader_Manager"), {
            "_TerraSize": 512, "_terraWorldSeed": "PRIVATE SEED",
            "_BaseBigTerrains": {"baseBigTerraTops": [], "BigTerraNames": []},
            "_BiomesLayers": ["CHANGED SHAPE", {"terrainTops": [{"m_AssetGUID": "forest"}],
                "BigTerraNames": ["Forest"], "newPopulationRule": "UNREVIEWED"}],
        }, [{"field": "/_BiomesLayers/1/terrainTops/0", "status": "resolved", "targets": ["fixture#2"]}])
        self.assertEqual([None, {"terrainTops": [None], "BigTerraNames": ["Forest"]}], facts["_BiomesLayers"])
        self.assertEqual(512, facts["_TerraSize"])
        self.assertEqual("/_BiomesLayers/1/terrainTops/0", selector.links[0]["source_field"])
        self.assertEqual(["fixture#2"], selector.links[0]["target_source_ids"])
        self.assertNotIn("PRIVATE", json.dumps(facts))
        self.assertTrue(any(g["code"] == "new-field" and g["pattern"].endswith("/newPopulationRule") for g in report["groups"]))

    def test_npc_transition_gap_does_not_shift_default_end_time(self):
        transition = {"_FadeDuration": 0.2, "_Speed": 1.5, "_NormalizedStartTime": {"float": "nan"},
                      "_Clip": "CLIP PAYLOAD", "_Events": {"_NormalizedTimes": [0.1, {"float": "inf"}, {"float": "nan"}],
                          "_Callbacks": "PRIVATE CALLBACKS", "_Names": []}}
        facts, _, report = self.select(("Creature", "NPC_Anims_Settings"), {
            "_NPC_Anim": {**dict.fromkeys("Walks Runs Crouchs CrouchsF Swims SwimsF MoveAttacks".split(), []),
                          "Walks": [transition], "futureAttackRule": 5},
            "_zombieTrapAnims": [{"speed": 2, "endRate": 0.9, "clip": "CLIP PAYLOAD"}],
        })
        self.assertEqual([0.1, None, {"float": "nan"}], facts["_NPC_Anim"]["Walks"][0]["_Events"]["_NormalizedTimes"])
        self.assertEqual(2, facts["_zombieTrapAnims"][0]["speed"])
        self.assertNotIn("PAYLOAD", json.dumps(facts))
        self.assertNotIn("PRIVATE", json.dumps(facts))
        self.assertEqual({"new-field", "unsupported-field-type"}, {g["code"] for g in report["groups"]})

    def test_stationary_bike_does_not_export_unused_inherited_propulsion(self):
        facts, _, report = self.select(("Bicycle", "SBPScripts.LockBicycleController"), {
            "wheelTorque": 100, "sprintWheelTorque": 200, "_useExternalMoveInput": 1,
            "_useExternalSprintInput": 1, "fastMoveHotKey": 304, "topSpeed": 999,
            "torque": 999, "wayPointSystem": "PRIVATE RIDE", "newGeneratorRule": 4,
        })
        self.assertEqual(200, facts["sprintWheelTorque"])
        self.assertNotIn("topSpeed", facts)
        self.assertNotIn("torque", facts)
        self.assertNotIn("PRIVATE", json.dumps(facts))
        self.assertEqual(1, report["group_count"])
        self.assertTrue(report["groups"][0]["pattern"].endswith("/newGeneratorRule"))

    def test_map_marker_retains_visibility_but_excludes_visit_save_and_mutable_text(self):
        facts, _, report = self.select(("CompassPro", "CompassNavigatorPro.CompassProPOI"), {
            "visibleDistanceOverride": 500, "visibleMinDistanceOverride": 0,
            "visitedDistanceOverride": 20, "radius": 0, "visibility": 0, "titleVisibility": 0,
            "canBeVisited": 1, "hideWhenVisited": 1, "miniMapVisibility": 1,
            "title": "PRIVATE MARKER", "visitedText": "PRIVATE TEXT", "isVisited": 1, "id": 55,
        })
        self.assertEqual(500, facts["visibleDistanceOverride"])
        self.assertNotIn("isVisited", facts)
        self.assertNotIn("PRIVATE", json.dumps(facts))
        self.assertEqual(0, report["group_count"])

    def test_composition_counts_conserve_valid_and_invalid_placements_without_geometry(self):
        data = {"PropsRefNoRepeat": [{"m_FileID": 0, "m_PathID": 0}] * 2, "PropsRefNoRepeatBig": [],
                "ScenePropsInfoBig": [], "ScenePropsInfo": [
                    {"protoRefIndex": 1, "localPos": "PRIVATE GEOMETRY"}, {"protoRefIndex": 0},
                    {"protoRefIndex": 1, "futureRule": "UNREVIEWED"}, {"protoRefIndex": -1},
                    {"protoRefIndex": 2}, {"protoRefIndex": True}, "UNSUPPORTED"]}
        facts, selector, report = self.select(("Build_System", "ScenePropSpawner"), data)
        expected = {"counts": [{"protoRefIndex": 0, "count": 1}, {"protoRefIndex": 1, "count": 2}],
                    "total_count": 7, "unresolved_count": 4}
        self.assertEqual(expected, facts["ScenePropsInfo"])
        self.assertEqual(5, report["occurrences"])
        self.assertEqual({"new-field", "prototype-index-range", "unsupported-field-type"},
                         {group["code"] for group in report["groups"]})
        self.assertIn("/ScenePropsInfo", selector.evidence)
        self.assertFalse(any(path.startswith("/ScenePropsInfo/") for path in selector.evidence))
        self.assertNotIn("PRIVATE", json.dumps(facts))
        self.assertNotIn("UNREVIEWED", json.dumps(facts))
        reordered, _, _ = self.select(("Build_System", "ScenePropSpawner"),
                                     {**data, "ScenePropsInfo": list(reversed(data["ScenePropsInfo"]))})
        self.assertEqual(facts, reordered)

    def test_composition_evidence_and_facts_stay_bounded_as_placements_repeat(self):
        data = {"PropsRefNoRepeat": [{"m_FileID": 0, "m_PathID": 0}], "PropsRefNoRepeatBig": [],
                "ScenePropsInfoBig": [], "ScenePropsInfo": [{"protoRefIndex": 0}] * 10000}
        facts, selector, report = self.select(("Build_System", "ScenePropSpawner"), data)
        self.assertEqual(10000, facts["ScenePropsInfo"]["counts"][0]["count"])
        self.assertLess(len(json.dumps(facts)), 300)
        self.assertEqual(3, len(selector.evidence))
        self.assertEqual(0, report["group_count"])


if __name__ == "__main__":
    unittest.main()
