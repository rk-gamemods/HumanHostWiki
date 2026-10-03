"""Versioned generated-file receipts, with bounded immutable metadata pages.

encode/decode are pure except for supplied byte callbacks. Checkout and pinned-Git
adapters share the codec; Git reads use one batch process per receipt.
"""

import json
import re
import subprocess

from . import bounded

from . import capacity, packs, shard_index
from .storage import ContractError, digest, json_bytes, within

OWNER_FILE = ".wiki-output.json"
PAGE_DIRECTORY = ".wiki-ownership"
PAGE_PATH = re.compile(r"\.wiki-ownership/([0-9a-f]{64})\.json")
ISSUE_TEMPLATE = re.compile(r"\.github/ISSUE_TEMPLATE/[A-Za-z0-9-]+\.yml")
PAGE_BYTES = 64 * 1024


def validate(value):
    if value.get("schema_version") != 1 or value.get("kind") != "generated-wiki-output":
        raise ContractError("Unknown generated-output ownership")
    files = value["files"]
    if not isinstance(files, dict):
        raise ContractError("Invalid ownership file map")
    for name, meta in files.items():
        if (not isinstance(name, str) or "\\" in name or ":" in name or
                any(part in {"", ".", ".."} for part in name.split("/")) or
                (name not in {"README.md", ".gitattributes"} and not name.startswith(("site/", "reference/")) and
                 ISSUE_TEMPLATE.fullmatch(name) is None)):
            raise ContractError(f"Generated ownership escapes site/reference: {name}")
        if (not isinstance(meta, dict) or set(meta) != {"sha256", "bytes"} or
                not isinstance(meta["sha256"], str) or not capacity.SHA.fullmatch(meta["sha256"]) or
                type(meta["bytes"]) is not int or meta["bytes"] < 0):
            raise ContractError(f"Invalid ownership file record: {name}")
    allocated = value.get("capacity_objects", [name for name in files if capacity.OBJECT.fullmatch(name)])
    if (not isinstance(allocated, list) or any(not isinstance(name, str) for name in allocated) or
            len(allocated) != len(set(allocated)) or
            any(name not in files or not capacity.OBJECT.fullmatch(name) for name in allocated)):
        raise ContractError("Invalid ownership allocation membership")
    return {**value, "capacity_objects": sorted(allocated)}


def encode(value, limit, emit):
    """Return root bytes and page metadata; emit(name, bytes) stages a new page."""
    value = validate(value)
    raw, page_limit = json_bytes(value), min(limit, PAGE_BYTES)
    if len(raw) <= page_limit:
        return raw, {}
    allocated = set(value["capacity_objects"])
    records = {name: packs.compact({**meta, **({"allocated": True} if name in allocated else {})})
               for name, meta in value["files"].items()}
    pages = {}

    def output(data):
        sha = digest(data)
        name, meta = f"{PAGE_DIRECTORY}/{sha}.json", {"sha256": sha, "bytes": len(data)}
        if name not in pages:
            emit(name, data)
            pages[name] = meta
        return {"path": name, **meta}

    refs = [{**output(data), "first": rows[0][0], "last": rows[-1][0], "count": len(rows)}
            for rows, data in packs.partition(records, page_limit)]
    root = {key: item for key, item in value.items() if key not in {"files", "capacity_objects"}}
    root.update(schema_version=2, file_index=refs, file_count=len(records),
                files_sha256=digest(json_bytes(value["files"])), allocated_count=len(allocated))
    roots = shard_index.compact({("ownership", "files"): packs.compact(root)}, page_limit,
                               lambda batch: [output(data) for _, data in batch], fields=("file_index",))
    return roots[("ownership", "files")], pages


def decode(raw, fetch):
    """Return the legacy logical view and the exact referenced metadata pages."""
    pages, files, allocated = {}, {}, []

    def rows(refs, depth=0):
        if depth >= 32 or not isinstance(refs, list):
            raise ContractError("Invalid ownership page directory depth")
        previous = None
        for ref in refs:
            if (not isinstance(ref["first"], str) or not isinstance(ref["last"], str) or
                    ref["first"] > ref["last"] or (previous is not None and ref["first"] <= previous) or
                    type(ref["count"]) is not int or ref["count"] < 1):
                raise ContractError("Invalid or duplicate ownership range")
            previous = ref["last"]
            name = ref["path"]
            match = PAGE_PATH.fullmatch(name)
            if (not match or match[1] != ref["sha256"] or type(ref["bytes"]) is not int or
                    not 0 < ref["bytes"] <= PAGE_BYTES or name in pages):
                raise ContractError("Invalid or duplicate ownership page reference")
            try:
                data = fetch(name)
            except (OSError, KeyError) as error:
                raise ContractError(f"Cannot read ownership page: {name}") from error
            if len(data) != ref["bytes"] or digest(data) != ref["sha256"]:
                raise ContractError(f"Modified ownership page: {name}")
            pages[name] = {"sha256": ref["sha256"], "bytes": ref["bytes"]}
            page = json.loads(data)
            if ref.get("kind"):
                if ref["kind"] != shard_index.KIND or page.get("kind") != ref["kind"] or page.get("schema_version") != 1:
                    raise ContractError("Unknown ownership page directory")
                children = page["shards"]
                if (not children or children[0]["first"] != ref["first"] or children[-1]["last"] != ref["last"] or
                        sum(child["count"] for child in children) != ref["count"]):
                    raise ContractError("Ownership page directory summary differs")
                yield from rows(children, depth + 1)
            else:
                if len(page) != ref["count"] or min(page) != ref["first"] or max(page) != ref["last"]:
                    raise ContractError("Ownership page summary differs")
                yield from page.items()

    try:
        value = json.loads(raw)
        if value.get("schema_version") == 1:
            return validate(value), pages
        if value.get("schema_version") != 2 or value.get("kind") != "generated-wiki-output":
            raise ContractError("Unknown generated-output ownership")
        for name, meta in rows(value["file_index"]):
            if name in files or set(meta) - {"sha256", "bytes", "allocated"} or type(meta.get("allocated", False)) is not bool:
                raise ContractError("Invalid or duplicate ownership file record")
            files[name] = {key: item for key, item in meta.items() if key != "allocated"}
            if meta.get("allocated"):
                allocated.append(name)
        if (len(files) != value["file_count"] or digest(json_bytes(files)) != value["files_sha256"] or
                len(allocated) != value["allocated_count"]):
            raise ContractError("Ownership membership summary differs")
        result = {key: item for key, item in value.items()
                  if key not in {"file_index", "file_count", "files_sha256", "allocated_count"}}
        result.update(schema_version=1, files=files, capacity_objects=allocated)
        return validate(result), pages
    except ContractError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ContractError("Malformed generated-output ownership") from error


def checkout(path):
    if (path / OWNER_FILE).is_symlink() or (path / PAGE_DIRECTORY).is_symlink():
        raise ContractError("Ownership metadata must not be a symbolic link")
    marker = within(path, OWNER_FILE)
    if not marker.exists():
        return {"files": {}, "capacity_objects": []}, {}
    return decode(marker.read_bytes(), lambda name: within(path, name).read_bytes())


# A receipt may include many ownership pages, but never the full raw catalog.
GIT_STREAM_TIMEOUT = 600


def committed(path, commit):
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit):
        raise ContractError("Ownership read requires a pinned commit")
    with bounded.stream(["git", "-C", str(path), "cat-file", "--batch"],
                        timeout=GIT_STREAM_TIMEOUT, stdin=subprocess.PIPE) as process:
        def fetch(name):
            if name != OWNER_FILE and not PAGE_PATH.fullmatch(name):
                raise ContractError("Invalid committed ownership path")
            process.stdin.write(f"{commit}:{name}\n".encode())
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob" or not header[2].isdigit():
                raise ContractError(f"Missing committed ownership page: {name}")
            size = int(header[2])
            if name != OWNER_FILE and size > PAGE_BYTES:
                raise ContractError("Committed ownership page exceeds the page budget")
            data = process.stdout.read(size)
            if len(data) != size or process.stdout.read(1) != b"\n":
                raise ContractError("Invalid committed ownership object boundary")
            return data
        result = decode(fetch(OWNER_FILE), fetch)
        process.stdin.close()
        if process.wait():
            raise ContractError("Git ownership read failed")
        return result
