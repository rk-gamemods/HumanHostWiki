"""Read-only production preflight, bound to merged code and a live-state rehearsal."""

from datetime import datetime, timedelta, timezone
import os
import re
import subprocess

from . import bounded, github_pages, physical
from .storage import ContractError, within

GIT_TIMEOUT = 120
WORKSPACE_REPOSITORY = "rk-gamemods/HumanHostWiki"
CI_PATH = ".github/workflows/ci.yml"


def git(root, *arguments):
    """Bound local checks and fetching; never prompt for credentials."""
    try:
        result = bounded.run(["git", "-C", str(root), *arguments], timeout=GIT_TIMEOUT,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        raise ContractError(f"Publish gate: git {arguments[0]} timed out after {GIT_TIMEOUT}s") from None
    if result.returncode:
        raise ContractError(f"Publish gate: git {arguments[0]} failed: "
                            f"{result.stderr.decode(errors='replace').strip()[:1200]}")
    return result.stdout.decode("utf-8").strip()


def receipt_path(root, release_id):
    if not isinstance(release_id, str) or not re.fullmatch(r"[0-9a-f]{64}", release_id):
        raise ContractError("Publish gate: invalid release id")
    return within(root, f".local/publication/rehearsals/{release_id}.json")


def destinations(root, project, manifest):
    names = {repo["github_name"] for repo in physical.repositories(project, manifest.get("physical"))}
    return {(name, branch) for name in names for branch in ("main", "gh-pages")}


def write_receipt(root, release_id, workspace_commit, remote_refs):
    from . import publication
    value = {"schema_version": 1, "release_id": release_id, "workspace_commit": workspace_commit,
             "contract": publication.contract(), "remote_refs": remote_refs,
             "created_utc": datetime.now(timezone.utc).isoformat()}
    publication.save(receipt_path(root, release_id), value)
    return value


def ensure_clean(root):
    """Shared by rehearsal and publication, before any other work."""
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ContractError("Publish gate: workspace must be clean, including non-ignored untracked files")


def check(root, project, manifest):
    """Fail on the first failed boundary, before publication touches any journal."""
    from . import publication
    ensure_clean(root)
    origin = git(root, "remote", "get-url", "origin")
    repository = re.escape(WORKSPACE_REPOSITORY)
    if not re.fullmatch(rf"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com(?::22)?/){repository}(?:\.git)?/?",
                        origin, re.IGNORECASE):
        raise ContractError(f"Publish gate: origin must resolve to github.com/{WORKSPACE_REPOSITORY}")
    git(root, "fetch", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main")
    commit = git(root, "rev-parse", "HEAD")
    if commit != git(root, "rev-parse", "refs/remotes/origin/main"):
        raise ContractError("Publish gate: HEAD must equal fetched origin/main")

    host = github_pages.GitHubPages(project["github_owner"])
    response = host.api("GET", f"repos/{WORKSPACE_REPOSITORY}/actions/runs?head_sha={commit}")
    if (not isinstance(response, dict) or not isinstance(response.get("workflow_runs"), list)
            or any(not isinstance(row, dict) for row in response["workflow_runs"])):
        raise ContractError("Publish gate: invalid CI response for this exact commit")
    runs = [row for row in response["workflow_runs"]
            if row.get("name") == "CI" and row.get("path") == CI_PATH
            and row.get("event") == "push" and row.get("head_branch") == "main"
            and row.get("head_sha") == commit]
    if not runs:
        raise ContractError("Publish gate: CI is missing for this exact commit")
    if any(type(row.get("id")) is not int or any(type(row.get(key, 0)) is not int
               for key in ("run_number", "run_attempt")) for row in runs):
        raise ContractError("Publish gate: invalid CI run identity for this exact commit")
    latest = max(runs, key=lambda row: (row.get("run_number", 0), row.get("run_attempt", 0), row["id"]))
    if latest.get("status") != "completed":
        raise ContractError("Publish gate: CI has not completed for this exact commit")
    if latest.get("conclusion") != "success":
        raise ContractError("Publish gate: CI did not conclude success for this exact commit")

    pulls = host.api("GET", f"repos/{WORKSPACE_REPOSITORY}/commits/{commit}/pulls")
    if not isinstance(pulls, list) or any(not isinstance(row, dict) for row in pulls):
        raise ContractError("Publish gate: invalid merged PR response for this exact commit")
    merged = next((row for row in pulls if isinstance(row.get("merged_at"), str)
                   and row["merged_at"] and row.get("merge_commit_sha") == commit), None)
    if merged is None:
        raise ContractError("Publish gate: this exact commit must be the merge commit of a merged PR")

    path = receipt_path(root, manifest["release_id"])
    if not path.is_file():
        raise ContractError("Publish gate: successful rehearsal receipt is missing for this release")
    try:
        receipt = publication.load(path)
        if receipt["schema_version"] != 1 or receipt["release_id"] != manifest["release_id"]:
            raise ContractError("Publish gate: rehearsal receipt belongs to another release or schema")
        if receipt["workspace_commit"] != commit:
            raise ContractError("Publish gate: rehearsal workspace commit differs")
        if receipt["contract"] != publication.contract():
            raise ContractError("Publish gate: rehearsal publication contract differs")
        created = datetime.fromisoformat(receipt["created_utc"])
        if created.tzinfo is None or created.utcoffset() != timedelta(0):
            raise ContractError("Publish gate: rehearsal timestamp must be UTC")
        age = datetime.now(timezone.utc) - created
        if age < timedelta(0) or age > timedelta(hours=24):
            raise ContractError("Publish gate: rehearsal receipt is stale or dated in the future")
        refs = receipt["remote_refs"]
        observed = set()
        for row in refs:
            key = (row["repository"], row["branch"])
            if (key in observed or not re.fullmatch(r"[A-Za-z0-9_.-]+", key[0])
                    or key[1] not in {"main", "gh-pages"}
                    or (row["commit"] is not None and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", row["commit"]))):
                raise ContractError("Publish gate: invalid rehearsal remote refs")
            observed.add(key)
        if not destinations(root, project, manifest).issubset(observed):
            raise ContractError("Publish gate: rehearsal does not cover every destination branch")
        for row in refs:
            if host.ref(row["repository"], row["branch"]) != row["commit"]:
                raise ContractError(f"Publish gate: rehearsal remote ref changed: {row['repository']}/{row['branch']}")
    except ContractError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ContractError(f"Publish gate: invalid rehearsal receipt: {exc}") from None
    return {"workspace_commit": commit, "origin": origin, "ci_run_id": latest["id"],
            "ci_run_attempt": latest.get("run_attempt", 1), "merged_pr": merged.get("number"),
            "checked_utc": datetime.now(timezone.utc).isoformat(), "rehearsal": receipt}
