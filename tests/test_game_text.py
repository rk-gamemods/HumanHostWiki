"""English game text and tooltip bindings survive extraction and model projection."""

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from test_components import CatalogFixture
from wikibuild import extraction, game_text, model
from wikibuild.adapters import components
from wikibuild.adapters.schema import Selection
from wikibuild.exceptions import Exceptions


ROOT = Path(__file__).resolve().parents[1]
MEMBERS = """_Dura_Title _BlockDura _Damage_Title _HitDown_Title _BladeHit_Title
_GunFireRate_Title _SingleShot_Title _GunMaxMag_Title _GunAmmoType_Title _BowAmmoType_Str
_Quality_Title _BladeHit_Instruct _HeadShot_Instruct _ArrowDamage _ArrowRange _ArrowSpeed
_ShootRange_Title _Recoil_Title _DummyRound_Title _Jam_Title _GatheringTool
_GatheringToolSmallAxe""".split()


def language(identity="fixture#2", text="Execute: "):
    return {"id": identity, "script": {"assembly": "Language", "class": "Language_Text"},
            "fields": {"_Infos": [{"languageType": 2, "text": text},
                                  {"languageType": 0, "text": "NON ENGLISH"}]}}


def tooltip_set(targets, identity="fixture#1"):
    return {"id": identity, "script": {"assembly": "UI", "class": "DynamicToolTipSet"},
            "fields": {"data": {member: {"m_FileID": 0,
                                          "m_PathID": int(targets[member].rsplit("#", 1)[1]) if member in targets else 0}
                                for member in MEMBERS},
                       "m_Name": "INTERNAL NAME", "m_Enabled": 1,
                       "m_GameObject": {"m_FileID": 0, "m_PathID": 0},
                       "m_Script": {"m_FileID": 0, "m_PathID": 100}},
            "references": [{"field": "/data/" + member, "status": "resolved", "target": target}
                           for member, target in targets.items()]}


class GameTextTests(unittest.TestCase):
    def select(self, class_name, data):
        spec = components.BY_CLASS[("Language", class_name)]
        issues = Exceptions()
        selector = Selection({"id": "fixture#2", "fields": data}, spec, issues)
        return selector.select(data, spec.fields), selector, issues.report()

    def extract(self, records):
        index = [{"id": record["id"], "type": "MonoBehaviour", **record["script"],
                  "record": {"sha256": "verified"}}
                 for record in sorted(records, key=lambda record: record["id"])]
        source = CatalogFixture(index, {record["id"]: record for record in records})
        issues = Exceptions()
        components.prepare(source, issues)
        rows = list(components.extract(source, issues))
        for row in rows:
            row["topic"] = "items-equipment" if row["kind"] == "equipment" else "technical-reference"
        return rows, issues

    def project(self, records):
        rows, issues = self.extract(records)
        assignments = {row["observation_key"]: "entity-" + str(index) for index, row in enumerate(rows)}
        indexes = model.targets_index(rows, assignments)
        dependencies = {locator["path"]: {"git_blob": "fixture", "sha256": "verified"}
                        for row in rows for locator in row["evidence"]}
        result = [model.project(row, assignments[row["observation_key"]], indexes, {}, dependencies, issues)
                  for row in rows]
        self.assertEqual(0, issues.report()["occurrences"])
        return result

    def test_language_text_selects_english_by_enum_and_preserves_whitespace_and_evidence(self):
        rows, issues = self.extract([language()])
        row = next(row for row in rows if row["kind"] == "configuration")
        self.assertEqual({"text": "Execute: "}, row["facts"])
        self.assertEqual("technical-reference", row["topic"])
        self.assertEqual(["/_Infos/0/languageType", "/_Infos/0/text"], row["evidence"][0]["fields"])
        self.assertEqual("verified", row["evidence"][0]["record_sha256"])
        self.assertNotIn("NON ENGLISH", json.dumps(rows))
        self.assertEqual(0, issues.report()["occurrences"])

    def test_missing_ambiguous_or_malformed_english_keeps_a_null_fact_and_gap(self):
        cases = [[], [{"languageType": 0, "text": "Not English"}],
                 [{"languageType": 2, "text": "A"}, {"languageType": 2, "text": "B"}],
                 [{"languageType": "2", "text": "Wrong enum type"}],
                 [{"languageType": 2.0, "text": "Wrong enum type"}], None]
        for infos in cases:
            with self.subTest(infos=infos):
                facts, _, report = self.select("Language_Text", {"_Infos": infos})
                self.assertEqual({"text": None}, facts)
                self.assertGreater(report["occurrences"], 0)
                self.assertTrue(all(group["pattern"].startswith("Language_Text/_Infos") for group in report["groups"]))
        facts, _, report = self.select("Language_Text", {})
        self.assertEqual({"text": None}, facts)
        self.assertEqual("missing-field", report["groups"][0]["code"])

    def test_absent_or_invalid_text_is_null_but_empty_english_is_preserved(self):
        for entry in ({"languageType": 2}, {"languageType": 2, "text": 42}):
            with self.subTest(entry=entry):
                facts, _, report = self.select("Language_Text", {"_Infos": [entry]})
                self.assertEqual({"text": None}, facts)
                self.assertEqual(1, report["occurrences"])
        facts, _, report = self.select("Language_Text", {"_Infos": [{"languageType": 2, "text": ""}]})
        self.assertEqual({"text": ""}, facts)
        self.assertEqual(0, report["occurrences"])

    def test_tooltip_text_selects_english_name_and_optional_instruction(self):
        record = {"id": "fixture#3", "script": {"assembly": "Language", "class": "Tooltip_Text"},
                  "fields": {"_Infos": [{"languageType": 0, "_ItemName": "NON ENGLISH"},
                                        {"languageType": 2, "_ItemName": "Canned beans",
                                         "_ItemInstruction": "Eat to restore energy.\nKeep the can.",
                                         "_ItemType": "OMITTED TYPE", "_ItemProperty": "OMITTED PROPERTY"}]}}
        rows, issues = self.extract([record])
        row = next(row for row in rows if row["kind"] == "configuration")
        self.assertEqual({"_ItemName": "Canned beans", "_ItemInstruction": "Eat to restore energy.\nKeep the can."}, row["facts"])
        self.assertEqual(["/_Infos/1/_ItemInstruction", "/_Infos/1/_ItemName", "/_Infos/1/languageType"],
                         row["evidence"][0]["fields"])
        self.assertNotIn("NON ENGLISH", json.dumps(rows))
        self.assertNotIn("OMITTED", json.dumps(rows))
        self.assertEqual(0, issues.report()["occurrences"])

    def test_optional_instruction_can_be_absent_or_invalid_without_losing_name(self):
        entry = {"languageType": 2, "_ItemName": "Beans"}
        facts, _, report = self.select("Tooltip_Text", {"_Infos": [entry]})
        self.assertEqual({"_ItemName": "Beans"}, facts)
        self.assertEqual(0, report["occurrences"])
        facts, _, report = self.select("Tooltip_Text", {"_Infos": [{**entry, "_ItemInstruction": 3}]})
        self.assertEqual({"_ItemName": "Beans", "_ItemInstruction": None}, facts)
        self.assertEqual("unsupported-field-type", report["groups"][0]["code"])
        facts, _, report = self.select("Tooltip_Text", {"_Infos": []})
        self.assertEqual({"_ItemName": None}, facts)
        self.assertEqual("english-text", report["groups"][0]["code"])

    def test_new_fields_stay_visible_without_exporting_unknown_text(self):
        data = {"_Infos": [{"languageType": 0, "text": "NON ENGLISH", "future": "UNKNOWN"},
                           {"languageType": 2, "text": "Execute: "}], "newRoot": "UNKNOWN"}
        facts, _, report = self.select("Language_Text", data)
        self.assertEqual({"text": "Execute: "}, facts)
        self.assertEqual({"Language_Text/_Infos/*/future", "Language_Text/newRoot"},
                         {group["pattern"] for group in report["groups"]})

    def test_dynamic_tooltip_contract_keeps_all_22_text_references_and_source_paths(self):
        targets = {member: "fixture#" + str(index + 2) for index, member in enumerate(MEMBERS)}
        rows, issues = self.extract([tooltip_set(targets)])
        row = next(row for row in rows if row["kind"] == "equipment")
        self.assertEqual("items-equipment", row["topic"])
        self.assertEqual({"data": {}}, row["facts"])
        self.assertEqual(22, len(row["relationships"]))
        for link in row["relationships"]:
            self.assertEqual("tooltip-text", link["predicate"])
            self.assertEqual("resolved", link["status"])
            self.assertEqual([targets[link["source_field"].removeprefix("/data/")]], link["target_source_ids"])
        self.assertEqual(0, issues.report()["occurrences"])
        spec = components.BY_CLASS[("UI", "Item_Slot_Mgr")]
        self.assertIn("_DyToolTipSet", spec.fields.excluded)
        self.assertNotIn("_DyToolTipSet", spec.fields.selected)

    def test_dynamic_tooltip_field_drift_and_missing_reference_are_gaps(self):
        record = tooltip_set({"_BladeHit_Title": "fixture#2"})
        record["references"] = []
        record["fields"]["data"]["_Future"] = "UNKNOWN"
        rows, issues = self.extract([record])
        row = next(row for row in rows if row["kind"] == "equipment")
        self.assertEqual({"data": {}}, row["facts"])
        self.assertEqual([{"predicate": "tooltip-text", "source_field": "/data/_BladeHit_Title", "status": "missing"}], row["relationships"])
        self.assertEqual({"new-field", "unresolved-reference"}, {group["code"] for group in issues.report()["groups"]})

    def test_labels_follow_model_targets_and_preserve_source_words_without_mutation(self):
        records = [tooltip_set({"_BladeHit_Title": "fixture#2", "_Damage_Title": "fixture#3",
                                "_HitDown_Title": "fixture#4", "_BladeHit_Instruct": "fixture#5"}),
                   language(), language("fixture#3", "Damage: "), language("fixture#4", "Knockdown: "),
                   language("fixture#5", "Execute: When using sharp weapons, follow the game's instruction.\nSecond line.")]
        rows = self.project(records)
        before = copy.deepcopy(rows)
        expected = {"_BladeHit_Title": "Execute: ", "_Damage_Title": "Damage: ", "_HitDown_Title": "Knockdown: ",
                    "_BladeHit_Instruct": records[-1]["fields"]["_Infos"][0]["text"]}
        self.assertEqual(expected, game_text.labels(iter(rows)))
        self.assertEqual(expected, game_text.labels(reversed(rows)))
        self.assertEqual(before, rows)

    def test_labels_omit_missing_unresolved_ambiguous_and_wrong_class_targets(self):
        original = self.project([tooltip_set({"_BladeHit_Title": "fixture#2"}), language()])
        for failure in ("missing", "gap", "technical", "multiple", "wrong-class", "null"):
            with self.subTest(failure=failure):
                rows = copy.deepcopy(original)
                row = next(row for row in rows if row["semantic"]["kind"] == "equipment")
                link = row["semantic"]["relationships"][0]
                target = next(row for row in rows if row["entity_key"] == link["targets"][0])
                if failure == "missing":
                    rows.remove(target)
                elif failure == "gap":
                    link["gaps"] = [{"status": "unresolved"}]
                elif failure == "technical":
                    link["technical_targets"] = ["summary"]
                elif failure == "multiple":
                    link["targets"].append("another")
                elif failure == "wrong-class":
                    target["provenance"]["component"]["class"] = "Tooltip_Text"
                else:
                    target["semantic"]["facts"]["text"] = None
                self.assertEqual({}, game_text.labels(rows))
        self.assertEqual({}, game_text.labels([]))

    def test_multiple_tooltip_sets_must_agree_regardless_of_order(self):
        for other_text, expected in (("Execute: ", {"_BladeHit_Title": "Execute: "}), ("Conflicting", {})):
            with self.subTest(other_text=other_text):
                rows = self.project([tooltip_set({"_BladeHit_Title": "fixture#2"}), language(),
                                     tooltip_set({"_BladeHit_Title": "fixture#4"}, "fixture#3"),
                                     language("fixture#4", other_text)])
                self.assertEqual(expected, game_text.labels(rows))
                self.assertEqual(expected, game_text.labels(reversed(rows)))

    def test_adding_english_field_changes_extraction_contract_hash(self):
        project = json.loads((ROOT / "project.json").read_text())
        path = ROOT / "wikibuild/adapters/technical.py"
        original = Path.read_bytes
        current = original(path)
        field = b'        "_Infos": EnglishText("text"),'
        self.assertIn(field, current)
        without_field = current.replace(field, b"")
        actual = extraction.contract(ROOT, project)
        with patch.object(Path, "read_bytes", lambda p: without_field if p == path else original(p)):
            self.assertNotEqual(actual, extraction.contract(ROOT, project))


if __name__ == "__main__":
    unittest.main()
