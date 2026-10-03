"""Prepare exact Git commits, then resume only recorded generated-file changes."""

import os
from pathlib import Path

from . import bounded

from .extraction import file_hash
from .storage import ContractError, git, within

# Local object/ref plumbing should finish quickly, including local Git hooks.
GIT_TIMEOUT = 30
# Index writes and tree scans may touch every generated file in a release.
GIT_TREE_TIMEOUT = 600


def command(path, *args, data=None, index=None, work_tree=None):
    environment = os.environ.copy()
    if index:
        environment["GIT_INDEX_FILE"] = str(index)
    if work_tree:
        environment["GIT_WORK_TREE"] = str(work_tree)
    options = args
    while options[:1] == ("-c",) and len(options) >= 2:
        options = options[2:]
    operation = options[0] if options else ""
    timeout = GIT_TREE_TIMEOUT if operation in {"add", "read-tree", "write-tree", "ls-tree", "diff-files", "ls-files"} else GIT_TIMEOUT
    result = bounded.run(["git", "-C", str(path), "--literal-pathspecs", *args],
                         timeout=timeout, input=data, env=environment)
    if result.returncode:
        raise ContractError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def changed_paths(path):
    tracked = command(path, "diff-files", "--name-only", "-z")
    untracked = command(path, "ls-files", "--others", "--exclude-standard", "-z")
    return {name.decode("utf-8") for name in (tracked + untracked).split(b"\0") if name}


def prepare(path, stage, files, message):
    """files maps each authorized path to its previous/new SHA-256 and byte count."""
    if git(path, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ContractError(f"Destination is dirty: {path}")
    base = git(path, "rev-parse", "HEAD")
    branch = git(path, "symbolic-ref", "HEAD")
    old_tree = git(path, "rev-parse", "HEAD^{tree}")
    for name, record in files.items():
        target = within(path, name)
        actual = file_hash(target) if target.is_file() else None
        if target.is_symlink() or actual != record["old"]:
            raise ContractError(f"Unowned or modified destination: {target}")
        staged = within(stage, name)
        if record["new"] is None:
            if record["old"] is None or record["bytes"] != 0 or staged.exists():
                raise ContractError(f"Invalid prepared deletion: {name}")
            continue
        if staged.stat().st_size != record["bytes"] or file_hash(staged) != record["new"]:
            raise ContractError(f"Prepared content differs: {name}")
    index = stage / "commit.index"
    command(path, "read-tree", base, index=index)
    pathspec = stage / "commit.paths"
    pathspec.write_bytes(b"".join(name.encode("utf-8") + b"\0" for name in sorted(files)))
    command(path, "-c", "core.autocrlf=false", "add", "--pathspec-from-file=" + str(pathspec),
            "--pathspec-file-nul", index=index, work_tree=stage)
    tree = command(path, "write-tree", index=index).decode().strip()
    commit = base if tree == old_tree else command(path, "commit-tree", tree, "-p", base,
                                                   data=(message + "\n").encode()).decode().strip()
    return {"base": base, "branch": branch, "old_tree": old_tree, "tree": tree, "commit": commit, "files": files}


def validate(path, plan):
    if git(path, "symbolic-ref", "HEAD") != plan["branch"] or git(path, "rev-parse", "HEAD") not in {plan["base"], plan["commit"]}:
        raise ContractError(f"Destination branch changed during release: {path}")
    tree = git(path, "write-tree")
    if tree not in {plan["old_tree"], plan["tree"]}:
        raise ContractError(f"Destination index changed during release: {path}")
    unexpected = changed_paths(path) - set(plan["files"])
    if unexpected:
        raise ContractError(f"Unrelated destination edits: {sorted(unexpected)[:8]}")
    for name, record in plan["files"].items():
        target = within(path, name)
        value = file_hash(target) if target.is_file() else None
        if target.is_symlink() or value not in {record["old"], record["new"]}:
            raise ContractError(f"Generated file changed outside this release: {target}")


def promote(path, stage, plan):
    """Caller owns the umbrella writer lock and has durably saved this plan."""
    validate(path, plan)
    for name, record in sorted(plan["files"].items()):
        target = within(path, name)
        if record["new"] is None:
            if not target.exists():
                continue
            if not target.is_file() or file_hash(target) != record["old"]:
                raise ContractError(f"Destination changed before file removal: {name}")
            target.unlink()
            continue
        if target.is_file() and file_hash(target) == record["new"]:
            continue
        source = within(stage, name)
        if source.stat().st_size != record["bytes"] or file_hash(source) != record["new"]:
            raise ContractError(f"Release staging was modified: {name}")
        # Temporary writes are outside generated paths and ignored by Git. A
        # crash leaves recoverable staging, never an unknown half-written page.
        temporary = within(path, ".local/release-writes/" + record["new"] + ".tmp")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(source.read_bytes())
        target.parent.mkdir(parents=True, exist_ok=True)
        value = file_hash(target) if target.is_file() else None
        if value != record["old"]:
            raise ContractError(f"Destination changed before file promotion: {name}")
        os.replace(temporary, target)
    validate(path, plan)
    if git(path, "write-tree") != plan["tree"]:
        # Two-tree merge preserves unrelated staged changes if another Git
        # client races us; the exact-tree check then refuses branch promotion.
        # Our journal has already validated and promoted the working files.
        # Merge only the index, retaining Git's staged-change conflict checks.
        git(path, "read-tree", "-i", "-m", plan["old_tree"], plan["tree"])
    if git(path, "write-tree") != plan["tree"]:
        raise ContractError("Index differs from the prepared release tree")
    if git(path, "rev-parse", "HEAD") != plan["commit"]:
        git(path, "update-ref", "-m", "Human Host Wiki release", plan["branch"], plan["commit"], plan["base"])
    if git(path, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ContractError(f"Destination differs after commit: {path}")
