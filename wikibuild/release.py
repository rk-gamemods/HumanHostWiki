"""Coordinate immutable reader releases across independently owned Git repositories."""

from dataclasses import asdict
import json
from pathlib import Path
import re
import uuid

from . import capacity_projection, extraction, git_transaction, physical, publication_git, reader, release_output, release_partitions, workspace
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
            for name in ("release.py", "release_content.py", "release_output.py", "release_partitions.py",
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
    topic = candidate / repo["id"]
    release_id = projection.release_id
    config_key = repo["id"] + f"/site/releases/{release_id}.json"
    configuration = projection.payloads[config_key].read()
    config_ref = projection.configurations[repo["id"]]
    if config_ref["path"].startswith("https://"):
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
            writer.add("site/" + name, source.read_bytes())
    writer.add("site/reader.js", (Path(__file__).parent / "release_bootstrap.js").read_bytes().replace(b"\r\n", b"\n"))
    writer.add("site/reader.css", b"/* The release loader selects the versioned stylesheet. */\n")
    links = [f"# {repo['title']} reference", "", f"Release: `{release_id}`.", "",
             "Selected extracted facts. Gameplay verification and complete coverage remain unfinished.", ""]
    links += [f"- [{name.removeprefix('reference/')}]({name.removeprefix('reference/')})" for name in reference_paths]
    writer.add("reference/index.md", ("\n".join(links) + "\n").encode())
    if "README.md" in writer.previous:
        writer.add("README.md", (f"# {repo['title']}\n\n{repo['coverage']}.\n\n"
            "Browse the [generated reference](reference/index.md). Coverage is partial; "
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


def verify(root, value, *, check_checkout=True):
    for topic, record in value["repositories"].items():
        path = within(root, record["path"])
        if git(path, "rev-parse", record["commit"] + "^{tree}") != record["tree"]:
            raise ContractError(f"Release commit tree differs: {topic}")
        if check_checkout:
            if git(path, "rev-parse", "HEAD") != record["commit"] or git(path, "status", "--porcelain=v1", "--untracked-files=all"):
                raise ContractError(f"Release checkout differs: {topic}")
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
    limits = physical.budgets(project)
    projection = capacity_projection.build(Path(candidate["path"]), release_id, project["github_owner"],
                                           inventory.partitions, inventory.stored, limits)
    registry = physical.registry(projection.partitions)
    ordered = sorted(physical.repositories(project, registry),
                     key=lambda repo: (repo["role"] == "hub", repo["role"] != "partition", repo["id"]))
    logical = {repo["id"]: repo for repo in project["repositories"]}
    previous = publication.published(root)
    stage = within(root, ".local/rs/" + uuid.uuid4().hex[:12])
    stage.mkdir(parents=True)
    plans, repositories, writers, destinations, new_repositories = {}, {}, {}, {}, []
    for repo in ordered:
        target = within(root, repo["path"])
        if repo["id"] in projection.created:
            target, entry = release_partitions.seed(root, stage, repo, logical[repo["logical_topic"]])
            new_repositories.append(entry)
        prepared = stage / repo["id"]
        prepared.mkdir()
        destinations[repo["id"]] = target
        writers[repo["id"]] = release_output.Writer(target, prepared, repo, release_id)
    for placement, data in projection.writes():
        writers[placement.partition].add(placement.artifact.path, data, allocated=True)
    for repo in ordered:
        writer, target = writers[repo["id"]], destinations[repo["id"]]
        if repo["role"] == "partition":
            release_partitions.landing(writer, project, repo)
        else:
            project_topic(Path(candidate["path"]), repo, writer, projection)
        changes, summary = writer.finish()
        if any(meta["bytes"] > limits.file_bytes for meta in changes.values()):
            raise ContractError(f"Generated control file exceeds the configured file budget: {repo['id']}")
        commit = git_transaction.prepare(target, stage / repo["id"], changes, f"Update wiki reference {release_id[:12]}")
        prior = previous["repositories"].get(repo["id"]) if previous else None
        old_pages = prior["pages"] if prior else None
        site_tree = git(target, "rev-parse", commit["commit"] + ":site")
        pages = (old_pages if prior and prior["tree"] == site_tree else
                 publication_git.commit(target, site_tree, old_pages, f"Publish wiki release {release_id}"))
        measured = capacity_inventory.history_size(target, [commit["commit"], pages])
        if changes and (summary["site_bytes"] > limits.site_bytes or measured["history_bytes"] > limits.history_bytes):
            raise ContractError(f"Prepared repository exceeds capacity after control files and Git history: {repo['id']}")
        git(target, "update-ref", f"refs/wiki-releases/{release_id}/source", commit["commit"])
        git(target, "update-ref", f"refs/wiki-releases/{release_id}/pages", pages)
        plans[repo["id"]] = {"path": repo["path"], "git": commit}
        repositories[repo["id"]] = {"path": repo["path"], "github_name": repo["github_name"],
                                     "commit": commit["commit"], "tree": commit["tree"], **summary,
                                     "pages": pages, "pages_parent": old_pages,
                                     "history_bytes": measured["history_bytes"]}
    if contract() != inputs["contract"]:
        raise ContractError("Release rules changed during preparation")
    reader.verify(Path(candidate["path"]), candidate["candidate_id"])
    result = {"schema_version": 1, "release_id": release_id, "inputs": inputs,
              "reader_candidate": candidate["candidate_id"], "versions": manifest["versions"],
              "routes": manifest["inputs"]["bases"], "repositories": repositories, "physical": registry,
              "capacity": {"budgets": asdict(limits), "phases": list(projection.phase_ids),
                           "new_repositories": list(projection.created), "prepared_sizes_checked": True},
              "status": "git-release-committed", "publication": "not-published",
              "validation": {"reader_artifacts": "passed", "gameplay_verification": "not-performed", "coverage": "partial"}}
    result["manifest_sha256"] = digest(json_bytes(result))
    journal = {"stage": stage.relative_to(root).as_posix(), "project": project,
               "order": [repo["id"] for repo in ordered], "plans": plans, "result": result,
               "new_repositories": new_repositories}
    immutable(stage / "plan.json", journal)
    write_changed(pending, json_bytes({"stage": journal["stage"], "sha256": digest(json_bytes(journal)), "complete": False}))
    return resume(root, journal), {"reused": False}
