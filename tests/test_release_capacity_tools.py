"""Capacity diagnostic entry points consume a real committed fixture release."""

import json
import os
from pathlib import Path
import shutil
import sys
import unittest

import test_reader
import test_release
from tests._support import cache_git_queries
from wikibuild import bounded, reader, release, workspace
from wikibuild.storage import digest, json_bytes


class CapacityToolTests(unittest.TestCase):
    def setUp(self):
        fixture = test_reader.ReaderTests()
        fixture.addCleanup = self.addCleanup
        fixture.setUp()
        self.root, self.project = fixture.root, fixture.project
        cache_git_queries(self, self.root)
        runs = fixture.runs
        if self._testMethodName == "test_projection_main_succeeds_on_committed_fixture":
            observations = []
            for number in range(24):
                observation = fixture.observation("e-" + f"{number:032x}", f"Item {number}")
                observation["semantic"]["facts"]["nested"]["field"] = "x" * 24000
                observation["revision_id"] = digest(json_bytes(observation["semantic"]))
                observations.append(observation)
            runs = [fixture.make_run("300", observations), *runs]
        self.project.update(schema_version=1, language="en", github_owner="wiki-fixture",
                            source={"steam_app_id": "2393970", "catalog_schema": 1},
                            publication={"visibility": "public", "monetized": False,
                                         "advertising": False, "host": "github-pages"},
                            relationships=[], pipeline=self.declared_pipeline())
        self.project["repositories"][0]["owns"] = ["navigation"]
        self.project["repositories"].append({"id": "technical-reference", "title": "Technical",
                                             "owns": ["unclassified"], "coverage": "Unclassified assets"})
        for repo in self.project["repositories"]:
            repo.update(path="repositories/" + repo["id"], github_name="Wiki-" + repo["id"],
                        role="hub" if repo["id"] == "hub" else "topic")
        (self.root / "project.json").write_bytes(json_bytes(self.project))
        test_release.copy_children(self.root, self.project)
        workspace.checkout_lock(self.root, self.project)
        candidate = reader.build(self.root, self.project, runs, bases=release.bases(self.project),
                                 max_pack_bytes=100000)
        self.manifest = release.run(self.root, self.project, candidate)[0]

    @staticmethod
    def declared_pipeline():
        # Manifest validation requires the declared stage graph to match pipeline.run.
        project = json.loads((Path(__file__).resolve().parents[1] / "project.json").read_text(encoding="utf-8"))
        return project["pipeline"]

    def run_tool(self, name, *, small_budget=False):
        repository = Path(__file__).resolve().parents[1]
        folder = self.root / "tools"
        folder.mkdir()
        script = folder / name
        shutil.copyfile(repository / "tools" / name, script)
        command = [sys.executable, str(script)]
        if small_budget:
            # Scale only the diagnostic's explicit forced budget. Record
            # validation and unchanged projection retain production limits.
            command = [sys.executable, "-c",
                       "import runpy, sys; from wikibuild import capacity; factory = capacity.Budgets; "
                       "small = factory(file_bytes=150000, site_bytes=600000, history_bytes=1200000, "
                       "site_reserve_bytes=128*1024, history_reserve_bytes=128*1024); "
                       "capacity.Budgets = lambda **kwargs: small if kwargs.get('site_bytes') == "
                       "2*capacity.MIB else factory(**kwargs); "
                       "runpy.run_path(sys.argv[1], run_name='__main__')", str(script)]
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
            str(repository), environment.get("PYTHONPATH"))))
        # The entry points read four real Git checkouts and project reader bytes.
        result = bounded.run(command, cwd=self.root, env=environment, timeout=120)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))
        return json.loads(result.stdout)

    def test_capacity_main_succeeds_on_committed_fixture(self):
        report = self.run_tool("check_capacity.py")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["release_id"], self.manifest["release_id"])
        self.assertGreater(report["immutable_objects"], 0)
        self.assertEqual(report["replay_new_partitions"], 0)

    def test_projection_main_succeeds_on_committed_fixture(self):
        report = self.run_tool("check_capacity_projection.py", small_budget=True)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["release_id"], self.manifest["release_id"])
        self.assertGreater(report["forced_new_partitions"], 0)
        self.assertGreater(report["forced"]["relocated_pack_references"], 0)
        self.assertEqual(report["replay_new_writes"], 0)


if __name__ == "__main__":
    unittest.main()
