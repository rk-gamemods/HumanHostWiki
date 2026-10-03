"""Availability is independently observed, cached, and never grants verification."""

from datetime import datetime, timedelta, timezone
import json
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tests._support import fixture_dir

from wikibuild import availability, manifest, reader, steam_build
from wikibuild.storage import ContractError, json_bytes
import test_reader
import test_pipeline


APP_INFO = '''Steam Console Client
Connecting anonymously to Steam Public...OK
"2393970"
{
 "common" { "name" "Human Host" }
 "depots" {
  "2393972" { "manifests" { "public" { "gid" "8060226703539543058" } } }
  "branches" {
   "public" { "buildid" "25548639" "timeupdated" "1790435702" }
   "prior_working_version" { "buildid" "25148022" "timeupdated" "1788663913" }
  }
 }
}
Unloading Steam API...OK
'''


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "avail")
        self.project = {"availability": {"enabled": True, "cache_seconds": 3600, "retry_seconds": 60}}
        self.steam = {"app_id": "2393970", "build_id": "25548639", "branch": "public"}
        self.now = datetime(2026, 9, 27, 9, tzinfo=timezone.utc)
        settings = self.root / ".local/steamcmd.json"
        settings.parent.mkdir(parents=True)
        settings.write_bytes(json_bytes({"executable": "fixture-steamcmd"}))
        self.fetch = Mock(return_value={**steam_build.parse(APP_INFO, "2393970", "public"),
                                       "source": "steamcmd-app-info", "response_sha256": "a" * 64})

    def refresh(self, seconds=0, **kwargs):
        return availability.refresh(self.root, self.project, self.steam,
                                    now=self.now + timedelta(seconds=seconds), fetch=self.fetch, **kwargs)

    def test_public_metadata_uses_exact_branch_and_manifest(self):
        value = steam_build.parse(APP_INFO, "2393970", "public")
        self.assertEqual(value["build_id"], "25548639")
        self.assertEqual(value["depot_manifests"], {"2393972": "8060226703539543058"})
        expanded = APP_INFO.replace('"common" { "name" "Human Host" }', '"common" {' +
            " ".join(f'"field{i}" "unused"' for i in range(10000)) + '}')
        self.assertEqual(steam_build.parse(expanded, "2393970", "public"), value)
        old = steam_build.parse(APP_INFO, "2393970", "prior_working_version")
        self.assertEqual(old["build_id"], "25148022")
        for text, app, branch in [(APP_INFO, "1", "public"), (APP_INFO, "2393970", "missing"),
                                   (APP_INFO.replace('"25548639"', '"unknown"'), "2393970", "public"),
                                   (APP_INFO.replace('"common"', 'garbage "common"'), "2393970", "public"),
                                   (APP_INFO[:APP_INFO.rfind('}')], "2393970", "public"),
                                   (APP_INFO.replace('"buildid" "25548639"', '"buildid" "1" "buildid" "2"'), "2393970", "public")]:
            with self.subTest(app=app, branch=branch, text=text):
                with self.assertRaises(ContractError):
                    steam_build.parse(text, app, branch)

    def test_process_output_limit_failure_and_anonymous_session_are_checked(self):
        client = self.root / "steamcmd.exe"
        client.write_bytes(b"fixture")
        for output, status, error in [(APP_INFO.encode(), 1, "exited"),
                (APP_INFO.replace("Connecting anonymously to Steam Public...OK", "").encode(), 0, "anonymous"),
                (b"x" * (steam_build.MAX_OUTPUT + 1), 0, "exceeds")]:
            process = Mock(stdout=io.BytesIO(output))
            process.wait.return_value = status
            with patch.object(steam_build.subprocess, "Popen", return_value=process), \
                    patch.object(steam_build.bounded, "kill_tree") as kill:
                with self.assertRaisesRegex(ContractError, error):
                    steam_build.fetch(client, "2393970", "public")
            if error == "exceeds":
                kill.assert_called_once_with(process)

    def test_repeat_is_byte_stable_and_expired_observation_is_replaced(self):
        first, metrics = self.refresh()
        self.assertFalse(metrics["reused"])
        pointer = self.root / "availability/latest.json"
        before = pointer.read_bytes(), pointer.stat().st_mtime_ns
        second, metrics = self.refresh(1)
        self.assertEqual(first, second)
        self.assertTrue(metrics["reused"])
        self.assertEqual(before, (pointer.read_bytes(), pointer.stat().st_mtime_ns))
        self.assertEqual(self.fetch.call_count, 1)
        third, _ = self.refresh(3600)
        self.assertNotEqual(first["checked_at"], third["checked_at"])
        self.assertEqual(len(list((self.root / "availability").glob("*.json"))), 3)
        self.assertEqual(self.fetch.call_count, 2)

    def test_failed_check_is_unknown_preserves_evidence_and_retries(self):
        first, _ = self.refresh()
        self.fetch.side_effect = OSError("private machine path")
        failed, _ = self.refresh(3600)
        self.assertEqual(failed["status"], "unavailable")
        self.assertNotIn("private", json.dumps(failed))
        self.assertIn("unknown", availability.describe(failed, self.steam))
        self.assertTrue(self.refresh(3601)[1]["reused"])
        self.fetch.side_effect = None
        retry, _ = self.refresh(3660)
        self.assertEqual(retry["status"], "observed")
        self.assertEqual(self.fetch.call_count, 3)
        self.assertIn(first, [json.loads(path.read_bytes()) for path in (self.root / "availability").glob("*.json")])

    def test_branch_clock_and_content_integrity_invalidate_cache(self):
        self.refresh()
        self.refresh(-1)
        self.assertEqual(self.fetch.call_count, 2)
        self.steam["branch"] = "prior_working_version"
        self.assertEqual(self.refresh()[0]["status"], "unavailable")
        pointer = json.loads((self.root / "availability/latest.json").read_bytes())
        path = self.root / "availability" / (pointer["observation_id"] + ".json")
        value = json.loads(path.read_bytes())
        value["status"] = "observed"
        path.write_bytes(json_bytes(value))
        with self.assertRaisesRegex(ContractError, "modified"):
            self.refresh()

    def test_descriptions_never_claim_gameplay_verification(self):
        value, _ = self.refresh()
        self.assertIn("matches", availability.describe(value, self.steam))
        self.assertIn("awaiting", availability.describe(value, {**self.steam, "build_id": "1"}))
        self.assertNotIn("matches", availability.describe(value, {**self.steam, "branch": "beta"}))

    def test_configuration_rejects_unbounded_or_ambiguous_settings(self):
        project = json.loads(json.dumps(test_pipeline.test_extraction.PROJECT))
        for options in [{"enabled": "yes"}, {"cache_seconds": 0}, {"retry_seconds": True},
                        {"cache_seconds": 86401}, {"command": "unreviewed hook"}]:
            with self.subTest(options=options):
                project["availability"] = options
                with self.assertRaises(ContractError):
                    manifest.validate(self.root, project)

    def test_freshness_change_reuses_projection_and_hardlinks_immutable_packs(self):
        fixture = test_reader.ReaderTests()
        fixture.addCleanup = self.addCleanup
        fixture.setUp()
        self.root = fixture.root
        fixture.project.update(self.project)
        settings = self.root / ".local/steamcmd.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_bytes(json_bytes({"executable": "fixture"}))
        self.refresh()
        first, result = fixture.build()
        first_manifest = reader.verify(first)
        self.refresh(3600)
        with patch.object(reader, "project_snapshot", side_effect=AssertionError("Models were projected again")):
            second, result = fixture.build()
        self.assertTrue(result["projection_reused"])
        second_manifest = reader.verify(second)
        self.assertEqual(first_manifest["versions"], second_manifest["versions"])
        linked = 0
        for name, record in first_manifest["files"].items():
            if "/data/" in name or "/snapshots/" in name:
                self.assertEqual(record, second_manifest["files"][name])
                self.assertTrue((first / name).samefile(second / name))
                linked += 1
        self.assertGreater(linked, 0)
        self.assertTrue(fixture.build()[1]["reused"])
        config = json.loads((second / "items/reader.json").read_bytes())
        self.assertEqual(config["availability"]["checked_at"], (self.now + timedelta(hours=1)).isoformat(timespec="seconds"))
        self.assertIsNone(fixture.index(second, "items", fixture.new)["latest_available_build"])

    def test_unavailable_check_does_not_block_supported_pipeline_or_hide_exceptions(self):
        fixture = test_pipeline.PipelineTests()
        fixture.addCleanup = self.addCleanup
        fixture.setUp()
        project = json.loads(json.dumps(test_pipeline.test_extraction.PROJECT))
        project.update(self.project)
        result = test_pipeline.pipeline.run(fixture.root, project, fixture.source)
        saved = test_pipeline.pipeline.read(fixture.root, result["run_id"])
        self.assertEqual(saved["completed"]["availability"]["status"], "unavailable")
        self.assertIn("release", saved["completed"])
        self.assertIn("Latest available build unknown", test_pipeline.pipeline.operator_report(fixture.root, result))


if __name__ == "__main__":
    unittest.main()
