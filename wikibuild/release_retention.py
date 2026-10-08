"""Remove committed release staging payloads; retain journals and recovery inputs."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess

from . import bounded, git_transaction, release, staging
from .storage import ContractError, digest, git_records, json_bytes, within, write_changed


def contract():
    return digest(Path(__file__).read_bytes().replace(b"\r\n", b"\n"))


def relative_path(name):
    """Validate lexical containment, including Windows separators and drive syntax."""
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ContractError(f"Invalid staging path: {name}")
    return relative


def regular(root, name):
    """Reject redirects, including directory junctions, before reading or unlinking."""
    relative = relative_path(name)
    literal = staging.regular(Path(root) / relative)
    resolved = within(root, name)
    if literal != resolved or literal.is_symlink():
        raise ContractError(f"Redirected staging path: {name}")
    return literal


def completed_journal(root, stage):
    """Bind a completed journal to its immutable release and compaction receipt."""
    relative = stage.relative_to(root).as_posix()
    plan_path = regular(root, relative + "/plan.json")
    if not plan_path.is_file():
        raise ContractError("No completed release journal; retained for recovery")
    data = plan_path.read_bytes()
    journal = json.loads(data)
    if journal["stage"] != relative:
        raise ContractError("Release journal names a different stage")
    result = release.read(root, journal["result"]["release_id"])
    if result != journal["result"] or set(result["repositories"]) != set(journal["plans"]):
        raise ContractError("Staging journal differs from the committed release")
    receipt = {"schema_version": 1, "stage": relative, "plan_sha256": digest(data),
               "release_id": result["release_id"]}
    marker = regular(root, ".local/releases/retention/" + stage.name + ".json")
    for identity, item in journal["plans"].items():
        saved, plan = result["repositories"][identity], item["git"]
        if (item["path"] != saved["path"] or plan["commit"] != saved["commit"]
                or plan["tree"] != saved["tree"]):
            raise ContractError("Staging destination differs from the committed release")
    return journal, result, receipt, marker


def completed_legacy(root, stage):
    """Retain proven pre-ownership metadata without inventing attempt ownership."""
    root = Path(root).resolve()
    stage = staging.child(root / ".local/rs", stage)
    if not re.fullmatch(r"[0-9a-f]{12}", stage.name) or regular(stage, staging.OWNER).exists():
        return False
    marker = regular(root, ".local/releases/retention/" + stage.name + ".json")
    if not marker.is_file():
        return False
    journal, _, receipt, marker = completed_journal(root, stage)
    if json.loads(marker.read_bytes()) != receipt:
        raise ContractError("Staging retention receipt differs")
    allowed_files = {"plan.json"}
    allowed_folders = {"."}
    for identity, item in journal["plans"].items():
        prefix = relative_path(identity)
        allowed_files.update((prefix / name).as_posix() for name in ("commit.index", "commit.paths"))
        for name in ["commit.index", "commit.paths", *item["git"]["files"]]:
            path = prefix / relative_path(name)
            allowed_folders.update(parent.as_posix() for parent in path.parents)
    pending, count = [stage], 0
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                count += 1
                if count > staging.MAX_ENTRIES:
                    raise ContractError("Legacy staging inventory exceeds its entry bound")
                path = staging.regular(Path(entry.path))
                name, mode = path.relative_to(stage).as_posix(), path.lstat().st_mode
                if stat.S_ISDIR(mode) and name in allowed_folders:
                    pending.append(path)
                elif not stat.S_ISREG(mode) or name not in allowed_files:
                    raise ContractError(f"Unrecognized legacy staging metadata: {name}")
    return True


def compact(root, stage, summary):
    """Caller holds writer_lock. Validate every payload before deleting any of them."""
    relative = stage.relative_to(root).as_posix()
    journal, result, receipt, marker = completed_journal(root, stage)
    if marker.exists():
        if json.loads(marker.read_bytes()) != receipt:
            raise ContractError("Staging retention receipt differs")
        return
    summary["reused"] = False
    removals = []
    for identity, item in journal["plans"].items():
        plan = item["git"]
        repository = regular(root, item["path"])
        # One tree read per repository. Stream local payloads in bounded chunks;
        # matching Git blob IDs independently proves the committed copy exists.
        blobs = {}
        for entry in git_records(repository, "--literal-pathspecs", "ls-tree", "-r", "-z", plan["commit"],
                                 timeout=git_transaction.GIT_TREE_TIMEOUT):
            if entry:
                metadata, name = entry.split(b"\t", 1)
                mode, kind, oid = metadata.split()
                if kind == b"blob" and mode in {b"100644", b"100755"}:
                    blobs[name.decode("utf-8")] = oid.decode("ascii")
        sizes = {}
        with bounded.stream(["git", "-C", str(repository), "--literal-pathspecs", "cat-file", "--batch-check"],
                            timeout=git_transaction.GIT_TREE_TIMEOUT, stdin=subprocess.PIPE) as child:
            for oid in sorted(set(blobs.values())):
                child.stdin.write((oid + "\n").encode())
                child.stdin.flush()
                fields = child.stdout.readline().split()
                if len(fields) != 3 or fields[1] != b"blob":
                    raise ContractError("Committed payload object is missing; staging retained")
                sizes[fields[0].decode("ascii")] = int(fields[2])
            child.stdin.close()
            if child.wait():
                raise ContractError(child.stderr.decode("utf-8", errors="replace").strip())
        for name, record in plan["files"].items():
            path = regular(root, relative + "/" + identity + "/" + name)
            if record["new"] is None or not path.exists():
                continue
            if not path.is_file() or name not in blobs:
                raise ContractError(f"Payload is not a committed regular file: {name}")
            stat = path.stat()
            if stat.st_size != record["bytes"] or sizes.get(blobs[name]) != stat.st_size:
                raise ContractError(f"Staged payload size changed: {name}")
            oid = blobs[name]
            algorithm = {40: "sha1", 64: "sha256"}.get(len(oid))
            if algorithm is None:
                raise ContractError("Unsupported Git object hash")
            blob = hashlib.new(algorithm)
            blob.update(f"blob {stat.st_size}\0".encode("ascii"))
            sha = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    blob.update(chunk)
                    sha.update(chunk)
            if sha.hexdigest() != record["new"] or blob.hexdigest() != oid:
                raise ContractError(f"Staged payload differs from its committed copy: {name}")
            removals.append((path, stat))
    for path, expected in removals:
        actual = regular(root, path.relative_to(root).as_posix()).stat()
        if (actual.st_size, actual.st_mtime_ns, actual.st_ino) != (expected.st_size, expected.st_mtime_ns, expected.st_ino):
            raise ContractError(f"Staged payload changed before removal: {path}")
        path.unlink()  # Never change permissions or override file protection.
        summary["removed_files"] += 1
        summary["removed_bytes"] += actual.st_size
    write_changed(marker, json_bytes(receipt))


def run(root):
    """Best-effort housekeeping after supported work, separate from content gaps."""
    root = Path(root).resolve()
    summary = {"reused": True, "removed_files": 0, "removed_bytes": 0, "retained": []}
    folder = regular(root, ".local/rs")
    if not folder.exists():
        return summary
    try:
        pending_path = regular(root, ".local/releases/pending.json")
        pending = json.loads(pending_path.read_bytes()) if pending_path.exists() else {}
        # Never clean anything while a transaction remains pending, even if its
        # release receipt was saved immediately before an interruption.
        if pending and pending.get("complete") is not True:
            raise ContractError("Release transaction remains pending; staging retained")
        retired = staging.retire(folder, "release", retained_completed=lambda stage: completed_legacy(root, stage))
        summary["retained"].extend(retired["retained"])
        if retired["removed"]:
            summary["reused"] = False
        stages = sorted(folder.iterdir())
    except (OSError, ValueError) as exc:
        summary["retained"].append({"stage": ".local/rs", "reason": str(exc)})
        stages = []
    for stage in stages:
        if not re.fullmatch(r"[0-9a-f]{12}", stage.name):
            summary["retained"].append({"stage": stage.name, "reason": "Unknown staging entry preserved"})
            continue
        try:
            if (stage / staging.OWNER).exists() and staging.record(stage, "release")[0]["state"] != "completed":
                continue
            compact(root, stage, summary)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            summary["retained"].append({"stage": stage.name, "reason": str(exc)})
    report = regular(root, ".local/releases/retention/report.json")
    try:
        write_changed(report, json_bytes({"retained": summary["retained"]}))
    except OSError as exc:
        summary["retained"].append({"stage": "report", "reason": str(exc)})
    return summary
