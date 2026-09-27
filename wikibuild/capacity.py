"""Pure placement of immutable wiki objects into bounded physical repositories.

No files or remotes are changed here. Release preparation supplies verified sizes
and prior locations, then journals and validates the proposed physical writes.
"""

from dataclasses import asdict, dataclass, replace
import hashlib
import re

from .storage import ContractError, digest, json_bytes

MIB = 1024 * 1024
SLUG = re.compile(r"[a-z][a-z0-9-]*")
SHA = re.compile(r"[0-9a-f]{64}")
OBJECT = re.compile(
    r"(?:site/(?:data|objects)/(?P<json>[0-9a-f]{64})\.json|"
    r"site/runtime/(?P<runtime>[0-9a-f]{64})/reader\.(?:js|css)|"
    r"site/releases/[0-9a-f]{64}\.json|"
    r"reference/objects/(?P<markdown>[0-9a-f]{64})\.md)")


@dataclass(frozen=True)
class Budgets:
    file_bytes: int = 32 * MIB
    site_bytes: int = 800 * MIB
    history_bytes: int = 800 * MIB
    site_reserve_bytes: int = 16 * MIB
    history_reserve_bytes: int = 16 * MIB

    def validate(self):
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ContractError("Capacity budgets must be positive integer bytes")
        if self.file_bytes >= 50 * MIB or self.site_bytes >= 1_000_000_000:
            raise ContractError("Capacity budgets must retain headroom below the checked GitHub limits")
        if self.file_bytes > min(self.site_bytes - self.site_reserve_bytes,
                                 self.history_bytes - self.history_reserve_bytes):
            raise ContractError("Capacity reserves leave too little room for a bounded file")


@dataclass(frozen=True)
class Topic:
    id: str
    github_name: str


@dataclass(frozen=True)
class Partition:
    id: str
    topic: str
    ordinal: int
    github_name: str
    site_bytes: int
    history_bytes: int
    sealed: bool = False
    entrypoint: bool = False

    @property
    def path(self):
        return "repositories/" + self.id


@dataclass(frozen=True)
class Artifact:
    topic: str
    path: str
    sha256: str
    bytes: int

    @property
    def key(self):
        return self.topic + "/" + self.path


@dataclass(frozen=True)
class Placement:
    artifact: Artifact
    partition: str


@dataclass(frozen=True)
class Plan:
    inputs_sha256: str
    partitions: tuple[Partition, ...]
    created: tuple[str, ...]
    placements: tuple[Placement, ...]
    reused: tuple[str, ...]

    def record(self):
        payload = {"schema_version": 1, **asdict(self)}
        return {"plan_id": digest(json_bytes(payload)), **payload}


def partition(topic, ordinal, *, site_bytes=0, history_bytes=0, sealed=False, entrypoint=False):
    if type(ordinal) is not int or ordinal < 0:
        raise ContractError("Partition ordinal must be a nonnegative integer")
    suffix = f"-part-{ordinal:04d}" if ordinal else ""
    name = topic.github_name + (f"-Part-{ordinal:04d}" if ordinal else "")
    if len(name) > 100:
        raise ContractError("Configured repository name leaves no room for a partition suffix")
    return Partition(topic.id + suffix, topic.id, ordinal, name, site_bytes, history_bytes, sealed, entrypoint)


def artifact_check(value, topics):
    match = OBJECT.fullmatch(value.path)
    if value.topic not in topics or match is None or SHA.fullmatch(value.sha256) is None:
        raise ContractError(f"Invalid immutable capacity object: {value.key}")
    if type(value.bytes) is not int or value.bytes < 0:
        raise ContractError(f"Invalid capacity object size: {value.key}")
    content_hash = next((value for value in match.groupdict().values() if value), None)
    if content_hash is not None and content_hash != value.sha256:
        raise ContractError(f"Content-addressed path differs from object hash: {value.key}")


def allocate(topics, partitions, stored, requested, budgets=None):
    """Preserve prior locations; first-fit decreasing places only previously unseen files.

    History is measured in uncompressed reachable Git object bytes. New blob bytes
    are charged once per partition. Reserved capacity covers control files, tree
    and commit growth; the release writer must check final prepared Git sizes.
    Iterables contain metadata only and are consumed once. Inputs are not mutated.
    """
    budgets = budgets or Budgets()
    budgets.validate()
    topic_list = sorted(topics, key=lambda value: value.id)
    owners = {topic.id: topic for topic in topic_list}
    if not owners or len(owners) != len(topic_list):
        raise ContractError("Capacity needs unique logical topics")
    names = set()
    for topic in topic_list:
        if (SLUG.fullmatch(topic.id) is None or
                re.fullmatch(r"[A-Za-z0-9-]{1,100}", topic.github_name) is None or
                topic.github_name.casefold() in names):
            raise ContractError("Invalid or overlapping capacity topic identity")
        names.add(topic.github_name.casefold())

    original = sorted(partitions, key=lambda value: (value.topic, value.ordinal))
    physical, groups, blob_sizes = {}, {topic: [] for topic in owners}, {}
    names = set()
    for item in original:
        if item.topic not in owners or item.id in physical:
            raise ContractError("Partition has unknown or duplicate ownership")
        expected = partition(owners[item.topic], item.ordinal, site_bytes=item.site_bytes,
                             history_bytes=item.history_bytes, sealed=item.sealed, entrypoint=item.entrypoint)
        if (item != expected or item.github_name.casefold() in names or
                type(item.sealed) is not bool or type(item.entrypoint) is not bool or
                (item.ordinal == 0 and item.entrypoint) or any(type(size) is not int or size < 0
                                                    for size in (item.site_bytes, item.history_bytes))):
            raise ContractError(f"Invalid physical partition: {item.id}")
        physical[item.id] = item
        groups[item.topic].append(item.id)
        names.add(item.github_name.casefold())
        blob_sizes[item.id] = {}
    if any(not ids or physical[ids[0]].ordinal != 0 for ids in groups.values()):
        raise ContractError("Every topic needs its original physical repository")

    existing, site_known, hashes = {}, dict.fromkeys(physical, 0), {}

    def check_hash(artifact):
        artifact_check(artifact, owners)
        if artifact.sha256 in hashes and hashes[artifact.sha256] != artifact.bytes:
            raise ContractError("One object hash has inconsistent byte sizes")
        hashes[artifact.sha256] = artifact.bytes

    for item in stored:
        check_hash(item.artifact)
        owner = physical.get(item.partition)
        if owner is None or owner.topic != item.artifact.topic:
            raise ContractError("Stored object is outside its logical topic")
        key = item.artifact.key
        if key in existing:
            raise ContractError(f"Stored object has duplicate physical ownership: {key}")
        existing[key] = item
        blob_sizes[item.partition][item.artifact.sha256] = item.artifact.bytes
        if item.artifact.path.startswith("site/"):
            site_known[item.partition] += item.artifact.bytes
    for item in original:
        if item.site_bytes < site_known[item.id] or item.history_bytes < sum(blob_sizes[item.id].values()):
            raise ContractError(f"Measured capacity is smaller than stored objects: {item.id}")

    wanted = {}
    for value in requested:
        check_hash(value)
        if value.key in wanted and wanted[value.key] != value:
            raise ContractError(f"Conflicting requested capacity object: {value.key}")
        if value.key in existing and existing[value.key].artifact != value:
            raise ContractError(f"Immutable capacity object changed: {value.key}")
        if value.key not in existing and value.bytes > budgets.file_bytes:
            raise ContractError(f"Split generated object before allocation: {value.key} ({value.bytes} bytes)")
        wanted[value.key] = value
    # Hash one small metadata record at a time, avoiding a second complete copy
    # of the historical file inventory and its serialized JSON.
    hasher = hashlib.sha256()
    for category, values in (("budgets", (budgets,)), ("topics", topic_list), ("partitions", original),
                             ("stored", (existing[key] for key in sorted(existing))),
                             ("requested", (wanted[key] for key in sorted(wanted)))):
        hasher.update(category.encode() + b"\0")
        for value in values:
            hasher.update(json_bytes(asdict(value)))
        hasher.update(b"\0")
    input_hash = hasher.hexdigest()
    chosen = {key: existing[key] for key in wanted.keys() & existing.keys()}
    reused = tuple(sorted(chosen))
    created = []
    for value in sorted((value for key, value in wanted.items() if key not in existing),
                        key=lambda value: (value.topic, -value.bytes, value.path)):
        site_growth = value.bytes if value.path.startswith("site/") else 0
        selected = None
        for identity in groups[value.topic]:
            item = physical[identity]
            history_growth = 0 if value.sha256 in blob_sizes[identity] else value.bytes
            if (not item.sealed and not item.entrypoint and item.site_bytes + site_growth <= budgets.site_bytes - budgets.site_reserve_bytes
                    and item.history_bytes + history_growth <= budgets.history_bytes - budgets.history_reserve_bytes):
                selected = item
                break
        if selected is None:
            ordinal = physical[groups[value.topic][-1]].ordinal + 1
            selected = partition(owners[value.topic], ordinal)
            while selected.id in physical or selected.github_name.casefold() in names:
                ordinal += 1
                selected = partition(owners[value.topic], ordinal)
            physical[selected.id] = selected
            groups[value.topic].append(selected.id)
            names.add(selected.github_name.casefold())
            blob_sizes[selected.id] = {}
            created.append(selected.id)
        history_growth = 0 if value.sha256 in blob_sizes[selected.id] else value.bytes
        physical[selected.id] = replace(selected, site_bytes=selected.site_bytes + site_growth,
                                        history_bytes=selected.history_bytes + history_growth)
        blob_sizes[selected.id][value.sha256] = value.bytes
        chosen[value.key] = Placement(value, selected.id)
    return Plan(input_hash, tuple(sorted(physical.values(), key=lambda value: (value.topic, value.ordinal))),
                tuple(created), tuple(chosen[key] for key in sorted(chosen)), reused)
