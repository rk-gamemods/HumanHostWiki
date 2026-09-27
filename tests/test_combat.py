"""Combat configuration must survive presentation and default-timing markers."""

import json
import unittest

from wikibuild.adapters import components
from wikibuild.adapters.schema import NumberWithSentinel, Selection, component
from wikibuild.exceptions import Exceptions


class CombatTests(unittest.TestCase):
    def test_only_explicit_encoded_float_markers_are_allowed(self):
        spec = component("fixture", "Timing", "combat-rule", "combat",
                         {"times": [NumberWithSentinel(frozenset({"nan"}))]})
        issues = Exceptions()
        selector = Selection({"id": "fixture#1"}, spec, issues)
        data = {"times": [0.25, {"float": "nan"}, {"float": "inf"},
                           {"float": "nan", "private": "DO NOT EXPORT"},
                           float("nan"), True, 1]}
        facts = selector.select(data, spec.fields)
        self.assertEqual([0.25, {"float": "nan"}, None, None, None, None, 1], facts["times"])
        self.assertNotIn("DO NOT EXPORT", json.dumps(facts, allow_nan=False))
        self.assertEqual(4, issues.report()["occurrences"])
        self.assertIn("/times/1", selector.evidence)

    def test_melee_timing_keeps_defaults_and_valid_values_when_new_event_fields_appear(self):
        spec = components.BY_CLASS[("Hand_Tools", "Melee_Anim_Sets")]
        data = {name: 0 for name in spec.fields.selected}
        transition = {"_FadeDuration": 0.2, "_Speed": {"float": "nan"},
                      "_NormalizedStartTime": {"float": "nan"}, "_Clip": "BINARY",
                      "_Events": {"_NormalizedTimes": [0.15, {"float": "nan"}],
                                  "_Callbacks": "CALLBACK PAYLOAD", "_Names": [], "newRule": 1}}
        data.update(_AnimTrans=transition, _AnimTransForShield=transition,
                    _KeepCheckSeconds=0.16, _BounceEndSeconds=0.5, references="UNITY METADATA")
        issues = Exceptions()
        facts = Selection({"id": "fixture#1"}, spec, issues).select(data, spec.fields)
        self.assertEqual(0.16, facts["_KeepCheckSeconds"])
        self.assertEqual(0.5, facts["_BounceEndSeconds"])
        self.assertEqual({"float": "nan"}, facts["_AnimTrans"]["_Events"]["_NormalizedTimes"][1])
        for omitted in ("BINARY", "CALLBACK PAYLOAD", "UNITY METADATA", "newRule"):
            self.assertNotIn(omitted, json.dumps(facts))
        self.assertEqual({"new-field"}, {group["code"] for group in issues.report()["groups"]})


if __name__ == "__main__":
    unittest.main()
