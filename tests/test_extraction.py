"""Small real Git fixtures prove selection, repeatability and promotion boundaries."""

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from wikibuild import extraction, snapshots
from wikibuild.adapters import items_loot
from wikibuild.exceptions import Exceptions
from wikibuild.source import Source
from wikibuild.storage import ContractError, git, json_bytes

ROOT = Path(__file__).resolve().parents[1]
PROJECT = json.loads((ROOT / "project.json").read_text())


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.parent = ROOT / ".local/test-extraction"
        self.parent.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(dir=self.parent))
        self.wiki = self.work / "wiki"
        self.source = self.work / "source"
        self.wiki.mkdir()
        self.source.mkdir()
        git(self.source, "init", "--initial-branch=main")
        git(self.source, "config", "user.name", "Wiki tests")
        git(self.source, "config", "user.email", "wiki-tests@example.invalid")
        self.put("Catalog/steam-build.json", {"app_id": "2393970", "build_id": "100"})
        self.put("Catalog/generator.json", {"schema": 1})
        self.put("Catalog/coverage.json", {"objects": 3, "decode_failures": []})
        self.put("Catalog/inputs.jsonl", [{"path": "fixture", "sha256": "fixture"}])
        self.item = {"id": "fixture.assets#1", "name": "internal", "game_objects": ["fixture.assets#3"],
                     "fields": {name: (0 if isinstance(kind, tuple) else kind()) for name, kind in items_loot.ITEM_FIELDS.items()},
                     "references": [{"field": "/_ToolTipText", "status": "resolved", "target": "fixture.assets#2"}]}
        self.item["fields"]["MaxStack"] = 7
        self.item["fields"]["_LootCountRange"] = {"x": 1, "y": 2}
        self.put(items_loot.INPUTS[0], [self.item])
        self.put(items_loot.INPUTS[1], [{"manager": "fixture.assets#4", "tag": "Food", "items": [
            {"guid": "a" * 32, "status": "resolved", "icon_components": [self.item["id"]], "localized_tooltips": "DO NOT EXPORT"}]}])
        self.put(items_loot.INPUTS[2], [{"id": "fixture.assets#5", "name": "Supplies", "rates": [
            {"_spawnLootTag": "Food", "_spawnRateRange": 0.25, "_stackFactor": 1.0}]}])
        self.put(items_loot.INPUTS[3], [{"id": "fixture.assets#6", "name": "Chest", "class": "Object_Interact",
            "fields": {"_ColumLineCount": {"x": 2, "y": 3}, "_ContainerType": 1, "_DoorOpenCloseSeconds": 1.0, "_OpenSecondsFactor": 1.5},
            "loot_sets": ["fixture.assets#5"]}])
        self.put("Catalog/objects/fixture.assets.jsonl", [
            {"id": "fixture.assets#2", "fields": {"_Infos": [
                {"languageType": 1, "_ItemName": "NON ENGLISH"},
                {"languageType": 2, "_ItemName": "Canned beans"}]}},
            {"id": "fixture.assets#999", "fields": {"unused": "DO NOT EXPORT"}}])
        self.put("Catalog/unselected.jsonl", [{"unselected": "DO NOT EXPORT"}])
        self.commit()

    def tearDown(self):
        try:
            shutil.rmtree(self.work)
        except PermissionError:
            print(f"Retained protected test fixture: {self.work}")

    def put(self, path, data):
        target = self.source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in data) if path.endswith(".jsonl") else json_bytes(data))

    def commit(self):
        git(self.source, "add", "-A")
        git(self.source, "commit", "-m", "Synthetic source state")
        self.receipt = snapshots.register(self.wiki, PROJECT, self.source)

    def extract(self):
        return extraction.run(self.wiki, PROJECT, self.source, self.receipt)

    def rows(self, result):
        return [json.loads(line) for line in extraction.artifact(self.wiki, result["records"]).read_text().splitlines()]

    def test_selected_facts_and_english_name_have_source_evidence(self):
        result, metrics = self.extract()
        rows = self.rows(result)
        item = rows[0]
        self.assertEqual("Canned beans", item["name"])
        self.assertEqual(7, item["facts"]["MaxStack"])
        self.assertEqual("items-equipment", item["topic"])
        self.assertEqual("fixture.assets#2", item["evidence"][1]["object"])
        self.assertEqual(0.25, rows[2]["facts"]["rates"][0]["_spawnRateRange"])
        self.assertNotIn("probability", json.dumps(rows))
        self.assertNotIn("DO NOT EXPORT", json.dumps(rows))
        self.assertNotIn("NON ENGLISH", json.dumps(rows))
        self.assertNotIn("Catalog/unselected.jsonl", result["dependencies"])
        self.assertGreater(metrics["source_bytes_read"], 0)
        self.assertIn("combat", result["remaining_topics"])
        self.assertEqual("not-created", result["wiki_release"])

    def test_noop_reuses_validated_outputs_without_source_reads_or_rewrites(self):
        first, _ = self.extract()
        pointer = self.wiki / ".local/extraction-latest.json"
        stamp = pointer.stat().st_mtime_ns
        second, metrics = self.extract()
        self.assertEqual(first, second)
        self.assertEqual(stamp, pointer.stat().st_mtime_ns)
        self.assertEqual({"reused": True, "source_bytes_read": 0}, metrics)

    def test_irrelevant_source_change_reuses_facts_but_records_new_snapshot(self):
        first, _ = self.extract()
        self.put("Catalog/unselected.jsonl", [{"irrelevant": "different"}])
        self.commit()
        second, metrics = self.extract()
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual(first["records"], second["records"])
        self.assertTrue(metrics["reused"])
        self.assertEqual(0, metrics["source_bytes_read"])

    def test_unknown_field_logs_exception_and_supported_work_completes(self):
        self.item["fields"]["_NewFeature"] = "uninterpreted contents"
        self.put(items_loot.INPUTS[0], [self.item])
        self.commit()
        result, _ = self.extract()
        report = json.loads(extraction.artifact(self.wiki, result["exceptions"]).read_text())
        self.assertEqual(1, report["group_count"])
        self.assertEqual("new-field", report["groups"][0]["code"])
        self.assertEqual(4, len(self.rows(result)))
        self.assertNotIn("_NewFeature", self.rows(result)[0]["facts"])

    def test_previously_missing_dependency_is_revisited_when_it_appears(self):
        path = "Catalog/objects/fixture.assets.jsonl"
        saved = (self.source / path).read_bytes()
        (self.source / path).unlink()
        self.commit()
        first, _ = self.extract()
        self.assertEqual("internal", self.rows(first)[0]["name_status"])
        (self.source / path).write_bytes(saved)
        self.commit()
        second, metrics = self.extract()
        self.assertFalse(metrics["reused"])
        self.assertEqual("Canned beans", self.rows(second)[0]["name"])

    def test_new_nested_field_is_logged_but_never_copied(self):
        self.item["fields"]["_LootCountRange"]["future"] = "DO NOT EXPORT"
        self.put(items_loot.INPUTS[0], [self.item])
        self.commit()
        result, _ = self.extract()
        self.assertNotIn("future", self.rows(result)[0]["facts"]["_LootCountRange"])
        report = json.loads(extraction.artifact(self.wiki, result["exceptions"]).read_text())
        self.assertEqual("Icon_Info/_LootCountRange/future", report["groups"][0]["pattern"])

    def test_unsupported_source_class_keeps_links_and_other_records(self):
        self.put(items_loot.INPUTS[3], [{"id": "fixture.assets#6", "name": "New source", "class": "FutureClass",
                                      "fields": {"new": 12}, "loot_sets": ["fixture.assets#5"]}])
        self.commit()
        result, _ = self.extract()
        row = self.rows(result)[-1]
        self.assertEqual({}, row["facts"])
        self.assertEqual("fixture.assets#5", row["relationships"][0]["target_source_id"])
        self.assertEqual(4, len(self.rows(result)))

    def test_corrupt_output_is_rejected_and_never_overwritten(self):
        result, _ = self.extract()
        path = self.wiki / result["records"]["path"]
        path.write_text("investigation")
        with self.assertRaisesRegex(ContractError, "modified"):
            self.extract()
        self.assertEqual("investigation", path.read_text())

    def test_missing_input_is_execution_failure_and_preserves_last_success(self):
        first, _ = self.extract()
        pointer = self.wiki / ".local/extraction-latest.json"
        old = pointer.read_bytes()
        (self.source / items_loot.INPUTS[1]).unlink()
        self.commit()
        with self.assertRaisesRegex(ContractError, "Missing"):
            self.extract()
        self.assertEqual(old, pointer.read_bytes())
        self.assertEqual(first, extraction.read(self.wiki, first["run_id"]))

    def test_failure_before_pointer_promotion_reuses_completed_receipt_on_retry(self):
        first, _ = self.extract()
        pointer = self.wiki / ".local/extraction-latest.json"
        old = pointer.read_bytes()
        self.item["fields"]["MaxStack"] = 9
        self.put(items_loot.INPUTS[0], [self.item])
        self.commit()
        original = extraction.write_changed

        def fail_pointer(path, data):
            if path == pointer:
                raise OSError("injected pointer failure")
            return original(path, data)

        with patch("wikibuild.extraction.write_changed", side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, "injected"):
                self.extract()
        self.assertEqual(old, pointer.read_bytes())
        second, metrics = self.extract()
        self.assertTrue(metrics["reused"])
        self.assertNotEqual(first["records"], second["records"])
        self.assertEqual(9, self.rows(second)[0]["facts"]["MaxStack"])

    def test_reader_uses_pinned_git_bytes_and_drains_partial_blob(self):
        self.put(items_loot.INPUTS[0], [{"working_tree": "changed"}])
        with Source(self.source, self.receipt["source_commit"]) as source:
            rows = source.records("Catalog/objects/fixture.assets.jsonl")
            self.assertEqual("fixture.assets#2", next(rows)["id"])
            rows.close()
            self.assertEqual(self.item["id"], list(source.records(items_loot.INPUTS[0]))[0]["id"])
            with self.assertRaisesRegex(ContractError, "Missing"):
                source.json("../outside")

    def test_grouping_is_bounded_and_independent_of_record_order(self):
        reports = []
        for ids in [range(100), reversed(range(100))]:
            issues = Exceptions()
            for identity in ids:
                issues.add("new", "combat", "NewClass", "Needs a rule", str(identity))
            reports.append(issues.report())
        self.assertEqual(reports[0], reports[1])
        self.assertEqual(100, reports[0]["occurrences"])
        self.assertEqual(8, len(reports[0]["groups"][0]["examples"]))


if __name__ == "__main__":
    unittest.main()
