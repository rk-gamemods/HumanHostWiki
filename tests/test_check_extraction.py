"""Independent checks against pinned Git records reject plausible output tampering."""

import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tests._support import fixture_dir

from tools import check_coded_values, check_extraction


ROOT = Path(__file__).resolve().parents[1]
OBJECT_PATH = "Catalog/objects/fixture.jsonl"
MEMBERS = """_Dura_Title _BlockDura _Damage_Title _HitDown_Title _BladeHit_Title
_GunFireRate_Title _SingleShot_Title _GunMaxMag_Title _GunAmmoType_Title _BowAmmoType_Str
_Quality_Title _BladeHit_Instruct _HeadShot_Instruct _ArrowDamage _ArrowRange _ArrowSpeed
_ShootRange_Title _Recoil_Title _DummyRound_Title _Jam_Title _GatheringTool
_GatheringToolSmallAxe""".split()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


class CheckExtractionTests(unittest.TestCase):
    def setUp(self):
        self.work = fixture_dir(self, "check")
        self.source, self.wiki = self.work / "source", self.work / "wiki"
        self.source.mkdir()
        self.wiki.mkdir()
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Wiki checker tests")
        self.git("config", "user.email", "wiki-checker@example.invalid")
        self.raw = [
            {"id": "fixture#1", "script": {"assembly": "UI", "class": "DynamicToolTipSet"},
             "fields": {"data": {name: {"m_FileID": 0, "m_PathID": 2} for name in MEMBERS}},
             "references": [{"field": "/data/" + name, "status": "resolved", "target": "fixture#2"} for name in MEMBERS]},
            {"id": "fixture#2", "script": {"assembly": "Language", "class": "Language_Text"},
             "fields": {"_Infos": [{"languageType": 2, "text": "Execute: "},
                                    {"languageType": 0, "text": "NON ENGLISH"}]}},
            {"id": "fixture#3", "script": {"assembly": "Language", "class": "Tooltip_Text"},
             "fields": {"_Infos": [{"languageType": 0, "_ItemName": "NON ENGLISH"},
                                    {"languageType": 2, "_ItemName": "Beans", "_ItemInstruction": "Eat.\nKeep the can. ",
                                     "_ItemType": "OMITTED", "_ItemProperty": "OMITTED"}]}},
            {"id": "fixture#4", "script": {"assembly": "Language", "class": "Language_Text"},
             "fields": {"_Infos": [{"languageType": 0, "text": "NON ENGLISH"}]}},
            {"id": "fixture#5", "script": {"assembly": "Language", "class": "Language_Text"},
             "fields": {"_Infos": [{"languageType": 2, "text": "First"}, {"languageType": 2, "text": "Second"}]}},
        ]
        facts = [{"data": {}}, {"text": "Execute: "},
                 {"_ItemName": "Beans", "_ItemInstruction": "Eat.\nKeep the can. "}, {"text": None}, {"text": None}]
        evidence = [["/data/" + member for member in MEMBERS], ["/_Infos/0/languageType", "/_Infos/0/text"],
                    ["/_Infos/1/languageType", "/_Infos/1/_ItemName", "/_Infos/1/_ItemInstruction"], ["/_Infos"], ["/_Infos"]]
        self.rows = [{"source_id": raw["id"], "kind": "equipment" if index == 0 else "configuration",
                      "component": dict(raw["script"]), "facts": fact, "name_status": "internal",
                      "fact_scope": "serialized-component-configuration", "relationships": [],
                      "evidence": [{"path": OBJECT_PATH, "object": raw["id"], "fields": fields}]}
                     for index, (raw, fact, fields) in enumerate(zip(self.raw, facts, evidence))]
        self.rows[0]["relationships"] = [{"source_field": "/data/" + name, "predicate": "tooltip-text",
                                           "status": "resolved", "target_source_ids": ["fixture#2"]} for name in MEMBERS]
        self.groups = [{"code": "english-text", "topic": "technical-reference", "pattern": "Language_Text/_Infos",
                        "occurrences": 2, "examples": ["fixture#4", "fixture#5"]}]
        self.pin()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.source), *args], stderr=subprocess.STDOUT).decode().strip()

    def put(self, root, path, data):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def pin(self):
        lines = [encoded(raw) + b"\n" for raw in self.raw]
        self.put(self.source, OBJECT_PATH, b"".join(lines))
        self.index = [{"id": raw["id"], "type": "MonoBehaviour", **raw["script"]} for raw in self.raw]
        for path, records in getattr(self, "supporting", {}).items():
            self.put(self.source, path, b"".join(encoded(raw) + b"\n" for raw in records))
            if path.startswith("Catalog/objects/"):
                self.index.extend({"id": raw["id"], "type": raw.get("type", "MonoBehaviour"),
                                   **raw.get("script", {})} for raw in records)
        self.put(self.source, "Catalog/views/object-index.jsonl", b"".join(encoded(row) + b"\n" for row in self.index))
        self.git("add", "-A")
        self.git("commit", "-m", "Synthetic pinned catalog")
        self.commit = self.git("rev-parse", "HEAD")
        for row, line in zip(self.rows, lines):
            row["evidence"][0]["record_sha256"] = hashlib.sha256(line).hexdigest()

    def outputs(self):
        records = b"".join(encoded(row) + b"\n" for row in self.rows)
        exceptions = encoded({"groups": self.groups})
        self.put(self.wiki, ".local/check-records.jsonl", records)
        self.put(self.wiki, ".local/check-exceptions.json", exceptions)
        self.run = {"source_commit": self.commit, "snapshot_id": "fixture-snapshot", "coverage": {"objects": len(self.index)},
                    "records": {"path": ".local/check-records.jsonl", "sha256": hashlib.sha256(records).hexdigest()},
                    "exceptions": {"path": ".local/check-exceptions.json", "sha256": hashlib.sha256(exceptions).hexdigest()}}
        self.put(self.wiki, ".local/extractions/runs/fixture.json", encoded(self.run))
        self.put(self.wiki, ".local/extraction-latest.json", encoded({"run_id": "fixture"}))

    def check(self, complete=True, write=True):
        if write:
            self.outputs()
        # Match the standalone CLI's tools-directory import environment.
        with patch.dict(sys.modules, {"check_coded_values": check_coded_values}):
            return check_extraction.check(self.wiki, self.source, complete)

    def test_pinned_text_exact_whitespace_null_gaps_and_all_tooltip_members_pass(self):
        first = self.check()
        self.assertEqual("passed", first["status"])
        self.assertEqual(5, first["observations_checked"])
        self.assertEqual("all", first["sampling"])
        # A dirty working copy must never replace the committed English text.
        self.put(self.source, OBJECT_PATH, b"not even a JSON record\n")
        self.assertEqual(first, self.check())
        self.assertEqual("passed", self.check(complete=False)["status"])

    def test_builder_outputs_pass_the_independent_checker(self):
        from test_components import CatalogFixture
        from wikibuild.adapters import components
        from wikibuild.exceptions import Exceptions
        index = [{**row, "record": {"sha256": self.rows[index]["evidence"][0]["record_sha256"]}}
                 for index, row in enumerate(self.index)]
        source = CatalogFixture(index, {raw["id"]: raw for raw in self.raw})
        issues = Exceptions()
        components.prepare(source, issues)
        self.rows = list(components.extract(source, issues))
        self.groups = issues.report()["groups"]
        self.assertEqual("passed", self.check()["status"])

    def test_changed_missing_extra_and_non_english_text_facts_are_rejected(self):
        originals = copy.deepcopy(self.rows)
        changes = [(1, {"text": "Execute:"}), (1, {}), (1, {"text": "NON ENGLISH"}),
                   (2, {"_ItemName": "Beans"}), (2, {"_ItemName": "Beans", "_ItemInstruction": "Eat."}),
                   (3, {}), (3, {"text": "Guessed"}), (4, {"text": "First"}),
                   (1, {"text": "Execute: ", "_Infos": self.raw[1]["fields"]["_Infos"]})]
        for index, facts in changes:
            with self.subTest(index=index, facts=facts):
                self.rows = copy.deepcopy(originals)
                self.rows[index]["facts"] = facts
                with self.assertRaisesRegex(ValueError, "Derived text facts differ"):
                    self.check()

    def test_missing_wrong_and_overcounted_gaps_are_rejected(self):
        original = copy.deepcopy(self.groups)
        for groups in ([], [{**original[0], "occurrences": 1}], [{**original[0], "occurrences": 3}],
                       [{**original[0], "code": "new-field"}], [{**original[0], "topic": "items-equipment"}]):
            with self.subTest(groups=groups):
                self.groups = groups
                with self.assertRaisesRegex(ValueError, "Derived text gap count differs"):
                    self.check()

    def test_gap_report_hash_is_verified(self):
        self.outputs()
        self.put(self.wiki, ".local/check-exceptions.json", encoded({"groups": []}))
        with self.assertRaisesRegex(ValueError, "Exception report does not match"):
            self.check(write=False)
        self.run.pop("exceptions")
        self.put(self.wiki, ".local/extractions/runs/fixture.json", encoded(self.run))
        with self.assertRaisesRegex(ValueError, "Missing exception report"):
            self.check(write=False)

    def test_sampling_uses_gap_lower_bounds_and_all_checks_exact_counts(self):
        self.raw.insert(3, {"id": "fixture#6", "script": {"assembly": "Language", "class": "Language_Text"},
                            "fields": {"_Infos": []}})
        row = copy.deepcopy(self.rows[3])
        row["source_id"] = row["evidence"][0]["object"] = "fixture#6"
        self.rows.insert(3, row)
        self.groups[0]["occurrences"] = 3
        self.pin()
        self.assertEqual(5, self.check(complete=False)["observations_checked"])
        self.assertEqual(6, self.check()["observations_checked"])
        self.groups[0]["occurrences"] = 2
        self.assertEqual("passed", self.check(complete=False)["status"])
        with self.assertRaisesRegex(ValueError, "Derived text gap count differs"):
            self.check()

    def test_altered_dropped_extra_and_relabelled_tooltip_edges_are_rejected(self):
        original = copy.deepcopy(self.rows[0]["relationships"])
        alternatives = [original[:-1], original + [original[0]],
                        [{**original[0], "predicate": "another-label"}, *original[1:]],
                        [{**original[0], "source_field": "/_Dura_Title"}, *original[1:]],
                        [{**original[0], "target_source_ids": ["fixture#3"]}, *original[1:]],
                        [{**original[0], "status": "unresolved"}, *original[1:]],
                        [{**original[0], "guid": "invented"}, *original[1:]]]
        for links in alternatives:
            with self.subTest(links=links[:1], count=len(links)):
                self.rows[0]["relationships"] = links
                with self.assertRaisesRegex(ValueError, "Tooltip references differ"):
                    self.check()

    def test_null_tooltip_pointer_omits_link_even_with_stale_reference_metadata(self):
        self.raw[0]["fields"]["data"]["_Dura_Title"]["m_PathID"] = 0
        self.rows[0]["relationships"].pop(0)
        self.pin()
        self.assertEqual("passed", self.check()["status"])

    def test_missing_and_unknown_tooltip_references_require_their_gaps(self):
        self.raw[0]["references"].pop(0)
        self.raw[0]["references"][0].pop("status")
        self.rows[0]["relationships"][0] = {"source_field": "/data/_Dura_Title", "predicate": "tooltip-text", "status": "missing"}
        self.rows[0]["relationships"][1]["status"] = "unknown"
        self.groups += [{"code": "unresolved-reference", "topic": "items-equipment", "pattern": "DynamicToolTipSet/data/" + member,
                         "occurrences": 1} for member in ("_Dura_Title", "_BlockDura")]
        self.pin()
        self.assertEqual("passed", self.check()["status"])
        self.groups.pop()
        with self.assertRaisesRegex(ValueError, "Derived text gap count differs"):
            self.check()

    def test_changed_text_and_reference_evidence_are_rejected(self):
        originals = copy.deepcopy(self.rows)
        for index, fields in ((0, []), (1, ["/_Infos/1/text"]), (2, ["/_Infos/1/_ItemName"]), (3, [])):
            with self.subTest(index=index):
                self.rows = copy.deepcopy(originals)
                self.rows[index]["evidence"][0]["fields"] = fields
                with self.assertRaisesRegex(ValueError, "Derived text evidence differs"):
                    self.check()

    def test_english_shapes_optional_instructions_and_enum_types(self):
        for class_name, field in (("Language_Text", "text"), ("Tooltip_Text", "_ItemName")):
            for infos in ([], [{"languageType": "2", field: "Wrong"}], [{"languageType": 2.0, field: "Wrong"}],
                          [{"languageType": 2, field: "Same"}, {"languageType": 2, field: "Same"}]):
                with self.subTest(class_name=class_name, infos=infos):
                    raw = {"script": {"class": class_name}, "fields": {"_Infos": infos}}
                    facts, evidence, gaps = check_extraction.english_text(raw)
                    self.assertEqual({field: None}, facts)
                    self.assertEqual({"/_Infos"}, evidence)
                    self.assertIn(("english-text", "/_Infos"), gaps)
        raw = {"script": {"class": "Tooltip_Text"}, "fields": {"_Infos": [{"languageType": 2, "_ItemName": ""}]}}
        self.assertEqual({"_ItemName": ""}, check_extraction.english_text(raw)[0])
        raw["fields"]["_Infos"][0]["_ItemInstruction"] = 4
        facts, _, gaps = check_extraction.english_text(raw)
        self.assertEqual({"_ItemName": "", "_ItemInstruction": None}, facts)
        self.assertEqual([("unsupported-field-type", "/_Infos/0/_ItemInstruction")], gaps)

    def add_mineable_fixture(self):
        entries = [
            {"ItemBI_refKey": "BO_Ore_Nitrate", "Name": "Chrismatite_Icon", "RandomRate": 0.2},
            {"ItemBI_refKey": "bo_ore_nitrate", "Name": "Chrismatite_Icon", "RandomRate": 0.05},
            {"ItemBI_refKey": "BO_Missing", "Name": "Missing_Icon", "RandomRate": 0.1},
            {"ItemBI_refKey": "BO_Mixed", "Name": "Ore_Nitrate_Icon", "RandomRate": 0.125},
            {"ItemBI_refKey": "BO_Missing", "Name": "Duplicate_Icon", "RandomRate": 0.25},
        ]
        raw = {"id": "fixture#6", "script": {"assembly": "Build_System", "class": "Terrain_Block_Info"},
               "fields": {"_BlockInfo": [{"CollectableItems": entries}]}}
        self.raw.append(raw)
        links = [{"predicate": "mineable-item", "source_field": f"/_BlockInfo/0/CollectableItems/{index}",
                  "resolution": resolution, "target_source_ids": targets,
                  **({"status": "unresolved"} if not targets else {})}
                 for index, (resolution, targets) in enumerate([
                     ("address", ["icons#21"]), ("name", ["icons#23"]),
                     ("unresolved", []), ("unresolved", []), ("unresolved", [])])]
        proof = [
            {"path": "Catalog/addressables.jsonl", "entry": 42, "fields": ["keys", "targets"]},
            {"path": "Catalog/objects/world.jsonl", "object": "world#10", "fields": ["/m_Component"]},
            {"path": "Catalog/objects/world.jsonl", "object": "world#11", "fields": ["/_Collectable_Info/_Items/0/_IconRef"]},
            {"path": "Catalog/views/items.jsonl", "object": "icons#21", "fields": ["id", "name", "game_objects"]},
            {"path": "Catalog/views/items.jsonl", "fields": ["name", "id"]},
            {"path": "Catalog/views/items.jsonl", "object": "icons#23", "fields": ["id", "name", "game_objects"]},
        ]
        fields = [f"/_BlockInfo/0/CollectableItems/{index}/{key}" for index in range(len(entries))
                  for key in ("ItemBI_refKey", "Name", "RandomRate")]
        self.rows.append({"source_id": raw["id"], "kind": "resource-distribution", "component": dict(raw["script"]),
                          "facts": copy.deepcopy(raw["fields"]), "name_status": "internal", "relationships": links,
                          "evidence": [{"path": OBJECT_PATH, "object": raw["id"], "fields": fields}, *proof]})
        self.supporting = {
            "Catalog/addressables.jsonl": [
                {"entry": 42, "keys": ["BO_Ore_Nitrate"], "targets": ["world#10"],
                 "resource_type": {"m_ClassName": "UnityEngine.GameObject"}},
                {"entry": 43, "keys": ["BO_Mixed"], "targets": ["world#12"],
                 "resource_type": {"m_ClassName": "UnityEngine.GameObject"}},
            ],
            "Catalog/views/items.jsonl": [
                {"id": "icons#21", "name": "Ore_Nitrate_Icon", "game_objects": ["icons#20"]},
                {"id": "icons#23", "name": "Chrismatite_Icon", "game_objects": ["icons#22"]},
                {"id": "icons#25", "name": "Duplicate_Icon", "game_objects": ["icons#24"]},
                {"id": "icons#27", "name": "Duplicate_Icon", "game_objects": ["icons#26"]},
            ],
            "Catalog/objects/world.jsonl": [
                {"id": "world#10", "type": "GameObject", "references": [
                    {"field": "/m_Component/0/component", "status": "resolved", "target": "world#11"}]},
                {"id": "world#11", "script": {"assembly": "Build_System", "class": "Build_Info"}, "references": [
                    {"field": "/_Collectable_Info/_Items/0/_IconRef", "status": "resolved", "targets": ["icons#20"]}]},
                {"id": "world#12", "type": "GameObject", "references": [
                    {"field": "/m_Component/0/component", "status": "resolved", "target": "world#13"}]},
                {"id": "world#13", "script": {"assembly": "Build_System", "class": "Build_Info"}, "references": [
                    {"field": "/_Collectable_Info/_Items/0/_IconRef", "status": "resolved", "target": "icons#20"},
                    {"field": "/_Collectable_Info/_Items/1/_IconRef", "status": "resolved", "target": "icons#22"}]},
            ],
        }
        self.groups.append({"code": "mineable-item-gap", "topic": "biomes-resources",
                            "pattern": "Terrain_Block_Info/_BlockInfo/*/CollectableItems/*", "occurrences": 3})
        self.pin()

    def test_pinned_mineable_paths_gaps_and_proof_pass(self):
        self.add_mineable_fixture()
        first = self.check()
        self.assertEqual("passed", first["status"])
        self.assertEqual(6, first["observations_checked"])
        for path in self.supporting:
            self.put(self.source, path, b"dirty working copy is not evidence\n")
        self.assertEqual(first, self.check())
        self.assertEqual("passed", self.check(complete=False)["status"])

    def test_mineable_targets_paths_missing_extra_and_relabelled_links_are_rejected(self):
        self.add_mineable_fixture()
        original = copy.deepcopy(self.rows[-1]["relationships"])
        alternatives = [[], original[:-1], original + [original[0]],
                        [{**original[0], "predicate": "collectible-item"}, *original[1:]],
                        [{**original[0], "source_field": "/_BlockInfo/1/CollectableItems/0"}, *original[1:]],
                        [{**original[0], "target_source_ids": ["world#10"]}, *original[1:]],
                        [{**original[0], "target_source_ids": ["icons#23"]}, *original[1:]],
                        [{**original[0], "resolution": "name"}, *original[1:]],
                        [{**original[0], "status": "unresolved"}, *original[1:]],
                        [*original[:2], {key: value for key, value in original[2].items() if key != "status"}, *original[3:]]]
        for links in alternatives:
            with self.subTest(links=links[:1], count=len(links)):
                self.rows[-1]["relationships"] = links
                with self.assertRaisesRegex(ValueError, "Mineable-item relationships differ"):
                    self.check()

    def test_mineable_missing_wrong_and_overcounted_gaps_are_rejected(self):
        self.add_mineable_fixture()
        others, mining = self.groups[:-1], self.groups[-1]
        for groups in ([], [{**mining, "occurrences": 2}], [{**mining, "occurrences": 4}],
                       [{**mining, "topic": "items-equipment"}], [{**mining, "code": "unresolved-reference"}]):
            with self.subTest(groups=groups):
                self.groups = others + groups
                with self.assertRaisesRegex(ValueError, "Mineable-item gap count differs"):
                    self.check()

    def test_mineable_evidence_and_unchanged_rates_are_checked(self):
        self.add_mineable_fixture()
        original = copy.deepcopy(self.rows[-1])
        for index, update in ((1, {"entry": 43}), (2, {"fields": ["/invented"]}),
                              (4, {"object": "icons#23"}), (5, {"fields": ["display_name"]})):
            with self.subTest(index=index):
                self.rows[-1] = copy.deepcopy(original)
                self.rows[-1]["evidence"][index].update(update)
                with self.assertRaisesRegex(ValueError, "Mineable-item evidence differs"):
                    self.check()
        self.rows[-1] = copy.deepcopy(original)
        self.rows[-1]["evidence"] = self.rows[-1]["evidence"][:1]
        with self.assertRaisesRegex(ValueError, "Mineable-item evidence differs"):
            self.check()
        self.rows[-1] = copy.deepcopy(original)
        self.rows[-1]["facts"]["_BlockInfo"][0]["CollectableItems"][0]["RandomRate"] = 20
        with self.assertRaisesRegex(ValueError, "Fact differs"):
            self.check()

    def test_changed_pinned_address_and_item_records_reject_stale_links(self):
        self.add_mineable_fixture()
        original = copy.deepcopy(self.supporting)
        for path, field, value in (("Catalog/addressables.jsonl", "keys", ["renamed"]),
                                   ("Catalog/views/items.jsonl", "game_objects", ["icons#99"])):
            with self.subTest(path=path):
                self.supporting = copy.deepcopy(original)
                self.supporting[path][0][field] = value
                self.pin()
                with self.assertRaisesRegex(ValueError, "Mineable-item relationships differ"):
                    self.check()

    def test_unresolved_or_uncaptured_prefab_falls_back_to_exact_item_name(self):
        self.add_mineable_fixture()
        original = copy.deepcopy(self.supporting)
        self.rows[-1]["relationships"][0].update(resolution="name", target_source_ids=["icons#23"])
        self.rows[-1]["evidence"] = [self.rows[-1]["evidence"][0], *self.rows[-1]["evidence"][5:]]
        for fault in ("unresolved-icon", "uncaptured-prefab"):
            with self.subTest(fault=fault):
                self.supporting = copy.deepcopy(original)
                if fault == "unresolved-icon":
                    self.supporting["Catalog/objects/world.jsonl"][1]["references"][0]["status"] = "unresolved"
                else:
                    self.supporting["Catalog/addressables.jsonl"][0]["targets"] = ["missing#99"]
                self.pin()
                self.assertEqual("passed", self.check()["status"])

    def test_mineable_sampling_uses_gap_lower_bound(self):
        self.add_mineable_fixture()
        for number in (7, 8, 9):
            raw, row = copy.deepcopy(self.raw[-1]), copy.deepcopy(self.rows[-1])
            raw["id"] = row["source_id"] = row["evidence"][0]["object"] = f"fixture#{number}"
            self.raw.append(raw)
            self.rows.append(row)
        self.groups[-1]["occurrences"] = 12
        self.pin()
        self.assertEqual(8, self.check(complete=False)["observations_checked"])
        self.assertEqual(9, self.check()["observations_checked"])
        self.groups[-1]["occurrences"] = 9
        self.assertEqual("passed", self.check(complete=False)["status"])
        with self.assertRaisesRegex(ValueError, "Mineable-item gap count differs"):
            self.check()

    def test_builder_mineable_output_passes_independent_checker(self):
        from types import SimpleNamespace
        from wikibuild.adapters import biomes
        from wikibuild.exceptions import Exceptions
        self.add_mineable_fixture()
        records = {raw["id"]: raw for raw in [*self.raw, *self.supporting["Catalog/objects/world.jsonl"]]}
        source = SimpleNamespace(
            catalog={"selected": {self.raw[-1]["id"]: {"assembly": "Build_System", "class": "Terrain_Block_Info"}}},
            objects=lambda identities: {identity: records[identity] for identity in identities if identity in records},
            records=lambda path: iter(self.supporting[path]),
            object_path=lambda identity: "Catalog/objects/" + identity.rsplit("#", 1)[0] + ".jsonl")
        row = self.rows[-1]
        row["relationships"], row["evidence"] = [], row["evidence"][:1]
        issues = Exceptions()
        biomes.enrich_mineable_items(row, biomes.prepare_mineable_items(source), issues)
        self.groups = self.groups[:-1] + issues.report()["groups"]
        self.assertEqual("passed", self.check()["status"])

    def test_checker_does_not_import_builder_code(self):
        tree = ast.parse((ROOT / "tools/check_extraction.py").read_text())
        imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        imports += [f"{node.module}.{alias.name}" for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) for alias in node.names]
        project_imports = {name for name in imports if name == "wikibuild" or name.startswith("wikibuild.")}
        self.assertEqual(project_imports, {"wikibuild.bounded"})
        # Infrastructure sharing must not bring builder semantics into the audit.
        owner = ast.parse((ROOT / "wikibuild/bounded.py").read_text())
        self.assertFalse(any(isinstance(node, ast.ImportFrom) and node.level for node in ast.walk(owner)))


if __name__ == "__main__":
    unittest.main()
