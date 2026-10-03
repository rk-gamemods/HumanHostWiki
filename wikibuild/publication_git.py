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
from .storage import ContractError, git, git_records

# Individual local lineage lookups retain their existing plumbing allowance.
GIT_TIMEOUT = 120
# A lineage stream remains open while every commit receives its ownership lookup.
GIT_LINEAGE_TIMEOUT = 600
# A public audit consumes every blob in the newly exported history.
GIT_AUDIT_TIMEOUT = 1800


def disposable_environment(*, identity=False):
    # No caller-supplied Git routing, injected config, trace paths or attributes.
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_SYSTEM=os.devnull,
                       GIT_ATTR_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    # The read-only identity query may use the operator's global user identity.
    # Every object/ref operation ignores global config, including arbitrary filters.
    if not identity:
        environment["GIT_CONFIG_GLOBAL"] = os.devnull
    return environment


def disposable_git(path, *arguments, data=None, hooks=None, identity=False):
    options = ["-c", "core.fsmonitor=false", "-c", f"core.attributesFile={os.devnull}",
               "-c", "filter.lfs.smudge=", "-c", "filter.lfs.clean=",
               "-c", "filter.lfs.process=", "-c", "filter.lfs.required=false"]
    if hooks is not None:
        options += ["-c", f"core.hooksPath={hooks}"]
    try:
        result = bounded.run(["git", "-C", str(path), *options, *arguments], timeout=120,
                             input=data, env=disposable_environment(identity=identity))
    except subprocess.TimeoutExpired:
        raise ContractError("Rehearsal Git storage command timed out") from None
    if result.returncode:
        raise ContractError(f"Rehearsal Git storage command failed: {result.stderr.decode(errors='replace')[:1200]}")
    return result.stdout


def storage_snapshot(path):
    """Exact read-only evidence; porcelain status cannot detect rehearsal lineage."""
    common = Path(disposable_git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip())
    pins = common / "refs/wiki-publications"
    files = {file.relative_to(common).as_posix(): file.read_bytes()
             for file in sorted(pins.rglob("*")) if file.is_file()}
    packed = common / "packed-refs"
    if packed.exists():
        files["packed-refs"] = packed.read_bytes()
    return {"refs": disposable_git(path, "for-each-ref"), "pins": files,
            "objects": disposable_git(path, "count-objects", "-v")}


def disposable_clone(source, destination, revision):
    """Borrow existing objects read-only; all new objects and refs belong to the clone."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    hooks = destination.parent / (destination.name + "-empty-hooks")
    hooks.mkdir()
    disposable_git(source, "clone", "--shared", "--template=", "--no-checkout",
                   "-c", f"core.hooksPath={hooks}", "--", str(source), str(destination), hooks=hooks)
    # Normal clone omits publication pins and other private refs. They are input
    # evidence, but any pins the engine adds here must never become production input.
    refs = disposable_git(source, "for-each-ref", "--format=%(objectname) %(refname)")
    disposable_git(destination, "update-ref", "--no-deref", "--stdin", hooks=hooks,
            data=b"".join(b"update " + name + b" " + oid + b"\n"
                          for oid, name in (row.split() for row in refs.splitlines())))
    identity = disposable_git(source, "var", "GIT_COMMITTER_IDENT", identity=True).decode().strip()
    match = re.fullmatch(r"(.*) <(.*)> \d+ [+-]\d{4}", identity)
    if not match:
        raise ContractError("Unable to read rehearsal Git identity")
    for key, value in {"user.name": match[1], "user.email": match[2], "core.autocrlf": "false",
                       "core.fsmonitor": "false", "core.attributesFile": os.devnull,
                       "filter.lfs.smudge": "", "filter.lfs.clean": "", "filter.lfs.process": "",
                       "filter.lfs.required": "false"}.items():
        disposable_git(destination, "config", key, value, hooks=hooks)
    disposable_git(destination, "checkout", "--detach", revision, hooks=hooks)


def remove_disposable(root, *, marker=None):
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
        if marker is None:
            shutil.rmtree(root, onerror=retry_readonly)
        else:
            if Path(marker).name != marker or marker in {".", ".."}:
                raise ContractError("Disposable marker must be a filename")
            # Keep the ownership proof until all other contents are gone. A
            # crash after unlinking the marker leaves only an empty root.
            for child in root.iterdir():
                if child.name == marker:
                    continue
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, onerror=retry_readonly)
                else:
                    child.unlink()
            (root / marker).unlink(missing_ok=True)
            root.rmdir()


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
            return bounded.run(["git", "-C", str(path), *args], timeout=GIT_TIMEOUT).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    if not succeeds("cat-file", "-e", head + "^{commit}") or (base and not succeeds("merge-base", "--is-ancestor", base, head)):
        return False
    # Without a completed baseline, the lineage must start at a pinned root.
    trees = {bounded_git(path, "rev-parse", base + "^{tree}")} if base else set()
    for raw_revision in git_records(path, "rev-list", "--reverse", head, *(["^" + base] if base else []),
                                    separator=b"\n", timeout=GIT_LINEAGE_TIMEOUT):
        revision = raw_revision.decode()
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
                               timeout=GIT_TIMEOUT).returncode == 0 for older, newer in
                   (*([(base, head)] if base else []), (head, release)))
    except subprocess.TimeoutExpired:
        return False


def bounded_git(path, *arguments):
    try:
        result = bounded.run(["git", "-C", str(path), *arguments], timeout=GIT_TIMEOUT)
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
        check = bounded.run(["git", "-C", str(path), "merge-base", "--is-ancestor", baseline, head], timeout=GIT_TIMEOUT)
        if check.returncode:
            raise ContractError("Remote main is not an ancestor of the selected release")
    revisions = 0
    blobs = {}
    for raw_revision in git_records(path, "rev-list", head, *(["^" + baseline] if baseline else []),
                                    separator=b"\n", timeout=GIT_AUDIT_TIMEOUT):
        revisions += 1
        revision = raw_revision.decode()
        for row in git_records(path, "--literal-pathspecs", "ls-tree", "-rz", revision, timeout=GIT_AUDIT_TIMEOUT):
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
    private = re.compile(rb"(?i)([A-Z]:[/\\]{1,2}Users[/\\]{1,2}|/home/[^/ ]+/|gh[pousr]_[A-Za-z0-9]{30}|github_pat_[A-Za-z0-9_]{30}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY)")
    with bounded.stream(["git", "-C", str(path), "cat-file", "--batch"],
                        timeout=GIT_AUDIT_TIMEOUT, stdin=subprocess.PIPE) as process:
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
    return {"commits": revisions, "blobs": len(blobs)}
