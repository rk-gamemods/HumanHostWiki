"""Read committed wiki ownership and measure reachable Git objects for allocation."""

from dataclasses import dataclass
import json
import subprocess

from . import capacity, publication, release
from .storage import ContractError, git, within


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
    revisions = subprocess.Popen(["git", "-C", str(path), "rev-list", "--objects", "--no-object-names", *refs, "--"],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    objects = None
    try:
        objects = subprocess.Popen(["git", "-C", str(path), "cat-file", "--batch-check=%(objecttype) %(objectsize)"],
                                   stdin=revisions.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
        object_error = objects.stderr.read().decode(errors="replace")
        revision_error = revisions.stderr.read().decode(errors="replace")
        object_exit, revision_exit = objects.wait(), revisions.wait()
        if object_exit or revision_exit:
            raise ContractError("Cannot measure Git history: " + (revision_error or object_error).strip()[:1000])
        return {"history_bytes": total, "objects": count, "blobs": blobs, "largest_blob_bytes": largest}
    finally:
        for process in (objects, revisions):
            if process is None:
                continue
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()


def read(root, project):
    """Read the current logical repositories as the initial allocation baseline.

    Caller holds the workspace lock while preparing an allocation from this state.
    Allocated partitions will be read from the release's physical registry when
    the release integration is added. Refuse that schema here until it is owned.
    """
    identity = json.loads((root / "releases/latest.json").read_text(encoding="utf-8"))["release_id"]
    manifest = release.read(root, identity)
    topics = tuple(capacity.Topic(repo["id"], repo["github_name"]) for repo in project["repositories"])
    if set(manifest["repositories"]) != {topic.id for topic in topics}:
        raise ContractError("Capacity inventory requires the initial logical repository layout")
    release.verify(root, manifest)
    published = publication.published(root)
    partitions, stored = [], []
    for topic in topics:
        record = manifest["repositories"][topic.id]
        if record["github_name"] != topic.github_name or record["path"] != "repositories/" + topic.id:
            raise ContractError("Released repository differs from the configured logical topic")
        path = within(root, record["path"])
        refs = [record["commit"]]
        if published and topic.id in published["repositories"]:
            prior = published["repositories"][topic.id]
            if prior["name"] != topic.github_name:
                raise ContractError("Published repository differs from capacity inventory")
            refs.append(prior["pages"])
        measured = history_size(path, refs)
        partitions.append(capacity.partition(topic, 0, site_bytes=record["site_bytes"],
                                               history_bytes=measured["history_bytes"]))
        owner = json.loads(git(path, "cat-file", "blob", record["commit"] + ":" + release.OWNER_FILE))
        for name, meta in owner["files"].items():
            if capacity.OBJECT.fullmatch(name):
                artifact = capacity.Artifact(topic.id, name, meta["sha256"], meta["bytes"])
                stored.append(capacity.Placement(artifact, topic.id))
    return Inventory(identity, topics, tuple(partitions), tuple(stored))
