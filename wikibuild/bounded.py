"""External processes with a total deadline, including their descendants."""

import os
import ctypes
from contextlib import contextmanager
import queue
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

    Concurrent cleanup is idempotent. POSIX orphans are reaped by the OS;
    the caller reaps its direct child. Descendants that leave the group escape it.
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


class _DeadlinePipe:
    """One I/O worker per pipe; no buffered-I/O lock can trap the caller."""
    def __init__(self, pipe, owner):
        self.pipe, self.owner = pipe, owner
        self.requests = queue.Queue()
        self.closed = False
        self.worker = threading.Thread(target=self._serve, daemon=True)
        self.worker.start()

    def _serve(self):
        try:
            while True:
                request = self.requests.get()
                if request is None:
                    return
                method, args, done, result = request
                try:
                    result.append((True, getattr(self.pipe, method)(*args)))
                except BaseException as exc:
                    result.append((False, exc))
                finally:
                    done.set()
                if method == "close":
                    return
        finally:
            self.pipe.close()

    def _call(self, method, *args):
        self.owner.remaining()
        if self.closed:
            raise ValueError("I/O operation on closed pipe")
        done, result = threading.Event(), []
        self.requests.put((method, args, done, result))
        if not done.wait(self.owner.remaining()):
            raise subprocess.TimeoutExpired(self.owner.command, self.owner.timeout)
        self.owner.remaining()
        success, value = result[0]
        if not success:
            raise value
        return value

    def read(self, size=-1):
        return self._call("read", size)

    def readline(self, size=-1):
        return self._call("readline", size)

    def write(self, data):
        return self._call("write", data)

    def flush(self):
        return self._call("flush")

    def close(self):
        if not self.closed:
            self._call("close")
            self.closed = True

    def fileno(self):
        # Allows an owned pipeline to pass this pipe directly to another child.
        return self.pipe.fileno()

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line


class _Streaming:
    def __init__(self, process, command, timeout):
        self.process, self.command, self.timeout = process, command, timeout
        self.expires = time.monotonic() + timeout
        self.stdout = self.stdin = None
        self.errors = bytearray()
        self.error_worker = None
        self.expired, self.cancel = threading.Event(), threading.Event()
        self.cleanup_error = None

    def remaining(self):
        remaining = self.expires - time.monotonic()
        if self.expired.is_set() or remaining <= 0:
            raise subprocess.TimeoutExpired(self.command, self.timeout)
        return remaining

    @property
    def stderr(self):
        return bytes(self.errors)

    @property
    def returncode(self):
        return self.process.returncode

    def wait(self):
        code = self.process.wait(timeout=self.remaining())
        self.error_worker.join(self.remaining())
        self.remaining()
        if self.error_worker.is_alive():
            raise subprocess.TimeoutExpired(self.command, self.timeout)
        return code

    def _watch(self):
        if not self.cancel.wait(max(0.0, self.expires - time.monotonic())):
            self.expired.set()
            try:
                kill_tree(self.process)
            except BaseException as exc:
                self.cleanup_error = exc


@contextmanager
def stream(command, timeout, *, stdin=subprocess.DEVNULL, env=None, cwd=None):
    """Yield owned binary stdout/stdin with deadline I/O and capped concurrent stderr.

    The elapsed deadline starts after launch and includes caller consumption.
    Exit, including early exit and exceptions, kills and reaps the entire tree.
    As with run, callers must reserve CLEANUP_SECONDS beyond the command bound.
    stdin may be PIPE for batch requests or another owned stream for a pipeline.
    """
    process = start(command, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)
    session = _Streaming(process, command, timeout)
    watcher = threading.Thread(target=session._watch, daemon=True)
    try:
        session.stdout = _DeadlinePipe(process.stdout, session)
        if process.stdin is not None:
            session.stdin = _DeadlinePipe(process.stdin, session)
        session.error_worker = threading.Thread(target=_collect, args=(process.stderr, session.errors), daemon=True)
        session.error_worker.start()
        watcher.start()
        yield session
    finally:
        elapsed = time.monotonic() >= session.expires
        session.cancel.set()
        try:
            kill_tree(process)
        finally:
            drained = time.monotonic() + DRAIN_SECONDS
            workers = []
            for pipe in (session.stdin, session.stdout):
                if pipe is not None:
                    pipe.closed = True
                    pipe.requests.put(None)
                    workers.append(pipe.worker)
            workers.extend(worker for worker in (session.error_worker, watcher) if worker is not None)
            for worker in workers:
                if worker.ident is not None:
                    worker.join(max(0.0, drained - time.monotonic()))
            # Only close pipes whose worker was never started; live daemon I/O
            # may belong to an escaped POSIX descendant and cannot be joined.
            for raw, worker in ((process.stdout, session.stdout.worker if session.stdout else None),
                                (process.stdin, session.stdin.worker if session.stdin else None),
                                (process.stderr, session.error_worker)):
                if raw is not None and (worker is None or worker.ident is None):
                    raw.close()
        if session.cleanup_error is not None:
            raise session.cleanup_error
        if elapsed or session.expired.is_set() or any(worker.is_alive() for worker in workers):
            raise subprocess.TimeoutExpired(command, timeout)
