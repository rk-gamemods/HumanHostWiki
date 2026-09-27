"""Validated, reusable selected facts. This stage alone is not a wiki release."""

import hashlib
import json
import os
from pathlib import Path
import uuid

from .adapters import ADAPTERS
from .exceptions import Exceptions
from .source import Source
from .storage import ContractError, digest, git, json_bytes, within, write_changed


def contract(root, project):
    modules = ["extraction.py", "source.py", "source_record.py", "exceptions.py", "storage.py"]
    paths = [Path(__file__).parent / name for name in modules]
    paths += sorted((Path(__file__).parent / "adapters").glob("*.py"))
    return digest(json_bytes({
        "schema": 1, "adapters": {adapter.NAME: adapter.VERSION for adapter in ADAPTERS},
        "code": {p.relative_to(Path(__file__).parent).as_posix(): digest(p.read_bytes().replace(b"\r\n", b"\n")) for p in paths},
        "owners": {repo["id"]: repo["owns"] for repo in project["repositories"]},
    }))


def file_hash(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def artifact(root, record):
    path = within(root, record["path"])
    if not path.is_file() or path.stat().st_size != record["bytes"] or file_hash(path) != record["sha256"]:
        raise ContractError(f"Extraction artifact missing or modified: {record['path']}")
    return path


def read(root, identity):
    if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise ContractError("Invalid extraction identity")
    result = json.loads(within(root, f".local/extractions/runs/{identity}.json").read_text(encoding="utf-8"))
    if result.get("schema_version") != 1 or result.get("run_id") != identity:
        raise ContractError("Extraction receipt identity or schema mismatch")
    artifact(root, result["records"])
    artifact(root, result["exceptions"])
    return result


def store_file(root, temporary, suffix):
    sha = file_hash(temporary)
    relative = f".local/extractions/objects/{sha}.{suffix}"
    path = within(root, relative)
    record = {"path": relative, "sha256": sha, "bytes": temporary.stat().st_size}
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        artifact(root, record)
        temporary.unlink()
    else:
        os.rename(temporary, path)
    return record


def ensure_source(source, revision):
    if git(source, "rev-parse", "HEAD") != revision or git(source, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ContractError("Source changed during wiki extraction; prior result preserved")


def dependencies_match(inputs, dependencies):
    for path, dependency in dependencies.items():
        if dependency.get("missing"):
            if path in inputs.blobs:
                return False
        elif inputs.blobs.get(path) != {"git_blob": dependency["git_blob"], "bytes": dependency["bytes"]}:
            return False
    return True


def run(root, project, source, receipt):
    """Caller owns the wiki writer lock. Promote the pointer only after validation."""
    revision = receipt["source_commit"]
    ensure_source(source, revision)
    contract_hash = contract(root, project)
    run_id = digest(json_bytes([revision, contract_hash]))
    manifest_path = within(root, f".local/extractions/runs/{run_id}.json")
    pointer_path = within(root, ".local/extraction-latest.json")
    if manifest_path.exists():
        result = read(root, run_id)
        ensure_source(source, revision)
        write_changed(pointer_path, json_bytes({"run_id": run_id}))
        return result, {"reused": True, "source_bytes_read": 0}

    previous = None
    if pointer_path.exists():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        previous = read(root, pointer["run_id"])
    issues = Exceptions()
    owners = {kind: repo["id"] for repo in project["repositories"] for kind in repo["owns"]}
    staging = within(root, ".local/extractions/staging/" + uuid.uuid4().hex)
    staging.mkdir(parents=True)
    with Source(source, revision) as inputs:
        inputs.item_names = {}
        if previous and previous["contract_sha256"] == contract_hash and dependencies_match(inputs, previous["dependencies"]):
            result = {**previous, "run_id": run_id, "snapshot_id": receipt["snapshot_id"], "source_commit": revision}
            metrics = {"reused": True, "source_bytes_read": 0}
        else:
            counts, keys = {}, set()
            observers = [adapter.observe for adapter in ADAPTERS if hasattr(adapter, "observe")]
            for adapter in ADAPTERS:
                for path in adapter.INPUTS:
                    inputs.identity(path)
                if hasattr(adapter, "prepare"):
                    adapter.prepare(inputs, issues)
            declared_coverage = inputs.json("Catalog/coverage.json")
            if declared_coverage.get("objects") != inputs.catalog["coverage"]["objects"]:
                raise ContractError("Catalog object accounting differs from capture coverage")
            inputs.catalog["coverage"]["decode_gaps"] = declared_coverage.get("decode_gaps", [])
            with (staging / "records.jsonl").open("wb") as stream:
                for adapter in ADAPTERS:
                    for row in adapter.extract(inputs, issues):
                        key = row["observation_key"]
                        if key in keys:
                            raise ContractError(f"Duplicate observation: {key}")
                        keys.add(key)
                        for observe in observers:
                            observe(inputs, row)
                        row["topic"] = owners[row["kind"]]
                        if row["kind"] == "item":
                            inputs.item_names[row["source_id"]] = row["name"]
                        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
                        stream.write((json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode())
            (staging / "exceptions.json").write_bytes(json_bytes(issues.report()))
            result = {"schema_version": 1, "run_id": run_id, "snapshot_id": receipt["snapshot_id"],
                      "source_commit": revision, "contract_sha256": contract_hash,
                      "dependencies": inputs.dependencies, "counts": counts,
                      "coverage": inputs.catalog["coverage"],
                      "records": store_file(root, staging / "records.jsonl", "jsonl"),
                      "exceptions": store_file(root, staging / "exceptions.json", "json"),
                      "supported_kinds": sorted({kind for adapter in ADAPTERS for kind in adapter.KINDS}),
                      "topics_without_records": sorted(repo["id"] for repo in project["repositories"] if repo["role"] == "topic"
                                                 and not set(repo["owns"]).intersection(counts)),
                      "topic_coverage": {repo["id"]: {"status": "partial" if set(repo["owns"]).intersection(counts) else "no-records",
                                                     "kinds": sorted(set(repo["owns"]).intersection(counts))}
                                         for repo in project["repositories"] if repo["role"] == "topic"},
                      "status": "selected-facts-extracted", "wiki_release": "not-created"}
            metrics = {"reused": False, "source_bytes_read": inputs.bytes_read}
    ensure_source(source, revision)
    # Content-addressed output may survive interruption; it never claims success
    # until this receipt and then the last-success pointer are atomically written.
    write_changed(manifest_path, json_bytes(result))
    read(root, run_id)
    write_changed(pointer_path, json_bytes({"run_id": run_id}))
    staging.rmdir()
    return result, metrics
