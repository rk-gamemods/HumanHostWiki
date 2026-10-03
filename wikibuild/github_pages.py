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
from .storage import ContractError


class BuildObservationError(ContractError):
    """Build outcome is unknown; preserve its commit and reconcile on the next run."""


class GitHubPages:
    # Every external wait is bounded. A stalled call or a build GitHub never
    # finishes becomes a reported failure instead of a process that hangs.
    API_TIMEOUT = 120
    PUSH_TIMEOUT = 600
    BUILD_DEADLINE = 30 * 60

    def __init__(self, owner, progress=None):
        self.owner = owner
        self.progress = progress or (lambda message: None)
        self.clock = time.monotonic

    def api(self, method, path, body=None, missing=False, empty=False):
        command = ["gh", "api", "--hostname", "github.com", "--method", method, path,
                   "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2026-03-10"]
        data = None
        if body is not None:
            command += ["--input", "-"]
            data = json.dumps(body).encode()
        for attempt in range(4):
            try:
                result = bounded.run(command, timeout=self.API_TIMEOUT, input=data)
            except subprocess.TimeoutExpired:
                # A timed-out POST may have taken effect; its caller reconciles instead of repeating it.
                if attempt < 3 and method == "GET":
                    self.progress(f"GitHub call timed out after {self.API_TIMEOUT}s: retry {attempt + 1} for {path}")
                    time.sleep(2 ** attempt)
                    continue
                raise ContractError(f"GitHub {method} {path}: timed out after {self.API_TIMEOUT}s, attempt {attempt + 1}")
            if result.returncode == 0:
                return json.loads(result.stdout) if result.stdout.strip() else None
            message = result.stderr.decode(errors="replace")
            if missing and "HTTP 404" in message:
                return None
            if empty and "HTTP 409" in message and "Git Repository is empty" in result.stdout.decode(errors="replace"):
                return None
            if attempt < 3 and any(code in message for code in ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")):
                self.progress(f"GitHub temporarily unavailable: retry {attempt + 1} for {path}")
                time.sleep(2 ** attempt)
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

    def ref(self, name, branch):
        result = self.api("GET", f"repos/{self.owner}/{name}/git/ref/heads/{branch}", missing=True, empty=True)
        return result["object"]["sha"] if result else None

    def push(self, path, name, commit, branch, expected):
        current = self.ref(name, branch)
        if current == commit:
            return
        if current != expected:
            raise ContractError(f"Remote branch changed: {name}/{branch}")
        url = f"https://github.com/{self.owner}/{name}.git"
        environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        for attempt in range(3):
            try:
                result = bounded.run(["git", "-C", str(path), "push", "--porcelain", url,
                                      f"{commit}:refs/heads/{branch}"], timeout=self.PUSH_TIMEOUT, env=environment)
                failure = result.stderr.decode(errors="replace")
            except subprocess.TimeoutExpired:
                # The push may still have landed; the remote ref decides.
                failure = f"git push timed out after {self.PUSH_TIMEOUT}s"
            actual = self.ref(name, branch)
            if actual == commit:
                return
            if actual != expected:
                raise ContractError(f"Remote branch changed during push: {name}/{branch}")
            if attempt < 2:
                self.progress(f"Retrying unconfirmed push: {name}/{branch}")
                time.sleep(2 ** attempt)
        raise ContractError(f"Push failed for {name}/{branch}: {failure[:1200]}")

    def configure(self, name):
        endpoint = f"repos/{self.owner}/{name}/pages"
        value = self.api("GET", endpoint, missing=True)
        if value is None:
            try:
                self.api("POST", endpoint, {"build_type": "legacy", "source": {"branch": "gh-pages", "path": "/"}})
            except ContractError:
                if self.api("GET", endpoint, missing=True) is None:
                    raise
            value = self.api("GET", endpoint)
        if value.get("source") != {"branch": "gh-pages", "path": "/"} or value.get("build_type", "legacy") != "legacy" or value.get("cname"):
            raise ContractError(f"Unexpected Pages configuration: {name}")
        expected = f"https://{self.owner}.github.io/{name}/"
        if value["html_url"].rstrip("/").casefold() != expected.rstrip("/").casefold():
            raise ContractError(f"Unexpected Pages URL: {name}")

    def failed_deployment(self, name, commit):
        """GitHub's Pages workflow run for this commit, if it finished without deploying.

        The Pages build record can stay 'building' after that workflow fails, for
        example on a transient 'Failed to get ID Token' timeout, so the run is the truth."""
        runs = self.api("GET", f"repos/{self.owner}/{name}/actions/runs?head_sha={commit}&per_page=20")
        for run in (runs or {}).get("workflow_runs", []):
            if run.get("name") == "pages build and deployment":
                done = run.get("status") == "completed" and run.get("conclusion") != "success"
                return run if done else None
        return None

    def wait(self, name, commit):
        # Twelve successful observations that find neither our build nor another
        # queued/running build ahead of it end the wait. A build still live after five
        # minutes is checked against its deployment run; a failed run is rerun up to
        # three times, then publication stops with its link. Any build, ours or one
        # ahead of it, still live at BUILD_DEADLINE leaves publication pending for the
        # next run to reconcile; GitHub can leave a build 'building' indefinitely.
        builds = f"repos/{self.owner}/{name}/pages/builds"
        endpoint = builds + "/latest"
        observed, ticks, missing, reruns = None, 0, 0, 0
        started = self.clock()

        def check_source():
            try:
                current = self.ref(name, "gh-pages")
            except ContractError as exc:
                raise BuildObservationError(f"Unable to observe Pages source {name}: {exc}") from exc
            if current != commit:
                raise ContractError(f"Pages source changed while waiting: {name}")

        while True:
            try:
                value = self.api("GET", endpoint, missing=True)
                if value is not None and not isinstance(value, dict):
                    raise BuildObservationError(f"Invalid Pages build record: {name}")
                active = False
                if endpoint.endswith("/latest") and (not value or value.get("commit") != commit):
                    # 'latest' alone cannot establish absence: another build may
                    # have arrived while we were observing our pinned commit.
                    recent = self.api("GET", builds + "?per_page=100")
                    if not isinstance(recent, list) or any(not isinstance(row, dict) for row in recent):
                        raise BuildObservationError(f"Invalid Pages build inventory: {name}")
                    active = any(row.get("status") in {"queued", "building"} for row in recent)
                    value = next((row for row in recent if row.get("commit") == commit), None)
            except (ContractError, ValueError) as exc:
                raise BuildObservationError(f"Unable to observe Pages build {name} at {commit}: {exc}") from exc
            if value and value.get("commit") != commit:
                raise BuildObservationError(f"Pinned Pages build identity changed: {name}")
            state = value.get("status") if value else ("waiting-for-earlier-build" if active else "awaiting-build")
            if value:
                missing = 0
                url = value.get("url", "")
                if re.fullmatch(re.escape("https://api.github.com/" + builds) + r"/\d+", url):
                    endpoint = url.removeprefix("https://api.github.com/")
                if state == "built":
                    check_source()
                    return {"commit": commit, "status": "built"}
                if state in {"errored", "cancelled"}:
                    raise ContractError(f"Pages build {name} failed: {value.get('error')}")
                if state not in {"queued", "building"}:
                    raise BuildObservationError(f"Unknown Pages build status for {name}: {state!r}")
                if ticks and ticks % 60 == 0:
                    try:
                        run = self.failed_deployment(name, commit)
                    except ContractError as exc:
                        run = None
                        self.progress(f"Pages {name}: deployment run not readable ({exc}); still waiting")
                    if run:
                        if reruns == 3:
                            raise ContractError(f"Pages deployment for {name} failed after 3 reruns: {run.get('html_url')}")
                        reruns += 1
                        self.progress(f"Pages {name}: GitHub's deployment failed; rerun {reruns} of 3")
                        try:
                            self.api("POST", f"repos/{self.owner}/{name}/actions/runs/{run['id']}/rerun-failed-jobs")
                        except ContractError as exc:
                            # GitHub may have accepted the rerun; keep the commit pending, do not roll back.
                            raise BuildObservationError(f"Rerun request for Pages {name} has an unknown outcome: {exc}") from exc
            elif active:
                missing = 0
            else:
                missing += 1
            if ticks % 4 == 0 or state != observed:
                self.progress(f"Pages {name}: {state}")
                check_source()
            if missing >= 12:
                raise BuildObservationError(
                    f"Pages build {name} at {commit} was not observable after 12 checks; "
                    "publication remains pending. Rerun to reconcile the same commit.")
            if self.clock() - started >= self.BUILD_DEADLINE:
                raise BuildObservationError(
                    f"Pages build {name} at {commit} was still {state} after {self.BUILD_DEADLINE // 60} minutes; "
                    "publication remains pending. Rerun to reconcile the same commit.")
            observed = state
            ticks += 1
            time.sleep(5)

    def verify(self, base, files, *, workers=4):
        def verify_one(item):
            name, expected = item
            url = base + quote(name, safe="/")
            for attempt in range(5):
                try:
                    request = Request(url, headers={"User-Agent": "HumanHostWiki-publisher", "Cache-Control": "no-cache"})
                    with urlopen(request, timeout=30) as response:
                        if response.url.split("?", 1)[0] != url:
                            raise ContractError(f"Public target redirected: {url}")
                        value, size = hashlib.sha256(), 0
                        while block := response.read(65536):
                            size += len(block)
                            if size > expected["bytes"]:
                                break
                            value.update(block)
                    if size == expected["bytes"] and value.hexdigest() == expected["sha256"]:
                        return size
                    reason = "content differs"
                except (HTTPError, URLError, TimeoutError, OSError) as exc:
                    reason = str(exc)
                if attempt < 4:
                    time.sleep(2 ** attempt)
            raise ContractError(f"Public verification failed: {url}: {reason}")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            sizes = list(pool.map(verify_one, sorted(files.items())))
        return {"files": len(sizes), "bytes": sum(sizes)}
