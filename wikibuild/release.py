"""Coordinate immutable reader releases across independently owned Git repositories."""

import json
from pathlib import Path
import re

from . import extraction, git_transaction, physical, reader, release_output, release_partitions, release_prepare, workspace
from . import staging
from .storage import ContractError, digest, git, json_bytes, within, write_changed

OWNER_FILE = release_output.OWNER_FILE


def immutable(path, value):
    data = json_bytes(value)
    if path.exists() and path.read_bytes() != data:
        raise ContractError(f"Release receipt differs: {path}")
    write_changed(path, data)


def contract():
    folder = Path(__file__).parent
    return {name: digest((folder / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in ("release.py", "release_prepare.py", "entrypoints.py", "release_content.py", "release_output.py", "ownership.py", "release_partitions.py",
                         "capacity.py", "capacity_inventory.py", "capacity_projection.py", "shard_index.py", "capture_catalog.py", "physical.py",
                         "git_transaction.py", "publication_git.py", "release_bootstrap.js", "workspace.py")}


def bases(project):
    return {repo["id"]: f"https://{project['github_owner']}.github.io/{repo['github_name']}/"
            for repo in project["repositories"]}


owned = release_output.owned


def preflight(root, project):
    for repo in workspace.repositories(root, project):
        state = workspace.inspect(root, repo)
        if state["state"] != "clean":
            raise ContractError(f"Release destination {repo['id']} is {state['state']}")
        path = within(root, repo["path"])
        owned(path)


def read(root, release_id):
    if not re.fullmatch(r"[0-9a-f]{64}", release_id):
        raise ContractError("Invalid release identity")
    value = json.loads(within(root, f"releases/{release_id}.json").read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or value.get("release_id") != release_id or digest(json_bytes(value["inputs"])) != release_id:
        raise ContractError("Release identity differs")
    if value.get("manifest_sha256") != digest(json_bytes({key: item for key, item in value.items() if key != "manifest_sha256"})):
        raise ContractError("Release manifest content differs")
    return value


def verify(root, value, *, check_checkout=True, reviewed_project=None):
    if reviewed_project is not None:
        if not check_checkout:
            raise ContractError("Reviewed successors require checkout validation")
        workspace.checkout_lock(root, reviewed_project, check=True)
    for topic, record in value["repositories"].items():
        path = within(root, record["path"])
        if git(path, "rev-parse", record["commit"] + "^{tree}") != record["tree"]:
            raise ContractError(f"Release commit tree differs: {topic}")
        if check_checkout:
            head = git(path, "rev-parse", "HEAD")
            if git(path, "status", "--porcelain=v1", "--untracked-files=all"):
                raise ContractError(f"Release checkout differs: {topic}")
            if head != record["commit"]:
                if reviewed_project is None:
                    raise ContractError(f"Release checkout differs: {topic}")
                # Only allocation for a new release accepts reviewed authored commits.
                # Current publication/reuse still requires the exact release HEAD.
                git(path, "merge-base", "--is-ancestor", record["commit"], head)
            if extraction.file_hash(path / OWNER_FILE) != record["ownership_sha256"]:
                raise ContractError(f"Release ownership receipt differs: {topic}")
            owned(path)


def inventory(root, project):
    """Caller holds the workspace lock; validate records before allocation."""
    from . import capacity_inventory, publication
    pointer = root / "releases/latest.json"
    identity = json.loads(pointer.read_text(encoding="utf-8"))["release_id"] if pointer.exists() else None
    manifest = read(root, identity) if identity else None
    if manifest:
        repositories = physical.repositories(project, manifest.get("physical"))
        if set(manifest["repositories"]) != {repo["id"] for repo in repositories}:
            raise ContractError("Release outputs differ from the physical registry")
        verify(root, manifest, reviewed_project=project)
    published = publication.published(root)
    return capacity_inventory.read(root, project, manifest, published)


def resume(root, journal):
    stage = staging.child(Path(root) / ".local/rs", Path(root) / journal["stage"])
    for entry in journal.get("new_repositories", []):
        release_partitions.install(root, entry)
    for repo in physical.repositories(journal["project"], journal["result"].get("physical")):
        workspace.inspect(root, repo)
        item = journal["plans"][repo["id"]]
        git_transaction.validate(within(root, item["path"]), item["git"])
    for repo in journal["order"]:
        item = journal["plans"][repo]
        git_transaction.promote(within(root, item["path"]), stage / repo, item["git"])
    result = journal["result"]
    verify(root, result)
    immutable(within(root, f"releases/{result['release_id']}.json"), result)
    workspace.checkout_lock(root, journal["project"], allocated=journal["result"].get("physical"))
    write_changed(within(root, "releases/latest.json"), json_bytes({"release_id": result["release_id"]}))
    # Keep the journal for diagnosis. A completed pointer is safe to replay.
    write_changed(within(root, ".local/releases/pending.json"), json_bytes({"stage": journal["stage"], "complete": True}))
    return result


def run(root, project, candidate):
    """Caller holds writer_lock. Complete any prepared transaction before new work."""
    pending = within(root, ".local/releases/pending.json")
    if pending.exists():
        pointer = json.loads(pending.read_text(encoding="utf-8"))
        if not pointer["complete"]:
            stage = staging.child(Path(root) / ".local/rs", Path(root) / pointer["stage"])
            data = staging.regular(stage / "plan.json").read_bytes()
            if digest(data) != pointer["sha256"]:
                raise ContractError("Pending release journal was modified")
            journal = json.loads(data)
            stage = staging.child(Path(root) / ".local/rs", Path(root) / journal["stage"])
            if (stage / staging.OWNER).exists():
                staging.finish(stage, "release", "completed")
            resume(root, journal)
    manifest = reader.verify(Path(candidate["path"]), candidate["candidate_id"])
    templates = reader.issue_templates(root)
    if {name: digest(data) for name, data in templates.items()} != manifest["inputs"].get("issue_templates"):
        raise ContractError("Issue template inputs changed after reader build")
    inputs = {"reader": candidate["candidate_id"], "contract": contract(), "project_sha256": digest(json_bytes(project))}
    release_id = digest(json_bytes(inputs))
    existing = within(root, f"releases/{release_id}.json")
    if existing.exists():
        result = read(root, release_id)
        verify(root, result)
        latest = json.loads(within(root, "releases/latest.json").read_text())["release_id"]
        if latest != release_id:
            raise ContractError("An older release cannot rewind the current checkout")
        return result, {"reused": True}
    preflight(root, project)
    workspace.checkout_lock(root, project, check=True)
    from . import publication
    committed = inventory(root, project)
    previous = publication.published(root)
    prepared, outputs = release_prepare.prepare(root, project, candidate, release_id, committed, previous, templates)
    stage = staging.child(Path(root) / ".local/rs", Path(root) / prepared["stage"])
    try:
        if contract() != inputs["contract"]:
            raise ContractError("Release rules changed during preparation")
        reader.verify(Path(candidate["path"]), candidate["candidate_id"])
        if reader.issue_templates(root) != templates:
            raise ContractError("Issue template inputs changed during release preparation")
        result = {"schema_version": 1, "release_id": release_id, "inputs": inputs,
                  "reader_candidate": candidate["candidate_id"], "versions": manifest["versions"],
                  "routes": manifest["inputs"]["bases"], **outputs,
                  "status": "git-release-committed", "publication": "not-published",
                  "validation": {"reader_artifacts": "passed", "gameplay_verification": "not-performed", "coverage": "partial"}}
        result["manifest_sha256"] = digest(json_bytes(result))
        journal = {**prepared, "project": project, "result": result}
        immutable(stage / "plan.json", journal)
        write_changed(pending, json_bytes({"stage": journal["stage"], "sha256": digest(json_bytes(journal)), "complete": False}))
    except Exception:
        staging.finish(stage, "release", "abandoned")
        staging.retire(stage.parent, "release", current=stage)
        raise
    staging.finish(stage, "release", "completed")
    staging.retire(stage.parent, "release", current=stage)
    return resume(root, journal), {"reused": False}
