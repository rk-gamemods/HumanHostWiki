"""Durable topic-first Pages publication; the hub selects a verified release last."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import Lock
from time import monotonic, perf_counter

from . import entrypoints, github_pages, ownership, physical, publication_git, publish_gate, release, run_timing
from .storage import ContractError, digest, git, json_bytes, within, write_changed


def contract():
    modules = {name: digest((Path(__file__).parent / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in ("publication.py", "publication_git.py", "github_pages.py", "ownership.py", "entrypoints.py", "physical.py", "publish_gate.py")}
    runner = Path(__file__).resolve().parents[1] / "tools/rehearse_publication.py"
    modules["tools/rehearse_publication.py"] = digest(runner.read_bytes().replace(b"\r\n", b"\n"))
    return modules


def refuse_pending(root):
    path = root / ".local/publication/pending.json"
    if not path.exists():
        return
    try:
        complete = load(path).get("phase") == "complete"
    except (ContractError, OSError, ValueError, KeyError, TypeError, AttributeError):
        complete = False
    if not complete:
        raise ContractError("Incomplete publication must be scrapped; run py -3 wiki.py abandon-publication, then rehearse and publish afresh")


def abandon(root):
    """Caller holds the writer lock. Archive local evidence without remote calls."""
    path = root / ".local/publication/pending.json"
    if not path.exists():
        return {"status": "nothing-to-abandon"}
    try:
        state = load(path)
    except (ContractError, ValueError, KeyError, TypeError, AttributeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    if state.get("phase") == "complete":
        return {"status": "nothing-to-abandon"}
    identity = state.get("release_id", "unknown")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
        identity = "unknown"
    related = {identity}
    for key in ("gate", "last_gate"):
        gate = state.get(key)
        rehearsal = gate.get("rehearsal") if isinstance(gate, dict) else None
        release_id = rehearsal.get("release_id") if isinstance(rehearsal, dict) else None
        if isinstance(release_id, str) and re.fullmatch(r"[0-9a-f]{64}", release_id):
            related.add(release_id)
    records = []
    for source in sorted((root / ".local/publication/rehearsals").rglob("*.json")):
        source = within(root, source.relative_to(root))
        try:
            receipt = load(source)
        except (ContractError, ValueError, KeyError, TypeError, AttributeError):
            receipt = {}
        release_id = receipt.get("release_id") if isinstance(receipt, dict) else None
        # An unidentified attempt cannot prove that any rehearsal is unrelated.
        if identity == "unknown" or source.stem in related or (isinstance(release_id, str) and release_id in related):
            records.append((source, f"rehearsal-{len(records) + 1:03d}.json"))
    if identity != "unknown":
        receipt = within(root, f"publications/{identity}.json")
        if receipt.exists():
            pointer = root / "publications/latest.json"
            latest = load(pointer) if pointer.exists() else {}
            if (not isinstance(latest, dict) or (pointer.exists() and
                    (not isinstance(latest.get("release_id"), str) or
                     not re.fullmatch(r"[0-9a-f]{64}", latest["release_id"])))):
                raise ContractError("Cannot abandon publication with an invalid latest publication pointer")
            if latest.get("release_id") != identity:
                try:
                    belongs = load(receipt) == completed_receipt(state)
                except (ContractError, ValueError, KeyError, TypeError, AttributeError):
                    belongs = False
                if belongs:
                    records.append((receipt, "publication.json"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = within(root, f".local/publication/abandoned/{stamp}-{identity}")
    destination.mkdir(parents=True)
    (destination / "README.md").write_text(
        "# Abandoned publication\n\nThis failed run was scrapped and will never resume.\n"
        "Local evidence was archived; remote branches were not changed.\n"
        "Rehearse the selected local release against current live state before publishing afresh.\n\n"
        "Archived records (short names avoid Windows path limits):\n"
        + "".join(f"- `{name}`: `{source.relative_to(root).as_posix()}`\n" for source, name in records)
        + "- `pending.json`: `.local/publication/pending.json`\n",
        encoding="utf-8")
    # Keep the pending boundary in place until all old eligibility is removed.
    for source, name in records:
        source.rename(destination / name)
    path.rename(destination / "pending.json")
    return {"status": "abandoned", "release_id": identity, "archive": destination.relative_to(root).as_posix()}


class RehearsedRefs:
    """Only rehearsed tips or this invocation's confirmed pushes may be advanced."""
    def __init__(self, rows):
        self.expected = {(row["repository"], row["branch"]): row["commit"] for row in rows}
        self.confirmed = {}

    @staticmethod
    def check_deadline(host, deadline):
        if deadline is not None and getattr(host, "clock", monotonic)() >= deadline:
            raise github_pages.BuildObservationError("Publication deadline exhausted")

    def read_ref(self, host, name, branch, *, deadline=None):
        self.check_deadline(host, deadline)
        try:
            actual = host.ref(name, branch, **({"deadline": deadline} if deadline is not None else {}))
        except (ContractError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            if deadline is None:
                raise
            # Recovery observations share the build deadline. An unknown outcome
            # must not enter execute's rollback path with a fresh push budget.
            raise github_pages.BuildObservationError(
                f"Unable to observe Pages recovery ref {name}/{branch}: {exc}") from exc
        self.check_deadline(host, deadline)
        return actual

    def observe(self, host, name, branch, *, deadline=None):
        key = (name, branch)
        if key not in self.expected:
            raise ContractError(f"Missing rehearsed ref: {name}/{branch}")
        actual = self.read_ref(host, name, branch, deadline=deadline)
        if actual != self.expected[key]:
            raise ContractError(f"Remote ref differs from rehearsal or this invocation's confirmed push: {name}/{branch}")
        return actual

    def check(self, host, keys):
        for name, branch in sorted(keys):
            self.observe(host, name, branch)

    def push(self, host, path, name, commit, branch, *, deadline=None):
        expected = self.observe(host, name, branch, deadline=deadline)
        key = (name, branch)
        # The adapter reconciles a lost push response before returning success.
        # A failing call is never authority to adopt a coincidentally matching tip.
        self.check_deadline(host, deadline)
        host.push(path, name, commit, branch, expected, **({"deadline": deadline} if deadline is not None else {}))
        actual = self.read_ref(host, name, branch, deadline=deadline)
        if actual != commit:
            raise ContractError(f"Publication push was not confirmed: {name}/{branch}")
        self.expected[key] = self.confirmed[key] = commit


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


class DestinationValidation:
    """Validate at first effect and before advertising the coordinated release."""
    def __init__(self, owner, host, observations):
        self.owner, self.host = owner, host
        self.expected = {row["repository"]: row for row in observations}
        self.checked = set()

    def observe(self, name):
        actual = github_pages.observe_configuration(self.host, self.owner, name)
        if name in self.expected and actual != self.expected[name]:
            raise ContractError(f"Publication destination observation changed: {name}")
        self.expected[name] = actual

    def before(self, name):
        if name not in self.checked:
            self.observe(name)
            self.checked.add(name)

    def created(self, name, repository):
        self.expected[name] = github_pages.validate_configuration(self.owner, name, repository, None)

    def configured(self, name, pages):
        if isinstance(pages, dict) and self.expected[name]["observed"] == "pages-disabled":
            row = self.expected[name]
            repository = {"id": row["repository_id"], **row["identity"],
                          "permissions": {"admin": row["identity"]["admin"]}}
            self.expected[name] = github_pages.validate_configuration(self.owner, name, repository, pages)

    def promotion(self):
        for name in sorted(self.expected):
            self.observe(name)
            self.checked.add(name)


def provision(root, project, host, validation=None):
    identities = {}
    previous = published(root)
    for repo in project["repositories"]:
        path = within(root, f".local/publication/remotes/{repo['id']}.json")
        name = repo["github_name"]
        full_name = project["github_owner"] + "/" + name
        description = f"{project.get('project', 'Unofficial game reference')}: {repo['title']}. An unofficial community project. Not affiliated with or endorsed by Virtual Matrix Studio."
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
            if validation is not None:
                validation.before(name)
            remote = host.create(name, description)
            if validation is not None:
                validation.created(name, remote)
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


def prepare(root, project, manifest, host, refs, validation=None):
    # Never adopt history that changed after the gate, even if it is our lineage.
    refs.check(host, publish_gate.destinations(root, project, manifest))
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
    identities = provision(root, {**project, "repositories": repositories}, host, validation)
    plans = {}
    for repo in repositories:
        topic, name = repo["id"], repo["github_name"]
        record = manifest["repositories"][topic]
        path = within(root, record["path"])
        old_main, old_pages = refs.observe(host, name, "main"), refs.observe(host, name, "gh-pages")
        prior = previous["repositories"].get(topic) if previous else None
        if prior and old_pages not in {None, prior["pages"]} and hasattr(host, "fetch"):
            host.fetch(path, name, "gh-pages")  # A restore made on the remote is not local yet.
        # An abandoned publication may have advanced main and gh-pages past the last
        # receipt. Adopt only history this workspace published; refuse anything else.
        abandoned_main = publication_git.released_lineage(path, prior["main"] if prior else None, old_main, record["commit"])
        if old_main not in {None, record["commit"], prior["main"] if prior else None} and not abandoned_main:
            raise ContractError(f"Unexpected remote main: {name}")
        if old_pages != (prior["pages"] if prior else None) and not (
                publication_git.owned_lineage(path, prior["pages"] if prior else None, old_pages)):
            raise ContractError(f"Unexpected remote Pages branch: {name}")
        tree = git(path, "rev-parse", record["commit"] + ":site")
        if "pages" in record:
            if record["pages_parent"] == old_pages:
                target = record["pages"]
            else:
                # A scrapped publication may have advanced the rehearsed parent.
                # Remeasure the rebased history before advertising bytes.
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


@contextmanager
def measure(timing, key):
    if isinstance(timing, run_timing.Values):
        with timing.observe(key):
            yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        if timing is not None:
            timing[key] = timing.get(key, 0.0) + (perf_counter() - started)


def timing_clock():
    """Resolve the publication clock when sampled, including injected clocks."""
    return perf_counter()


def repository_timing(lock=None):
    return run_timing.Values(dict.fromkeys(("push_main", "push_pages", "configure", "pages_build", "verify", "total"), 0.0),
                            lock=lock, clock=timing_clock)


def repository_row(timing, group, identity):
    if isinstance(timing, run_timing.Values):
        with timing.lock:
            return timing[group].setdefault(identity, repository_timing(timing.lock))
    return timing[group].setdefault(identity, repository_timing())


def deploy(root, plan, host, timing=None, refs=None, journal=None, validation=None):
    if refs is None:
        refs = RehearsedRefs([{"repository": plan["name"], "branch": branch, "commit": plan[key]}
                              for branch, key in (("main", "old_main"), ("gh-pages", "old_pages"))])
    path = within(root, plan["path"])
    with measure(timing, "total"):
        if validation is not None:
            validation.before(plan["name"])
        with measure(timing, "configure"):
            configuration = host.configure(plan["name"], defer=True)
        with measure(timing, "push_main"):
            refs.push(host, path, plan["name"], plan["main"], "main")
        with measure(timing, "push_pages"):
            refs.push(host, path, plan["name"], plan["pages"], "gh-pages")
        if callable(configuration):
            with measure(timing, "configure"):
                configuration = configuration()
        if validation is not None:
            validation.configured(plan["name"], configuration)
        try:
            with measure(timing, "pages_build"):
                host.wait(plan["name"], plan["pages"])
        except github_pages.QueuedPagesError as exc:
            if plan.get("recovery") or journal is None:
                raise github_pages.BuildObservationError(
                    f"Pages {plan['name']} remains queued-not-started; no further successor attempt is allowed. "
                    "Abandon the publication journal and rehearse a fresh run later.") from exc
            stuck = plan["pages"]
            if refs.observe(host, plan["name"], "gh-pages", deadline=exc.deadline) != stuck:
                raise ContractError(f"Pages recovery source changed: {plan['name']}")
            tree = git(path, "rev-parse", stuck + "^{tree}")
            if tree != plan["tree"]:
                raise ContractError(f"Pages recovery tree differs: {plan['name']}")
            successor = publication_git.commit(path, tree, stuck, "Recover never-started Pages build")
            pin(path, successor)
            transition = {"stuck": stuck, "successor": successor, "status": "prepared"}
            # Persist our exact transition before any remote effect. A failed run
            # never reloads this journal to resume a recovery.
            journal(plan, transition)
            with measure(timing, "push_pages"):
                refs.push(host, path, plan["name"], successor, "gh-pages", deadline=exc.deadline)
            journal(plan, {**transition, "status": "confirmed"})
            try:
                with measure(timing, "pages_build"):
                    host.wait(plan["name"], successor, deadline=exc.deadline)
            except github_pages.QueuedPagesError as successor_error:
                raise github_pages.BuildObservationError(
                    f"Pages successor {successor} for {plan['name']} is also queued-not-started; "
                    "the single recovery attempt is exhausted. Abandon the publication journal "
                    "and rehearse a fresh run later.") from successor_error
        with measure(timing, "verify"):
            host.verify(plan["base"], plan["checks"])


def health(plan):
    name = "reader.json" if "reader.json" in plan["files"] else "index.html"
    return {name: plan["files"][name]}


def completed_receipt(state):
    """The exact promotion record also proves an orphan belongs to this attempt."""
    result = {"schema_version": 1, "release_id": state["release_id"], "contract": state["contract"],
              "status": "published", "repositories": state["repositories"], "hub": state["repositories"]["hub"]["base"],
              "entrypoints": state.get("entrypoints", {topic: topic for topic, plan in state["repositories"].items()
                                                      if plan.get("role") != "partition"})}
    if "gate" in state:
        result["gate"] = state["gate"]
    return result


def rollback(root, state, path, host, refs, timing=None):
    hub = state["repositories"][state.get("hub_control", "hub")]
    repo = within(root, hub["path"])
    if state["rollback"] is None:
        target = publication_git.commit(repo, state["fallback"]["tree"], hub["pages"],
                                        f"Restore previous hub after release {state['release_id']}")
        pin(repo, target)
        state["rollback"] = target
        state["phase"] = "rolling-back"
        save(path, state)
    with measure(timing, "push_pages"):
        refs.push(host, repo, hub["name"], state["rollback"], "gh-pages")
    with measure(timing, "configure"):
        host.configure(hub["name"])
    with measure(timing, "pages_build"):
        host.wait(hub["name"], state["rollback"])
    with measure(timing, "verify"):
        host.verify(hub["base"], state["fallback"]["files"])
    state["phase"] = "rolled-back"
    save(path, state)


def execute(root, state, path, host, workers, refs, timing=None, validation=None):
    timing = timing if timing is not None else {"repositories": {}, "rollback": {}, "phases": {}}
    journal_lock = Lock()

    def journal(plan, transition):
        with journal_lock:
            plan["recovery"] = transition
            plan["pages"] = transition["successor"]
            save(path, state)

    def restore():
        identity = state.get("hub_control", "hub")
        row = repository_row(timing, "rollback", identity)
        with measure(timing["phases"], "rollback"), measure(row, "total"):
            rollback(root, state, path, host, refs, row)

    with measure(timing["phases"], "reconcile"):
        for topic, plan in state["repositories"].items():
            remote = host.repository(plan["name"])
            if not remote or remote["id"] != plan["repository_id"] or remote.get("private"):
                raise ContractError(f"Publication destination changed: {plan['name']}")
    # Storage is a dependency of every topic/front that references its bytes.
    # Complete independent workers within each phase before advertising the next.
    groups = state.get("groups") or [[topic for topic, plan in state["repositories"].items()
                                      if topic != "hub" and (plan.get("role") == "partition") == storage]
                                     for storage in (True, False)]
    for rank, identities in enumerate(groups):
        topics = {topic: state["repositories"][topic] for topic in identities if not state["repositories"][topic]["verified"]}
        errors = []
        with measure(timing["phases"], f"topics-{rank}"), ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(deploy, root, plan, host,
                       repository_row(timing, "repositories", topic), refs, journal, validation): plan
                       for topic, plan in topics.items()}
            for future in as_completed(pending):
                plan = pending[future]
                try:
                    future.result()
                    with journal_lock:
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
        if validation is not None:
            validation.promotion()
        try:
            row = repository_row(timing, "repositories", state.get("hub_control", "hub"))
            with measure(timing["phases"], "hub"):
                deploy(root, hub, host, row, refs, journal, validation)
            hub["verified"] = True
            save(path, state)
        except github_pages.BuildObservationError:
            # Unknown build outcome stays journaled, but the failed run is scrapped.
            raise
        except Exception:
            # Only our confirmed hub push permits a compensating commit.
            # The ref boundary is checked again before the rollback push.
            if (refs.confirmed.get((hub["name"], "gh-pages")) == hub["pages"]
                    and host.ref(hub["name"], "gh-pages") == hub["pages"]):
                restore()
            raise
    with measure(timing["phases"], "promote"):
        result = completed_receipt(state)
        receipt = within(root, f"publications/{state['release_id']}.json")
        if receipt.exists() and load(receipt) != result:
            raise ContractError("Immutable publication receipt differs")
        save(receipt, result)
        save(root / "publications/latest.json", {"release_id": state["release_id"]})
        state["phase"] = "complete"
        save(path, state)
    return result


def new_timing(lock=None):
    """Publication timing values; run and the rehearsal share this shape."""
    timing = run_timing.Values({"repositories": {}, "rollback": {}, "prepare": 0.0, "resume": 0.0},
                              lock=lock, clock=timing_clock)
    timing["phases"] = run_timing.Values(lock=timing.lock, clock=timing_clock)
    return timing


def run(root, project, manifest, *, host=None, progress=None, timing_sink=None):
    """Caller holds the shared OS writer lock. Production always passes the gate."""
    timing = new_timing(timing_sink.lock if timing_sink is not None else None)
    if timing_sink is not None:
        with timing.lock:
            timing_sink.publication = timing
    try:
        with measure(timing, "total"):
            with measure(timing, "gate"):
                refuse_pending(root)
                gate = publish_gate.check(root, project, manifest)
            result, metrics = _run(root, project, manifest, host, progress, timing, gate)
        return result, {**metrics, "timing": timing}
    except (Exception, KeyboardInterrupt) as exc:
        exc.publication_timing = timing
        raise


def _run(root, project, manifest, host, progress, timing, gate):
    refuse_pending(root)
    if not project.get("publication", {}).get("enabled", False):
        return {"status": "disabled"}, {"reused": True}
    host = host or github_pages.GitHubPages(project["github_owner"], progress)
    workers = project["publication"].get("workers", 4)
    path = root / ".local/publication/pending.json"
    refs = RehearsedRefs(gate["rehearsal"]["remote_refs"])
    refs.check(host, publish_gate.destinations(root, project, manifest))
    release.verify(root, manifest)
    validation = DestinationValidation(project["github_owner"], host,
                                       gate["rehearsal"].get("destination_observations", []))
    current = published(root)
    if current and current["release_id"] == manifest["release_id"]:
        def check_current(topic, plan):
            row = timing["repositories"][topic]
            with measure(row, "total"):
                check(plan, row)

        def check(plan, row):
            remote = host.repository(plan["name"])
            if not remote or remote["id"] != plan["repository_id"] or remote.get("private"):
                raise ContractError(f"Published destination changed: {plan['name']}")
            if host.ref(plan["name"], "main") != plan["main"] or host.ref(plan["name"], "gh-pages") != plan["pages"]:
                raise ContractError(f"Published branch changed: {plan['name']}")
            with measure(row, "configure"):
                validation.before(plan["name"])
                host.configure(plan["name"])
            with measure(row, "verify"):
                host.verify(plan["base"], health(plan))
        with timing.lock:
            timing["repositories"].update({topic: repository_timing(timing.lock) for topic in current["repositories"]})
        with measure(timing, "resume"), measure(timing["phases"], "current"), ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(check_current, current["repositories"], current["repositories"].values()))
        return current, {"reused": True}
    with measure(timing, "prepare"):
        state = prepare(root, project, manifest, host, refs, validation)
    state["gate"] = gate
    save(path, state)
    with measure(timing, "resume"):
        result = execute(root, state, path, host, workers, refs, timing, validation)
    return result, {"reused": False}
