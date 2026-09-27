"""Prepare Pages trees in existing Git object storage without a second checkout."""

import hashlib
import re
import subprocess

from .git_transaction import command
from .storage import ContractError, git


def commit(path, tree, parent, message):
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return command(path, *args, data=(message + "\n").encode()).decode().strip()


def unavailable(path):
    data = b"<!doctype html><html lang=en><meta charset=utf-8><title>Human Host Wiki</title><h1>Human Host Wiki</h1><p>No validated public release is available. Publication is being retried.</p></html>\n"
    blob = command(path, "hash-object", "-w", "--stdin", data=data).decode().strip()
    entries = b"".join(f"100644 blob {blob}\t{name}\n".encode() for name in ("404.html", "index.html"))
    tree = command(path, "mktree", data=entries).decode().strip()
    return tree, {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name in ("404.html", "index.html")}


def audit(path, head, baseline=None):
    """Scan newly exported history, including deleted blobs, before the first push."""
    if baseline and baseline != head:
        check = subprocess.run(["git", "-C", str(path), "merge-base", "--is-ancestor", baseline, head], capture_output=True)
        if check.returncode:
            raise ContractError("Remote main is not an ancestor of the selected release")
    revisions = git(path, "rev-list", head, *(["^" + baseline] if baseline else [])).splitlines()
    blobs = {}
    for revision in revisions:
        for row in command(path, "ls-tree", "-rz", revision).split(b"\0"):
            if not row:
                continue
            meta, raw_name = row.split(b"\t", 1)
            mode, kind, oid = meta.split()
            name = raw_name.decode()
            metadata = name in {".gitattributes", ".gitignore", ".wiki-repository.json", ".wiki-output.json", "README.md"}
            metadata = metadata or re.fullmatch(r"\.wiki-ownership/[0-9a-f]{64}\.json", name) is not None
            generated = name.startswith(("site/", "reference/")) and name.rsplit("/", 1)[-1].endswith((".json", ".md", ".js", ".css", ".html", ".nojekyll"))
            authored = name.startswith("authored/") and name.endswith(".md")
            if mode != b"100644" or kind != b"blob" or not (metadata or generated or authored):
                raise ContractError(f"Unapproved public history path: {name}")
            blobs[oid.decode()] = name
    # One streaming Git process; only a small block is resident per blob.
    process = subprocess.Popen(["git", "-C", str(path), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    private = re.compile(rb"(?i)([A-Z]:[/\\]{1,2}Users[/\\]{1,2}|/home/[^/ ]+/|gh[pousr]_[A-Za-z0-9]{30}|github_pat_[A-Za-z0-9_]{30}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY)")
    try:
        for oid, name in blobs.items():
            process.stdin.write((oid + "\n").encode())
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                raise ContractError(f"Invalid Git object during public audit: {name}")
            remaining = int(header[2])
            tail = b""
            while remaining:
                block = process.stdout.read(min(65536, remaining))
                if not block:
                    raise ContractError("Git stopped during public history audit")
                if b"\0" in block or private.search(tail + block):
                    raise ContractError(f"Private or binary bytes in public history: {name}")
                tail = block[-256:]
                remaining -= len(block)
            if process.stdout.read(1) != b"\n":
                raise ContractError("Invalid Git object boundary")
        process.stdin.close()
        if process.wait():
            raise ContractError("Git public history audit failed")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()
        if not process.stdin.closed:
            process.stdin.close()
    return {"commits": len(revisions), "blobs": len(blobs)}
