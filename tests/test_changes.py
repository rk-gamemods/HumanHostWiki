"""Compact change log: real semantic changes per capture, independent of provenance."""

import json
import unittest
from unittest.mock import patch

import test_history
from test_identity import observation
from wikibuild import changes, history, identity
from wikibuild.storage import json_bytes, writer_lock


class ChangeLogTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_history.HistoryTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.setUp()
        self.root = self.fixture.root
        self.key_a, self.key_b, self.key_c = (identity.fingerprint(["item", name])[:32] for name in "abc")

    def capture(self, rows, build):
        self.fixture.set_input(rows, build=build)
        receipt = self.fixture.receipt
        path = self.root / "snapshots" / (receipt["snapshot_id"] + ".json")
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(json_bytes({"schema_version": 1, "snapshot_id": receipt["snapshot_id"], "steam": receipt["steam"],
                                     "game_version": "0.8." + build, "captured": "2026-11-0" + build[0] + "T10:00:00Z",
                                     "status": "input-registered", "wiki_verification": "not-performed"}))
        run, _ = self.fixture.run_history()
        return run

    def record(self, run):
        with writer_lock(self.root):
            return changes.record(self.root, run)

    def log(self, topic="items-equipment"):
        return json.loads((self.root / "changes" / (topic + ".json")).read_bytes())

    def test_first_capture_records_counts_without_comparison(self):
        run = self.capture([observation("bundle#1", "A", 1, self.key_a)], "100")
        self.assertEqual(["items-equipment"], self.record(run)["recorded"])
        entry = self.log()["versions"][0]
        self.assertEqual({"snapshot_id": run["snapshot_id"], "game_version": "0.8.100", "build_id": "100",
                          "captured": "2026-11-01", "count": 1, "previous": None}, entry)
        before = (self.root / "changes/items-equipment.json").read_bytes()
        self.assertTrue(self.record(run)["reused"])
        self.assertEqual(before, (self.root / "changes/items-equipment.json").read_bytes())

    def test_added_removed_and_changed_fields_ignore_provenance_only_changes(self):
        first = self.capture([observation("bundle#1", "A", 1, self.key_a), observation("bundle#2", "B", 1, self.key_b)], "100")
        self.record(first)
        # Same facts under a new source id: identity keeps or pairs the record; nothing is logged for it.
        second = self.capture([observation("bundle#7", "A", 1, self.key_a), observation("bundle#3", "C", 5, self.key_c)], "200")
        self.record(second)
        entry = self.log()["versions"][0]
        self.assertEqual(entry["previous"]["snapshot_id"], first["snapshot_id"])
        self.assertEqual(["C"], [row["name"] for row in entry["added"]])
        self.assertEqual([("B", "not-present")], [(row["name"], row["status"]) for row in entry["removed"]])
        self.assertEqual([], entry["changed"])
        third = self.capture([observation("bundle#7", "A", 2, self.key_a), observation("bundle#3", "C", 5, self.key_c)], "300")
        self.record(third)
        log = self.log()
        self.assertEqual([third["snapshot_id"], second["snapshot_id"], first["snapshot_id"]],
                         [row["snapshot_id"] for row in log["versions"]])
        changed = log["versions"][0]["changed"]
        self.assertEqual(["A"], [row["name"] for row in changed])
        self.assertEqual({"/facts/value": {"old": 1, "new": 2}}, changed[0]["fields"])
        self.assertNotIn("bundle#", json.dumps(log))
        self.assertLess(len((self.root / "changes/items-equipment.json").read_bytes()), 4096)

    def test_correction_run_of_one_capture_compares_with_the_previous_capture_once(self):
        first = self.capture([observation("bundle#1", "A", 1, self.key_a)], "100")
        self.record(first)
        second = self.capture([observation("bundle#1", "A", 2, self.key_a)], "200")
        with patch.object(history, "contract", return_value="corrected-contract"):
            corrected, _ = self.fixture.run_history()
        self.assertEqual(second["run_id"], corrected["parent_run"])
        self.assertEqual(first["run_id"], changes.base_run(self.root, corrected)["run_id"])
        self.record(corrected)
        self.assertTrue(self.record(corrected)["reused"])
        self.assertEqual([second["snapshot_id"], first["snapshot_id"]], [row["snapshot_id"] for row in self.log()["versions"]])

    def test_pruned_state_or_models_degrade_without_inventing_changes(self):
        first = self.capture([observation("bundle#1", "A", 1, self.key_a)], "100")
        second = self.capture([observation("bundle#1", "A", 2, self.key_a)], "200")
        (self.root / first["models"]["path"]).unlink()
        entry = changes.compute(self.root, second)["items-equipment"]
        self.assertEqual([{"entity_key": entry["changed"][0]["entity_key"], "name": "A", "kind": "item"}], entry["changed"])
        (self.root / first["state"]["path"]).unlink()
        entry = changes.compute(self.root, second)["items-equipment"]
        self.assertIsNone(entry["previous"])
        self.assertNotIn("changed", entry)

    def test_identity_reader_and_log_work_after_older_states_are_pruned(self):
        first = self.capture([observation("bundle#1", "A", 1, self.key_a)], "100")
        second = self.capture([observation("bundle#1", "A", 2, self.key_a)], "200")
        for label in ("state", "models"):
            (self.root / first[label]["path"]).unlink()
        third = self.capture([observation("bundle#1", "A", 3, self.key_a)], "300")
        self.assertEqual(second["run_id"], third["parent_run"])
        self.assertEqual(third["run_id"], history.latest(self.root)["run_id"])
        self.record(third)
        self.assertEqual({"/facts/value": {"old": 2, "new": 3}}, self.log()["versions"][0]["changed"][0]["fields"])

    def test_large_values_are_summarized_and_relationships_are_keyed(self):
        old = {"facts": {"list": list(range(100)), "small": 1},
               "relationships": [{"predicate": "yields", "field": "/items/0", "targets": ["e-1"]}]}
        new = {"facts": {"list": list(range(101)), "small": 1},
               "relationships": [{"predicate": "yields", "field": "/items/0", "targets": ["e-2"]}]}
        result = changes.difference(old, new)
        self.assertEqual({"/facts/list", "/relationships/yields/items/0/targets"}, set(result))
        self.assertEqual({"omitted_bytes", "sha256"}, set(result["/facts/list"]["new"]))
        self.assertEqual({"old": ["e-1"], "new": ["e-2"]}, result["/relationships/yields/items/0/targets"])

    def test_markdown_escapes_names_and_links_current_entries(self):
        log = {"schema_version": 1, "topic": "items", "versions": [
            {"snapshot_id": "build-2-" + "a" * 12, "game_version": "0.8.2", "build_id": "2", "count": 1,
             "previous": {"snapshot_id": "build-1-" + "a" * 12, "game_version": "0.8.1", "build_id": "1"},
             "added": [{"entity_key": "e-" + "a" * 32, "name": "<b>New</b>", "kind": "item"}],
             "removed": [{"entity_key": "e-" + "b" * 32, "name": "Gone", "kind": "item", "status": "not-present"}],
             "changed": []}]}
        text = changes.markdown("Items", log, "/items/", lambda base, key: base + "entry/" + key + "/").decode()
        self.assertIn("&lt;b&gt;New&lt;/b&gt;", text)
        self.assertIn('href="/items/entry/e-' + "a" * 32 + '/"', text)
        self.assertNotIn("entry/e-" + "b" * 32, text)
        self.assertIn("1 added, 1 removed, 0 changed", text)


if __name__ == "__main__":
    unittest.main()
