"""Exercise publication ordering, abandonment and rollback with real Git trees."""

import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import itertools
import json
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import patch

import test_release
from tests.test_github_pages import Clock
from wikibuild import github_pages, publication, publication_git, reader, release, workspace
from wikibuild.storage import ContractError, git, json_bytes


class Host:
    def __init__(self, owner):
        self.owner = owner
        self.repos, self.refs, self.paths = {}, {}, {}
        self.events, self.verified = [], []
        self.fail_name = None
        self.interrupt_name = None

    def repository(self, name):
        return self.repos.get(name)

    def create(self, name, description):
        value = {"id": len(self.repos) + 1, "full_name": self.owner + "/" + name, "description": description,
                 "private": False, "archived": False, "fork": False, "permissions": {"admin": True}}
        self.repos[name] = value
        self.events.append(("create", name))
        return value

    def ref(self, name, branch):
        return self.refs.get((name, branch))

    def gate(self, root, project, manifest):
        return {"rehearsal": {"fixture": True, "remote_refs": [
            {"repository": name, "branch": branch, "commit": self.ref(name, branch)}
            for name, branch in sorted(publication.publish_gate.destinations(root, project, manifest))]}}

    def push(self, path, name, commit, branch, expected):
        current = self.ref(name, branch)
        if current == commit:
            return
        if current != expected:
            raise ContractError("Remote branch changed")
        if current:
            result = subprocess.run(["git", "-C", str(path), "merge-base", "--is-ancestor", current, commit], capture_output=True)
            if result.returncode:
                raise ContractError("Non-fast-forward push")
        self.paths[name] = path
        self.refs[(name, branch)] = commit
        self.events.append(("push", name, branch, commit))
        if self.interrupt_name == name and branch == "gh-pages":
            self.interrupt_name = None
            raise KeyboardInterrupt("Interrupted after remote accepted push")

    def configure(self, name):
        self.events.append(("configure", name))

    def wait(self, name, commit):
        if self.ref(name, "gh-pages") != commit:
            raise ContractError("Wrong build commit")

    def verify(self, base, files, **kwargs):
        name = base.rstrip("/").rsplit("/", 1)[1]
        if self.fail_name == name:
            self.fail_name = None
            raise ContractError("Injected public hash failure")
        path, commit = self.paths[name], self.ref(name, "gh-pages")
        for name_in_tree, expected in files.items():
            data = subprocess.check_output(["git", "-C", str(path), "cat-file", "blob", commit + ":" + name_in_tree])
            if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
                raise ContractError("Served Git bytes differ")
        self.verified.append((name, tuple(files)))
        self.events.append(("verified", name))


class RecoveryHost(Host):
    """Real Pages polling against fake API records and real local Git trees."""
    def __init__(self, owner, root, mode="built"):
        super().__init__(owner)
        self.root, self.mode = root, mode
        self.target = "Wiki-items"
        self.waited, self.transitions = [], []
        self.clock = Clock()
        self.adapter = github_pages.GitHubPages(owner)
        self.adapter.clock = self.clock
        self.adapter.QUEUED_GRACE = 10
        self.adapter.api = self.api
        self.adapter.ref = lambda name, branch, **kwargs: self.ref(name, branch)

    def api(self, method, path, **kwargs):
        if method != "GET":
            raise AssertionError("Recovery must never cancel, delete or rerun a workflow")
        commit = self.waited[-1]
        if "/actions/runs?" in path:
            return {"workflow_runs": [{"id": 1, "head_sha": "unrelated", "name": "pages build and deployment", "status": "queued"},
                                      {"id": 2, "head_sha": commit, "name": "pages build and deployment", "status": "queued"}]}
        if "/jobs?" in path:
            return {"total_count": 0, "jobs": []}
        return {"commit": commit, "status": "built" if len(self.waited) == 2 and self.mode != "stuck" else "queued"}

    def wait(self, name, commit, **kwargs):
        if name != self.target:
            return super().wait(name, commit)
        self.waited.append(commit)
        with patch.object(github_pages.time, "sleep", side_effect=self.clock.sleep):
            try:
                return self.adapter.wait(name, commit, **kwargs)
            except github_pages.QueuedPagesError:
                if self.mode == "drift":
                    self.refs[(name, "gh-pages")] = "foreign"
                raise

    def push(self, path, name, commit, branch, expected):
        if name == self.target and branch == "gh-pages" and self.waited:
            plan = publication.load(self.root / ".local/publication/pending.json")["repositories"]["items"]
            transition = plan["recovery"]
            if transition != {"stuck": expected, "successor": commit, "status": "prepared"}:
                raise AssertionError("Transition was not journaled before the leased push")
            self.transitions.append(transition)
            super().push(path, name, commit, branch, expected)
            if self.mode == "lost":
                raise RuntimeError("Lost successor push response")
            return
        return super().push(path, name, commit, branch, expected)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_release.ReleaseTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.project = self.fixture.root, self.fixture.project
        self.project["publication"] = {"enabled": True, "workers": 2}
        self.host = Host(self.project["github_owner"])
        # Gate refusals and bounded Git preflight are covered by test_publish_gate.
        gate = patch.object(publication.publish_gate, "check", side_effect=self.host.gate)
        self.gate = gate.start()
        self.addCleanup(gate.stop)
        self.make_release()

    def make_release(self):
        workspace.checkout_lock(self.root, self.project)
        candidate = reader.build(self.root, self.project, self.fixture.fixture.runs, bases=release.bases(self.project))
        self.manifest, _ = release.run(self.root, self.project, candidate)

    def run_publish(self):
        return publication.run(self.root, self.project, self.manifest, host=self.host)

    def next_release(self):
        self.project["official_links"] = [{"title": "Changed", "url": "https://example.invalid/"}]
        self.make_release()

    def recover(self, mode="built"):
        self.host = RecoveryHost(self.project["github_owner"], self.root, mode)
        self.gate.side_effect = self.host.gate
        return self.run_publish()

    def test_queued_build_recovers_once_and_verifies_the_same_tree(self):
        result, _ = self.recover()
        plan = result["repositories"]["items"]
        stuck, successor = self.host.waited
        path = self.root / plan["path"]
        self.assertEqual(git(path, "rev-parse", successor + "^"), stuck)
        self.assertEqual(git(path, "rev-parse", stuck + "^{tree}"), plan["tree"])
        self.assertEqual(git(path, "rev-parse", successor + "^{tree}"), plan["tree"])
        self.assertEqual(plan["pages"], successor)
        self.assertEqual(plan["recovery"], {"stuck": stuck, "successor": successor, "status": "confirmed"})
        self.assertEqual(len(self.host.transitions), 1)
        self.assertTrue(any(name == self.host.target for name, files in self.host.verified))
        # Repeat uses the confirmed successor and creates no third commit.
        self.run_publish()
        self.assertEqual(len(self.host.transitions), 1)

    def test_successor_also_stuck_fails_with_journal_and_requires_abandonment(self):
        with self.assertRaisesRegex(ContractError, "single recovery attempt is exhausted"):
            self.recover("stuck")
        state = publication.load(self.root / ".local/publication/pending.json")
        plan = state["repositories"]["items"]
        self.assertEqual(plan["recovery"]["status"], "confirmed")
        self.assertEqual(plan["pages"], self.host.waited[1])
        self.assertFalse(plan["verified"])
        self.assertEqual(len(self.host.transitions), 1)
        self.assertNotIn(("Wiki-hub", "gh-pages"), self.host.refs)
        with self.assertRaisesRegex(ContractError, "abandon-publication"):
            self.run_publish()
        self.assertEqual(len(self.host.transitions), 1)

    def test_lost_successor_push_response_is_confirmed_as_our_transition(self):
        result, _ = self.recover("lost")
        plan = result["repositories"]["items"]
        self.assertEqual(plan["pages"], self.host.ref(self.host.target, "gh-pages"))
        self.assertEqual(plan["recovery"]["status"], "confirmed")
        self.assertEqual(len(self.host.transitions), 1)

    def test_drift_after_queued_grace_aborts_without_a_successor_push(self):
        with self.assertRaisesRegex(ContractError, "Remote ref differs"):
            self.recover("drift")
        self.assertEqual(self.host.ref(self.host.target, "gh-pages"), "foreign")
        self.assertEqual(self.host.transitions, [])
        plan = publication.load(self.root / ".local/publication/pending.json")["repositories"]["items"]
        self.assertNotIn("recovery", plan)

    def test_interrupted_final_promotion_blocks_until_abandoned_and_keeps_legacy_receipt(self):
        result, _ = self.run_publish()
        legacy = {key: value for key, value in result.items() if key != "gate"}
        receipt = self.root / "publications" / (result["release_id"] + ".json")
        publication.save(receipt, legacy)
        before = receipt.read_bytes()
        pending = self.root / ".local/publication/pending.json"
        state = publication.load(pending)
        state.pop("gate")
        state["phase"] = "hub"
        publication.save(pending, state)
        with self.assertRaisesRegex(ContractError, "abandon-publication"):
            self.run_publish()
        publication.abandon(self.root)
        current, _ = self.run_publish()
        self.assertEqual(current, legacy)
        self.assertEqual(receipt.read_bytes(), before)
        self.assertFalse(pending.exists())

    def test_topics_verify_before_hub_and_repeat_is_stable(self):
        result, metrics = self.run_publish()
        self.assertTrue(result["gate"]["rehearsal"]["fixture"])
        self.assertEqual(len(result["gate"]["rehearsal"]["remote_refs"]), 6)
        self.assertEqual(publication.load(self.root / ".local/publication/pending.json")["gate"], result["gate"])
        timing = metrics["timing"]
        self.assertEqual(set(timing["repositories"]), set(result["repositories"]))
        for row in timing["repositories"].values():
            self.assertEqual(set(row), {"push_main", "push_pages", "configure", "pages_build", "verify", "total"})
            self.assertTrue(all(seconds >= 0 for seconds in row.values()))
            self.assertGreaterEqual(row["total"], sum(seconds for key, seconds in row.items() if key != "total"))
        self.assertGreaterEqual(timing["prepare"], 0)
        self.assertGreaterEqual(timing["resume"], sum(timing["phases"].values()))
        self.assertNotIn("timing", json.dumps(result))
        self.assertFalse(metrics["reused"])
        self.assertEqual(result["status"], "published")
        hub_push = next(i for i, e in enumerate(self.host.events) if e[:3] == ("push", "Wiki-hub", "gh-pages"))
        self.assertTrue(all(self.host.events.index(("verified", n)) < hub_push for n in ("Wiki-items", "Wiki-loot")))
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.root / "publications").glob("*.json")}
        pushes = [e for e in self.host.events if e[0] == "push"]
        again, metrics = self.run_publish()
        self.assertEqual(self.gate.call_count, 2)
        self.assertTrue(metrics["reused"])
        self.assertEqual(set(metrics["timing"]["repositories"]), set(result["repositories"]))
        self.assertIn("current", metrics["timing"]["phases"])
        self.assertTrue(all(row["push_main"] == row["push_pages"] == row["pages_build"] == 0
                            for row in metrics["timing"]["repositories"].values()))
        self.assertEqual(again, result)
        self.assertEqual(pushes, [e for e in self.host.events if e[0] == "push"])
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
        self.assertTrue(all(names == ("reader.json",) for _, names in self.host.verified[-3:]))

    def abandon_partial_publication(self):
        # 2026-09-29: a publication pushed most topics, stalled, and was abandoned unpromoted.
        first, _ = self.run_publish()
        self.next_release()
        self.host.fail_name = "Wiki-items"
        with self.assertRaisesRegex(ContractError, "Topic publication failed"):
            self.run_publish()
        publication.abandon(self.root)
        return first

    def test_next_release_adopts_an_abandoned_publication(self):
        first = self.abandon_partial_publication()
        self.assertNotEqual(self.host.ref("Wiki-loot", "gh-pages"), first["repositories"]["loot"]["pages"])
        self.assertNotEqual(self.host.ref("Wiki-loot", "main"), first["repositories"]["loot"]["main"])
        # A byte-identical restore made directly on the remote, as done for World on 2026-10-02.
        path = self.host.paths["Wiki-items"]
        moved = self.host.ref("Wiki-items", "gh-pages")
        restore = publication_git.commit(path, git(path, "rev-parse", first["repositories"]["items"]["pages"] + "^{tree}"),
                                         moved, "Restore the served build")
        self.host.refs[("Wiki-items", "gh-pages")] = restore
        self.next_release()
        result, _ = self.run_publish()
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["release_id"], self.manifest["release_id"])
        for topic in ("loot", "items"):
            plan = result["repositories"][topic]
            self.assertEqual(self.host.ref(plan["name"], "gh-pages"), plan["pages"])

    def test_remote_main_is_adopted_only_on_this_workspaces_release_history(self):
        first, _ = self.run_publish()
        path, base = self.host.paths["Wiki-loot"], first["repositories"]["loot"]["main"]
        other = publication_git.unavailable(path)[0]
        abandoned = publication_git.commit(path, other, base, "Abandoned release")
        selected = publication_git.commit(path, git(path, "rev-parse", base + "^{tree}"), abandoned, "Selected release")
        foreign = publication_git.commit(path, other, base, "Someone else's main")
        self.assertTrue(publication_git.released_lineage(path, base, abandoned, selected))
        self.assertFalse(publication_git.released_lineage(path, base, foreign, selected))
        self.assertFalse(publication_git.released_lineage(path, selected, abandoned, selected))

    def test_foreign_commit_on_a_published_branch_is_still_refused(self):
        first, _ = self.run_publish()
        path = self.host.paths["Wiki-loot"]
        foreign_tree = publication_git.unavailable(path)[0]
        foreign = publication_git.commit(path, foreign_tree, first["repositories"]["loot"]["pages"], "Someone else's change")
        self.host.refs[("Wiki-loot", "gh-pages")] = foreign
        self.next_release()
        with self.assertRaisesRegex(ContractError, "Unexpected remote Pages branch: Wiki-loot"):
            self.run_publish()

    def test_topic_failure_preserves_hub_then_fresh_run_adopts_abandoned_lineage(self):
        first, _ = self.run_publish()
        before = (self.root / "publications/latest.json").read_bytes()
        self.next_release()
        self.host.fail_name = "Wiki-items"
        with self.assertRaisesRegex(ContractError, "Topic publication failed"):
            self.run_publish()
        self.assertEqual(self.host.ref("Wiki-hub", "gh-pages"), first["repositories"]["hub"]["pages"])
        self.assertEqual(before, (self.root / "publications/latest.json").read_bytes())
        state = publication.load(self.root / ".local/publication/pending.json")
        self.assertTrue(state["repositories"]["loot"]["verified"])
        target = state["repositories"]["items"]["pages"]
        with self.assertRaisesRegex(ContractError, "abandon-publication"):
            self.run_publish()
        publication.abandon(self.root)
        result, _ = self.run_publish()
        self.assertEqual(git(self.root / "repositories/items", "rev-parse", result["repositories"]["items"]["pages"] + "^"), target)

    def test_failed_hub_restores_previous_tree_without_rewriting_history(self):
        first, _ = self.run_publish()
        self.next_release()
        self.host.fail_name = "Wiki-hub"
        with self.assertRaisesRegex(ContractError, "Injected public hash failure") as raised:
            self.run_publish()
        timing = raised.exception.publication_timing
        self.assertIn("hub", timing["repositories"])
        self.assertIn("hub", timing["rollback"])
        self.assertGreaterEqual(timing["phases"]["rollback"], 0)
        self.assertEqual(set(timing["rollback"]["hub"]), {"push_main", "push_pages", "configure", "pages_build", "verify", "total"})
        self.assertTrue(all(seconds >= 0 for seconds in timing["rollback"]["hub"].values()))
        self.assertEqual(publication.published(self.root), first)
        rollback = self.host.ref("Wiki-hub", "gh-pages")
        path = self.root / "repositories/hub"
        self.assertEqual(git(path, "rev-parse", rollback + "^{tree}"), first["repositories"]["hub"]["tree"])
        self.assertEqual(publication.load(self.root / ".local/publication/pending.json")["phase"], "rolled-back")
        publication.abandon(self.root)
        result, _ = self.run_publish()
        self.assertEqual(result["release_id"], self.manifest["release_id"])
        self.assertEqual(git(path, "rev-parse", result["repositories"]["hub"]["pages"] + "^"), rollback)

    def test_initial_hub_failure_restores_explicit_unavailable_page(self):
        self.host.fail_name = "Wiki-hub"
        with self.assertRaises(ContractError):
            self.run_publish()
        self.assertIsNone(publication.published(self.root))
        head = self.host.ref("Wiki-hub", "gh-pages")
        self.assertIn("No validated public release", git(self.root / "repositories/hub", "show", head + ":index.html"))
        publication.abandon(self.root)
        self.assertEqual(self.run_publish()[0]["status"], "published")

    def test_unavailable_hub_build_observation_requires_abandonment_before_fresh_run(self):
        first, _ = self.run_publish()
        self.next_release()
        original = self.host.wait

        def unavailable(name, commit):
            if name == "Wiki-hub":
                raise github_pages.BuildObservationError("Build observation unavailable")
            return original(name, commit)

        with patch.object(self.host, "wait", side_effect=unavailable), self.assertRaises(github_pages.BuildObservationError):
            self.run_publish()
        pending = publication.load(self.root / ".local/publication/pending.json")
        hub_commit = self.host.ref("Wiki-hub", "gh-pages")
        self.assertEqual(pending["phase"], "hub")
        self.assertIsNone(pending["rollback"])
        self.assertFalse(pending["repositories"]["hub"]["verified"])
        self.assertEqual(publication.published(self.root), first)
        publication.abandon(self.root)
        result, _ = self.run_publish()
        self.assertEqual(git(self.root / "repositories/hub", "rev-parse", result["repositories"]["hub"]["pages"] + "^"), hub_commit)
        self.assertEqual(sum(e[:3] == ("push", "Wiki-hub", "gh-pages") and e[3] == hub_commit
                             for e in self.host.events), 1)

    def test_interrupted_push_requires_abandonment_and_prepares_fresh_history(self):
        self.host.interrupt_name = "Wiki-items"
        with self.assertRaises(KeyboardInterrupt):
            self.run_publish()
        target = self.host.ref("Wiki-items", "gh-pages")
        self.assertIsNone(publication.published(self.root))
        publication.abandon(self.root)
        result, _ = self.run_publish()
        self.assertEqual(git(self.root / "repositories/items", "rev-parse", result["repositories"]["items"]["pages"] + "^"), target)
        self.assertEqual(sum(e[:3] == ("push", "Wiki-items", "gh-pages") for e in self.host.events), 2)

    def test_modified_journal_and_unexpected_remote_are_refused(self):
        self.host.fail_name = "Wiki-items"
        with self.assertRaises(ContractError):
            self.run_publish()
        journal = self.root / ".local/publication/pending.json"
        value = json.loads(journal.read_text())
        original = journal.read_bytes()
        value["payload"]["repositories"]["hub"]["main"] = "0" * 40
        journal.write_bytes(json_bytes(value))
        with self.assertRaisesRegex(ContractError, "abandon-publication"):
            self.run_publish()
        journal.write_bytes(original)
        self.host.refs[("Wiki-items", "gh-pages")] = "f" * 40
        publication.abandon(self.root)
        with self.assertRaisesRegex(ContractError, "Unexpected remote Pages branch"):
            self.run_publish()
        self.assertIsNone(self.host.ref("Wiki-hub", "gh-pages"))

    def test_existing_unowned_remote_is_never_adopted(self):
        self.host.create("Wiki-hub", "Someone else's work")
        with self.assertRaisesRegex(ContractError, "without this workspace"):
            self.run_publish()
        self.assertFalse(any(e[0] == "push" for e in self.host.events))

    def test_pending_prior_publication_is_scrapped_before_new_release_is_prepared(self):
        first = self.manifest
        self.host.fail_name = "Wiki-items"
        with self.assertRaises(ContractError):
            self.run_publish()
        self.next_release()
        with self.assertRaisesRegex(ContractError, "abandon-publication"):
            self.run_publish()
        old_refs = dict(self.host.refs)
        publication.abandon(self.root)
        result, _ = self.run_publish()
        self.assertEqual(result["release_id"], self.manifest["release_id"])
        self.assertFalse((self.root / "publications" / (first["release_id"] + ".json")).exists())
        for identity, plan in result["repositories"].items():
            if (plan["name"], "gh-pages") in old_refs:
                self.assertEqual(git(self.root / plan["path"], "rev-parse", plan["pages"] + "^"),
                                 old_refs[(plan["name"], "gh-pages")])

    def test_unchanged_immutable_packs_do_not_download_again(self):
        first, _ = self.run_publish()
        for receipt in (self.root / '.local/publication/remotes').glob('*.json'):
            receipt.unlink()  # Completed public receipts reconstruct these local records.
        self.next_release()
        second, _ = self.run_publish()
        for topic, plan in second["repositories"].items():
            self.assertFalse(any(name.startswith("data/") for name in plan["checks"]))
            self.assertLess(len(plan["checks"]), len(plan["files"]))
            for name, meta in first["repositories"][topic]["files"].items():
                if name.startswith(("data/", "objects/", "releases/", "runtime/", "fonts/")):
                    self.assertEqual(plan["files"][name], meta)

    def test_public_history_audit_checks_deleted_private_files(self):
        repo = self.root / "repositories/items"
        secret = repo / "authored/private.md"
        secret.parent.mkdir()
        secret.write_text("C:/Users/Secret/private")
        git(repo, "add", "authored/private.md")
        git(repo, "commit", "-m", "Private fixture")
        secret.unlink()
        git(repo, "add", "authored/private.md")
        git(repo, "commit", "-m", "Remove private fixture")
        with self.assertRaisesRegex(ContractError, "Private or binary"):
            publication_git.audit(repo, git(repo, "rev-parse", "HEAD"))

    def test_public_history_allows_hub_issue_template_only_and_scans_bytes(self):
        data = b"name: Correction\ndescription: Wrong fact\nbody:\n  - type: input\n"
        for identity in ("hub", "items"):
            repo = self.root / "repositories" / identity
            baseline = git(repo, "rev-parse", "HEAD")
            path = repo / ".github/ISSUE_TEMPLATE/accuracy.yml"
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            git(repo, "add", ".github/ISSUE_TEMPLATE/accuracy.yml")
            git(repo, "commit", "-qm", "Issue template fixture")
            head = git(repo, "rev-parse", "HEAD")
            if identity == "hub":
                self.assertEqual(publication_git.audit(repo, head, baseline)["commits"], 1)
                invalid = repo / ".github/ISSUE_TEMPLATE/accuracy_bad.yml"
                invalid.write_bytes(data)
                git(repo, "add", ".github/ISSUE_TEMPLATE/accuracy_bad.yml")
                git(repo, "commit", "-qm", "Invalid template path fixture")
                with self.assertRaisesRegex(ContractError, "Unapproved public history path"):
                    publication_git.audit(repo, git(repo, "rev-parse", "HEAD"), head)
                invalid.unlink()
                git(repo, "add", ".github/ISSUE_TEMPLATE/accuracy_bad.yml")
                git(repo, "commit", "-qm", "Remove invalid template fixture")
                head = git(repo, "rev-parse", "HEAD")
                path.write_bytes(data + b"C:/Users/Admin/private\n")
                git(repo, "add", ".github/ISSUE_TEMPLATE/accuracy.yml")
                git(repo, "commit", "-qm", "Private template fixture")
                with self.assertRaisesRegex(ContractError, "Private or binary"):
                    publication_git.audit(repo, git(repo, "rev-parse", "HEAD"), head)
            else:
                with self.assertRaisesRegex(ContractError, "Unapproved public history path"):
                    publication_git.audit(repo, head, baseline)


    def test_curated_json_is_audited_and_cannot_export_private_bytes_or_code_paths(self):
        repo = self.root / 'repositories/items'
        baseline = git(repo, 'rev-parse', 'HEAD')
        path = repo / 'curated/example.json'
        path.parent.mkdir()
        path.write_bytes(json_bytes({'text': ['Configured value: ', {'fact': 'value'}]}))
        git(repo, 'add', 'curated')
        git(repo, 'commit', '-qm', 'Public authored JSON')
        accepted = git(repo, 'rev-parse', 'HEAD')
        self.assertEqual(publication_git.audit(repo, accepted, baseline)['commits'], 1)
        path.write_bytes(json_bytes({'text': ['C:/Users/Admin/private']}))
        git(repo, 'add', 'curated')
        git(repo, 'commit', '-qm', 'Private bytes fixture')
        private = git(repo, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(ContractError, 'Private or binary'):
            publication_git.audit(repo, private, accepted)
        (path.parent / 'raw.cs').write_text('class Raw {}')
        git(repo, 'add', 'curated')
        git(repo, 'commit', '-qm', 'Forbidden source fixture')
        with self.assertRaisesRegex(ContractError, 'Unapproved public history path'):
            publication_git.audit(repo, git(repo, 'rev-parse', 'HEAD'), private)


    def test_public_audit_only_allows_binary_fonts_in_the_font_namespace(self):
        repo = self.root / "repositories/items"
        baseline = git(repo, "rev-parse", "HEAD")
        folder = repo / "site/fonts" / ("a" * 64)
        folder.mkdir(parents=True)
        path = folder / "Fixture.woff2"
        path.write_bytes(b"wOF2\x00\r\nfixture")
        git(repo, "add", "site")
        git(repo, "commit", "-qm", "Font fixture")
        accepted = git(repo, "rev-parse", "HEAD")
        self.assertEqual(publication_git.audit(repo, accepted, baseline)["commits"], 1)
        path.write_bytes(b"not a font\x00")
        git(repo, "add", "site")
        git(repo, "commit", "-qm", "Invalid font fixture")
        invalid = git(repo, "rev-parse", "HEAD")
        with self.assertRaisesRegex(ContractError, "Invalid WOFF2"):
            publication_git.audit(repo, invalid, accepted)
        path.write_bytes(b"wOF2\x00C:/Users/Admin/private")
        git(repo, "add", "site")
        git(repo, "commit", "-qm", "Private font fixture")
        private = git(repo, "rev-parse", "HEAD")
        with self.assertRaisesRegex(ContractError, "Private or binary"):
            publication_git.audit(repo, private, invalid)
        path.write_bytes(b"wOF2\x00\r\nfixture")
        (repo / "site/data.json").write_bytes(b"wOF2\x00\r\nfixture")
        git(repo, "add", "site")
        git(repo, "commit", "-qm", "Binary data fixture")
        with self.assertRaisesRegex(ContractError, "Private or binary"):
            publication_git.audit(repo, git(repo, "rev-parse", "HEAD"), private)


class TimingTests(unittest.TestCase):
    def test_deploy_attributes_each_host_step_and_keeps_failed_wait_time(self):
        class Steps:
            elapsed = 0

            def __init__(self):
                self.refs = {}

            def ref(self, name, branch):
                return self.refs.get(branch)

            def push(self, path, name, commit, branch, expected):
                self.elapsed += 1 if branch == "main" else 2
                self.refs[branch] = commit

            def configure(self, name):
                self.elapsed += 3

            def wait(self, name, commit):
                self.elapsed += 4
                if fail:
                    raise RuntimeError("build fault")

            def verify(self, base, checks):
                self.elapsed += 5

        plan = {"path": ".local", "name": "wiki", "main": "main", "pages": "pages",
                "old_main": None, "old_pages": None, "base": "https://example.invalid/", "checks": {}}
        for fail in (False, True):
            host, timing = Steps(), publication.repository_timing()
            with self.subTest(fail=fail), patch.object(publication, "perf_counter", side_effect=lambda: host.elapsed):
                if fail:
                    with self.assertRaisesRegex(RuntimeError, "build fault"):
                        publication.deploy(Path(__file__).resolve().parents[1], plan, host, timing)
                else:
                    self.assertIsNone(publication.deploy(Path(__file__).resolve().parents[1], plan, host, timing))
            self.assertEqual(timing, {"push_main": 1, "push_pages": 2, "configure": 3,
                                     "pages_build": 4, "verify": 0 if fail else 5, "total": 10 if fail else 15})


class AdapterTests(unittest.TestCase):
    @staticmethod
    def build_records(records):
        records = iter(records)
        def api(method, path, **kwargs):
            if "/actions/runs?" in path:
                return {"workflow_runs": []}
            return next(records)
        return api

    def test_public_http_hashes_and_oversized_response_rejection(self):
        content = b'{"selected":true}\n'

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(content if self.path == "/good.json" else content + b"bad")

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                host = github_pages.GitHubPages("fixture")
                base = f"http://127.0.0.1:{server.server_port}/"
                meta = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
                self.assertEqual(host.verify(base, {"good.json": meta})["bytes"], len(content))
                with patch.object(github_pages.time, "sleep"), self.assertRaisesRegex(ContractError, "content differs"):
                    host.verify(base, {"bad.json": meta})
            finally:
                server.shutdown()
                thread.join()

    def test_live_build_is_polled_without_restarting(self):
        host = github_pages.GitHubPages("fixture")
        states = [{"commit": "abc", "status": state} for state in ("queued", "building", "built")]
        with patch.object(host, "api", side_effect=self.build_records(states)) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.wait("wiki", "abc")["status"], "built")
            self.assertTrue(all(c.args[0] == "GET" for c in calls.call_args_list))

    def test_observed_build_is_pinned_and_live_polls_have_no_absence_limit(self):
        host = github_pages.GitHubPages("fixture")
        path = "repos/fixture/wiki/pages/builds/17"
        states = [{"commit": "abc", "status": state, "url": "https://api.github.com/" + path}
                  for state in ["queued"] * 15 + ["building"] * 15 + ["built"]]
        with patch.object(host, "api", side_effect=self.build_records(states)) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.wait("wiki", "abc")["status"], "built")
            builds = [call for call in calls.call_args_list if "/pages/builds" in call.args[1]]
            self.assertEqual(len(builds), 31)
            self.assertTrue(all(c.args == ("GET", path) for c in builds[1:]))

    def test_failed_deployment_behind_a_live_build_is_rerun_then_bounded(self):
        # GitHub can leave the build record at 'building' after its deployment workflow fails.
        host = github_pages.GitHubPages("fixture")
        path = "repos/fixture/wiki/pages/builds/17"
        building = {"commit": "abc", "status": "building", "url": "https://api.github.com/" + path}
        failed = {"workflow_runs": [{"id": 9, "head_sha": "abc", "name": "pages build and deployment", "status": "completed",
                                     "conclusion": "failure", "html_url": "https://github.com/run/9"}]}
        polls, reruns, finish = 0, 0, True
        def api(method, endpoint, **kwargs):
            nonlocal polls, reruns
            if method == "POST":
                reruns += 1
                return None
            if "/actions/runs?" in endpoint:
                return failed if polls >= 61 else {"workflow_runs": []}
            polls += 1
            return {**building, "status": "built"} if finish and reruns else building
        with patch.object(host, "api", side_effect=api) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.wait("wiki", "abc")["status"], "built")
            self.assertEqual([call.args for call in calls.call_args_list if call.args[0] == "POST"],
                             [("POST", "repos/fixture/wiki/actions/runs/9/rerun-failed-jobs")])
        polls, reruns, finish = 0, 0, False
        with patch.object(host, "api", side_effect=api), patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            with self.assertRaisesRegex(ContractError, "failed after 3 reruns: https://github.com/run/9"):
                host.wait("wiki", "abc")

    def test_other_latest_build_does_not_hide_the_target(self):
        host = github_pages.GitHubPages("fixture")
        target = {"commit": "abc", "status": "building", "url": "https://api.github.com/repos/fixture/wiki/pages/builds/17"}
        states = [{"commit": "other", "status": "built"}, [target], {**target, "status": "built"}]
        with patch.object(host, "api", side_effect=self.build_records(states)) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.wait("wiki", "abc")["status"], "built")
            self.assertTrue(calls.call_args_list[1].args[1].endswith("?per_page=100"))
            builds = [call for call in calls.call_args_list if "/pages/builds" in call.args[1]]
            self.assertTrue(builds[2].args[1].endswith("/17"))

    def test_disappearing_pinned_build_is_rechecked_without_substitution(self):
        host = github_pages.GitHubPages("fixture")
        path = "repos/fixture/wiki/pages/builds/17"
        building = {"commit": "abc", "status": "building", "url": "https://api.github.com/" + path}
        with patch.object(host, "api", side_effect=self.build_records([building] + [None] * 12)) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            with self.assertRaises(github_pages.BuildObservationError):
                host.wait("wiki", "abc")
            builds = [call for call in calls.call_args_list if "/pages/builds" in call.args[1]]
            self.assertEqual(len(builds), 13)
            self.assertTrue(all(c.args == ("GET", path) for c in builds[1:]))

    def test_absent_build_returns_observation_failure_without_dispatch(self):
        host = github_pages.GitHubPages("fixture")
        with patch.object(host, "api", side_effect=self.build_records([None, []] * 12)) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            with self.assertRaisesRegex(github_pages.BuildObservationError, "not observable after 12 checks"):
                host.wait("wiki", "abc")
            self.assertEqual(calls.call_count, 36)
            self.assertTrue(all(c.args[0] == "GET" for c in calls.call_args_list))

    def test_unrelated_live_build_does_not_extend_the_target_absence_budget(self):
        host = github_pages.GitHubPages("fixture")
        older = {"commit": "older", "status": "building"}
        states = [older, [older]] * 12
        with patch.object(host, "api", side_effect=self.build_records(states)), patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            with self.assertRaisesRegex(github_pages.BuildObservationError, "not observable after 12 checks"):
                host.wait("wiki", "abc")

    def test_unknown_status_and_transient_read_failure_do_not_claim_build_failure(self):
        host = github_pages.GitHubPages("fixture")
        for value in ({"commit": "abc", "status": "new-state"}, ContractError("HTTP 503 after retries")):
            with self.subTest(value=value), patch.object(host, "api", side_effect=[value]):
                with self.assertRaises(github_pages.BuildObservationError):
                    host.wait("wiki", "abc")
        with patch.object(host, "api", return_value={"commit": "abc", "status": "built"}), patch.object(host, "ref", side_effect=ContractError("HTTP 503")):
            with self.assertRaises(github_pages.BuildObservationError):
                host.wait("wiki", "abc")

    def test_terminal_build_failure_and_changed_source_are_not_observation_failures(self):
        host = github_pages.GitHubPages("fixture")
        for state, ref in (("errored", "abc"), ("cancelled", "abc"), ("built", "other")):
            with self.subTest(state=state), patch.object(host, "api", return_value={"commit": "abc", "status": state}), patch.object(host, "ref", return_value=ref):
                with self.assertRaises(ContractError) as failure:
                    host.wait("wiki", "abc")
                self.assertNotIsInstance(failure.exception, github_pages.BuildObservationError)

    def test_live_build_that_never_finishes_stops_at_the_deadline(self):
        # A run once waited three days on a build GitHub never finished. Our own
        # build stops at the deadline; unrelated builds cannot extend discovery.
        ours = {"commit": "abc", "status": "building"}
        earlier = {"commit": "older", "status": "building"}
        for name, value in (("ours", ours), ("earlier", earlier)):
            with self.subTest(name):
                host = github_pages.GitHubPages("fixture")
                clock = itertools.count(0, 5)
                host.clock = lambda: next(clock)
                def api(method, path, **kwargs):
                    return [value] if "per_page=100" in path else value
                with patch.object(host, "api", side_effect=api), \
                        patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
                    expected = "after 30 minutes" if name == "ours" else "not observable after 12 checks"
                    with self.assertRaisesRegex(github_pages.BuildObservationError, expected):
                        host.wait("wiki", "abc")

    def test_hung_github_call_is_retried_then_reported(self):
        host = github_pages.GitHubPages("fixture")
        hung = subprocess.TimeoutExpired(["gh"], 1)
        success = subprocess.CompletedProcess([], 0, b'{"id":1}', b'')
        with patch.object(github_pages.bounded, "run", side_effect=[hung, success]) as calls, patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.repository("wiki"), {"id": 1})
            self.assertIsNotNone(calls.call_args_list[0].kwargs.get("timeout"))
        with patch.object(github_pages.bounded, "run", side_effect=hung), patch.object(github_pages.time, "sleep"):
            with self.assertRaisesRegex(ContractError, "timed out"):
                host.repository("wiki")

    def test_timed_out_post_is_not_repeated(self):
        host = github_pages.GitHubPages("fixture")
        hung = subprocess.TimeoutExpired(["gh"], 1)
        with patch.object(github_pages.bounded, "run", side_effect=hung) as calls, patch.object(github_pages.time, "sleep"):
            with self.assertRaisesRegex(ContractError, "timed out"):
                host.api("POST", "repos/fixture/wiki/actions/runs/9/rerun-failed-jobs")
            self.assertEqual(calls.call_count, 1)

    def test_post_that_fails_with_server_error_is_not_repeated(self):
        host = github_pages.GitHubPages("fixture")
        failure = subprocess.CompletedProcess([], 1, b'', b'gh: Gateway timeout (HTTP 504)')
        with patch.object(github_pages.bounded, "run", return_value=failure) as calls, patch.object(github_pages.time, "sleep"):
            with self.assertRaisesRegex(ContractError, "HTTP 504"):
                host.api("POST", "repos/fixture/wiki/actions/runs/9/rerun-failed-jobs")
            self.assertEqual(calls.call_count, 1)

    def test_rerun_request_with_unknown_outcome_leaves_publication_pending(self):
        host = github_pages.GitHubPages("fixture")
        path = "repos/fixture/wiki/pages/builds/17"
        building = {"commit": "abc", "status": "building", "url": "https://api.github.com/" + path}
        failed = {"workflow_runs": [{"id": 9, "head_sha": "abc", "name": "pages build and deployment", "status": "completed",
                                     "conclusion": "failure", "html_url": "https://github.com/run/9"}]}
        def api(method, endpoint, **kwargs):
            if method == "POST":
                raise ContractError("GitHub POST timed out")
            return failed if "/actions/runs?" in endpoint else building
        with patch.object(host, "api", side_effect=api), patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            with self.assertRaisesRegex(github_pages.BuildObservationError, "unknown outcome"):
                host.wait("wiki", "abc")

    def test_hung_push_is_confirmed_by_the_remote_ref(self):
        host = github_pages.GitHubPages("fixture")
        hung = subprocess.TimeoutExpired(["git"], 1)
        ancestry = subprocess.CompletedProcess([], 0, b"", b"")
        with patch.object(github_pages.bounded, "run", side_effect=[ancestry, hung]) as calls, \
                patch.object(host, "ref", side_effect=["old", "new"]):
            host.push(".", "wiki", "new", "main", "old")
            self.assertTrue(all(call.kwargs.get("timeout") for call in calls.call_args_list))
            self.assertIn("--force-with-lease=refs/heads/main:old", calls.call_args.args[0])

    def test_empty_remote_response_and_transient_get_retry(self):
        host = github_pages.GitHubPages("fixture")
        empty = subprocess.CompletedProcess([], 1, b'{"message":"Git Repository is empty."}', b'gh: Git Repository is empty. (HTTP 409)')
        with patch.object(github_pages.bounded, "run", return_value=empty):
            self.assertIsNone(host.ref("wiki", "main"))
        failure = subprocess.CompletedProcess([], 1, b'', b'gh: Service unavailable (HTTP 503)')
        success = subprocess.CompletedProcess([], 0, b'{"id":1}', b'')
        with patch.object(github_pages.bounded, "run", side_effect=[failure, success]) as calls, patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.repository("wiki"), {"id": 1})
            self.assertEqual(calls.call_count, 2)


if __name__ == "__main__":
    unittest.main()
