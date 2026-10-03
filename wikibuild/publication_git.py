"""Prepare Pages trees in existing Git object storage without a second checkout."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

from . import bounded
from .git_transaction import command
from .storage import ContractError, git


def storage_snapshot(path):
    """Exact read-only evidence; porcelain status cannot detect rehearsal lineage."""
    common = Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    pins = common / "refs/wiki-publications"
    files = {file.relative_to(common).as_posix(): file.read_bytes()
             for file in sorted(pins.rglob("*")) if file.is_file()}
    packed = common / "packed-refs"
    if packed.exists():
        files["packed-refs"] = packed.read_bytes()
    return {"refs": command(path, "for-each-ref"), "pins": files,
            "objects": command(path, "count-objects", "-v")}


def disposable_clone(source, destination, revision):
    """Borrow existing objects read-only; all new objects and refs belong to the clone."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    command(source, "clone", "--shared", "--no-checkout", "--", str(source), str(destination))
    # Normal clone omits publication pins and other private refs. They are input
    # evidence, but any pins the engine adds here must never become production input.
    refs = command(source, "for-each-ref", "--format=%(objectname) %(refname)")
    command(destination, "update-ref", "--no-deref", "--stdin",
            data=b"".join(b"update " + name + b" " + oid + b"\n"
                          for oid, name in (row.split() for row in refs.splitlines())))
    identity = command(source, "var", "GIT_COMMITTER_IDENT").decode().strip()
    match = re.fullmatch(r"(.*) <(.*)> \d+ [+-]\d{4}", identity)
    if not match:
        raise ContractError("Unable to read rehearsal Git identity")
    git(destination, "config", "user.name", match[1])
    git(destination, "config", "user.email", match[2])
    git(destination, "config", "core.autocrlf", "false")
    git(destination, "checkout", "--detach", revision)


def remove_disposable(root):
    """Delete an owned temp tree, retrying only Git's read-only object files."""
    root = Path(root).resolve()
    if (root.parent != Path(tempfile.gettempdir()).resolve()
            or not re.fullmatch(r"hhwiki-(?:rehearsal|publication)-[0-9a-f]{32}", root.name)):
        raise ContractError(f"Refusing disposable cleanup outside an owned temp root: {root}")

    def retry_readonly(function, filename, error):
        path = Path(filename).resolve()
        if not path.is_relative_to(root):
            raise error[1]
        parts = path.relative_to(root).parts
        mode = path.stat().st_mode
        if (os.name != "nt" or not isinstance(error[1], PermissionError)
                or function not in {os.unlink, os.remove} or not stat.S_ISREG(mode)
                or mode & stat.S_IWRITE or not any(parts[i:i + 2] == (".git", "objects")
                                                 for i in range(len(parts) - 1))):
            raise error[1]
        path.chmod(mode | stat.S_IWRITE)
        function(filename)

    if root.exists():
        shutil.rmtree(root, onerror=retry_readonly)


def commit(path, tree, parent, message):
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return command(path, *args, data=(message + "\n").encode()).decode().strip()


def owned_lineage(path, base, head):
    """True when `head` fast-forwards `base` only through commits this workspace published.

    An abandoned publication leaves its pushed commits on the remote branch. Each commit
    after `base` must be pinned under refs/wiki-publications/ (pushed from here) or carry a
    tree already on that line (a byte-identical restore). Anything else stays refused."""
    if not head:
        return False

    def succeeds(*args):
        try:
            return bounded.run(["git", "-C", str(path), *args], timeout=120).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    if not succeeds("cat-file", "-e", head + "^{commit}") or (base and not succeeds("merge-base", "--is-ancestor", base, head)):
        return False
    # Without a completed baseline, the lineage must start at a pinned root.
    trees = {bounded_git(path, "rev-parse", base + "^{tree}")} if base else set()
    for revision in reversed(bounded_git(path, "rev-list", head, *(["^" + base] if base else [])).splitlines()):
        tree = bounded_git(path, "rev-parse", revision + "^{tree}")
        if tree not in trees and not succeeds("show-ref", "--verify", "--quiet", "refs/wiki-publications/" + revision):
            return False
        trees.add(tree)
    return True


def released_lineage(path, base, head, release):
    """True when remote main `head` lies on this workspace's own release history:
    it descends from the last published `base` and the selected `release` descends from it."""
    if not head:
        return False
    try:
        return all(bounded.run(["git", "-C", str(path), "merge-base", "--is-ancestor", older, newer],
                               timeout=120).returncode == 0 for older, newer in
                   (*([(base, head)] if base else []), (head, release)))
    except subprocess.TimeoutExpired:
        return False


def bounded_git(path, *arguments):
    try:
        result = bounded.run(["git", "-C", str(path), *arguments], timeout=120)
    except subprocess.TimeoutExpired:
        raise ContractError("Publication lineage check timed out") from None
    if result.returncode:
        raise ContractError("Publication lineage check failed")
    return result.stdout.decode().strip()


def unavailable(path):
    data = b"<!doctype html><html lang=en><meta charset=utf-8><title>Unofficial game reference</title><h1>Unofficial game reference</h1><p>Not affiliated with or endorsed by Virtual Matrix Studio.</p><p>No validated public release is available. Publication is being retried.</p></html>\n"
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
            issue_template = (path.name == "hub" and
                              re.fullmatch(r"\.github/ISSUE_TEMPLATE/[A-Za-z0-9-]+\.yml", name) is not None)
            generated = name.startswith(("site/", "reference/")) and name.rsplit("/", 1)[-1].endswith((".json", ".md", ".js", ".css", ".html", ".nojekyll"))
            font = re.fullmatch(r"site/fonts/[0-9a-f]{64}/[A-Za-z0-9-]+\.(?:woff2|txt)", name) is not None
            authored = (name.startswith("authored/") and name.endswith(".md")) or (
                name.startswith("curated/") and name.endswith(".json"))
            if mode != b"100644" or kind != b"blob" or not (metadata or generated or authored or font or issue_template):
                raise ContractError(f"Unapproved public history path: {name}")
            # A blob may also occur at a non-font path or in older history.
            # Retain the strictest use when deduplicating bytes for the scan.
            if oid.decode() not in blobs or not (font and name.endswith(".woff2")):
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
            font = re.fullmatch(r"site/fonts/[0-9a-f]{64}/[A-Za-z0-9-]+\.woff2", name) is not None
            if font and remaining < 4:
                raise ContractError(f"Invalid WOFF2 font in public history: {name}")
            first = True
            while remaining:
                block = process.stdout.read(min(65536, remaining))
                if not block:
                    raise ContractError("Git stopped during public history audit")
                if font and first and not block.startswith(b"wOF2"):
                    raise ContractError(f"Invalid WOFF2 font in public history: {name}")
                first = False
                if (not font and b"\0" in block) or private.search(tail + block):
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
