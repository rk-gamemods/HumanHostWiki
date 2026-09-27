"""GitHub CLI and public HTTP adapter. Credentials stay in the CLI's keyring."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .storage import ContractError


class GitHubPages:
    def __init__(self, owner, progress=None):
        self.owner = owner
        self.progress = progress or (lambda message: None)

    def api(self, method, path, body=None, missing=False, empty=False):
        command = ["gh", "api", "--hostname", "github.com", "--method", method, path,
                   "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2026-03-10"]
        data = None
        if body is not None:
            command += ["--input", "-"]
            data = json.dumps(body).encode()
        for attempt in range(4):
            result = subprocess.run(command, input=data, capture_output=True)
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
            result = subprocess.run(["git", "-C", str(path), "push", "--porcelain", url,
                                     f"{commit}:refs/heads/{branch}"], capture_output=True, env=environment)
            actual = self.ref(name, branch)
            if actual == commit:
                return
            if actual != expected:
                raise ContractError(f"Remote branch changed during push: {name}/{branch}")
            if attempt < 2:
                self.progress(f"Retrying unconfirmed push: {name}/{branch}")
                time.sleep(2 ** attempt)
        raise ContractError(f"Push failed for {name}/{branch}: {result.stderr.decode(errors='replace')[:1200]}")

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

    def wait(self, name, commit):
        # A queued/building job stays live. Poll the same build until its actual
        # state is terminal; an observation delay is not a failed deployment.
        endpoint = f"repos/{self.owner}/{name}/pages/builds/latest"
        observed, ticks = None, 0
        while True:
            value = self.api("GET", endpoint, missing=True)
            state = (value or {}).get("status", "awaiting-build")
            if value and value.get("commit") == commit:
                if state == "built":
                    return {"commit": commit, "status": "built"}
                if state in {"errored", "cancelled"}:
                    raise ContractError(f"Pages build {name} failed: {value.get('error')}")
            if ticks % 4 == 0 or state != observed:
                self.progress(f"Pages {name}: {state}")
                if self.ref(name, "gh-pages") != commit:
                    raise ContractError(f"Pages source changed while waiting: {name}")
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
