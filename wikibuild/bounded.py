"""External processes with a total deadline, including their descendants."""

import os
import ctypes
import signal
import subprocess
import threading
import time

# Worst-case cleanup must fit inside any caller's elapsed deadline.
REAP_SECONDS = 30
# After the process exits or is killed, how long to wait for its pipes to close.
DRAIN_SECONDS = 10
# The reap deadline includes the per-tree lock, parent wait and job query.
CLEANUP_SECONDS = REAP_SECONDS + DRAIN_SECONDS
# A descendant that outlives a killed parent can keep writing; stop keeping its bytes.
MAX_CAPTURE = 64 * 1024 * 1024

_children = set()
_children_lock = threading.RLock()
_stopping = threading.Event()


class _WindowsJob:
    """Kill-on-close ownership, established while the child is suspended."""
    def __init__(self):
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                        ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                        ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

        self.accounting = Accounting
        self.kernel = kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                     wintypes.DWORD, ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = kernel.CreateJobObjectW(None, None)
        self.exited = False
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = Extended()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def assign(self, process):
        from ctypes import wintypes
        if not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def resume(self, process):
        from ctypes import wintypes
        resume = ctypes.WinDLL("ntdll").NtResumeProcess
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = ctypes.c_long
        if resume(wintypes.HANDLE(process._handle)):
            raise OSError("Could not resume wiki child")

    def terminate(self):
        if self.handle and not self.kernel.TerminateJobObject(self.handle, 124):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait(self, expires):
        if not self.handle and not self.exited:
            raise RuntimeError("Owned Windows job closed before exit was confirmed")
        while self.handle:
            counters = self.accounting()
            if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(counters),
                                                         ctypes.sizeof(counters), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not counters.ActiveProcesses:
                self.exited = True
                return
            remaining = expires - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Windows job still has live processes after the reap deadline")
            time.sleep(min(0.02, remaining))

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


class _Owned:
    def __init__(self, process):
        self.process, self.job = process, None
        self.lock = threading.Lock()
        self.done = False
        self.state = "starting"
        self.error = None


def _terminate_suspended(process):
    """Use the real process handle even when ownership setup was interrupted."""
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        if not kernel.TerminateProcess(wintypes.HANDLE(process._handle), 124):
            error = ctypes.get_last_error()
            if process.poll() is None:
                raise ctypes.WinError(error)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _group_exited(group):
    """True only when the OS reports the POSIX group empty.

    The caller has already reaped the direct child, and PID 1 reaps orphaned
    descendants, so any member the OS still reports means cleanup is unresolved.
    """
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return True
    return False


def _wait_group(group, expires):
    """killpg only sends the signal, so wait for the group's members to exit."""
    while not _group_exited(group):
        if time.monotonic() >= expires:
            raise subprocess.TimeoutExpired(f"process group {group}", REAP_SECONDS)
        time.sleep(0.02)


def _finish_tree(owned, expires):
    """Keep an unresolved job open until both parent and tree exit are confirmed."""
    process = owned.process
    try:
        if process is not None:
            if owned.job is not None:
                owned.job.terminate()
            else:
                _terminate_suspended(process)
            process.wait(timeout=max(0.0, expires - time.monotonic()))
            if os.name != "nt":
                _wait_group(process.pid, expires)
        if owned.job is not None:
            owned.job.wait(expires)
            owned.job.close()
        with _children_lock:
            _children.discard(owned)
        owned.done, owned.state, owned.error = True, "done", None
    except BaseException as exc:
        owned.done, owned.state, owned.error = False, "unresolved", str(exc)
        raise


def begin_shutdown():
    """Fence new launches before taking the registry snapshot."""
    previous = _stopping.is_set()
    _stopping.set()
    return previous


def end_shutdown(previous):
    # A real watchdog exits inside this fence. Injectable stops may return.
    if not previous:
        _stopping.clear()


def start(command, **options):
    """Start a registered, owned tree; callers must finish it with kill_tree."""
    if _stopping.is_set():
        raise RuntimeError("Wiki child launch refused during timeout cleanup")
    if os.name == "nt":
        options["creationflags"] = options.get("creationflags", 0) | 0x4 | subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    process, owned, locked = None, _Owned(None), False
    try:
        # The per-tree lock prevents cleanup from racing assignment/resume.
        # Register before creation so shutdown also sees an in-flight launch.
        owned.lock.acquire()
        locked = True
        with _children_lock:
            if _stopping.is_set():
                raise RuntimeError("Wiki child launch refused during timeout cleanup")
            _children.add(owned)
        process = subprocess.Popen(command, **options)
        owned.process = process
        process._wiki_owned = owned
        if os.name == "nt":
            owned.job = _WindowsJob()
            owned.job.assign(process)
        if _stopping.is_set():
            raise RuntimeError("Wiki child launch interrupted by timeout cleanup")
        if owned.job is not None:
            owned.job.resume(process)
        owned.state = "owned"
        return process
    except BaseException as original:
        try:
            expires = time.monotonic() + REAP_SECONDS
            if process is not None:
                owned.process = process
                _terminate_suspended(process)
            _finish_tree(owned, expires)
        except BaseException as exc:
            child = process.pid if process is not None else "launch pending"
            original.add_note(f"Suspended child PID {child} cleanup unresolved: {exc}")
            owned.state, owned.error = "unresolved", str(exc)
            with _children_lock:
                _children.add(owned)
        finally:
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except (OSError, ValueError):
                            pass
        raise
    finally:
        if locked:
            owned.lock.release()


def _kill_owned(owned):
    expires = time.monotonic() + REAP_SECONDS
    if not owned.lock.acquire(timeout=REAP_SECONDS):
        owned.state, owned.error = "unresolved", "ownership setup or cleanup lock did not finish"
        command = owned.process.args if owned.process is not None else "pending wiki child launch"
        raise subprocess.TimeoutExpired(command, REAP_SECONDS)
    try:
        if owned.done:
            return
        _finish_tree(owned, expires)
    finally:
        owned.lock.release()


def kill_tree(process):
    """Terminate the owned tree even after parent exit, then reap within 30s.

    Concurrent cleanup is idempotent. On POSIX it returns only after every
    group member has exited; the OS reaps orphans. Descendants that leave the
    group escape it.
    """
    _kill_owned(process._wiki_owned)


def terminate_all():
    """Stop all registered trees concurrently, with one shared reap bound."""
    with _children_lock:
        children = list(_children)
    errors = []

    def stop(owned):
        try:
            _kill_owned(owned)
        except BaseException as exc:
            child = owned.process.pid if owned.process is not None else "launch pending"
            errors.append(f"unresolved child PID {child}: {exc}")

    expires = time.monotonic() + REAP_SECONDS
    workers = [(owned, threading.Thread(target=stop, args=(owned,), daemon=True)) for owned in children]
    for _, worker in workers:
        worker.start()
    for owned, worker in workers:
        worker.join(max(0.0, expires - time.monotonic()))
        if worker.is_alive():
            child = owned.process.pid if owned.process is not None else "launch pending"
            errors.append(f"unresolved child PID {child}: cleanup did not finish within {REAP_SECONDS}s")
    return errors


def _collect(stream, sink):
    try:
        while chunk := stream.read1(65536):
            if len(sink) < MAX_CAPTURE:
                sink.extend(chunk[:MAX_CAPTURE - len(sink)])
    except (OSError, ValueError):
        pass
    finally:
        stream.close()


def _feed(stream, data):
    try:
        stream.write(data)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def run(command, timeout, *, input=None, env=None, cwd=None):
    """After launch, capture an owned tree within timeout + CLEANUP_SECONDS.

    Cleanup shares REAP_SECONDS across the ownership lock, parent reap and job
    exit query, then shares DRAIN_SECONDS across all pipe workers. Callers with
    an elapsed deadline must reserve CLEANUP_SECONDS from the process timeout.

    All pipe I/O happens on daemon threads; the caller only ever waits with a deadline.
    subprocess.run cannot promise that on Windows: it writes stdin before its timeout
    starts, and after a timeout it drains pipes that a descendant (git-remote-https
    under git push) may hold open forever."""
    process = start(command, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)
    stdout, stderr = bytearray(), bytearray()
    workers = []
    try:
        pipes = [(process.stdout, _collect, stdout), (process.stderr, _collect, stderr)]
        if input is not None:
            pipes.append((process.stdin, _feed, input))
        for stream, action, value in pipes:
            worker = threading.Thread(target=action, args=(stream, value), daemon=True)
            workers.append((stream, worker))
            worker.start()
        process.wait(timeout=timeout)
    finally:
        try:
            kill_tree(process)
        finally:
            drained = time.monotonic() + DRAIN_SECONDS
            for _, worker in workers:
                if worker.ident is not None:
                    worker.join(max(0.0, drained - time.monotonic()))
            active = {stream for stream, worker in workers if worker.is_alive()}
            # Never close a pipe underneath a blocked reader/writer. Unstarted
            # and finished workers leave no buffered-I/O lock to wait for.
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and stream not in active:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
    # Still-open pipes mean a descendant holds them: the output is incomplete. Abandon
    # the daemon readers; MAX_CAPTURE bounds what they keep.
    if any(worker.is_alive() for _, worker in workers):
        raise subprocess.TimeoutExpired(command, timeout)
    return subprocess.CompletedProcess(command, process.returncode, bytes(stdout), bytes(stderr))
