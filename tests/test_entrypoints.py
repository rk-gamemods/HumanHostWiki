"""Front generations preserve public history and publish their successors first."""

import json
import unittest
from unittest.mock import patch

import test_publication
import test_release
from tools.check_release import check
from wikibuild import capacity, entrypoints, physical, publication, reader, release, release_partitions, workspace
from wikibuild.storage import ContractError, git


class EntrypointPlanTests(unittest.TestCase):
    def test_rollover_seals_only_current_front_and_keeps_all_locations(self):
        topics = (capacity.Topic("hub", "Wiki-hub"), capacity.Topic("items", "Wiki-items"))
        parts = (capacity.partition(topics[0], 0), capacity.partition(topics[1], 0), capacity.partition(topics[1], 1))
        proposed = entrypoints.rollover(parts, topics, {"items"})
        self.assertEqual(entrypoints.active(proposed), {"hub": "hub", "items": "items-part-0002"})
        self.assertFalse(parts[1].sealed)
        self.assertTrue(proposed[1].sealed)
        self.assertEqual(proposed[2], parts[2])
        plan = capacity.allocate(topics, proposed, (), [capacity.Artifact("items", "site/data/" + "a" * 64 + ".json", "a" * 64, 1)])
        self.assertEqual(plan.placements[0].partition, "items-part-0001")
        with self.assertRaisesRegex(ContractError, "Multiple active"):
            entrypoints.active((*parts, proposed[-1]))
        with self.assertRaisesRegex(ContractError, "no active"):
            entrypoints.active(proposed[:-1])

    def test_configured_names_are_skipped_without_changing_their_owner(self):
        topics = (capacity.Topic("items", "Wiki-items"), capacity.Topic("items-part-0001", "Wiki-items-Part-0001"))
        parts = tuple(capacity.partition(topic, 0) for topic in topics)
        proposed = entrypoints.rollover(parts, topics, {"items"})
        self.assertEqual(entrypoints.active(proposed)["items"], "items-part-0002")
        self.assertEqual(proposed[1], parts[1])


class EntrypointReleaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_release.ReleaseTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.setUp(build_candidate=False)
        self.fixture.fixture.runs = [self.fixture.fixture.new]
        self.root, self.project = self.fixture.root, self.fixture.project
        self.project["publication"] = {"enabled": True, "workers": 2}
        self.host = test_publication.Host(self.project["github_owner"])
        gate = patch.object(publication.publish_gate, "check", side_effect=self.host.gate)
        gate.start()
        self.addCleanup(gate.stop)

    def make(self, title):
        self.project["official_links"] = [{"title": title, "url": "https://example.invalid/"}]
        workspace.checkout_lock(self.root, self.project)
        candidate = reader.build(self.root, self.project, self.fixture.fixture.runs, bases=release.bases(self.project))
        self.fixture.candidate = candidate
        return candidate, release.run(self.root, self.project, candidate)[0]

    def force_next_fronts(self):
        _, first = self.make("First")
        published, _ = publication.run(self.root, self.project, first, host=self.host)
        inventory = release.inventory(self.root, self.project)
        sizes = [part.history_bytes for part in inventory.partitions]
        soft, hard = min(sizes) - 1, max(sizes) + 65536
        self.project["capacity"] = {"file_bytes": 30000, "history_bytes": hard, "history_reserve_bytes": hard - soft}
        return first, published

    def test_real_size_rollover_interrupt_retry_publication_failure_and_frozen_replay(self):
        first, published = self.force_next_fronts()
        retained = {(identity, name): git(self.root / record["path"], "show", record["commit"] + ":" + name)
                    for identity, record in first["repositories"].items()
                    for name in ("site/releases/" + first["release_id"] + ".json",)}
        before = (self.root / "releases/latest.json").read_bytes()
        install = release_partitions.install
        interrupted = False

        def fail_after_install(*args):
            nonlocal interrupted
            install(*args)
            if not interrupted:
                interrupted = True
                raise OSError("entrypoint installed before interruption")

        with patch.object(release_partitions, "install", side_effect=fail_after_install):
            with self.assertRaisesRegex(OSError, "entrypoint installed"):
                self.make("Second")
        self.assertEqual((self.root / "releases/latest.json").read_bytes(), before)
        pointer = json.loads((self.root / ".local/releases/pending.json").read_bytes())
        journal = json.loads((self.root / pointer["stage"] / "plan.json").read_bytes())
        candidate = {"path": str(self.root / ".local/readers" / journal["result"]["reader_candidate"][:24]),
                     "candidate_id": journal["result"]["reader_candidate"]}
        second, _ = release.run(self.root, self.project, candidate)
        self.assertEqual(second["capacity"]["rolled_topics"], ["hub", "items", "loot"])
        self.assertEqual({k: v["commit"] for k, v in second["repositories"].items()},
                         {k: v["git"]["commit"] for k, v in journal["plans"].items()})
        self.assertEqual(check(self.root)["historical_configs"], 6)
        for (identity, name), data in retained.items():
            self.assertEqual(git(self.root / first["repositories"][identity]["path"], "show", "HEAD:" + name), data)
        for topic, identity in second["entrypoints"].items():
            self.assertNotEqual(topic, identity)
            self.assertTrue(second["physical"][topic]["sealed"])
            self.assertTrue(second["physical"][identity]["entrypoint"])
        workspace.checkout_lock(self.root, self.project, check=True)

        replacement = second["entrypoints"]["items"]
        confirmed_refs = dict(self.host.refs)
        self.host.fail_name = second["repositories"][replacement]["github_name"]
        with self.assertRaisesRegex(ContractError, "Topic publication failed"):
            publication.run(self.root, self.project, second, host=self.host)
        self.assertEqual(self.host.ref("Wiki-hub", "gh-pages"), published["repositories"]["hub"]["pages"])
        self.assertEqual(self.host.ref("Wiki-items", "gh-pages"), published["repositories"]["items"]["pages"])
        publication.abandon(self.root)
        with self.assertRaisesRegex(ContractError, "Unexpected remote Pages branch"):
            publication.run(self.root, self.project, second, host=self.host)
        # Later failure scenarios start from the confirmed fake remote state.
        # Abandonment itself never restores or adopts unconfirmed history.
        self.host.refs = dict(confirmed_refs)
        self.host.fail_name = "Wiki-hub"
        with self.assertRaisesRegex(ContractError, "Injected public"):
            publication.run(self.root, self.project, second, host=self.host)
        pending = publication.load(self.root / ".local/publication/pending.json")
        self.assertEqual(pending["phase"], "rolled-back")
        publication.abandon(self.root)
        self.host.refs = dict(confirmed_refs)
        public, _ = publication.run(self.root, self.project, second, host=self.host)
        self.assertEqual(public["entrypoints"], second["entrypoints"])
        new_hub = second["repositories"][second["entrypoints"]["hub"]]["github_name"]
        hub_update = next(i for i, event in enumerate(self.host.events) if event[:3] == ("push", "Wiki-hub", "gh-pages") and event[3] != published["repositories"]["hub"]["pages"])
        self.assertLess(self.host.events.index(("verified", new_hub)), hub_update)
        frozen = {topic: second["repositories"][topic]["commit"] for topic in second["entrypoints"]}
        _, third = self.make("Third")
        self.assertEqual(third["entrypoints"], second["entrypoints"])
        self.assertEqual(frozen, {topic: third["repositories"][topic]["commit"] for topic in frozen})
        self.assertEqual(check(self.root)["historical_configs"], 9)
        self.assertEqual(publication.run(self.root, self.project, third, host=self.host)[0]["status"], "published")
        self.assertTrue(publication.run(self.root, self.project, third, host=self.host)[1]["reused"])
        # Roll again from a generated front. The hub control identity now lives
        # in a partition repository, while canonical URLs still name ordinal 0.
        inventory = release.inventory(self.root, self.project)
        active = set(third["entrypoints"].values())
        soft = min(part.history_bytes for part in inventory.partitions if part.id in active) - 1
        hard = max(part.history_bytes for part in inventory.partitions) + 65536
        self.project["capacity"] = {"file_bytes": min(8000, soft), "history_bytes": hard, "history_reserve_bytes": hard - soft}
        _, fourth = self.make("Fourth")
        self.assertEqual(fourth["capacity"]["rolled_topics"], ["hub", "items", "loot"])
        self.assertTrue(all(fourth["entrypoints"][topic] != third["entrypoints"][topic] for topic in third["entrypoints"]))
        self.assertEqual(frozen, {topic: fourth["repositories"][topic]["commit"] for topic in frozen})
        self.assertEqual(check(self.root)["historical_configs"], 12)
        old_hub = third["entrypoints"]["hub"]
        confirmed_refs = dict(self.host.refs)
        self.host.fail_name = fourth["repositories"][old_hub]["github_name"]
        with self.assertRaisesRegex(ContractError, "Injected public"):
            publication.run(self.root, self.project, fourth, host=self.host)
        pending = publication.load(self.root / ".local/publication/pending.json")
        self.assertEqual((pending["hub_control"], pending["phase"]), (old_hub, "rolled-back"))
        publication.abandon(self.root)
        self.host.refs = dict(confirmed_refs)
        self.assertEqual(publication.run(self.root, self.project, fourth, host=self.host)[0]["status"], "published")


if __name__ == "__main__":
    unittest.main()
