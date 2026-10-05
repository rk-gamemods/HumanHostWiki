"""Pure, conservative identity reconciliation. No filesystem or network access."""

from collections import Counter, defaultdict
import re

from .adapters.components import identity_rule
from .adapters.entries import definition_identity
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


def owner_anchor(source_id, record):
    anchor = typed_anchor(source_id, record)
    hierarchy = record.get("hierarchy")
    if not anchor or not hierarchy or not all(isinstance(name, str) and name for name in hierarchy):
        return None
    return {key: value for key, value in anchor.items() if key != "asset_name"} | {"owner_hierarchy": hierarchy}


def reference_role(field):
    return re.sub(r"/\d+(?=/|$)", "/*", field)


def unique_anchors(anchors, metadata=None):
    counts = Counter(fingerprint(anchor) for anchor in anchors.values() if anchor)
    return {key: anchor for key, anchor in anchors.items() if anchor and counts[fingerprint(anchor)] == 1
            and (metadata is None or metadata[key].get("anchor_count", 1) == 1)}


def slot_anchors(metadata, rules, owners):
    return {key: {**owners[key], "slot_index": record["slot_index"]} for key, record in metadata.items()
            if rules[key].get("kind") == "slot" and owners[key] and type(record.get("slot_index")) is int}


def localization_anchors(metadata, rules, callers):
    """Return unique caller-role claims and all contextual presence candidates."""
    blocked_roles = set()
    for source, caller in callers.items():
        for ref in metadata[source].get("reference_roles", []):
            if ref.get("status") == "null":
                continue
            targets = ref.get("targets", [])
            missing_text = any(target not in metadata or (rules[target].get("kind") == "localization"
                                and not isinstance(metadata[target].get("text"), str)) for target in targets)
            if ref.get("status") not in {None, "resolved"} or not targets or missing_text:
                blocked_roles.add((fingerprint(caller), reference_role(ref["source_field"])))
                blocked_roles.add((fingerprint(caller), ref["source_field"]))
    roles, claims, presence = defaultdict(set), defaultdict(dict), set()
    for target, record in metadata.items():
        rule = rules[target]
        if rule.get("kind") != "localization" or not isinstance(record.get("text"), str):
            continue
        for ref in record.get("callers", []):
            source = ref["source_id"]
            role = reference_role(ref["source_field"]) if rule.get("normalize_indices") else ref["source_field"]
            def claim(caller):
                return {"container": target.split("#", 1)[0], "engine_type": record["type"],
                        "assembly": record["assembly"], "class": record["class"], "text": record["text"],
                        "callers": [{"caller": caller, "role": role}]}
            # Nonunique callers can establish presence, but cannot prove identity.
            for candidate in (typed_anchor(source, metadata.get(source, {})), owner_anchor(source, metadata.get(source, {}))):
                if candidate:
                    presence.add(fingerprint(claim(candidate)))
            caller = callers.get(source)
            if caller is None or (fingerprint(caller), role) in blocked_roles:
                continue
            key = fingerprint(claim(caller))
            roles[key].add(target)
            claims[target][key] = claim(caller)
    return {target: {key: value for key, value in values.items() if len(roles[key]) == 1}
            for target, values in claims.items()}, presence


class CaptureIndex:
    """Build catalog anchors, contextual presence and path lookups once."""

    def __init__(self, metadata, previous=None):
        self.metadata, self.paths, self.source_paths = metadata, defaultdict(set), {}
        self.rules = {key: identity_rule(record) for key, record in metadata.items()}
        typed = {key: typed_anchor(key, record) for key, record in metadata.items()}
        owners = {key: owner_anchor(key, record) for key, record in metadata.items()}
        named, owned = unique_anchors(typed, metadata), unique_anchors(owners)
        callers = owned | named
        claims, self.presence = localization_anchors(metadata, self.rules, callers)
        slots = slot_anchors(metadata, self.rules, owners)
        self.presence.update(fingerprint(anchor) for anchor in [*typed.values(), *slots.values()] if anchor)
        preferred = {fingerprint(row["descriptor"]["anchor"]) for row in (previous or {}).values()
                     if row.get("status") != "superseded" and (row["descriptor"].get("anchor") or {}).get("callers")}
        targets = dict(named)
        for key, rule in self.rules.items():
            if rule.get("kind") == "slot":
                targets.pop(key, None)
            choices = claims.get(key, {})
            retained = choices.keys() & preferred
            if retained or (key not in targets and choices):
                targets.pop(key, None)
                if len(retained) <= 1:
                    targets[key] = choices[next(iter(retained)) if retained else min(choices)]
            self.source_paths[key] = metadata[key].get("paths", [])
            for path in self.source_paths[key]:
                self.paths[path].add(key)
        self.anchors = unique_anchors(targets | slots)


def target_anchors(metadata, previous=None):
    return CaptureIndex(metadata, previous).anchors


def definition_anchor(definition, parent):
    if definition["type"] == "status-member":
        return {"parent_entity": parent, "member": definition["member"]}
    if definition["type"] == "skill" and definition.get("localized_name_anchor"):
        return {"parent_entity": parent, "skill_family": definition["family"],
                "localized_name": definition["localized_name_anchor"]}
    return None


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


def describe(row, metadata, capture=None):
    capture = capture if capture is not None else CaptureIndex(metadata)
    anchors = capture.anchors
    identity = row["source_id"]
    paths = set(row.get("asset_paths", []))
    for key in [identity, row.get("parent_source_id"), *row.get("game_objects", [])]:
        paths.update(capture.source_paths.get(key, []))
    summary = row.get("fact_scope") == "catalog-type-summary"
    component = row.get("component", {})
    base = row.get("source_field_base", "")
    anchor = None if summary or row.get("parent_source_id") else anchors.get(identity)
    context_kind, anchor_rule, ordinals = None, "unique-typed-anchor", None
    record = metadata.get(identity, {})
    rule = capture.rules.get(identity) or identity_rule(component)
    review = {field: record.get(field) for field in rule.get("review_fields", ())}
    if rule.get("kind") == "slot":
        context_kind, anchor_rule = "slot", "slot-owner-and-index"
        ordinals = record.get("hierarchy_ordinals")
        if not anchor or type(row["facts"].get(rule["index_field"])) is not int or anchor.get("slot_index") != row["facts"][rule["index_field"]] or any(value is None for value in review.values()):
            anchor = None
    elif rule.get("kind") == "localization" and record and (not anchor or "callers" in anchor):
        context_kind, anchor_rule = "localization", "caller-role-and-text"
        if anchor and row["facts"].get(rule["text_field"]) != anchor["text"]:
            anchor = None
    definition = row.get("definition_identity") or definition_identity(row, rule)
    if definition is not None:
        context_kind, anchor_rule = "definition", "parent-relative-definition"
        definition = {**definition, "parent_source_id": row["parent_source_id"]}
        definition["parent_anchor"] = anchors.get(row["parent_source_id"])
        if definition["type"] == "skill":
            definition["localized_name_anchor"] = anchors.get(definition.get("localized_name_source_id"))
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
            "anchor": anchor, "anchor_rule": anchor_rule, "context_kind": context_kind,
            "hierarchy_ordinals": ordinals, "review_fields": rule.get("review_fields", ()), "definition": definition, **review}


def context_compatible(current, old):
    if not (current.get("context_kind") or old.get("context_kind")):
        return True
    if not current.get("anchor") or current.get("anchor") != old.get("anchor"):
        return False
    return review_compatible(current, old)


def review_compatible(current, old):
    return all(current.get(field) == old.get(field) for field in
               set(current.get("review_fields", ())) | set(old.get("review_fields", ())))


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


def independent_context(current, old, paths=()):
    return bool((current.get("anchor") and current["anchor"] == old.get("anchor"))
                or set(old["paths"]) & set(paths))


def candidate_rules(current, previous, index, same_capture, anchor_counts=None, continuing=None, path_counts=None):
    family = (current["family"], tuple(current["component"]))
    unique_paths = [path for path in current["paths"] if path_counts and path_counts[(family, path)] == 1
                    and len(index["path"].get((family, path), set())) == 1]
    levels = defaultdict(dict)
    anchored = set()
    if current.get("anchor"):
        anchor_key = (family, fingerprint(current["anchor"]))
        anchored = index["anchor"].get(anchor_key, set())
        if anchor_counts and anchor_counts[anchor_key] == 1 and len(anchored) == 1:
            entity = next(iter(anchored))
            if context_compatible(current, previous[entity]["descriptor"]):
                levels[4][entity] = [current.get("anchor_rule", "unique-typed-anchor"), "unique-on-both-sides"]
    direct = set(index["source"].get((family, current["source_id"]), set()))
    # The old occupant can continue at another ID. Its independently matched
    # context is evidence against a new record inheriting that numeric ID.
    for entity in tuple(direct):
        if continuing and entity in continuing and continuing[entity] != current["observation_key"]:
            direct.remove(entity)
    for entity in direct:
        state = previous[entity]
        old = state["descriptor"]
        evidence = ["scoped-source-id", "kind-and-component"]
        if same_capture and state["status"] == "present" and old["observation_key"] == current["observation_key"] and review_compatible(current, old):
            evidence.append("same-captured-game-inputs")
            levels[5][entity] = evidence
            continue
        elif current.get("context_kind") or old.get("context_kind"):
            continue
        elif current["name"] != old["name"] and not independent_context(current, old, unique_paths):
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
            if current.get("context_kind") or old.get("context_kind"):
                continue
            if current["name"] == old["name"] or (current["has_facts"] and current["facts_hash"] == old["facts_hash"]):
                levels[2][entity] = ["asset-path", path, "kind-and-component",
                                     "unchanged-name" if current["name"] == old["name"] else "unchanged-selected-facts"]
    if current["has_facts"]:
        for entity in index["content"].get((family, current["scope"], current["name"], current["facts_hash"]), set()):
            if current.get("context_kind") or previous[entity]["descriptor"].get("context_kind"):
                continue
            levels[1][entity] = ["container", "kind-and-component", "unchanged-name-and-selected-facts"]
    related = direct | anchored | index["name"].get((family, current["scope"], current["name"]), set())
    if same_capture:
        # Different objects in one pinned capture cannot become one lineage
        # through equal values or a shared path; require independent anchors.
        related = {entity for entity in related if entity in levels.get(4, {})
                   or previous[entity]["descriptor"]["source_object"] == current["source_object"]}
        levels = {level: {entity: evidence for entity, evidence in values.items() if entity in related}
                  for level, values in levels.items()}
        levels = {level: values for level, values in levels.items() if values}
    return levels, related


def reconcile(current, previous, snapshot, request_key, same_capture=False, corrections=(), reserved=(), allocations=None):
    """Reconcile containers first, then anchor definitions to their assigned keys."""
    for correction in corrections:
        if correction.get("snapshot_id") == snapshot and correction.get("observation_key") not in current:
            raise ContractError("Invalid, duplicate or stale reviewed identity mapping")
    parents = {key: row for key, row in current.items() if not row.get("definition")}
    children = {key: row for key, row in current.items() if row.get("definition")}
    parent_corrections = [row for row in corrections if row.get("observation_key") in parents]
    index = indexes(previous)
    assignments, decisions = reconcile_rows(parents, previous, snapshot, request_key, same_capture, parent_corrections,
                                             reserved, index, allocations)
    by_source = defaultdict(list)
    for key, row in parents.items():
        if not row["summary"]:
            by_source[row["source_id"]].append(key)
    for row in children.values():
        definition = row["definition"]
        possible = by_source.get(definition["parent_source_id"], [])
        row["anchor"] = None
        if len(possible) != 1:
            continue
        parent_key = possible[0]
        if row["component"] != parents[parent_key]["component"]:
            continue
        row["anchor"] = definition_anchor(definition, assignments[parent_key])
    child_corrections = [row for row in corrections if row.get("observation_key") in children]
    child_assignments, child_decisions = reconcile_rows(children, previous, snapshot, request_key, same_capture,
                                                       child_corrections, set(reserved) | set(assignments.values()), index, allocations)
    return assignments | child_assignments, decisions | child_decisions


def reconcile_rows(current, previous, snapshot, request_key, same_capture=False, corrections=(), reserved=(), index=None, allocations=None):
    """Reserve stronger unique matches first; leave all ties explicit."""
    index = indexes(previous) if index is None else index
    anchor_counts = Counter(((row["family"], tuple(row["component"])), fingerprint(row["anchor"]))
                            for row in current.values() if row.get("anchor"))
    path_counts = Counter(((row["family"], tuple(row["component"])), path)
                          for row in current.values() for path in row["paths"])
    continuing = {}
    for key, row in current.items():
        if not row.get("anchor"):
            continue
        anchor_key = ((row["family"], tuple(row["component"])), fingerprint(row["anchor"]))
        candidates = index["anchor"].get(anchor_key, set())
        if anchor_counts[anchor_key] == 1 and len(candidates) == 1:
            entity = next(iter(candidates))
            if context_compatible(row, previous[entity]["descriptor"]):
                continuing[entity] = key
    proposals, direct, assignments, decisions, used = {}, {}, {}, {}, set(reserved)
    for observation, row in sorted(current.items()):
        proposals[observation], direct[observation] = candidate_rules(row, previous, index, same_capture, anchor_counts, continuing, path_counts)

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
            decisions[key] = {"status": "matched", "rule": {5: "same-observation-in-capture", 4: current[key].get("anchor_rule", "unique-typed-anchor"), 3: "corroborated-source", 2: "corroborated-path-or-history", 1: "unique-content-in-container"}[level],
                              "confidence": "deterministic", "candidates": [entity], "evidence": values[entity]}
            if previous[entity].get("decision", {}).get("status") == "ambiguous" and entity not in proposals[key].get(4, {}):
                decisions[key] = {**previous[entity]["decision"], "rule": "retained-unresolved-identity"}

    for key, row in sorted(current.items()):
        if key in assignments:
            continue
        candidates = sorted({entity for values in proposals[key].values() for entity in values} | direct[key])
        # First appearance uses a wiki-owned allocation seed. Later source IDs
        # may change without changing this key; source IDs are not the key itself.
        entity = (allocations or {}).get(key) or "e-" + fingerprint([snapshot, row["family"], key])[:32]
        if entity in previous or entity in used:
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
