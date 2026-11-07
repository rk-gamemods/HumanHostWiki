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
# Must match paths-ignore in .github/workflows/ci.yml (test_foundation checks this).
DATA_PREFIXES = ("availability/", "curation/runs/", "external-links/", "identity/requests/",
                 "identity/runs/", "identity/states/", "publications/", "releases/", "snapshots/")
DATA_FILES = {"curation/latest.json", "identity/latest.json", "workspace.lock.json"}
DATA_ONLY_DEPTH = 20
MERGED_PR_QUERY = ("query($owner: String!, $name: String!, $oid: GitObjectID!) { repository(owner: $owner, name: $name) "
                   "{ object(oid: $oid) { ... on Commit { associatedPullRequests(first: 10) { nodes { number merged mergeCommit { oid } } } } } } }")


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


def write_receipt(root, release_id, workspace_commit, remote_refs, destination_observations):
    from . import publication
    value = {"schema_version": 1, "release_id": release_id, "workspace_commit": workspace_commit,
             "contract": publication.contract(), "remote_refs": remote_refs,
             "destination_observations": destination_observations,
             "created_utc": datetime.now(timezone.utc).isoformat()}
    publication.save(receipt_path(root, release_id), value)
    return value


def ensure_clean(root):
    """Shared by rehearsal and publication, before any other work."""
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ContractError("Publish gate: workspace must be clean, including non-ignored untracked files")


def is_data(path):
    """Generated wiki data that no test or tool reads as code. Markdown is always code."""
    return not path.endswith(".md") and (path in DATA_FILES or path.startswith(DATA_PREFIXES))


def ci_run(host, commit, event="push"):
    """Newest CI run of this exact commit for a main push or a pull request, or None."""
    response = host.api("GET", f"repos/{WORKSPACE_REPOSITORY}/actions/runs?head_sha={commit}")
    if (not isinstance(response, dict) or not isinstance(response.get("workflow_runs"), list)
            or any(not isinstance(row, dict) for row in response["workflow_runs"])):
        raise ContractError("Publish gate: invalid CI response for this exact commit")
    runs = [row for row in response["workflow_runs"]
            if row.get("name") == "CI" and row.get("path") == CI_PATH
            and row.get("event") == event and (event != "push" or row.get("head_branch") == "main")
            and row.get("head_sha") == commit]
    if not runs:
        return None
    if any(type(row.get("id")) is not int or any(type(row.get(key, 0)) is not int
               for key in ("run_number", "run_attempt")) for row in runs):
        raise ContractError("Publish gate: invalid CI run identity for this exact commit")
    return max(runs, key=lambda row: (row.get("run_number", 0), row.get("run_attempt", 0), row["id"]))


def tested_run(root, host, commit):
    """CI that tested exactly this commit's tree, as (tested commit, run) or None.

    A main push run of the commit counts. So does the pull request run of a merge
    commit's second parent when both have the same tree: the merge added nothing,
    so the PR run tested the code being published and main need not test it again.
    """
    parents = git(root, "rev-list", "--parents", "-n", "1", commit).split()[1:]
    if len(parents) == 2 and git(root, "rev-parse", f"{commit}^{{tree}}") == git(root, "rev-parse", f"{parents[1]}^{{tree}}"):
        latest = ci_run(host, parents[1], "pull_request")
        if latest is not None and latest.get("status") == "completed" and latest.get("conclusion") == "success":
            return parents[1], latest
    latest = ci_run(host, commit)
    return (commit, latest) if latest is not None else None


def data_only_ci(root, host, commit):
    """Use the newest first-parent ancestor with CI when everything since it is data."""
    ancestors = git(root, "rev-list", "--first-parent", f"--max-count={DATA_ONLY_DEPTH + 1}", commit).split()
    for ancestor in ancestors[1:]:
        changed = git(root, "diff", "--name-only", "--no-renames", ancestor, commit).splitlines()
        if not all(is_data(path) for path in changed):
            break
        found = tested_run(root, host, ancestor)
        if found is not None:
            return found
    raise ContractError("Publish gate: CI is missing for this exact commit")


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
    # CI skips pushes that change only generated data. Such a commit carries the
    # exact code of a first-parent ancestor, so that ancestor's CI applies.
    ci_commit, latest = tested_run(root, host, commit) or data_only_ci(root, host, commit)
    if latest.get("status") != "completed":
        raise ContractError("Publish gate: CI has not completed for this exact commit")
    if latest.get("conclusion") != "success":
        raise ContractError("Publish gate: CI did not conclude success for this exact commit")

    # REST API 2026-03-10 returns merge_commit_sha as null; GraphQL still names the merge commit.
    owner, name = WORKSPACE_REPOSITORY.split("/")
    response = host.api("POST", "graphql", {"query": MERGED_PR_QUERY,
                                            "variables": {"owner": owner, "name": name, "oid": commit}})
    try:
        pulls = response["data"]["repository"]["object"]["associatedPullRequests"]["nodes"]
    except (KeyError, TypeError):
        pulls = None
    if not isinstance(pulls, list) or any(not isinstance(row, dict) for row in pulls):
        raise ContractError("Publish gate: invalid merged PR response for this exact commit")
    merged = next((row for row in pulls if row.get("merged") is True
                   and isinstance(row.get("mergeCommit"), dict) and row["mergeCommit"].get("oid") == commit), None)
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
        observations = receipt["destination_observations"]
        names = {name for name, branch in destinations(root, project, manifest)}
        covered = set()
        for row in observations:
            name = row["repository"]
            if name in covered or name not in names or row["observed"] not in {"absent", "pages-disabled", "present"}:
                raise ContractError("Publish gate: invalid rehearsal destination observations")
            covered.add(name)
            if github_pages.observe_configuration(host, project["github_owner"], name) != row:
                raise ContractError(f"Publish gate: rehearsal destination observation changed: {name}")
        if covered != names:
            raise ContractError("Publish gate: rehearsal does not cover every destination configuration")
    except ContractError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ContractError(f"Publish gate: invalid rehearsal receipt: {exc}") from None
    return {"workspace_commit": commit, "origin": origin, "ci_commit": ci_commit, "ci_run_id": latest["id"],
            "ci_run_attempt": latest.get("run_attempt", 1), "merged_pr": merged.get("number"),
            "checked_utc": datetime.now(timezone.utc).isoformat(), "rehearsal": receipt}
