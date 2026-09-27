"""Build semantic revisions and snapshot-specific provenance from selected facts."""

from collections import defaultdict
import json

from .identity import fingerprint
from .storage import ContractError

TARGET_KINDS = {
    "coded-value": {"configuration"}, "ammunition-item": {"item"},
    **dict.fromkeys(("eligible-item", "produces-item", "produces-item-asset", "consumes-item-asset", "yields-item-asset", "collectible-item", "repair-item"), {"item"}),
    "uses-loot-table": {"loot-table"}, "disassembly": {"processing-rule"},
    "body-damage-set": {"damage-type"}, "biome": {"biome"}, "weather": {"weather"},
    "terrain-block-set": {"resource-distribution"}, "spawn-set": {"spawn-rule"},
    "spawns-prefab": {"creature"}, "headless-prefab": {"asset"}, "model": {"asset"},
    "engine": {"vehicle-rule"}, "tire": {"vehicle-rule"}, "character-skills": {"survival-rule"},
    "armor-part": {"equipment"},
    "material": {"construction-rule"}, "material-binding": {"construction-rule"},
    "weather-zone-settings": {"world-rule"},
    "merchant-stock-item": {"item"}, "initial-item": {"item"},
    "merchant-prefab": {"asset"}, "initial-inventory": {"loot-source"},
    "hotkey-binding": {"configuration"},
    "melee-animation": {"combat-rule"}, "scope-setting": {"equipment"},
    "material-damage-set": {"damage-type"}, "weapon-hit-set": {"combat-rule"},
    "gathered-item": {"item"},
    "inventory-template": {"loot-source"}, "player-crafting": {"workbench"},
    "terrain-material-table": {"construction-rule"},
    "dungeon-entrance-prefab": {"asset"}, "dungeon-exit-prefab": {"asset"}, "dungeon-prefab": {"asset"},
    "base-terrain-prefab": {"asset"}, "biome-terrain-prefab": {"asset"}, "bicycle-prefab": {"asset"},
    "vehicle-top": {"vehicle"}, "generator-building": {"building-piece"}, "next-rail": {"vehicle-rule"},
    "mechanic-platform-prefab": {"asset"}, "vehicle-top-prefab": {"asset"},
    "door-support-building": {"building-piece"}, "tree-log-item": {"item"},
    "tree-log-prefab": {"asset"}, "terrain-block-prefab": {"asset"}, "scene-prop-prefab": {"asset"},
    "character-status": {"survival-rule"}, "movement-collider": {"ai-rule"},
    "npc-animation-settings": {"ai-rule"}, "player-character-prefab": {"asset"},
    "controller": {"ai-rule"}, "zombie-controller": {"ai-rule"},
    "clock-module": {"time-rule"}, "weather-module": {"world-rule"},
    "environment-configuration": {"world-rule"}, "environment-weather": {"world-rule"},
}


def rows(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ContractError("Expected normalized input object")
            yield row


def source_ids(row):
    result = {row["source_id"], *row.get("game_objects", [])}
    if row.get("parent_source_id"):
        result.add(row["parent_source_id"])
    for evidence in row.get("evidence", []):
        if evidence.get("object"):
            result.add(evidence["object"])
    for link in row.get("relationships", []):
        result.update(link.get("target_source_ids", []))
        if link.get("target_source_id"):
            result.add(link["target_source_id"])
    return {identity for identity in result if "#" in identity and "/tag/" not in identity
            and identity.rsplit("#", 1)[-1].lstrip("-").isdigit()}


def targets_index(observations, assignments):
    aliases, summaries, kinds = defaultdict(set), {}, {}
    direct = defaultdict(set)
    for row in observations:
        entity = assignments[row["observation_key"]]
        kinds[entity] = row["kind"]
        aliases[row["source_id"]].add(entity)
        direct[row["source_id"]].add(entity)
        for identity in row.get("game_objects", []):
            aliases[identity].add(entity)
        if row.get("fact_scope") == "catalog-type-summary":
            facts = row["facts"]
            summaries[(facts["engine_type"], facts.get("assembly"), facts.get("class"))] = entity
    return aliases, summaries, kinds, direct


def relationships(row, indexes, metadata, issues):
    aliases, summaries, kinds, direct = indexes
    semantic, resolved = [], []
    for link in row.get("relationships", []):
        predicate = link["predicate"]
        targets = sorted(set(link.get("target_source_ids", [link["target_source_id"]] if link.get("target_source_id") else [])))
        field = link.get("source_field", "")
        base = row.get("source_field_base", "")
        semantic_field = field[len(base):] if base and (field == base or field.startswith(base + "/")) else field
        destinations, gaps, technical = [], [], []
        for target in targets:
            candidates = aliases.get(target, set())
            if predicate in TARGET_KINDS:
                candidates = {candidate for candidate in candidates if kinds[candidate] in TARGET_KINDS[predicate]}
            exact = candidates & direct.get(target, set())
            if exact:
                candidates = exact
            if len(candidates) == 1:
                entity = next(iter(candidates))
                destinations.append(entity)
                resolved.append({"source_field": field, "predicate": predicate, "target_source_id": target,
                                 "target_entity": entity, "status": "resolved"})
            elif len(candidates) > 1:
                gaps.append({"source_id": target, "status": "ambiguous-target", "candidates": sorted(candidates)})
            else:
                record = metadata.get(target)
                summary = summaries.get((record["type"], record.get("assembly"), record.get("class"))) if record else None
                if summary:
                    technical.append(summary)
                    resolved.append({"source_field": field, "predicate": predicate, "target_source_id": target,
                                     "target_entity": summary, "status": "technical-summary"})
                    if predicate in TARGET_KINDS:
                        gaps.append({"source_id": target, "status": "domain-target-not-cataloged", "technical_summary": summary})
                else:
                    gaps.append({"source_id": target, "status": "payload-omitted" if record else "missing-target-observation"})
        if not targets and (link.get("status") not in {None, "null"} or link.get("guid")):
            gaps.append({"status": link.get("status", "unresolved"), **({"guid": link["guid"]} if link.get("guid") else {})})
        if gaps:
            unresolved = [gap for gap in gaps if gap["status"] != "payload-omitted"]
            if unresolved:
                issues.add("relationship-gap", row["topic"], predicate,
                           "A selected relationship lacks a unique cataloged target; other relationships were retained.", row["source_id"], count=len(unresolved))
        semantic.append({"predicate": predicate, "field": semantic_field, "targets": sorted(set(destinations)),
                         **({"technical_targets": sorted(set(technical))} if technical else {}),
                         **({"gaps": gaps} if gaps else {})})
    return sorted(semantic, key=lambda link: (link["predicate"], link["field"], fingerprint(link))), resolved


def project(row, entity, indexes, metadata, dependencies, issues):
    links, resolved = relationships(row, indexes, metadata, issues)
    semantic = {"kind": row["kind"], "topic": row["topic"], "name": row["name"], "facts": row["facts"],
                "evidence_level": row["evidence_level"], "relationships": links}
    for key in ("notes", "fact_scope", "name_status", "family", "fact_labels"):
        if key in row:
            semantic[key] = row[key]
    evidence = []
    for locator in row["evidence"]:
        dependency = dependencies.get(locator["path"])
        if not dependency or dependency.get("missing"):
            raise ContractError(f"Observation evidence is not a validated input: {locator['path']}")
        evidence.append({**locator, "git_blob": dependency["git_blob"],
                         **({"input_sha256": dependency["sha256"]} if dependency.get("sha256") else {})})
    provenance = {"observation_key": row["observation_key"], "source_id": row["source_id"],
                  "evidence": evidence, "relationships": row.get("relationships", []), "resolved_targets": resolved}
    if row.get("fact_labels"):
        from .adapters.coded_values import values
        provenance["coded_facts"] = {field: value for pointer in row["fact_labels"]
                                      for field, value in values(row["facts"], pointer)}
    for key in ("component", "asset_paths", "game_objects", "parent_source_id", "source_field_base", "examples", "decode_gaps"):
        if key in row:
            provenance[key] = row[key]
    return {"entity_key": entity, "revision_id": fingerprint(semantic), "semantic": semantic, "provenance": provenance}


def absent_status(state, current_kinds, metadata, captured=True):
    if not captured or state["descriptor"]["kind"] not in current_kinds:
        return "uncaptured"
    if state["descriptor"]["summary"]:
        return "not-present"
    return "unresolved" if state["descriptor"]["source_object"] in metadata else "not-present"
