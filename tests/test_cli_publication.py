"""Publication CLI boundaries use synthetic gate fixtures without network."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import wiki
from tests import test_publish_gate
from wikibuild import publication, publish_gate
from wikibuild.storage import ContractError


class PublicationCliTests(unittest.TestCase):
    def setUp(self):
        fixture = test_publish_gate.PublishGateTests()
        fixture.addCleanup = self.addCleanup
        fixture.setUp()
        self.root, self.project = fixture.root, fixture.project
        self.manifest, self.host = fixture.manifest, fixture.host

    def test_abandon_entrypoint_archives_locally_then_next_publish_reaches_gate(self):
        path = self.root / ".local/publication/pending.json"
        publication.save(path, {"phase": "hub", "release_id": self.manifest["release_id"]})
        before = path.read_bytes()
        with patch.object(wiki.manifest, "load", return_value=self.project):
            result = wiki.run(self.root, SimpleNamespace(command="abandon-publication"))
        archive = self.root / result["archive"]
        self.assertEqual((archive / "pending.json").read_bytes(), before)
        self.assertTrue((archive / "README.md").is_file())
        self.assertFalse(path.exists())
        self.assertEqual(publication.abandon(self.root)["status"], "nothing-to-abandon")
        self.assertEqual(self.host.method_calls, [])
        with patch.object(publish_gate, "check", side_effect=ContractError("reached fresh gate")) as gate:
            with self.assertRaisesRegex(ContractError, "reached fresh gate"):
                publication.run(self.root, self.project, self.manifest)
            gate.assert_called_once()

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
