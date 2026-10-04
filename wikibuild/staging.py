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
FIELD_TYPES = {"schema_version": int, "stage": str, "attempt_id": str,
               "created_utc": str, "state": str}


def _checkpoint(point):
    """Inert seam overridden by subprocess process-death tests only."""


def _sync_directory(path):
    if os.name != "nt":  # Windows does not support opening directories for fsync.
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _durable_write(path, data):
    path = regular(path)
    existing = signature(path.lstat()) if path.exists() else None
    if existing is not None and path.read_bytes() == data:
        # A prior rename may have succeeded while either directory fsync failed.
        _sync_directory(path.parent.parent)
        _sync_directory(path.parent)
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    # Persist the directory's own entry, including a retry after its fsync failed.
    _sync_directory(path.parent.parent)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        written = signature(regular(temporary).lstat())
        os.replace(temporary, path)
        _sync_directory(path.parent)
        return written
    finally:
        if temporary.exists():
            temporary.unlink()


def regular(path):
    """Check ancestors as well as leaves; never follow a junction or symlink."""
    path = Path(path)
    if ".." in path.parts:
        raise ContractError(f"Invalid staging path: {path}")
    path = path.absolute()
    # Check from the root down, so even lstat on a leaf never traverses a redirect.
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ContractError(f"Redirected staging path: {item}")
    return path


def child(folder, path):
    """Validate a direct child of the literal stage root, without resolving either."""
    folder = regular(folder)
    path = Path(path).absolute()
    if path.parent != folder:
        raise ContractError(f"Staging attempt is not a direct child of {folder}: {path}")
    return regular(path)


def validate(value, path, stage):
    """The same exact scalar schema governs ownership reads and writes."""
    if (not isinstance(value, dict) or value.keys() != FIELD_TYPES.keys()
            or any(type(value[name]) is not kind for name, kind in FIELD_TYPES.items())
            or value["schema_version"] != 1
            or value["stage"] != stage or value["attempt_id"] != path.name
            or not re.fullmatch(r"[0-9a-f]{12}|[0-9a-f]{32}", path.name)
            or value["state"] not in {"materializing", "completed", "abandoned"}):
        raise ContractError("Unrecognized staging ownership record")
    try:
        created = datetime.fromisoformat(value["created_utc"])
    except ValueError as exc:
        raise ContractError("Unrecognized staging ownership record: invalid creation time") from exc
    if created.utcoffset() != timezone.utc.utcoffset(created):
        raise ContractError("Staging creation time must be UTC")
    return created


def record(path, stage, *, folder=None):
    path = child(folder, path) if folder is not None else regular(path)
    marker = regular(path / OWNER)
    if not path.is_dir() or not marker.is_file():
        raise ContractError("Unrecognized staging directory; ownership record missing")
    with marker.open("rb") as stream:
        data = stream.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        raise ContractError("Staging ownership record exceeds its read bound")
    try:
        value = json.loads(data)
    except (ValueError, RecursionError) as exc:
        raise ContractError("Unrecognized staging ownership record: invalid JSON") from exc
    return value, validate(value, path, stage)


def write_record(path, stage, value):
    path = regular(path)
    validate(value, path, stage)
    data = json_bytes(value)
    if len(data) > MAX_RECORD_BYTES:
        raise ContractError("Staging ownership record exceeds its write bound")
    _durable_write(path / OWNER, data)


def finish(path, stage, state):
    value, _ = record(path, stage)
    if (type(state) is not str or state not in {"completed", "abandoned"}
            or value["state"] == "completed" and state != "completed"):
        raise ContractError("Invalid staging terminal transition")
    write_record(path, stage, {**value, "state": state})


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode


def _directory_identity(path):
    info = regular(path).lstat()
    if not stat.S_ISDIR(info.st_mode) or not info.st_ino:
        raise ContractError("Staging directory has no usable identity")
    # Size/mtime change as children are removed. Birth time is stable on Windows;
    # Unix ctime is not a birth time and must not be used as one. This is a guard,
    # not proof of content ownership: an inode may have been recycled.
    birth = getattr(info, "st_birthtime_ns", info.st_ctime_ns if os.name == "nt" else None)
    return [info.st_dev, info.st_ino, birth]


def _recovery_path(folder, path):
    return regular(folder.with_name(folder.name + "-records") / (path.name + ".json"))


def _recovery_signature(receipt, folder):
    records = child(folder.parent, folder.with_name(folder.name + "-records"))
    if not stat.S_ISDIR(records.lstat().st_mode):
        raise ContractError("Unrecognized staging recovery directory")
    receipt = child(records, receipt)
    info = receipt.lstat()
    if not stat.S_ISREG(info.st_mode) or receipt.suffix != ".json":
        raise ContractError("Unrecognized staging recovery record")
    return signature(info)


def _read_recovery(receipt, folder, stage):
    expected = _recovery_signature(receipt, folder)
    with receipt.open("rb") as stream:
        data = stream.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        raise ContractError("Staging recovery record exceeds its read bound")
    try:
        value = json.loads(data)
    except (ValueError, RecursionError) as exc:
        raise ContractError("Unrecognized staging recovery record: invalid JSON") from exc
    if (not isinstance(value, dict) or value.keys() != {"kind", "owner", "directory"}
            or type(value["kind"]) is not str or value["kind"] not in {"registration", "retirement"}):
        raise ContractError("Unrecognized staging recovery record")
    path = child(folder, folder / receipt.stem)
    validate(value["owner"], path, stage)
    identity = value["directory"]
    if (identity is not None and (type(identity) is not list or len(identity) != 3
            or any(type(item) is not int for item in identity[:2])
            or not identity[1] or identity[2] is not None and type(identity[2]) is not int)
            or value["kind"] == "retirement" and identity is None
            or value["owner"]["state"] == "completed"):
        raise ContractError("Unrecognized staging recovery identity")
    return path, value, expected


def _write_recovery(folder, path, stage, kind, owner, identity):
    validate(owner, path, stage)
    receipt = _recovery_path(folder, path)
    value = {"kind": kind, "owner": owner, "directory": identity}
    if receipt.exists():
        _, previous, _ = _read_recovery(receipt, folder, stage)
        if (previous["owner"] != owner
                or previous["directory"] not in (None, identity)):
            raise ContractError("Staging recovery record changed")
    data = json_bytes(value)
    if len(data) > MAX_RECORD_BYTES:
        raise ContractError("Staging recovery record exceeds its write bound")
    expected = _durable_write(receipt, data)
    if _recovery_signature(receipt, folder) != expected:
        raise ContractError("Staging recovery record changed")
    return receipt, expected


def _forget_recovery(receipt, folder, expected):
    folder = regular(folder)
    if _recovery_signature(receipt, folder) != expected:
        raise ContractError("Staging recovery record changed")
    # Persist the attempt's directory entry before discarding its recovery proof,
    # including when a previous rmdir succeeded but its directory fsync did not.
    # First-use registration can precede creation of the stage root itself.
    _sync_directory(folder if folder.exists() else regular(folder.parent))
    # Directory fsync may block; recheck the literal path and file after it too.
    if _recovery_signature(receipt, folder) != expected:
        raise ContractError("Staging recovery record changed")
    receipt.unlink()
    _sync_directory(regular(receipt.parent))


def _remove_empty(path, identity):
    if _directory_identity(path) != identity:
        raise ContractError("Staging directory changed before retirement")
    path.rmdir()  # Unexpected contents are always preserved, never recursively removed.
    _sync_directory(path.parent)


def _recover(folder, stage, current, summary):
    protected = set()
    receipts = regular(folder.with_name(folder.name + "-records"))
    if not receipts.exists():
        return protected
    with os.scandir(receipts) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_ENTRIES:
                raise ContractError("Staging recovery inventory exceeds its entry bound")
            receipt = Path(entry.path)
            try:
                path, value, receipt_signature = _read_recovery(receipt, folder, stage)
                if path == current:
                    continue
                if not path.exists():
                    _forget_recovery(receipt, folder, receipt_signature)
                    continue
                if value["directory"] is None or _directory_identity(path) != value["directory"]:
                    raise ContractError("Staging recovery directory identity does not match")
                if (path / OWNER).exists():
                    owner, _ = record(path, stage, folder=folder)
                    if owner != {**value["owner"], "state": owner["state"]}:
                        raise ContractError("Staging recovery ownership does not match")
                    if value["kind"] == "registration" or owner["state"] == "completed":
                        # A process may have died after the ownership rename,
                        # before its containing directory was synced.
                        _sync_directory(path)
                        _forget_recovery(receipt, folder, receipt_signature)
                        continue  # Ordinary retention still governs owned attempts.
                    if owner != value["owner"]:
                        raise ContractError("Staging ownership changed before retirement")
                    remove(path, stage, owner, folder=folder, expected_identity=value["directory"])
                else:
                    _remove_empty(path, value["directory"])
                    _forget_recovery(receipt, folder, receipt_signature)
                summary["removed"].append(path.name)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                protected.add(receipt.stem)
                summary["retained"].append({"stage": receipt.name, "reason": str(exc)})
    return protected


def unlink(path, expected):
    """Unlink first; changing protection is safe only for a single-link file."""
    try:
        path.unlink()
    except PermissionError:
        actual = regular(path).lstat()
        if signature(actual) != signature(expected):
            raise ContractError("Staging file changed before retirement")
        if actual.st_nlink != 1:
            raise ContractError("Cannot unlink protected multiply linked staging file")
        if actual.st_mode & stat.S_IWRITE:
            raise
        path.chmod(actual.st_mode | stat.S_IWRITE)
        path.unlink()


def remove(path, stage, expected_owner, *, folder, expected_identity=None):
    """Validate a bounded tree first; retain the ownership marker until last."""
    path = child(folder, path)
    identity = _directory_identity(path)
    if expected_identity is not None and identity != expected_identity:
        raise ContractError("Staging directory changed before retirement")
    if expected_owner["state"] == "completed":
        raise ContractError("Completed staging directories cannot be retired")
    pending, files, folders, count = [path], [], [], 0
    while pending:
        directory = pending.pop()
        folders.append(directory)
        with os.scandir(directory) as entries:
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
    if record(path, stage, folder=folder)[0] != expected_owner:
        raise ContractError("Staging ownership changed before retirement")
    if _directory_identity(path) != identity:
        raise ContractError("Staging directory changed before retirement")
    receipt, receipt_signature = _write_recovery(
        Path(folder).absolute(), path, stage, "retirement", expected_owner, identity)
    _checkpoint("retirement-recorded")
    for item, expected in files:
        if signature(regular(marker).lstat()) != signature(marker_info):
            raise ContractError("Staging ownership changed before retirement")
        actual = regular(item).lstat()
        if signature(actual) != signature(expected):
            raise ContractError("Staging file changed before retirement")
        unlink(item, actual)
    for directory in reversed(folders[1:]):
        info = regular(directory).lstat()
        if not info.st_mode & stat.S_IWRITE:
            directory.chmod(info.st_mode | stat.S_IWRITE)
        directory.rmdir()
    if signature(regular(marker).lstat()) != signature(marker_info):
        raise ContractError("Staging ownership changed before retirement")
    if _directory_identity(path) != identity:
        raise ContractError("Staging directory changed before retirement")
    if record(path, stage, folder=folder)[0] != expected_owner:
        raise ContractError("Staging ownership changed before retirement")
    # Any protection change must happen while ownership still proves this tree.
    info = regular(path).lstat()
    if not info.st_mode & stat.S_IWRITE:
        path.chmod(info.st_mode | stat.S_IWRITE)
    unlink(marker, marker_info)
    _checkpoint("owner-removed")
    _remove_empty(path, identity)
    _checkpoint("directory-removed")
    _forget_recovery(receipt, path.parent, receipt_signature)


def retire(folder, stage, current=None):
    """Only valid records of this stage authorize retirement; report everything else."""
    folder = Path(folder).absolute()
    summary = {"removed": [], "retained": []}
    attempts = []
    try:
        folder = regular(folder)
        current = child(folder, current) if current is not None else None
        protected = _recover(folder, stage, current, summary)
        if not folder.exists():
            return summary
        with os.scandir(folder) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_ENTRIES:
                    raise ContractError("Staging inventory exceeds its entry bound")
                path = Path(entry.path)
                try:
                    value, created = record(path, stage, folder=folder)
                    attempts.append((path, value, created))
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    summary["retained"].append({"stage": path.name, "reason": str(exc)})
        # A live current attempt is not stale. A just-abandoned current attempt
        # ranks newest under the writer lock, but is still never deleted here.
        failed = [(path, created) for path, value, created in attempts
                  if value["state"] != "completed"
                  and (path != current or value["state"] == "abandoned")]
        newest = max(failed, key=lambda row: (row[0] == current, row[1], row[0].name), default=(None, None))[0]
        for path, value, created in attempts:
            if value["state"] == "completed" or path == current or path.name in protected:
                continue
            try:
                if path != newest:
                    remove(path, stage, value, folder=folder)
                    summary["removed"].append(path.name)
                elif value["state"] == "materializing":
                    finish(path, stage, "abandoned")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                summary["retained"].append({"stage": path.name, "reason": str(exc)})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        summary["retained"].append({"stage": str(folder), "reason": str(exc)})
    try:
        # A redirected root can still be reported at its safe literal sibling.
        report = regular(folder.with_name(folder.name + "-retention.json"))
        write_changed(report, json_bytes(summary))
    except (OSError, ValueError) as exc:
        summary["retained"].append({"stage": str(folder), "reason": str(exc)})
    return summary


@contextmanager
def attempt(folder, stage, *, short=False, deferred=False):
    """Ordinary failures abandon; process interruptions leave materializing evidence."""
    retire(folder, stage)
    folder = regular(folder)
    identity = uuid.uuid4().hex[:12] if short else uuid.uuid4().hex
    path = child(folder, folder / identity)
    if path.exists() or _recovery_path(folder, path).exists():
        raise ContractError("Staging attempt identity already exists")
    owner = {"schema_version": 1, "stage": stage, "attempt_id": identity,
             "created_utc": datetime.now(timezone.utc).isoformat(), "state": "materializing"}
    _write_recovery(folder, path, stage, "registration", owner, None)
    _checkpoint("registration-intent")
    path.mkdir(parents=True)
    _checkpoint("directory-created")
    receipt, receipt_signature = _write_recovery(
        folder, path, stage, "registration", owner, _directory_identity(path))
    _checkpoint("registered")
    write_record(path, stage, owner)
    _checkpoint("owned")
    _forget_recovery(receipt, folder, receipt_signature)
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
