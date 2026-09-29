"""Transform reader metadata after its immutable dependencies have locations."""

import json
import re

from . import packs, shard_index
from .storage import ContractError, json_bytes

SHARD_KINDS = shard_index.FIELDS


def indexed(data, resolve, fields):
    """Resolve only declared pack references; retain original bytes when unchanged.

    resolve receives a candidate-relative path and its expected hash/size, and
    returns the public path. Paths inside facts or evidence are never rewritten.
    The browser resolves these paths against the logical topic's entrypoint,
    regardless of which physical repository stores this index.
    """
    value = json.loads(data)
    if value.get("schema_version") != 1:
        raise ContractError("Unsupported snapshot schema during release projection")
    changed = False
    for kind in fields:
        if kind == "cards" and kind not in value:
            continue
        for reference in value[kind]:
            path = reference["path"]
            if (re.fullmatch(r"data/[0-9a-f]{64}\.json", path) is None or
                    path != "data/" + reference["sha256"] + ".json"):
                raise ContractError("Snapshot pack reference is not content-addressed")
            resolved = resolve(path, reference["sha256"], reference["bytes"])
            changed |= resolved != path
            reference["path"] = resolved
    return packs.compact(value) if changed else data


def snapshot(data, resolve):
    return indexed(data, resolve, SHARD_KINDS)


def configuration(data, release_id, snapshots, runtime, external_articles=None):
    value = json.loads(data)
    if value.get("schema_version") != 1:
        raise ContractError("Unsupported reader schema during release projection")
    if set(snapshots) != {version["snapshot_id"] for version in value["versions"]}:
        raise ContractError("Release snapshot coverage differs from reader versions")
    if set(runtime) != {"js", "css"}:
        raise ContractError("Release requires both reader runtimes")
    if value.get("external_articles"):
        if not external_articles:
            raise ContractError("External article projection is missing")
        value["external_articles"] = external_articles
    value.update(release_id=release_id, publication="prepared-git-release",
                 snapshots=snapshots, runtime=runtime)
    return json_bytes(value)
