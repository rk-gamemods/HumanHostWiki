"""Share verified immutable reader files without evicting historical previews."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from . import staging
from .storage import ContractError, digest, json_bytes, within, write_changed

MAX_MANIFEST_BYTES = 8 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}")


def contract():
    return digest(Path(__file__).read_bytes().replace(b"\r\n", b"\n"))


def checked(root, name):
    relative = PurePosixPath(name)
    if (relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name
            or relative.as_posix() != name):
        raise ContractError(f"Invalid reader cache path: {name}")
    literal = root / relative
    if literal != within(root, name) or literal.is_symlink():
        raise ContractError(f"Redirected reader cache path: {name}")
    return literal


def metadata(path):
    with path.open("rb") as stream:
        data = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise ContractError("Reader cache metadata exceeds 8 MiB; retained")
    return json.loads(data), digest(data)


def signature(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_mode


def inventory(folder):
    """Never traverse redirects; Windows directory entries omit file identities."""
    files = {}
    pending = [folder]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if (stat.S_ISLNK(info.st_mode)
                        or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                    raise ContractError("Reader candidate contains a redirected path")
                path = Path(entry.path)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    files[path.relative_to(folder).as_posix()] = path.stat() if os.name == "nt" else info
                else:
                    raise ContractError("Reader candidate contains a non-regular file")
    return files


def verified_files(root, folder, manifest, manifest_hash, verified, summary):
    """Validate an entire candidate before allowing any of its files to be shared."""
    actual = inventory(folder)
    records = manifest["files"]
    if set(actual) != set(records) | {"candidate.json"}:
        raise ContractError("Reader candidate contains missing or unknown files")
    if metadata(folder / "candidate.json")[1] != manifest_hash:
        raise ContractError("Reader candidate manifest changed during cleanup")
    result = []
    for name, record in records.items():
        path = checked(root, (folder / name).relative_to(root).as_posix())
        info = actual[name]
        if info.st_size != record["bytes"]:
            raise ContractError(f"Reader candidate size changed: {name}")
        key = signature(info)
        if key not in verified:
            sha = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    sha.update(chunk)
                    summary["verified_bytes"] += len(chunk)
            if signature(path.stat()) != key:
                raise ContractError(f"Reader candidate changed during verification: {name}")
            verified[key] = sha.hexdigest()
            summary["verified_files"] += 1
        if verified[key] != record["sha256"]:
            raise ContractError(f"Reader candidate hash changed: {name}")
        result.append((path, info, (record["sha256"], record["bytes"])))
    return result


def replace_duplicate(root, source, target, expected):
    """Atomic rename keeps readers on complete identical bytes, including on retry."""
    source_path = source[0]
    target_path = target[0]
    for path, info in (source, target):
        if signature(checked(root, path.relative_to(root).as_posix()).stat()) != signature(info):
            raise ContractError("Reader file changed before sharing; retained")
    name = digest(target_path.relative_to(root).as_posix().encode()) + ".link"
    temporary = checked(root, ".local/reader-retention/links/" + name)
    temporary.parent.mkdir(parents=True, exist_ok=True)
    if temporary.exists():
        if not os.path.samefile(temporary, source_path):
            raise ContractError("Unknown reader sharing temporary file; retained")
    else:
        os.link(source_path, temporary)
    # A crash leaves either the original complete file or the verified hard link.
    # A leftover temporary is reusable only when it is still this source inode.
    try:
        for path, info in (source, target):
            if signature(checked(root, path.relative_to(root).as_posix()).stat()) != signature(info):
                raise ContractError("Reader file changed before replacement; retained")
        before = target_path.stat()
        os.replace(temporary, target_path)
        return expected[1] if before.st_nlink == 1 else 0
    finally:
        if temporary.exists() and os.path.samefile(temporary, source_path):
            temporary.unlink()  # Ordinary unlink only; never override protection.


def run(root):
    """Caller holds writer_lock. Housekeeping failures stay separate from content."""
    root = Path(root).resolve()
    summary = {"reused": True, "linked_files": 0, "linked_bytes": 0,
               "released_file_bytes": 0, "verified_files": 0, "verified_bytes": 0, "retained": []}
    candidates = {}
    retired = staging.retire(root / ".local/reader-stage", "reader")
    # Staging names its entries by stage; reader retention reports candidates.
    summary["retained"].extend({"candidate": row["stage"], "reason": row["reason"]} for row in retired["retained"])
    if retired["removed"]:
        summary["reused"] = False
    try:
        folder = checked(root, ".local/readers")
        if not folder.exists():
            return summary
        for entry in sorted(folder.iterdir()):
            try:
                if not re.fullmatch(r"[0-9a-f]{24}|[0-9a-f]{64}", entry.name):
                    raise ContractError("Unknown reader cache entry; retained")
                path = checked(root, entry.relative_to(root).as_posix() + "/candidate.json")
                manifest, sha = metadata(path)
                identity = manifest["candidate_id"]
                if (manifest.get("schema_version") != 1 or not isinstance(identity, str)
                        or not HASH.fullmatch(identity) or entry.name not in {identity, identity[:24]}
                        or identity != digest(json_bytes(manifest["inputs"]))):
                    raise ContractError("Reader candidate identity differs")
                records = manifest["files"]
                if not isinstance(records, dict) or "candidate.json" in records:
                    raise ContractError("Invalid reader file manifest")
                for name, record in records.items():
                    relative = PurePosixPath(name)
                    if (relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name
                            or relative.as_posix() != name or not isinstance(record["sha256"], str)
                            or not HASH.fullmatch(record["sha256"]) or type(record["bytes"]) is not int
                            or record["bytes"] < 0):
                        raise ContractError("Invalid reader file record")
                candidates[entry] = manifest, sha
            except (OSError, ValueError, KeyError, TypeError) as exc:
                summary["retained"].append({"candidate": entry.name, "reason": str(exc)})
        receipt = {"schema_version": 1, "contract": contract(),
                   "candidates": {entry.name: sha for entry, (_, sha) in candidates.items()}}
        marker = checked(root, ".local/reader-retention/completed.json")
        if not summary["retained"] and marker.exists() and metadata(marker)[0] == receipt:
            return summary
        summary["reused"] = False
        verified, groups = {}, {}
        for entry, (manifest, sha) in candidates.items():
            try:
                files = verified_files(root, entry, manifest, sha, verified, summary)
                for path, info, key in files:
                    groups.setdefault(key, []).append((path, info))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                summary["retained"].append({"candidate": entry.name, "reason": str(exc)})
        for key, files in groups.items():
            source = files[0]
            for target in files[1:]:
                if (source[1].st_dev, source[1].st_ino) == (target[1].st_dev, target[1].st_ino):
                    continue
                try:
                    freed = replace_duplicate(root, source, target, key)
                    summary["linked_files"] += 1
                    summary["linked_bytes"] += key[1]
                    summary["released_file_bytes"] += freed
                except (OSError, ValueError) as exc:
                    summary["retained"].append({"candidate": target[0].relative_to(folder).as_posix(), "reason": str(exc)})
        if not summary["retained"]:
            write_changed(marker, json_bytes(receipt))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        summary["retained"].append({"candidate": ".local/readers", "reason": str(exc)})
    try:
        write_changed(checked(root, ".local/reader-retention/report.json"), json_bytes({"retained": summary["retained"]}))
    except (OSError, ValueError) as exc:
        summary["retained"].append({"candidate": "report", "reason": str(exc)})
    return summary
