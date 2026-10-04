"""Allocate reader objects in dependency order without writing destination files.

The release transaction owns materialization, final Git measurements and promotion.
This module reads a verified candidate and retains only metadata plus the small
transformed indexes/configurations. Unchanged data packs are never copied here.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re

from . import capacity, capture_catalog, reader, release_content, shard_index
from .storage import ContractError, digest, json_bytes, within


@dataclass(frozen=True)
class Payload:
    artifact: capacity.Artifact
    source: Path | None = None
    data: bytes | None = None

    def read(self):
        data = self.source.read_bytes() if self.source is not None else self.data
        if data is None or len(data) != self.artifact.bytes or digest(data) != self.artifact.sha256:
            raise ContractError(f"Projected source changed before release write: {self.artifact.key}")
        return data


@dataclass(frozen=True)
class Projection:
    candidate_id: str
    release_id: str
    partitions: tuple[capacity.Partition, ...]
    created: tuple[str, ...]
    placements: tuple[capacity.Placement, ...]
    reused: tuple[str, ...]
    phase_ids: tuple[str, ...]
    payloads: dict[str, Payload]
    configurations: dict[str, dict]
    entrypoints: dict[str, str]

    def writes(self):
        """Yield one verified new payload at a time; never read reused pack bytes."""
        reused = set(self.reused)
        for placement in self.placements:
            if placement.artifact.key not in reused:
                yield placement, self.payloads[placement.artifact.key].read()


def classify_reader_path(topic, relative):
    if re.fullmatch(r"data/[0-9a-f]{64}\.json", relative):
        return "leaf"
    if topic == "hub" and re.fullmatch(r"fonts/[0-9a-f]{64}/[A-Za-z0-9-]+\.(?:woff2|css|txt)", relative):
        return "leaf"
    if relative in {"reader.js", "reader.css"}:
        return "runtime"
    if re.fullmatch(r"snapshots/build-[0-9]+-[0-9a-f]{12}\.json", relative):
        return "snapshot"
    if relative == "reader.json":
        return "configuration"
    if (relative in {"index.html", "404.html", ".nojekyll"} or
            re.fullmatch(r"groups/[a-z][a-z0-9-]*/index\.html", relative) or
            (topic == "hub" and re.fullmatch(r"reference/guides/[a-z][a-z0-9-]*\.md", relative)) or
            re.fullmatch(r"reference/[a-z][a-z0-9-]*/[0-9]{4,}\.md", relative)):
        return "mutable"
    raise ContractError(f"Unexpected reader output for capacity projection: {topic}/{relative}")


def prepare_candidate(candidate, release_id, github_owner, entrypoints):
    if capacity.SHA.fullmatch(release_id) is None or re.fullmatch(r"[A-Za-z0-9-]+", github_owner) is None:
        raise ContractError("Invalid release identity or publication namespace")
    candidate = Path(candidate)
    manifest = reader.verify(candidate)
    repositories = manifest["inputs"]["project"]["repositories"]
    topics = tuple(capacity.Topic(repo["id"], repo["github_name"]) for repo in repositories)
    owners = {topic.id: topic for topic in topics}
    bases = {topic.id: f"https://{github_owner}.github.io/{topic.github_name}/" for topic in topics}
    if manifest["inputs"]["bases"] != bases:
        raise ContractError("Candidate routes differ from the capacity publication namespace")
    entrypoints = entrypoints or bases
    if set(entrypoints) != set(bases):
        raise ContractError("Entrypoint coverage differs from logical topics")
    return candidate, manifest, topics, owners, bases, entrypoints

def add_payload(payloads, topic, name, *, source=None, data=None, metadata=None):
    sha, size = (metadata["sha256"], metadata["bytes"]) if metadata else (digest(data), len(data))
    artifact = capacity.Artifact(topic, name, sha, size)
    value = Payload(artifact, source, data)
    if artifact.key in payloads and payloads[artifact.key].artifact != artifact:
        raise ContractError("Conflicting projected object")
    payloads[artifact.key] = value
    return artifact

def located_reference(located, by_partition, github_owner, topic, name, sha, size):
    placement = located.get(topic + "/site/" + name)
    if placement is None or (placement.artifact.sha256, placement.artifact.bytes) != (sha, size):
        raise ContractError(f"Snapshot dependency differs from allocated object: {topic}/{name}")
    if placement.partition == topic:
        return name
    part = by_partition[placement.partition]
    return f"https://{github_owner}.github.io/{part.github_name}/{name}"

def project_leaves(candidate, manifest, owners, add):
    # Read leaf sizes/hashes from the verified candidate. Keep their paths, not
    # their bytes, while placing dependencies and regenerating parent hashes.
    leaves, snapshots, configs, runtimes = [], [], {}, {topic: {} for topic in owners}
    for name, metadata in sorted(manifest["files"].items()):
        topic, relative = name.split("/", 1)
        if topic not in owners:
            raise ContractError("Reader file belongs to an unconfigured topic")
        source = within(candidate, name)
        kind = classify_reader_path(topic, relative)
        if kind == "leaf":
            leaves.append(add(topic, "site/" + relative, source=source, metadata=metadata))
        elif kind == "runtime":
            target = f"runtime/{metadata['sha256']}/{relative}"
            leaves.append(add(topic, "site/" + target, source=source, metadata=metadata))
            runtimes[topic][source.suffix[1:]] = (target, metadata)
        elif kind == "snapshot":
            snapshots.append((topic, source, metadata))
        elif kind == "configuration":
            configs[topic] = (source, metadata)
        # Mutable shells/reference are owned by the release writer.
    if set(configs) != set(owners):
        raise ContractError("Reader configuration coverage differs from logical topics")
    return leaves, snapshots, configs, runtimes

def verified_metadata(source, metadata):
    data = source.read_bytes()
    if (digest(data), len(data)) != (metadata["sha256"], metadata["bytes"]):
        raise ContractError("Reader metadata changed during capacity projection")
    return data

def project_fonts(manifest, configs, bases, located, by_partition, github_owner):
    fonts = json.loads(verified_metadata(*configs["hub"])).get("fonts")
    projected_fonts = None
    font_leaves = {name.removeprefix("hub/"): meta for name, meta in manifest["files"].items()
                   if name.startswith("hub/fonts/")}
    if fonts:
        folder = "fonts/" + digest(json_bytes(fonts["files"])) + "/"
        expected = {folder + name: meta for name, meta in fonts["files"].items()}
        if (fonts["base"] != bases["hub"] + folder or expected != font_leaves or
                "fonts.css" not in fonts["files"]):
            raise ContractError("Font set differs from candidate content")
        locations = {located["hub/site/" + name].partition for name in expected}
        if len(locations) != 1:
            raise ContractError("Font set spans multiple partitions")
        part = by_partition[locations.pop()]
        projected_fonts = {**fonts, "base": f"https://{github_owner}.github.io/{part.github_name}/{folder}"}
    elif font_leaves:
        raise ContractError("Font files have no configuration")
    for source, metadata in configs.values():
        if json.loads(verified_metadata(source, metadata)).get("fonts") != fonts:
            raise ContractError("Topics disagree on the shared font set")

    return projected_fonts

def project_snapshots(snapshots, reference):
    snapshot_data = {}
    for topic, source, metadata in snapshots:
        snapshot_data[(topic, source.stem)] = release_content.snapshot(verified_metadata(source, metadata),
                                            lambda name, sha, size: reference(topic, name, sha, size))

    return snapshot_data

def project_metadata_objects(batch, add, allocate, reference):
    artifacts = [add(topic, "site/objects/" + digest(data) + ".json", data=data) for topic, data in batch]
    allocate(artifacts)
    return [{"path": reference(item.topic, item.path.removeprefix("site/"), item.sha256, item.bytes),
             "sha256": item.sha256, "bytes": item.bytes} for item in artifacts]

def project_directories(configs, batch, emit):
    for topic in {topic for topic, _ in batch}:
        source, metadata = configs[topic]
        if "shard-directories-v1" not in json.loads(verified_metadata(source, metadata)).get("features", []):
            raise ContractError("Reader runtime does not support shard directories; regenerate the candidate")
    return emit(batch)

def project_articles(configs, reference):
    article_data = {}
    for topic, (source, metadata) in configs.items():
        view = json.loads(verified_metadata(source, metadata)).get("external_articles")
        if view:
            article_data[(topic, "external")] = release_content.indexed(json_bytes(view),
                lambda name, sha, size, topic=topic: reference(topic, name, sha, size), ("entries",))
    return article_data

def project_indexes(snapshot_data, article_data, owners, add):
    indexes, snapshot_objects = [], {topic: {} for topic in owners}
    article_objects = {}
    for (topic, _), data in article_data.items():
        name = "objects/" + digest(data) + ".json"
        indexes.append(add(topic, "site/" + name, data=data))
        article_objects[topic] = (name, digest(data), len(data))
    for (topic, snapshot), data in snapshot_data.items():
        name = "objects/" + digest(data) + ".json"
        indexes.append(add(topic, "site/" + name, data=data))
        snapshot_objects[topic][snapshot] = (name, digest(data), len(data))
    return indexes, snapshot_objects, article_objects

def project_configurations(configs, snapshot_objects, article_objects, runtimes, reference, release_id, projected_fonts, entrypoints, bases):
    release_data = {}
    for topic, (source, metadata) in sorted(configs.items()):
        resolved = {snapshot: {"path": reference(topic, name, sha, size), "sha256": sha, "bytes": size}
                    for snapshot, (name, sha, size) in snapshot_objects[topic].items()}
        runtime = {extension: reference(topic, name, meta["sha256"], meta["bytes"])
                   for extension, (name, meta) in runtimes[topic].items()}
        external = None
        if topic in article_objects:
            name, sha, size = article_objects[topic]
            external = {"path": reference(topic, name, sha, size), "sha256": sha, "bytes": size}
        release_data[topic] = release_content.configuration(verified_metadata(source, metadata), release_id, resolved, runtime, external)
        if projected_fonts:
            value = json.loads(release_data[topic])
            value["fonts"] = projected_fonts
            release_data[topic] = json_bytes(value)
        if entrypoints != bases:
            value = json.loads(release_data[topic])
            if "entrypoint-rollover-v1" not in value.get("features", []):
                raise ContractError("Reader runtime does not support entrypoint rollover; regenerate the candidate")
            value["entrypoints"] = entrypoints
            release_data[topic] = json_bytes(value)
    return release_data

def release_references(releases, reference):
    configurations = {}
    for artifact in releases:
        configurations[artifact.topic] = {"path": reference(artifact.topic, artifact.path.removeprefix("site/"),
                                                            artifact.sha256, artifact.bytes),
                                          "sha256": artifact.sha256, "bytes": artifact.bytes}
    return configurations


def build(candidate, release_id, github_owner, partitions, stored=(), budgets=None, *, entrypoints=None):
    """Plan leaves, then indexes, then release configurations. No writes or Git calls.

    Caller holds the workspace writer lock and provides a committed inventory.
    This result is preparation only: it neither provisions partitions nor changes
    live routes. Stable entrypoint rollover is owned by release coordination.
    """
    candidate, manifest, topics, owners, bases, entrypoints = prepare_candidate(candidate, release_id, github_owner, entrypoints)
    physical, prior = tuple(partitions), tuple(stored)
    # Validate duplicates before lookup maps can conceal conflicting ownership.
    capacity.allocate(topics, physical, prior, (), budgets)
    located = {value.artifact.key: value for value in prior}
    committed, wanted = set(located), set()
    payloads, created, reused, phases, by_partition = {}, [], set(), [], {}

    def add(topic, name, *, source=None, data=None, metadata=None):
        return add_payload(payloads, topic, name, source=source, data=data, metadata=metadata)

    def allocate(objects):
        nonlocal physical, by_partition
        plan = capacity.allocate(topics, physical, located.values(), objects, budgets)
        physical = plan.partitions
        phases.append(plan.inputs_sha256)
        created.extend(plan.created)
        # A later level may request a directory already planned by this run.
        # It still needs one write unless it existed in the committed inventory.
        reused.update(key for key in plan.reused if key in committed)
        for placement in plan.placements:
            located[placement.artifact.key] = placement
            wanted.add(placement.artifact.key)
        by_partition = {part.id: part for part in physical}

    def reference(topic, name, sha, size):
        return located_reference(located, by_partition, github_owner, topic, name, sha, size)

    leaves, snapshots, configs, runtimes = project_leaves(candidate, manifest, owners, add)
    allocate(leaves)
    fonts = project_fonts(manifest, configs, bases, located, by_partition, github_owner)

    def metadata_objects(batch):
        return project_metadata_objects(batch, add, allocate, reference)

    def directories(batch):
        return project_directories(configs, batch, metadata_objects)

    snapshot_data = project_snapshots(snapshots, reference)
    snapshot_data = shard_index.compact(snapshot_data, (budgets or capacity.Budgets()).file_bytes, directories)
    article_data = project_articles(configs, reference)
    if article_data:
        article_data = shard_index.compact(article_data, (budgets or capacity.Budgets()).file_bytes, directories, fields=("entries",))
    indexes, snapshot_objects, article_objects = project_indexes(snapshot_data, article_data, owners, add)
    allocate(indexes)
    release_data = project_configurations(configs, snapshot_objects, article_objects, runtimes, reference,
                                          release_id, fonts, entrypoints, bases)
    release_data = capture_catalog.compact(release_data, (budgets or capacity.Budgets()).file_bytes, metadata_objects)
    releases = [add(topic, f"site/releases/{release_id}.json", data=data) for topic, data in sorted(release_data.items())]
    allocate(releases)
    configurations = release_references(releases, reference)
    return Projection(manifest["candidate_id"], release_id, physical, tuple(created),
                      tuple(located[key] for key in sorted(wanted)), tuple(sorted(reused)),
                      tuple(phases), payloads, configurations, entrypoints)
