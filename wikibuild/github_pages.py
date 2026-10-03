"""GitHub CLI and public HTTP adapter. Credentials stay in the CLI's keyring."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import bounded
from .bounded_http import response_deadline
from .storage import ContractError


class BuildObservationError(ContractError):
    """Build outcome is unknown; retain evidence for abandonment and a fresh run."""


class QueuedPagesError(BuildObservationError):
    """The exact commit has a workflow, but no job started within the grace period."""

    def __init__(self, name, commit, deadline):
        super().__init__(f"Pages {name} at {commit} is queued-not-started past the grace period")
        self.deadline = deadline


def _validate_pages(owner, name, value):
    if (not isinstance(value, dict) or value.get("source") != {"branch": "gh-pages", "path": "/"}
            or value.get("build_type", "legacy") != "legacy" or value.get("cname")):
        raise ContractError(f"Unexpected Pages configuration: {name}")
    expected = f"https://{owner}.github.io/{name}/"
    url = value.get("html_url")
    if not isinstance(url, str) or url.rstrip("/").casefold() != expected.rstrip("/").casefold():
        raise ContractError(f"Unexpected Pages URL: {name}")


def validate_configuration(owner, name, repository, pages):
    """Read-only validation and a receipt-sized observation of deployment settings."""
    observation = {"repository": name, "observed": "absent"}
    if repository is None:
        return observation
    full_name = f"{owner}/{name}"
    if (not isinstance(repository, dict) or not isinstance(repository.get("full_name"), str)
            or repository["full_name"].casefold() != full_name.casefold()
            or type(repository.get("id")) is not int or repository["id"] <= 0
            or repository.get("private") or repository.get("archived") or repository.get("fork")
            or not isinstance(repository.get("permissions"), dict)
            or not repository.get("permissions", {}).get("admin")):
        raise ContractError(f"Unexpected remote identity or permissions: {full_name}")
    observation.update(repository_id=repository["id"], observed="pages-disabled" if pages is None else "present")
    observation["identity"] = {key: repository.get(key) for key in ("full_name", "private", "archived", "fork")}
    observation["identity"]["admin"] = repository["permissions"]["admin"]
    if pages is not None:
        _validate_pages(owner, name, pages)
        observation["pages"] = {key: pages.get(key) for key in ("source", "build_type", "cname", "html_url")}
    return observation


def observe_configuration(host, owner, name):
    repository = host.repository(name)
    pages = host.api("GET", f"repos/{owner}/{name}/pages", missing=True) if repository is not None else None
    return validate_configuration(owner, name, repository, pages)


def pages_run(commit, runs):
    """Newest Pages attempt for this commit; never adopt an unrelated queued run."""
    if not isinstance(runs, (list, tuple)) or any(not isinstance(run, dict) for run in runs):
        raise BuildObservationError("Invalid Pages workflow inventory")
    matching = [run for run in runs if run.get("head_sha") == commit
                and run.get("name") == "pages build and deployment"]
    if any(type(run.get("id")) is not int or run["id"] <= 0
           or type(run.get("run_attempt")) is not int or run["run_attempt"] <= 0 for run in matching):
        raise BuildObservationError("Invalid Pages workflow attempt identity")
    return max(matching, key=lambda run: (run["id"], run["run_attempt"]), default=None)


def classify_pages_state(commit, builds, runs=(), jobs=None):
    """Classify one commit; jobs maps (run id, attempt) pairs to job lists."""
    if not isinstance(builds, (list, tuple)) or any(not isinstance(row, dict) for row in builds):
        raise BuildObservationError("Invalid Pages build inventory")
    build = next((row for row in builds if row.get("commit") == commit), None)
    status = build.get("status") if build else None
    if status == "built":
        return "built"
    if status in {"errored", "cancelled"}:
        return "failed"
    if build and status not in {"queued", "building"}:
        raise BuildObservationError(f"Unknown Pages build status: {status!r}")
    run = pages_run(commit, runs)
    if run:
        state = run.get("status")
        if state == "completed":
            if run.get("conclusion") is None:
                raise BuildObservationError("Completed Pages workflow has no conclusion")
            return "building" if run["conclusion"] == "success" else "failed"
        if state in {"queued", "waiting", "pending"}:
            observed_jobs = (jobs or {}).get((run["id"], run["run_attempt"]))
            if observed_jobs is not None and (not isinstance(observed_jobs, list)
                    or any(not isinstance(job, dict) for job in observed_jobs)):
                raise BuildObservationError("Invalid Pages job inventory")
            if observed_jobs is not None and any(
                    not isinstance(job.get("status"), str)
                    or job["status"] not in {"queued", "waiting", "pending", "in_progress", "completed"}
                    or "started_at" not in job or (job["started_at"] is not None
                    and (not isinstance(job["started_at"], str) or not job["started_at"]))
                    for job in observed_jobs):
                raise BuildObservationError("Unknown Pages job observation")
            if observed_jobs is not None and not any(
                    job.get("started_at") or job.get("status") in {"in_progress", "completed"}
                    for job in observed_jobs):
                return "queued-not-started"
            return "building"
        if state not in {"in_progress", "requested"}:
            raise BuildObservationError(f"Unknown Pages workflow status: {state!r}")
        return "building"
    return "building" if build else "missing"


class GitHubPages:
    # Every external wait is bounded. A stalled call or a build GitHub never
    # finishes becomes a reported failure instead of a process that hangs.
    API_TIMEOUT = 120
    PUSH_TIMEOUT = 600
    BUILD_DEADLINE = 30 * 60
    QUEUED_GRACE = 5 * 60
    VERIFY_DEADLINE = 5 * 30 + 15

    def __init__(self, owner, progress=None):
        self.owner = owner
        self.progress = progress or (lambda message: None)
        self.clock = time.monotonic

    def api(self, method, path, body=None, missing=False, empty=False, *, deadline=None):
        deadline = self.clock() + self.API_TIMEOUT * 4 + 7 if deadline is None else deadline

        def remaining():
            budget = deadline - self.clock()
            if budget <= 0:
                raise ContractError(f"GitHub {method} {path}: elapsed deadline exhausted")
            return budget

        def pause(attempt):
            time.sleep(min(2 ** attempt, remaining()))
            remaining()

        command = ["gh", "api", "--hostname", "github.com", "--method", method, path,
                   "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2026-03-10"]
        data = None
        if body is not None:
            command += ["--input", "-"]
            data = json.dumps(body).encode()
        for attempt in range(4):
            try:
                # Reserve the shared owned-tree reap and pipe-drain deadlines.
                timeout = min(self.API_TIMEOUT, remaining() - bounded.CLEANUP_SECONDS)
                if timeout <= 0:
                    raise ContractError(f"GitHub {method} {path}: elapsed deadline cannot cover process cleanup")
                # Cancellation must reach bounded.run in this thread so it kills
                # the process tree before the publisher releases its writer lock.
                result = bounded.run(command, timeout=timeout, input=data)
            except subprocess.TimeoutExpired:
                remaining()
                # A timed-out POST may have taken effect; its caller reconciles instead of repeating it.
                if attempt < 3 and method == "GET":
                    self.progress(f"GitHub call timed out after {self.API_TIMEOUT}s: retry {attempt + 1} for {path}")
                    pause(attempt)
                    continue
                raise ContractError(f"GitHub {method} {path}: timed out after {self.API_TIMEOUT}s, attempt {attempt + 1}")
            remaining()
            if result.returncode == 0:
                return json.loads(result.stdout) if result.stdout.strip() else None
            message = result.stderr.decode(errors="replace")
            if missing and "HTTP 404" in message:
                return None
            if empty and "HTTP 409" in message and "Git Repository is empty" in result.stdout.decode(errors="replace"):
                return None
            # A POST that failed with a 5xx may still have taken effect; only 429 proves it did not run.
            retryable = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504") if method == "GET" else ("HTTP 429",)
            if attempt < 3 and any(code in message for code in retryable):
                self.progress(f"GitHub temporarily unavailable: retry {attempt + 1} for {path}")
                pause(attempt)
                continue
            raise ContractError(f"GitHub {method} {path}: {message.strip()[:1200]}")

    def repository(self, name):
        return self.api("GET", f"repos/{self.owner}/{name}", missing=True)

    def create(self, name, description):
        # Reconcile a lost create response instead of creating a differently named repo.
        try:
            return self.api("POST", f"orgs/{self.owner}/repos", {
                "name": name, "description": description, "private": False, "auto_init": False,
                "has_wiki": False, "has_projects": False})
        except ContractError:
            existing = self.repository(name)
            if existing is None:
                raise
            return existing

    def ref(self, name, branch, *, deadline=None):
        result = self.api("GET", f"repos/{self.owner}/{name}/git/ref/heads/{branch}", missing=True, empty=True, deadline=deadline)
        return result["object"]["sha"] if result else None

    def fetch(self, path, name, branch):
        """Copy a remote branch tip into local object storage (read-only on GitHub)."""
        url = f"https://github.com/{self.owner}/{name}.git"
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        try:
            result = bounded.run(["git", "-C", str(path), "fetch", "--no-tags", "--quiet", url,
                                  f"+refs/heads/{branch}:refs/wiki-remote/{branch}"], timeout=self.PUSH_TIMEOUT, env=environment)
        except subprocess.TimeoutExpired:
            raise ContractError(f"git fetch timed out after {self.PUSH_TIMEOUT}s: {name}/{branch}") from None
        if result.returncode:
            raise ContractError(f"Fetch failed for {name}/{branch}: {result.stderr.decode(errors='replace')[:1200]}")

    def push(self, path, name, commit, branch, expected, *, deadline=None):
        def budget(*, cleanup=False):
            remaining = self.PUSH_TIMEOUT if deadline is None else deadline - self.clock()
            if cleanup and deadline is not None:
                remaining -= bounded.CLEANUP_SECONDS
            if remaining <= 0:
                raise ContractError(f"Push deadline exhausted: {name}/{branch}")
            return min(self.PUSH_TIMEOUT, remaining)

        def read_ref():
            budget()
            value = self.ref(name, branch, **({"deadline": deadline} if deadline is not None else {}))
            budget()
            return value

        current = read_ref()
        if current != expected:
            raise ContractError(f"Remote branch changed: {name}/{branch}")
        if current == commit:
            return
        url = f"https://github.com/{self.owner}/{name}.git"
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        if current:
            try:
                ancestry = bounded.run(["git", "-C", str(path), "merge-base", "--is-ancestor", current, commit],
                                       timeout=budget(cleanup=True), env=environment)
            except subprocess.TimeoutExpired:
                raise ContractError(f"Push ancestry check timed out: {name}/{branch}") from None
            if ancestry.returncode:
                raise ContractError(f"Non-fast-forward push: {name}/{branch}")
        lease = f"--force-with-lease=refs/heads/{branch}:{expected or ''}"
        for attempt in range(3):
            try:
                result = bounded.run(["git", "-C", str(path), "push", "--porcelain", lease, url,
                                      f"{commit}:refs/heads/{branch}"], timeout=budget(cleanup=True), env=environment)
                failure = result.stderr.decode(errors="replace")
            except subprocess.TimeoutExpired:
                # The push may still have landed; the remote ref decides.
                failure = f"git push timed out after {self.PUSH_TIMEOUT}s"
            actual = read_ref()
            if actual == commit:
                return
            if actual != expected:
                raise ContractError(f"Remote branch changed during push: {name}/{branch}")
            if attempt < 2:
                self.progress(f"Retrying unconfirmed push: {name}/{branch}")
                time.sleep(min(2 ** attempt, budget()))
        raise ContractError(f"Push failed for {name}/{branch}: {failure[:1200]}")

    def configure(self, name, *, defer=False):
        endpoint = f"repos/{self.owner}/{name}/pages"
        value = self.api("GET", endpoint, missing=True)
        if value is None:
            def enable():
                try:
                    self.api("POST", endpoint, {"build_type": "legacy", "source": {"branch": "gh-pages", "path": "/"}})
                except ContractError:
                    if self.api("GET", endpoint, missing=True) is None:
                        raise
                configured = self.api("GET", endpoint)
                _validate_pages(self.owner, name, configured)
                return configured
            # The source branch must exist before Pages can be enabled. The
            # read-only check happens before pushes; only provisioning is deferred.
            return enable if defer else enable()
        _validate_pages(self.owner, name, value)
        return value

    def failed_deployment(self, name, commit, *, deadline=None):
        """GitHub's Pages workflow run for this commit, if it finished without deploying.

        The Pages build record can stay 'building' after that workflow fails, for
        example on a transient 'Failed to get ID Token' timeout, so the run is the truth."""
        runs = self.api("GET", f"repos/{self.owner}/{name}/actions/runs?head_sha={commit}&per_page=20", deadline=deadline)
        rows = (runs or {}).get("workflow_runs", [])
        return pages_run(commit, rows) if classify_pages_state(commit, [], rows) == "failed" else None

    def wait(self, name, commit, *, deadline=None):
        # A successor shares this deadline. Only a workflow with observed unstarted
        # jobs qualifies for recovery; a missing build or an unrelated run does not.
        builds = f"repos/{self.owner}/{name}/pages/builds"
        endpoint = builds + "/latest"
        observed, ticks, missing, reruns = None, 0, 0, 0
        deadline = self.clock() + self.BUILD_DEADLINE if deadline is None else deadline
        queued_since, queued_attempt = None, None

        def check_deadline():
            if self.clock() >= deadline:
                raise BuildObservationError(
                    f"Pages build {name} at {commit} did not finish after {self.BUILD_DEADLINE // 60} minutes; "
                    "abandon the publication journal before rehearsing a fresh run.")

        def check_source():
            try:
                current = self.ref(name, "gh-pages", deadline=deadline)
            except ContractError as exc:
                raise BuildObservationError(f"Unable to observe Pages source {name}: {exc}") from exc
            if current != commit:
                raise ContractError(f"Pages source changed while waiting: {name}")

        while True:
            check_deadline()
            try:
                value = self.api("GET", endpoint, missing=True, deadline=deadline)
                if value is not None and not isinstance(value, dict):
                    raise BuildObservationError(f"Invalid Pages build record: {name}")
                if endpoint.endswith("/latest") and (not value or value.get("commit") != commit):
                    # 'latest' alone cannot establish absence: another build may
                    # have arrived while we were observing our pinned commit.
                    recent = self.api("GET", builds + "?per_page=100", deadline=deadline)
                    if not isinstance(recent, list) or any(not isinstance(row, dict) for row in recent):
                        raise BuildObservationError(f"Invalid Pages build inventory: {name}")
                    value = next((row for row in recent if row.get("commit") == commit), None)
                runs, jobs = [], {}
                if value is None or value.get("status") in {"queued", "building"}:
                    inventory = self.api("GET", f"repos/{self.owner}/{name}/actions/runs?head_sha={commit}&per_page=20",
                                         deadline=deadline)
                    runs = (inventory or {}).get("workflow_runs", [])
                    run = pages_run(commit, runs)
                    if run and run.get("status") in {"queued", "waiting", "pending"}:
                        # All jobs must be observed before asserting that none started.
                        page, rows = 1, []
                        while True:
                            record = self.api("GET", f"repos/{self.owner}/{name}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100&page={page}",
                                              deadline=deadline)
                            batch = record["jobs"]
                            if (not isinstance(batch, list) or any(not isinstance(job, dict) for job in batch)
                                    or type(record["total_count"]) is not int or record["total_count"] < 0):
                                raise BuildObservationError("Invalid Pages job inventory")
                            rows.extend(batch)
                            if len(rows) >= record["total_count"]:
                                break
                            if not batch:
                                raise BuildObservationError("Incomplete Pages job inventory")
                            page += 1
                        jobs[(run["id"], run["run_attempt"])] = rows
            except (ContractError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise BuildObservationError(f"Unable to observe Pages build {name} at {commit}: {exc}") from exc
            if value and value.get("commit") != commit:
                raise BuildObservationError(f"Pinned Pages build identity changed: {name}")
            check_deadline()
            state = classify_pages_state(commit, [value] if value else [], runs, jobs)
            if value:
                missing = 0
                url = value.get("url", "")
                if re.fullmatch(re.escape("https://api.github.com/" + builds) + r"/\d+", url):
                    endpoint = url.removeprefix("https://api.github.com/")
            if state == "built":
                check_source()
                check_deadline()
                return {"commit": commit, "status": "built"}
            run = pages_run(commit, runs)
            deployment_failed = state == "failed" and value and value.get("status") == "building" and run
            if state == "failed" and not deployment_failed:
                raise ContractError(f"Pages build {name} failed: {value.get('error') if value else pages_run(commit, runs)}")
            if state == "building" or deployment_failed:
                state = "building"
                missing = 0
                if ticks and ticks % 60 == 0:
                    if deployment_failed:
                        if reruns == 3:
                            raise ContractError(f"Pages deployment for {name} failed after 3 reruns: {run.get('html_url')}")
                        reruns += 1
                        self.progress(f"Pages {name}: GitHub's deployment failed; rerun {reruns} of 3")
                        try:
                            self.api("POST", f"repos/{self.owner}/{name}/actions/runs/{run['id']}/rerun-failed-jobs", deadline=deadline)
                        except ContractError as exc:
                            # GitHub may have accepted the rerun; keep the commit pending, do not roll back.
                            raise BuildObservationError(f"Rerun request for Pages {name} has an unknown outcome: {exc}") from exc
            elif state == "queued-not-started":
                missing = 0
            else:
                missing += 1
            if state == "queued-not-started":
                attempt = (run["id"], run["run_attempt"])
                if attempt != queued_attempt:
                    queued_since, queued_attempt = self.clock(), attempt
                if self.clock() - queued_since >= self.QUEUED_GRACE:
                    check_source()
                    raise QueuedPagesError(name, commit, deadline)
            else:
                queued_since, queued_attempt = None, None
            if ticks % 4 == 0 or state != observed:
                self.progress(f"Pages {name}: {state}")
                check_source()
            if missing >= 12:
                raise BuildObservationError(
                    f"Pages build {name} at {commit} was not observable after 12 checks; "
                    "abandon the publication journal before rehearsing a fresh run.")
            check_deadline()
            observed = state
            ticks += 1
            time.sleep(max(0, min(5, deadline - self.clock())))

    def verify(self, base, files, *, workers=4, deadline=None):
        def verify_one(item):
            end = self.clock() + self.VERIFY_DEADLINE if deadline is None else deadline
            name, expected = item
            url = base + quote(name, safe="/")

            def read(read_deadline):
                request = Request(url, headers={"User-Agent": "HumanHostWiki-publisher", "Cache-Control": "no-cache"})
                with response_deadline(urlopen(request, timeout=max(0.001, read_deadline - self.clock())),
                                       read_deadline, self.clock) as response:
                    if response.url.split("?", 1)[0] != url:
                        raise ContractError(f"Public target redirected: {url}")
                    value, size = hashlib.sha256(), 0
                    read_block = getattr(response, "read1", response.read)
                    while self.clock() < read_deadline:
                        block = read_block(65536)
                        if not block:
                            return size, value.hexdigest()
                        size += len(block)
                        if size > expected["bytes"]:
                            return size, ""
                        value.update(block)
                    raise TimeoutError("elapsed deadline exhausted")

            for attempt in range(5):
                try:
                    read_deadline = min(end, self.clock() + 30)
                    if self.clock() >= read_deadline:
                        raise TimeoutError("elapsed deadline exhausted")
                    size, checksum = read(read_deadline)
                    if size == expected["bytes"] and checksum == expected["sha256"]:
                        return size
                    reason = "content differs"
                except (HTTPError, URLError, TimeoutError, OSError) as exc:
                    reason = str(exc)
                remaining = end - self.clock()
                if remaining <= 0:
                    raise ContractError(f"Public verification deadline exhausted: {url}")
                if attempt < 4:
                    time.sleep(min(2 ** attempt, remaining))
            raise ContractError(f"Public verification failed: {url}: {reason}")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            sizes = list(pool.map(verify_one, sorted(files.items())))
        return {"files": len(sizes), "bytes": sum(sizes)}
