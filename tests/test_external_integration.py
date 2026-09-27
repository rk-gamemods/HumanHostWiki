"""External observations flow through offline readers and located release objects."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_external_links
import test_pipeline
import test_reader
from tools.audit_external_articles import compare
from tools.check_capacity_projection import audit
from tools.check_external_projection import check as audit_projection
from wikibuild import capacity, capacity_projection, external_links, mediawiki, reader, release
from wikibuild.storage import ContractError, json_bytes, writer_lock


def options(topic="items"):
    return {"source": deepcopy(test_external_links.SOURCE), "cache_seconds": 3600, "retry_seconds": 60,
            "routes": {topic: {"titles": [test_external_links.PREFIX],
                               "entity_prefixes": {"item": [test_external_links.PREFIX]}}}}


class ExternalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_reader.ReaderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        f.old = f.make_run("100", [f.observation(f.a, "Axe"), f.observation(f.b, "Old item")])
        f.new = f.make_run("200", [f.observation(f.a, "Axe")], absent={f.b: "not-present"})
        f.runs = [f.new, f.old]
        self.root, self.project = f.root, f.project
        self.project["external_articles"] = options()
        self.provider = test_external_links.Provider(test_external_links.page(1, "Axe"),
                                                     test_external_links.page(2, "Old item", "{{Info}}"))
        self.now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)

    def observe(self, seconds=0):
        with writer_lock(self.root):
            return external_links.refresh(self.root, self.project["external_articles"]["source"],
                request=self.provider, now=self.now + timedelta(seconds=seconds))[0]

    def view(self, site):
        return json.loads((site / "items/reader.json").read_bytes())["external_articles"]

    def test_reader_matches_each_historical_snapshot_offline_and_keeps_facts_separate(self):
        observed = self.observe()
        with patch.object(mediawiki, "Client", side_effect=AssertionError("Rendering contacted the provider")):
            site, result = self.fixture.build()
        view = self.view(site)
        self.assertEqual(view["checked_at"], observed["checked_at"])
        self.assertEqual(view["topics"][0]["status"], "missing")
        matched = reader.load_maps(site / "items", view["entries"])
        self.assertIn(self.fixture.old["snapshot_id"] + "/" + self.fixture.b, matched)
        self.assertNotIn(self.fixture.new["snapshot_id"] + "/" + self.fixture.b, matched)
        key = self.fixture.new["snapshot_id"] + "/" + self.fixture.a
        self.assertIn("oldid=10", matched[key]["url"])
        index = self.fixture.index(site, "items", self.fixture.new)
        for row in reader.load_maps(site / "items", index["entries"]).values():
            self.assertNotIn("url", row)
        self.assertTrue(self.fixture.build()[1]["reused"])
        audited = audit_projection(site)
        self.assertEqual(audited["eligible_entries"], 3)
        self.assertEqual(audited["populated_entry_links"], 2)

    def test_external_change_reuses_gameplay_files_and_removes_obsolete_article_packs(self):
        self.observe()
        first, _ = self.fixture.build()
        before = self.view(first)
        self.provider.pages[0] = test_external_links.page(1, "Axe", "Damage: 20", revision=11)
        self.observe(3600)
        with patch.object(reader, "project_snapshot", side_effect=AssertionError("Gameplay was reprojected")):
            second, result = self.fixture.build()
        self.assertTrue(result["projection_reused"])
        after = self.view(second)
        self.assertNotEqual(before["entries"], after["entries"])
        for ref in before["entries"]:
            self.assertFalse((second / "items" / ref["path"]).exists())
        for run in self.fixture.runs:
            for topic in ("hub", "items", "loot"):
                index = self.fixture.index(first, topic, run)
                self.assertTrue((first / topic / "snapshots" / (run["snapshot_id"] + ".json")).samefile(
                    second / topic / "snapshots" / (run["snapshot_id"] + ".json")))
                for kind in ("entries", "semantics", "provenance", "search", "backlinks"):
                    for ref in index[kind]:
                        self.assertTrue((first / topic / ref["path"]).samefile(second / topic / ref["path"]))
        self.observe(7200)
        third, _ = self.fixture.build()
        for ref in after["entries"]:
            self.assertTrue((second / "items" / ref["path"]).samefile(third / "items" / ref["path"]))

    def test_availability_only_change_does_not_repeat_article_matching(self):
        self.observe()
        first, _ = self.fixture.build()
        with patch.object(reader.availability, "latest", return_value={"status": "unavailable", "checked_at": "new"}), \
                patch.object(reader, "external_views", side_effect=AssertionError("Article matching repeated")):
            second, result = self.fixture.build()
        self.assertTrue(result["projection_reused"])
        self.assertEqual(self.view(first), self.view(second))

    def test_outage_preserves_gameplay_and_records_unknown_instead_of_missing(self):
        self.observe()
        first, _ = self.fixture.build()
        self.provider.failure = OSError("offline")
        self.observe(3600)
        second, result = self.fixture.build()
        self.assertEqual(self.view(second)["default_status"], "unavailable")
        self.assertEqual(self.view(second)["topics"][0]["status"], "unavailable")
        self.assertEqual(self.view(second)["entries"], [])
        self.assertTrue(result["projection_reused"])
        self.assertEqual(self.fixture.index(first, "items", self.fixture.new), self.fixture.index(second, "items", self.fixture.new))

    def test_capacity_relocates_article_control_and_packs_and_replay_writes_nothing(self):
        self.project["github_owner"] = "wiki-fixture"
        for repo in self.project["repositories"]:
            repo["github_name"] = "Wiki-" + repo["id"]
        self.observe()
        site, _ = self.fixture.build(bases=release.bases(self.project))
        topics = [capacity.Topic(repo["id"], repo["github_name"]) for repo in self.project["repositories"]]
        initial = [replace(capacity.partition(topic, 0), sealed=True) for topic in topics]
        projected = capacity_projection.build(site, "a" * 64, "wiki-fixture", initial)
        self.assertGreater(audit(site, projected, "wiki-fixture")["relocated_pack_references"], 0)
        config = json.loads(projected.payloads["items/site/releases/" + "a" * 64 + ".json"].read())
        self.assertTrue(config["external_articles"]["path"].startswith("https://wiki-fixture.github.io/"))
        again = capacity_projection.build(site, "a" * 64, "wiki-fixture", projected.partitions, projected.placements)
        self.assertEqual(list(again.writes()), [])
        corrupted = deepcopy(config["external_articles"])
        corrupted["sha256"] = "f" * 64
        with self.assertRaises(AssertionError):
            compare(self.view(site), corrupted, lambda ref: self.assertEqual(ref["sha256"], config["external_articles"]["sha256"]))

    def test_route_validation_respects_topic_ownership_and_selected_sources(self):
        for mutate in (lambda o: o["routes"].update(unknown=o["routes"]["items"]),
                       lambda o: o["routes"]["items"]["entity_prefixes"].update(creature=[test_external_links.PREFIX]),
                       lambda o: o["routes"]["items"]["entity_prefixes"].update(item=["Human Host:Elsewhere"]),
                       lambda o: o.update(cache_seconds=True)):
            project = deepcopy(self.project)
            mutate(project["external_articles"])
            with self.assertRaises(ContractError):
                external_links.configuration(project)

    def test_provider_failure_does_not_stop_pipeline_and_reaches_final_operator_report(self):
        f = test_pipeline.PipelineTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        project = deepcopy(test_pipeline.test_extraction.PROJECT)
        project["external_articles"] = options("items-equipment")
        provider = test_external_links.Provider()
        provider.failure = mediawiki.RemoteError("offline")
        with patch.object(mediawiki, "Client", return_value=provider):
            result = test_pipeline.pipeline.run(f.root, project, f.source)
        saved = test_pipeline.pipeline.read(f.root, result["run_id"])
        self.assertIn("release", saved["completed"])
        self.assertFalse(saved["completed"]["external-articles"]["inventory_complete"])
        report = test_pipeline.pipeline.operator_report(f.root, result)
        self.assertIn("External article index unavailable", report)
        self.assertIn("ask how to proceed", report)


if __name__ == "__main__":
    unittest.main()
