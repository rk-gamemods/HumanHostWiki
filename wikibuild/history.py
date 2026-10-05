"""Durable identity decisions and reusable normalized staging, under the writer lock."""

from collections import Counter
import io
import json
import os
from pathlib import Path
import re
import uuid

from . import extraction, identity, model
from . import staging as staging_attempts
from .exceptions import Exceptions
from .source import Source
from .source_record import read_record
from .storage import ContractError, digest, json_bytes, within, write_changed


def immutable(path, data):
    if path.exists() and path.read_bytes() != data:
        raise ContractError(f"Immutable identity artifact differs: {path.name}")
    write_changed(path, data)


def install(root, temporary, namespace):
    sha = extraction.file_hash(temporary)
    relative = f"{namespace}/{sha}.jsonl"
    destination = within(root, relative)
    record = {"path": relative, "sha256": sha, "bytes": temporary.stat().st_size}
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        extraction.artifact(root, record)
        temporary.unlink()
    else:
        os.rename(temporary, destination)
    return record


def contract():
    folder = Path(__file__).parent
    return digest(json_bytes({name: digest((folder / name).read_bytes().replace(b"\r\n", b"\n"))
                             for name in ("identity.py", "model.py", "history.py", "storage.py", "exceptions.py", "source.py")}))


def corrections(root):
    path = within(root, "identity/corrections.json")
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "mappings": []}
    if data.get("schema_version") != 1 or not isinstance(data.get("mappings"), list):
        raise ContractError("Invalid reviewed identity corrections")
    return data


def read(root, run_id, require_models=True):
    if not isinstance(run_id, str) or len(run_id) != 64 or any(c not in "0123456789abcdef" for c in run_id):
        raise ContractError("Invalid identity run identifier")
    result = json.loads(within(root, f"identity/runs/{run_id}.json").read_text(encoding="utf-8"))
    if result.get("schema_version") != 1 or result.get("run_id") != run_id or identity.fingerprint([result["request_key"], result["parent_run"]]) != run_id:
        raise ContractError("Identity run schema or identity mismatch")
    for key in ("state", "models") if require_models else ("state",):
        extraction.artifact(root, result[key])
    return result


def latest(root):
    pointer = within(root, "identity/latest.json")
    return read(root, json.loads(pointer.read_text())["run_id"], require_models=False) if pointer.exists() else None


def load_state(root, run):
    states = {}
    if run:
        for row in model.rows(extraction.artifact(root, run["state"])):
            if row["entity_key"] in states:
                raise ContractError("Duplicate entity in identity state")
            states[row["entity_key"]] = row
    return states


def same_inputs(receipt, previous):
    return bool(previous and receipt["steam"] == previous["input_identity"]["steam"]
                and receipt["input_inventory_git_blob"] == previous["input_identity"]["inventory"])


def write_row(stream, row):
    stream.write((json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode())


def context_records(inputs, catalog):
    """Read only hierarchy objects and script reference context, in shard order."""
    by_path = {}
    for key in catalog:
        by_path.setdefault(Source.object_path(key), set()).add(key)
    result = {}
    identifier = re.compile(rb'"id": ("(?:[^"\\]|\\.)*")')
    for path, wanted in sorted(by_path.items()):
        if hasattr(inputs, "blobs") and path not in inputs.blobs:
            continue
        with inputs.lines(path) as lines:
            for line in lines:
                # Canonical catalog records put id after fields. References and
                # script descriptors have no id member. Check the decoded id too.
                matches = list(identifier.finditer(line))
                key = json.loads(matches[-1][1]) if matches else None
                if key not in wanted:
                    continue
                entry = catalog[key]
                fields = {"m_GameObject"}
                if (entry.get("assembly"), entry.get("class")) == ("UI", "Slot_Info"):
                    fields.add("_slotIndex")
                if (entry.get("assembly"), entry.get("class")) == ("Language", "Language_Text"):
                    fields.add("_Infos")
                location = entry.get("record")
                row = read_record(io.BytesIO(line).read, location, fields) if location else json.loads(line)
                if not row or row.get("id") != key or row.get("type") != entry["type"]:
                    raise ContractError("Hierarchy/reference context differs from the pinned object index")
                if entry["type"] == "MonoBehaviour" and row.get("script", {}) != {"assembly": entry.get("assembly"), "class": entry.get("class")}:
                    # Some captured script descriptors carry additional locators.
                    script = row.get("script", {})
                    if (script.get("assembly"), script.get("class")) != (entry.get("assembly"), entry.get("class")):
                        continue
                values = row.get("fields", {})
                result[key] = {"fields": values if isinstance(values, dict) else {}, "references": row.get("references", [])}
                if entry["type"] == "MonoBehaviour":
                    result[key]["fields"] = {name: value for name, value in result[key]["fields"].items() if name in fields}
    return result


def contextual_metadata(inputs, metadata):
    containers = {key.split("#", 1)[0] for key, row in metadata.items()
                  if (row.get("assembly"), row.get("class")) == ("UI", "Slot_Info")
                  or ((row.get("assembly"), row.get("class")) == ("Language", "Language_Text")
                      and row.get("anchor_count", 1) > 1)}
    if not containers:
        return
    catalog = {entry["id"]: entry for entry in inputs.records("Catalog/views/object-index.jsonl")
               if entry["id"].split("#", 1)[0] in containers
               and entry["type"] in {"MonoBehaviour", "GameObject", "Transform", "RectTransform"}}
    records = context_records(inputs, catalog)
    counts = Counter(identity.fingerprint(anchor) for key, row in catalog.items()
                     if (anchor := identity.typed_anchor(key, row)))
    for key, row in catalog.items():
        if row["type"] != "MonoBehaviour":
            continue
        metadata[key] = {name: row[name] for name in ("type", "assembly", "class", "name", "paths") if name in row}
        anchor = identity.typed_anchor(key, row)
        if anchor:
            metadata[key]["anchor_count"] = counts[identity.fingerprint(anchor)]
    transforms = {}
    for key, row in records.items():
        if catalog[key]["type"] in {"Transform", "RectTransform"}:
            for ref in row["references"]:
                if ref.get("field") == "/m_GameObject" and ref.get("status") == "resolved":
                    transforms.setdefault(ref.get("target"), []).append(key)
    hierarchies, active = {}, set()

    def hierarchy(transform):
        if transform in hierarchies:
            return hierarchies[transform]
        if transform in active or transform not in records:
            return None
        active.add(transform)
        row = records[transform]
        owners = [ref.get("target") for ref in row["references"]
                  if ref.get("field") == "/m_GameObject" and ref.get("status") == "resolved"]
        result = None
        if len(owners) == 1:
            owner = owners[0]
            name = catalog.get(owner, {}).get("name")
            components = [ref.get("target") for ref in records.get(owner, {}).get("references", [])
                          if ref.get("field", "").startswith("/m_Component/") and ref.get("status") == "resolved"]
            father = [ref for ref in row["references"] if ref.get("field") == "/m_Father"]
            root = row["fields"].get("m_Father", {})
            if isinstance(name, str) and name and transform in components:
                if isinstance(root, dict) and root.get("m_PathID") == 0 and all(ref.get("status") == "null" for ref in father):
                    result = ([name], [None])
                elif len(father) == 1 and father[0].get("status") == "resolved":
                    parent = father[0].get("target")
                    ancestry = hierarchy(parent)
                    positions = [ref["field"].rsplit("/", 1)[1] for ref in records.get(parent, {}).get("references", [])
                                 if ref.get("field", "").startswith("/m_Children/")
                                 and ref.get("target") == transform and ref.get("status") == "resolved"]
                    if ancestry and len(positions) == 1 and positions[0].isdigit():
                        result = (ancestry[0] + [name], ancestry[1] + [int(positions[0])])
        active.remove(transform)
        hierarchies[transform] = result
        return result

    for key, row in records.items():
        if catalog[key]["type"] != "MonoBehaviour" or key not in metadata:
            continue
        target = metadata[key]
        owners = [ref.get("target") for ref in row["references"]
                  if ref.get("field") == "/m_GameObject" and ref.get("status") == "resolved"]
        if len(owners) == 1 and len(transforms.get(owners[0], [])) == 1:
            owner_path = hierarchy(transforms[owners[0]][0])
            if owner_path:
                target["hierarchy"], target["hierarchy_ordinals"] = owner_path
        if (target.get("assembly"), target.get("class")) == ("UI", "Slot_Info"):
            target["slot_index"] = row["fields"].get("_slotIndex")
        if (target.get("assembly"), target.get("class")) == ("Language", "Language_Text"):
            infos = row["fields"].get("_Infos", [])
            texts = {info.get("text") for info in (infos if isinstance(infos, list) else [])
                     if isinstance(info, dict) and info.get("languageType") == 2 and isinstance(info.get("text"), str)}
            if len(texts) == 1:
                target["text"] = next(iter(texts))
    for caller, row in records.items():
        if catalog[caller]["type"] != "MonoBehaviour":
            continue
        metadata[caller]["reference_roles"] = [{"source_field": ref["field"], "status": ref.get("status"),
                                               "targets": ref.get("targets", [ref["target"]] if ref.get("target") else [])}
                                              for ref in row["references"]]
        for ref in row["references"]:
            if ref.get("status") != "resolved":
                continue
            for target in ref.get("targets", [ref["target"]] if ref.get("target") else []):
                record = metadata.get(target, {})
                if (record.get("assembly"), record.get("class")) == ("Language", "Language_Text"):
                    record.setdefault("callers", []).append({"source_id": caller, "source_field": ref["field"]})


def relevant_metadata(source, revision, needed):
    metadata = {}
    with Source(source, revision) as inputs:
        for entry in inputs.records("Catalog/views/object-index.jsonl"):
            if entry["id"] in needed:
                metadata[entry["id"]] = {key: entry[key] for key in ("type", "assembly", "class", "name", "paths") if key in entry}
        # Count only relevant anchors, but against the complete pinned catalog.
        # An unselected namesake must not make two relationship targets equal.
        counts = dict.fromkeys((identity.fingerprint(anchor) for key, record in metadata.items()
                                if (anchor := identity.typed_anchor(key, record))), 0)
        if counts:
            for entry in inputs.records("Catalog/views/object-index.jsonl"):
                anchor = identity.typed_anchor(entry["id"], entry)
                key = identity.fingerprint(anchor) if anchor else None
                if key in counts:
                    counts[key] += 1
            for key, record in metadata.items():
                anchor = identity.typed_anchor(key, record)
                if anchor:
                    record["anchor_count"] = counts[identity.fingerprint(anchor)]
        contextual_metadata(inputs, metadata)
        return metadata, inputs.bytes_read


def restore_models(root, source, observations, extracted, prepared):
    """Rebuild missing staging from frozen decisions; never rerun matching."""
    path = within(root, prepared["models"]["path"])
    if path.exists():
        extraction.artifact(root, prepared["models"])
        return 0
    state = load_state(root, prepared)
    by_observation = {row["descriptor"]["observation_key"]: row for row in state.values() if row["status"] == "present"}
    assignments = {key: row["entity_key"] for key, row in by_observation.items()}
    needed = {key for row in model.rows(observations) for key in model.source_ids(row)}
    metadata, source_bytes = relevant_metadata(source, prepared["source_commit"], needed)
    indexes = model.targets_index(model.rows(observations), assignments)
    temporary = within(root, ".local/history/repair/" + uuid.uuid4().hex + ".jsonl")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("wb") as stream:
        for row in model.rows(observations):
            key = row["observation_key"]
            projected = model.project(row, assignments[key], indexes, metadata, extracted["dependencies"], Exceptions())
            projected["snapshot_id"] = prepared["snapshot_id"]
            projected["identity_decision"] = by_observation[key]["decision"]
            write_row(stream, projected)
    if extraction.file_hash(temporary) != prepared["models"]["sha256"]:
        raise ContractError("Rebuilt staging differs from the accepted identity run; preserved for investigation")
    install(root, temporary, ".local/history/objects")
    return source_bytes


def run(root, source, receipt, extracted):
    """Caller holds writer_lock. No publication or page-verification side effect."""
    extraction.ensure_source(source, receipt["source_commit"])
    if extracted["source_commit"] != receipt["source_commit"] or extracted["snapshot_id"] != receipt["snapshot_id"]:
        raise ContractError("Extraction and identity inputs name different snapshots")
    observations = extraction.artifact(root, extracted["records"])
    reviewed = corrections(root)
    contract_hash = contract()
    request_key = identity.fingerprint([receipt["snapshot_id"], extracted["run_id"], extracted["records"]["sha256"], contract_hash, reviewed])
    request_path = within(root, f"identity/requests/{request_key}.json")
    pointer = within(root, "identity/latest.json")
    previous = latest(root)
    parent_id = previous["run_id"] if previous else None
    if request_path.exists():
        prepared = read(root, json.loads(request_path.read_text())["run_id"], require_models=False)
        if prepared["request_key"] != request_key:
            raise ContractError("Identity request receipt mismatch")
        if parent_id not in {prepared["parent_run"], prepared["run_id"]}:
            raise ContractError("An earlier identity request cannot rewind later decisions")
        source_bytes = restore_models(root, source, observations, extracted, prepared)
        extraction.ensure_source(source, receipt["source_commit"])
        write_changed(pointer, json_bytes({"run_id": prepared["run_id"]}))
        staging_attempts.retire(Path(root) / ".local/history/staging", "history")
        return prepared, {"reused": True, "source_bytes_read": source_bytes}

    run_id = identity.fingerprint([request_key, parent_id])
    old = load_state(root, previous)
    needed = {state["descriptor"]["source_object"] for state in old.values()}
    for row in model.rows(observations):
        needed.update(model.source_ids(row))
    metadata, source_bytes = relevant_metadata(source, receipt["source_commit"], needed)
    anchors = identity.target_anchors(metadata)
    descriptors = {}
    for row in model.rows(observations):
        key = row["observation_key"]
        if key in descriptors:
            raise ContractError("Duplicate observation in identity input")
        descriptors[key] = identity.describe(row, metadata, anchors)
    unchanged_inputs = same_inputs(receipt, previous)
    assignments, decisions = identity.reconcile(descriptors, old, receipt["snapshot_id"], request_key,
                                               same_capture=unchanged_inputs, corrections=reviewed["mappings"])
    supersessions = identity.reviewed_supersessions(descriptors, old, assignments, receipt["snapshot_id"], reviewed["mappings"])
    indexes = model.targets_index(model.rows(observations), assignments)
    issues, states, counts = Exceptions(), {}, Counter()
    with staging_attempts.attempt(Path(root) / ".local/history/staging", "history") as staging:
        with (staging / "models.jsonl").open("wb") as stream:
            for row in model.rows(observations):
                key = row["observation_key"]
                entity = assignments[key]
                projected = model.project(row, entity, indexes, metadata, extracted["dependencies"], issues)
                prior = old.get(entity)
                changed = not prior or prior["revision_id"] != projected["revision_id"]
                counts["new" if not prior else "changed" if changed else "unchanged"] += 1
                decision = decisions[key]
                if decision["status"] == "ambiguous":
                    counts["ambiguous"] += 1
                    issues.add("ambiguous-identity", row["topic"], row["kind"],
                               "Identity candidates are unresolved; this observation retains a separate wiki key.", row["source_id"])
                states[entity] = {"entity_key": entity, "descriptor": descriptors[key], "revision_id": projected["revision_id"],
                                  "status": "present", "first_seen": prior["first_seen"] if prior else receipt["snapshot_id"],
                                  "last_seen": receipt["snapshot_id"], "last_changed": receipt["snapshot_id"] if changed else prior["last_changed"],
                                  "last_data_checked": receipt["snapshot_id"], "last_verified": None, "decision": decision}
                projected["snapshot_id"] = receipt["snapshot_id"]
                projected["identity_decision"] = decision
                write_row(stream, projected)
        ambiguous_old = {candidate for decision in decisions.values() if decision["status"] == "ambiguous" for candidate in decision["candidates"]}
        current_by_observation = {state["descriptor"]["observation_key"]: entity for entity, state in states.items()}
        for entity, state in old.items():
            if entity in states:
                continue
            if state["status"] == "superseded":
                states[entity] = state
                continue
            observation = state["descriptor"]["observation_key"]
            replacement = supersessions.get(entity) or current_by_observation.get(observation)
            if entity in supersessions or (replacement and decisions[observation]["status"] == "reviewed"):
                status = "superseded"
            elif entity in ambiguous_old:
                status = "unresolved"
            else:
                status = model.absent_status(state, extracted["supported_kinds"], metadata)
            states[entity] = {**state, "status": status,
                              **({"superseded_by": replacement} if status == "superseded" else {})}
            if status == "unresolved":
                descriptor = state["descriptor"]
                issues.add("unresolved-observation", descriptor["topic"], descriptor["kind"],
                           "A prior observation is absent but its source object remains; review the extraction or identity change.",
                           descriptor["source_id"])
            if status != state["status"]:
                counts[status] += 1
        with (staging / "state.jsonl").open("wb") as stream:
            for entity in sorted(states):
                write_row(stream, states[entity])
        result = {"schema_version": 1, "run_id": run_id, "request_key": request_key, "parent_run": parent_id,
                  "snapshot_id": receipt["snapshot_id"], "source_commit": receipt["source_commit"],
                  "extraction_run": extracted["run_id"], "contract_sha256": contract_hash,
                  "input_identity": {"steam": receipt["steam"], "inventory": receipt["input_inventory_git_blob"]},
                  "corrections_sha256": identity.fingerprint(reviewed),
                  "change_origin": ("initial" if not previous else "game-input-change" if not unchanged_inputs else
                                    "identity-correction" if previous.get("corrections_sha256") != identity.fingerprint(reviewed) else "extractor-correction"),
                  "state": install(root, staging / "state.jsonl", "identity/states"),
                  "models": install(root, staging / "models.jsonl", ".local/history/objects"),
                  "counts": dict(sorted(counts.items())), "exceptions": issues.report(),
                  "verification": "selected-data-only; gameplay and pages not verified", "wiki_release": "not-created"}
        extraction.ensure_source(source, receipt["source_commit"])
        extraction.artifact(root, extracted["records"])
        if contract() != contract_hash or corrections(root) != reviewed:
            raise ContractError("Identity rules changed during generation; previous pointer preserved")
        immutable(within(root, f"identity/runs/{run_id}.json"), json_bytes(result))
        read(root, run_id)
        immutable(request_path, json_bytes({"run_id": run_id}))
        write_changed(pointer, json_bytes({"run_id": run_id}))
        return result, {"reused": False, "source_bytes_read": source_bytes}
