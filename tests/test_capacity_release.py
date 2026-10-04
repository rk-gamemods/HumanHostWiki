"""Forced physical allocation through real Git release and publication adapters."""

import json
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import test_publication
import test_release
from tools.check_release import check
from wikibuild import capacity_inventory, ownership, physical, publication, reader, release, release_partitions, shard_index, workspace
from wikibuild.storage import ContractError, git, json_bytes

_CAPACITY_TEMPLATE = None
_CAPACITY_PREPARED = None


class CapacityReleaseTests(unittest.TestCase):
    def setUp(self):
        global _CAPACITY_TEMPLATE, _CAPACITY_PREPARED
        if self._testMethodName in {
                'test_forced_capacity_commits_provisions_dependencies_and_repeats_without_new_work',
                'test_storage_failure_keeps_all_fronts_unpublished_then_resumes',
                'test_next_release_preserves_historical_partition_bytes_and_lock_membership',
                'test_paged_ownership_commits_publishes_and_preserves_prior_release_reads',
                'test_interrupted_partition_install_resumes_prepared_repositories'}:
            if _CAPACITY_TEMPLATE is None or not _CAPACITY_TEMPLATE.root.exists():
                template = CapacityReleaseTests()
                template.addCleanup = test_release._ModuleFixtures().addCleanup
                template.setUp()
                with patch.object(ownership, 'PAGE_BYTES', 4096):
                    with patch.object(release_partitions, 'install',
                                      side_effect=test_release._FixtureCheckpoint('prepared capacity fixture')):
                        try:
                            template.run_release()
                        except test_release._FixtureCheckpoint:
                            pass
                        else:
                            raise AssertionError('Capacity fixture did not stop before install')
                    _CAPACITY_PREPARED = test_release.clone_fixture(
                        test_release._ModuleFixtures(), template.fixture, 'cap-plan')
                    template.run_release()
                _CAPACITY_TEMPLATE = template
            if self._testMethodName == 'test_interrupted_partition_install_resumes_prepared_repositories':
                self.fixture = test_release.clone_fixture(self, _CAPACITY_PREPARED, 'cap-retry')
                self.root, self.project, self.candidate = self.fixture.root, self.fixture.project, self.fixture.candidate
                self.host = test_publication.Host(self.project['github_owner'])
                self.host.install_gate(self)
                return
            template = _CAPACITY_TEMPLATE
            self.fixture = test_release.clone_fixture(self, template.fixture, 'capacity')
            self.root, self.project = self.fixture.root, self.fixture.project
            self.candidate = copy.deepcopy(template.candidate)
            self.candidate['path'] = str(self.root / Path(template.candidate['path']).relative_to(template.root))
            self.host = test_publication.Host(self.project['github_owner'])
            self.host.install_gate(self)
            return
        self.fixture = test_release.ReleaseTests()
        self.fixture.addCleanup = self.addCleanup
        self.fixture.setUp(build_candidate=False)
        self.fixture.fixture.runs = [self.fixture.fixture.new]
        self.root, self.project = self.fixture.root, self.fixture.project
        self.project["capacity"] = {"file_bytes": 150_000, "site_bytes": 535_000, "history_bytes": 650_000,
                                    "site_reserve_bytes": 30_000, "history_reserve_bytes": 30_000}
        self.project["publication"] = {"enabled": True, "workers": 2}
        self.host = test_publication.Host(self.project["github_owner"])
        self.host.install_gate(self)
        workspace.checkout_lock(self.root, self.project)
        self.candidate = reader.build(self.root, self.project, self.fixture.fixture.runs, bases=release.bases(self.project))
        self.fixture.candidate = self.candidate

    def run_release(self):
        return release.run(self.root, self.project, self.candidate)

    def test_forced_capacity_commits_provisions_dependencies_and_repeats_without_new_work(self):
        result, _ = self.run_release()
        self.assertTrue(result["capacity"]["new_repositories"])
        self.assertGreater(len(result["repositories"]), len(self.project["repositories"]))
        audit = check(self.root)
        self.assertEqual(audit["historical_configs"], len(self.project["repositories"]))
        workspace.checkout_lock(self.root, self.project, check=True)
        inventory = release.inventory(self.root, self.project)
        self.assertEqual(len(inventory.partitions), len(result["repositories"]))
        for repo in result["repositories"].values():
            self.assertLessEqual(repo["site_bytes"], self.project["capacity"]["site_bytes"])
            self.assertLessEqual(repo["history_bytes"], self.project["capacity"]["history_bytes"])
        public, _ = publication.run(self.root, self.project, result, host=self.host)
        storage = [repo["github_name"] for repo in physical.repositories(self.project, result["physical"]) if repo["role"] == "partition"]
        fronts = [repo["github_name"] for repo in self.project["repositories"]]
        for name in storage:
            verified = self.host.events.index(("verified", name))
            for front in fronts:
                self.assertLess(verified, next(i for i, event in enumerate(self.host.events) if event[:3] == ("push", front, "gh-pages")))
        events = list(self.host.events)
        self.assertTrue(self.run_release()[1]["reused"])
        self.assertTrue(publication.run(self.root, self.project, result, host=self.host)[1]["reused"])
        self.assertEqual([event for event in events if event[0] in {"create", "push"}],
                         [event for event in self.host.events if event[0] in {"create", "push"}])

    def test_interrupted_partition_install_resumes_prepared_repositories(self):
        original = release_partitions.install
        interrupted = False

        def fail_after_install(*args):
            nonlocal interrupted
            original(*args)
            if not interrupted:
                interrupted = True
                raise OSError("after partition install")

        with patch.object(release_partitions, "install", side_effect=fail_after_install):
            with self.assertRaisesRegex(OSError, "after partition"):
                self.run_release()
        self.assertFalse((self.root / "releases/latest.json").exists())
        pointer = json.loads((self.root / ".local/releases/pending.json").read_bytes())
        journal = json.loads((self.root / pointer["stage"] / "plan.json").read_bytes())
        expected = {key: value["git"]["commit"] for key, value in journal["plans"].items()}
        result, _ = self.run_release()
        self.assertEqual(expected, {key: value["commit"] for key, value in result["repositories"].items()})
        check(self.root)

    def test_paged_captures_commit_publish_and_remain_reachable_after_replay(self):
        self.enterContext(patch.object(shard_index, "PAGE_BYTES", 2048))
        runs = [self.fixture.fixture.make_run(str(build), []) for build in reversed(range(1000, 1008))]
        self.candidate = reader.build(self.root, self.project, runs, bases=release.bases(self.project))
        result, _ = self.run_release()
        inventory = release.inventory(self.root, self.project)
        catalogs = []
        for item in inventory.stored:
            if item.artifact.path.startswith("site/releases/"):
                path = self.root / result["repositories"][item.partition]["path"] / item.artifact.path
                catalogs.append(json.loads(path.read_bytes()))
        self.assertEqual(len(catalogs), 3)
        self.assertTrue(all("capture_catalog" in value for value in catalogs))
        self.assertEqual(check(self.root)["historical_configs"], 3)
        self.assertEqual(publication.run(self.root, self.project, result, host=self.host)[0]["status"], "published")
        before = {identity: value["commit"] for identity, value in result["repositories"].items()}
        repeated, stats = self.run_release()
        self.assertTrue(stats["reused"])
        self.assertEqual(before, {identity: value["commit"] for identity, value in repeated["repositories"].items()})

    def test_storage_failure_keeps_all_fronts_unpublished_then_requires_abandonment(self):
        result, _ = self.run_release()
        identity = next(repo["id"] for repo in physical.repositories(self.project, result["physical"])
                        if repo["role"] == "partition" and repo["id"] in result["capacity"]["new_repositories"])
        self.host.fail_name = result["repositories"][identity]["github_name"]
        with self.assertRaisesRegex(ContractError, "Storage publication failed"):
            publication.run(self.root, self.project, result, host=self.host)
        for repo in self.project["repositories"]:
            self.assertIsNone(self.host.ref(repo["github_name"], "gh-pages"))
        with self.assertRaisesRegex(ContractError, "abandon-publication"):
            publication.run(self.root, self.project, result, host=self.host)
        publication.abandon(self.root)
        refs = dict(self.host.refs)
        with self.assertRaisesRegex(ContractError, "Unexpected remote Pages branch"):
            publication.run(self.root, self.project, result, host=self.host)
        self.assertEqual(self.host.refs, refs)

    def test_next_release_preserves_historical_partition_bytes_and_lock_membership(self):
        first, _ = self.run_release()
        publication.run(self.root, self.project, first, host=self.host)
        stored = release.inventory(self.root, self.project).stored
        before = {(item.partition, item.artifact.path): (self.root / first["repositories"][item.partition]["path"] / item.artifact.path).read_bytes()
                  for item in stored}
        self.project["official_links"] = [{"title": "Changed", "url": "https://example.invalid/"}]
        workspace.checkout_lock(self.root, self.project)
        self.candidate = reader.build(self.root, self.project, self.fixture.fixture.runs, bases=release.bases(self.project))
        second, _ = self.run_release()
        self.assertEqual(check(self.root)["historical_configs"], 2 * len(self.project["repositories"]))
        for (identity, name), data in before.items():
            self.assertEqual((self.root / second["repositories"][identity]["path"] / name).read_bytes(), data)
        workspace.checkout_lock(self.root, self.project, check=True)
        publication.run(self.root, self.project, second, host=self.host)
        for identity in first["capacity"]["new_repositories"]:
            if first["repositories"][identity]["files_sha256"] == second["repositories"][identity]["files_sha256"]:
                self.assertEqual(first["repositories"][identity]["commit"], second["repositories"][identity]["commit"])

    def test_paged_ownership_commits_publishes_and_preserves_prior_release_reads(self):
        # Force only the metadata-page threshold. Runtime objects still obey
        # the independently configured 150,000-byte physical file budget.
        with patch.object(ownership, "PAGE_BYTES", 4096):
            first, _ = self.run_release()
            audit = check(self.root)
            self.assertGreater(audit["ownership_pages"], 0)
            prior_sites = {topic: publication.site_files(self.root, record)
                           for topic, record in first["repositories"].items()}
            publication.run(self.root, self.project, first, host=self.host)
            self.project["official_links"] = [{"title": "Fixture revision", "url": "https://example.invalid/"}]
            workspace.checkout_lock(self.root, self.project)
            self.candidate = reader.build(self.root, self.project, self.fixture.fixture.runs, bases=release.bases(self.project))
            second, _ = self.run_release()
            self.assertGreater(check(self.root)["ownership_pages"], 0)
            self.assertEqual(check(self.root)["historical_configs"], 6)
            for topic, record in first["repositories"].items():
                self.assertEqual(publication.site_files(self.root, record), prior_sites[topic])
            self.assertEqual(publication.run(self.root, self.project, second, host=self.host)[0]["status"], "published")
            self.assertTrue(self.run_release()[1]["reused"])
            release.inventory(self.root, self.project)

    def test_final_prepared_size_failure_preserves_all_existing_checkouts(self):
        before = self.fixture.heads()
        measure = capacity_inventory.history_size

        def overflow(path, refs):
            result = measure(path, refs)
            if len(refs) == 2:  # Prepared source + Pages, after real measurement.
                result["history_bytes"] = self.project["capacity"]["history_bytes"] + 1
            return result

        with patch.object(capacity_inventory, "history_size", side_effect=overflow):
            with self.assertRaisesRegex(ContractError, "exceeds capacity after"):
                self.run_release()
        self.assertEqual(before, self.fixture.heads())
        self.assertFalse((self.root / "releases/latest.json").exists())
        self.assertFalse((self.root / ".local/releases/pending.json").exists())
        self.assertEqual(set(path.name for path in (self.root / "repositories").iterdir()),
                         {repo["id"] for repo in self.project["repositories"]})


if __name__ == "__main__":
    unittest.main()
