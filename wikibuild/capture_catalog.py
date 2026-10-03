"""Bound release capture lists; allocation owns all I/O and physical locations.

ID lookup and chronological browsing share one record per capture. Ordinals count
from the oldest capture, so a newly prepended capture leaves older records stable.
"""

import json

from . import packs, shard_index
from .storage import ContractError

FIELDS = ("by_id", "by_order")


def compact(configurations, limit, emit):
    """Keep small configurations unchanged; page oversized capture collections.

    emit accepts [(topic, bytes)] and returns allocated path/hash/size references.
    The default capture stays inline so ordinary startup needs no catalog reads.
    """
    result, roots, configs, requests, plans = dict(configurations), {}, {}, [], []
    page_limit = min(limit, shard_index.PAGE_BYTES)
    for topic, data in sorted(configurations.items()):
        if len(data) <= page_limit:
            continue
        value = json.loads(data)
        if "paged-captures-v1" not in value.get("features", []):
            raise ContractError("Reader runtime does not support paged captures; regenerate the candidate")
        versions, snapshots = value.pop("versions"), value.pop("snapshots")
        if len(versions) != len(snapshots) or {v["snapshot_id"] for v in versions} != set(snapshots):
            raise ContractError("Capture catalog snapshot coverage differs")
        records, order = {}, {}
        for position, version in enumerate(versions):
            identity, ordinal = version["snapshot_id"], len(versions) - position - 1
            record = {"version": version, "index": snapshots[identity], "ordinal": ordinal}
            records[identity] = packs.compact(record)
            order[f"{ordinal:016d}"] = packs.compact(identity)
            if identity == value["default_snapshot"]:
                value["default_capture"] = record
        if "default_capture" not in value:
            raise ContractError("Capture catalog default is unavailable")
        configs[topic] = value
        root = {"schema_version": 1, "kind": "wiki-capture-catalog", "count": len(versions)}
        roots[(topic, "captures")] = root
        for field, rows in (("by_id", records), ("by_order", order)):
            root[field] = []
            for items, raw in packs.partition(rows, page_limit):
                requests.append((topic, raw))
                plans.append((root[field], items[0][0], items[-1][0], len(items)))
    if not roots:
        return result
    refs = emit(requests)
    if len(refs) != len(plans):
        raise ContractError("Capture catalog allocation omitted a page")
    for (target, first, last, count), ref in zip(plans, refs):
        target.append({**ref, "first": first, "last": last, "count": count})
    bounded = shard_index.compact({key: packs.compact(value) for key, value in roots.items()},
                                  page_limit, emit, fields=FIELDS)
    keys = sorted(bounded)
    refs = emit([(key[0], bounded[key]) for key in keys])
    if len(refs) != len(keys):
        raise ContractError("Capture catalog allocation omitted a root")
    for (topic, _), ref in zip(keys, refs):
        value = configs[topic]
        value["capture_catalog"] = ref
        raw = packs.compact(value)
        if len(raw) > limit:
            raise ContractError("Release configuration metadata exceeds the file budget")
        result[topic] = raw
    return result
