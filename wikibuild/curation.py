"""Check optional committed explanations against selected, captured dependencies."""

from collections import defaultdict
import json
from pathlib import Path

from . import curated_rules as rules, extraction, model, snapshots
from .exceptions import Exceptions
from .source import Source
from .storage import ContractError, digest, git, json_bytes, within, write_changed


def contract():
    folder = Path(__file__).parent
    return {name: digest((folder / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in ("curation.py", "curated_rules.py", "source.py", "storage.py")}


def definitions(root, project):
    result = {}
    for repo in project["repositories"]:
        if "path" not in repo:
            continue
        checkout = within(root, repo["path"])
        folder = checkout / "curated"
        if not folder.exists():
            continue
        if folder.resolve() != folder or folder.is_symlink():
            raise ContractError("Curated definitions directory is redirected")
        if git(checkout, "status", "--porcelain=v1", "--untracked-files=all", "--", "curated"):
            raise ContractError(f"Commit curated definitions before generation: {repo['id']}")
        tracked = set(git(checkout, "ls-files", "-z", "--", "curated").split("\0"))
        for path in sorted(folder.rglob("*.json")):
            name = path.relative_to(checkout).as_posix()
            if name not in tracked or path.resolve() != path or path.is_symlink():
                raise ContractError(f"Untracked or redirected curated input: {repo['id']}/{name}")
            if path.stat().st_size > 32768:
                data, value, error = None, None, "Definition exceeds the 32 KiB record budget"
                sha = extraction.file_hash(path)
            else:
                data = path.read_bytes()
                sha = digest(data.replace(b"\r\n", b"\n"))
                value, error = None, None
                try:
                    value = rules.validate(json.loads(data))
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    error = str(exc)
                    value = None
            key = repo["id"] + "/" + name.removeprefix("curated/").removesuffix(".json")
            result[key] = {"topic": repo["id"], "path": name, "sha256": sha,
                           "definition": value, "error": error}
    return result


def read(root, identity):
    if not isinstance(identity, str) or len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
        raise ContractError("Invalid curated check identity")
    envelope = json.loads(within(root, f"curation/runs/{identity}.json").read_bytes())
    value = envelope["payload"]
    if (value.get("schema_version") != 1 or value.get("run_id") != identity
            or digest(json_bytes(value["inputs"])) != identity or digest(json_bytes(value)) != envelope["sha256"]):
        raise ContractError("Curated check receipt differs")
    return value


def definition_inputs(authored):
    return {key: {name: item[name] for name in ("topic", "path", "sha256")} for key, item in authored.items()}


def ensure_definitions(root, project, result):
    expected = result["inputs"]["definitions"] if result else {}
    if definition_inputs(definitions(root, project)) != expected:
        raise ContractError("Curated definitions changed during reader generation")


def activate(pointer, result):
    current = json.loads(pointer.read_bytes())["run_id"] if pointer.exists() else None
    if current in {result["run_id"], result["previous_run"]}:
        write_changed(pointer, json_bytes({"run_id": result["run_id"]}))
    elif current is None:
        raise ContractError("Curated last-result pointer is missing")
    # Historical results can be rendered without rewinding a newer diagnostic pointer.


def selected(root, run, active):
    wanted = defaultdict(set)
    for item in active.values():
        definition = item["definition"]
        if not definition:
            continue
        wanted[definition["entity"]]
        for spec in definition["facts"].values():
            wanted[spec.get("entity", definition["entity"])].add(spec["path"])
    if not wanted:
        return {}, 0
    path = extraction.artifact(root, run["models"])
    result = {}
    for row in model.rows(path):
        entity = row["entity_key"]
        if entity not in wanted:
            continue
        if entity in result:
            raise ContractError("Duplicate curated fact dependency entity")
        values = {}
        for field in wanted[entity]:
            try:
                values[field] = rules.pointer(row["semantic"]["facts"], field)
            except (KeyError, IndexError):
                pass
        result[entity] = {"topic": row["semantic"]["topic"], "values": values,
                          "source_id": row["provenance"]["source_id"],
                          "evidence": row["provenance"].get("evidence", [])}
    return result, path.stat().st_size


def code_hashes(source, run, active):
    paths = {dep["path"] for item in active.values() if item["definition"]
             for dep in item["definition"]["code"]}
    if not paths:
        return {}, 0
    result = {}
    with Source(source, run["source_commit"]) as inputs:
        for path in sorted(paths):
            if path not in inputs.blobs:
                result[path] = None
                continue
            with inputs.lines(path) as lines:
                for _ in lines:
                    pass
            result[path] = inputs.dependencies[path]["sha256"]
        return result, inputs.bytes_read


def evaluate(key, item, run, receipt, facts, codes, previous, identity, baseline_known):
    definition = item["definition"]
    entity = definition["entity"] if definition else (previous or {}).get("entity")
    title = definition["title"] if definition else (previous or {}).get("title", key)
    result = {"claim_key": key, "entity": entity, "topic": item["topic"], "title": title,
              "definition_sha256": item["sha256"], "snapshot_id": run["snapshot_id"],
              "scope": definition["scope"] if definition else "invalid-definition",
              "authored_source": {"topic": item["topic"], "path": item["path"], "sha256": item["sha256"]},
              "status": "unverified", "reasons": [], "checks": [], "text": None,
              "last_verified": (previous or {}).get("last_verified") if (previous or {}).get("entity") == entity else None}
    if not definition:
        result["reasons"].append("invalid-definition: " + item["error"])
        return result
    if not baseline_known:
        result["reasons"].append("starting-snapshot-not-captured")
    if entity not in facts or facts[entity]["topic"] != item["topic"]:
        result["reasons"].append("target-entry-missing-or-owned-by-another-topic")
    values = {}
    for name, spec in sorted(definition["facts"].items()):
        target = spec.get("entity", entity)
        observation = facts.get(target)
        check = {"fact": name, "entity": target, "field": spec["path"], "value_sha256": None}
        if observation is None or spec["path"] not in observation["values"]:
            reason = "fact-not-captured"
        else:
            value = observation["values"][spec["path"]]
            check.update(value_sha256=rules.value_hash(value), source_id=observation["source_id"], evidence=observation["evidence"])
            reason = rules.check(value, spec)
            if not reason:
                values[name] = value
        check["result"] = reason or "passed"
        result["checks"].append(check)
        if reason:
            result["reasons"].append(name + ": " + reason)
    for dep in definition["code"]:
        actual = codes[dep["path"]]
        check = {"code": dep["path"], "expected_sha256": dep["sha256"], "actual_sha256": actual,
                 "result": "passed" if actual == dep["sha256"] else "code-changed-or-missing"}
        result["checks"].append(check)
        if check["result"] != "passed":
            result["reasons"].append(dep["path"] + ": " + check["result"])
    if not result["reasons"]:
        try:
            result["text"] = rules.render(definition, values)
        except ContractError as exc:
            result["reasons"].append(str(exc))
            return result
        result["status"] = "passed"
        result["last_verified"] = {"snapshot_id": run["snapshot_id"], "build_id": receipt["steam"]["build_id"],
                                   "identity_run": run["run_id"], "check_run": identity,
                                   "definition_sha256": item["sha256"], "text": result["text"],
                                   "dependencies_sha256": digest(json_bytes(result["checks"]))}
    return result


def previous_check(candidates, order, snapshot):
    known = [prior for prior in candidates if prior and prior.get("last_verified")
             and prior["last_verified"]["snapshot_id"] in order
             and order[prior["last_verified"]["snapshot_id"]] <= order[snapshot]]
    return max(known, key=lambda prior: order[prior["last_verified"]["snapshot_id"]]) if known else next(
        (prior for prior in candidates if prior and not prior.get("last_verified")), None)


def run(root, project, source, runs):
    """Caller holds writer_lock. Content failures remain successful check results."""
    authored = definitions(root, project)
    metrics = {"reused": True, "source_bytes_read": 0, "model_bytes_read": 0, "snapshots_reused": 0}
    if not authored:
        return None, metrics
    inputs = {"definitions": definition_inputs(authored),
              "identity_runs": [digest(json_bytes(run)) for run in runs], "contract": contract(),
              "receipts": [digest(json_bytes(snapshots.read(root, run["snapshot_id"]))) for run in runs]}
    identity = digest(json_bytes(inputs))
    destination = within(root, f"curation/runs/{identity}.json")
    pointer = within(root, "curation/latest.json")
    if destination.exists():
        result = read(root, identity)
        activate(pointer, result)
        return result, metrics
    previous = read(root, json.loads(pointer.read_bytes())["run_id"]) if pointer.exists() else None
    order = {run["snapshot_id"]: number for number, run in enumerate(reversed(runs))}
    source_pin = None
    if any(item["definition"] and item["definition"]["code"] for item in authored.values()):
        source_pin = git(source, "rev-parse", "HEAD")
        extraction.ensure_source(source, source_pin)
    result = {"schema_version": 1, "run_id": identity, "inputs": inputs, "snapshots": {},
              "snapshot_inputs": {}, "previous_run": previous["run_id"] if previous else None}
    carried = {}
    issues = Exceptions()
    for captured in reversed(runs):
        snapshot = captured["snapshot_id"]
        active = {key: item for key, item in authored.items() if not item["definition"] or
                  item["definition"]["since"] not in order or order[snapshot] >= order[item["definition"]["since"]]}
        receipt = snapshots.read(root, snapshot)
        signature = digest(json_bytes([captured, receipt, definition_inputs(active), inputs["contract"],
                                      {key: bool(item["definition"] and item["definition"]["since"] in order)
                                       for key, item in active.items()}]))
        result["snapshot_inputs"][snapshot] = signature
        old = (previous or {}).get("snapshots", {}).get(snapshot, {})
        prior = {key: previous_check([old.get(key), carried.get(key)], order, snapshot) for key in active}
        reusable = (previous or {}).get("snapshot_inputs", {}).get(snapshot) == signature and set(old) == set(active)
        if reusable:
            reusable = all(record["status"] == "passed" or record["last_verified"] ==
                           (prior[key] or {}).get("last_verified") for key, record in old.items())
        if reusable:
            metrics["snapshots_reused"] += 1
        else:
            facts, count = selected(root, captured, active)
            metrics["model_bytes_read"] += count
            codes, count = code_hashes(source, captured, active)
            metrics["source_bytes_read"] += count
        records = {}
        for key, item in active.items():
            record = old[key] if reusable else evaluate(key, item, captured, receipt, facts, codes, prior[key], identity,
                              bool(item["definition"] and item["definition"]["since"] in order))
            records[key] = carried[key] = record
            if snapshot == runs[0]["snapshot_id"] and record["status"] != "passed":
                issues.add("curated-check-failed", item["topic"], key,
                           "Authored explanation checks did not pass; generated facts remain available.",
                           snapshot + "/" + "; ".join(record["reasons"]))
        result["snapshots"][snapshot] = records
    result["exceptions"] = issues.report()
    if contract() != inputs["contract"] or definitions(root, project) != authored:
        raise ContractError("Curated definitions or checker changed during processing")
    if source_pin:
        extraction.ensure_source(source, source_pin)
    data = json_bytes({"payload": result, "sha256": digest(json_bytes(result))})
    if destination.exists() and destination.read_bytes() != data:
        raise ContractError("Curated check receipt was changed during processing")
    write_changed(destination, data)
    read(root, identity)
    activate(pointer, result)
    metrics["reused"] = False
    return result, metrics
