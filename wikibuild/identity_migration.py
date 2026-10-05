"""Explicit, one-time correction of retained identity history. No update replay."""

from collections import defaultdict
import json
import io
from pathlib import Path

from . import extraction, history, identity, model
from .adapters.components import BY_CLASS, identity_rule
from .adapters.entries import definition_identity, expand
from .adapters.items_loot import observation
from .storage import ContractError, git, json_bytes, within, writer_lock


def validate_redirects(redirects, states):
    """Redirects are one-hop, evidenced, and never canonical allocations."""
    if set(redirects) & set(states):
        raise ContractError("Redirect sources intersect canonical identity keys")
    for source, proof in redirects.items():
        target = proof.get("entity_key")
        if target == source or target in redirects or target not in states or not proof.get("evidence"):
            raise ContractError("Conflicting or invalid identity redirect")


def read(root):
    path = within(root, "identity/migration.json")
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    payload = {key: value for key, value in record.items() if key != "migration_id"}
    if record.get("schema_version") != 1 or identity.fingerprint(payload) != record.get("migration_id"):
        raise ContractError("Immutable identity migration record mismatch")
    states = history.load_state(root, {"state": record["baseline"]})
    validate_redirects(record["redirects"], states)
    return record


def previous_state(root, previous, migration):
    if migration and previous and previous["run_id"] == migration["base_run"]:
        return history.load_state(root, {"state": migration["baseline"]})
    return history.load_state(root, previous)


def reader_inputs(root, run, migration, destination):
    """Apply recorded assignment repairs to packs, never to frozen history."""
    state = history.load_state(root, run)
    models = extraction.artifact(root, run["models"])
    repairs = {row["old_key"]: row for row in (migration or {}).get("repairs", []) if row["run_id"] == run["run_id"]}
    if not repairs:
        return state, models
    rekeys = {key: proof["entity_key"] for key, proof in repairs.items()}
    corrected = {key: row for key, row in state.items() if row["status"] != "present"
                 and key not in migration["redirects"]}
    seen = set()
    with destination.open("wb") as stream:
        for row in model.rows(models):
            old = row["entity_key"]
            if (old in seen or old not in state or state[old]["status"] != "present"
                    or row["revision_id"] != identity.fingerprint(row["semantic"])
                    or row["revision_id"] != state[old]["revision_id"]):
                raise ContractError("Retained reader model differs from its identity state")
            seen.add(old)
            key = rekeys.get(old, old)
            for relation in row["semantic"]["relationships"]:
                for field in ("targets", "technical_targets"):
                    if field in relation:
                        relation[field] = sorted({rekeys.get(target, target) for target in relation[field]})
            for target in row["provenance"].get("resolved_targets", []):
                if "target_entity" in target:
                    target["target_entity"] = rekeys.get(target["target_entity"], target["target_entity"])
            row["entity_key"], row["revision_id"] = key, identity.fingerprint(row["semantic"])
            corrected[key] = {**state[old], "entity_key": key, "revision_id": row["revision_id"],
                              **({"first_seen": repairs[old]["origin"]["snapshot_id"],
                                  "decision": repairs[old]["evidence"]["decision"]} if old in repairs else {})}
            history.write_row(stream, row)
    if seen != {key for key, row in state.items() if row["status"] == "present"}:
        raise ContractError("Retained reader model omitted an identity observation")
    return corrected, destination


def retained_runs(root):
    runs, seen = [], set()
    current = history.latest(root)
    while current:
        if current["run_id"] in seen:
            raise ContractError("Cyclic retained identity ancestry")
        seen.add(current["run_id"])
        # The operator migration requires every retained model, unlike updates.
        extraction.artifact(root, current["models"])
        runs.append(current)
        current = history.read(root, current["parent_run"]) if current["parent_run"] else None
    if not runs:
        raise ContractError("No identity baseline to migrate")
    return list(reversed(runs))


def observations(root, run):
    for frozen in model.rows(extraction.artifact(root, run["models"])):
        yield frozen, {**frozen["semantic"], **frozen["provenance"]}


def repair_capture(run, rows, metadata, previous, redirects):
    """Pure chronological step; seed first appearances with their recorded keys."""
    capture = identity.CaptureIndex(metadata, previous)
    current, frozen, parents, missing_parents = {}, {}, set(), {}
    for stored, row in rows:
        key = row["observation_key"]
        if key in current:
            raise ContractError("Duplicate retained observation")
        current[key] = identity.describe(row, metadata, capture)
        frozen[key] = stored
        if not row.get("parent_source_id"):
            parents.add(row["source_id"])
        rule = identity_rule(row.get("component", {}))
        definition = row.get("definition_identity") or definition_identity(row, rule)
        if definition and definition["type"] == "skill":
            missing_parents[row["parent_source_id"]] = row
    for parent in missing_parents.keys() - parents:
        row = missing_parents[parent]
        spec = BY_CLASS.get((row["component"].get("assembly"), row["component"].get("class")))
        if spec:
            container = observation(spec.kind, parent, metadata.get(parent, {}).get("name") or spec.name,
                                    {}, row["evidence"][0]["path"], ())
            container.update(topic=spec.topic, component=row["component"], notes=spec.notes)
            container = next(expand(container, {}, {}))
            current[container["observation_key"]] = identity.describe(container, metadata, capture)
    allocations = {key: stored["entity_key"] for key, stored in frozen.items()}
    assignments, decisions = identity.reconcile(current, previous, run["snapshot_id"], run["run_id"],
        same_capture=bool(previous and all(state["last_seen"] == run["snapshot_id"]
                                         for state in previous.values() if state["status"] == "present")),
        reserved=redirects, allocations=allocations)
    states = {}
    for key, entity in assignments.items():
        prior = previous.get(entity)
        stored = frozen.get(key, {})
        revision = stored.get("revision_id")
        changed = not prior or prior["revision_id"] != revision
        states[entity] = {"entity_key": entity, "descriptor": current[key], "revision_id": revision,
            "status": "present", "first_seen": prior["first_seen"] if prior else run["snapshot_id"],
            "last_seen": run["snapshot_id"], "last_data_checked": run["snapshot_id"], "last_verified": None,
            "last_changed": run["snapshot_id"] if changed else prior["last_changed"], "decision": decisions[key]}
    kinds = {row["kind"] for row in current.values()}
    for entity, state in previous.items():
        if entity not in states:
            states[entity] = {**state, "status": model.absent_status(state, kinds, metadata, capture=capture)}
    return states, assignments, decisions, current, frozen


def plan(root, source, progress=None):
    """Read-only planner. Historical states and models are never rewritten."""
    runs = retained_runs(root)
    contract_hash = history.contract()
    corrections_hash = identity.fingerprint(history.corrections(root))
    needed = defaultdict(set)
    for run in runs:
        for _, row in observations(root, run):
            needed[run["source_commit"]].update(model.source_ids(row))
    metadata, states, redirects, repairs, origins = {}, {}, {}, [], {}
    for ordinal, run in enumerate(runs):
        revision = run["source_commit"]
        if revision not in metadata:
            metadata[revision] = history.relevant_metadata(source, revision, needed[revision])[0]
        prior = states
        states, assignments, decisions, current, frozen = repair_capture(
            run, observations(root, run), metadata[revision], prior, redirects)
        for entity, recorded in history.load_state(root, run).items():
            if recorded["status"] == "superseded" and entity in states and states[entity]["status"] != "present":
                states[entity] = recorded
        for key, stored in frozen.items():
            old, target = stored["entity_key"], assignments[key]
            origins.setdefault(target, {"run_id": run["run_id"], "snapshot_id": run["snapshot_id"]})
            if old == target:
                continue
            decision = decisions[key]
            proof = {"entity_key": target, "topic": current[key]["topic"], "run_id": run["run_id"],
                     "snapshot_id": run["snapshot_id"], "observation_key": key, "source_id": current[key]["source_id"],
                     "origin": origins[target], "evidence": {"anchor": current[key].get("anchor"), "decision": decision}}
            repairs.append({"old_key": old, **proof})
            # A reused historical canonical key is a bad assignment, not a URL redirect.
            # First appearances remain canonical, including coexisting identical values.
            if old not in states and old not in origins and decision["status"] == "matched" and current[key].get("anchor"):
                if old in redirects and redirects[old]["entity_key"] != target:
                    continue  # Later reuse is already recorded above, never changes the map.
                redirects.setdefault(old, proof)
        validate_redirects(redirects, states)
        if progress:
            progress({"run": ordinal + 1, "total": len(runs), "redirects": len(redirects), "repairs": len(repairs)})
    return {"schema_version": 1, "base_run": runs[-1]["run_id"], "contract_sha256": contract_hash,
            "corrections_sha256": corrections_hash,
            "runs": [run["run_id"] for run in runs], "redirects": redirects, "repairs": repairs}, states


def require_clean(root, project):
    paths = [Path(root)] + [within(root, repo["path"]) for repo in project.get("repositories", [])]
    for path in paths:
        if path.exists() and git(path, "--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=all"):
            raise ContractError(f"Identity migration requires a clean workspace: {path}")


def run(root, source, project, dry_run=False):
    if dry_run:
        existing = read(root)
        if existing:
            return {"migration": existing, "reused": True}
        record, states = plan(root, source)
        return {"dry_run": True, "migration": record, "canonical_keys": len(states)}
    with writer_lock(root):
        require_clean(root, project)
        existing = read(root)
        if existing:
            return {"migration": existing, "reused": True}
        record, states = plan(root, source)
        require_clean(root, project)
        record = dict(record)
        # Hash-addressed baseline first; activation is the immutable record, written last.
        stream = io.BytesIO()
        for key in sorted(states):
            history.write_row(stream, states[key])
        data = stream.getvalue()
        sha = identity.digest(data)
        baseline = {"path": f"identity/states/{sha}.jsonl", "bytes": len(data), "sha256": sha}
        record["baseline"] = baseline
        record["migration_id"] = identity.fingerprint(record)
        if (history.latest(root)["run_id"] != record["base_run"] or history.contract() != record["contract_sha256"]
                or identity.fingerprint(history.corrections(root)) != record["corrections_sha256"]):
            raise ContractError("Identity migration inputs changed before activation")
        history.immutable(within(root, baseline["path"]), data)
        history.immutable(within(root, "identity/migration.json"), json_bytes(record))
        read(root)
        return {"migration": record, "reused": False}
