"""Owned private attempts and bounded retirement, under the caller's writer lock."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import uuid

from .storage import ContractError, json_bytes, write_changed

OWNER = "attempt.json"
MAX_ENTRIES = 100_000
MAX_RECORD_BYTES = 4096


def regular(path):
    """Check ancestors as well as leaves; never follow a junction or symlink."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if not item.exists() and not item.is_symlink():
            continue
        info = item.lstat()
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ContractError(f"Redirected staging path: {item}")
    return path


def record(path, stage):
    regular(path)
    marker = regular(path / OWNER)
    if not path.is_dir() or not marker.is_file():
        raise ContractError("Unrecognized staging directory; ownership record missing")
    with marker.open("rb") as stream:
        data = stream.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        raise ContractError("Staging ownership record exceeds its read bound")
    value = json.loads(data)
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("stage") != stage or value.get("attempt_id") != path.name
            or not re.fullmatch(r"[0-9a-f]{12}|[0-9a-f]{32}", path.name)
            or value.get("state") not in {"materializing", "completed", "abandoned"}):
        raise ContractError("Unrecognized staging ownership record")
    created = datetime.fromisoformat(value["created_utc"])
    if created.utcoffset() != timezone.utc.utcoffset(created):
        raise ContractError("Staging creation time must be UTC")
    return value, created


def finish(path, stage, state):
    value, _ = record(path, stage)
    if state not in {"completed", "abandoned"} or value["state"] == "completed" and state != "completed":
        raise ContractError("Invalid staging terminal transition")
    write_changed(path / OWNER, json_bytes({**value, "state": state}))


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode


def remove(path, stage, expected_owner):
    """Validate a bounded tree first; retain the ownership marker until last."""
    path = regular(path)
    pending, files, folders, count = [path], [], [], 0
    while pending:
        folder = pending.pop()
        folders.append(folder)
        with os.scandir(folder) as entries:
            for entry in entries:
                count += 1
                if count > MAX_ENTRIES:
                    raise ContractError("Staging deletion exceeds its entry bound")
                item = regular(Path(entry.path))
                info = item.lstat()
                if stat.S_ISDIR(info.st_mode):
                    pending.append(item)
                elif stat.S_ISREG(info.st_mode):
                    files.append((item, info))
                else:
                    raise ContractError("Staging contains a non-regular entry")
    marker = path / OWNER
    marker_info = next(info for item, info in files if item == marker)
    files = [(item, info) for item, info in files if item != marker]
    if record(path, stage)[0] != expected_owner:
        raise ContractError("Staging ownership changed before retirement")
    for item, expected in files:
        if signature(regular(marker).lstat()) != signature(marker_info):
            raise ContractError("Staging ownership changed before retirement")
        actual = regular(item).lstat()
        if signature(actual) != signature(expected):
            raise ContractError("Staging file changed before retirement")
        # These are owned disposable attempts, including read-only Git objects.
        if not actual.st_mode & stat.S_IWRITE:
            item.chmod(actual.st_mode | stat.S_IWRITE)
        item.unlink()
    for folder in reversed(folders[1:]):
        info = regular(folder).lstat()
        if not info.st_mode & stat.S_IWRITE:
            folder.chmod(info.st_mode | stat.S_IWRITE)
        folder.rmdir()
    if signature(regular(marker).lstat()) != signature(marker_info):
        raise ContractError("Staging ownership changed before retirement")
    if not marker_info.st_mode & stat.S_IWRITE:
        marker.chmod(marker_info.st_mode | stat.S_IWRITE)
    marker.unlink()
    info = regular(path).lstat()
    if not info.st_mode & stat.S_IWRITE:
        path.chmod(info.st_mode | stat.S_IWRITE)
    path.rmdir()


def retire(folder, stage, current=None):
    """Only valid records of this stage authorize retirement; report everything else."""
    folder = Path(folder).absolute()
    summary = {"removed": [], "retained": []}
    if not folder.exists():
        return summary
    attempts = []
    try:
        regular(folder)
        with os.scandir(folder) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_ENTRIES:
                    raise ContractError("Staging inventory exceeds its entry bound")
                path = Path(entry.path)
                try:
                    value, created = record(path, stage)
                    attempts.append((path, value, created))
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    summary["retained"].append({"stage": path.name, "reason": str(exc)})
        current = Path(current).absolute() if current is not None else None
        # A live current attempt is not stale. A just-abandoned current attempt
        # ranks newest under the writer lock, but is still never deleted here.
        failed = [(path, created) for path, value, created in attempts
                  if value["state"] != "completed"
                  and (path != current or value["state"] == "abandoned")]
        newest = max(failed, key=lambda row: (row[0] == current, row[1], row[0].name), default=(None, None))[0]
        for path, value, created in attempts:
            if value["state"] == "completed" or path == current:
                continue
            try:
                if path != newest:
                    remove(path, stage, value)
                    summary["removed"].append(path.name)
                elif value["state"] == "materializing":
                    finish(path, stage, "abandoned")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                summary["retained"].append({"stage": path.name, "reason": str(exc)})
        write_changed(folder.with_name(folder.name + "-retention.json"), json_bytes(summary))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        summary["retained"].append({"stage": str(folder), "reason": str(exc)})
    return summary


@contextmanager
def attempt(folder, stage, *, short=False, deferred=False):
    """Ordinary failures abandon; process interruptions leave materializing evidence."""
    folder = regular(folder)
    retire(folder, stage)
    identity = uuid.uuid4().hex[:12] if short else uuid.uuid4().hex
    path = folder / identity
    path.mkdir(parents=True)
    write_changed(path / OWNER, json_bytes({"schema_version": 1, "stage": stage,
                                           "attempt_id": identity,
                                           "created_utc": datetime.now(timezone.utc).isoformat(),
                                           "state": "materializing"}))
    try:
        yield path
    except Exception:
        finish(path, stage, "abandoned")
        raise
    else:
        if not deferred:
            finish(path, stage, "completed")
    finally:
        retire(folder, stage, current=path)
