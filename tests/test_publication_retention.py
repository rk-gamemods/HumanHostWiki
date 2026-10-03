"""Publication history remains readable after release-stage retention."""

import subprocess
import unittest

from tests import test_release_retention
from wikibuild import publication, release, release_retention
from wikibuild.storage import digest, json_bytes


class PublicationRetentionTests(unittest.TestCase):
    def setUp(self):
        fixture = test_release_retention.RetentionTests()
        fixture.addCleanup = self.addCleanup
        fixture.setUp()
        self.root, self.repo = fixture.root, fixture.repo
        self.plan, self.payloads = fixture.plan, fixture.payloads

    def test_published_and_latest_unpublished_manifests_and_objects_survive_retention(self):
        published = self.plan["result"]
        newest = {**published, "inputs": {"test": "awaiting-publication"}}
        newest["release_id"] = digest(json_bytes(newest["inputs"]))
        newest.pop("manifest_sha256")
        newest["manifest_sha256"] = digest(json_bytes(newest))
        (self.root / "releases" / (newest["release_id"] + ".json")).write_bytes(json_bytes(newest))
        (self.root / "releases/latest.json").write_bytes(json_bytes({"release_id": newest["release_id"]}))
        publication.save(self.root / "publications/latest.json", {"release_id": published["release_id"]})
        publication.save(self.root / "publications" / (published["release_id"] + ".json"), published)
        before = {path: path.read_bytes() for folder in ("releases", "publications")
                  for path in (self.root / folder).glob("*.json")}
        self.assertGreater(release_retention.run(self.root)["removed_files"], 0)
        self.assertTrue(release_retention.run(self.root)["reused"])
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)
        for manifest in (published, newest):
            self.assertEqual(release.read(self.root, manifest["release_id"]), manifest)
            for name, data in self.payloads.items():
                self.assertEqual(subprocess.check_output(["git", "-C", str(self.repo), "show",
                                                         manifest["repositories"]["topic"]["commit"] + ":" + name],
                                                        timeout=120), data)


if __name__ == "__main__":
    unittest.main()
