"""Two-snapshot public-reader contracts, using real pack/file transactions."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wikibuild import game_text, history, model, packs, presentation, reader
from wikibuild.storage import ContractError, digest, json_bytes, writer_lock


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.registry_path = self.root / "presentation/fields.json"
        self.registry_path.parent.mkdir()
        names = json.loads((Path(reader.__file__).resolve().parents[1] / "presentation/fields.json").read_bytes())["names"]
        self.registry_path.write_bytes(json_bytes({"schema_version": 1, "names": names, "glossaries": {}, "kinds": {
            "item": {"fields": {"/weight": {"tier": "player", "format": "round2",
                                            "label": {"game": "_Weight_Title", "fallback": "Weight"}}}}}}))
        self.project = {"repositories": [
            {"id": "hub", "title": "Home", "owns": [], "coverage": "Navigation"},
            {"id": "items", "title": "Items", "owns": ["item"], "coverage": "Items"},
            {"id": "loot", "title": "Loot", "owns": ["loot-source"], "coverage": "Loot"}], "official_links": []}
        self.a, self.b, self.c = ["e-" + letter * 32 for letter in "abc"]
        self.old = self.make_run("100", [self.observation(self.a, "<script>alert(1)</script>"), self.observation(self.b, "Old item")])
        self.new = self.make_run("200", [self.observation(self.a, "<script>alert(1)</script>"), self.observation(self.c, "Crate", "loot-source", "loot", self.a)],
                                 absent={self.b: "not-present"})
        self.runs = [self.new, self.old]

    def observation(self, key, name, kind="item", topic="items", target=None):
        semantic = {"name": name, "kind": kind, "topic": topic, "facts": {"weight": 3, "nested": {"field": "value"}},
                    "relationships": [{"predicate": "yields", "field": "/items/0", "targets": [target]}] if target else [],
                    "evidence_level": "extracted"}
        return {"entity_key": key, "semantic": semantic, "revision_id": digest(json_bytes(semantic)),
                "provenance": {"source_id": "bundle#" + str(ord(key[-1])), "evidence": [{"path": "Catalog/views/items.jsonl", "git_blob": "a" * 40}]}}

    def make_run(self, build, observations, absent=None):
        snapshot = f"build-{build}-{'a' * 12}"
        state = []
        for observation in observations:
            observation["snapshot_id"] = snapshot
            semantic = observation["semantic"]
            state.append({"entity_key": observation["entity_key"], "status": "present", "revision_id": observation["revision_id"],
                          "descriptor": {"name": semantic["name"], "kind": semantic["kind"], "topic": semantic["topic"]},
                          "first_seen": "build-100-" + "a" * 12, "last_changed": "build-100-" + "a" * 12,
                          "last_data_checked": snapshot, "last_verified": None, "decision": {"status": "matched"}})
        for key, status in (absent or {}).items():
            state.append({"entity_key": key, "status": status, "revision_id": "old",
                          "descriptor": {"name": "Old item", "topic": "items", "kind": "item"},
                          "last_seen": "build-100-" + "a" * 12, "last_changed": "build-100-" + "a" * 12, "last_verified": None})
        result = {"snapshot_id": snapshot, "run_id": digest(build.encode()), "source_commit": "b" * 40, "change_origin": "initial"}
        for label, rows in [("state", state), ("models", observations)]:
            path = self.root / f"{build}-{label}.jsonl"
            path.write_bytes(b"".join(packs.compact(row) + b"\n" for row in rows))
            result[label] = history.install(self.root, path, f"fixtures/{label}")
        path = self.root / "snapshots" / f"{snapshot}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(json_bytes({"schema_version": 1, "snapshot_id": snapshot, "steam": {"app_id": "2393970", "build_id": build},
                                    "game_version": None, "latest_available_game_build": None,
                                    "status": "input-registered", "wiki_verification": "not-performed"}))
        return result

    def build(self, **kwargs):
        with writer_lock(self.root):
            result = reader.build(self.root, self.project, self.runs, **kwargs)
        return Path(result["path"]), result

    def index(self, site, topic, run):
        return json.loads((site / topic / "snapshots" / f"{run['snapshot_id']}.json").read_text())

    def test_shared_fonts_have_exact_bytes_resolving_links_and_repeat_build(self):
        site, _ = self.build()
        config = json.loads((site / "hub/reader.json").read_bytes())
        fonts = config["fonts"]
        self.assertEqual(fonts["base"], "/hub/fonts/" + digest(json_bytes(fonts["files"])) + "/")
        sources = Path(reader.__file__).parent / "web/fonts"
        for name, meta in fonts["files"].items():
            data = (site / (fonts["base"] + name).lstrip("/")).read_bytes()
            original = (sources / name).read_bytes()
            self.assertEqual(data, original if name.endswith(".woff2") else original.replace(b"\r\n", b"\n"))
            self.assertEqual(meta, {"sha256": digest(data), "bytes": len(data)})
        for topic in ("hub", "items", "loot"):
            value = json.loads((site / topic / "reader.json").read_bytes())
            self.assertEqual(value["fonts"], fonts)
            for shell in (site / topic).rglob("*.html"):
                self.assertIn('id="wiki-fonts" rel="stylesheet" href="' + fonts["base"] + 'fonts.css"', shell.read_text())
            if topic != "hub":
                self.assertFalse((site / topic / "fonts").exists())
        before = {p.relative_to(site): p.read_bytes() for p in site.rglob("*") if p.is_file()}
        repeated, result = self.build()
        self.assertTrue(result["reused"])
        self.assertEqual(before, {p.relative_to(repeated): p.read_bytes() for p in repeated.rglob("*") if p.is_file()})

    def test_font_change_changes_candidate_and_set_identity(self):
        first, initial = self.build()
        font = Path(reader.__file__).parent / "web/fonts/Geist.woff2"
        read_bytes = Path.read_bytes
        def changed(path):
            data = read_bytes(path)
            return data + b"\r\n" if path == font else data
        with patch.object(Path, "read_bytes", changed):
            second, updated = self.build()
            self.assertTrue(self.build()[1]["reused"])
        self.assertNotEqual(initial["candidate_id"], updated["candidate_id"])
        old_fonts = json.loads((first / "hub/reader.json").read_bytes())["fonts"]
        new_fonts = json.loads((second / "hub/reader.json").read_bytes())["fonts"]
        self.assertNotEqual(old_fonts["base"], new_fonts["base"])
        self.assertEqual((second / (new_fonts["base"] + font.name).lstrip("/")).read_bytes(), font.read_bytes() + b"\r\n")

    def test_short_cache_name_keeps_full_identity_and_rejects_prefix_collision(self):
        site, result = self.build()
        self.assertEqual(site.name, result["candidate_id"][:24])
        collision = result["candidate_id"][:24] + "f" * 40
        self.assertNotEqual(collision, result["candidate_id"])
        self.assertEqual(site, reader.candidate_path(self.root / ".local", collision))
        with self.assertRaisesRegex(ContractError, "does not match requested"):
            reader.verify(site, collision)
        self.assertTrue(self.build()[1]["reused"])

    def test_captured_application_version_and_evidence_remain_snapshot_specific(self):
        path = self.root / "snapshots" / (self.new["snapshot_id"] + ".json")
        receipt = json.loads(path.read_bytes())
        evidence = [{"source_path": "Human Host_Data/globalgamemanagers", "source_sha256": "a" * 64,
                     "object_id": "globalgamemanagers#1", "field": "/bundleVersion"}]
        receipt.update(game_version="0.8.315", game_version_status="recorded", game_version_evidence=evidence)
        path.write_bytes(json_bytes(receipt))
        site, _ = self.build()
        for topic in ("items", "loot", "hub"):
            current = self.index(site, topic, self.new)
            self.assertEqual(current["game_version"], "0.8.315")
            self.assertEqual(current["game_version_evidence"], evidence)
            self.assertIsNone(self.index(site, topic, self.old)["game_version"])
            versions = json.loads((site / topic / "reader.json").read_bytes())["versions"]
            self.assertEqual([row["game_version"] for row in versions], ["0.8.315", None])
        self.assertTrue(self.build()[1]["reused"])

    def test_existing_full_hash_cache_location_remains_resolvable(self):
        candidate = "a" * 64
        legacy = self.root / ".local/readers" / candidate
        legacy.mkdir(parents=True)
        self.assertEqual(reader.candidate_path(self.root / ".local", candidate), legacy)

    def test_versions_keep_facts_removal_provenance_and_cross_topic_routes(self):
        site, _ = self.build()
        latest = self.index(site, "items", self.new)
        entries = reader.load_maps(site / "items", latest["entries"])
        self.assertEqual("not-present", entries[self.b]["status"])
        reverse = reader.load_maps(site / "items", latest["backlinks"])
        self.assertEqual("loot", next(value for key, value in reverse.items() if key.startswith(self.a + "/"))["topic"])
        self.assertEqual(1, entries[self.a]["backlink_count"])
        self.assertIsNone(entries[self.a]["last_verified"])
        older = self.index(site, "items", self.old)
        old_entries = reader.load_maps(site / "items", older["entries"])
        self.assertEqual("present", old_entries[self.b]["status"])
        self.assertEqual(old_entries[self.a]["revision_id"], entries[self.a]["revision_id"])
        self.assertTrue(set(row["path"] for row in older["semantics"]) <= set(row["path"] for row in latest["semantics"]))
        config = json.loads((site / "loot/reader.json").read_text())
        self.assertEqual(["200", "100"], [version["build_id"] for version in config["versions"]])
        self.assertEqual(2, reader.validate_snapshot(site, self.new["snapshot_id"], ["hub", "items", "loot"]))

    def test_unchanged_candidate_is_byte_and_pointer_stable(self):
        site, first = self.build()
        pointer = self.root / ".local/reader-latest.json"
        before = pointer.stat().st_mtime_ns
        files = {p.relative_to(site): (p.stat().st_mtime_ns, p.read_bytes()) for p in site.rglob("*") if p.is_file()}
        _, second = self.build()
        self.assertTrue(second["reused"])
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(before, pointer.stat().st_mtime_ns)
        self.assertEqual(files, {p.relative_to(site): (p.stat().st_mtime_ns, p.read_bytes()) for p in site.rglob("*") if p.is_file()})

    def test_registered_cards_match_formatter_and_preserve_semantic_records(self):
        site, _ = self.build()
        registry = presentation.load(self.registry_path)
        for run in self.runs:
            for row in model.rows(self.root / run["models"]["path"]):
                topic = row["semantic"]["topic"]
                index = self.index(site, topic, run)
                entry = reader.load_maps(site / topic, index["entries"])[row["entity_key"]]
                cards = reader.load_maps(site / topic, index["cards"])
                self.assertEqual(entry["revision_id"], row["revision_id"])
                self.assertEqual(reader.load_maps(site / topic, index["semantics"])[entry["revision_id"]], row["semantic"])
                if row["semantic"]["kind"] == "item":
                    expected = presentation.card(registry, "item", row["semantic"], {}, entry["links"])
                    self.assertTrue(expected["stats"])
                    self.assertEqual(cards[entry["card_id"]], expected)
                    self.assertEqual(entry["card_id"], digest(json_bytes({
                        "revision_id": row["revision_id"], "game_text": digest(json_bytes({})),
                        "presentation": digest(self.registry_path.read_bytes())})))
                else:
                    self.assertNotIn("card_id", entry)
                    self.assertEqual(cards, {})
        latest = self.index(site, "items", self.new)
        self.assertNotIn("card_id", reader.load_maps(site / "items", latest["entries"])[self.b])
        self.assertIn("presentation.py", reader.contract())
        self.assertIn("game_text.py", reader.contract())

    def test_unchanged_cards_share_storage_when_another_entry_disappears(self):
        site, _ = self.build()
        indexes = [self.index(site, "items", run) for run in self.runs]
        entries = [reader.load_maps(site / "items", index["entries"]) for index in indexes]
        card_id = entries[0][self.a]["card_id"]
        self.assertEqual(card_id, entries[1][self.a]["card_id"])
        shared = [{ref["path"] for ref in index["cards"]
                   if card_id in reader.load_maps(site / "items", [ref])} for index in indexes]
        self.assertEqual(shared[0], shared[1])
        self.assertEqual(len(shared[0]), 1)
        stored = [path for path in (site / "items/data").glob("*.json") if card_id in json.loads(path.read_bytes())]
        self.assertEqual(len(stored), 1)
        self.assertEqual(set(reader.load_maps(site / "items", indexes[0]["cards"])), {card_id})

    def test_registry_change_invalidates_candidate_and_card_without_changing_facts(self):
        before, first = self.build()
        registry = presentation.load(self.registry_path)
        registry["kinds"]["item"]["fields"]["/weight"]["label"]["fallback"] = "Mass"
        self.registry_path.write_bytes(json_bytes(registry))
        after, second = self.build()
        self.assertNotEqual(first["candidate_id"], second["candidate_id"])
        self.assertFalse(second["reused"])
        self.assertFalse(second.get("projection_reused", False))
        manifest = reader.verify(after)
        self.assertEqual(manifest["inputs"]["presentation"], digest(self.registry_path.read_bytes()))
        for run in self.runs:
            old, new = [self.index(site, "items", run) for site in (before, after)]
            for kind in ("semantics", "provenance", "search"):
                self.assertEqual(old[kind], new[kind])
            old_cards = reader.load_maps(before / "items", old["cards"])
            new_cards = reader.load_maps(after / "items", new["cards"])
            self.assertTrue(old_cards.keys().isdisjoint(new_cards))
            self.assertTrue(all(card["stats"][0]["label"] == "Mass" for card in new_cards.values()))
        self.assertTrue(self.build()[1]["reused"])

    def test_game_text_is_snapshot_specific_even_when_item_revision_is_unchanged(self):
        self.project["repositories"][0]["owns"] = ["tooltip", "language-text"]
        tooltip_key, text_key = ["e-" + letter * 32 for letter in "de"]
        def observations(label):
            item = self.observation(self.a, "Item")
            tooltip = self.observation(tooltip_key, "Tooltip", "tooltip", "hub", text_key)
            tooltip["provenance"]["component"] = {"assembly": "UI", "class": "DynamicToolTipSet"}
            tooltip["semantic"]["relationships"][0].update(predicate="tooltip-text", field="/data/_Weight_Title")
            tooltip["revision_id"] = digest(json_bytes(tooltip["semantic"]))
            text = self.observation(text_key, "Weight label", "language-text", "hub")
            text["provenance"]["component"] = {"assembly": "Language", "class": "Language_Text"}
            text["semantic"]["facts"] = {"text": label}
            text["revision_id"] = digest(json_bytes(text["semantic"]))
            return [item, tooltip, text]
        self.runs = [self.make_run("400", observations("Mass: ")), self.make_run("300", observations("Weight: "))]
        site, _ = self.build()
        entries = []
        for run, label in zip(self.runs, ("Mass", "Weight")):
            index = self.index(site, "items", run)
            entry = reader.load_maps(site / "items", index["entries"])[self.a]
            card = reader.load_maps(site / "items", index["cards"])[entry["card_id"]]
            text = game_text.labels(model.rows(self.root / run["models"]["path"]))
            semantic = reader.load_maps(site / "items", index["semantics"])[entry["revision_id"]]
            self.assertEqual(card, presentation.card(presentation.load(self.registry_path), "item", semantic, text, entry["links"]))
            self.assertEqual(card["stats"][0]["label"], label)
            entries.append(entry)
        self.assertEqual(entries[0]["revision_id"], entries[1]["revision_id"])
        self.assertNotEqual(entries[0]["card_id"], entries[1]["card_id"])

    def test_validation_rejects_missing_cards_and_accepts_legacy_entries(self):
        site, _ = self.build()
        path = site / "items/snapshots" / f"{self.new['snapshot_id']}.json"
        index = self.index(site, "items", self.new)
        for missing in ([], None):
            with self.subTest(cards=missing):
                broken = {**index, "cards": missing}
                if missing is None:
                    del broken["cards"]
                path.write_bytes(packs.compact(broken))
                with self.assertRaisesRegex(ContractError, "card_id is missing"):
                    reader.validate_snapshot(site, self.new["snapshot_id"], ["hub", "items", "loot"])
        entries = reader.load_maps(site / "items", index["entries"])
        for entry in entries.values():
            entry.pop("card_id", None)
        def output(name, data):
            (site / "items" / name).write_bytes(data)
        index["entries"] = packs.write({key: packs.compact(value) for key, value in entries.items()}, 4096, output)
        path.write_bytes(packs.compact(index))
        with self.assertRaisesRegex(ContractError, "card has no owning entry"):
            reader.validate_snapshot(site, self.new["snapshot_id"], ["hub", "items", "loot"])
        del index["cards"]
        path.write_bytes(packs.compact(index))
        self.assertEqual(reader.validate_snapshot(site, self.new["snapshot_id"], ["hub", "items", "loot"]), 2)

    def test_registry_change_during_projection_does_not_promote(self):
        _, initial = self.build()
        original = reader.project_snapshot
        def change_registry(*args, **kwargs):
            result = original(*args, **kwargs)
            self.registry_path.write_bytes(self.registry_path.read_bytes() + b"\n")
            return result
        with patch("wikibuild.reader.project_snapshot", side_effect=change_registry):
            with self.assertRaisesRegex(ContractError, "inputs changed during generation"):
                self.build(max_pack_bytes=2048)
        self.assertEqual(json.loads((self.root / ".local/reader-latest.json").read_bytes())["candidate_id"], initial["candidate_id"])
        self.assertFalse(self.build(max_pack_bytes=2048)[1]["reused"])
        self.assertTrue(self.build(max_pack_bytes=2048)[1]["reused"])

    def test_modified_or_unknown_output_is_refused(self):
        site, _ = self.build()
        path = site / "items/index.html"
        original = path.read_bytes()
        path.write_text("local investigation")
        with self.assertRaisesRegex(ContractError, "modified"):
            self.build()
        self.assertEqual("local investigation", path.read_text())
        path.write_bytes(original)
        (site / "unknown.txt").write_text("keep")
        with self.assertRaisesRegex(ContractError, "unknown"):
            self.build()

    def test_failure_before_promotion_preserves_previous_and_retries(self):
        _, initial = self.build()
        original = reader.write_changed

        def fail_pointer(path, data):
            if path.name == "reader-latest.json":
                raise OSError("injected pointer interruption")
            return original(path, data)

        with patch("wikibuild.reader.write_changed", side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, "injected"):
                self.build(max_pack_bytes=2048)
        saved = json.loads((self.root / ".local/reader-latest.json").read_text())
        self.assertEqual(initial["candidate_id"], saved["candidate_id"])
        _, retry = self.build(max_pack_bytes=2048)
        self.assertTrue(retry["reused"])

    def test_text_is_escaped_in_markdown_and_absent_from_shell(self):
        site, _ = self.build()
        markdown = (site / "items/reference/item/0001.md").read_text()
        self.assertIn("&lt;script&gt;", markdown)
        self.assertNotIn("<script>alert", markdown)
        self.assertNotIn("alert(1)", (site / "items/index.html").read_text())
        self.assertIn("snapshot=build-200-", markdown)
        self.assertIn("release=", markdown)

    def test_bad_model_target_does_not_promote_candidate(self):
        row = self.observation(self.c, "Crate", "loot-source", "loot", "e-" + "d" * 32)
        self.runs = [self.make_run("300", [row])]
        with self.assertRaisesRegex(ContractError, "absent snapshot target"):
            self.build()
        self.assertFalse((self.root / ".local/reader-latest.json").exists())

    def test_missing_current_models_are_not_silently_treated_as_absence(self):
        path = self.root / self.new["models"]["path"]
        path.unlink()
        with self.assertRaisesRegex(ContractError, "missing"):
            self.build()

    def test_removed_group_keeps_its_historical_static_route(self):
        self.runs = [self.make_run("300", [], absent={self.a: "not-present", self.b: "not-present"}), self.old]
        site, _ = self.build()
        self.assertTrue((site / "items/groups/item/index.html").is_file())
        self.assertEqual({}, self.index(site, "items", self.runs[0])["counts"])
        self.assertEqual({"item": 2}, self.index(site, "items", self.old)["counts"])

    def test_unsafe_site_bases_fail_before_output(self):
        for base in ("javascript:alert(1)/", "//unconfigured.test/", "/items/../private/", "https://user:secret@example.com/"):
            with self.subTest(base=base), self.assertRaisesRegex(ContractError, "HTTPS"):
                self.build(bases={"hub": "/hub/", "items": base, "loot": "/loot/"})

    def test_dense_reverse_links_split_without_oversized_entry(self):
        observations = [self.observation(self.a, "Material")]
        observations += [self.observation(f"e-{number:032x}", "Long recipe label " + "x" * 150, "loot-source", "loot", self.a)
                         for number in range(1, 41)]
        self.runs = [self.make_run("300", observations)]
        site, _ = self.build(max_pack_bytes=2048)
        index = self.index(site, "items", self.runs[0])
        entries = reader.load_maps(site / "items", index["entries"])
        self.assertEqual(40, entries[self.a]["backlink_count"])
        self.assertEqual(40, len(reader.load_maps(site / "items", index["backlinks"])))
        self.assertGreater(len(index["backlinks"]), 1)
        self.assertTrue(all(shard["bytes"] <= 2048 for shard in index["backlinks"]))

    def test_uncaptured_is_preserved_and_cache_cannot_leave_workspace(self):
        self.runs = [self.make_run("300", [], absent={self.b: "uncaptured"})]
        site, _ = self.build()
        index = self.index(site, "items", self.runs[0])
        self.assertEqual("uncaptured", reader.load_maps(site / "items", index["entries"])[self.b]["status"])
        with self.assertRaisesRegex(ContractError, "owning"):
            self.build(cache_root=self.root.parent)

    def test_capacity_split_preserves_every_record_and_reuses_known_revisions(self):
        records = {digest(str(i).encode()): packs.compact({"facts": "x" * 100}) for i in range(100)}
        written, known = {}, {}
        def output(path, data):
            written[path] = data
        first = packs.reuse(records, known, 1024, output)
        self.assertGreater(len(first), 1)
        self.assertTrue(all(len(data) <= 1024 for data in written.values()))
        values = {key: value for data in written.values() for key, value in json.loads(data).items()}
        self.assertEqual(set(records), set(values))
        before = dict(written)
        extended = {**records, "f" * 64: packs.compact({"facts": "new"})}
        packs.reuse(extended, known, 1024, output)
        self.assertEqual(1, len(written) - len(before))
        self.assertTrue(all(written[path] == data for path, data in before.items()))
        with self.assertRaisesRegex(ContractError, "exceeds"):
            list(packs.partition({"large": packs.compact("x" * 2000)}, 1024))


if __name__ == "__main__":
    unittest.main()
