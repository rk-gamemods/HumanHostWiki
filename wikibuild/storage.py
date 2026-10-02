"""Bounded local paths, atomic files and an OS-held writer lock."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


class ContractError(ValueError):
    """An input or workspace violates an explicit contract."""


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def within(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise ContractError(f"Path escapes its owning directory: {relative}")
    return path


def write_changed(path, data):
    """Never rewrite identical files; replacement honors existing file protection."""
    path = Path(path)
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return True


def git(path, *arguments):
    result = subprocess.run(["git", "-C", str(path), *arguments], capture_output=True, check=False)
    if result.returncode:
        raise ContractError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout.decode("utf-8").strip()


def process_running(pid):
    # os.kill(pid, 0) terminates the process on Windows, so ask the OS instead.
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes
    kernel = ctypes.WinDLL("kernel32")
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def lock_holder(owner):
    """Describe the recorded lock holder so a stuck run can be found and stopped."""
    try:
        record = json.loads(owner.read_text(encoding="utf-8"))
        pid, started = int(record["pid"]), datetime.fromisoformat(record["started"])
    except (OSError, ValueError, KeyError, TypeError):
        return "its holder is not recorded."
    state = "running" if process_running(pid) else "not running; the PID may have been reused"
    minutes = int((datetime.now(timezone.utc) - started).total_seconds() // 60)
    return (f"held by PID {pid} ({state}) since {record['started']} for {minutes} min "
            f"(command: {record.get('command', 'unknown')}).")


@contextmanager
def writer_lock(root):
    path = within(root, ".local/writer.lock")
    owner = path.with_name("writer.lock.owner.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ContractError(f"Another wiki writer holds .local/writer.lock, {lock_holder(owner)} "
                                "Retry after it exits.") from exc
        try:
            write_changed(owner, json_bytes({"pid": os.getpid(), "command": " ".join(sys.argv),
                                             "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
            yield
        finally:
            owner.unlink(missing_ok=True)
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
