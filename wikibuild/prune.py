"""Delete local state the next update does not need; keep only the latest of each.

Kept: the latest identity state and models (plus a migration baseline, which the
migration record validates against), the latest extraction run, the reader
candidates named by the reader pointer and the latest release, and the release
stage named by the completed release journal. Everything else in the owned
folders below is removed. Run receipts in identity/runs and identity/requests stay:
they are small and keep the identity chain readable. Nothing outside these
folders is touched, and nothing is removed while another writer holds the lock.
"""

import json
import os
from pathlib import Path
import re
import shutil
import stat

from . import history, identity_migration
from .storage import ContractError, within, writer_lock

# Owned folder, whether its entries are files or directories, and the only names removed.
OWNED = {"states": ("identity/states", False, r"[0-9a-f]{64}\.jsonl"),
         "models": (".local/history/objects", False, r"[0-9a-f]{64}\.jsonl"),
         "extraction-runs": (".local/extractions/runs", False, r"[0-9a-f]{64}\.json"),
         "extraction-objects": (".local/extractions/objects", False, r"[0-9a-f]{64}\.jsonl?"),
         "readers": (".local/readers", True, r"[0-9a-f]{24}|[0-9a-f]{64}"),
         "reader-stage": (".local/reader-stage", True, r"[0-9a-f]{32}"),
         "release-stage": (".local/rs", True, r"[0-9a-f]{12}")}


def folder(root, relative):
    """A literal owned directory: no symlink or junction on the way or at the end."""
    current = Path(root)
    for part in Path(relative).parts:
        current = current / part
        if current.exists() and redirected(current):
            raise ContractError(f"Prune target is redirected: {relative}")
    if within(root, relative) != current:
        raise ContractError(f"Prune target escapes the wiki root: {relative}")
    if current.exists() and not current.is_dir():
        raise ContractError(f"Prune target is not a directory: {relative}")
    return current


def redirected(path):
    info = os.lstat(path)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def size(path):
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())


def json_file(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def artifact_paths(value):
    """Every artifact path a run receipt names, at any depth."""
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            yield value["path"]
        for item in value.values():
            yield from artifact_paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from artifact_paths(item)


def keep_sets(root):
    """Return {category: names to keep} or raise when the latest state is not settled."""
    pending = json_file(within(root, ".local/releases/pending.json"))
    if pending is not None and not pending.get("complete"):
        raise ContractError("A release transaction is pending; finish it before pruning")
    latest = history.latest(root)
    if latest is None:
        raise ContractError("No identity run; nothing can be pruned safely")
    history.read(root, latest["run_id"])  # The kept state and models must be intact.
    states = {Path(latest["state"]["path"]).name}
    migration = identity_migration.read(root)
    if migration:
        states.add(Path(migration["baseline"]["path"]).name)
    extraction_runs = {latest["extraction_run"]}
    pointer = json_file(within(root, ".local/extraction-latest.json"))
    if pointer:
        extraction_runs.add(pointer["run_id"])
    objects = set()
    for identity in extraction_runs:
        receipt = json_file(within(root, f".local/extractions/runs/{identity}.json"))
        if receipt is None:
            raise ContractError(f"Latest extraction run receipt is missing: {identity}")
        objects.update(Path(name).name for name in artifact_paths(receipt) if name.startswith(".local/extractions/objects/"))
    candidates = set()
    reader_pointer = json_file(within(root, ".local/reader-latest.json"))
    release_pointer = json_file(within(root, "releases/latest.json"))
    for identity in ([reader_pointer["candidate_id"]] if reader_pointer else []) + (
            [json_file(within(root, f"releases/{release_pointer['release_id']}.json"))["reader_candidate"]] if release_pointer else []):
        candidates.update({identity, identity[:24]})
    return {"states": states, "models": {Path(latest["models"]["path"]).name},
            "extraction-runs": {identity + ".json" for identity in extraction_runs}, "extraction-objects": objects,
            "readers": candidates, "reader-stage": set(),
            "release-stage": {Path(pending["stage"]).name} if pending else set()}


def plan(root):
    keep = keep_sets(root)
    targets = {}
    for category, (relative, directories, pattern) in OWNED.items():
        base = folder(root, relative)
        targets[category] = []
        if not base.exists():
            continue
        for entry in sorted(base.iterdir()):
            if entry.name in keep[category]:
                continue
            if redirected(entry):
                raise ContractError(f"Prune target contains a redirected entry: {entry}")
            # Unknown names and kinds are kept: only generated entries are removed.
            if re.fullmatch(pattern, entry.name) and (entry.is_dir() if directories else entry.is_file()):
                targets[category].append(entry)
    return keep, targets


def delete(path):
    def writable(function, name, _):
        os.chmod(name, stat.S_IWRITE)
        function(name)
    if path.is_dir():
        shutil.rmtree(path, onerror=writable)
    else:
        try:
            path.unlink()
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()


def run(root, dry_run=False):
    """Take the writer lock (refusing if held), plan every deletion, then delete."""
    with writer_lock(root):
        keep, targets = plan(root)
        summary = {"dry_run": dry_run, "kept": {category: sorted(names) for category, names in keep.items()},
                   "removed": {}, "bytes": 0}
        for category, entries in targets.items():
            summary["removed"][category] = len(entries)
            for entry in entries:
                summary["bytes"] += size(entry)
                if not dry_run:
                    delete(entry)
        return summary
