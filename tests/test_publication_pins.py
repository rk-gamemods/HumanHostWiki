"""Durable publication provenance qualifies pins without modifying local evidence."""

import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock, patch

from tests._support import fixture_dir
from wikibuild import publication, publication_git
from wikibuild.storage import digest, git, json_bytes


class PublicationPinTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "pins")
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        self.repo = {"id": "loot", "path": "repositories/loot", "github_name": "Wiki-loot"}
        self.path = self.root / self.repo["path"]
        self.path.mkdir(parents=True)
        git(self.path, "init", "-q")
        git(self.path, "config", "user.name", "Fixture")
        git(self.path, "config", "user.email", "fixture@example.invalid")

    def page(self, text, parent=None):
        blob = publication_git.command(self.path, "hash-object", "-w", "--stdin", data=text.encode()).decode().strip()
        tree = publication_git.command(self.path, "mktree", data=f"100644 blob {blob}\tindex.html\n".encode()).decode().strip()
        commit = publication_git.commit(self.path, tree, parent, text)
        publication.pin(self.path, commit)
        return commit

    def evidence(self, pages, *, old_pages=None, journal=False, archive=False, row=None, committed=True, **extra):
        row = row or {"path": self.repo["path"], "name": self.repo["github_name"],
                      "pages": pages, "old_pages": old_pages}
        payload = {"schema_version": 1, "release_id": "a" * 64,
                   "repositories": {self.repo["id"]: row}, **extra}
        if journal:
            payload["phase"] = "topics"
            payload.setdefault("contract", {"publish_gate.py": "b" * 64})
            payload.setdefault("gate", self.production_gate(payload["contract"]))
            filename = ".local/publication/abandoned/attempt/pending.json" if archive else ".local/publication/pending.json"
        else:
            payload["status"] = "published"
            filename = ".local/publication/abandoned/attempt/publication.json" if archive else "publications/" + "a" * 64 + ".json"
        publication.save(self.root / filename, payload)
        if committed and not journal and not archive:
            self.commit_evidence(self.root / filename)
        return self.root / filename

    def commit_evidence(self, path):
        git(self.root, "-c", "core.autocrlf=false", "add", "--", path.relative_to(self.root).as_posix())
        git(self.root, "commit", "--allow-empty", "-qm", "Reviewed publication receipt")

    def production_gate(self, contract=None):
        # Common shape written by every production gate since 5644493.
        stamp = "2026-10-03T00:00:00+00:00"
        return {"workspace_commit": "c" * 40, "ci_run_id": 1, "checked_utc": stamp,
                "rehearsal": {"schema_version": 1, "release_id": "a" * 64,
                    "workspace_commit": "c" * 40, "created_utc": stamp,
                    "contract": contract or {"publish_gate.py": "b" * 64},
                    "remote_refs": [{"repository": self.repo["github_name"], "branch": branch, "commit": None}
                                    for branch in ("main", "gh-pages")]}}

    def commits(self):
        evidence, errors = publication_git.publication_provenance(self.root)
        self.assertEqual(errors, [])
        return evidence.get((self.repo["id"], self.repo["path"], self.repo["github_name"]), set())

    def owned(self, base, head):
        return publication_git.owned_lineage(self.path, base, head, provenance=self.commits())

    def test_untracked_hash_valid_receipt_never_qualifies_even_with_a_retained_gate(self):
        first = self.page("Simulated publication")
        for gate in (None, self.production_gate()):
            with self.subTest(gate=gate):
                self.evidence(first, committed=False, **({"gate": gate} if gate else {}))
                self.assertFalse(self.owned(None, first))
                self.assertEqual(publication.pin_report(self.root, [self.repo])["unprovenanced_pins"][0]["commit"], first)

    def test_staged_only_hash_valid_receipt_never_qualifies(self):
        first = self.page("Staged simulated publication")
        path = self.evidence(first, committed=False)
        git(self.root, "add", "--", path.relative_to(self.root).as_posix())
        self.assertFalse(self.owned(None, first))

    def test_modified_tracked_receipt_never_qualifies_even_when_staged(self):
        first = self.page("Confirmed publication")
        path = self.evidence(first)
        changed = self.page("Retry wiki release", first)
        self.evidence(changed, committed=False, gate=self.production_gate())
        for staged in (False, True):
            with self.subTest(staged=staged):
                if staged:
                    git(self.root, "add", "--", path.relative_to(self.root).as_posix())
                before = {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in self.root.rglob("*") if p.is_file()}
                self.assertFalse(self.owned(first, changed))
                self.assertFalse(self.owned(None, first))
                report = publication.pin_report(self.root, [self.repo])
                self.assertEqual({row["commit"] for row in report["unprovenanced_pins"]}, {first, changed})
                self.assertEqual({p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in self.root.rglob("*") if p.is_file()}, before)

    def test_committed_receipt_qualifies_without_gate_field_heuristics(self):
        first = self.page("Reviewed publication")
        for gate in (None, {"rehearsal": {"remote_refs": []}}, self.production_gate()):
            with self.subTest(gate=gate):
                self.evidence(first, **({"gate": gate} if gate else {}))
                self.assertTrue(self.owned(None, first))

    def test_receipt_bytes_must_match_head_without_line_ending_normalization(self):
        first = self.page("Reviewed publication")
        path = self.evidence(first)
        self.assertTrue(self.owned(None, first))
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assertFalse(self.owned(None, first))
        self.assertEqual(publication.pin_report(self.root, [self.repo])["unprovenanced_pins"][0]["commit"], first)

    def test_committed_receipt_read_timeout_is_bounded_and_does_not_qualify(self):
        first = self.page("Reviewed publication")
        self.evidence(first)
        with patch.object(publication_git.bounded, "run", side_effect=subprocess.TimeoutExpired(
                ["git", "cat-file"], publication_git.GIT_TIMEOUT)) as read:
            commits, errors = publication_git.publication_provenance(self.root)
        self.assertEqual(commits, {})
        self.assertEqual(read.call_args.kwargs["timeout"], publication_git.GIT_TIMEOUT)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["path"], "publications/" + "a" * 64 + ".json")
        self.assertFalse(publication_git.owned_lineage(self.path, None, first, provenance=commits))

    def test_receipt_pin_qualifies_and_legacy_pin_is_excluded_and_reported(self):
        first = self.page("Published")
        self.evidence(first)
        self.assertTrue(self.owned(None, first))
        legacy = self.page("Legacy rehearsal", first)
        self.assertFalse(self.owned(first, legacy))
        self.assertFalse(self.owned(None, legacy))
        report = publication.pin_report(self.root, [self.repo])
        self.assertEqual(report["provenance_errors"], [])
        self.assertEqual(report["unprovenanced_pins"], [{
            "destination": "loot", "repository": "Wiki-loot", "path": "repositories/loot",
            "ref": "refs/wiki-publications/" + legacy, "commit": legacy,
            "retire_command": f"git -C 'repositories/loot' update-ref --no-deref -d 'refs/wiki-publications/{legacy}' {legacy}"}])
        self.assertEqual(git(self.path, "rev-parse", "refs/wiki-publications/" + legacy), legacy)

    def test_only_receipts_in_publications_qualify_not_journals_or_archives(self):
        first = self.page("Unconfirmed publication")
        for journal, archive in ((True, False), (True, True), (False, True)):
            with self.subTest(journal=journal, archive=archive):
                evidence = self.evidence(first, journal=journal, archive=archive)
                self.assertFalse(self.owned(None, first))
                self.assertEqual(publication.pin_report(self.root, [self.repo])["unprovenanced_pins"][0]["commit"], first)
                evidence.unlink()
        self.evidence(first)
        self.assertTrue(self.owned(None, first))

    def test_abandon_preserves_journal_and_pin_without_qualifying_them(self):
        first = self.page("Partially published")
        pending = self.evidence(first, journal=True)
        original = pending.read_bytes()
        before = publication_git.storage_snapshot(self.path)
        self.assertFalse(self.owned(None, first))
        result = publication.abandon(self.root)
        self.assertEqual(result["status"], "abandoned")
        self.assertFalse(pending.exists())
        self.assertTrue((self.root / result["archive"] / "pending.json").is_file())
        self.assertEqual((self.root / result["archive"] / "pending.json").read_bytes(), original)
        self.assertFalse(self.owned(None, first))
        self.assertEqual(publication.pin_report(self.root, [self.repo])["unprovenanced_pins"][0]["commit"], first)
        self.assertEqual(publication_git.storage_snapshot(self.path), before)

    def test_uncommitted_rehearsal_evidence_never_qualifies(self):
        first = self.page("Simulated publication")
        # e6f3499 and eb4dba1 passed this gate to _run in the real workspace.
        gates = ({"rehearsal": {"remote_refs": []}},
                 {"rehearsal": {"remote_refs": [], "destination_observations": []}})
        for gate in gates:
            for key in ("gate", "last_gate"):
                for journal, archive in ((True, False), (True, True), (False, False), (False, True)):
                    with self.subTest(gate=gate, key=key, journal=journal, archive=archive):
                        path = self.evidence(first, journal=journal, archive=archive, committed=False, **{key: gate})
                        self.assertFalse(self.owned(None, first))
                        report = publication.pin_report(self.root, [self.repo])
                        self.assertEqual(report["unprovenanced_pins"][0]["commit"], first)
                        self.assertEqual(git(self.path, "rev-parse", "refs/wiki-publications/" + first), first)
                        path.unlink()
        self.evidence(first, journal=True, gate=gates[0])
        result = publication.abandon(self.root)
        self.assertTrue((self.root / result["archive"] / "pending.json").is_file())
        self.assertFalse(self.owned(None, first))
        self.assertEqual(publication.pin_report(self.root, [self.repo])["unprovenanced_pins"][0]["commit"], first)

    def test_gate_less_abandoned_rehearsal_journal_does_not_qualify(self):
        first = self.page("Early rehearsal")
        pending = self.evidence(first, journal=True, contract={"publish_gate.py": "b" * 64})
        payload = publication.load(pending)
        payload.pop("gate", None)
        publication.save(pending, payload)
        # 5644493 called _run without a gate; hard termination left this journal.
        result = publication.abandon(self.root)
        self.assertTrue((self.root / result["archive"] / "pending.json").is_file())
        before = publication_git.storage_snapshot(self.path)
        self.assertFalse(self.owned(None, first))
        report = publication.pin_report(self.root, [self.repo])
        self.assertEqual(report["unprovenanced_pins"][0]["commit"], first)
        self.assertEqual(publication_git.storage_snapshot(self.path), before)

    def test_completed_receipts_with_legacy_production_gates_qualify(self):
        first = self.page("Real publication")
        for version in ("5644493", "e6f3499", "3b50a31"):
            gate = self.production_gate()
            if version != "5644493":
                gate.update(origin="https://github.com/rk-gamemods/HumanHostWiki", ci_run_attempt=1, merged_pr=27)
            if version == "3b50a31":
                gate["rehearsal"]["destination_observations"] = []
            with self.subTest(version=version):
                self.evidence(first, gate=gate)
                self.assertTrue(self.owned(None, first))

    def test_journals_never_qualify_even_when_marked_complete(self):
        first = self.page("Unconfirmed attempt")
        for phase in ("topics", "hub", "rolling-back", "rolled-back", "complete"):
            for archive in (False, True):
                with self.subTest(phase=phase, archive=archive):
                    path = self.evidence(first, journal=True, archive=archive)
                    payload = publication.load(path)
                    payload.update(phase=phase, status="published")
                    publication.save(path, payload)
                    self.assertFalse(self.owned(None, first))
                    path.unlink()

    def test_resumed_rehearsal_with_retained_production_gate_is_unprovenanced(self):
        simulated = self.page("Retry wiki release")
        pending = self.evidence(simulated, journal=True)
        payload = publication.load(pending)
        payload["phase"] = "rolled-back"
        publication.save(pending, payload)
        # 5644493 resumed production state during rehearsal without replacing
        # its gate. Neither that saved journal nor its archive confirms a push.
        before = publication_git.storage_snapshot(self.path)
        self.assertFalse(self.owned(None, simulated))
        publication.abandon(self.root)
        self.assertFalse(self.owned(None, simulated))
        self.assertEqual(publication.pin_report(self.root, [self.repo])["unprovenanced_pins"][0]["commit"], simulated)
        self.assertEqual(publication_git.storage_snapshot(self.path), before)

    def test_dangling_symbolic_pin_is_reported_with_non_dereferencing_retirement(self):
        target = self.page("Pages target")
        self.evidence(target)
        ref = "refs/wiki-publications/" + target
        git(self.path, "update-ref", "--no-deref", "-d", ref)
        git(self.path, "symbolic-ref", ref, "refs/heads/missing")
        before = publication_git.storage_snapshot(self.path)
        rows = publication.pin_report(self.root, [self.repo])["unprovenanced_pins"]
        self.assertEqual(rows, [{"destination": "loot", "repository": "Wiki-loot", "path": "repositories/loot",
            "ref": ref, "commit": None, "symbolic_target": "refs/heads/missing",
            "retire_command": f"git -C 'repositories/loot' update-ref --no-deref -d '{ref}'"}])
        self.assertEqual(publication_git.storage_snapshot(self.path), before)
        # Exercise exactly the reported command's arguments in the private fixture.
        git(self.root, "-C", self.repo["path"], "update-ref", "--no-deref", "-d", ref)
        self.assertFalse((self.path / ".git" / ref).exists())
        self.assertFalse((self.path / ".git/refs/heads/missing").exists())

    def test_symbolic_pin_retirement_preserves_its_branch_target(self):
        target = self.page("Unconfirmed target")
        ref = "refs/wiki-publications/" + target
        git(self.path, "update-ref", "--no-deref", "-d", ref)
        git(self.path, "update-ref", "refs/heads/main", target)
        git(self.path, "symbolic-ref", ref, "refs/heads/main")
        before = publication_git.storage_snapshot(self.path)
        pin = publication.pin_report(self.root, [self.repo])["unprovenanced_pins"][0]
        self.assertEqual(pin["commit"], target)
        self.assertEqual(pin["symbolic_target"], "refs/heads/main")
        self.assertEqual(pin["retire_command"], f"git -C 'repositories/loot' update-ref --no-deref -d '{ref}'")
        self.assertEqual(publication_git.storage_snapshot(self.path), before)
        git(self.root, "-C", self.repo["path"], "update-ref", "--no-deref", "-d", ref)
        self.assertEqual(git(self.path, "rev-parse", "refs/heads/main"), target)
        self.assertFalse((self.path / ".git" / ref).exists())

    def test_pin_never_retargets_direct_or_symbolic_collisions(self):
        target = self.page("Pages target")
        unrelated = self.page("Unrelated work")
        ref = "refs/wiki-publications/" + target
        for kind in ("direct", "symbolic", "symbolic-same", "dangling-symbolic"):
            with self.subTest(kind=kind):
                git(self.path, "update-ref", "--no-deref", "-d", ref)
                git(self.path, "update-ref", "refs/heads/main", target if kind == "symbolic-same" else unrelated)
                if kind == "direct":
                    git(self.path, "update-ref", ref, unrelated)
                else:
                    git(self.path, "symbolic-ref", ref,
                        "refs/heads/missing" if kind == "dangling-symbolic" else "refs/heads/main")
                before = publication_git.storage_snapshot(self.path)
                with self.assertRaisesRegex(publication.ContractError, "Publication pin collision"):
                    publication.pin(self.path, target)
                self.assertEqual(publication_git.storage_snapshot(self.path), before)

    def test_disposable_clone_does_not_retarget_a_pin_collision(self):
        target = self.page("Pinned input")
        unrelated = self.page("Unrelated work")
        ref = "refs/wiki-publications/" + target
        destination = self.root / "clone"
        original = publication_git.disposable_git

        def collide(path, *arguments, **options):
            if arguments[:3] == ("update-ref", "--no-deref", "--stdin"):
                git(path, "update-ref", ref, unrelated)
            return original(path, *arguments, **options)

        with patch.object(publication_git, "disposable_git", side_effect=collide):
            with self.assertRaises(publication.ContractError):
                publication_git.disposable_clone(self.path, destination, target)
        self.assertEqual(git(destination, "rev-parse", ref), unrelated)

    def test_symbolic_historical_pin_and_direct_clone_have_identical_lineage_reads(self):
        target = self.page("Published history")
        self.evidence(target)
        ref = "refs/wiki-publications/" + target
        git(self.path, "update-ref", "--no-deref", "-d", ref)
        git(self.path, "update-ref", "refs/heads/main", target)
        git(self.path, "symbolic-ref", ref, "refs/heads/main")
        before = publication_git.storage_snapshot(self.path)
        destination = self.root / "clone"
        publication_git.disposable_clone(self.path, destination, target)
        self.assertEqual(git(self.path, "symbolic-ref", ref), "refs/heads/main")
        direct = publication_git.bounded.run(["git", "-C", str(destination), "symbolic-ref", "--quiet", ref], timeout=120)
        self.assertEqual(direct.returncode, 1)
        for path in (self.path, destination):
            self.assertEqual(git(path, "show-ref", "--verify", "--hash", ref), target)
            self.assertTrue(publication_git.owned_lineage(path, None, target, provenance=self.commits()))
        self.assertEqual(publication_git.storage_snapshot(self.path), before)

    def test_packed_identical_pin_is_reused_without_file_or_ref_changes(self):
        target = self.page("Published")
        git(self.path, "pack-refs", "--all")
        before = {p.relative_to(self.path).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.path.rglob("*") if p.is_file()}
        refs = publication_git.storage_snapshot(self.path)
        publication.pin(self.path, target)
        publication.pin(self.path, target)
        self.assertEqual(publication_git.storage_snapshot(self.path), refs)
        after = {p.relative_to(self.path).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.path.rglob("*") if p.is_file()}
        self.assertEqual(after, before)

    def test_pin_creation_race_preserves_the_other_ref(self):
        target = self.page("Pages target")
        unrelated = self.page("Unrelated work")
        ref = "refs/wiki-publications/" + target
        original = publication_git.bounded.stream
        for symbolic in (False, True):
            with self.subTest(symbolic=symbolic):
                git(self.path, "update-ref", "--no-deref", "-d", ref)
                snapshots = []

                def collide(argv, **options):
                    if symbolic:
                        git(self.path, "symbolic-ref", ref, "refs/heads/missing")
                    else:
                        git(self.path, "update-ref", ref, unrelated)
                    snapshots.append(publication_git.storage_snapshot(self.path))
                    return original(argv, **options)

                with patch.object(publication_git.bounded, "stream", side_effect=collide):
                    with self.assertRaisesRegex(publication.ContractError, "Publication pin collision"):
                        publication.pin(self.path, target)
                self.assertEqual(publication_git.storage_snapshot(self.path), snapshots[0])

    def test_failed_pin_inspection_aborts_before_promotion_and_can_retry(self):
        target = self.page("Pages target")
        ref = "refs/wiki-publications/" + target
        git(self.path, "update-ref", "--no-deref", "-d", ref)
        before = publication_git.storage_snapshot(self.path)
        original = publication_git.bounded.run
        inspections = []

        def fail_inspection(argv, **options):
            if "symbolic-ref" in argv:
                inspections.append(argv)
                if len(inspections) == 2:  # Fail while the prepared ref lock is held.
                    return subprocess.CompletedProcess(argv, 2, b"", b"Injected inspection failure")
            return original(argv, **options)

        with patch.object(publication_git.bounded, "run", side_effect=fail_inspection):
            with self.assertRaisesRegex(publication.ContractError, "Cannot inspect publication pin"):
                publication.pin(self.path, target)
        self.assertEqual(publication_git.storage_snapshot(self.path), before)
        self.assertEqual(list((self.path / ".git").rglob("*.lock")), [])
        publication.pin(self.path, target)
        self.assertEqual(git(self.path, "rev-parse", ref), target)

    def test_invalid_pin_input_cannot_inject_ref_commands(self):
        target = self.page("Pages target")
        before = publication_git.storage_snapshot(self.path)
        with self.assertRaisesRegex(publication.ContractError, "Invalid publication pin"):
            publication.pin(self.path, target + "\ncreate refs/heads/foreign " + target)
        with self.assertRaisesRegex(publication.ContractError, "Invalid publication pin"):
            publication_git.create_pin(self.path, "refs/wiki-publications/pin\ncreate refs/heads/foreign", target)
        self.assertEqual(publication_git.storage_snapshot(self.path), before)

    def test_prepare_adopts_only_provenance_for_its_exact_destination(self):
        self.repo = {**self.repo, "id": "hub", "role": "hub"}
        first = self.page("Legacy rehearsal")
        site = self.path / "site"
        site.mkdir()
        (site / "index.html").write_text("Selected release", encoding="utf-8")
        git(self.path, "add", "site")
        git(self.path, "commit", "-qm", "Selected main")
        main = git(self.path, "rev-parse", "HEAD")
        tree = git(self.path, "rev-parse", main + ":site")
        target = publication_git.commit(self.path, tree, first, "Selected Pages")
        project = {"github_owner": "fixture", "repositories": [self.repo]}
        manifest = {"release_id": "b" * 64, "inputs": {"project_sha256": digest(json_bytes(project))},
                    "repositories": {"hub": {"path": self.repo["path"], "commit": main,
                                               "pages": target, "pages_parent": first}}}
        host = Mock()
        host.ref.side_effect = lambda name, branch: main if branch == "main" else first
        refs = publication.RehearsedRefs([
            {"repository": self.repo["github_name"], "branch": branch, "commit": value}
            for branch, value in (("main", main), ("gh-pages", first))])
        with patch.object(publication, "provision", return_value={"hub": 1}), \
                patch.object(publication, "site_files", return_value={}):
            for row in (None, {"path": self.repo["path"], "name": "Wiki-other", "pages": first},
                        {"path": self.repo["path"], "name": self.repo["github_name"], "pages": "c" * 40}):
                with self.subTest(row=row):
                    if row is not None:
                        self.evidence(first, row=row)
                    with self.assertRaisesRegex(publication.ContractError, "Unexpected remote Pages branch"):
                        publication.prepare(self.root, project, manifest, host, refs)
                    self.assertEqual(git(self.path, "rev-parse", "refs/wiki-publications/" + first), first)
            self.evidence(first, old_pages=first)
            state = publication.prepare(self.root, project, manifest, host, refs)
        self.assertEqual(state["repositories"]["hub"]["old_pages"], first)
        self.assertEqual(state["repositories"]["hub"]["pages"], target)
        host.push.assert_not_called()

    def test_exact_destination_commits_in_each_receipt_field_qualify(self):
        first = self.page("Published")
        for field in ("main", "old_main", "pages", "old_pages"):
            with self.subTest(field=field):
                self.evidence(first, row={"path": self.repo["path"], "name": self.repo["github_name"], field: first})
                self.assertTrue(self.owned(None, first))
                self.assertEqual(publication.pin_report(self.root, [self.repo])["unprovenanced_pins"], [])

    def test_report_refuses_to_attribute_parent_refs_to_an_uninitialized_child(self):
        path = self.path / "uninitialized-child"
        path.mkdir()
        with self.assertRaisesRegex(publication.ContractError, "Not an independent repository"):
            publication.pin_report(self.root, [{**self.repo, "path": self.repo["path"] + "/uninitialized-child"}])

    def test_receipt_for_another_destination_or_commit_does_not_qualify(self):
        first = self.page("Forged pin")
        row = {"path": self.repo["path"], "name": self.repo["github_name"], "pages": first}
        variants = [{**row, "path": "repositories/other"}, {**row, "name": "Wiki-other"},
                    {**row, "pages": "b" * 40}]
        for variant in variants:
            with self.subTest(row=variant):
                self.evidence(first, row=variant)
                self.assertFalse(self.owned(None, first))
                self.assertEqual(publication.pin_report(self.root, [self.repo])["unprovenanced_pins"][0]["commit"], first)
        self.evidence(first)
        payload = publication.load(self.root / ("publications/" + "a" * 64 + ".json"))
        payload["repositories"] = {"other": payload["repositories"]["loot"]}
        path = self.root / ("publications/" + "a" * 64 + ".json")
        publication.save(path, payload)
        self.commit_evidence(path)
        self.assertFalse(self.owned(None, first))

    def test_rehearsal_receipt_and_corrupt_publication_receipt_do_not_qualify(self):
        first = self.page("Legacy rehearsal")
        receipt = self.evidence(first)
        rehearsal = self.root / ".local/publication/rehearsals/attempt.json"
        rehearsal.parent.mkdir(parents=True)
        receipt.rename(rehearsal)
        self.assertFalse(self.owned(None, first))
        receipt = self.evidence(first)
        receipt.write_text(receipt.read_text().replace(first, "b" * 40))
        report = publication.pin_report(self.root, [self.repo])
        self.assertEqual(len(report["provenance_errors"]), 1)
        evidence, _ = publication_git.publication_provenance(self.root)
        self.assertEqual(evidence, {})
        self.assertEqual(report["unprovenanced_pins"][0]["commit"], first)

    def test_exact_pin_target_is_required_and_identical_restores_still_qualify(self):
        first = self.page("Published")
        self.evidence(first)
        restore = publication_git.commit(self.path, git(self.path, "rev-parse", first + "^{tree}"), first, "Restore")
        self.assertTrue(self.owned(first, restore))
        self.assertTrue(self.owned(None, restore))
        forged = self.page("Different tree")
        git(self.path, "update-ref", "refs/wiki-publications/" + first, forged)
        self.assertFalse(self.owned(None, first))

    def test_receipt_recovery_commits_qualify_but_journal_rollback_does_not(self):
        first = self.page("Prepared")
        successor = self.page("Recovery", first)
        rollback = self.page("Rollback", successor)
        row = {"path": self.repo["path"], "name": self.repo["github_name"], "pages": successor,
               "recovery": {"stuck": first, "successor": successor, "status": "confirmed"}}
        self.evidence(successor, row=row, journal=True, rollback=rollback, hub_control="loot")
        self.assertEqual(self.commits(), set())
        self.evidence(successor, row=row)
        self.assertTrue(self.owned(None, successor))
        self.assertFalse(self.owned(None, rollback))

    def test_08318_receipt_preserves_adopted_4f077e3e_pages_without_old_journal(self):
        # The actual 0.8.318 receipt is the durable adoption evidence. The
        # abandoned 4f077e3e attempt has no publication receipt in the repository.
        identity = "cd0a533da3419bc83656c4e016f2733ab49757fe7952e88568d516425e5adb07"
        receipt = publication.load(Path(__file__).resolve().parents[1] / f"publications/{identity}.json")
        topic = "loot-acquisition"
        row = {key: receipt["repositories"][topic][key] for key in ("path", "name", "pages", "old_pages")}
        self.assertEqual(row["old_pages"], "ab5aa9b481202a9ad162bcefbe391f26d6835865")
        self.assertEqual(row["pages"], "d0650e746f30500d9bd0b07c000f6378a527f350")
        publication.save(self.root / f"publications/{identity}.json", {
            "schema_version": 1, "release_id": identity, "status": "published", "repositories": {topic: row}})
        self.commit_evidence(self.root / f"publications/{identity}.json")
        evidence, errors = publication_git.publication_provenance(self.root)
        self.assertEqual(errors, [])
        commits = evidence[(topic, row["path"], row["name"])]
        self.assertIn(row["old_pages"], commits)

        def command(argv, **kwargs):
            args = argv[3:]
            output = args[-1].rsplit("/", 1)[-1] if args[0] == "show-ref" else args[-1] if args[0] == "rev-parse" else ""
            return subprocess.CompletedProcess(argv, 0, output.encode(), b"")

        def records(*args, **kwargs):
            yield row["old_pages"].encode()
            yield row["pages"].encode()

        with patch.object(publication_git.bounded, "run", side_effect=command), \
                patch.object(publication_git, "git_records", side_effect=records):
            self.assertTrue(publication_git.owned_lineage(self.path, None, row["pages"], provenance=commits))

    def test_report_is_repeatable_without_file_or_ref_changes_including_packed_pins(self):
        first = self.page("Published")
        self.evidence(first)
        self.page("Legacy rehearsal", first)
        git(self.path, "pack-refs", "--all")
        symbolic = "refs/wiki-publications/symbolic"
        dangling = "refs/wiki-publications/dangling"
        git(self.path, "update-ref", "refs/heads/main", first)
        git(self.path, "symbolic-ref", symbolic, "refs/heads/main")
        git(self.path, "symbolic-ref", dangling, "refs/heads/missing")
        before = {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.root.rglob("*") if p.is_file()}
        refs = publication_git.storage_snapshot(self.path)
        first_report = publication.pin_report(self.root, [self.repo])
        self.assertIn(dangling, {row["ref"] for row in first_report["unprovenanced_pins"]})
        self.assertNotIn(symbolic, {row["ref"] for row in first_report["unprovenanced_pins"]})
        self.assertEqual(publication.pin_report(self.root, [self.repo]), first_report)
        self.assertEqual(publication_git.storage_snapshot(self.path), refs)
        after = {p.relative_to(self.root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)


    @unittest.skipIf(os.name == "nt", "filesystem symbolic refs need POSIX symlinks")
    def test_filesystem_symlink_pin_refs_are_read_without_following(self):
        # core.preferSymlinkRefs stores a symbolic ref as a filesystem link.
        common = self.path / ".git"
        folder = common / "refs/wiki-publications/" / ("a" * 40)
        folder.mkdir(parents=True)
        (folder / "backup").symlink_to("refs/heads/missing")
        refs = publication_git._pin_refs(common)
        self.assertEqual(refs["refs/wiki-publications/" + "a" * 40 + "/backup"], "ref: refs/heads/missing")
        self.assertTrue((folder / "backup").is_symlink())


if __name__ == "__main__":
    unittest.main()
