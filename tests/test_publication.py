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

    def test_unavailable_hub_build_observation_preserves_commit_for_retry(self):
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
        result, _ = self.run_publish()
        self.assertEqual(result["repositories"]["hub"]["pages"], hub_commit)
        self.assertEqual(sum(e[:3] == ("push", "Wiki-hub", "gh-pages") and e[3] == hub_commit
                             for e in self.host.events), 1)

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

    def test_pending_prior_publication_finishes_before_new_pages_parent_is_prepared(self):
        first = self.manifest
        self.host.fail_name = "Wiki-items"
        with self.assertRaises(ContractError):
            self.run_publish()
        self.next_release()
        result, _ = self.run_publish()
        self.assertEqual(result["release_id"], self.manifest["release_id"])
        previous = publication.load(self.root / "publications" / (first["release_id"] + ".json"))
        for identity, plan in result["repositories"].items():
            self.assertEqual(git(self.root / plan["path"], "rev-parse", plan["pages"] + "^"),
                             previous["repositories"][identity]["pages"])

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

    def test_observed_build_is_pinned_and_live_polls_have_no_absence_limit(self):
        host = github_pages.GitHubPages("fixture")
        path = "repos/fixture/wiki/pages/builds/17"
        states = [{"commit": "abc", "status": state, "url": "https://api.github.com/" + path}
                  for state in ["queued"] * 15 + ["building"] * 15 + ["built"]]
        with patch.object(host, "api", side_effect=states) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.wait("wiki", "abc")["status"], "built")
            self.assertEqual(calls.call_count, 31)
            self.assertTrue(all(c.args == ("GET", path) for c in calls.call_args_list[1:]))

    def test_failed_deployment_behind_a_live_build_is_rerun_then_bounded(self):
        # GitHub can leave the build record at 'building' after its deployment workflow fails.
        host = github_pages.GitHubPages("fixture")
        path = "repos/fixture/wiki/pages/builds/17"
        building = {"commit": "abc", "status": "building", "url": "https://api.github.com/" + path}
        failed = {"workflow_runs": [{"id": 9, "name": "pages build and deployment", "status": "completed",
                                     "conclusion": "failure", "html_url": "https://github.com/run/9"}]}
        states = [building] * 61 + [failed, None, {**building, "status": "built"}]
        with patch.object(host, "api", side_effect=states) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.wait("wiki", "abc")["status"], "built")
            self.assertEqual(calls.call_args_list[62].args, ("POST", "repos/fixture/wiki/actions/runs/9/rerun-failed-jobs"))
        states = [building] * 61 + [failed, None] + ([building] * 60 + [failed, None]) * 2 + [building] * 60 + [failed]
        with patch.object(host, "api", side_effect=states), patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            with self.assertRaisesRegex(ContractError, "failed after 3 reruns: https://github.com/run/9"):
                host.wait("wiki", "abc")

    def test_other_latest_build_does_not_hide_the_target(self):
        host = github_pages.GitHubPages("fixture")
        target = {"commit": "abc", "status": "building", "url": "https://api.github.com/repos/fixture/wiki/pages/builds/17"}
        states = [{"commit": "other", "status": "built"}, [target], {**target, "status": "built"}]
        with patch.object(host, "api", side_effect=states) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.wait("wiki", "abc")["status"], "built")
            self.assertTrue(calls.call_args_list[1].args[1].endswith("?per_page=100"))
            self.assertTrue(calls.call_args_list[2].args[1].endswith("/17"))

    def test_disappearing_pinned_build_is_rechecked_without_substitution(self):
        host = github_pages.GitHubPages("fixture")
        path = "repos/fixture/wiki/pages/builds/17"
        queued = {"commit": "abc", "status": "queued", "url": "https://api.github.com/" + path}
        with patch.object(host, "api", side_effect=[queued] + [None] * 12) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            with self.assertRaises(github_pages.BuildObservationError):
                host.wait("wiki", "abc")
            self.assertEqual(calls.call_count, 13)
            self.assertTrue(all(c.args == ("GET", path) for c in calls.call_args_list[1:]))

    def test_absent_build_returns_observation_failure_without_dispatch(self):
        host = github_pages.GitHubPages("fixture")
        with patch.object(host, "api", side_effect=[None, []] * 12) as calls, patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            with self.assertRaisesRegex(github_pages.BuildObservationError, "not observable after 12 checks"):
                host.wait("wiki", "abc")
            self.assertEqual(calls.call_count, 24)
            self.assertTrue(all(c.args[0] == "GET" for c in calls.call_args_list))

    def test_earlier_live_build_does_not_consume_absence_budget(self):
        host = github_pages.GitHubPages("fixture")
        older = {"commit": "older", "status": "building"}
        states = [older, [older]] * 15 + [{"commit": "abc", "status": "built"}]
        with patch.object(host, "api", side_effect=states), patch.object(host, "ref", return_value="abc"), patch.object(github_pages.time, "sleep"):
            self.assertEqual(host.wait("wiki", "abc")["status"], "built")

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
