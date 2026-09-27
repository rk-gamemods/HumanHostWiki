"""Manage local repository boundaries; never create a remote or publish."""

import json
import os
import uuid

from .storage import ContractError, digest, git, json_bytes, within, write_changed


def marker(repo):
    value = {"schema_version": 1, "repository_id": repo["id"], "role": repo["role"]}
    if repo["role"] in {"partition", "entrypoint"}:
        value.update(logical_topic=repo["logical_topic"], ordinal=repo["ordinal"])
    return value


def repositories(root, project, allocated=None):
    from . import physical, release
    if allocated is None and (root / "releases/latest.json").exists():
        identity = json.loads((root / "releases/latest.json").read_text())["release_id"]
        allocated = release.read(root, identity).get("physical")
    return physical.repositories(project, allocated)


def seed_readme(repo):
    return (f"# {repo['title']}\n\n{repo['coverage']}.\n\n"
            "This repository is initialized for Human Host Wiki. Topic content is not generated yet.\n"
            "The umbrella's `project.json` owns its identity, routing and shared build contracts.\n\n"
            "## Ownership\n\n" + ", ".join(f"`{kind}`" for kind in repo["owns"]) + "\n").encode()


def inspect(root, repo):
    path = within(root, repo["path"])
    if not path.exists():
        return {"id": repo["id"], "state": "absent"}
    if not (path / ".git").is_dir():
        raise ContractError(f"Not an independent repository: {path}")
    if git(path, "rev-parse", "--show-toplevel").replace("\\", "/").casefold() != path.as_posix().casefold():
        raise ContractError(f"Repository root mismatch: {path}")
    identity = path / ".wiki-repository.json"
    if not identity.exists() or json.loads(identity.read_text()) != marker(repo):
        raise ContractError(f"Unknown repository ownership: {path}")
    changes = git(path, "status", "--porcelain=v1", "--untracked-files=all")
    return {"id": repo["id"], "state": "dirty" if changes else "clean", "changes": changes.splitlines(),
            "remotes": git(path, "remote").splitlines()}


def initialize(root, manifest):
    # Preflight every destination before creating any repository.
    states = [inspect(root, repo) for repo in manifest["repositories"]]
    created = []
    for repo, state in zip(manifest["repositories"], states):
        if state["state"] != "absent":
            continue
        destination = within(root, repo["path"])
        path = within(root, f".local/repository-stage/{repo['id']}-{uuid.uuid4().hex}")
        path.mkdir(parents=True)
        git(path, "init", "--initial-branch=main")
        write_changed(path / ".wiki-repository.json", json_bytes(marker(repo)))
        write_changed(path / "README.md", seed_readme(repo))
        write_changed(path / ".gitignore", b".local/\n__pycache__/\n*.local.json\n")
        write_changed(path / ".gitattributes", b"* text=auto eol=lf\n")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(path, destination)
        created.append(repo["id"])
    return created


def checkout_lock(root, manifest, check=False, *, allocated=None):
    """Pin clean local commits without claiming a coordinated wiki release."""
    records = {}
    for repo in repositories(root, manifest, allocated):
        state = inspect(root, repo)
        if state["state"] != "clean":
            raise ContractError(f"Cannot pin {repo['id']}: checkout is {state['state']}")
        path = within(root, repo["path"])
        revision = git(path, "rev-parse", "--verify", "HEAD")
        records[repo["id"]] = {"commit": revision, "path": repo["path"], "github_name": repo["github_name"]}
    result = {"schema_version": 1, "kind": "local-checkout-baseline", "project_sha256": digest(json_bytes(manifest)),
              "repositories": records}
    path = within(root, "workspace.lock.json")
    data = json_bytes(result)
    if check:
        if not path.exists() or path.read_bytes() != data:
            raise ContractError("Checkout lock differs from registry or current child commits")
    else:
        write_changed(path, data)
    return result
