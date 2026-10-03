"""Select mutable topic fronts and seal full generations without moving history."""

from dataclasses import replace
from pathlib import Path

from . import capacity, physical
from .storage import ContractError, json_bytes


def active(partitions):
    result = {}
    owners = {part.topic for part in partitions}
    for part in partitions:
        if not part.sealed and (part.ordinal == 0 or part.entrypoint):
            if part.topic in result:
                raise ContractError("Multiple active entrypoints for a logical topic")
            result[part.topic] = part.id
    if set(result) != owners:
        raise ContractError("Logical topic has no active entrypoint")
    return result


def rollover(partitions, topics, requested):
    """Pure proposal; the release journal owns installation and publication."""
    current = active(partitions)
    owners = {topic.id: topic for topic in topics}
    if not set(requested) <= set(current):
        raise ContractError("Cannot roll an unknown entrypoint")
    retiring = {current[topic] for topic in requested}
    result = [replace(part, sealed=True) if part.id in retiring else part
              for part in partitions]
    identities = {part.id for part in result}
    names = {part.github_name.casefold() for part in result}
    for topic in sorted(requested):
        ordinal = max(part.ordinal for part in result if part.topic == topic) + 1
        candidate = capacity.partition(owners[topic], ordinal, entrypoint=True)
        while candidate.id in identities or candidate.github_name.casefold() in names:
            ordinal += 1
            candidate = capacity.partition(owners[topic], ordinal, entrypoint=True)
        result.append(candidate)
        identities.add(candidate.id)
        names.add(candidate.github_name.casefold())
    return tuple(result)


def retire(writer, project, topic, target, release_id, candidate, *, fonts_base=None):
    hub = next(repo for repo in project["repositories"] if repo["id"] == "hub")
    writer.add("site/reader.json", json_bytes({"schema_version": 1, "kind": "wiki-entrypoint-successor",
               "topic": topic, "hub": physical.base(project, hub), "target": target,
               "since_release": release_id}))
    writer.add("site/reader.js", (Path(__file__).parent / "release_bootstrap.js").read_bytes().replace(b"\r\n", b"\n"))
    # A first release can fill the original repository with immutable objects
    # before it ever hosts a front. Its stable URL still needs a bootstrap shell.
    for name in ("index.html", "404.html", ".nojekyll"):
        if "site/" + name not in writer.previous:
            data = (Path(candidate) / topic / name).read_bytes()
            if fonts_base and name.endswith(".html"):
                from html import escape
                import json
                original = json.loads((Path(candidate) / topic / "reader.json").read_bytes())["fonts"]["base"]
                data = data.replace(escape(original, quote=True).encode(), escape(fonts_base, quote=True).encode())
            writer.add("site/" + name, data)
    if "site/reader.css" not in writer.previous:
        writer.add("site/reader.css", b"/* The release loader selects the versioned stylesheet. */\n")


def publication_groups(repositories, active_fronts, previous_fronts):
    """Publish dependencies before successor records; the hub selection is last."""
    control = previous_fronts.get("hub", active_fronts["hub"])
    retiring = {previous_fronts[t] for t in previous_fronts if previous_fronts[t] != active_fronts[t]}
    groups = [[], [], [], []]
    for repo in repositories:
        identity, topic = repo["id"], repo.get("logical_topic", repo["id"])
        if identity == control:
            continue
        if topic == "hub" and identity == active_fronts["hub"]:
            rank = 3
        elif identity in retiring:
            rank = 2
        elif repo["role"] == "partition" or identity != active_fronts[topic]:
            rank = 0
        else:
            rank = 1
        groups[rank].append(identity)
    return control, groups
