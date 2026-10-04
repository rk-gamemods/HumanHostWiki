"""Transform reader metadata after its immutable dependencies have locations."""

import json
from pathlib import Path
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
        if kind in {"cards", "player", "guides"} and kind not in value:
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
    # Guides are ordered metadata rows, not range directories consumed by keyed().
    return indexed(data, resolve, (*SHARD_KINDS, "guides"))


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


def project_topic(candidate, repo, writer, projection):
    """Write mutable entrypoints around the already located immutable objects."""
    logical = repo.get("logical_topic", repo["id"])
    topic = candidate / logical
    release_id = projection.release_id
    config_key = logical + f"/site/releases/{release_id}.json"
    configuration = projection.payloads[config_key].read()
    fonts = json.loads(configuration).get("fonts")
    config_ref = projection.configurations[logical]
    if config_ref["path"].startswith("https://") or repo["id"] != logical:
        if not config_ref["path"].startswith("https://"):
            base = json.loads((topic / "reader.json").read_bytes())["topics"]
            config_ref = {**config_ref, "path": next(item["base"] for item in base if item["id"] == logical) + config_ref["path"]}
        configuration = json_bytes({"schema_version": 1, "kind": "wiki-release-reference",
                                    "release_id": release_id, "target": config_ref})
        writer.add(f"site/releases/{release_id}.json", configuration)
    writer.add("site/reader.json", configuration)
    reference_paths = []
    for source in sorted(topic.rglob("*")):
        if not source.is_file():
            continue
        name = source.relative_to(topic).as_posix()
        if name.startswith("reference/") and source.suffix == ".md":
            data = source.read_bytes().replace(("release=" + projection.candidate_id).encode(),
                                               ("release=" + release_id).encode())
            writer.add(name, data)
            reference_paths.append(name)
        elif name in {"index.html", "404.html", ".nojekyll"} or re.fullmatch(r"groups/[a-z][a-z0-9-]*/index\.html", name):
            data = source.read_bytes()
            # Protect the shared font URL while rewriting a rolled front's
            # own routes, including when the logical topic is the hub itself.
            if fonts and source.suffix == ".html":
                original_fonts = json.loads((topic / "reader.json").read_bytes())["fonts"]
                from html import escape
                data = data.replace(escape(original_fonts["base"], quote=True).encode(), b"__WIKI_FONT_BASE__")
            if repo["id"] != logical and source.suffix == ".html":
                from urllib.parse import urlsplit
                config = json.loads((topic / "reader.json").read_bytes())
                base = next(item["base"] for item in config["topics"] if item["id"] == logical)
                data = data.replace(urlsplit(base).path.encode(), urlsplit(projection.entrypoints[logical]).path.encode())
            if fonts and source.suffix == ".html":
                data = data.replace(b"__WIKI_FONT_BASE__", escape(fonts["base"], quote=True).encode())
            writer.add("site/" + name, data)
    writer.add("site/reader.js", (Path(__file__).parent / "release_bootstrap.js").read_bytes().replace(b"\r\n", b"\n"))
    writer.add("site/reader.css", b"/* The release loader selects the versioned stylesheet. */\n")
    links = [f"# {repo['title']} reference", "", f"Release: `{release_id}`.", "",
             "Selected extracted facts. Runtime gameplay verification is unknown unless a scoped check is shown.", ""]
    links += [f"- [{name.removeprefix('reference/')}]({name.removeprefix('reference/')})" for name in reference_paths]
    writer.add("reference/index.md", ("\n".join(links) + "\n").encode())
    if "README.md" in writer.previous:
        project_name = json.loads((topic / "reader.json").read_bytes()).get("project", "Unofficial game reference")
        writer.add("README.md", (f"# {project_name}\n\n## {repo['title']}\n\n{repo['coverage']}.\n\n"
            "An unofficial community project. Not affiliated with or endorsed by Virtual Matrix Studio.\n\n"
            "Browse the [generated reference](reference/index.md) for selected captured data; "
            "serialized facts are not runtime-verified gameplay claims.\n\n"
            f"Current prepared release: `{release_id}`. Publication is tracked separately by the hub.\n\n"
            "Generated files are recorded in `.wiki-output.json`. Put authored explanations outside "
            "the generated `site/` and `reference/` directories.\n").encode())
