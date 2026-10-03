"""External processes with a total deadline, including their descendants."""

import os
import subprocess
import threading
import time

# After the process exits or is killed, how long to wait for its pipes to close.
DRAIN_SECONDS = 10
# A descendant that outlives a killed parent can keep writing; stop keeping its bytes.
MAX_CAPTURE = 64 * 1024 * 1024


def kill_tree(process):
    """Kill a process and its descendants; a descendant can hold the parent's pipes."""
    if os.name == "nt":
        # taskkill walks the tree from the live parent, so it runs before kill().
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                           timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    process.kill()


def _collect(stream, sink):
    try:
        while chunk := stream.read1(65536):
            if len(sink) < MAX_CAPTURE:
                sink.extend(chunk[:MAX_CAPTURE - len(sink)])
    except (OSError, ValueError):
        pass


def _feed(stream, data):
    try:
        stream.write(data)
        stream.close()
    except (OSError, ValueError):
        pass


def run(command, timeout, *, input=None, env=None, cwd=None):
    """subprocess.run(capture_output=True) that returns or raises within timeout + DRAIN_SECONDS.

    All pipe I/O happens on daemon threads; the caller only ever waits with a deadline.
    subprocess.run cannot promise that on Windows: it writes stdin before its timeout
    starts, and after a timeout it drains pipes that a descendant (git-remote-https
    under git push) may hold open forever."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)
    stdout, stderr = bytearray(), bytearray()
    workers = [threading.Thread(target=_collect, args=(process.stdout, stdout), daemon=True),
               threading.Thread(target=_collect, args=(process.stderr, stderr), daemon=True)]
    if input is not None:
        workers.append(threading.Thread(target=_feed, args=(process.stdin, input), daemon=True))
    for worker in workers:
        worker.start()
    try:
        process.wait(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        kill_tree(process)
        timed_out = True
    except BaseException:
        kill_tree(process)
        raise
    drained = time.monotonic() + DRAIN_SECONDS
    for worker in workers:
        worker.join(max(0.0, drained - time.monotonic()))
    # Still-open pipes mean a descendant holds them: the output is incomplete. Abandon
    # the daemon readers; MAX_CAPTURE bounds what they keep.
    if timed_out or any(worker.is_alive() for worker in workers):
        raise subprocess.TimeoutExpired(command, timeout)
    return subprocess.CompletedProcess(command, process.returncode, bytes(stdout), bytes(stderr))
