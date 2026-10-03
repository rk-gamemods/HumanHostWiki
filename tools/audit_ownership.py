"""Independent receipt reader for release audits; no builder imports."""

import hashlib
import json
import re

from tools.audit_shard_index import leaves


def expand(owner, read_bytes):
    pages = {}
    if owner["schema_version"] == 1:
        return owner, pages
    assert owner["schema_version"] == 2 and owner["kind"] == "generated-wiki-output"

    def fetch(ref):
        name = ref["path"]
        assert re.fullmatch(r"\.wiki-ownership/[0-9a-f]{64}\.json", name)
        data = read_bytes(name)
        assert hashlib.sha256(data).hexdigest() == ref["sha256"] == name.split("/")[1][:-5]
        assert len(data) == ref["bytes"]
        pages[name] = {"sha256": ref["sha256"], "bytes": len(data)}
        return json.loads(data)

    files, allocated = {}, []
    for ref in leaves(owner["file_index"], fetch):
        page = fetch(ref)
        assert len(page) == ref["count"] and min(page) == ref["first"] and max(page) == ref["last"]
        for name, meta in page.items():
            assert name not in files
            assert set(meta) <= {"sha256", "bytes", "allocated"}
            files[name] = {"sha256": meta["sha256"], "bytes": meta["bytes"]}
            assert type(meta.get("allocated", False)) is bool
            if meta.get("allocated"):
                allocated.append(name)
    raw = (json.dumps(files, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    assert hashlib.sha256(raw).hexdigest() == owner["files_sha256"]
    assert len(files) == owner["file_count"] and len(allocated) == owner["allocated_count"]
    result = {k: v for k, v in owner.items() if k not in {"file_index", "file_count", "files_sha256", "allocated_count"}}
    result.update(schema_version=1, files=files, capacity_objects=sorted(allocated))
    return result, pages
