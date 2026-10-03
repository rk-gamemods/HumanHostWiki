"""Production preflight against synthetic Git repositories, with no network."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import wiki
from wikibuild import publication, publish_gate
from wikibuild.storage import ContractError


class PublishGateTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / ".local/test-publish-gate"
        parent.mkdir(parents=True, exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(dir=parent))
        self.addCleanup(self.cleanup)
        self.origin, self.root = self.folder / "origin", self.folder / "workspace"
        self.origin.mkdir()
        publish_gate.git(self.origin, "init", "--initial-branch=main")
        publish_gate.git(self.origin, "config", "user.name", "Gate fixture")
        publish_gate.git(self.origin, "config", "user.email", "gate@example.invalid")
        (self.origin / ".gitignore").write_text(".local/\npublications/\n")
        (self.origin / "code.txt").write_text("reviewed code")
        publish_gate.git(self.origin, "add", ".")
        publish_gate.git(self.origin, "commit", "-qm", "Reviewed main")
        publish_gate.git(self.folder, "clone", "--quiet", "--no-hardlinks", str(self.origin), str(self.root))
        publish_gate.git(self.root, "config", "user.name", "Gate fixture")
        publish_gate.git(self.root, "config", "user.email", "gate@example.invalid")
        self.commit = publish_gate.git(self.root, "rev-parse", "HEAD")
        self.project = {"github_owner": "rk-gamemods", "publication": {"enabled": True},
                        "repositories": [{"id": "hub", "github_name": "Wiki-hub", "path": "repositories/hub"}]}
        self.manifest = {"release_id": "a" * 64}
        self.refs = [{"repository": "Wiki-hub", "branch": branch, "commit": "c" * 40}
                     for branch in ("main", "gh-pages")]
        self.host = Mock()
        self.host.api.return_value = {"workflow_runs": [{"id": 1, "name": "CI", "head_sha": self.commit,
                                                        "status": "completed", "conclusion": "success"}]}
        self.host.ref.return_value = "c" * 40
        self.client = patch.object(publish_gate.github_pages, "GitHubPages", return_value=self.host)
        self.client.start()
        self.addCleanup(self.client.stop)
        publish_gate.write_receipt(self.root, self.manifest["release_id"], self.commit, self.refs)

    def cleanup(self):
        try:
            shutil.rmtree(self.folder)
        except PermissionError:
            print(f"Retained protected gate fixture: {self.folder}")

    def check(self):
        return publish_gate.check(self.root, self.project, self.manifest)

    def edit_receipt(self, **values):
        path = publish_gate.receipt_path(self.root, self.manifest["release_id"])
        receipt = publication.load(path)
        publication.save(path, {**receipt, **values})

    def test_pass_records_exact_commit_ci_and_receipt_and_ignores_local_files(self):
        result = self.check()
        self.assertEqual(result["workspace_commit"], self.commit)
        self.assertEqual(result["ci_run_id"], 1)
        self.assertEqual(result["rehearsal"]["remote_refs"], self.refs)
        self.host.api.assert_called_once_with("GET", f"repos/rk-gamemods/HumanHostWiki/actions/runs?head_sha={self.commit}")
        self.assertEqual(self.host.ref.call_count, 2)

    def test_dirty_and_untracked_fail_before_fetch_or_host_construction(self):
        for tracked in (True, False):
            with self.subTest(tracked=tracked):
                path = self.root / ("code.txt" if tracked else "untracked.txt")
                path.write_text("pending work")
                with patch.object(publish_gate.bounded, "run", wraps=publish_gate.bounded.run) as command:
                    with self.assertRaisesRegex(ContractError, "workspace must be clean"):
                        self.check()
                    self.assertEqual(command.call_count, 1)
                    self.assertEqual(command.call_args.kwargs["timeout"], publish_gate.GIT_TIMEOUT)
                self.host.api.assert_not_called()
                if tracked:
                    path.write_text("reviewed code")
                else:
                    path.unlink()

    def test_head_ahead_and_behind_are_refused_after_fetch(self):
        for path in (self.root, self.origin):
            with self.subTest(repository=path.name):
                publish_gate.git(path, "commit", "--allow-empty", "-qm", "Different main")
                with self.assertRaisesRegex(ContractError, "HEAD must equal fetched origin/main"):
                    self.check()
                self.host.api.assert_not_called()
                # Restore only the synthetic HEAD, so the next case starts aligned.
                publish_gate.git(path, "update-ref", "refs/heads/main", self.commit)

    def test_ci_missing_in_progress_failed_and_wrong_sha_fail_closed(self):
        for runs, message in [([], "CI is missing"),
                              ([{"status": "in_progress", "conclusion": None}], "CI has not completed"),
                              ([{"status": "completed", "conclusion": "failure"}], "CI did not conclude success"),
                              ([{"head_sha": "f" * 40}], "CI is missing")]:
            with self.subTest(message=message, runs=runs):
                self.host.api.return_value = {"workflow_runs": [
                    {"id": 1, "name": "CI", "head_sha": self.commit, **row} for row in runs]}
                with self.assertRaisesRegex(ContractError, message):
                    self.check()
                self.host.ref.assert_not_called()

    def test_latest_ci_attempt_must_succeed(self):
        good = self.host.api.return_value["workflow_runs"][0]
        self.host.api.return_value["workflow_runs"].append({**good, "run_attempt": 2, "conclusion": "failure"})
        with self.assertRaisesRegex(ContractError, "CI did not conclude success"):
            self.check()

    def test_malformed_ci_response_is_refused_before_remote_refs(self):
        for response in (None, {}, {"workflow_runs": None}, {"workflow_runs": [None]}):
            with self.subTest(response=response):
                self.host.api.return_value = response
                with self.assertRaisesRegex(ContractError, "invalid CI response"):
                    self.check()
                self.host.ref.assert_not_called()

    def test_no_receipt_is_refused(self):
        publish_gate.receipt_path(self.root, self.manifest["release_id"]).unlink()
        with self.assertRaisesRegex(ContractError, "rehearsal receipt is missing"):
            self.check()

    def test_malformed_receipt_is_refused_with_a_gate_message(self):
        publish_gate.receipt_path(self.root, self.manifest["release_id"]).write_text("[]")
        with self.assertRaisesRegex(ContractError, "Publish gate: invalid rehearsal receipt"):
            self.check()
        self.host.ref.assert_not_called()

    def test_wrong_release_commit_contract_and_stale_receipts_are_refused(self):
        cases = [({"release_id": "b" * 64}, "another release"),
                 ({"workspace_commit": "b" * 40}, "workspace commit differs"),
                 ({"contract": {}}, "publication contract differs"),
                 ({"created_utc": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()}, "stale"),
                 ({"created_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}, "future"),
                 ({"created_utc": "2026-10-02T00:00:00"}, "must be UTC"),
                 ({"remote_refs": self.refs[:1]}, "every destination branch")]
        for values, message in cases:
            with self.subTest(values=values):
                publish_gate.write_receipt(self.root, self.manifest["release_id"], self.commit, self.refs)
                self.edit_receipt(**values)
                with self.assertRaisesRegex(ContractError, message):
                    self.check()
                self.host.ref.assert_not_called()

    def test_ref_drift_and_missing_branch_are_refused(self):
        for sha in ("d" * 40, None):
            with self.subTest(sha=sha):
                self.host.ref.return_value = sha
                with self.assertRaisesRegex(ContractError, "remote ref changed: Wiki-hub/main"):
                    self.check()

    def test_pending_gate_failure_preserves_journal_and_makes_no_host_call(self):
        path = self.root / ".local/publication/pending.json"
        publication.save(path, {"phase": "topics", "owner": "rk-gamemods"})
        before = path.read_bytes()
        (self.root / "code.txt").write_text("dirty")
        with patch.object(publication, "resume", side_effect=AssertionError("Unexpected resume")), \
                patch.object(publication, "prepare", side_effect=AssertionError("Unexpected provisioning")):
            with self.assertRaisesRegex(ContractError, "workspace must be clean"):
                publication.run(self.root, self.project, self.manifest, host=self.host)
        self.assertEqual(path.read_bytes(), before)
        self.host.assert_not_called()
        self.assertEqual(self.host.method_calls, [])

    def test_pending_destinations_must_also_be_rehearsed(self):
        publication.save(self.root / ".local/publication/pending.json",
                         {"phase": "topics", "repositories": {"older": {"name": "Wiki-older"}}})
        with self.assertRaisesRegex(ContractError, "every destination branch"):
            self.check()

    def test_git_fetch_failure_and_timeout_fail_before_ci(self):
        original = publish_gate.bounded.run
        for timeout in (False, True):
            def fail_fetch(command, **options):
                if "fetch" in command:
                    if timeout:
                        raise subprocess.TimeoutExpired(command, options["timeout"])
                    return subprocess.CompletedProcess(command, 1, b"", b"unavailable")
                return original(command, **options)
            with self.subTest(timeout=timeout), patch.object(publish_gate.bounded, "run", side_effect=fail_fetch):
                with self.assertRaisesRegex(ContractError, "git fetch (failed|timed out)"):
                    self.check()
                self.host.api.assert_not_called()

    def test_publish_entrypoint_uses_only_the_explicit_release(self):
        with patch.object(wiki.manifest, "load", return_value=self.project), \
                patch.object(wiki.release, "read", return_value=self.manifest) as read, \
                patch.object(publication, "run", return_value=({"status": "published"}, {})) as publish:
            result = wiki.run(self.root, SimpleNamespace(command="publish", release=self.manifest["release_id"]))
        read.assert_called_once_with(self.root, self.manifest["release_id"])
        self.assertEqual(publish.call_args.args, (self.root, self.project, self.manifest))
        self.assertEqual(result["release_id"], self.manifest["release_id"])

    def test_publish_cli_requires_release_and_has_no_override_flag(self):
        for arguments in (["wiki.py", "publish"],
                          ["wiki.py", "publish", "--release", "a" * 64, "--override"]):
            with self.subTest(arguments=arguments), patch.object(wiki.sys, "argv", arguments), \
                    patch.object(wiki.sys, "stderr", Mock()), patch.object(wiki, "run") as run:
                with self.assertRaises(SystemExit) as exit:
                    wiki.main()
                self.assertEqual(exit.exception.code, 2)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
