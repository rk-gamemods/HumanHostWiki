"""Coordinate immutable reader releases across independently owned Git repositories."""

import json
from pathlib import Path
import re

from . import extraction, git_transaction, physical, reader, release_output, release_partitions, release_prepare, workspace
from .storage import ContractError, digest, git, json_bytes, within, write_changed

OWNER_FILE = release_output.OWNER_FILE


def immutable(path, value):
    data = json_bytes(value)
    if path.exists() and path.read_bytes() != data:
        raise ContractError(f"Release receipt differs: {path}")
    write_changed(path, data)


def contract():
    folder = Path(__file__).parent
    return {name: digest((folder / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in ("release.py", "release_prepare.py", "entrypoints.py", "release_content.py", "release_output.py", "ownership.py", "release_partitions.py",
                         "capacity.py", "capacity_inventory.py", "capacity_projection.py", "shard_index.py", "capture_catalog.py", "physical.py",
                         "git_transaction.py", "publication_git.py", "release_bootstrap.js", "workspace.py")}


def bases(project):
    return {repo["id"]: f"https://{project['github_owner']}.github.io/{repo['github_name']}/"
            for repo in project["repositories"]}


owned = release_output.owned


def preflight(root, project):
    for repo in workspace.repositories(root, project):
        state = workspace.inspect(root, repo)
        if state["state"] != "clean":
            raise ContractError(f"Release destination {repo['id']} is {state['state']}")
        path = within(root, repo["path"])
        owned(path)


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


def read(root, release_id):
    if not re.fullmatch(r"[0-9a-f]{64}", release_id):
        raise ContractError("Invalid release identity")
    value = json.loads(within(root, f"releases/{release_id}.json").read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or value.get("release_id") != release_id or digest(json_bytes(value["inputs"])) != release_id:
        raise ContractError("Release identity differs")
    if value.get("manifest_sha256") != digest(json_bytes({key: item for key, item in value.items() if key != "manifest_sha256"})):
        raise ContractError("Release manifest content differs")
    return value


def verify(root, value, *, check_checkout=True, reviewed_project=None):
    if reviewed_project is not None:
        if not check_checkout:
            raise ContractError("Reviewed successors require checkout validation")
        workspace.checkout_lock(root, reviewed_project, check=True)
    for topic, record in value["repositories"].items():
        path = within(root, record["path"])
        if git(path, "rev-parse", record["commit"] + "^{tree}") != record["tree"]:
            raise ContractError(f"Release commit tree differs: {topic}")
        if check_checkout:
            head = git(path, "rev-parse", "HEAD")
            if git(path, "status", "--porcelain=v1", "--untracked-files=all"):
                raise ContractError(f"Release checkout differs: {topic}")
            if head != record["commit"]:
                if reviewed_project is None:
                    raise ContractError(f"Release checkout differs: {topic}")
                # Only allocation for a new release accepts reviewed authored commits.
                # Current publication/reuse still requires the exact release HEAD.
                git(path, "merge-base", "--is-ancestor", record["commit"], head)
            if extraction.file_hash(path / OWNER_FILE) != record["ownership_sha256"]:
                raise ContractError(f"Release ownership receipt differs: {topic}")
            owned(path)


def resume(root, journal):
    stage = within(root, journal["stage"])
    for entry in journal.get("new_repositories", []):
        release_partitions.install(root, entry)
    for repo in physical.repositories(journal["project"], journal["result"].get("physical")):
        workspace.inspect(root, repo)
        item = journal["plans"][repo["id"]]
        git_transaction.validate(within(root, item["path"]), item["git"])
    for repo in journal["order"]:
        item = journal["plans"][repo]
        git_transaction.promote(within(root, item["path"]), stage / repo, item["git"])
    result = journal["result"]
    verify(root, result)
    immutable(within(root, f"releases/{result['release_id']}.json"), result)
    workspace.checkout_lock(root, journal["project"], allocated=journal["result"].get("physical"))
    write_changed(within(root, "releases/latest.json"), json_bytes({"release_id": result["release_id"]}))
    # Keep the journal for diagnosis. A completed pointer is safe to replay.
    write_changed(within(root, ".local/releases/pending.json"), json_bytes({"stage": journal["stage"], "complete": True}))
    return result


def run(root, project, candidate):
    """Caller holds writer_lock. Complete any prepared transaction before new work."""
    pending = within(root, ".local/releases/pending.json")
    if pending.exists():
        pointer = json.loads(pending.read_text(encoding="utf-8"))
        if not pointer["complete"]:
            data = within(root, pointer["stage"] + "/plan.json").read_bytes()
            if digest(data) != pointer["sha256"]:
                raise ContractError("Pending release journal was modified")
            journal = json.loads(data)
            resume(root, journal)
    manifest = reader.verify(Path(candidate["path"]), candidate["candidate_id"])
    templates = reader.issue_templates(root)
    if {name: digest(data) for name, data in templates.items()} != manifest["inputs"].get("issue_templates"):
        raise ContractError("Issue template inputs changed after reader build")
    inputs = {"reader": candidate["candidate_id"], "contract": contract(), "project_sha256": digest(json_bytes(project))}
    release_id = digest(json_bytes(inputs))
    existing = within(root, f"releases/{release_id}.json")
    if existing.exists():
        result = read(root, release_id)
        verify(root, result)
        latest = json.loads(within(root, "releases/latest.json").read_text())["release_id"]
        if latest != release_id:
            raise ContractError("An older release cannot rewind the current checkout")
        return result, {"reused": True}
    preflight(root, project)
    workspace.checkout_lock(root, project, check=True)
    from . import capacity_inventory, publication
    inventory = capacity_inventory.read(root, project)
    previous = publication.published(root)
    prepared, outputs = release_prepare.prepare(root, project, candidate, release_id, inventory, previous, templates)
    stage = within(root, prepared["stage"])
    if contract() != inputs["contract"]:
        raise ContractError("Release rules changed during preparation")
    reader.verify(Path(candidate["path"]), candidate["candidate_id"])
    if reader.issue_templates(root) != templates:
        raise ContractError("Issue template inputs changed during release preparation")
    result = {"schema_version": 1, "release_id": release_id, "inputs": inputs,
              "reader_candidate": candidate["candidate_id"], "versions": manifest["versions"],
              "routes": manifest["inputs"]["bases"], **outputs,
              "status": "git-release-committed", "publication": "not-published",
              "validation": {"reader_artifacts": "passed", "gameplay_verification": "not-performed", "coverage": "partial"}}
    result["manifest_sha256"] = digest(json_bytes(result))
    journal = {**prepared, "project": project, "result": result}
    immutable(stage / "plan.json", journal)
    write_changed(pending, json_bytes({"stage": journal["stage"], "sha256": digest(json_bytes(journal)), "complete": False}))
    return resume(root, journal), {"reused": False}
