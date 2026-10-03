"""Contract failures and repeatability at real local Git/filesystem boundaries."""

import copy
import json
import os
import re
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlparse

from tests._support import fixture_parent
from wikibuild import manifest, navigation, snapshots, workspace
from wikibuild.storage import ContractError, git, json_bytes, writer_lock, write_changed

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((PROJECT_ROOT / "project.json").read_text())


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.test_parent = fixture_parent("test-runs")
        self.root = Path(tempfile.mkdtemp(dir=self.test_parent)).resolve()
        self.project = copy.deepcopy(BASE)

    def tearDown(self):
        if self.root.is_relative_to(self.test_parent.resolve()):
            # Ordinary removal only: no permission override or ignore-errors handler.
            try:
                shutil.rmtree(self.root)
            except PermissionError:
                # Git for Windows makes object files read-only. Retain them;
                # cleanup cannot authorize overriding file protection.
                print(f"Retained protected test fixture: {self.root}")

    def git_source(self, schema=1, failures=None):
        source = self.root / "source"
        source.mkdir()
        git(source, "init", "--initial-branch=main")
        git(source, "config", "user.name", "Wiki tests")
        git(source, "config", "user.email", "wiki-tests@example.invalid")
        catalog = source / "Catalog"
        catalog.mkdir()
        (catalog / "steam-build.json").write_bytes(json_bytes({"app_id": "2393970", "branch": "public",
               "build_id": "100", "installed_depots": {"2393972": {"manifest": "200"}}}))
        (catalog / "generator.json").write_bytes(json_bytes({"schema": schema, "tools": {"fixture.py": "a" * 64}}))
        (catalog / "coverage.json").write_bytes(json_bytes({"objects": 2, "decode_failures": failures or [], "decode_gaps": []}))
        (catalog / "inputs.jsonl").write_text('{"path":"sample","sha256":"fixture"}\n')
        git(source, "add", "Catalog")
        git(source, "commit", "-m", "Synthetic input")
        wiki = self.root / "wiki"
        wiki.mkdir()
        return wiki, source

    def test_valid_manifest_and_semantic_cycles(self):
        owners = manifest.validate(self.root, self.project)
        self.assertEqual("items-equipment", owners["item"])
        self.assertEqual("technical-reference", owners["unclassified"])
        order = manifest.stage_order(self.project)
        self.assertLess(order.index("identity"), order.index("project"))

    def test_duplicate_entity_owner_rejected(self):
        self.project["repositories"][2]["owns"].append("item")
        with self.assertRaisesRegex(ContractError, "multiple owners"):
            manifest.validate(self.root, self.project)

    def test_missing_relation_target_rejected(self):
        self.project["relationships"][0]["to"] = "missing"
        with self.assertRaisesRegex(ContractError, "target is missing"):
            manifest.validate(self.root, self.project)

    def test_pipeline_cycle_rejected(self):
        self.project["pipeline"][0]["depends_on"] = ["publish"]
        with self.assertRaisesRegex(ContractError, "cycle"):
            manifest.validate(self.root, self.project)

    def test_checkout_path_escape_rejected(self):
        self.project["repositories"][0]["path"] = "../other"
        with self.assertRaisesRegex(ContractError, "checkout path"):
            manifest.validate(self.root, self.project)

    def test_case_colliding_remote_names_rejected(self):
        self.project["repositories"][1]["github_name"] = self.project["repositories"][0]["github_name"].lower()
        with self.assertRaisesRegex(ContractError, "Duplicate GitHub name"):
            manifest.validate(self.root, self.project)

    def test_registry_map_is_deterministic(self):
        result = manifest.repository_map(self.project)
        self.assertEqual(result, manifest.repository_map(self.project))
        self.assertIn(b"Semantic cycles and backlinks are expected", result)
        for repo in self.project["repositories"]:
            self.assertIn(repo["github_name"].encode(), result)

    def test_initialize_independent_repositories_and_preserve_edits_on_repeat(self):
        created = workspace.initialize(self.root, self.project)
        self.assertEqual(13, len(created))
        hub = self.root / "repositories/hub"
        (hub / "README.md").write_text("user-owned edits\n")
        self.assertEqual([], workspace.initialize(self.root, self.project))
        self.assertEqual("user-owned edits\n", (hub / "README.md").read_text())
        for repo in self.project["repositories"]:
            state = workspace.inspect(self.root, repo)
            self.assertEqual([], state["remotes"])
            self.assertEqual("dirty", state["state"])

    def test_unknown_existing_path_prevents_any_initialization(self):
        unknown = self.root / "repositories/combat"
        unknown.mkdir(parents=True)
        (unknown / "keep.txt").write_text("belongs to someone else")
        with self.assertRaisesRegex(ContractError, "Not an independent"):
            workspace.initialize(self.root, self.project)
        self.assertFalse((self.root / "repositories/hub").exists())
        self.assertEqual("belongs to someone else", (unknown / "keep.txt").read_text())

    def test_inherited_parent_git_repository_is_not_a_child(self):
        git(self.root, "init", "--initial-branch=main")
        (self.root / "repositories/hub").mkdir(parents=True)
        with self.assertRaisesRegex(ContractError, "Not an independent"):
            workspace.inspect(self.root, self.project["repositories"][0])

    def test_registration_pins_real_commit_and_repeats_without_rewriting(self):
        wiki, source = self.git_source()
        receipt = snapshots.register(wiki, self.project, source)
        path = wiki / "snapshots" / (receipt["snapshot_id"] + ".json")
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        again = snapshots.register(wiki, self.project, source)
        self.assertEqual(receipt, again)
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        self.assertEqual(git(source, "rev-parse", "HEAD"), receipt["source_commit"])
        self.assertIsNone(receipt["game_version"])
        self.assertEqual("not-performed", receipt["wiki_verification"])
        self.assertFalse((wiki / "Catalog").exists())
        self.assertEqual("", git(source, "status", "--porcelain"))

    def test_dirty_source_rejected_without_receipt(self):
        wiki, source = self.git_source()
        (source / "notes.txt").write_text("uncommitted work")
        with self.assertRaisesRegex(ContractError, "dirty"):
            snapshots.register(wiki, self.project, source)
        self.assertFalse((wiki / "snapshots").exists())

    def test_application_version_requires_pinned_source_evidence_and_preserves_older_receipt(self):
        wiki, source = self.git_source()
        older = snapshots.register(wiki, self.project, source)
        old_path = wiki / "snapshots" / (older["snapshot_id"] + ".json")
        old_bytes = old_path.read_bytes()
        item = {"source_path": "Human Host_Data/globalgamemanagers", "source_sha256": "a" * 64,
                "object_id": "globalgamemanagers#1", "field": "/bundleVersion"}
        value = {"schema": 1, "status": "recorded", "version": "0.8.315", "evidence": [item]}
        (source / "Catalog/game-version.json").write_bytes(json_bytes(value))
        (source / "Catalog/inputs.jsonl").write_bytes(json_bytes({"path": item["source_path"], "sha256": item["source_sha256"]}).replace(b"\n", b"") + b"\n")
        git(source, "add", "Catalog")
        git(source, "commit", "-m", "Capture application version")
        recorded = snapshots.register(wiki, self.project, source)
        self.assertEqual(recorded["game_version"], "0.8.315")
        self.assertEqual(recorded["game_version_evidence"], [item])
        self.assertIn("Catalog/game-version.json", recorded["catalog_metadata_sha256"])
        self.assertEqual(recorded, snapshots.register(wiki, self.project, source))
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertIsNone(older["game_version"])
        value["evidence"][0]["source_sha256"] = "b" * 64
        (source / "Catalog/game-version.json").write_bytes(json_bytes(value))
        git(source, "add", "Catalog")
        git(source, "commit", "-m", "Mismatched evidence fixture")
        with self.assertRaisesRegex(ContractError, "pinned input"):
            snapshots.register(wiki, self.project, source)
        self.assertEqual(len(list((wiki / "snapshots").glob("*.json"))), 2)

    def test_unknown_and_malformed_game_version_metadata(self):
        wiki, source = self.git_source()
        revision = git(source, "rev-parse", "HEAD")
        value = {"schema": 1, "status": "unknown", "version": None, "evidence": [], "reason": "missing-player-settings"}
        self.assertEqual(snapshots.game_version(source, revision, value)["game_version_reason"], "missing-player-settings")
        for invalid in ([], {**value, "schema": 2}, {**value, "version": "invented"},
                        {**value, "reason": "machine/path"}, {**value, "status": "recorded", "version": "line\nbreak"}):
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                snapshots.game_version(source, revision, invalid)

    def test_source_remote_rejected(self):
        wiki, source = self.git_source()
        git(source, "remote", "add", "origin", "https://example.invalid/source.git")
        with self.assertRaisesRegex(ContractError, "must not have a remote"):
            snapshots.register(wiki, self.project, source)

    def test_unknown_catalog_schema_rejected(self):
        wiki, source = self.git_source(schema=999)
        with self.assertRaisesRegex(ContractError, "Unsupported catalog schema"):
            snapshots.register(wiki, self.project, source)

    def test_decode_failures_rejected(self):
        wiki, source = self.git_source(failures=["broken fixture"])
        with self.assertRaisesRegex(ContractError, "decode failures"):
            snapshots.register(wiki, self.project, source)

    def test_snapshot_collision_preserves_prior_receipt(self):
        wiki, source = self.git_source()
        receipt = snapshots.register(wiki, self.project, source)
        path = wiki / "snapshots" / (receipt["snapshot_id"] + ".json")
        path.write_text("prior receipt was edited\n")
        with self.assertRaisesRegex(ContractError, "collision"):
            snapshots.register(wiki, self.project, source)
        self.assertEqual("prior receipt was edited\n", path.read_text())

    def test_snapshot_identifier_cannot_escape_directory(self):
        with self.assertRaisesRegex(ContractError, "Invalid snapshot"):
            snapshots.read(self.root, "../../other")

    def test_preview_links_cover_every_topic_and_input_is_escaped(self):
        self.project["repositories"][1]["title"] = '<script>alert("x")</script>'
        files = navigation.render(self.project, None)
        navigation.validate_links(files)
        self.assertEqual(13, len(files))
        self.assertNotIn(b"<script>", files["index.html"])
        for name, data in files.items():
            self.assertIn(b"Gameplay articles are not generated", data)
            self.assertIn(b"start here", data)

    def test_missing_link_and_unsafe_scheme_rejected(self):
        for href in ["missing.html", "../../escape.html", "javascript:alert(1)"]:
            with self.subTest(href=href), self.assertRaises(ContractError):
                navigation.validate_links({"index.html": f'<a href="{href}">link</a>'.encode()})

    def test_preview_repeat_is_byte_and_pointer_stable(self):
        first = navigation.build(self.root, self.project)
        pointer = self.root / ".local/preview.json"
        before = (pointer.read_bytes(), pointer.stat().st_mtime_ns)
        second = navigation.build(self.root, self.project)
        self.assertEqual(first, second)
        self.assertEqual(before, (pointer.read_bytes(), pointer.stat().st_mtime_ns))

    def test_modified_preview_rejected_without_overwrite(self):
        result = navigation.build(self.root, self.project)
        entry = Path(result["entry"])
        entry.write_text("local investigation")
        with self.assertRaisesRegex(ContractError, "was modified"):
            navigation.build(self.root, self.project)
        self.assertEqual("local investigation", entry.read_text())

    def test_failure_before_promotion_preserves_previous_preview_and_retry_works(self):
        first = navigation.build(self.root, self.project)
        pointer = self.root / ".local/preview.json"
        old_pointer = pointer.read_bytes()
        self.project["repositories"][1]["coverage"] += "; amended"
        with patch("wikibuild.navigation.os.rename", side_effect=OSError("injected promotion failure")):
            with self.assertRaisesRegex(OSError, "injected"):
                navigation.build(self.root, self.project)
        self.assertEqual(old_pointer, pointer.read_bytes())
        self.assertTrue(Path(first["entry"]).exists())
        second = navigation.build(self.root, self.project)
        self.assertNotEqual(first["build_id"], second["build_id"])
        self.assertEqual(second["build_id"], json.loads(pointer.read_text())["build_id"])

    def test_writer_exclusion_and_release(self):
        with writer_lock(self.root):
            with self.assertRaisesRegex(ContractError, "Another wiki writer"):
                with writer_lock(self.root):
                    self.fail("Second writer acquired lock")
        with writer_lock(self.root):
            self.assertTrue((self.root / ".local/writer.lock").exists())

    def test_blocked_writer_names_the_holder(self):
        # A stuck run once held the lock for three days with no clue who owned it.
        with writer_lock(self.root):
            with self.assertRaisesRegex(ContractError, rf"held by PID {os.getpid()} \(running\) since .+ for \d+ min"):
                with writer_lock(self.root):
                    self.fail("Second writer acquired lock")
        self.assertFalse((self.root / ".local/writer.lock.owner.json").exists())

    def test_unqueryable_holder_is_not_reported_as_stopped(self):
        from wikibuild import storage
        with writer_lock(self.root), patch.object(storage, "process_running", return_value=None):
            with self.assertRaisesRegex(ContractError, r"status unknown"):
                with writer_lock(self.root):
                    self.fail("Second writer acquired lock")

    def test_atomic_write_does_not_rewrite_unchanged_file(self):
        path = self.root / "result.json"
        self.assertTrue(write_changed(path, b"{}\n"))
        stamp = path.stat().st_mtime_ns
        self.assertFalse(write_changed(path, b"{}\n"))
        self.assertEqual(stamp, path.stat().st_mtime_ns)

    def test_checkout_lock_detects_dirty_and_changed_child_commit(self):
        self.project["repositories"] = self.project["repositories"][:1]
        workspace.initialize(self.root, self.project)
        hub = self.root / "repositories/hub"
        git(hub, "config", "user.name", "Wiki tests")
        git(hub, "config", "user.email", "wiki-tests@example.invalid")
        with self.assertRaisesRegex(ContractError, "dirty"):
            workspace.checkout_lock(self.root, self.project)
        git(hub, "add", ".wiki-repository.json", "README.md", ".gitignore", ".gitattributes")
        git(hub, "commit", "-m", "Initial synthetic repository")
        receipt = workspace.checkout_lock(self.root, self.project)
        self.assertEqual("local-checkout-baseline", receipt["kind"])
        workspace.checkout_lock(self.root, self.project, check=True)
        (hub / "README.md").write_text("reviewed new content\n")
        git(hub, "add", "README.md")
        git(hub, "commit", "-m", "Synthetic later revision")
        with self.assertRaisesRegex(ContractError, "differs"):
            workspace.checkout_lock(self.root, self.project, check=True)

    def test_documentation_local_links_and_plain_punctuation(self):
        documents = [PROJECT_ROOT / "README.md", PROJECT_ROOT / "AGENTS.md",
                     PROJECT_ROOT / "snapshots/README.md", PROJECT_ROOT / "releases/README.md",
                     *sorted((PROJECT_ROOT / "docs").rglob("*.md"))]
        for document in documents:
            text = document.read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, document.name)
            for href in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                parsed = urlparse(href)
                if parsed.scheme:
                    continue
                target = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
                self.assertTrue(target.is_file(), f"Broken document link: {document.name}: {href}")
                if parsed.fragment:
                    headings = re.findall(r"^#+ (.+)$", target.read_text(encoding="utf-8"), flags=re.MULTILINE)
                    anchors = {re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-") for title in headings}
                    self.assertIn(parsed.fragment, anchors, f"Missing anchor: {document.name}: {href}")


if __name__ == "__main__":
    unittest.main()
