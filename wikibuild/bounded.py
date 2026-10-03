"""External processes with a total deadline, including their descendants."""

import os
import subprocess

# After the process tree is killed, how long to wait for its output pipes to close.
DRAIN_SECONDS = 10


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


def run(command, timeout, *, input=None, env=None, cwd=None):
    """subprocess.run(capture_output=True) that cannot outlive `timeout` by more than a bounded drain.

    On Windows, subprocess.run's own timeout path kills only the child and then drains
    its pipes without a deadline, so a descendant that inherited them (git-remote-https
    under git push) can block it forever."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)
    try:
        stdout, stderr = process.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        try:
            process.communicate(timeout=DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            # An orphan still holds the pipes. Abandon them rather than wait;
            # the reader threads are daemons and end with the process.
            pass
        raise subprocess.TimeoutExpired(command, timeout) from None
    except BaseException:
        kill_tree(process)
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
