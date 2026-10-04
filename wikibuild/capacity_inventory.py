"""Read committed wiki ownership and measure reachable Git objects for allocation."""

from dataclasses import dataclass

from . import bounded, capacity, ownership, physical
from .storage import ContractError, git, within

# Reachable-object enumeration can span all retained releases and packed history.
GIT_HISTORY_TIMEOUT = 1800


@dataclass(frozen=True)
class Inventory:
    release_id: str
    topics: tuple[capacity.Topic, ...]
    partitions: tuple[capacity.Partition, ...]
    stored: tuple[capacity.Placement, ...]


def history_size(path, refs):
    """Stream unique reachable object sizes; no loose-object scan or payload decoding.

    Explicit refs scope this to exported history. Unrelated local branches and
    abandoned prepared objects are not evidence about a public repository's size.
    """
    if not refs or any(not isinstance(ref, str) or not ref or ref.startswith("-") for ref in refs):
        raise ContractError("History measurement needs explicit Git revisions")
    with bounded.stream(["git", "-C", str(path), "rev-list", "--objects", "--no-object-names", *refs, "--"],
                        timeout=GIT_HISTORY_TIMEOUT) as revisions, \
            bounded.stream(["git", "-C", str(path), "cat-file", "--batch-check=%(objecttype) %(objectsize)"],
                           timeout=GIT_HISTORY_TIMEOUT, stdin=revisions.stdout) as objects:
        revisions.stdout.close()
        total, count, blobs, largest = 0, 0, 0, 0
        for line in objects.stdout:
            row = line.split()
            if len(row) != 2 or row[0] not in {b"blob", b"tree", b"commit", b"tag"} or not row[1].isdigit():
                raise ContractError("Git returned an invalid object size during capacity measurement")
            size = int(row[1])
            total += size
            count += 1
            if row[0] == b"blob":
                blobs += 1
                largest = max(largest, size)
        object_exit, revision_exit = objects.wait(), revisions.wait()
        object_error = objects.stderr.decode(errors="replace")
        revision_error = revisions.stderr.decode(errors="replace")
        if object_exit or revision_exit:
            raise ContractError("Cannot measure Git history: " + (revision_error or object_error).strip()[:1000])
        return {"history_bytes": total, "objects": count, "blobs": blobs, "largest_blob_bytes": largest}


def read(root, project, manifest, published):
    """Measure committed ownership from records validated by the coordinator.

    Caller holds the workspace lock. None records describe an unreleased or
    unpublished baseline; this layer never loads coordinator state itself.
    """
    identity = manifest["release_id"] if manifest else None
    topics = tuple(capacity.Topic(repo["id"], repo["github_name"]) for repo in project["repositories"])
    registry = manifest.get("physical") if manifest else None
    repositories = physical.repositories(project, registry)
    owners = {topic.id: topic for topic in topics}
    partitions, stored = [], []
    for repo in repositories:
        path = within(root, repo["path"])
        if manifest:
            record = manifest["repositories"][repo["id"]]
            if record["github_name"] != repo["github_name"] or record["path"] != repo["path"]:
                raise ContractError("Released repository differs from its physical identity")
            commit = git(path, "rev-parse", "HEAD")
            owner, _ = ownership.committed(path, commit)
        else:
            if (path / ownership.OWNER_FILE).exists():
                raise ContractError("Owned outputs exist without a release baseline")
            commit, owner = git(path, "rev-parse", "HEAD"), {"files": {}}
        refs = [commit]
        if published and repo["id"] in published["repositories"]:
            prior = published["repositories"][repo["id"]]
            if prior["name"] != repo["github_name"]:
                raise ContractError("Published repository differs from capacity inventory")
            refs.append(prior["pages"])
        measured = history_size(path, refs)
        logical = repo.get("logical_topic", repo["id"])
        state = registry[repo["id"]] if registry else {"ordinal": 0, "sealed": False}
        site_bytes = sum(meta["bytes"] for name, meta in owner["files"].items() if name.startswith("site/"))
        partitions.append(capacity.partition(owners[logical], state["ordinal"], site_bytes=site_bytes,
                                               history_bytes=measured["history_bytes"], sealed=state["sealed"],
                                               entrypoint=state.get("entrypoint", False)))
        selected = owner.get("capacity_objects", [name for name in owner["files"] if capacity.OBJECT.fullmatch(name)])
        if len(selected) != len(set(selected)):
            raise ContractError("Duplicate capacity object in output ownership")
        for name in selected:
            if capacity.OBJECT.fullmatch(name) is None or name not in owner["files"]:
                raise ContractError("Invalid capacity object in output ownership")
            meta = owner["files"][name]
            artifact = capacity.Artifact(logical, name, meta["sha256"], meta["bytes"])
            stored.append(capacity.Placement(artifact, repo["id"]))
    return Inventory(identity, topics, tuple(partitions), tuple(stored))
