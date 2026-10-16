"""Independently confirm advanced topic sites using only remote reads."""

import json

from . import github_pages, physical, publication, publication_evidence, publication_git
from .storage import ContractError, digest, git, json_bytes, within


def run(root, project, selected, host=None, progress=None):
    publication.refuse_pending(root)
    progress = progress or (lambda message: None)
    host = host or github_pages.GitHubPages(project["github_owner"], progress)
    release_path = within(root, f"releases/{selected['release_id']}.json")
    data = publication_evidence.committed_bytes(root, release_path)
    project_data = publication_evidence.committed_bytes(root, root / "project.json")
    if (data is None or project_data is None or json.loads(data) != selected
            or json.loads(project_data) != project):
        raise ContractError("Topic confirmation requires the committed selected release and project")
    previous = publication.published(root)
    if previous and publication_evidence.committed_bytes(root,
            root / f"publications/{previous['release_id']}.json") is None:
        raise ContractError("Topic confirmation requires the reviewed previous publication")
    prior_rows = previous["repositories"] if previous else {}
    rows, checks_by_id, observations = {}, {}, {}
    for repo in physical.repositories(project, selected.get("physical")):
        key, name = repo["id"], repo["github_name"]
        # The transaction's selection point and all hub partitions are excluded.
        if repo.get("logical_topic", key) == "hub" or repo["role"] == "hub":
            continue
        record, prior = selected["repositories"][key], prior_rows.get(key)
        pages = host.ref(name, "gh-pages")
        if pages == (prior["pages"] if prior else None):
            continue
        progress(f"Confirm topic metadata: {name}")
        observation = github_pages.observe_configuration(host, project["github_owner"], name)
        intent_path = within(root, f".local/publication/remotes/{key}.json")
        intent = publication.load(intent_path) if intent_path.exists() else None
        expected_id = prior["repository_id"] if prior else (intent or {}).get("repository_id")
        if (observation["observed"] != "present" or observation["repository_id"] != expected_id
                or (intent and intent["full_name"] != project["github_owner"] + "/" + name)):
            raise ContractError(f"Topic confirmation destination differs: {name}")
        main = host.ref(name, "main")
        path = within(root, record["path"])
        if main != record["commit"]:
            raise ContractError(f"Topic confirmation main differs: {name}")
        if not pages or not publication_git.check_pin(path, "refs/wiki-publications/" + pages, pages):
            raise ContractError(f"Topic confirmation requires an exact direct pin: {name}")
        parent = git(path, "show", "-s", "--format=%P", pages)
        baseline = prior["pages"] if prior else None
        if parent != (baseline or ""):
            raise ContractError(f"Topic confirmation requires the last published parent: {name}")
        tree = git(path, "rev-parse", record["commit"] + ":site")
        if git(path, "rev-parse", pages + "^{tree}") != tree:
            raise ContractError(f"Topic confirmation tree differs: {name}")
        build = host.api("GET", f"repos/{project['github_owner']}/{name}/pages/builds/latest")
        if not isinstance(build, dict) or build.get("commit") != pages or build.get("status") != "built":
            raise ContractError(f"Topic confirmation requires the exact completed Pages build: {name}")
        files = publication.site_files(root, record)
        checks = {key: value for key, value in files.items() if not prior or prior["files"].get(key) != value
                  or key in {"reader.json", "index.html", "404.html"}}
        if not checks:
            raise ContractError(f"Topic confirmation has no public checks: {name}")
        rows[key] = {"path": record["path"], "name": name, "role": repo["role"],
                     "repository_id": expected_id, "main": main, "pages": pages,
                     "base_pages": baseline, "tree": tree, "build_commit": build["commit"],
                     "build_status": build["status"], "build_url": build["url"],
                     "files_sha256": digest(json_bytes(files)), "checks_sha256": digest(json_bytes(checks)),
                     "checked_files": len(checks)}
        checks_by_id[key], observations[key] = checks, observation
    if not rows:
        return {"status": "no-advanced-topics", "confirmed_topics": 0}
    # Check every cheap condition before any public downloads. No pushes, build
    # requests, retries with effects, provisioning or publication state writes.
    for key, row in rows.items():
        progress(f"Confirm public topic bytes: {row['name']} ({row['checked_files']} files)")
        host.verify(physical.base(project, {"github_name": row["name"]}), checks_by_id[key])
    for key, row in rows.items():
        if (host.ref(row["name"], "main") != row["main"] or host.ref(row["name"], "gh-pages") != row["pages"]
                or github_pages.observe_configuration(host, project["github_owner"], row["name"]) != observations[key]):
            raise ContractError(f"Topic confirmation remote changed during verification: {row['name']}")
    payload = {"schema_version": 1, "kind": "topic-publication-confirmation", "status": "verified",
               "owner": project["github_owner"], "release_id": selected["release_id"],
               "release_file_sha256": digest(data), "workspace_commit": git(root, "rev-parse", "HEAD"),
               "repositories": rows}
    # A proof's review commit must not make its unchanged repeat a new artifact.
    # Reuse only the exact same independently rechecked observations, with an
    # existing ancestor as the original observation's workspace commit.
    for existing in sorted((root / "topic-confirmations").glob("*.json")):
        observed = publication.load(existing)
        if ({key: value for key, value in observed.items() if key != "workspace_commit"}
                == {key: value for key, value in payload.items() if key != "workspace_commit"}
                and publication_git.released_lineage(root, None, observed["workspace_commit"], payload["workspace_commit"])):
            payload = observed
            break
    identity = digest(json_bytes(payload))
    target = root / "topic-confirmations" / (identity + ".json")
    if target.exists() and publication.load(target) != payload:
        raise ContractError("Immutable topic confirmation differs")
    publication.save(target, payload)
    return {"status": "topics-confirmed", "confirmed_topics": len(rows), "receipt": target.relative_to(root).as_posix(),
            "note": "Review and commit this independent proof before a fresh rehearsal. The hub selection is unchanged."}
