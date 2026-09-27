"""Own generated paths and stage only changed release bytes."""

import json

from . import capacity, extraction, workspace
from .storage import ContractError, digest, json_bytes, within

OWNER_FILE = ".wiki-output.json"
IMMUTABLE = ("site/data/", "site/objects/", "site/releases/", "site/runtime/")


def owned(path):
    marker = path / OWNER_FILE
    files = {}
    if marker.exists():
        data = json.loads(marker.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or data.get("kind") != "generated-wiki-output":
            raise ContractError(f"Unknown generated-output ownership: {path}")
        files = data["files"]
    for folder in ("site", "reference"):
        base = path / folder
        if base.is_symlink():
            raise ContractError(f"Generated directory is a symbolic link: {base}")
        if base.exists():
            for entry in base.rglob("*"):
                if entry.is_symlink() or (entry.is_file() and entry.relative_to(path).as_posix() not in files):
                    raise ContractError(f"Unknown file in generated namespace: {entry}")
    for name, record in files.items():
        if name != "README.md" and not name.startswith(("site/", "reference/")):
            raise ContractError(f"Generated ownership escapes site/reference: {name}")
        target = within(path, name)
        if not target.is_file() or target.stat().st_size != record["bytes"] or extraction.file_hash(target) != record["sha256"]:
            raise ContractError(f"Modified or missing owned output: {target}")
    return files


class Writer:
    def __init__(self, destination, stage, repo, release_id):
        self.destination, self.stage, self.repo, self.release_id = destination, stage, repo, release_id
        self.previous = owned(destination)
        self.marker = destination / OWNER_FILE
        old = json.loads(self.marker.read_bytes()) if self.marker.exists() else {}
        self.allocated = set(old.get("capacity_objects", [name for name in self.previous if capacity.OBJECT.fullmatch(name)]))
        readme = destination / "README.md"
        if repo["role"] != "partition" and "README.md" not in self.previous and readme.is_file() and readme.read_bytes() == workspace.seed_readme(repo):
            self.previous["README.md"] = {"sha256": extraction.file_hash(readme), "bytes": readme.stat().st_size}
        self.output, self.changes = dict(self.previous), {}

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

    def finish(self):
        if self.changes or not self.marker.exists():
            data = json_bytes({"schema_version": 1, "kind": "generated-wiki-output", "release_id": self.release_id,
                               "repository_id": self.repo["id"], "files": self.output,
                               "capacity_objects": sorted(self.allocated)})
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
