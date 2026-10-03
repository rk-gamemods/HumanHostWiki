"""Real publication engine, fake GitHub reads and disposable Git storage."""

from dataclasses import replace
from pathlib import Path
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_publication
from tools import rehearse_publication
from wikibuild import capacity, capacity_inventory, github_pages, publication, publication_git, publish_gate, workspace
from wikibuild.storage import ContractError, git

GATE_CHECK = publish_gate.check


class DisposableCleanupTests(unittest.TestCase):
    def test_storage_timeout_uses_bounded_descendant_cleanup(self):
        bounded = publication_git.bounded
        real_run, real_popen = bounded.run, subprocess.Popen
        processes = []

        def sleeper(command, **kwargs):
            if command[0] == "git":
                command = [sys.executable, "-c", "import time; time.sleep(60)"]
            process = real_popen(command, **kwargs)
            if command[0] == sys.executable:
                processes.append(process)
            return process

        def short_timeout(command, **kwargs):
            self.assertEqual(kwargs.pop("timeout"), 120)
            self.assertEqual(kwargs["env"]["GIT_CONFIG_NOSYSTEM"], "1")
            return real_run(command, timeout=0.1, **kwargs)

        with patch.object(bounded.subprocess, "Popen", side_effect=sleeper), \
                patch.object(bounded, "run", side_effect=short_timeout), \
                patch.object(bounded, "kill_tree", wraps=bounded.kill_tree) as cleanup:
            with self.assertRaisesRegex(ContractError, "storage command timed out"):
                publication_git.storage_snapshot(Path(tempfile.gettempdir()))
        cleanup.assert_called_once_with(processes[0])
        self.assertIsNotNone(processes[0].poll())
        for stream in (processes[0].stdout, processes[0].stderr):
            stream.close()

    def test_clone_ignores_global_hooks_filters_templates_and_git_routing(self):
        root = Path(tempfile.gettempdir()).resolve() / ("hhwiki-publication-" + uuid4().hex)
        root.mkdir()
        self.addCleanup(publication_git.remove_disposable, root)
        source, destination = root / "source", root / "clone"
        source.mkdir()
        git(source, "init", "-b", "main")
        git(source, "config", "user.name", "Safe fixture")
        git(source, "config", "user.email", "fixture@example.invalid")
        (source / "data.txt").write_text("raw data\n")
        (source / ".gitattributes").write_text("*.txt filter=custom\n")
        git(source, "add", ".")
        git(source, "commit", "-m", "Fixture")
        revision = git(source, "rev-parse", "HEAD")
        hooks, template = root / "hooks", root / "template"
        hooks.mkdir()
        (template / "hooks").mkdir(parents=True)
        marker, filtered = root / "hook-marker", root / "filter-marker"
        script = "#!/bin/sh\nprintf hook > '" + marker.as_posix() + "'\n"
        for path in (hooks / "post-checkout", template / "hooks/post-checkout"):
            path.write_text(script)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        config = root / "global.gitconfig"
        config.write_text('[core]\n hooksPath = "' + hooks.as_posix() + '"\n'
                          '[init]\n templateDir = "' + template.as_posix() + '"\n'
                          '[filter "custom"]\n clean = cat\n smudge = "echo filtered > ' + filtered.as_posix() + '; cat"\n required = true\n')
        # Positive control: this exact global hook really runs on an ordinary checkout.
        (source / "data.txt").unlink()
        with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)}):
            git(source, "checkout", revision, "--", "data.txt")
        self.assertTrue(marker.exists())
        self.assertTrue(filtered.exists())
        marker.unlink()
        filtered.unlink()
        before = publication_git.storage_snapshot(source)
        inherited = {"GIT_CONFIG_GLOBAL": str(config), "GIT_DIR": str(source / ".git"),
                     "GIT_WORK_TREE": str(source), "GIT_INDEX_FILE": str(root / "poison-index"),
                     "GIT_OBJECT_DIRECTORY": str(root / "poison-objects"),
                     "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath",
                     "GIT_CONFIG_VALUE_0": str(hooks)}
        with patch.dict(os.environ, inherited), patch.object(publication_git.bounded, "run", wraps=publication_git.bounded.run) as commands:
            publication_git.disposable_clone(source, destination, revision)
            self.assertEqual(publication_git.storage_snapshot(source), before)
        self.assertFalse(marker.exists())
        self.assertFalse(filtered.exists())
        self.assertFalse((root / "poison-index").exists())
        self.assertEqual((destination / "data.txt").read_text(), "raw data\n")
        self.assertFalse((destination / ".git/hooks").exists())
        self.assertEqual(list(Path(git(destination, "config", "core.hooksPath")).iterdir()), [])
        for call in commands.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 120)
            env = call.kwargs["env"]
            self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertTrue(all(key not in env for key in inherited if key != "GIT_CONFIG_GLOBAL"))
        clone = next(call.args[0] for call in commands.call_args_list if "clone" in call.args[0])
        self.assertIn("--template=", clone)
        self.assertIn("--no-checkout", clone)

    def test_cleanup_rejects_real_repository_paths(self):
        with patch.object(publication_git.shutil, "rmtree") as remove:
            with self.assertRaisesRegex(ContractError, "outside an owned temp root"):
                publication_git.remove_disposable(Path(__file__).resolve().parents[1])
            remove.assert_not_called()

    def test_engine_git_environment_clears_routing_and_restores_on_failure(self):
        inherited = {"GIT_DIR": "somewhere", "GIT_CONFIG_GLOBAL": "custom", "GIT_CONFIG_COUNT": "1"}
        with patch.dict(os.environ, inherited):
            before = dict(os.environ)
            with self.assertRaisesRegex(ContractError, "engine failure"):
                with rehearse_publication.isolated_git_environment():
                    self.assertNotIn("GIT_DIR", os.environ)
                    self.assertNotIn("GIT_CONFIG_COUNT", os.environ)
                    self.assertEqual(os.environ["GIT_CONFIG_GLOBAL"], os.devnull)
                    self.assertEqual(os.environ["GIT_CONFIG_NOSYSTEM"], "1")
                    raise ContractError("engine failure")
            self.assertEqual(dict(os.environ), before)

    def test_cleanup_retries_only_readonly_git_objects_and_propagates_other_failures(self):
        root = Path(tempfile.gettempdir()) / ("hhwiki-rehearsal-" + "a" * 32)
        failure = PermissionError("read-only object")
        for name, mode, retry in (("repo/.git/objects/ab/cd", stat.S_IFREG | stat.S_IREAD, os.name == "nt"),
                                  ("backup/receipt.json", stat.S_IFREG | stat.S_IREAD, False),
                                  ("repo/.git/objects/ab/cd", stat.S_IFREG | stat.S_IWRITE, False)):
            with self.subTest(name=name, mode=mode):
                def failed_remove(path, *, onerror):
                    onerror(os.unlink, str(root / name), (PermissionError, failure, None))
                with patch.object(Path, "exists", return_value=True), \
                        patch.object(Path, "stat", return_value=SimpleNamespace(st_mode=mode)), \
                        patch.object(Path, "chmod") as chmod, patch.object(os, "unlink") as unlink, \
                        patch.object(publication_git.shutil, "rmtree", side_effect=failed_remove):
                    if retry:
                        publication_git.remove_disposable(root)
                        chmod.assert_called_once_with(mode | stat.S_IWRITE)
                        unlink.assert_called_once_with(str(root / name))
                    else:
                        with self.assertRaises(PermissionError):
                            publication_git.remove_disposable(root)
                        chmod.assert_not_called()
                        unlink.assert_not_called()


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        fixture = test_publication.PublicationTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.fixture = fixture
        self.root, self.project, self.manifest = fixture.root, fixture.project, fixture.manifest
        self.remote = fixture.host
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "Rehearsal fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        (self.root / ".gitignore").write_text(".local/\nrepositories/\nreleases/\npublications/\nremote-store/\n*-empty-hooks/\n")
        (self.root / "code.txt").write_text("reviewed code")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Reviewed fixture")
        self.path = publish_gate.receipt_path(self.root, self.manifest["release_id"])
        api = patch.object(github_pages.GitHubPages, "api", side_effect=self.read_api)
        self.api = api.start()
        self.addCleanup(api.stop)

    def read_api(self, method, path, **kwargs):
        self.assertEqual(method, "GET", "Rehearsal attempted a GitHub write")
        name = path.split("/")[2]
        if "/git/ref/heads/" in path:
            sha = self.remote.ref(name, path.rsplit("/", 1)[1])
            return {"object": {"sha": sha}} if sha else None
        if path.endswith("/pages"):
            return self.remote.pages.get(name)
        if len(path.split("/")) == 3:
            return self.remote.repository(name)
        raise AssertionError(f"Unexpected rehearsal read: {path}")

    def rehearse(self):
        return rehearse_publication.rehearse(self.root, self.project, self.manifest, lambda message: None)

    def storage(self):
        return {key: publication_git.storage_snapshot(self.root / record["path"])
                for key, record in self.manifest["repositories"].items()}

    def existing_release(self):
        self.fixture.run_publish()
        self.fixture.next_release()
        self.manifest = self.fixture.manifest
        self.path = publish_gate.receipt_path(self.root, self.manifest["release_id"])
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Reviewed fixture update")

    def abandoned_temp(self, *, marked=True):
        temporary = Path(tempfile.gettempdir()).resolve() / ("hhwiki-rehearsal-" + uuid4().hex)
        temporary.mkdir()
        self.addCleanup(publication_git.remove_disposable, temporary)
        record = {"path": str(temporary), "workspace": str(self.root.resolve()), "nonce": uuid4().hex,
                  "created_dirs": []}
        if marked:
            publication.save(temporary / rehearse_publication.TEMP_MARKER,
                             {"workspace": record["workspace"], "nonce": record["nonce"]})
        publication.save(self.root / rehearse_publication.TEMP_RECORD, record)
        return temporary

    def test_next_invocation_cleans_only_recorded_marked_temp_root_and_prints_new_path(self):
        abandoned = self.abandoned_temp()
        unrelated = Path(tempfile.gettempdir()).resolve() / ("hhwiki-rehearsal-" + uuid4().hex)
        unrelated.mkdir()
        self.addCleanup(publication_git.remove_disposable, unrelated)
        (abandoned / "leftover.txt").write_text("abandoned")
        (unrelated / "keep.txt").write_text("unrecorded")
        messages = []
        rehearse_publication.rehearse(self.root, self.project, self.manifest, messages.append)
        self.assertFalse(abandoned.exists())
        self.assertEqual((unrelated / "keep.txt").read_text(), "unrecorded")
        self.assertFalse((self.root / rehearse_publication.TEMP_RECORD).exists())
        self.assertIn(f"Removing abandoned rehearsal temp root: {abandoned}", messages)
        current = next(message.removeprefix("Rehearsal temp root: ") for message in messages
                       if message.startswith("Rehearsal temp root: "))
        self.assertFalse(Path(current).exists())

    def test_temp_record_is_present_before_clone_and_removed_after_timeout(self):
        temporary = []

        def timeout(*args):
            record = publication.load(self.root / rehearse_publication.TEMP_RECORD)
            temporary.append(Path(record["path"]))
            self.assertTrue((temporary[0] / rehearse_publication.TEMP_MARKER).is_file())
            raise ContractError("Injected clone timeout")

        with patch.object(publication_git, "disposable_clone", side_effect=timeout):
            with self.assertRaisesRegex(ContractError, "clone timeout"):
                self.rehearse()
        self.assertFalse(temporary[0].exists())
        self.assertFalse((self.root / rehearse_publication.TEMP_RECORD).exists())

    def test_recovery_refuses_unmarked_root_outside_temp_and_wrong_owner(self):
        temporary = self.abandoned_temp(marked=False)
        with self.assertRaisesRegex(ContractError, "without its ownership marker"):
            self.rehearse()
        self.assertTrue(temporary.exists())
        pointer = self.root / rehearse_publication.TEMP_RECORD
        original = publication.load(pointer)
        for change in ({"path": str(self.root)}, {"workspace": "another workspace"}):
            publication.save(pointer, {**original, **change})
            with self.assertRaisesRegex(ContractError, "unowned rehearsal temp path"):
                self.rehearse()
            self.assertTrue(temporary.exists())

    def test_mixed_existing_publication_and_one_new_destination_receipt_passes_production_gate(self):
        self.fixture.run_publish()
        previous = publication.published(self.root)
        inventory = capacity_inventory.read(self.root, self.project)
        extra = {"id": "extra", "title": "Extra", "owns": [], "coverage": "Extra reference",
                 "role": "topic", "path": "repositories/extra", "github_name": "Wiki-extra"}
        self.project["repositories"].append(extra)
        workspace.initialize(self.root, self.project)
        path = self.root / extra["path"]
        git(path, "config", "user.name", "Wiki fixture")
        git(path, "config", "user.email", "wiki@example.invalid")
        git(path, "add", ".")
        git(path, "commit", "-m", "Add destination fixture")
        # The previous local release registry predates the new logical topic.
        # This fixture starts its next local release from the expanded registry.
        old_registry = self.manifest["physical"]
        expanded = {**old_registry, "extra": {"topic": "extra", "ordinal": 0, "sealed": False}}
        topic = capacity.Topic("extra", "Wiki-extra")
        inventory = replace(inventory, topics=(*inventory.topics, topic),
                            partitions=(*inventory.partitions, capacity.partition(topic, 0)))
        with patch.object(workspace, "repositories", side_effect=lambda root, project, allocated=None:
                          publication.physical.repositories(project, allocated or expanded)), \
                patch.object(capacity_inventory, "read", return_value=inventory):
            self.fixture.make_release()
        self.manifest = self.fixture.manifest
        self.path = publish_gate.receipt_path(self.root, self.manifest["release_id"])
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "Review added destination fixture")
        self.assertEqual(publication.published(self.root), previous)
        self.rehearse()
        receipt = publication.load(self.path)
        observations = {row["repository"]: row["observed"] for row in receipt["destination_observations"]}
        self.assertEqual(observations, {"Wiki-hub": "present", "Wiki-items": "present",
                                        "Wiki-loot": "present", "Wiki-extra": "absent"})
        sha = git(self.root, "rev-parse", "HEAD")
        real_git = publish_gate.git
        real_api = self.remote.api

        def gate_git(root, *args):
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/rk-gamemods/HumanHostWiki.git"
            if args[0] == "fetch":
                return ""
            if args == ("rev-parse", "refs/remotes/origin/main"):
                return sha
            return real_git(root, *args)

        def gate_api(method, endpoint, **kwargs):
            if "actions/runs?head_sha=" in endpoint:
                return {"workflow_runs": [{"id": 1, "name": "CI", "head_sha": sha,
                    "path": publish_gate.CI_PATH, "event": "push", "head_branch": "main",
                    "status": "completed", "conclusion": "success"}]}
            if endpoint.endswith("/pulls"):
                return [{"number": 1, "merged_at": "2026-10-03T00:00:00Z", "merge_commit_sha": sha}]
            return real_api(method, endpoint, **kwargs)

        with patch.object(publish_gate, "git", side_effect=gate_git), \
                patch.object(self.remote, "api", side_effect=gate_api), \
                patch.object(publish_gate.github_pages, "GitHubPages", return_value=self.remote), \
                patch.object(publish_gate, "check", GATE_CHECK):
            result = publish_gate.check(self.root, self.project, self.manifest)
        self.assertEqual(result["rehearsal"], receipt)
        self.assertNotIn("Wiki-extra", self.remote.repos)

    def test_real_engine_isolated_refs_pins_objects_state_and_repeat(self):
        self.existing_release()
        for record in self.manifest["repositories"].values():
            git(self.root / record["path"], "pack-refs", "--all")
        before = self.storage()
        self.assertTrue(all("packed-refs" in row["pins"] for row in before.values()))
        state = rehearse_publication.state_snapshot(self.root)
        real_run, clones = publication._run, []

        def engine(root, project, manifest, host, *args):
            self.assertFalse(root.is_relative_to(self.root))
            self.assertEqual(set(host.paths.values()), {root / row["path"] for row in manifest["repositories"].values()})
            result = real_run(root, project, manifest, host, *args)
            for path in host.paths.values():
                self.assertTrue(git(path, "for-each-ref", "refs/wiki-publications"))
                clones.append(path)
            self.assertTrue((root / ".local/publication/pending.json").exists())
            self.assertTrue((root / "publications/latest.json").exists())
            return result

        for attempt in range(2):
            with patch.object(publication, "_run", side_effect=engine), \
                    patch.object(publication, "run", side_effect=AssertionError("Production wrapper in rehearsal")):
                self.assertEqual(self.rehearse(), self.path)
            self.assertEqual(self.storage(), before)
            self.assertTrue(all(not path.exists() for path in clones))
            self.path.unlink()
            self.path.parent.rmdir()
            self.assertEqual(rehearse_publication.state_snapshot(self.root), state)

    def test_fetches_and_new_pages_pins_never_reach_real_children(self):
        self.existing_release()
        source = self.root / "repositories/items"
        remote_store = self.root / "remote-store"
        publication_git.disposable_clone(source, remote_store, self.manifest["repositories"]["items"]["commit"])
        prior = publication.published(self.root)["repositories"]["items"]["pages"]
        restored = publication_git.commit(remote_store, git(source, "rev-parse", prior + "^{tree}"), prior, "Remote restore")
        self.remote.refs[("Wiki-items", "gh-pages")] = restored
        before = self.storage()
        fetched = []

        def fetch(host, path, name, branch):
            self.assertFalse(path.is_relative_to(self.root))
            git(path, "fetch", "--no-tags", str(remote_store), f"{restored}:refs/remotes/fake/gh-pages")
            fetched.append(path)

        with patch.object(rehearse_publication.RehearsalHost, "fetch", fetch):
            self.rehearse()
        self.assertTrue(fetched)
        self.assertEqual(self.storage(), before)
        self.assertFalse(publication_git.owned_lineage(source, prior, restored))
        self.assertNotEqual(subprocess.run(["git", "-C", str(source), "cat-file", "-e", restored], capture_output=True).returncode, 0)

    def test_missing_destinations_record_absence_and_provision_only_in_simulation(self):
        before = self.storage()
        self.rehearse()
        receipt = publication.load(self.path)
        self.assertEqual(receipt["destination_observations"], [
            {"repository": name, "observed": "absent"} for name in ("Wiki-hub", "Wiki-items", "Wiki-loot")])
        self.assertTrue(all(row["commit"] is None for row in receipt["remote_refs"]))
        self.assertEqual(self.remote.events, [])
        self.assertEqual(self.storage(), before)
        self.assertFalse((self.root / ".local/publication/remotes").exists())
        self.assertFalse((self.root / "publications").exists())

    def test_disabled_pages_records_identity_and_simulates_enable(self):
        self.existing_release()
        self.remote.pages.pop("Wiki-items")
        before = self.storage()
        self.rehearse()
        observations = {row["repository"]: row for row in publication.load(self.path)["destination_observations"]}
        self.assertEqual(observations["Wiki-items"]["observed"], "pages-disabled")
        self.assertEqual(observations["Wiki-items"]["repository_id"], self.remote.repos["Wiki-items"]["id"])
        self.assertEqual(observations["Wiki-hub"]["observed"], "present")
        self.assertNotIn("Wiki-items", self.remote.pages)
        self.assertEqual(self.storage(), before)

    def test_wrong_cname_and_url_fail_before_any_simulated_push(self):
        self.existing_release()
        for key, value, message in (("cname", "other.example", "Pages configuration"),
                                    ("html_url", "https://other.example/", "Pages URL")):
            with self.subTest(key=key):
                old = self.remote.pages["Wiki-items"][key]
                self.remote.pages["Wiki-items"][key] = value
                before = self.storage()
                with patch.object(rehearse_publication.RehearsalHost, "push") as push:
                    with self.assertRaisesRegex(ContractError, message):
                        self.rehearse()
                    push.assert_not_called()
                self.assertEqual(self.storage(), before)
                self.assertFalse(self.path.exists())
                self.remote.pages["Wiki-items"][key] = old

    def test_failed_engine_leaves_original_state_and_no_receipt(self):
        publication.save(self.root / ".local/publication/pending.json", {"phase": "complete"})
        state, storage, engines = rehearse_publication.state_snapshot(self.root), self.storage(), []

        def fail(root, *args):
            engines.append(root)
            publication.save(root / ".local/publication/pending.json", {"phase": "simulated"})
            publication.save(root / "publications/latest.json", {"release_id": self.manifest["release_id"]})
            raise ContractError("Injected rehearsal failure")

        with patch.object(publication, "_run", side_effect=fail):
            with self.assertRaisesRegex(ContractError, "Injected rehearsal failure"):
                self.rehearse()
        self.assertEqual(rehearse_publication.state_snapshot(self.root), state)
        self.assertEqual(self.storage(), storage)
        self.assertFalse(self.path.exists())
        self.assertTrue(all(not root.parent.exists() for root in engines))

    def test_restore_failure_keeps_durable_backup_and_displaced_original(self):
        pending = self.root / ".local/publication/pending.json"
        publication.save(pending, {"phase": "complete"})
        before, saved_roots = pending.read_bytes(), []
        copytree = shutil.copytree

        def fail_restore(source, target, *args, **kwargs):
            if Path(target) == pending.parent:
                raise OSError("Injected restore failure")
            return copytree(source, target, *args, **kwargs)

        def escaped_write(engine, *args):
            saved_roots.append(engine.parent)
            self.addCleanup(publication_git.remove_disposable, engine.parent)
            publication.save(pending, {"phase": "escaped"})
            return {"status": "published"}, {}

        with patch.object(publication, "_run", side_effect=escaped_write), \
                patch.object(rehearse_publication.shutil, "copytree", side_effect=fail_restore):
            with self.assertRaisesRegex(ContractError, "restore failed; durable backup retained"):
                self.rehearse()
        retained = saved_roots[0]
        self.assertEqual((retained / "backup/.local/publication/pending.json").read_bytes(), before)
        self.assertTrue((retained / "displaced/.local/publication/pending.json").exists())
        self.assertFalse(self.path.exists())
        record = publication.load(self.root / rehearse_publication.TEMP_RECORD)
        self.assertEqual(record["path"], str(retained))
        self.assertTrue(record["recovery_required"])
        with self.assertRaisesRegex(ContractError, "requires the retained backup"):
            self.rehearse()
        self.assertTrue(retained.exists())

    def test_verified_restore_discards_backup_but_refuses_receipt(self):
        pending = self.root / ".local/publication/pending.json"
        publication.save(pending, {"phase": "complete"})
        before, engines = pending.read_bytes(), []

        def escaped_write(engine, *args):
            engines.append(engine)
            publication.save(pending, {"phase": "escaped"})
            return {"status": "published"}, {}

        with patch.object(publication, "_run", side_effect=escaped_write):
            with self.assertRaisesRegex(ContractError, "changed original publication state; restored"):
                self.rehearse()
        self.assertEqual(pending.read_bytes(), before)
        self.assertTrue(all(not engine.parent.exists() for engine in engines))
        self.assertFalse(self.path.exists())

    def test_dirty_and_pending_refuse_before_isolation_or_host(self):
        for kind in ("tracked", "untracked", "pending"):
            with self.subTest(kind=kind):
                path = self.root / ("code.txt" if kind == "tracked" else "untracked.txt" if kind == "untracked" else ".local/publication/pending.json")
                if kind == "pending":
                    publication.save(path, {"phase": "topics"})
                else:
                    path.write_text("dirty")
                with patch.object(rehearse_publication, "isolated_workspace") as isolation, \
                        patch.object(rehearse_publication, "RehearsalHost") as host:
                    with self.assertRaisesRegex(ContractError, "abandon-publication" if kind == "pending" else "workspace must be clean"):
                        self.rehearse()
                    isolation.assert_not_called()
                    host.assert_not_called()
                if kind == "tracked":
                    path.write_text("reviewed code")
                else:
                    path.unlink()

    def test_runner_contract_drift_and_disabled_run_prevent_receipt(self):
        contract = publication.contract()
        changed = {**contract, "tools/rehearse_publication.py": "f" * 64}
        with patch.object(publication, "contract", side_effect=[contract, changed]), \
                patch.object(publication, "_run", return_value=({"status": "published"}, {})):
            with self.assertRaisesRegex(ContractError, "contract changed"):
                self.rehearse()
        with patch.object(publication, "_run", return_value=({"status": "disabled"}, {})):
            with self.assertRaisesRegex(ContractError, "did not complete"):
                self.rehearse()
        self.assertFalse(self.path.exists())

    def test_real_ref_drift_does_not_replace_observations(self):
        host = rehearse_publication.RehearsalHost("fixture", {}, lambda message: None)
        with patch.object(github_pages.GitHubPages, "api", side_effect=[
                {"object": {"sha": "c" * 40}}, {"object": {"sha": "d" * 40}}]):
            self.assertEqual(host.ref("Wiki-hub", "main"), "c" * 40)
            with self.assertRaisesRegex(ContractError, "changed during rehearsal"):
                host.ref("Wiki-hub", "main")
        host.simulated[("Wiki-hub", "main")] = "e" * 40
        self.assertEqual(host.ref("Wiki-hub", "main"), "e" * 40)
        self.assertEqual(host.observed[("Wiki-hub", "main")], "c" * 40)
        with self.assertRaisesRegex(ContractError, "forbids GitHub writes"):
            host.api("POST", "must-never-run")


if __name__ == "__main__":
    unittest.main()
