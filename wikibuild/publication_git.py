"""Prepare Pages trees in existing Git object storage without a second checkout."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time

from . import bounded
from .git_transaction import command
from .storage import ContractError, digest, git, git_records, json_bytes, within

# Individual local lineage lookups retain their existing plumbing allowance.
GIT_TIMEOUT = 120
# The shared lineage budget includes enumeration and every commit's ownership lookup.
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


def check_pin(path, ref, commit, *, env=None, hooks=None, timeout=GIT_TIMEOUT, descendants=False):
    """Read-only collision check shared by production and simulated pin writes."""
    if (not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit)
            or not re.fullmatch(r"refs/wiki-publications/[^\x00-\x20\x7f]+", ref)):
        raise ContractError("Invalid publication pin ref or commit")
    argv = ["git", "-C", str(path)]
    if hooks is not None:
        argv += ["-c", f"core.hooksPath={hooks}"]

    def inspect(*arguments, absent):
        result = bounded.run([*argv, *arguments], timeout=timeout, env=env)
        if result.returncode not in {0, absent}:
            raise ContractError(f"Cannot inspect publication pin: {path}: {ref}: "
                                + result.stderr.decode(errors="replace").strip())
        return result

    symbolic = inspect("symbolic-ref", "--quiet", ref, absent=1)
    if symbolic.returncode == 0:
        raise ContractError(f"Publication pin collision: {path}: {ref} is symbolic; existing ref preserved")
    # --quiet distinguishes absence from inspection failure; the hash lookup
    # below must then succeed and identify this exact direct ref.
    if inspect("show-ref", "--verify", "--quiet", ref, absent=1).returncode == 1:
        if descendants:
            common = Path(inspect("rev-parse", "--path-format=absolute", "--git-common-dir", absent=0)
                          .stdout.decode().strip())
            children = sorted(child for child in _pin_refs(common) if child.startswith(ref + "/"))
            if children:
                # Git's ref transaction refuses this namespace, even when
                # for-each-ref omitted a dangling symbol from the clone. Git's
                # own wording varies by version, so only the prefix matches it.
                raise ContractError(f"Cannot create publication pin: {path}: {ref}: "
                                    f"'{children[0]}' exists below it")
        return False
    current = inspect("show-ref", "--verify", "--hash", ref, absent=0)
    if current.stdout.decode().strip() != commit:
        raise ContractError(f"Publication pin collision: {path}: {ref} has another target; existing ref preserved")
    return True


def create_pin(path, ref, commit, *, env=None, hooks=None):
    """Create under Git's ref lock; never replace even a dangling symbolic pin."""
    if check_pin(path, ref, commit, env=env, hooks=hooks):
        return
    argv = ["git", "-C", str(path)]
    if hooks is not None:
        argv += ["-c", f"core.hooksPath={hooks}"]
    with bounded.stream([*argv, "update-ref", "--no-deref", "--stdin"],
                        timeout=GIT_TIMEOUT, stdin=subprocess.PIPE, env=env) as child:
        try:
            child.stdin.write(f"start\ncreate {ref} {commit}\nprepare\n".encode())
            child.stdin.flush()
            if (child.stdout.readline() != b"start: ok\n"
                    or child.stdout.readline() != b"prepare: ok\n"):
                child.stdin.close()
                child.wait()
                if check_pin(path, ref, commit, env=env, hooks=hooks, timeout=child.remaining()):
                    return  # An identical direct pin is already durable.
                raise ContractError(f"Cannot create publication pin: {path}: {ref}: "
                                    + child.stderr.decode(errors="replace").strip())
            # A zero old OID alone also accepts a dangling symbolic ref. Check
            # after prepare, while Git holds the ref lock, before any promotion.
            check_pin(path, ref, commit, env=env, hooks=hooks, timeout=child.remaining())
            child.stdin.write(b"commit\n")
            child.stdin.flush()
            if child.stdout.readline() != b"commit: ok\n":
                raise ContractError(f"Cannot create publication pin: {path}: {ref}")
        finally:
            # EOF aborts any explicitly started, uncommitted transaction and
            # releases its ref lock, including on a failed inspection.
            child.stdin.close()
            child.wait()


def disposable_clone(source, destination, revision):
    """Borrow existing objects read-only; all new objects and refs belong to the clone."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    hooks = destination.parent / (destination.name + "-empty-hooks")
    hooks.mkdir()
    disposable_git(source, "clone", "--shared", "--template=", "--no-checkout",
                   "-c", f"core.hooksPath={hooks}", "--", str(source), str(destination), hooks=hooks)
    # Normal clone omits publication pins and other private refs. They are input
    # evidence, but any pins the engine adds here must never become production input.
    # Flattening historical symbolic pins preserves their lineage read value;
    # preparation checks the source ref only when it would write that exact pin.
    refs = disposable_git(source, "for-each-ref", "--format=%(objectname) %(refname)")
    rows = [row.split() for row in refs.splitlines()]
    disposable_git(destination, "update-ref", "--no-deref", "--stdin", hooks=hooks,
            data=b"".join(b"update " + name + b" " + oid + b"\n"
                          for oid, name in rows if not name.startswith(b"refs/wiki-publications/")))
    for oid, name in rows:
        if name.startswith(b"refs/wiki-publications/"):
            create_pin(destination, name.decode(), oid.decode(), env=disposable_environment(), hooks=hooks)
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


def publication_provenance(root):
    """Index destination commits from hash-valid receipts matching committed history."""
    commits, errors = {}, []
    records = [path for path in sorted((root / "publications").glob("*.json"))
               if path.name != "latest.json"]
    for path in records:
        try:
            path = within(root, path.relative_to(root))
            data = path.read_bytes()
            envelope = json.loads(data.decode("utf-8"))
            payload = envelope["payload"]
            if envelope.get("sha256") != digest(json_bytes(payload)):
                raise ValueError("content hash differs")
            if (payload.get("schema_version") != 1
                    or not re.fullmatch(r"[0-9a-f]{64}", payload.get("release_id", ""))
                    or payload.get("status") != "published"):
                raise ValueError("not a completed publication receipt")
            # Legacy rehearsals could write valid receipts and retain real gates.
            # Only reviewed, committed bytes establish publication provenance.
            committed = bounded.run(["git", "-C", str(root), "cat-file", "blob",
                                     "HEAD:" + path.relative_to(root).as_posix()], timeout=GIT_TIMEOUT)
            if committed.returncode or committed.stdout != data:
                continue
            record_commits = {}
            for destination, row in payload["repositories"].items():
                key = (destination, row["path"], row["name"])
                if not all(isinstance(value, str) and value for value in key):
                    raise ValueError("invalid destination identity")
                # old_pages preserves adopted history, including 0.8.318's
                # adoption of the abandoned 4f077e3e publication.
                values = [row.get(field) for field in ("main", "old_main", "pages", "old_pages")]
                recovery = row.get("recovery") or {}
                values += [recovery.get("stuck"), recovery.get("successor")]
                qualified = {value for value in values if isinstance(value, str)
                             and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value)}
                record_commits.setdefault(key, set()).update(qualified)
            for key, qualified in record_commits.items():
                commits.setdefault(key, set()).update(qualified)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
            errors.append({"path": path.relative_to(root).as_posix(), "error": str(exc)})
    return commits, errors


def _pin_refs(common):
    """Read raw loose and packed pin refs, including dangling symbolic refs."""
    pins = {}
    packed = common / "packed-refs"
    if packed.exists():
        for line in packed.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1].startswith("refs/wiki-publications/"):
                commit, ref = fields
                pins[ref] = commit
    # Loose refs override packed refs. Git's iterator skips dangling symbols,
    # so read their names and targets directly without following or editing them.
    for file in sorted((common / "refs/wiki-publications").rglob("*")):
        if file.name.endswith(".lock"):
            continue
        ref = file.relative_to(common).as_posix()
        if file.is_symlink():
            # core.preferSymlinkRefs writes symbolic refs as filesystem links.
            pins[ref] = "ref: " + Path(os.readlink(file)).as_posix()
        elif file.is_file():
            pins[ref] = file.read_text(encoding="utf-8").strip()
    return pins


def unprovenanced_pins(path, provenance):
    """Read every pin, retaining ambiguous refs unchanged for operator review."""
    common = Path(bounded_git(path, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    pins = {}
    for ref, value in sorted(_pin_refs(common).items()):
        if value.startswith("ref: "):
            resolved = bounded.run(["git", "-C", str(path), "rev-parse", "--verify", "--quiet", ref],
                                   timeout=GIT_TIMEOUT)
            if resolved.returncode not in {0, 1}:
                raise ContractError(f"Cannot resolve publication pin: {path}: {ref}")
            pins[ref] = {"ref": ref, "commit": resolved.stdout.decode().strip() if resolved.returncode == 0 else None,
                         "symbolic_target": value[5:]}
        else:
            pins[ref] = {"ref": ref, "commit": value}
    return [pins[ref] for ref in sorted(pins) if pins[ref]["commit"] not in provenance]


def owned_lineage(path, base, head, *, provenance=()):
    """True when `head` fast-forwards `base` only through commits this workspace published.

    An abandoned publication leaves its pushed commits on the remote branch. Each commit
    after `base` must have both an exact pin and durable publication provenance for
    this destination, or carry a tree already on that line (a byte-identical restore).
    Anything else stays refused."""
    if not head:
        return False
    deadline = time.monotonic() + GIT_LINEAGE_TIMEOUT

    def remaining():
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise subprocess.TimeoutExpired(["git", "-C", str(path), "rev-list", "--reverse", head],
                                            GIT_LINEAGE_TIMEOUT)
        return budget

    def succeeds(*args):
        try:
            return bounded.run(["git", "-C", str(path), *args],
                               timeout=min(GIT_TIMEOUT, remaining())).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def pinned(revision):
        if revision not in provenance:
            return False
        try:
            result = bounded.run(["git", "-C", str(path), "show-ref", "--verify", "--hash",
                                  "refs/wiki-publications/" + revision],
                                 timeout=min(GIT_TIMEOUT, remaining()))
            return result.returncode == 0 and result.stdout.decode().strip() == revision
        except subprocess.TimeoutExpired:
            return False

    if not succeeds("cat-file", "-e", head + "^{commit}") or (base and not succeeds("merge-base", "--is-ancestor", base, head)):
        return False
    # Without a completed baseline, the lineage must start at a provenanced pin.
    trees = {bounded_git(path, "rev-parse", base + "^{tree}",
                         timeout=min(GIT_TIMEOUT, remaining()))} if base else set()
    with closing(git_records(path, "rev-list", "--reverse", head, *(["^" + base] if base else []),
                             separator=b"\n", timeout=remaining())) as revisions:
        for raw_revision in revisions:
            revision = raw_revision.decode()
            tree = bounded_git(path, "rev-parse", revision + "^{tree}",
                               timeout=min(GIT_TIMEOUT, remaining()))
            if tree not in trees and not pinned(revision):
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


def bounded_git(path, *arguments, timeout=None):
    try:
        result = bounded.run(["git", "-C", str(path), *arguments],
                             timeout=GIT_TIMEOUT if timeout is None else timeout)
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
