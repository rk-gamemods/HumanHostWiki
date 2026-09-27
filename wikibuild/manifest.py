"""Single authority for repository ownership, topic routes and pipeline order."""

import json
import re
from urllib.parse import urlparse

from .storage import ContractError, within
from .physical import budgets

SLUG = re.compile(r"^[a-z][a-z0-9-]*$")


def require(condition, message):
    if not condition:
        raise ContractError(message)


def load(root):
    manifest = json.loads((root / "project.json").read_text(encoding="utf-8"))
    validate(root, manifest)
    return manifest


def validate(root, manifest):
    require(manifest.get("schema_version") == 1, "Unsupported project schema")
    require(manifest.get("language") == "en", "The accepted publishing language is English")
    budgets(manifest)
    availability = manifest.get("availability", {})
    require(type(availability) is dict and not set(availability) - {"enabled", "cache_seconds", "retry_seconds"},
            "Unknown availability configuration")
    require(type(availability.get("enabled", False)) is bool, "Availability enabled must be boolean")
    for key, default in (("cache_seconds", 3600), ("retry_seconds", 60)):
        require(type(availability.get(key, default)) is int and 1 <= availability.get(key, default) <= 86400,
                "Availability cache and retry seconds must be between 1 and 86400")
    publication = manifest["publication"]
    require(all(publication.get(key) == value for key, value in {
        "visibility": "public", "monetized": False, "advertising": False, "host": "github-pages"}.items()),
            "Publication contract changed; update the ADR and implementation together")
    require(isinstance(publication.get("enabled", False), bool), "Publication enabled must be boolean")
    require(type(publication.get("workers", 4)) is int and 1 <= publication.get("workers", 4) <= 8,
            "Publication workers must be between 1 and 8")
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", manifest["github_owner"])), "Invalid GitHub namespace")
    require(manifest["source"]["steam_app_id"] == "2393970", "Wrong source game")
    require(manifest["source"]["catalog_schema"] == 1, "Unsupported input catalog schema")
    repositories = manifest["repositories"]
    require(bool(repositories), "Repository registry is empty")
    identifiers, paths, names, owners = set(), set(), set(), {}
    for repo in repositories:
        identity = repo["id"]
        require(bool(SLUG.fullmatch(identity)), f"Invalid repository ID: {identity}")
        require(identity not in identifiers, f"Duplicate repository ID: {identity}")
        identifiers.add(identity)
        require(repo["path"] == f"repositories/{identity}", f"Unexpected checkout path: {identity}")
        path = within(root, repo["path"])
        require(str(path).casefold() not in paths, f"Overlapping repository path: {identity}")
        paths.add(str(path).casefold())
        name = repo["github_name"]
        require(bool(re.fullmatch(r"[A-Za-z0-9-]+", name)), f"Invalid GitHub name: {name}")
        require(name.casefold() not in names, f"Duplicate GitHub name: {name}")
        names.add(name.casefold())
        require(repo["role"] in {"hub", "topic"}, f"Unknown repository role: {identity}")
        require(bool(repo["title"].strip()) and bool(repo["coverage"].strip()), f"Missing description: {identity}")
        require(bool(repo["owns"]), f"Missing ownership: {identity}")
        for kind in repo["owns"]:
            require(bool(SLUG.fullmatch(kind)), f"Invalid entity kind: {kind}")
            require(kind not in owners, f"Entity kind has multiple owners: {kind}")
            owners[kind] = identity
    hubs = [r["id"] for r in repositories if r["role"] == "hub"]
    require(hubs == ["hub"], "Exactly one navigation hub named hub is required")
    require(owners.get("unclassified") == "technical-reference", "Unclassified assets need an explicit owner")
    edges = set()
    for edge in manifest["relationships"]:
        require(edge["from"] in identifiers and edge["to"] in identifiers, "Relationship target is missing")
        require(bool(SLUG.fullmatch(edge["kind"])), "Invalid relationship kind")
        key = (edge["from"], edge["to"], edge["kind"])
        require(key not in edges, "Duplicate topic relationship")
        edges.add(key)
    for link in manifest["official_links"]:
        parsed = urlparse(link["url"])
        require(parsed.scheme == "https" and bool(parsed.netloc), "Official links must be absolute HTTPS URLs")
    stage_order(manifest)
    return owners


def stage_order(manifest):
    stages = manifest["pipeline"]
    by_id = {stage["id"]: stage for stage in stages}
    require(len(stages) == len(by_id), "Duplicate pipeline stage")
    for stage in stages:
        require(bool(SLUG.fullmatch(stage["id"])), "Invalid stage ID")
        require(stage["status"] in {"implemented", "partial", "planned", "external-existing"}, "Invalid stage status")
        require(len(stage["depends_on"]) == len(set(stage["depends_on"])), "Duplicate stage dependency")
        require(all(dep in by_id for dep in stage["depends_on"]), "Unknown pipeline dependency")
    ordered, active = [], set()

    def visit(identity):
        require(identity not in active, f"Pipeline cycle at {identity}")
        if identity in ordered:
            return
        active.add(identity)
        for parent in by_id[identity]["depends_on"]:
            visit(parent)
        active.remove(identity)
        ordered.append(identity)

    for stage in stages:
        visit(stage["id"])
    return ordered


def repository_map(manifest):
    lines = ["# Repository and pipeline map", "", "Generated from `project.json` by `py -3 wiki.py map`. Do not edit this file.",
             "", "GitHub names below are configured destinations. Publication receipts record verified remote state.", "",
             "This map shows logical topics. Release manifests record additional physical storage repositories;",
             "the [capacity contract](CAPACITY.md) defines their ownership, allocation and recovery.", "",
             "| Repository | Local checkout | Intended GitHub name | Content ownership |",
             "| --- | --- | --- | --- |"]
    for repo in manifest["repositories"]:
        lines.append(f"| {repo['title']} | `{repo['path']}` | `{repo['github_name']}` | {repo['coverage']} |")
    lines += ["", "## Navigation and topic relationships", "", "```mermaid", "flowchart LR", '  hub["Start here and curated guides"]']
    for repo in manifest["repositories"]:
        if repo["role"] == "topic":
            key = repo["id"].replace("-", "_")
            lines += [f'  {key}["{repo["title"]}"]', f"  hub --> {key}"]
    for edge in manifest["relationships"]:
        lines.append(f"  {edge['from'].replace('-', '_')} -. {edge['kind']} .-> {edge['to'].replace('-', '_')}")
    lines += ["```", "", "Solid edges are entry navigation; dotted edges describe representative semantic links.",
              "They are not build dependencies. Semantic cycles and backlinks are expected.", "", "## Build dependencies", "", "```mermaid", "flowchart LR"]
    for stage in manifest["pipeline"]:
        lines.append(f'  {stage["id"]}["{stage["id"]}: {stage["status"]}"]')
        for dependency in stage["depends_on"]:
            lines.append(f"  {dependency} --> {stage['id']}")
    lines += ["```", "", "| Stage | Owner | Implementation |", "| --- | --- | --- |"]
    for stage in manifest["pipeline"]:
        lines.append(f"| {stage['id']} | {stage['owner']} | {stage['status']} |")
    lines += ["", "The navigation preview is an independent foundation build, not the publish stage above.", ""]
    return "\n".join(lines).encode("utf-8")
