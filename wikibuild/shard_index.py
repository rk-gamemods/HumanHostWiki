"""Split oversized snapshot directories; allocation owns all external effects.

Small indexes keep their exact bytes. Large lists become bounded directory pages
whose range summaries allow the reader to skip unrelated branches. Each level is
allocated as a batch before its parent references are hashed.
"""

import json

from . import packs
from .storage import ContractError

FIELDS = ("entries", "semantics", "provenance", "search", "backlinks")
KIND = "wiki-shard-directory"
PAGE_BYTES = 64 * 1024


def groups(refs, limit):
    prefix = b'{"kind":"wiki-shard-directory","schema_version":1,"shards":['
    suffix = b']}'
    rows, encoded, size = [], [], len(prefix) + len(suffix)
    for ref in refs:
        data = packs.compact(ref)
        if len(prefix) + len(data) + len(suffix) > limit:
            raise ContractError("Snapshot directory reference exceeds the file budget")
        if rows and size + 1 + len(data) > limit:
            yield rows, prefix + b",".join(encoded) + suffix
            rows, encoded, size = [], [], len(prefix) + len(suffix)
        size += bool(rows) + len(data)
        rows.append(ref)
        encoded.append(data)
    if rows:
        yield rows, prefix + b",".join(encoded) + suffix


def compact(indexes, limit, emit):
    """Return bounded bytes for {(topic, snapshot): bytes}, preserving leaf order.

    emit receives [(topic, directory_bytes)] and returns path/hash/size references
    in the same order. It may allocate partitions, but must not promote a release.
    """
    result = dict(indexes)
    for _ in range(32):
        active = [(key, data) for key, data in sorted(result.items()) if len(data) > limit]
        if not active:
            return result
        requests, plans = [], []
        for key, data in active:
            value = json.loads(data)
            fixed = {name: [] if name in FIELDS else item for name, item in value.items()}
            if len(packs.compact(fixed)) > limit:
                raise ContractError("Snapshot metadata exceeds the file budget")
            candidates = [kind for kind in FIELDS if len(value[kind]) > 1]
            if not candidates:
                raise ContractError("Snapshot metadata cannot fit the file budget")
            kind = max(candidates, key=lambda field: len(packs.compact(value[field])))
            chunks = list(groups(value[kind], min(limit, PAGE_BYTES)))
            if len(chunks) >= len(value[kind]):
                raise ContractError("Snapshot directory budget cannot reduce its references")
            offset = len(requests)
            requests.extend((key[0], raw) for _, raw in chunks)
            plans.append((key, value, kind, chunks, offset, len(data)))
        allocated = emit(requests)
        if len(allocated) != len(requests):
            raise ContractError("Snapshot directory allocation omitted a page")
        for key, value, kind, chunks, offset, before_size in plans:
            value[kind] = [{**allocated[offset + number], "kind": KIND,
                            "first": min(row["first"] for row in rows),
                            "last": max(row["last"] for row in rows),
                            "count": sum(row["count"] for row in rows)}
                           for number, (rows, _) in enumerate(chunks)]
            data = packs.compact(value)
            if len(data) >= before_size:
                raise ContractError("Snapshot directory allocation did not reduce metadata")
            result[key] = data
    raise ContractError("Snapshot directory depth exceeds the supported budget")
