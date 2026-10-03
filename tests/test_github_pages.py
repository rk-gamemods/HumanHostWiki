"""Commit-scoped Pages observations and elapsed budgets, without network calls."""

from email.message import Message
import _thread
import io
import subprocess
import sys
import threading
import time
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
    def test_api_reserves_worst_case_cleanup_within_the_deadline(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock = clock
        reserve = github_pages.bounded.CLEANUP_SECONDS
        self.assertEqual(reserve, github_pages.bounded.REAP_SECONDS + github_pages.bounded.DRAIN_SECONDS)
        def timeout(command, **kwargs):
            clock.sleep(kwargs["timeout"] + reserve)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        with patch.object(github_pages.bounded, "run", side_effect=timeout) as calls, \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaisesRegex(ContractError, "deadline"):
                host.api("GET", "fixture-only", deadline=reserve + 3)
        self.assertEqual(clock.now, reserve + 3)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(calls.call_args.kwargs["timeout"], 3)
        for remaining in (0, reserve / 2, reserve):
            with self.subTest(remaining=remaining), patch.object(github_pages.bounded, "run") as calls:
                with self.assertRaisesRegex(ContractError, "deadline"):
                    host.api("POST", "fixture-only", deadline=clock.now + remaining)
                calls.assert_not_called()

    def test_blocked_api_timeout_and_interruption_leave_no_child_process(self):
        real_popen = subprocess.Popen
        for interruption in (False, True):
            with self.subTest(interruption=interruption):
                ready, processes = threading.Event(), []

                class ReadyPipe:
                    def __init__(self, pipe):
                        self.pipe = pipe

                    def read1(self, size):
                        block = self.pipe.read1(size)
                        if b"ready" in block:
                            ready.set()
                        return block

                    def close(self):
                        self.pipe.close()

                def local_process(command, **kwargs):
                    # Replace gh only; bounded.run's real process-tree cleanup runs.
                    if command[0] == "gh":
                        command = [sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(60)"]
                        process = real_popen(command, **kwargs)
                        process.stdout = ReadyPipe(process.stdout)
                        processes.append(process)
                        return process
                    return real_popen(command, **kwargs)

                def interrupt():
                    if ready.wait(1.5):
                        _thread.interrupt_main()

                interrupter = threading.Thread(target=interrupt) if interruption else None
                host = github_pages.GitHubPages("fixture")
                try:
                    with patch.object(github_pages.bounded.subprocess, "Popen", side_effect=local_process):
                        if interrupter:
                            interrupter.start()
                        with self.assertRaises(KeyboardInterrupt if interruption else ContractError):
                            host.api("POST", "fixture-only",
                                     deadline=host.clock() + github_pages.bounded.CLEANUP_SECONDS + 2)
                    self.assertTrue(ready.is_set())
                    self.assertEqual(len(processes), 1)
                    self.assertIsNotNone(processes[0].poll(), "API returned while its child was still running")
                finally:
                    if interrupter:
                        interrupter.join()
                    for process in processes:
                        if process.poll() is None:
                            process.kill()
                        process.wait()
                        process.stdout.close()
                        process.stderr.close()

    def test_blocked_http_read_and_interruption_close_response_and_socket(self):
        class Response:
            def __init__(self):
                self.released = threading.Event()
                self.closed = False
                self.active = False
                from unittest.mock import Mock
                self.fp = Mock()
                self.fp.raw._sock.shutdown.side_effect = lambda how: self.released.set()

            def read(self):
                self.active = True
                try:
                    if not self.released.wait(2):
                        raise AssertionError("Timeout did not shut down the blocked socket")
                finally:
                    self.active = False

            def close(self):
                self.closed = True

        for interruption in (False, True):
            with self.subTest(interruption=interruption):
                response, timers = Response(), []
                real_timer = threading.Timer
                def timer(*args, **kwargs):
                    value = real_timer(*args, **kwargs)
                    timers.append(value)
                    return value
                with patch.object(mediawiki, "Timer", side_effect=timer):
                    with self.assertRaises(KeyboardInterrupt if interruption else TimeoutError):
                        with mediawiki.response_deadline(response, time.monotonic() + 0.05, time.monotonic):
                            if interruption:
                                raise KeyboardInterrupt
                            response.read()
                self.assertTrue(response.closed)
                self.assertFalse(response.active)
                response.fp.raw._sock.shutdown.assert_called()
                self.assertTrue(all(not timer.is_alive() for timer in timers))

    def test_api_runs_in_the_calling_thread(self):
        host = github_pages.GitHubPages("fixture")
        caller = threading.get_ident()
        threads = []
        def operation(command, **kwargs):
            threads.append(threading.get_ident())
            return subprocess.CompletedProcess(command, 0, b"{}", b"")
        with patch.object(github_pages.bounded, "run", side_effect=operation):
            host.api("POST", "fixture-only")
        self.assertEqual(threads, [caller])

    def test_unknown_job_observations_are_not_unstarted_jobs(self):
        run = {"id": 2, "run_attempt": 1, "head_sha": "abc", "name": "pages build and deployment", "status": "queued"}
        for job in ({}, {"status": "unknown", "started_at": None}, {"status": None, "started_at": None},
                    {"status": [], "started_at": None}, {"status": {}, "started_at": None},
                    {"status": "queued"}, {"status": "queued", "started_at": 123}):
            with self.subTest(job=job), self.assertRaises(github_pages.BuildObservationError):
                github_pages.classify_pages_state("abc", [], [run], {(2, 1): [job]})

    def test_push_retries_and_preflight_share_the_remaining_budget(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock = clock
        invocations, reads = [], []
        def ref(name, branch, **kwargs):
            reads.append(kwargs["deadline"])
            return "stuck"
        def command(args, **kwargs):
            invocations.append((args, kwargs["timeout"]))
            if "push" in args:
                clock.sleep(0.5)
                return subprocess.CompletedProcess(args, 1, b"", b"unavailable")
            return subprocess.CompletedProcess(args, 0, b"", b"")
        with patch.object(github_pages.bounded, "CLEANUP_SECONDS", 1), \
                patch.object(host, "ref", side_effect=ref), patch.object(github_pages.bounded, "run", side_effect=command), \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaisesRegex(ContractError, "deadline"):
                host.push(".", "wiki", "successor", "gh-pages", "stuck", deadline=3)
        self.assertEqual(clock.now, 3)
        self.assertEqual(reads, [3, 3, 3])
        self.assertEqual([timeout for args, timeout in invocations], [2, 2, 0.5])
        with patch.object(host, "ref") as ref, patch.object(github_pages.bounded, "run") as run:
            with self.assertRaisesRegex(ContractError, "deadline"):
                host.push(".", "wiki", "successor", "gh-pages", "stuck", deadline=3)
        ref.assert_not_called()
        run.assert_not_called()

    def test_recovery_push_reserves_cleanup_for_ancestry_and_push(self):
        reserve = github_pages.bounded.CLEANUP_SECONDS
        for blocked in ("merge-base", "push"):
            with self.subTest(blocked=blocked):
                clock, host = Clock(), github_pages.GitHubPages("fixture")
                host.clock = clock
                def command(args, **kwargs):
                    if blocked in args:
                        clock.sleep(kwargs["timeout"] + reserve)
                        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
                    return subprocess.CompletedProcess(args, 0, b"", b"")
                with patch.object(host, "ref", return_value="stuck") as reads, \
                        patch.object(github_pages.bounded, "run", side_effect=command) as calls:
                    with self.assertRaises(ContractError):
                        host.push(".", "wiki", "successor", "gh-pages", "stuck", deadline=reserve + 3)
                self.assertEqual(clock.now, reserve + 3)
                self.assertEqual(reads.call_count, 1)
                self.assertEqual([call.kwargs["timeout"] for call in calls.call_args_list],
                                 [3] if blocked == "merge-base" else [3, 3])

    def test_queued_grace_resets_for_a_new_run_or_attempt(self):
        for change in ("id", "run_attempt"):
            with self.subTest(change=change):
                clock, host = Clock(), github_pages.GitHubPages("fixture")
                host.clock, host.QUEUED_GRACE = clock, 10
                paths = []
                def api(method, path, **kwargs):
                    run = {"id": 2, "run_attempt": 1, "head_sha": "abc", "name": "pages build and deployment", "status": "queued"}
                    if clock.now >= 5:
                        run[change] += 1
                    if "/actions/runs?" in path:
                        return {"workflow_runs": [run]}
                    if "/jobs?" in path:
                        paths.append(path)
                        return {"total_count": 0, "jobs": []}
                    return {"commit": "abc", "status": "queued"}
                with patch.object(host, "api", side_effect=api), patch.object(host, "ref", return_value="abc"), \
                        patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
                    with self.assertRaises(github_pages.QueuedPagesError):
                        host.wait("wiki", "abc")
                self.assertEqual(clock.now, 15)
                self.assertIn("/actions/runs/2/attempts/1/jobs?", paths[0])
                expected = "/actions/runs/3/attempts/1/jobs?" if change == "id" else "/actions/runs/2/attempts/2/jobs?"
                self.assertIn(expected, paths[-1])

    def test_classifies_only_the_requested_commit(self):
        stale = {"id": 1, "run_attempt": 1, "name": "pages build and deployment", "head_sha": "old", "status": "queued"}
        queued = {**stale, "id": 2, "head_sha": "abc"}
        fixtures = [
            ("built", [{"commit": "abc", "status": "built"}], [stale], {}),
            ("building", [{"commit": "abc", "status": "building"}], [stale], {}),
            ("failed", [{"commit": "abc", "status": "errored"}], [stale], {}),
            ("queued-not-started", [], [stale, queued], {(2, 1): []}),
            ("building", [], [queued], {(2, 1): [{"status": "in_progress", "started_at": "2026-09-30"}]}),
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
            clock.sleep(kwargs["timeout"] + github_pages.bounded.CLEANUP_SECONDS)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with patch.object(github_pages.bounded, "run", side_effect=timeout), \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaisesRegex(ContractError, "deadline"):
                host.api("GET", "repos/fixture/wiki", deadline=github_pages.bounded.CLEANUP_SECONDS + 3)
        self.assertEqual(clock.now, github_pages.bounded.CLEANUP_SECONDS + 3)
        self.assertEqual(timeouts, [3])

    def test_all_queued_statuses_and_terminal_conclusions(self):
        run = {"id": 2, "run_attempt": 1, "head_sha": "abc", "name": "pages build and deployment"}
        for status in ("queued", "waiting", "pending"):
            with self.subTest(status=status):
                self.assertEqual(github_pages.classify_pages_state("abc", [], [{**run, "status": status}], {(2, 1): []}),
                                 "queued-not-started")
        for conclusion in ("failure", "cancelled", "timed_out", "action_required", "neutral", "skipped", "stale", "startup_failure"):
            with self.subTest(conclusion=conclusion):
                terminal = {**run, "status": "completed", "conclusion": conclusion}
                self.assertEqual(github_pages.classify_pages_state("abc", [{"commit": "abc", "status": "building"}], [terminal]), "failed")
        older = {**run, "id": 1, "status": "completed", "conclusion": "failure"}
        newer = {**run, "status": "queued"}
        self.assertEqual(github_pages.classify_pages_state("abc", [], [older, newer], {(2, 1): []}), "queued-not-started")

    def test_grace_applies_without_a_pages_build_record(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock, host.QUEUED_GRACE = clock, 10
        run = {"id": 2, "run_attempt": 1, "head_sha": "abc", "name": "pages build and deployment", "status": "waiting"}
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
        stale = {"id": 1, "run_attempt": 1, "head_sha": "old", "name": "pages build and deployment", "status": "queued"}
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
        run = {"id": 2, "run_attempt": 1, "head_sha": "abc", "name": "pages build and deployment", "status": "queued"}
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
        run = {"id": 2, "run_attempt": 1, "head_sha": "abc", "name": "pages build and deployment", "status": "pending"}
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
        unrelated = {"id": 9, "run_attempt": 1, "head_sha": "old", "name": "pages build and deployment", "status": "completed", "conclusion": "failure"}
        target = {**unrelated, "id": 2, "head_sha": "abc", "conclusion": "timed_out"}
        with patch.object(host, "api", return_value={"workflow_runs": [unrelated, target]}):
            self.assertEqual(host.failed_deployment("wiki", "abc"), target)

    def test_wait_read_failure_exhausts_shared_deadline_without_more_retries(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock, host.BUILD_DEADLINE = clock, github_pages.bounded.CLEANUP_SECONDS + 3
        def timeout(command, **kwargs):
            clock.sleep(kwargs["timeout"] + github_pages.bounded.CLEANUP_SECONDS)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        with patch.object(github_pages.bounded, "run", side_effect=timeout) as calls, \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaisesRegex(github_pages.BuildObservationError, "deadline"):
                host.wait("wiki", "abc")
        self.assertEqual(clock.now, host.BUILD_DEADLINE)
        self.assertEqual(calls.call_count, 1)

    def test_retry_sleep_and_next_attempt_share_remaining_budget(self):
        clock, host = Clock(), github_pages.GitHubPages("fixture")
        host.clock = clock
        timeouts = []
        def retry(command, **kwargs):
            timeouts.append(kwargs["timeout"])
            clock.sleep(0.75)
            return subprocess.CompletedProcess(command, 1, b"", b"HTTP 503")
        with patch.object(github_pages.bounded, "CLEANUP_SECONDS", 1), \
                patch.object(github_pages.bounded, "run", side_effect=retry), \
                patch.object(github_pages.time, "sleep", side_effect=clock.sleep):
            with self.assertRaisesRegex(ContractError, "deadline"):
                host.api("GET", "repos/fixture/wiki", deadline=4)
        self.assertEqual(clock.now, 4)
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
