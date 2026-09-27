"""Coordinate immutable reader releases across independently owned Git repositories."""

import json
from pathlib import Path
import re
import uuid

from . import extraction, git_transaction, reader, release_content, workspace
from .storage import ContractError, digest, git, json_bytes, within, write_changed

OWNER_FILE = ".wiki-output.json"
IMMUTABLE = ("site/data/", "site/objects/", "site/releases/", "site/runtime/")


def immutable(path, value):
    data = json_bytes(value)
    if path.exists() and path.read_bytes() != data:
        raise ContractError(f"Release receipt differs: {path}")
    write_changed(path, data)


def contract():
    folder = Path(__file__).parent
    return {name: digest((folder / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in ("release.py", "release_content.py", "git_transaction.py", "release_bootstrap.js", "workspace.py")}


def bases(project):
    return {repo["id"]: f"https://{project['github_owner']}.github.io/{repo['github_name']}/"
            for repo in project["repositories"]}


def owned(path):
    marker = path / OWNER_FILE
    files = {}
    if marker.exists():
        data = json.loads(marker.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or data.get("kind") != "generated-wiki-output":
            raise ContractError(f"Unknown generated-output ownership: {path}")
        files = data["files"]
    for folder in ("site", "reference"):
        base = path / folder
        if base.is_symlink():
            raise ContractError(f"Generated directory is a symbolic link: {base}")
        if base.exists():
            for entry in base.rglob("*"):
                if entry.is_symlink() or (entry.is_file() and entry.relative_to(path).as_posix() not in files):
                    raise ContractError(f"Unknown file in generated namespace: {entry}")
    for name, record in files.items():
        if name != "README.md" and not name.startswith(("site/", "reference/")):
            raise ContractError(f"Generated ownership escapes site/reference: {name}")
        target = within(path, name)
        if not target.is_file() or target.stat().st_size != record["bytes"] or extraction.file_hash(target) != record["sha256"]:
            raise ContractError(f"Modified or missing owned output: {target}")
    return files


def preflight(root, project):
    for repo in project["repositories"]:
        state = workspace.inspect(root, repo)
        if state["state"] != "clean":
            raise ContractError(f"Release destination {repo['id']} is {state['state']}")
        path = within(root, repo["path"])
        owned(path)


def project_topic(candidate, repo, destination, stage, release_id):
    previous = owned(destination)
    readme = destination / "README.md"
    if "README.md" not in previous and readme.is_file() and readme.read_bytes() == workspace.seed_readme(repo):
        # Adopt only the exact generator-owned seed. Preserve authored READMEs.
        previous["README.md"] = {"sha256": extraction.file_hash(readme), "bytes": readme.stat().st_size}
    output, changes = dict(previous), {}
    topic = candidate / repo["id"]

    def add(name, data):
        record = {"sha256": digest(data), "bytes": len(data)}
        prior = previous.get(name)
        if name.startswith(IMMUTABLE) and prior and record != prior:
            raise ContractError(f"Immutable public object differs: {name}")
        output[name] = record
        if prior == record:
            return
        target = within(destination, name)
        if prior is None and target.exists():
            raise ContractError(f"Refusing to adopt an unknown generated file: {target}")
        staged = within(stage, name)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        changes[name] = {"old": prior["sha256"] if prior else None, "new": record["sha256"], "bytes": len(data)}

    config = json.loads((topic / "reader.json").read_text(encoding="utf-8"))
    snapshot_refs, runtime_refs = {}, {}
    reference_paths = []
    for source in sorted(topic.rglob("*")):
        if not source.is_file():
            continue
        name = source.relative_to(topic).as_posix()
        data = source.read_bytes()
        if re.fullmatch(r"data/[0-9a-f]{64}\.json", name):
            add("site/" + name, data)
        elif re.fullmatch(r"snapshots/build-[0-9]+-[0-9a-f]{12}\.json", name):
            data = release_content.snapshot(data, lambda path, sha, size: path)
            target = "objects/" + digest(data) + ".json"
            add("site/" + target, data)
            snapshot_refs[source.stem] = {"path": target, "sha256": digest(data), "bytes": len(data)}
        elif name in {"reader.js", "reader.css"}:
            target = f"runtime/{digest(data)}/{name}"
            add("site/" + target, data)
            runtime_refs[source.suffix[1:]] = target
        elif name.startswith("reference/") and source.suffix == ".md":
            add(name, data.replace(("release=" + config["candidate_id"]).encode(), ("release=" + release_id).encode()))
            reference_paths.append(name)
        elif name in {"index.html", "404.html", ".nojekyll"} or re.fullmatch(r"groups/[a-z][a-z0-9-]*/index\.html", name):
            add("site/" + name, data)
        elif name != "reader.json":
            raise ContractError(f"Unexpected reader output for release: {name}")
    configuration = release_content.configuration((topic / "reader.json").read_bytes(), release_id,
                                                   snapshot_refs, runtime_refs)
    add(f"site/releases/{release_id}.json", configuration)
    add("site/reader.json", configuration)
    add("site/reader.js", (Path(__file__).parent / "release_bootstrap.js").read_bytes().replace(b"\r\n", b"\n"))
    add("site/reader.css", b"/* The release loader selects the versioned stylesheet. */\n")
    links = [f"# {repo['title']} reference", "", f"Release: `{release_id}`.", "",
             "Selected extracted facts. Gameplay verification and complete coverage remain unfinished.", ""]
    links += [f"- [{name.removeprefix('reference/')}]({name.removeprefix('reference/')})" for name in reference_paths]
    add("reference/index.md", ("\n".join(links) + "\n").encode())
    if "README.md" in previous:
        add("README.md", (f"# {repo['title']}\n\n{repo['coverage']}.\n\n"
            "Browse the [generated reference](reference/index.md). Coverage is partial; "
            "serialized facts are not runtime-verified gameplay claims.\n\n"
            f"Current prepared release: `{release_id}`. Publication is tracked separately by the hub.\n\n"
            "Generated files are recorded in `.wiki-output.json`. Put authored explanations outside "
            "the generated `site/` and `reference/` directories.\n").encode())
    marker = json_bytes({"schema_version": 1, "kind": "generated-wiki-output", "release_id": release_id,
                         "repository_id": repo["id"], "files": output})
    target = destination / OWNER_FILE
    (stage / OWNER_FILE).write_bytes(marker)
    changes[OWNER_FILE] = {"old": extraction.file_hash(target) if target.exists() else None,
                           "new": digest(marker), "bytes": len(marker)}
    return changes, {"files_sha256": digest(json_bytes(output)), "file_count": len(output),
                     "site_bytes": sum(record["bytes"] for name, record in output.items() if name.startswith("site/")),
                     "output_bytes": sum(record["bytes"] for record in output.values()),
                     "ownership_sha256": digest(marker)}


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
    for repo in journal["project"]["repositories"]:
        workspace.inspect(root, repo)
        item = journal["plans"][repo["id"]]
        git_transaction.validate(within(root, item["path"]), item["git"])
    for repo in journal["order"]:
        item = journal["plans"][repo]
        git_transaction.promote(within(root, item["path"]), stage / repo, item["git"])
    result = journal["result"]
    verify(root, result)
    immutable(within(root, f"releases/{result['release_id']}.json"), result)
    workspace.checkout_lock(root, journal["project"])
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
    stage = within(root, ".local/rs/" + uuid.uuid4().hex[:12])
    stage.mkdir(parents=True)
    plans, repositories = {}, {}
    ordered = sorted(project["repositories"], key=lambda repo: (repo["role"] == "hub", repo["id"]))
    for repo in ordered:
        target, prepared = within(root, repo["path"]), stage / repo["id"]
        prepared.mkdir()
        changes, summary = project_topic(Path(candidate["path"]), repo, target, prepared, release_id)
        commit = git_transaction.prepare(target, prepared, changes, f"Update wiki reference {release_id[:12]}")
        plans[repo["id"]] = {"path": repo["path"], "git": commit}
        repositories[repo["id"]] = {"path": repo["path"], "github_name": repo["github_name"],
                                     "commit": commit["commit"], "tree": commit["tree"], **summary}
    if contract() != inputs["contract"]:
        raise ContractError("Release rules changed during preparation")
    reader.verify(Path(candidate["path"]), candidate["candidate_id"])
    result = {"schema_version": 1, "release_id": release_id, "inputs": inputs,
              "reader_candidate": candidate["candidate_id"], "versions": manifest["versions"],
              "routes": manifest["inputs"]["bases"], "repositories": repositories,
              "status": "git-release-committed", "publication": "not-published",
              "validation": {"reader_artifacts": "passed", "gameplay_verification": "not-performed", "coverage": "partial"}}
    result["manifest_sha256"] = digest(json_bytes(result))
    journal = {"stage": stage.relative_to(root).as_posix(), "project": project,
               "order": [repo["id"] for repo in ordered], "plans": plans, "result": result}
    immutable(stage / "plan.json", journal)
    write_changed(pending, json_bytes({"stage": journal["stage"], "sha256": digest(json_bytes(journal)), "complete": False}))
    return resume(root, journal), {"reused": False}
