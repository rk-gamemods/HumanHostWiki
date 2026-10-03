"""Real Git receipts exercise migration, obsolete-page removal and recovery."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests._support import fixture_dir

from wikibuild import git_transaction, ownership, publication, publication_git, release_output
from wikibuild.storage import ContractError, digest, git


class OwnershipTransactionTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "owner")
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Wiki fixture")
        git(self.repo, "config", "user.email", "wiki@example.invalid")
        (self.repo / ".gitignore").write_text(".local/\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-m", "Seed fixture")

    def prepare(self, label, count=60, limit=2048):
        stage = self.repo / ".local" / label
        stage.mkdir(parents=True)
        writer = release_output.Writer(self.repo, stage, {"id": "items", "role": "partition"}, label * 64)
        for number in range(count):
            data = json.dumps({"item": number}).encode()
            writer.add("site/data/" + digest(data) + ".json", data, allocated=True)
        writer.add("site/current.json", json.dumps({"value": label}).encode())
        changes, _ = writer.finish(limit)
        self.assertTrue(all(meta["bytes"] <= limit for meta in changes.values()))
        plan = git_transaction.prepare(self.repo, stage, changes, "Fixture " + label)
        # Persist and reload the same shape the release journal owns.
        (stage / "plan.json").write_text(json.dumps(plan))
        return stage, json.loads((stage / "plan.json").read_text())

    def install(self, label, count=60, limit=2048):
        stage, plan = self.prepare(label, count, limit)
        git_transaction.promote(self.repo, stage, plan)
        return plan

    def test_flat_migration_deletion_crash_resume_and_pinned_old_commit(self):
        self.install("a", count=2, limit=65536)
        self.assertEqual(json.loads((self.repo / ownership.OWNER_FILE).read_bytes())["schema_version"], 1)
        prior = self.install("b")
        old, old_parts = ownership.committed(self.repo, prior["commit"])
        self.assertTrue(old_parts)
        self.assertEqual(release_output.owned(self.repo), old["files"])
        stage, plan = self.prepare("c")
        removed = {name for name, value in plan["files"].items() if value["new"] is None}
        self.assertTrue(removed)
        original = Path.unlink
        interrupted = False

        def crash_after_removal(path, *args, **kwargs):
            nonlocal interrupted
            original(path, *args, **kwargs)
            if path.parent.name == ownership.PAGE_DIRECTORY and not interrupted:
                interrupted = True
                raise OSError("interrupted after ownership page removal")

        with patch.object(Path, "unlink", crash_after_removal):
            with self.assertRaisesRegex(OSError, "after ownership"):
                git_transaction.promote(self.repo, stage, plan)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), prior["commit"])
        git_transaction.promote(self.repo, stage, plan)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), plan["commit"])
        current, parts = ownership.checkout(self.repo)
        self.assertEqual(release_output.owned(self.repo), current["files"])
        self.assertTrue(all(not (self.repo / name).exists() for name in removed))
        self.assertEqual({p.relative_to(self.repo).as_posix() for p in (self.repo / ownership.PAGE_DIRECTORY).glob("*.json")}, set(parts))
        with patch.object(ownership.subprocess, "Popen", wraps=ownership.subprocess.Popen) as process:
            self.assertEqual(ownership.committed(self.repo, prior["commit"]), (old, old_parts))
            self.assertEqual(process.call_count, 1)
        published_files = publication.site_files(self.root, {"path": "repo", "commit": prior["commit"]})
        self.assertEqual(published_files["current.json"], old["files"]["site/current.json"])
        self.assertNotEqual(published_files["current.json"], current["files"]["site/current.json"])
        self.assertTrue(all(not name.startswith(ownership.PAGE_DIRECTORY) for name in published_files))
        publication_git.audit(self.repo, plan["commit"])
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (self.repo / ownership.PAGE_DIRECTORY).glob("*")}
        git_transaction.promote(self.repo, stage, plan)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
        frozen = self.repo / ".local/frozen"
        frozen.mkdir()
        writer = release_output.Writer(self.repo, frozen, {"id": "items", "role": "partition"}, "d" * 64)
        self.assertEqual(writer.finish(2048)[0], {})

    def test_unknown_and_modified_pages_are_preserved(self):
        self.install("a")
        unknown = self.repo / ownership.PAGE_DIRECTORY / ("0" * 64 + ".json")
        unknown.write_bytes(b"unknown")
        with self.assertRaisesRegex(ContractError, "Unknown file"):
            release_output.owned(self.repo)
        self.assertEqual(unknown.read_bytes(), b"unknown")
        unknown.unlink()  # This test created the exact disposable file above.
        stage, plan = self.prepare("b")
        doomed = next(name for name, meta in plan["files"].items() if meta["new"] is None)
        path = self.repo / doomed
        modified = path.read_bytes() + b" "
        path.write_bytes(modified)
        with self.assertRaisesRegex(ContractError, "outside this release"):
            git_transaction.promote(self.repo, stage, plan)
        self.assertEqual(path.read_bytes(), modified)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), plan["base"])
        with self.assertRaisesRegex(ContractError, "Modified ownership page"):
            release_output.owned(self.repo)


if __name__ == "__main__":
    unittest.main()
