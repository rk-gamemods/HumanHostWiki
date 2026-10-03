"""Commit-scoped Pages observations and elapsed budgets, without network calls."""

from email.message import Message
import io
import subprocess
import unittest
from unittest.mock import patch

from wikibuild import github_pages, mediawiki
from wikibuild.storage import ContractError


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class PagesStateTests(unittest.TestCase):
    def test_classifies_only_the_requested_commit(self):
        stale = {"id": 1, "name": "pages build and deployment", "head_sha": "old", "status": "queued"}
        queued = {**stale, "id": 2, "head_sha": "abc"}
        fixtures = [
            ("built", [{"commit": "abc", "status": "built"}], [stale], {}),
            ("building", [{"commit": "abc", "status": "building"}], [stale], {}),
            ("failed", [{"commit": "abc", "status": "errored"}], [stale], {}),
            ("queued-not-started", [], [stale, queued], {2: []}),
            ("building", [], [queued], {2: [{"status": "in_progress", "started_at": "2026-09-30"}]}),
            ("missing", [{"commit": "old", "status": "queued"}], [stale], {}),
        ]
        for state, builds, runs, jobs in fixtures:
            with self.subTest(state=state):
                self.assertEqual(github_pages.classify_pages_state("abc", builds, runs, jobs), state)

    def test_api_retry_stops_at_elapsed_deadline(self):
        clock = Clock()
        host = github_pages.GitHubPages("fixture")
        host.clock = clock
        timeouts = []

        def timeout(command, **kwargs):
            timeouts.append(kwargs["timeout"])
            clock.sleep(kwargs["timeout"])
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with patch.object(github_pages.bounded, "run", side_effect=timeout), \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaisesRegex(ContractError, "deadline"):
                host.api("GET", "repos/fixture/wiki", deadline=3)
        self.assertEqual(clock.now, 3)
        self.assertEqual(timeouts, [3])

    def test_all_queued_statuses_and_terminal_conclusions(self):
        run = {"id": 2, "head_sha": "abc", "name": "pages build and deployment"}
        for status in ("queued", "waiting", "pending"):
            with self.subTest(status=status):
                self.assertEqual(github_pages.classify_pages_state("abc", [], [{**run, "status": status}], {2: []}),
                                 "queued-not-started")
        for conclusion in ("failure", "cancelled", "timed_out", "action_required", "neutral", "skipped", "stale", "startup_failure"):
            with self.subTest(conclusion=conclusion):
                terminal = {**run, "status": "completed", "conclusion": conclusion}
                self.assertEqual(github_pages.classify_pages_state("abc", [{"commit": "abc", "status": "building"}], [terminal]), "failed")
        older = {**run, "id": 1, "status": "completed", "conclusion": "failure"}
        newer = {**run, "status": "queued"}
        self.assertEqual(github_pages.classify_pages_state("abc", [], [older, newer], {2: []}), "queued-not-started")

    def test_grace_applies_without_a_pages_build_record(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock, host.QUEUED_GRACE = clock, 10
        run = {"id": 2, "head_sha": "abc", "name": "pages build and deployment", "status": "waiting"}
        def api(method, path, **kwargs):
            self.assertEqual(kwargs["deadline"], 1800)
            if path.endswith("/latest"):
                return None
            if "/pages/builds?" in path:
                return []
            if "/actions/runs?" in path:
                return {"workflow_runs": [run]}
            return {"total_count": 0, "jobs": []}
        with patch.object(host, "api", side_effect=api), patch.object(host, "ref", return_value="abc"), \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaises(github_pages.QueuedPagesError) as exc:
                host.wait("wiki", "abc")
        self.assertEqual(clock.now, 10)
        self.assertEqual(exc.exception.deadline, 1800)

    def test_unrelated_stale_queued_run_never_triggers_recovery(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock, host.QUEUED_GRACE = clock, 10
        stale = {"id": 1, "head_sha": "old", "name": "pages build and deployment", "status": "queued"}
        def api(method, path, **kwargs):
            if path.endswith("/latest"):
                return {"commit": "old", "status": "queued"}
            if "/pages/builds?" in path:
                return [{"commit": "old", "status": "queued"}]
            return {"workflow_runs": [stale]}
        with patch.object(host, "api", side_effect=api) as calls, patch.object(host, "ref", return_value="abc"), \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaisesRegex(github_pages.BuildObservationError, "not observable after 12 checks") as exc:
                host.wait("wiki", "abc")
        self.assertNotIsInstance(exc.exception, github_pages.QueuedPagesError)
        self.assertTrue(all(call.args[0] == "GET" for call in calls.call_args_list))

    def test_building_record_does_not_hide_unstarted_jobs_and_grace_resets(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock, host.QUEUED_GRACE = clock, 10
        run = {"id": 2, "head_sha": "abc", "name": "pages build and deployment", "status": "queued"}
        def api(method, path, **kwargs):
            if "/actions/runs?" in path:
                return {"workflow_runs": [run]}
            if "/jobs?" in path:
                jobs = [{"status": "in_progress", "started_at": "started"}] if 5 <= clock.now < 15 else []
                return {"total_count": len(jobs), "jobs": jobs}
            return {"commit": "abc", "status": "building"}
        with patch.object(host, "api", side_effect=api), patch.object(host, "ref", return_value="abc"), \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaises(github_pages.QueuedPagesError):
                host.wait("wiki", "abc")
        self.assertEqual(clock.now, 25)

    def test_all_job_pages_must_show_no_started_job(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock, host.QUEUED_GRACE = clock, 10
        run = {"id": 2, "head_sha": "abc", "name": "pages build and deployment", "status": "pending"}
        def api(method, path, **kwargs):
            if "/actions/runs?" in path:
                return {"workflow_runs": [run]}
            if "/jobs?" in path:
                jobs = ([{"status": "queued", "started_at": None}] if path.endswith("page=1")
                        else [{"status": "in_progress", "started_at": "started"}])
                return {"total_count": 2, "jobs": jobs}
            return {"commit": "abc", "status": "built" if clock.now >= 15 else "queued"}
        with patch.object(host, "api", side_effect=api) as calls, patch.object(host, "ref", return_value="abc"), \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            self.assertEqual(host.wait("wiki", "abc")["status"], "built")
        self.assertTrue(any(call.args[1].endswith("page=2") for call in calls.call_args_list))

    def test_failed_deployment_uses_the_same_terminal_classifier(self):
        host = github_pages.GitHubPages("fixture")
        unrelated = {"id": 9, "head_sha": "old", "name": "pages build and deployment", "status": "completed", "conclusion": "failure"}
        target = {**unrelated, "id": 2, "head_sha": "abc", "conclusion": "timed_out"}
        with patch.object(host, "api", return_value={"workflow_runs": [unrelated, target]}):
            self.assertEqual(host.failed_deployment("wiki", "abc"), target)

    def test_wait_read_failure_exhausts_shared_deadline_without_more_retries(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock, host.BUILD_DEADLINE = clock, 3
        def timeout(command, **kwargs):
            clock.sleep(kwargs["timeout"])
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        with patch.object(github_pages.bounded, "run", side_effect=timeout) as calls, \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaisesRegex(github_pages.BuildObservationError, "deadline"):
                host.wait("wiki", "abc")
        self.assertEqual(clock.now, 3)
        self.assertEqual(calls.call_count, 1)

    def test_retry_sleep_and_next_attempt_share_remaining_budget(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock = clock
        timeouts = []
        def retry(command, **kwargs):
            timeouts.append(kwargs["timeout"])
            clock.sleep(0.75)
            return subprocess.CompletedProcess(command, 1, b"", b"HTTP 503")
        with patch.object(github_pages.bounded, "run", side_effect=retry), \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaisesRegex(ContractError, "deadline"):
                host.api("GET", "repos/fixture/wiki", deadline=3)
        self.assertEqual(clock.now, 3)
        self.assertEqual(timeouts, [3, 1.25])

    def test_public_and_mediawiki_reads_exhaust_elapsed_budget(self):
        for adapter in ("pages", "mediawiki"):
            with self.subTest(adapter=adapter):
                clock = Clock()
                class Slow(io.BytesIO):
                    def read1(self, size):
                        clock.sleep(1)
                        return b"x"
                response = Slow()
                response.url = "https://example.invalid/file"
                response.status = 200
                response.headers = Message()
                response.headers["Content-Type"] = "application/json"
                if adapter == "pages":
                    host = github_pages.GitHubPages("fixture")
                    host.clock = clock
                    with patch.object(github_pages, "urlopen", return_value=response) as opened:
                        with self.assertRaisesRegex(ContractError, "deadline"):
                            host.verify("https://example.invalid/", {"file": {"bytes": 100, "sha256": "unused"}}, deadline=3)
                    self.assertEqual(opened.call_args.kwargs["timeout"], 3)
                else:
                    client = mediawiki.Client("https://example.invalid/api.php", clock=clock)
                    with patch.object(client.opener, "open", return_value=response) as opened:
                        with self.assertRaisesRegex(mediawiki.RemoteError, "deadline"):
                            client({}, deadline=3)
                    self.assertEqual(opened.call_args.kwargs["timeout"], 3)
                self.assertEqual(clock.now, 3)
                self.assertTrue(response.closed)

    def test_exhausted_mediawiki_budget_prevents_a_new_request(self):
        clock = Clock()
        client = mediawiki.Client("https://example.invalid/api.php", deadline=0, clock=clock)
        with patch.object(client.opener, "open") as opened:
            with self.assertRaisesRegex(mediawiki.RemoteError, "deadline"):
                client({})
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
