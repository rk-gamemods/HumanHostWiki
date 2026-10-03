"""Rehearsal receipts are saved after success and restoration, without network."""

from contextlib import contextmanager
from pathlib import Path
import shutil
import unittest
from uuid import uuid4
from unittest.mock import patch

import test_publish_gate
from tools import rehearse_publication
from wikibuild import github_pages, publication, publish_gate
from wikibuild.storage import ContractError


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        fixture = test_publish_gate.PublishGateTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.client.stop()  # RehearsalHost inherits the real class; mock its API below.
        self.fixture = fixture
        self.root, self.project = fixture.root, fixture.project
        self.manifest = {**fixture.manifest, "repositories": {"hub": {"path": "repositories/hub"}}}
        self.path = publish_gate.receipt_path(self.root, self.manifest["release_id"])
        self.path.unlink()
        self.api = patch.object(github_pages.GitHubPages, "api", return_value={"object": {"sha": "c" * 40}})
        self.api.start()
        self.addCleanup(self.api.stop)
        temporary = patch.object(rehearse_publication.tempfile, "TemporaryDirectory", self.temporary_directory)
        temporary.start()
        self.addCleanup(temporary.stop)

    @staticmethod
    @contextmanager
    def temporary_directory(dir):
        # Ordinary owned directories avoid mkdtemp's sandbox ACLs; cleanup is mandatory.
        path = Path(dir) / uuid4().hex[:4]
        path.mkdir()
        try:
            yield str(path)
        finally:
            shutil.rmtree(path)

    def test_success_restores_publication_state_then_writes_bound_receipt(self):
        pending = self.root / ".local/publication/pending.json"
        publication.save(pending, {"phase": "complete"})
        before = pending.read_bytes()

        def simulate(root, project, manifest, host, progress, timing, gate):
            self.assertEqual(len(gate["rehearsal"]["remote_refs"]), 2)
            publication.save(pending, {"phase": "simulated"})
            publication.save(root / "publications/latest.json", {"release_id": manifest["release_id"]})
            host.simulated[("Wiki-hub", "main")] = "d" * 40
            self.assertEqual(host.ref("Wiki-hub", "main"), "d" * 40)
            return {"status": "published"}, {}

        with patch.object(publication, "_run", side_effect=simulate), \
                patch.object(publication, "run", side_effect=AssertionError("Production gate in rehearsal")):
            path = rehearse_publication.rehearse(self.root, self.project, self.manifest, lambda message: None)
        self.assertEqual(path, self.path)
        self.assertEqual(pending.read_bytes(), before)
        self.assertFalse((self.root / "publications").exists())
        receipt = publication.load(path)
        self.assertEqual(receipt["release_id"], self.manifest["release_id"])
        self.assertEqual(receipt["workspace_commit"], publish_gate.git(self.root, "rev-parse", "HEAD"))
        self.assertEqual(receipt["contract"], publication.contract())
        self.assertIn("tools/rehearse_publication.py", receipt["contract"])
        self.assertIn("publish_gate.py", receipt["contract"])
        self.assertEqual(len(receipt["remote_refs"]), 2)
        self.assertTrue(all(ref["commit"] == "c" * 40 for ref in receipt["remote_refs"]))
        self.assertTrue(receipt["created_utc"].endswith("+00:00"))

    def test_failed_rehearsal_restores_journal_and_writes_no_receipt(self):
        pending = self.root / ".local/publication/pending.json"
        publication.save(pending, {"phase": "complete"})
        before = pending.read_bytes()

        def fail(*args):
            publication.save(pending, {"phase": "simulated"})
            raise ContractError("Injected rehearsal failure")

        with patch.object(publication, "_run", side_effect=fail):
            with self.assertRaisesRegex(ContractError, "Injected rehearsal failure"):
                rehearse_publication.rehearse(self.root, self.project, self.manifest, lambda message: None)
        self.assertEqual(pending.read_bytes(), before)
        self.assertFalse(self.path.exists())

    def test_disabled_rehearsal_does_not_write_receipt(self):
        with patch.object(publication, "_run", return_value=({"status": "disabled"}, {})):
            with self.assertRaisesRegex(ContractError, "did not complete"):
                rehearse_publication.rehearse(self.root, self.project, self.manifest, lambda message: None)
        self.assertFalse(self.path.exists())

    def test_dirty_rehearsal_refuses_before_lock_backup_contract_or_host(self):
        for file in ("code.txt", "untracked.txt"):
            with self.subTest(file=file):
                path = self.root / file
                path.write_text("dirty")
                with patch.object(rehearse_publication, "writer_lock") as lock, \
                        patch.object(publication, "contract") as contract, \
                        patch.object(rehearse_publication, "RehearsalHost") as host:
                    with self.assertRaisesRegex(ContractError, "workspace must be clean"):
                        rehearse_publication.rehearse(self.root, self.project, {}, lambda message: None)
                    lock.assert_not_called()
                    contract.assert_not_called()
                    host.assert_not_called()
                self.assertFalse((self.root / ".local/rehearsal-backups").exists())
                self.assertFalse(self.path.exists())
                if file == "code.txt":
                    path.write_text("reviewed code")
                else:
                    path.unlink()

    def test_incomplete_publication_cannot_be_rehearsed_or_salvaged(self):
        pending = self.root / ".local/publication/pending.json"
        publication.save(pending, {"phase": "topics"})
        before = pending.read_bytes()
        with patch.object(rehearse_publication, "RehearsalHost") as host:
            with self.assertRaisesRegex(ContractError, "abandon-publication"):
                rehearse_publication.rehearse(self.root, self.project, self.manifest, lambda message: None)
            host.assert_not_called()
        self.assertEqual(pending.read_bytes(), before)
        self.assertFalse(self.path.exists())

    def test_runner_contract_drift_prevents_receipt(self):
        contract = publication.contract()
        changed = {**contract, "tools/rehearse_publication.py": "f" * 64}
        with patch.object(publication, "contract", side_effect=[contract, changed]), \
                patch.object(publication, "_run", return_value=({"status": "published"}, {})):
            with self.assertRaisesRegex(ContractError, "contract changed"):
                rehearse_publication.rehearse(self.root, self.project, self.manifest, lambda message: None)
        self.assertFalse(self.path.exists())

    def test_repeated_real_ref_reads_detect_drift_and_simulated_refs_do_not_replace_observations(self):
        host = rehearse_publication.RehearsalHost("rk-gamemods", {}, lambda message: None)
        with patch.object(github_pages.GitHubPages, "api", side_effect=[
                {"object": {"sha": "c" * 40}}, {"object": {"sha": "d" * 40}}]):
            self.assertEqual(host.ref("Wiki-hub", "main"), "c" * 40)
            with self.assertRaisesRegex(ContractError, "changed during rehearsal"):
                host.ref("Wiki-hub", "main")
        self.assertEqual(host.observed[("Wiki-hub", "main")], "c" * 40)


if __name__ == "__main__":
    unittest.main()
