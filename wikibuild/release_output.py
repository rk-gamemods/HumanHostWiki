"""Own generated paths and stage only changed release bytes.

Each release's tree holds the generated files that release writes or keeps, plus
the immutable files of one retained release: the release a live hub may still
select while this one publishes. Its configuration and objects stay loadable until
the hub moves. Every other earlier site and reference file is removed through the
normal commit; Git history may still contain them.
"""

import subprocess

from . import bounded, capacity, extraction, ownership, workspace
from .storage import ContractError, digest, json_bytes, within

OWNER_FILE = ownership.OWNER_FILE
IMMUTABLE = ("site/data/", "site/objects/", "site/releases/", "site/runtime/", "site/fonts/")
GENERATED = ("site/", "reference/")
HUB_ATTRIBUTES = b"* text=auto eol=lf\n/.github/ISSUE_TEMPLATE/*.yml -text\n"


def retainable(name):
    """Only immutable paths can serve an earlier release beside the current one."""
    return name.startswith(IMMUTABLE) or capacity.OBJECT.fullmatch(name) is not None


def members(owner):
    """Files that belong to the receipt's own release, from its explicit membership."""
    retained = set(owner.get("retained_files", ()))
    return {name: meta for name, meta in owner["files"].items() if name not in retained}


def committed_blobs(path, commit, names):
    """Read committed file bytes through one Git process; binary-safe."""
    result = {}
    with bounded.stream(["git", "-C", str(path), "cat-file", "--batch"],
                        timeout=ownership.GIT_STREAM_TIMEOUT, stdin=subprocess.PIPE) as process:
        for name in names:
            process.stdin.write(f"{commit}:{name}\n".encode())
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob" or not header[2].isdigit():
                raise ContractError(f"Retained release file is missing from its pinned commit: {name}")
            size = int(header[2])
            data = process.stdout.read(size)
            if len(data) != size or process.stdout.read(1) != b"\n":
                raise ContractError("Invalid committed object boundary")
            result[name] = data
        process.stdin.close()
        if process.wait():
            raise ContractError("Git object read failed")
    return result


def owned(path, receipt=None):
    owner, pages = ownership.checkout(path) if receipt is None else receipt
    files = owner["files"]
    folders = ["site", "reference", ownership.PAGE_DIRECTORY]
    if owner.get("repository_id") == "hub":
        folders.append(".github/ISSUE_TEMPLATE")
    for folder in folders:
        base = path / folder
        if base.is_symlink():
            raise ContractError(f"Generated directory is a symbolic link: {base}")
        if base.exists():
            for entry in base.rglob("*"):
                allowed = pages if folder == ownership.PAGE_DIRECTORY else files
                if entry.is_symlink() or (entry.is_file() and entry.relative_to(path).as_posix() not in allowed):
                    raise ContractError(f"Unknown file in generated namespace: {entry}")
    for name, record in files.items():
        if name not in {"README.md", ".gitattributes"} and not name.startswith(("site/", "reference/")) and ownership.ISSUE_TEMPLATE.fullmatch(name) is None:
            raise ContractError(f"Generated ownership escapes site/reference: {name}")
        target = within(path, name)
        if not target.is_file() or target.stat().st_size != record["bytes"] or extraction.file_hash(target) != record["sha256"]:
            raise ContractError(f"Modified or missing owned output: {target}")
    return files


class Writer:
    def __init__(self, destination, stage, repo, release_id, retain=None):
        """retain is (release_id, member files, pinned commit, allocated objects) of the
        release to keep loadable, or None. The commit restores retained files a
        tree no longer holds; the allocated set keeps capacity accounting exact."""
        self.destination, self.stage, self.repo, self.release_id = destination, stage, repo, release_id
        receipt = ownership.checkout(destination)
        self.previous = owned(destination, receipt)
        self.marker = destination / OWNER_FILE
        old, self.pages = receipt
        self.previous_allocated = set(old["capacity_objects"])
        self.recorded = (frozenset(old.get("retained_files", ())), old.get("retained_release_id"))
        if retain is not None and retain[0] == release_id:
            raise ContractError("A release cannot retain itself")
        self.retain, self.removed = retain, set()
        # Allocation membership is rebuilt from this release's add and keep calls.
        self.allocated = set()
        readme = destination / "README.md"
        if repo["role"] != "partition" and "README.md" not in self.previous and readme.is_file() and readme.read_bytes() == workspace.seed_readme(repo):
            self.previous["README.md"] = {"sha256": extraction.file_hash(readme), "bytes": readme.stat().st_size}
        attributes = destination / ".gitattributes"
        if repo["role"] == "hub" and ".gitattributes" not in self.previous and attributes.is_file() and attributes.read_bytes() == b"* text=auto eol=lf\n":
            self.previous[".gitattributes"] = {"sha256": extraction.file_hash(attributes), "bytes": attributes.stat().st_size}
        # Generated site and reference files exist only when this release writes or keeps them.
        self.output = {name: meta for name, meta in self.previous.items() if not name.startswith(GENERATED)}
        self.changes = {}

    def add(self, name, data, *, allocated=False):
        record = {"sha256": digest(data), "bytes": len(data)}
        prior = self.previous.get(name)
        if name.startswith(IMMUTABLE) and prior and record != prior:
            raise ContractError(f"Immutable public object differs: {name}")
        self.output[name] = record
        if allocated:
            if capacity.OBJECT.fullmatch(name) is None:
                raise ContractError("Allocated object has an unsupported path")
            self.allocated.add(name)
        if prior == record:
            return
        target = within(self.destination, name)
        if prior is None and target.exists():
            raise ContractError(f"Refusing to adopt an unknown generated file: {target}")
        staged = within(self.stage, name)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        self.changes[name] = {"old": prior["sha256"] if prior else None, "new": record["sha256"], "bytes": len(data)}

    def keep(self, name, *, allocated=False):
        """Retain an unchanged owned file, such as a reused allocated object."""
        if name not in self.previous:
            raise ContractError(f"Cannot keep an unowned generated file: {name}")
        self.output[name] = self.previous[name]
        if allocated:
            if capacity.OBJECT.fullmatch(name) is None:
                raise ContractError("Allocated object has an unsupported path")
            self.allocated.add(name)

    def remove(self, name):
        if name not in self.previous:
            raise ContractError(f"Cannot remove an unowned generated file: {name}")
        self.output.pop(name, None)
        self.removed.add(name)

    def _retain(self):
        """Keep the retained release's immutable files this release does not own."""
        retained = set()
        if self.retain is None:
            return retained
        missing = []
        for name, meta in sorted(self.retain[1].items()):
            if name in self.output or name in self.removed or not retainable(name):
                continue
            prior = self.previous.get(name)
            if prior is None:
                # An earlier release dropped it; restore the exact bytes from the
                # retained release's pinned commit so its hub stays loadable.
                missing.append(name)
            elif prior != meta:
                raise ContractError(f"The tree holds different bytes for a file of retained release {self.retain[0][:12]}: {name}")
            self.output[name] = meta
            retained.add(name)
            if name in self.previous_allocated or (len(self.retain) > 3 and name in self.retain[3]):
                self.allocated.add(name)
        if missing:
            if len(self.retain) < 3:
                raise ContractError(f"The tree no longer holds a file of retained release {self.retain[0][:12]}: {missing[0]}")
            for name, data in committed_blobs(self.destination, self.retain[2], missing).items():
                meta = self.retain[1][name]
                if {"sha256": digest(data), "bytes": len(data)} != meta:
                    raise ContractError(f"Retained release file differs from its receipt: {name}")
                if within(self.destination, name).exists():
                    raise ContractError(f"Refusing to adopt an unknown generated file: {name}")
                staged = within(self.stage, name)
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(data)
                self.changes[name] = {"old": None, "new": meta["sha256"], "bytes": meta["bytes"]}
        return retained

    def finish(self, file_limit=capacity.Budgets().file_bytes):
        retained = self._retain()
        retained_id = self.retain[0] if retained else None
        for name in sorted(self.previous.keys() - self.output.keys()):
            self.changes[name] = {"old": self.previous[name]["sha256"], "new": None, "bytes": 0}
        # Membership is part of the receipt: a changed retained set needs a new
        # receipt even when no file bytes change.
        membership = (frozenset(retained), retained_id) != self.recorded
        if self.changes or membership or not self.marker.exists():
            def emit(name, data):
                prior = self.pages.get(name)
                meta = {"sha256": digest(data), "bytes": len(data)}
                if prior == meta:
                    return
                if (self.destination / name).exists():
                    raise ContractError(f"Refusing to adopt or change ownership metadata: {name}")
                target = within(self.stage, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                self.changes[name] = {"old": None, "new": meta["sha256"], "bytes": len(data)}

            receipt = {"schema_version": 1, "kind": "generated-wiki-output", "release_id": self.release_id,
                       "repository_id": self.repo["id"], "files": self.output,
                       "capacity_objects": sorted(self.allocated), "retained_files": sorted(retained)}
            if retained_id is not None:
                receipt["retained_release_id"] = retained_id
            data, pages = ownership.encode(receipt, file_limit, emit)
            # Receipts are read at pinned commits, not browser URLs. Their old
            # pages remain in Git history; HEAD needs only the current graph.
            for name in self.pages.keys() - pages.keys():
                self.changes[name] = {"old": self.pages[name]["sha256"], "new": None, "bytes": 0}
            (self.stage / OWNER_FILE).write_bytes(data)
            self.changes[OWNER_FILE] = {"old": extraction.file_hash(self.marker) if self.marker.exists() else None,
                                       "new": digest(data), "bytes": len(data)}
        else:
            # Full storage partitions stay frozen across later releases. A
            # receipt-only rewrite would consume history without new content.
            data = self.marker.read_bytes()
        return self.changes, {"files_sha256": digest(json_bytes(self.output)), "file_count": len(self.output),
                              "site_bytes": sum(meta["bytes"] for name, meta in self.output.items() if name.startswith("site/")),
                              "output_bytes": sum(meta["bytes"] for meta in self.output.values()),
                              "ownership_sha256": digest(data)}
