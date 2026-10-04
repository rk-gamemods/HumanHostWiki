"""Production boundaries with synthetic Git/API responses and owned local fixtures."""

from datetime import datetime, timedelta, timezone
import subprocess
import unittest
from unittest.mock import Mock, patch

from tests._support import fixture_dir
from wikibuild import github_pages, publication, publication_git, publish_gate
from wikibuild.storage import ContractError


class PublishGateTests(unittest.TestCase):
    def setUp(self):
        self.folder = fixture_dir(self, "gate")
        self.origin, self.root = self.folder / "origin", self.folder
        self.origin.mkdir()
        (self.root / "code.txt").write_text("reviewed code")
        self.commit = self.head = self.main = "e" * 40
        self.origin_url = "https://github.com/rk-gamemods/HumanHostWiki.git"
        commands = patch.object(publish_gate.bounded, "run", side_effect=self.git_response)
        self.commands = commands.start()
        self.addCleanup(commands.stop)
        self.project = {"github_owner": "rk-gamemods", "publication": {"enabled": True},
                        "repositories": [{"id": "hub", "github_name": "Wiki-hub", "path": "repositories/hub"}]}
        self.manifest = {"release_id": "a" * 64}
        self.refs = [{"repository": "Wiki-hub", "branch": branch, "commit": "c" * 40}
                     for branch in ("main", "gh-pages")]
        self.host = Mock()
        self.host.api.return_value = {"workflow_runs": [{"id": 1, "name": "CI", "head_sha": self.commit,
                                                        "path": publish_gate.CI_PATH, "event": "push",
                                                        "head_branch": "main", "run_attempt": 1,
                                                        "status": "completed", "conclusion": "success"}]}
        self.pulls = [{"number": 27, "merged_at": "2026-10-03T00:00:00Z", "merge_commit_sha": self.commit}]
        self.pages = {"source": {"branch": "gh-pages", "path": "/"}, "build_type": "legacy",
                      "cname": None, "html_url": "https://rk-gamemods.github.io/Wiki-hub/"}
        self.remote = {"id": 1, "full_name": "rk-gamemods/Wiki-hub", "private": False,
                       "archived": False, "fork": False, "permissions": {"admin": True}}
        self.host.repository.side_effect = lambda name: self.remote
        self.host.api.side_effect = lambda method, path, **kwargs: (self.pulls if path.endswith("/pulls") else
                                                                  self.pages if path.endswith("/pages") else self.host.api.return_value)
        self.host.ref.return_value = "c" * 40
        self.client = patch.object(publish_gate.github_pages, "GitHubPages", return_value=self.host)
        self.client.start()
        self.addCleanup(self.client.stop)
        self.observations = [github_pages.validate_configuration(self.project["github_owner"], "Wiki-hub", self.remote, self.pages)]
        publish_gate.write_receipt(self.root, self.manifest["release_id"], self.commit, self.refs, self.observations)

    def git_response(self, command, **options):
        self.assertEqual(options["timeout"], publish_gate.GIT_TIMEOUT)
        args = command[3:]
        if args[0] == "status":
            value = (" M code.txt" if (self.root / "code.txt").read_text() != "reviewed code" else
                     "?? untracked.txt" if (self.root / "untracked.txt").exists() else "")
        elif args == ["remote", "get-url", "origin"]:
            value = self.origin_url
        elif args[0] == "fetch":
            value = ""
        elif args == ["rev-parse", "HEAD"]:
            value = self.head
        elif args == ["rev-parse", "refs/remotes/origin/main"]:
            value = self.main
        else:
            raise AssertionError(f"Unexpected Git command: {command}")
        return subprocess.CompletedProcess(command, 0, value.encode(), b"")

    def check(self):
        return publish_gate.check(self.root, self.project, self.manifest)

    def edit_receipt(self, **values):
        path = publish_gate.receipt_path(self.root, self.manifest["release_id"])
        receipt = publication.load(path)
        publication.save(path, {**receipt, **values})

    def prepared_publication(self, pages="c" * 40):
        plan = {"path": "origin", "name": "Wiki-hub", "repository_id": 1, "role": "hub",
                "base": "https://rk-gamemods.github.io/Wiki-hub/", "main": "c" * 40,
                "old_main": "c" * 40, "old_pages": "c" * 40, "pages": pages,
                "tree": "f" * 40, "files": {}, "checks": {}, "verified": False}
        return {"schema_version": 1, "release_id": self.manifest["release_id"],
                "owner": self.project["github_owner"], "contract": publication.contract(),
                "phase": "hub", "repositories": {"hub": plan}, "groups": [[], []],
                "entrypoints": {"hub": "hub"}, "hub_control": "hub", "rollback": None,
                "fallback": {"tree": "f" * 40, "files": {}}}

    def completed_publication(self, state):
        return {"schema_version": 1, "release_id": state["release_id"], "status": "published",
                "contract": state["contract"], "repositories": state["repositories"],
                "hub": state["repositories"]["hub"]["base"], "entrypoints": {"hub": "hub"}}

    def test_pass_records_exact_commit_ci_and_receipt_and_ignores_local_files(self):
        result = self.check()
        self.assertEqual(result["workspace_commit"], self.commit)
        self.assertEqual(result["ci_run_id"], 1)
        self.assertEqual(result["rehearsal"]["remote_refs"], self.refs)
        self.assertEqual(result["merged_pr"], 27)
        self.assertEqual(self.host.api.call_count, 3)
        self.host.api.assert_any_call("GET", f"repos/rk-gamemods/HumanHostWiki/actions/runs?head_sha={self.commit}")
        self.host.api.assert_any_call("GET", f"repos/rk-gamemods/HumanHostWiki/commits/{self.commit}/pulls")
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
        for head, main in (("a" * 40, self.commit), (self.commit, "a" * 40)):
            with self.subTest(head=head, main=main):
                self.head, self.main = head, main
                with self.assertRaisesRegex(ContractError, "HEAD must equal fetched origin/main"):
                    self.check()
                self.host.api.assert_not_called()

    def test_ci_missing_in_progress_failed_and_wrong_sha_fail_closed(self):
        for runs, message in [([], "CI is missing"),
                              ([{"status": "in_progress", "conclusion": None}], "CI has not completed"),
                              ([{"status": "completed", "conclusion": "failure"}], "CI did not conclude success"),
                              ([{"head_sha": "f" * 40}], "CI is missing")]:
            with self.subTest(message=message, runs=runs):
                self.host.api.return_value = {"workflow_runs": [
                    {"id": 1, "name": "CI", "path": publish_gate.CI_PATH, "event": "push",
                     "head_branch": "main", "head_sha": self.commit, **row} for row in runs]}
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
                publish_gate.write_receipt(self.root, self.manifest["release_id"], self.commit, self.refs, self.observations)
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

    def test_absent_and_disabled_observations_pass_and_changes_fail(self):
        original, pages = self.remote, self.pages
        self.host.ref.return_value = None
        refs = [{**row, "commit": None} for row in self.refs]
        for observed in ("absent", "pages-disabled", "present"):
            with self.subTest(observed=observed):
                self.remote = None if observed == "absent" else original
                self.pages = None if observed == "pages-disabled" else pages
                row = github_pages.validate_configuration(self.project["github_owner"], "Wiki-hub", self.remote, self.pages)
                self.edit_receipt(remote_refs=refs, destination_observations=[row])
                self.check()
                if observed == "absent":
                    self.remote = original
                elif observed == "pages-disabled":
                    self.pages = pages
                else:
                    self.remote = {**original, "id": 2}
                with self.assertRaisesRegex(ContractError, "destination observation changed"):
                    self.check()

    def test_destination_observations_require_complete_unique_coverage(self):
        for observations in ([], self.observations * 2, [{"repository": "other", "observed": "absent"}],
                             [{"repository": "Wiki-hub", "observed": "unknown"}], [None]):
            with self.subTest(observations=observations):
                self.edit_receipt(destination_observations=observations)
                with self.assertRaises(ContractError):
                    self.check()

    def test_changed_pages_configuration_and_visibility_fail_read_only(self):
        for key, value in (("cname", "other.example"), ("html_url", "https://other.example/"),
                           ("source", {"branch": "main", "path": "/"})):
            with self.subTest(key=key):
                original = self.pages[key]
                self.pages[key] = value
                with self.assertRaisesRegex(ContractError, "Unexpected Pages"):
                    self.check()
                self.host.push.assert_not_called()
                self.host.create.assert_not_called()
                self.pages[key] = original
        self.remote["private"] = True
        with self.assertRaisesRegex(ContractError, "remote identity or permissions"):
            self.check()

    def test_pending_gate_failure_preserves_journal_and_makes_no_host_call(self):
        path = self.root / ".local/publication/pending.json"
        publication.save(path, {"phase": "topics", "owner": "rk-gamemods"})
        before = path.read_bytes()
        (self.root / "code.txt").write_text("dirty")
        with patch.object(publication, "execute", side_effect=AssertionError("Unexpected execution")), \
                patch.object(publication, "prepare", side_effect=AssertionError("Unexpected provisioning")):
            with self.assertRaisesRegex(ContractError, "abandon-publication"):
                publication.run(self.root, self.project, self.manifest, host=self.host)
        self.assertEqual(path.read_bytes(), before)
        self.host.assert_not_called()
        self.assertEqual(self.host.method_calls, [])

    def test_pending_blocks_same_and_other_releases_before_gate(self):
        for identity in (self.manifest["release_id"], "b" * 64):
            with self.subTest(identity=identity):
                path = self.root / ".local/publication/pending.json"
                publication.save(path, {"phase": "topics", "release_id": identity})
                before = path.read_bytes()
                with patch.object(publish_gate, "check") as gate:
                    with self.assertRaisesRegex(ContractError, "abandon-publication"):
                        publication.run(self.root, self.project, self.manifest)
                    gate.assert_not_called()
                self.assertEqual(path.read_bytes(), before)
                self.host.assert_not_called()

    def test_abandon_invalidates_all_related_rehearsals_and_requires_a_fresh_one(self):
        target = self.manifest["release_id"]
        related, last_gate, unrelated = "b" * 64, "c" * 64, "d" * 64
        original = publish_gate.receipt_path(self.root, target).read_bytes()
        alias = self.root / ".local/publication/rehearsals/copy.json"
        alias.write_bytes(original)
        for identity in (related, last_gate, unrelated):
            publish_gate.write_receipt(self.root, identity, self.commit, self.refs, self.observations)
        preserved = publish_gate.receipt_path(self.root, unrelated).read_bytes()
        publication.save(self.root / ".local/publication/pending.json",
                         {"phase": "hub", "release_id": target,
                          "gate": {"rehearsal": {"release_id": related}},
                          "last_gate": {"rehearsal": {"release_id": last_gate}}})
        result = publication.abandon(self.root)
        archive = self.root / result["archive"]
        for identity in (target, related, last_gate):
            self.assertFalse(publish_gate.receipt_path(self.root, identity).exists())
        self.assertFalse(alias.exists())
        self.assertEqual(publish_gate.receipt_path(self.root, unrelated).read_bytes(), preserved)
        archived = list(archive.glob("rehearsal-*.json"))
        self.assertEqual(len(archived), 4)
        self.assertEqual({publication.load(path)["release_id"] for path in archived},
                         {target, related, last_gate})
        self.assertEqual(self.host.method_calls, [])
        with patch.object(publication, "_run", side_effect=AssertionError("Engine reached before fresh rehearsal")):
            with self.assertRaisesRegex(ContractError, "rehearsal receipt is missing"):
                publication.run(self.root, self.project, self.manifest, host=self.host)
        publish_gate.write_receipt(self.root, target, self.commit, self.refs, self.observations)
        self.assertEqual(self.check()["rehearsal"]["release_id"], target)

    def test_abandon_preserves_receipt_referenced_by_latest(self):
        state = self.prepared_publication()
        state["repositories"]["hub"]["verified"] = True
        publication.save(self.root / ".local/publication/pending.json", state)
        receipt = self.root / "publications" / (state["release_id"] + ".json")
        publication.save(receipt, self.completed_publication(state))
        pointer = self.root / "publications/latest.json"
        publication.save(pointer, {"release_id": state["release_id"]})
        before = receipt.read_bytes(), pointer.read_bytes()
        result = publication.abandon(self.root)
        self.assertEqual((receipt.read_bytes(), pointer.read_bytes()), before)
        self.assertFalse((self.root / result["archive"] / "publication.json").exists())

    def test_abandon_does_not_archive_an_unreferenced_receipt_from_another_attempt(self):
        state = self.prepared_publication()
        publication.save(self.root / ".local/publication/pending.json", state)
        receipt = self.root / "publications" / (state["release_id"] + ".json")
        other = self.completed_publication(state)
        other["gate"] = {"checked_utc": "a different attempt"}
        publication.save(receipt, other)
        before = receipt.read_bytes()
        result = publication.abandon(self.root)
        self.assertEqual(receipt.read_bytes(), before)
        self.assertFalse((self.root / result["archive"] / "publication.json").exists())

    def test_abandon_archives_own_orphan_when_latest_does_not_exist(self):
        state = self.prepared_publication()
        state["repositories"]["hub"]["verified"] = True
        publication.save(self.root / ".local/publication/pending.json", state)
        receipt = self.root / "publications" / (state["release_id"] + ".json")
        publication.save(receipt, self.completed_publication(state))
        before = receipt.read_bytes()
        result = publication.abandon(self.root)
        self.assertEqual((self.root / result["archive"] / "publication.json").read_bytes(), before)
        self.assertFalse(receipt.exists())

    def test_invalid_latest_pointer_blocks_archival_before_any_moves(self):
        state = self.prepared_publication()
        pending = self.root / ".local/publication/pending.json"
        publication.save(pending, state)
        receipt = self.root / "publications" / (state["release_id"] + ".json")
        publication.save(receipt, self.completed_publication(state))
        publication.save(self.root / "publications/latest.json", [])
        rehearsal = publish_gate.receipt_path(self.root, state["release_id"])
        before = pending.read_bytes(), receipt.read_bytes(), rehearsal.read_bytes()
        with self.assertRaisesRegex(ContractError, "invalid latest publication pointer"):
            publication.abandon(self.root)
        self.assertEqual((pending.read_bytes(), receipt.read_bytes(), rehearsal.read_bytes()), before)
        self.assertFalse((self.root / ".local/publication/abandoned").exists())

    def test_malformed_rehearsal_identity_does_not_crash_abandonment(self):
        target = self.manifest["release_id"]
        self.edit_receipt(release_id=[])
        broken = self.root / ".local/publication/rehearsals/broken.json"
        publication.save(broken, {"release_id": []})
        before = broken.read_bytes()
        publication.save(self.root / ".local/publication/pending.json", {"phase": "hub", "release_id": target})
        publication.abandon(self.root)
        self.assertFalse(publish_gate.receipt_path(self.root, target).exists())
        self.assertEqual(broken.read_bytes(), before)

    def test_abandon_archives_checksum_valid_non_object_journals_as_unknown(self):
        pending = self.root / ".local/publication/pending.json"
        for payload in ([], None, "invalid", 42, True):
            with self.subTest(payload=payload):
                publication.save(pending, payload)
                before = pending.read_bytes()
                publish_gate.write_receipt(self.root, self.manifest["release_id"], self.commit, self.refs, self.observations)
                result = publication.abandon(self.root)
                self.assertEqual(result["release_id"], "unknown")
                archive = self.root / result["archive"]
                self.assertEqual((archive / "pending.json").read_bytes(), before)
                self.assertFalse(pending.exists())
                self.assertFalse(publish_gate.receipt_path(self.root, self.manifest["release_id"]).exists())
        self.assertEqual(self.host.method_calls, [])

    def test_origin_identity_accepts_only_canonical_https_and_ssh(self):
        for url in ("https://github.com/rk-gamemods/HumanHostWiki.git", "git@github.com:rk-gamemods/HumanHostWiki.git",
                    "ssh://git@github.com/rk-gamemods/HumanHostWiki"):
            with self.subTest(url=url):
                self.origin_url = url
                self.check()
        self.host.reset_mock()
        for url in (str(self.origin), "https://github.com/other/HumanHostWiki.git",
                    "https://github.com/rk-gamemods/Other.git", "https://example.com/rk-gamemods/HumanHostWiki.git",
                    "https://github.com.evil.invalid/rk-gamemods/HumanHostWiki.git"):
            with self.subTest(url=url):
                self.origin_url = url
                self.commands.reset_mock()
                with self.assertRaisesRegex(ContractError, "origin must resolve"):
                    self.check()
                self.assertFalse(any("fetch" in call.args[0] for call in self.commands.call_args_list))
                self.host.api.assert_not_called()

    def test_ci_wrong_workflow_event_branch_or_sha_is_refused(self):
        good = self.host.api.return_value["workflow_runs"][0]
        for field, value in (("path", ".github/workflows/fake.yml"), ("path", None),
                             ("event", "pull_request"), ("event", "workflow_dispatch"),
                             ("head_branch", "feature"), ("head_sha", "b" * 40)):
            with self.subTest(field=field, value=value):
                self.host.api.return_value = {"workflow_runs": [{**good, field: value}]}
                with self.assertRaisesRegex(ContractError, "CI is missing"):
                    self.check()
                self.host.ref.assert_not_called()

    def test_merged_pr_for_this_exact_commit_is_required(self):
        for pulls in ([], [{"merged_at": None, "merge_commit_sha": self.commit}],
                      [{"merged_at": "2026-10-03T00:00:00Z", "merge_commit_sha": "b" * 40}]):
            with self.subTest(pulls=pulls):
                self.pulls = pulls
                with self.assertRaisesRegex(ContractError, "merge commit of a merged PR"):
                    self.check()
                self.host.ref.assert_not_called()
        self.pulls = {}
        with self.assertRaisesRegex(ContractError, "invalid merged PR response"):
            self.check()

    def test_drift_between_gate_and_prepare_aborts_without_provision_or_push(self):
        self.host.ref.side_effect = ["c" * 40, "c" * 40, "d" * 40]
        with patch.object(publication, "provision") as provision:
            with self.assertRaisesRegex(ContractError, "differs from rehearsal"):
                publication.run(self.root, self.project, self.manifest, host=self.host)
            provision.assert_not_called()
        self.host.push.assert_not_called()
        self.assertFalse((self.root / ".local/publication/pending.json").exists())

    def test_prepare_checks_refs_before_adopting_owned_lineage(self):
        refs = publication.RehearsedRefs(self.refs)
        self.host.ref.return_value = "d" * 40
        with patch.object(publication.publication_git, "owned_lineage", return_value=True) as lineage, \
                patch.object(publication, "provision") as provision:
            with self.assertRaisesRegex(ContractError, "differs from rehearsal"):
                publication.prepare(self.root, self.project, self.manifest, self.host, refs)
            lineage.assert_not_called()
            provision.assert_not_called()
        self.host.push.assert_not_called()

    def test_each_push_requires_rehearsal_or_own_confirmed_tip(self):
        refs = publication.RehearsedRefs(self.refs)
        current = "c" * 40
        self.host.ref.side_effect = lambda *args: current

        def pushed(*args):
            nonlocal current
            current = args[2]
        self.host.push.side_effect = pushed
        refs.push(self.host, self.root, "Wiki-hub", "d" * 40, "main")
        self.assertEqual(self.host.push.call_args.args[-1], "c" * 40)
        refs.push(self.host, self.root, "Wiki-hub", "e" * 40, "main")
        self.assertEqual(self.host.push.call_args.args[-1], "d" * 40)
        current = "f" * 40
        with self.assertRaisesRegex(ContractError, "differs from rehearsal"):
            refs.push(self.host, self.root, "Wiki-hub", "a" * 40, "main")
        self.assertEqual(self.host.push.call_count, 2)

    def test_deploy_refuses_drift_after_main_push_before_pages_push(self):
        current = {(row["repository"], row["branch"]): row["commit"] for row in self.refs}
        self.host.ref.side_effect = lambda name, branch: current[(name, branch)]

        def pushed(path, name, commit, branch, expected):
            current[(name, branch)] = commit
            current[(name, "gh-pages")] = "f" * 40
        self.host.push.side_effect = pushed
        plan = {"path": "origin", "name": "Wiki-hub", "main": "d" * 40, "pages": "e" * 40}
        with self.assertRaisesRegex(ContractError, "differs from rehearsal"):
            publication.deploy(self.root, plan, self.host, refs=publication.RehearsedRefs(self.refs))
        self.assertEqual(self.host.push.call_count, 1)
        self.host.configure.assert_called_once_with("Wiki-hub", defer=True)

    def test_failed_push_cannot_adopt_a_matching_unconfirmed_tip(self):
        refs = publication.RehearsedRefs(self.refs)
        self.host.ref.side_effect = ["c" * 40, "d" * 40]
        self.host.push.side_effect = ContractError("push refused")
        with self.assertRaisesRegex(ContractError, "push refused"):
            refs.push(self.host, self.root, "Wiki-hub", "d" * 40, "main")
        self.assertEqual(refs.confirmed, {})
        with self.assertRaisesRegex(ContractError, "differs from rehearsal"):
            refs.push(self.host, self.root, "Wiki-hub", "e" * 40, "main")
        self.assertEqual(self.host.push.call_count, 1)

    def test_gate_compares_rehearsal_runner_digest(self):
        contract = publication.contract()
        self.assertIn("tools/rehearse_publication.py", contract)
        self.edit_receipt(contract={**contract, "tools/rehearse_publication.py": "f" * 64})
        with self.assertRaisesRegex(ContractError, "publication contract differs"):
            self.check()
        self.host.ref.assert_not_called()

    def test_first_abandoned_pages_lineage_requires_a_pinned_root(self):
        root, head = "a" * 40, "b" * 40

        def command(argv, **kwargs):
            self.assertEqual(kwargs["timeout"], 120)
            args = argv[3:]
            output = (head + "\n" + root if args[0] == "rev-list" else
                      args[-1].rsplit("/", 1)[-1] if args[0] == "show-ref" else
                      "root-tree" if args[0] == "rev-parse" and args[1].startswith(root) else "head-tree")
            return subprocess.CompletedProcess(argv, 0, output.encode(), b"")
        def records(path, *args, **kwargs):
            self.assertEqual(path, self.root)
            self.assertEqual(args, ("rev-list", "--reverse", head))
            self.assertEqual(kwargs["separator"], b"\n")
            self.assertGreater(kwargs["timeout"], 0)
            self.assertLessEqual(kwargs["timeout"], publication_git.GIT_LINEAGE_TIMEOUT)
            yield from (root.encode(), head.encode())
        with patch.object(publication_git.bounded, "run", side_effect=command), \
                patch.object(publication_git, "git_records", side_effect=records):
            self.assertTrue(publication_git.owned_lineage(self.root, None, head, provenance={root, head}))

        def foreign_root(argv, **kwargs):
            if argv[3] == "show-ref" and argv[-1].endswith(root):
                return subprocess.CompletedProcess(argv, 1, b"", b"")
            return command(argv, **kwargs)
        with patch.object(publication_git.bounded, "run", side_effect=foreign_root), \
                patch.object(publication_git, "git_records", side_effect=records):
            self.assertFalse(publication_git.owned_lineage(self.root, None, head, provenance={root, head}))

    def test_push_adapter_uses_explicit_lease_and_ancestry_check(self):
        self.client.stop()
        host = github_pages.GitHubPages("rk-gamemods")
        target = "d" * 40
        for expected in ("c" * 40, None):
            with self.subTest(expected=expected), patch.object(host, "ref", side_effect=[expected, target]), \
                    patch.object(github_pages.bounded, "run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as run:
                host.push(self.root, "Wiki-hub", target, "gh-pages", expected)
                push = run.call_args.args[0]
                self.assertIn(f"--force-with-lease=refs/heads/gh-pages:{expected or ''}", push)
                self.assertEqual(run.call_args.kwargs["timeout"], host.PUSH_TIMEOUT)
                if expected:
                    self.assertIn("--is-ancestor", run.call_args_list[0].args[0])
                else:
                    self.assertEqual(run.call_count, 1)
        with patch.object(host, "ref", return_value="c" * 40), \
                patch.object(github_pages.bounded, "run", return_value=subprocess.CompletedProcess([], 1, b"", b"")) as run:
            with self.assertRaisesRegex(ContractError, "Non-fast-forward"):
                host.push(self.root, "Wiki-hub", target, "gh-pages", "c" * 40)
            self.assertEqual(run.call_count, 1)
            self.assertNotIn("push", run.call_args.args[0])
        with patch.object(host, "ref", return_value=target), patch.object(github_pages.bounded, "run") as run:
            with self.assertRaisesRegex(ContractError, "Remote branch changed"):
                host.push(self.root, "Wiki-hub", target, "gh-pages", "c" * 40)
            run.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
