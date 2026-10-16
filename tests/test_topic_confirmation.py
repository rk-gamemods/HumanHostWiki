"""Read-only topic confirmation failures never create ownership or promote a hub."""

import copy
import unittest
from unittest.mock import patch

from tests._support import fixture_dir
from wikibuild import publication, publication_evidence, publication_git, topic_confirmation
from wikibuild.storage import ContractError, digest, git, json_bytes


class TopicConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "topic-confirmation")
        self.repo = {"id": "loot", "path": "repositories/loot", "github_name": "Wiki-loot", "role": "topic"}
        self.project = {"github_owner": "fixture", "repositories": [self.repo]}
        self.path = self.root / self.repo["path"]
        self.path.mkdir(parents=True)
        for path in (self.root, self.path):
            git(path, "init", "-q")
            git(path, "config", "user.name", "Fixture")
            git(path, "config", "user.email", "fixture@example.invalid")
        (self.path / "site").mkdir()
        (self.path / "site/index.html").write_text("Selected site")
        git(self.path, "add", "site")
        git(self.path, "commit", "-qm", "Selected main")
        main = git(self.path, "rev-parse", "HEAD")
        tree = git(self.path, "rev-parse", "HEAD:site")
        self.pages = publication_git.commit(self.path, tree, None, "Selected Pages")
        publication.pin(self.path, self.pages)
        self.identity = "b" * 64
        self.selected = {"release_id": self.identity, "repositories": {"loot": {
            "path": self.repo["path"], "github_name": self.repo["github_name"], "commit": main}}}
        (self.root / "project.json").write_bytes(json_bytes(self.project))
        (self.root / "releases").mkdir()
        (self.root / f"releases/{self.identity}.json").write_bytes(json_bytes(self.selected))
        git(self.root, "add", "project.json", "releases")
        git(self.root, "commit", "-qm", "Reviewed selected release")
        publication.save(self.root / ".local/publication/remotes/loot.json", {
            "full_name": "fixture/Wiki-loot", "repository_id": 1})
        self.files = {"index.html": {"sha256": digest(b"Selected site"), "bytes": len(b"Selected site")}}
        self.refs = {"main": main, "gh-pages": self.pages}
        self.remote = {"id": 1, "full_name": "fixture/Wiki-loot", "private": False,
                       "archived": False, "fork": False, "permissions": {"admin": True}}
        self.build = {"commit": self.pages, "status": "built",
                      "url": "https://api.github.com/repos/fixture/Wiki-loot/pages/builds/1"}
        test = self

        class ReadOnlyHost:
            def repository(self, name):
                return test.remote

            def ref(self, name, branch):
                return test.refs[branch]

            def api(self, method, path, **kwargs):
                test.assertEqual(method, "GET")
                if path.endswith("/pages"):
                    return {"source": {"branch": "gh-pages", "path": "/"}, "build_type": "legacy",
                            "cname": None, "html_url": "https://fixture.github.io/Wiki-loot/"}
                test.assertTrue(path.endswith("/pages/builds/latest"))
                return test.build

            def verify(self, base, files):
                test.assertEqual(files, test.files)
                test.verifications += 1

        self.host, self.verifications = ReadOnlyHost(), 0

    def confirm(self):
        with patch.object(publication, "site_files", return_value=self.files):
            return topic_confirmation.run(self.root, self.project, self.selected, host=self.host)

    def test_repeat_is_stable_and_only_reviewed_confirmation_qualifies(self):
        first = self.confirm()
        path = self.root / first["receipt"]
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertEqual(self.confirm(), first)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(publication_evidence.confirmations(self.root), ({}, []))
        git(self.root, "add", "topic-confirmations")
        git(self.root, "commit", "-qm", "Reviewed independent topic proof")
        commits, errors = publication_evidence.confirmations(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(commits[("loot", self.repo["path"], "Wiki-loot")], {self.pages})
        self.assertEqual(self.confirm(), first)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertFalse((self.root / "publications/latest.json").exists())

    def test_cheap_failures_precede_public_downloads_and_write_no_proof(self):
        for case in ("main", "identity", "build", "tree", "pin", "parent"):
            with self.subTest(case=case):
                original_refs, original_remote, original_build = copy.deepcopy((self.refs, self.remote, self.build))
                if case == "main":
                    self.refs["main"] = "c" * 40
                elif case == "identity":
                    self.remote["id"] = 2
                elif case == "build":
                    self.build["status"] = "errored"
                elif case == "pin":
                    git(self.path, "update-ref", "--no-deref", "-d", "refs/wiki-publications/" + self.pages)
                else:
                    tree = git(self.path, "rev-parse", "HEAD^{tree}" if case == "tree" else "HEAD:site")
                    other = publication_git.commit(self.path, tree, self.pages if case == "parent" else None, case)
                    publication.pin(self.path, other)
                    self.refs["gh-pages"] = other
                with self.assertRaises(ContractError):
                    self.confirm()
                self.assertEqual(self.verifications, 0)
                self.assertFalse((self.root / "topic-confirmations").exists())
                self.refs, self.remote, self.build = original_refs, original_remote, original_build
                publication.pin(self.path, self.pages)

    def test_hash_failure_and_ref_drift_write_no_proof(self):
        with patch.object(self.host, "verify", side_effect=ContractError("public mismatch")):
            with self.assertRaisesRegex(ContractError, "public mismatch"):
                self.confirm()
        self.assertFalse((self.root / "topic-confirmations").exists())
        with patch.object(self.host, "verify", side_effect=lambda *args: self.refs.update(main="d" * 40)):
            with self.assertRaisesRegex(ContractError, "changed during"):
                self.confirm()
        self.assertFalse((self.root / "topic-confirmations").exists())

    def test_modified_proof_wrong_owner_and_hub_cannot_qualify(self):
        first = self.confirm()
        path = self.root / first["receipt"]
        git(self.root, "add", "topic-confirmations")
        git(self.root, "commit", "-qm", "Reviewed independent topic proof")
        original = path.read_bytes()
        path.write_bytes(original.replace(b"built", b"errored"))
        self.assertEqual(publication_evidence.confirmations(self.root), ({}, []))
        path.write_bytes(original)
        for case in ("owner", "hub", "release", "destination"):
            with self.subTest(case=case):
                payload = publication.load(path)
                if case == "owner":
                    payload["owner"] = "other"
                elif case == "hub":
                    payload["repositories"]["loot"]["role"] = "hub"
                elif case == "release":
                    payload["release_file_sha256"] = "f" * 64
                else:
                    payload["repositories"]["loot"]["name"] = "Other"
                changed = self.root / "topic-confirmations" / (digest(json_bytes(payload)) + ".json")
                publication.save(changed, payload)
                git(self.root, "add", "topic-confirmations")
                git(self.root, "commit", "-qm", "Invalid proof fixture")
                commits, errors = publication_evidence.confirmations(self.root)
                self.assertEqual(len(errors), 1)
                self.assertEqual(commits[("loot", self.repo["path"], "Wiki-loot")], {self.pages})
                git(self.root, "rm", "--", changed.relative_to(self.root).as_posix())
                git(self.root, "commit", "-qm", "Remove invalid fixture")

    def test_hub_and_hub_partitions_are_excluded_without_remote_reads(self):
        project = {**self.project, "repositories": [{**self.repo, "id": "hub", "role": "hub"}]}
        (self.root / "project.json").write_bytes(json_bytes(project))
        git(self.root, "add", "project.json")
        git(self.root, "commit", "-qm", "Hub fixture")
        with patch.object(self.host, "ref", side_effect=AssertionError("Hub must never be adopted")):
            result = topic_confirmation.run(self.root, project, self.selected, host=self.host)
        self.assertEqual(result["status"], "no-advanced-topics")
        self.assertFalse((self.root / "topic-confirmations").exists())


if __name__ == "__main__":
    unittest.main()
