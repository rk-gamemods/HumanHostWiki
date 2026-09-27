"""Read selected immutable Git blobs in place, through one streaming process.

No worktree copies, persistent raw index, or process per source object. Adapters
declare their input paths; object lookups group requested IDs by catalog shard.
"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

from .storage import ContractError, git


class Source:
    def __init__(self, path, revision):
        self.path = Path(path).resolve()
        self.revision = git(self.path, "rev-parse", "--verify", revision + "^{commit}")
        tree = subprocess.run(["git", "-C", str(self.path), "ls-tree", "-r", "-z", "-l", self.revision],
                              check=True, capture_output=True).stdout
        self.blobs = {}
        for entry in tree.split(b"\0"):
            if not entry:
                continue
            metadata, name = entry.split(b"\t", 1)
            mode, kind, oid, size = metadata.split()
            if kind == b"blob" and mode in {b"100644", b"100755"}:
                self.blobs[name.decode("utf-8")] = {"git_blob": oid.decode(), "bytes": int(size)}
        self.dependencies = {}
        self.locations = {}
        self.bytes_read = 0
        self._active = False
        self.process = None

    def __enter__(self):
        self.process = subprocess.Popen(["git", "-C", str(self.path), "cat-file", "--batch"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self

    def __exit__(self, kind, value, traceback):
        self.process.stdin.close()
        self.process.stdout.close()
        error = self.process.stderr.read()
        self.process.stderr.close()
        code = self.process.wait()
        if code and kind is None:
            raise ContractError(f"Git source reader failed: {error.decode('utf-8', errors='replace')}")

    def identity(self, path):
        if not isinstance(path, str) or ".." in PurePosixPath(path).parts or path not in self.blobs:
            raise ContractError(f"Missing or unsupported source input: {path}")
        return self.blobs[path]

    @contextmanager
    def lines(self, path):
        """Drain a blob even when a consumer stops early; preserve batch framing."""
        entry = self.identity(path)
        if self._active:
            raise ContractError("Nested source reads are unsupported; finish the current stream first")
        self._active = True
        remaining = entry["bytes"]
        sha = hashlib.sha256()
        try:
            self.process.stdin.write((entry["git_blob"] + "\n").encode("ascii"))
            self.process.stdin.flush()
            header = self.process.stdout.readline().decode("ascii").strip()
            if header != f"{entry['git_blob']} blob {remaining}":
                raise ContractError(f"Invalid Git blob response for {path}: {header}")

            def read_lines():
                nonlocal remaining
                while remaining:
                    line = self.process.stdout.readline(remaining)
                    if not line:
                        raise ContractError(f"Truncated Git blob: {path}")
                    remaining -= len(line)
                    sha.update(line)
                    self.bytes_read += len(line)
                    yield line

            try:
                yield read_lines()
            finally:
                # Bounded drain avoids allocating an entire skipped catalog shard.
                while remaining:
                    block = self.process.stdout.read(min(remaining, 1024 * 1024))
                    if not block:
                        raise ContractError(f"Truncated Git blob: {path}")
                    remaining -= len(block)
                    sha.update(block)
                    self.bytes_read += len(block)
                if self.process.stdout.read(1) != b"\n":
                    raise ContractError(f"Invalid Git blob terminator: {path}")
                self.dependencies[path] = {**entry, "sha256": sha.hexdigest()}
        finally:
            self._active = False

    def json(self, path):
        with self.lines(path) as lines:
            try:
                return json.loads(b"".join(lines))
            except (ValueError, UnicodeError) as exc:
                raise ContractError(f"Malformed JSON input: {path}") from exc

    def records(self, path):
        with self.lines(path) as lines:
            for number, line in enumerate(lines, 1):
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise ContractError(f"Malformed JSONL input: {path}:{number}") from exc
                if not isinstance(row, dict):
                    raise ContractError(f"Expected object record: {path}:{number}")
                yield row

    @staticmethod
    def object_path(identity):
        try:
            shard, object_id = identity.rsplit("#", 1)
            int(object_id)
        except (ValueError, AttributeError) as exc:
            raise ContractError(f"Invalid source object identity: {identity}") from exc
        return "Catalog/objects/" + shard.replace("::", "/") + ".jsonl"

    def objects(self, identities):
        by_path = {}
        for identity in identities:
            by_path.setdefault(self.object_path(identity), set()).add(identity)
        result = {}
        for path, wanted in sorted(by_path.items()):
            if path not in self.blobs:
                self.dependencies[path] = {"missing": True}
                continue
            remaining = set(wanted)
            local = (self.path / path).resolve()
            if local.is_relative_to(self.path) and local.is_file():
                with local.open("rb") as handle:
                    for identity in sorted(wanted):
                        location = self.locations.get(identity)
                        if not location:
                            continue
                        offset, size = location.get("offset"), location.get("bytes")
                        if type(offset) is not int or type(size) is not int or offset < 0 or size < 1 or offset + size > self.blobs[path]["bytes"]:
                            raise ContractError(f"Invalid source record location: {identity}")
                        handle.seek(offset)
                        data = handle.read(size)
                        self.bytes_read += len(data)
                        if hashlib.sha256(data).hexdigest() != location.get("sha256"):
                            # A historical commit or different line endings may
                            # need the immutable blob. Never accept stale ranges.
                            continue
                        try:
                            row = json.loads(data)
                        except (ValueError, UnicodeError) as exc:
                            raise ContractError(f"Malformed source record location: {identity}") from exc
                        if not isinstance(row, dict) or row.get("id") != identity:
                            raise ContractError(f"Source record location identity mismatch: {identity}")
                        result[identity] = row
                        remaining.remove(identity)
                        self.dependencies[path] = {**self.blobs[path], "access": "verified-record-ranges"}
            if not remaining:
                continue
            with self.lines(path) as lines:
                for line in lines:
                    try:
                        row = json.loads(line)
                    except (ValueError, UnicodeError) as exc:
                        raise ContractError(f"Malformed source object record: {path}") from exc
                    if not isinstance(row, dict):
                        raise ContractError(f"Expected source object record: {path}")
                    identity = row.get("id")
                    if identity in remaining:
                        if identity in result:
                            raise ContractError(f"Duplicate source object: {identity}")
                        location = self.locations.get(identity)
                        if location and hashlib.sha256(line).hexdigest() != location.get("sha256"):
                            raise ContractError(f"Indexed record hash differs from pinned source: {identity}")
                        result[identity] = row
        return result

    def changed_paths(self, previous):
        if previous is None:
            return {path: "A" for path in self.blobs}
        output = subprocess.run(["git", "-C", str(self.path), "diff", "--name-status", "-z", "--no-renames",
                                 previous, self.revision, "--"], check=True, capture_output=True).stdout
        fields = output.rstrip(b"\0").split(b"\0") if output else []
        return {fields[index + 1].decode("utf-8"): fields[index].decode("ascii") for index in range(0, len(fields), 2)}
