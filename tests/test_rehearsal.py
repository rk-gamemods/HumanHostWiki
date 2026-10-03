"""Rehearsal receipts are saved after success and restoration, without network."""

import unittest
from unittest.mock import patch

import test_publish_gate
from tools import rehearse_publication
from wikibuild import github_pages, publication, publish_gate
from wikibuild.storage import ContractError


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        fixture = test_publish_gate.PublishGateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.client.stop()  # RehearsalHost inherits the real class; mock its API below.
        self.root, self.project = fixture.root, fixture.project
        self.manifest = {**fixture.manifest, "repositories": {"hub": {"path": "repositories/hub"}}}
        self.path = publish_gate.receipt_path(self.root, self.manifest["release_id"])
        self.path.unlink()
        self.api = patch.object(github_pages.GitHubPages, "api", return_value={"object": {"sha": "c" * 40}})
        self.api.start()
        self.addCleanup(self.api.stop)

    def test_success_restores_publication_state_then_writes_bound_receipt(self):
        pending = self.root / ".local/publication/pending.json"
        publication.save(pending, {"phase": "complete"})
        before = pending.read_bytes()

        def simulate(root, project, manifest, host, progress, timing):
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
