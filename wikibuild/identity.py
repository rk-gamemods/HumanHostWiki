"""Pure, conservative identity reconciliation. No filesystem or network access."""

from collections import Counter, defaultdict

from .storage import ContractError, digest, json_bytes


def fingerprint(value):
    return digest(json_bytes(value))


def typed_anchor(source_id, record):
    """Use catalog evidence, never a display label or a Unity script path ID."""
    if not record or "#" not in source_id or not record.get("type"):
        return None
    engine_type = record["type"]
    assembly, cls = record.get("assembly"), record.get("class")
    if engine_type in {"MonoBehaviour", "MonoScript"} and not (assembly and cls):
        return None
    if engine_type == "MonoScript":
        name = cls
    else:
        name = record.get("name")
    if not isinstance(name, str) or not name:
        return None
    return {"container": source_id.split("#", 1)[0], "engine_type": engine_type,
            "assembly": assembly, "class": cls, "asset_name": name}


def target_anchors(metadata):
    """Only independently unique catalog targets can replace build-scoped IDs."""
    anchors = {key: typed_anchor(key, record) for key, record in metadata.items()}
    counts = Counter(fingerprint(anchor) for anchor in anchors.values() if anchor)
    return {key: anchor for key, anchor in anchors.items() if anchor
            and counts[fingerprint(anchor)] == 1 and metadata[key].get("anchor_count", 1) == 1}


def relationship_signature(link, anchors):
    targets = link.get("target_source_ids", [link["target_source_id"]] if link.get("target_source_id") else [])
    status, guid = link.get("status"), link.get("guid")
    if status not in {None, "resolved"}:
        return {"status": status, "source_ids": sorted(targets), **({"guid": guid} if guid else {})}
    if guid:
        return {"guid": guid, "status": "resolved" if targets else "unresolved-target"}
    if not targets:
        return {"status": "unresolved", "source_ids": []}
    return {"targets": sorted([{"anchor": anchors[target]} if target in anchors else
                               {"status": "unresolved-target", "source_id": target}
                               for target in targets], key=fingerprint)}


def describe(row, metadata, anchors=None):
    identity = row["source_id"]
    paths = set(row.get("asset_paths", []))
    for key in [identity, row.get("parent_source_id"), *row.get("game_objects", [])]:
        paths.update(metadata.get(key, {}).get("paths", []))
    summary = row.get("fact_scope") == "catalog-type-summary"
    component = row.get("component", {})
    base = row.get("source_field_base", "")
    if anchors is None:
        anchors = target_anchors(metadata)
    references = []
    for link in row.get("relationships", []):
        if link["predicate"] == "defined-by":
            continue
        field = link.get("source_field", "")
        if base and (field == base or field.startswith(base + "/")):
            field = field[len(base):]
        references.append([link["predicate"], field, relationship_signature(link, anchors)])
    return {"observation_key": row["observation_key"], "source_id": identity,
            "source_object": row.get("parent_source_id", identity).split("/tag/", 1)[0],
            "kind": row["kind"], "topic": row["topic"],
            "family": "catalog-type" if summary else "source-enumeration" if row.get("fact_scope") == "source-enumeration" else row["kind"],
            "component": [component.get("assembly"), component.get("class")],
            "scope": identity.split("#", 1)[0] if "#" in identity else "catalog-summary",
            "name": row["name"], "facts_hash": fingerprint([row["facts"], sorted(references, key=fingerprint)]),
            "has_facts": bool(row["facts"] or references),
            "paths": sorted(paths), "summary": summary,
            "anchor": None if summary or row.get("parent_source_id") else anchors.get(identity)}


def compatible(left, right):
    return left["family"] == right["family"] and left["component"] == right["component"]


def indexes(previous):
    result = {key: defaultdict(set) for key in ("source", "path", "content", "name", "anchor")}
    for entity, state in previous.items():
        if state.get("status") == "superseded":
            continue
        row = state["descriptor"]
        family = (row["family"], tuple(row["component"]))
        result["source"][(family, row["source_id"])].add(entity)
        result["name"][(family, row["scope"], row["name"])].add(entity)
        if row.get("anchor"):
            result["anchor"][(family, fingerprint(row["anchor"]))].add(entity)
        for path in row["paths"]:
            result["path"][(family, path)].add(entity)
        if row["has_facts"]:
            result["content"][(family, row["scope"], row["name"], row["facts_hash"])].add(entity)
    return result


def candidate_rules(current, previous, index, same_capture, anchor_counts=None):
    family = (current["family"], tuple(current["component"]))
    levels = defaultdict(dict)
    anchored = set()
    if current.get("anchor"):
        anchor_key = (family, fingerprint(current["anchor"]))
        anchored = index["anchor"].get(anchor_key, set())
        if anchor_counts and anchor_counts[anchor_key] == 1 and len(anchored) == 1:
            entity = next(iter(anchored))
            levels[4][entity] = ["unique-typed-anchor", "container-and-engine-type", "assembly-and-class", "catalog-asset-name"]
    direct = index["source"].get((family, current["source_id"]), set())
    for entity in direct:
        state = previous[entity]
        old = state["descriptor"]
        evidence = ["scoped-source-id", "kind-and-component"]
        if same_capture and state["status"] == "present" and old["observation_key"] == current["observation_key"]:
            evidence.append("same-captured-game-inputs")
            levels[5][entity] = evidence
            continue
        elif current["paths"] and old["paths"] and set(current["paths"]).isdisjoint(old["paths"]) and current["facts_hash"] != old["facts_hash"]:
            continue
        elif current["name"] == old["name"]:
            evidence.append("unchanged-name")
        elif current["has_facts"] and old["facts_hash"] == current["facts_hash"]:
            evidence.append("unchanged-selected-facts")
        else:
            continue
        levels[3 if state["status"] == "present" else 2][entity] = evidence
    for path in current["paths"]:
        for entity in index["path"].get((family, path), set()):
            old = previous[entity]["descriptor"]
            if current["name"] == old["name"] or (current["has_facts"] and current["facts_hash"] == old["facts_hash"]):
                levels[2][entity] = ["asset-path", path, "kind-and-component",
                                     "unchanged-name" if current["name"] == old["name"] else "unchanged-selected-facts"]
    if current["has_facts"]:
        for entity in index["content"].get((family, current["scope"], current["name"], current["facts_hash"]), set()):
            levels[1][entity] = ["container", "kind-and-component", "unchanged-name-and-selected-facts"]
    return levels, direct | anchored | index["name"].get((family, current["scope"], current["name"]), set())


def reconcile(current, previous, snapshot, request_key, same_capture=False, corrections=()):
    """Reserve stronger unique matches first; leave all ties explicit."""
    index = indexes(previous)
    anchor_counts = Counter(((row["family"], tuple(row["component"])), fingerprint(row["anchor"]))
                            for row in current.values() if row.get("anchor"))
    proposals, direct, assignments, decisions, used = {}, {}, {}, {}, set()
    for observation, row in sorted(current.items()):
        proposals[observation], direct[observation] = candidate_rules(row, previous, index, same_capture, anchor_counts)

    reviewed = {}
    for correction in corrections:
        if correction.get("snapshot_id") != snapshot:
            continue
        key = correction.get("observation_key")
        if key not in current or key in reviewed or not correction.get("reviewer") or not correction.get("reason"):
            raise ContractError("Invalid, duplicate or stale reviewed identity mapping")
        target = correction.get("entity_key")
        if target != "new" and (target not in previous or not compatible(current[key], previous[target]["descriptor"])):
            raise ContractError("Reviewed identity mapping names an absent or incompatible entity")
        reviewed[key] = correction
        # A reviewed allocation survives unrelated rule/contract changes.
        entity = target if target != "new" else "e-" + fingerprint([snapshot, key, "reviewed-new"])[:32]
        if entity in used:
            raise ContractError("Reviewed identity mappings assign multiple observations to one entity")
        if target == "new" and entity in previous and previous[entity]["descriptor"]["observation_key"] != key:
            raise ContractError("Reviewed identity allocation collides with another observation")
        assignments[key] = entity
        used.add(entity)
        decisions[key] = {"status": "reviewed", "rule": "reviewed-mapping", "confidence": "reviewed",
                          "reviewer": correction["reviewer"], "reason": correction["reason"], "candidates": sorted(direct[key])}

    for level in (5, 4, 3, 2, 1):
        choices = {key: values[level] for key, values in proposals.items()
                   if key not in assignments and level in values and level == max(values)}
        claims = Counter(entity for values in choices.values() for entity in values)
        for key, values in sorted(choices.items()):
            if len(values) != 1:
                continue
            entity = next(iter(values))
            if entity in used or claims[entity] != 1:
                continue
            assignments[key] = entity
            used.add(entity)
            decisions[key] = {"status": "matched", "rule": {5: "same-observation-in-capture", 4: "unique-typed-anchor", 3: "corroborated-source", 2: "corroborated-path-or-history", 1: "unique-content-in-container"}[level],
                              "confidence": "deterministic", "candidates": [entity], "evidence": values[entity]}
            if previous[entity].get("decision", {}).get("status") == "ambiguous":
                decisions[key] = {**previous[entity]["decision"], "rule": "retained-unresolved-identity"}

    for key, row in sorted(current.items()):
        if key in assignments:
            continue
        candidates = sorted({entity for values in proposals[key].values() for entity in values} | direct[key])
        # First appearance uses a wiki-owned allocation seed. Later source IDs
        # may change without changing this key; source IDs are not the key itself.
        entity = "e-" + fingerprint([snapshot, row["family"], key])[:32]
        if entity in previous or entity in used:
            entity = "e-" + fingerprint([request_key, row["family"], key])[:32]
        if entity in previous or entity in used:
            raise ContractError("New identity allocation collides with an existing entity")
        assignments[key] = entity
        used.add(entity)
        decisions[key] = {"status": "ambiguous" if candidates else "new", "rule": "retain-unresolved-candidates" if candidates else "first-observation",
                          "confidence": "unresolved" if candidates else "new", "candidates": candidates}
    return assignments, decisions


def reviewed_supersessions(current, previous, assignments, snapshot, corrections):
    """Retire exact reviewed reclassifications without treating them as game removals."""
    result = {}
    active = set(assignments.values())
    for correction in corrections:
        if correction.get("snapshot_id") != snapshot:
            continue
        retired = correction.get("supersedes", [])
        if not isinstance(retired, list):
            raise ContractError("Invalid reviewed supersession list")
        key = correction["observation_key"]
        current_row, target = current[key], assignments[key]
        for entity in retired:
            if not isinstance(entity, str) or entity not in previous or entity in result or entity in active:
                raise ContractError("Reviewed supersession names an absent, duplicate or active entity")
            state = previous[entity]
            old = state["descriptor"]
            if (state["last_seen"] != snapshot or old["summary"] or current_row["summary"]
                    or old["kind"] == current_row["kind"] or not all(current_row["component"])
                    or any(old[field] != current_row[field] for field in ("source_id", "source_object", "component"))
                    or (state["status"] == "superseded" and state.get("superseded_by") != target)):
                raise ContractError("Reviewed supersession must reclassify the same captured component")
            result[entity] = target
    return result
