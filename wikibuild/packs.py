"""Bounded immutable JSON maps, shared by snapshot indexes and browser lookup."""

import json
from bisect import bisect_right

from .storage import ContractError, digest


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def partition(records, limit):
    """Split by key prefixes, so inserting one key changes only its prefix bucket."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 256:
        raise ContractError("JSON pack limit must be at least 256 bytes")
    items = [(key, compact(key) + b":" + value) for key, value in sorted(records.items())]

    def split(values, depth):
        size = 2 + max(0, len(values) - 1) + sum(len(value) for _, value in values)
        if size <= limit:
            if values:
                yield values, b"{" + b",".join(value for _, value in values) + b"}"
            return
        if len(values) == 1:
            raise ContractError(f"Selected record exceeds JSON pack limit: {values[0][0]} ({size} bytes)")
        buckets = {}
        for key, value in values:
            buckets.setdefault(key[:depth + 1], []).append((key, value))
        for bucket in buckets.values():
            yield from split(bucket, depth + 1)

    yield from split(items, 0)


def write(records, limit, output):
    shards = []
    for rows, data in partition(records, limit):
        sha = digest(data)
        path = f"data/{sha}.json"
        output(path, data)
        shards.append({"path": path, "sha256": sha, "bytes": len(data),
                       "first": rows[0][0], "last": rows[-1][0], "count": len(rows)})
    return shards


def reuse(records, known, limit, output):
    """Append only previously unseen revisions; retain earlier immutable packs."""
    fresh = {key: value for key, value in records.items() if key not in known}
    added = write(fresh, limit, output)
    starts = [shard["first"] for shard in added]
    for key in fresh:
        known[key] = added[bisect_right(starts, key) - 1]
    return sorted({known[key]["path"]: known[key] for key in records}.values(), key=lambda shard: (shard["first"], shard["path"]))
