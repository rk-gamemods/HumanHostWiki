"""Prune keeps only the latest local state, inside owned folders, never under another writer."""

import json
import unittest

import test_history
from test_identity import observation
from wikibuild import prune, reader
from wikibuild.storage import ContractError, json_bytes, writer_lock


class PruneTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_history.HistoryTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.setUp()
        self.root = self.fixture.root
        self.runs, self.extractions = [], []
        for build, value in (("100", 1), ("200", 2)):
            self.fixture.set_input([observation(value=value)], build=build)
            extracted = self.fixture.extracted
            receipt = self.root / ".local/extractions/runs" / (extracted["run_id"] + ".json")
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_bytes(json_bytes({"run_id": extracted["run_id"], "records": extracted["records"]}))
            self.extractions.append(extracted)
            self.runs.append(self.fixture.run_history()[0])
        (self.root / ".local/extraction-latest.json").write_bytes(json_bytes({"run_id": self.extractions[-1]["run_id"]}))
        self.current, self.old_candidate = "a" * 64, "b" * 64
        for candidate in (self.current, self.old_candidate):
            folder = self.root / ".local/readers" / candidate[:24]
            folder.mkdir(parents=True)
            (folder / "candidate.json").write_bytes(b"{}")
        (self.root / ".local/reader-latest.json").write_bytes(json_bytes({"candidate_id": self.current}))
        (self.root / ".local/reader-stage" / ("c" * 32)).mkdir(parents=True)
        for stage in ("d" * 12, "e" * 12):
            (self.root / ".local/rs" / stage).mkdir(parents=True)
            (self.root / ".local/rs" / stage / "plan.json").write_bytes(b"{}")
        (self.root / ".local/releases").mkdir(parents=True)
        self.pending = self.root / ".local/releases/pending.json"
        self.pending.write_bytes(json_bytes({"stage": ".local/rs/" + "e" * 12, "complete": True}))
        self.unknown = [self.root / "identity/states/notes.txt", self.root / ".local/readers/keep.txt",
                        self.root / ".local/unrelated.json"]
        for path in self.unknown:
            path.write_bytes(b"keep")

    def files(self):
        return {path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file()}

    def test_keeps_only_latest_of_each_and_never_touches_other_files(self):
        old, latest = self.runs
        before = self.files()
        summary = prune.run(self.root)
        after = self.files()
        for label in ("state", "models"):
            self.assertIn(latest[label]["path"], after)
            self.assertNotIn(old[label]["path"], after)
        self.assertIn(self.extractions[-1]["records"]["path"], after)
        self.assertNotIn(self.extractions[0]["records"]["path"], after)
        self.assertNotIn(".local/extractions/runs/" + self.extractions[0]["run_id"] + ".json", after)
        self.assertTrue((self.root / ".local/readers" / self.current[:24]).is_dir())
        self.assertFalse((self.root / ".local/readers" / self.old_candidate[:24]).exists())
        self.assertFalse((self.root / ".local/reader-stage" / ("c" * 32)).exists())
        self.assertTrue((self.root / ".local/rs" / ("e" * 12)).is_dir())
        self.assertFalse((self.root / ".local/rs" / ("d" * 12)).exists())
        self.assertTrue(all(path.read_bytes() == b"keep" for path in self.unknown))
        # Identity receipts stay; only bulky state left. Nothing appeared.
        self.assertTrue((self.root / "identity/runs" / (old["run_id"] + ".json")).is_file())
        self.assertLessEqual(after, before)
        self.assertEqual(1, summary["removed"]["states"])
        self.assertEqual([latest["run_id"]], [run["run_id"] for run in reader.versions(self.root)])
        self.assertEqual({key: 0 for key in summary["removed"]}, prune.run(self.root)["removed"])

    def test_refuses_while_another_writer_holds_the_lock_and_deletes_nothing(self):
        before = self.files()
        with writer_lock(self.root):
            with self.assertRaisesRegex(ContractError, "Another wiki writer"):
                prune.run(self.root)
        self.assertEqual(before, self.files())

    def test_refuses_during_a_pending_release_and_dry_run_deletes_nothing(self):
        before = self.files()
        self.pending.write_bytes(json_bytes({"stage": ".local/rs/" + "e" * 12, "complete": False}))
        with self.assertRaisesRegex(ContractError, "release transaction is pending"):
            prune.run(self.root)
        self.assertEqual(before, self.files())
        self.pending.write_bytes(json_bytes({"stage": ".local/rs/" + "e" * 12, "complete": True}))
        summary = prune.run(self.root, dry_run=True)
        self.assertTrue(summary["dry_run"])
        self.assertGreater(sum(summary["removed"].values()), 0)
        self.assertEqual(before, self.files())

    def test_refuses_when_the_kept_state_is_damaged(self):
        before = self.files()
        (self.root / self.runs[-1]["models"]["path"]).unlink()
        with self.assertRaises(ContractError):
            prune.run(self.root)
        self.assertEqual(before - {self.runs[-1]["models"]["path"]}, self.files())

    def test_migration_baseline_state_is_kept(self):
        old, latest = self.runs
        record = {"schema_version": 1, "base_run": old["run_id"], "baseline": old["state"], "redirects": {}, "repairs": []}
        from wikibuild import model
        record["migration_id"] = model.fingerprint(record)
        (self.root / "identity/migration.json").write_bytes(json_bytes(record))
        prune.run(self.root)
        self.assertTrue((self.root / old["state"]["path"]).is_file())
        self.assertFalse((self.root / old["models"]["path"]).exists())
        self.assertTrue(json.loads((self.root / "identity/latest.json").read_bytes())["run_id"] == latest["run_id"])


if __name__ == "__main__":
    unittest.main()
