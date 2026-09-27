"""Pure, conservative identity reconciliation. No filesystem or network access."""

from collections import Counter, defaultdict

from .storage import ContractError, digest, json_bytes


def fingerprint(value):
    return digest(json_bytes(value))


def describe(row, metadata):
    identity = row["source_id"]
    paths = set(row.get("asset_paths", []))
    for key in [identity, row.get("parent_source_id"), *row.get("game_objects", [])]:
        paths.update(metadata.get(key, {}).get("paths", []))
    summary = row.get("fact_scope") == "catalog-type-summary"
    component = row.get("component", {})
    base = row.get("source_field_base", "")
    references = []
    for link in row.get("relationships", []):
        if link["predicate"] == "defined-by":
            continue
        field = link.get("source_field", "")
        if base and (field == base or field.startswith(base + "/")):
            field = field[len(base):]
        references.append([link["predicate"], field, link.get("guid") or
                           sorted(link.get("target_source_ids", [link["target_source_id"]] if link.get("target_source_id") else []))])
    return {"observation_key": row["observation_key"], "source_id": identity,
            "source_object": row.get("parent_source_id", identity).split("/tag/", 1)[0],
            "kind": row["kind"], "topic": row["topic"],
            "family": "catalog-type" if summary else row["kind"],
            "component": [component.get("assembly"), component.get("class")],
            "scope": identity.split("#", 1)[0] if "#" in identity else "catalog-summary",
            "name": row["name"], "facts_hash": fingerprint([row["facts"], sorted(references, key=fingerprint)]),
            "has_facts": bool(row["facts"] or references),
            "paths": sorted(paths), "summary": summary}


def compatible(left, right):
    return left["family"] == right["family"] and left["component"] == right["component"]


def indexes(previous):
    result = {key: defaultdict(set) for key in ("source", "path", "content", "name")}
    for entity, state in previous.items():
        if state.get("status") == "superseded":
            continue
        row = state["descriptor"]
        family = (row["family"], tuple(row["component"]))
        result["source"][(family, row["source_id"])].add(entity)
        result["name"][(family, row["scope"], row["name"])].add(entity)
        for path in row["paths"]:
            result["path"][(family, path)].add(entity)
        if row["has_facts"]:
            result["content"][(family, row["scope"], row["name"], row["facts_hash"])].add(entity)
    return result


def candidate_rules(current, previous, index, same_capture):
    family = (current["family"], tuple(current["component"]))
    levels = defaultdict(dict)
    direct = index["source"].get((family, current["source_id"]), set())
    for entity in direct:
        state = previous[entity]
        old = state["descriptor"]
        evidence = ["scoped-source-id", "kind-and-component"]
        if same_capture and state["status"] == "present" and old["observation_key"] == current["observation_key"]:
            evidence.append("same-captured-game-inputs")
            levels[4][entity] = evidence
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
    return levels, direct | index["name"].get((family, current["scope"], current["name"]), set())


def reconcile(current, previous, snapshot, request_key, same_capture=False, corrections=()):
    """Reserve stronger unique matches first; leave all ties explicit."""
    index = indexes(previous)
    proposals, direct, assignments, decisions, used = {}, {}, {}, {}, set()
    for observation, row in sorted(current.items()):
        proposals[observation], direct[observation] = candidate_rules(row, previous, index, same_capture)

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

    for level in (4, 3, 2, 1):
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
            decisions[key] = {"status": "matched", "rule": {4: "same-observation-in-capture", 3: "corroborated-source", 2: "corroborated-path-or-history", 1: "unique-content-in-container"}[level],
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
