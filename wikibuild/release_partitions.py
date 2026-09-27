"""Prepare new local storage repositories and install them only from a saved journal."""

import html
import json
import os

from . import physical, workspace
from .storage import ContractError, git, json_bytes, within


def seed(root, stage, repo, owner):
    destination = within(root, repo["path"])
    if destination.exists():
        raise ContractError(f"New partition destination already exists: {destination}")
    path = stage / "new" / repo["id"]
    path.mkdir(parents=True)
    git(path, "init", "--initial-branch=main")
    # Match the owning topic's effective Git identity, including repository-local
    # configuration. Never invent an author or modify the user's global config.
    for setting in ("user.name", "user.email"):
        value = git(within(root, owner["path"]), "config", "--get", setting)
        git(path, "config", setting, value)
    for name, data in {".wiki-repository.json": json_bytes(workspace.marker(repo)),
                       ".gitignore": b".local/\n__pycache__/\n*.local.json\n",
                       ".gitattributes": b"* text=auto eol=lf\n"}.items():
        (path / name).write_bytes(data)
    git(path, "add", ".wiki-repository.json", ".gitignore", ".gitattributes")
    git(path, "commit", "-m", "Initialize wiki storage " + repo["id"])
    return path, {"source": path.relative_to(root).as_posix(), "path": repo["path"],
                  "repo": repo, "seed_commit": git(path, "rev-parse", "HEAD")}


def install(root, entry):
    source, target = within(root, entry["source"]), within(root, entry["path"])
    if target.exists():
        workspace.inspect(root, entry["repo"])
        if source.exists():
            raise ContractError("Both staged and destination partition repositories exist")
        return  # The prepared Git plan validates the installed checkout next.
    if not source.is_dir() or git(source, "rev-parse", "HEAD") != entry["seed_commit"]:
        raise ContractError("Prepared partition seed differs")
    if git(source, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ContractError("Prepared partition seed was modified")
    if json.loads((source / ".wiki-repository.json").read_bytes()) != workspace.marker(entry["repo"]):
        raise ContractError("Prepared partition identity differs")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(source, target)


def landing(writer, project, repo):
    owner = next(item for item in project["repositories"] if item["id"] == repo["logical_topic"])
    url = physical.base(project, owner)
    title = html.escape(repo["title"])
    page = (f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title>'
            f'<h1>{title}</h1><p>Immutable reference storage. '
            f'<a href="{html.escape(url, quote=True)}">Browse {html.escape(owner["title"])}</a>.</p></html>\n').encode()
    writer.add("site/index.html", page)
    writer.add("site/.nojekyll", b"")
