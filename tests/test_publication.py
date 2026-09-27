"""Exercise publication ordering and recovery with real Git trees and a fake host."""

import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import unittest
from unittest.mock import patch

import test_release
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


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_release.ReleaseTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.project = self.fixture.root, self.fixture.project
        self.project["publication"] = {"enabled": True, "workers": 2}
        self.host = Host(self.project["github_owner"])
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

    def test_topics_verify_before_hub_and_repeat_is_stable(self):
        result, metrics = self.run_publish()
        self.assertFalse(metrics["reused"])
        self.assertEqual(result["status"], "published")
        hub_push = next(i for i, e in enumerate(self.host.events) if e[:3] == ("push", "Wiki-hub", "gh-pages"))
        self.assertTrue(all(self.host.events.index(("verified", n)) < hub_push for n in ("Wiki-items", "Wiki-loot")))
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.root / "publications").glob("*.json")}
        pushes = [e for e in self.host.events if e[0] == "push"]
        again, metrics = self.run_publish()
        self.assertTrue(metrics["reused"])
        self.assertEqual(again, result)
        self.assertEqual(pushes, [e for e in self.host.events if e[0] == "push"])
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
        self.assertTrue(all(names == ("reader.json",) for _, names in self.host.verified[-3:]))

    def test_topic_failure_preserves_hub_and_independent_success_then_resumes(self):
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
        result, _ = self.run_publish()
        self.assertEqual(result["repositories"]["items"]["pages"], target)

    def test_failed_hub_restores_previous_tree_without_rewriting_history(self):
        first, _ = self.run_publish()
        self.next_release()
        self.host.fail_name = "Wiki-hub"
        with self.assertRaisesRegex(ContractError, "Injected public hash failure"):
            self.run_publish()
        self.assertEqual(publication.published(self.root), first)
        rollback = self.host.ref("Wiki-hub", "gh-pages")
        path = self.root / "repositories/hub"
        self.assertEqual(git(path, "rev-parse", rollback + "^{tree}"), first["repositories"]["hub"]["tree"])
        self.assertEqual(publication.load(self.root / ".local/publication/pending.json")["phase"], "rolled-back")
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
        self.assertEqual(self.run_publish()[0]["status"], "published")

    def test_lost_push_response_reuses_exact_prepared_commit(self):
        self.host.interrupt_name = "Wiki-items"
        with self.assertRaises(KeyboardInterrupt):
            self.run_publish()
        target = self.host.ref("Wiki-items", "gh-pages")
        self.assertIsNone(publication.published(self.root))
        result, _ = self.run_publish()
        self.assertEqual(result["repositories"]["items"]["pages"], target)
        self.assertEqual(sum(e[:3] == ("push", "Wiki-items", "gh-pages") for e in self.host.events), 1)

    def test_modified_journal_and_unexpected_remote_are_refused(self):
        self.host.fail_name = "Wiki-items"
        with self.assertRaises(ContractError):
            self.run_publish()
        journal = self.root / ".local/publication/pending.json"
        value = json.loads(journal.read_text())
        original = journal.read_bytes()
        value["payload"]["repositories"]["hub"]["main"] = "0" * 40
        journal.write_bytes(json_bytes(value))
        with self.assertRaisesRegex(ContractError, "modified"):
            self.run_publish()
        journal.write_bytes(original)
        self.host.refs[("Wiki-items", "gh-pages")] = "f" * 40
        with self.assertRaisesRegex(ContractError, "Remote branch changed"):
            self.run_publish()
        self.assertIsNone(self.host.ref("Wiki-hub", "gh-pages"))

    def test_existing_unowned_remote_is_never_adopted(self):
        self.host.create("Wiki-hub", "Someone else's work")
        with self.assertRaisesRegex(ContractError, "without this workspace"):
            self.run_publish()
        self.assertFalse(any(e[0] == "push" for e in self.host.events))

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
                if name.startswith(("data/", "objects/", "releases/", "runtime/")):
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


class AdapterTests(unittest.TestCase):
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
        with patch.object(host, "api", side_effect=states) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.wait("wiki", "abc")["status"], "built")
            self.assertTrue(all(c.args[0] == "GET" for c in calls.call_args_list))

    def test_empty_remote_response_and_transient_get_retry(self):
        host = github_pages.GitHubPages("fixture")
        empty = subprocess.CompletedProcess([], 1, b'{"message":"Git Repository is empty."}', b'gh: Git Repository is empty. (HTTP 409)')
        with patch.object(github_pages.subprocess, "run", return_value=empty):
            self.assertIsNone(host.ref("wiki", "main"))
        failure = subprocess.CompletedProcess([], 1, b'', b'gh: Service unavailable (HTTP 503)')
        success = subprocess.CompletedProcess([], 0, b'{"id":1}', b'')
        with patch.object(github_pages.subprocess, "run", side_effect=[failure, success]) as calls, patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.repository("wiki"), {"id": 1})
            self.assertEqual(calls.call_count, 2)


if __name__ == "__main__":
    unittest.main()
