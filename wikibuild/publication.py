"""Durable topic-first Pages publication; the hub selects a verified release last."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

from . import entrypoints, github_pages, ownership, physical, publication_git, release
from .storage import ContractError, digest, git, json_bytes, within, write_changed


def contract():
    return {name: digest((Path(__file__).parent / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in ("publication.py", "publication_git.py", "github_pages.py", "ownership.py", "entrypoints.py", "physical.py")}


def save(path, payload):
    write_changed(path, json_bytes({"payload": payload, "sha256": digest(json_bytes(payload))}))


def load(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("sha256") != digest(json_bytes(value["payload"])):
        raise ContractError(f"Publication receipt was modified: {path}")
    return value["payload"]


def published(root):
    pointer = root / "publications/latest.json"
    if not pointer.exists():
        return None
    identity = load(pointer)["release_id"]
    return load(within(root, f"publications/{identity}.json"))


def provision(root, project, host):
    identities = {}
    previous = published(root)
    for repo in project["repositories"]:
        path = within(root, f".local/publication/remotes/{repo['id']}.json")
        name = repo["github_name"]
        full_name = project["github_owner"] + "/" + name
        description = f"Human Host community wiki: {repo['title']}. Generated reference with explicit coverage gaps."
        intent = load(path) if path.exists() else None
        remote = host.repository(name)
        if intent is None:
            prior = previous["repositories"].get(repo["id"]) if previous else None
            if remote is not None and not (prior and prior["name"] == name and prior["repository_id"] == remote["id"]):
                raise ContractError(f"Remote exists without this workspace's provisioning receipt: {full_name}")
            intent = {"full_name": full_name, "repository_id": remote["id"] if remote else None, "description": description}
            save(path, intent)
        if intent["full_name"] != full_name:
            raise ContractError("Remote destination changed from the provisioning receipt")
        if remote is None:
            if intent["repository_id"] is not None:
                raise ContractError(f"Previously provisioned remote is missing: {full_name}")
            remote = host.create(name, description)
        if (remote["full_name"].casefold() != full_name.casefold() or remote.get("private") or
                remote.get("archived") or remote.get("fork") or not remote.get("permissions", {}).get("admin")):
            raise ContractError(f"Unexpected remote identity or permissions: {full_name}")
        if intent["repository_id"] is None:
            if remote.get("description") != description or host.ref(name, "main") is not None:
                raise ContractError(f"Unrecognized remote after interrupted creation: {full_name}")
            intent["repository_id"] = remote["id"]
            save(path, intent)
        if intent["repository_id"] != remote["id"]:
            raise ContractError(f"Remote was replaced: {full_name}")
        identities[repo["id"]] = remote["id"]
    return identities


def site_files(root, record):
    path = within(root, record["path"])
    owner, _ = ownership.committed(path, record["commit"])
    return {name.removeprefix("site/"): meta for name, meta in owner["files"].items() if name.startswith("site/")}


def pin(path, commit):
    git(path, "update-ref", f"refs/wiki-publications/{commit}", commit)


def prepare(root, project, manifest, host):
    if digest(json_bytes(project)) != manifest["inputs"]["project_sha256"]:
        raise ContractError("Publication project differs from the pinned Git release")
    previous = published(root)
    # Audit all outgoing history before creating any remote or pushing any bytes.
    for topic, record in manifest["repositories"].items():
        baseline = previous["repositories"][topic]["main"] if previous and topic in previous["repositories"] else None
        publication_git.audit(within(root, record["path"]), record["commit"], baseline)
    repositories = physical.repositories(project, manifest.get("physical"))
    if {repo["id"] for repo in repositories} != set(manifest["repositories"]):
        raise ContractError("Publication outputs differ from the physical registry")
    identities = provision(root, {**project, "repositories": repositories}, host)
    plans = {}
    for repo in repositories:
        topic, name = repo["id"], repo["github_name"]
        record = manifest["repositories"][topic]
        path = within(root, record["path"])
        old_main, old_pages = host.ref(name, "main"), host.ref(name, "gh-pages")
        prior = previous["repositories"].get(topic) if previous else None
        if old_main not in {None, record["commit"], prior["main"] if prior else None}:
            raise ContractError(f"Unexpected remote main: {name}")
        if old_pages != (prior["pages"] if prior else None):
            raise ContractError(f"Unexpected remote Pages branch: {name}")
        tree = git(path, "rev-parse", record["commit"] + ":site")
        if "pages" in record:
            if record["pages_parent"] == old_pages:
                target = record["pages"]
            else:
                # An earlier pending publication can finish after this local
                # release was prepared. Its verified receipt is the new parent;
                # remeasure the exact rebased history before advertising bytes.
                from .capacity_inventory import history_size
                target = publication_git.commit(path, tree, old_pages, f"Publish wiki release {manifest['release_id']}")
                if history_size(path, [record["commit"], target])["history_bytes"] > physical.budgets(project).history_bytes:
                    raise ContractError("Recovered Pages history exceeds the configured capacity")
            if git(path, "rev-parse", target + "^{tree}") != tree:
                raise ContractError("Prepared Pages tree differs")
        else:
            target = publication_git.commit(path, tree, old_pages, f"Publish wiki release {manifest['release_id']}")
        pin(path, target)
        files = site_files(root, record)
        checks = {key: value for key, value in files.items() if not prior or prior["files"].get(key) != value
                  or key in {"reader.json", "index.html", "404.html"}}
        plans[topic] = {"path": record["path"], "name": name, "repository_id": identities[topic],
                        "base": physical.base(project, repo), "role": repo["role"],
                        "old_main": old_main, "old_pages": old_pages,
                        "main": record["commit"], "pages": target, "tree": tree,
                        "files": files, "checks": checks, "verified": False}
    fronts = manifest.get("entrypoints", {repo["id"]: repo["id"] for repo in project["repositories"]})
    prior_fronts = previous.get("entrypoints", {topic: topic for topic in fronts}) if previous else {topic: topic for topic in fronts}
    control, groups = entrypoints.publication_groups(repositories, fronts, prior_fronts)
    hub_path = within(root, plans[control]["path"])
    fallback_tree, fallback_files = ((previous["repositories"][control]["tree"], previous["repositories"][control]["files"])
                                     if previous and control in previous["repositories"] else publication_git.unavailable(hub_path))
    return {"schema_version": 1, "release_id": manifest["release_id"], "owner": project["github_owner"],
            "contract": contract(), "phase": "topics", "repositories": plans,
            "hub_control": control, "entrypoints": fronts, "groups": groups,
            "fallback": {"tree": fallback_tree, "files": fallback_files}, "rollback": None}


def deploy(root, plan, host):
    path = within(root, plan["path"])
    host.push(path, plan["name"], plan["main"], "main", plan["old_main"])
    host.push(path, plan["name"], plan["pages"], "gh-pages", plan["old_pages"])
    host.configure(plan["name"])
    host.wait(plan["name"], plan["pages"])
    host.verify(plan["base"], plan["checks"])


def health(plan):
    name = "reader.json" if "reader.json" in plan["files"] else "index.html"
    return {name: plan["files"][name]}


def rollback(root, state, path, host):
    hub = state["repositories"][state.get("hub_control", "hub")]
    repo = within(root, hub["path"])
    if state["rollback"] is None:
        target = publication_git.commit(repo, state["fallback"]["tree"], hub["pages"],
                                        f"Restore previous hub after release {state['release_id']}")
        pin(repo, target)
        state["rollback"] = target
        state["phase"] = "rolling-back"
        save(path, state)
    host.push(repo, hub["name"], state["rollback"], "gh-pages", hub["pages"])
    host.configure(hub["name"])
    host.wait(hub["name"], state["rollback"])
    host.verify(hub["base"], state["fallback"]["files"])
    state["phase"] = "rolled-back"
    save(path, state)


def resume(root, state, path, host, workers):
    if state["phase"] == "rolling-back":
        rollback(root, state, path, host)
    if state["phase"] == "rolled-back":
        hub = state["repositories"][state.get("hub_control", "hub")]
        hub["old_pages"] = state["rollback"]
        hub["pages"] = publication_git.commit(within(root, hub["path"]), hub["tree"], hub["old_pages"],
                                               f"Retry wiki release {state['release_id']}")
        pin(within(root, hub["path"]), hub["pages"])
        state.update(phase="topics", rollback=None)
        save(path, state)
    # Reconcile already verified topic refs. A saved success is not authority to
    # overwrite later external edits, or proof that the current target is live.
    for topic, plan in state["repositories"].items():
        remote = host.repository(plan["name"])
        if not remote or remote["id"] != plan["repository_id"] or remote.get("private"):
            raise ContractError(f"Publication destination changed: {plan['name']}")
        if plan["verified"]:
            if host.ref(plan["name"], "main") != plan["main"] or host.ref(plan["name"], "gh-pages") != plan["pages"]:
                raise ContractError(f"Verified publication changed remotely: {plan['name']}")
            host.verify(plan["base"], health(plan))
    # Storage is a dependency of every topic/front that references its bytes.
    # Complete independent workers within each phase before advertising the next.
    groups = state.get("groups") or [[topic for topic, plan in state["repositories"].items()
                                      if topic != "hub" and (plan.get("role") == "partition") == storage]
                                     for storage in (True, False)]
    for rank, identities in enumerate(groups):
        topics = [state["repositories"][topic] for topic in identities if not state["repositories"][topic]["verified"]]
        errors = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(deploy, root, plan, host): plan for plan in topics}
            for future in as_completed(pending):
                plan = pending[future]
                try:
                    future.result()
                    plan["verified"] = True
                    save(path, state)
                except Exception as exc:
                    errors.append(f"{plan['name']}: {exc}")
        if errors:
            raise ContractError(("Storage" if rank == 0 else "Topic") + " publication failed; hub unchanged: " + "; ".join(errors))
    hub = state["repositories"][state.get("hub_control", "hub")]
    if not hub["verified"]:
        state["phase"] = "hub"
        save(path, state)
        try:
            deploy(root, hub, host)
            hub["verified"] = True
            save(path, state)
        except github_pages.BuildObservationError:
            # An unavailable observation is not a terminal build result. Keep the
            # prepared commit pending; a retry discovers its actual remote state.
            raise
        except Exception:
            # Only a push that actually advanced the hub needs a compensating
            # commit. An unconfirmed response is reconciled against the live ref.
            if host.ref(hub["name"], "gh-pages") == hub["pages"]:
                rollback(root, state, path, host)
            raise
    result = {"schema_version": 1, "release_id": state["release_id"], "contract": state["contract"],
              "status": "published", "repositories": state["repositories"], "hub": state["repositories"]["hub"]["base"],
              "entrypoints": state.get("entrypoints", {topic: topic for topic, plan in state["repositories"].items()
                                                      if plan.get("role") != "partition"})}
    receipt = within(root, f"publications/{state['release_id']}.json")
    if receipt.exists() and load(receipt) != result:
        raise ContractError("Immutable publication receipt differs")
    save(receipt, result)
    save(root / "publications/latest.json", {"release_id": state["release_id"]})
    state["phase"] = "complete"
    save(path, state)
    return result


def run(root, project, manifest, *, host=None, progress=None):
    """Caller holds the shared OS writer lock; no model calls or human gates."""
    if not project.get("publication", {}).get("enabled", False):
        return {"status": "disabled"}, {"reused": True}
    host = host or github_pages.GitHubPages(project["github_owner"], progress)
    workers = project["publication"].get("workers", 4)
    path = root / ".local/publication/pending.json"
    state = load(path) if path.exists() else None
    if state and state["phase"] != "complete":
        if state["owner"] != project["github_owner"]:
            raise ContractError("Pending publication belongs to another namespace")
        resumed = resume(root, state, path, host, workers)
        if resumed["release_id"] == manifest["release_id"]:
            return resumed, {"reused": False}
    release.verify(root, manifest)
    current = published(root)
    if current and current["release_id"] == manifest["release_id"]:
        def check_current(plan):
            remote = host.repository(plan["name"])
            if not remote or remote["id"] != plan["repository_id"] or remote.get("private"):
                raise ContractError(f"Published destination changed: {plan['name']}")
            if host.ref(plan["name"], "main") != plan["main"] or host.ref(plan["name"], "gh-pages") != plan["pages"]:
                raise ContractError(f"Published branch changed: {plan['name']}")
            host.configure(plan["name"])
            host.verify(plan["base"], health(plan))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(check_current, current["repositories"].values()))
        return current, {"reused": True}
    state = prepare(root, project, manifest, host)
    save(path, state)
    return resume(root, state, path, host, workers), {"reused": False}
