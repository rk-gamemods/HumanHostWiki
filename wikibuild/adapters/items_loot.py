"""Serialized item and loot facts. Rates remain stored values, not probabilities.

Schema evidence: Catalog/views/{items,loot-tags,loot-rate-sets,loot-sources}.jsonl
from game build 25548639. Interpretation is deliberately limited to serialized
fields. Code-dependent mechanics and enum meanings require separate adapters.
"""

import math

from ..storage import ContractError, digest, json_bytes

NAME = "items-loot"
VERSION = 1
INPUTS = tuple("Catalog/views/" + name + ".jsonl" for name in
               ("items", "loot-tags", "loot-rate-sets", "loot-sources"))
KINDS = ("item", "loot-tag", "loot-table", "loot-source")

# Every recognized input field is either selected or explicitly excluded.
# Additions are exceptions until their meaning is established.
ITEM_FIELDS = {
    "MaxStack": int, "_BaseMaxDurability": (int, float), "_BuySellValue": int,
    "_Can_Repair": int, "_Can_Stack": int, "_DuraCostPerAttack": (int, float),
    "_LootCountRange": dict, "_SlotType": int, "_Tag": str, "_Tags": list,
    "_ammoType": str, "_baseBladeHitProb": (int, float), "_baseDamage": (int, float),
    "_baseHitDownProb": (int, float), "_blockDurability": (int, float),
    "_fireRate": str, "_headShotFactor": (int, float), "_maxMagCount": int,
    "_noiseDistance": (int, float),
}
ITEM_REFERENCES = {"/_DisResources": "disassembly", "/ModelRef": "model",
                   "/_RepairIconRef": "repair-item"}
ITEM_EXCLUDED = {"Icon", "m_Enabled", "m_GameObject", "m_Name", "m_Script",
                 "_ToolTipText", "_DisResources", "ModelRef", "_RepairIconRef"}
SOURCE_FIELDS = {"_ColumLineCount": dict, "_ContainerType": int,
                 "_DoorOpenCloseSeconds": (int, float), "_OpenSecondsFactor": (int, float)}
SOURCE_EXCLUDED = {"_AirDropPOI", "_CloseSFX", "_LootRateSet", "_LootSFX",
                   "_NPC_DeadBodyTempSaveKey", "_OpenSFX", "_Rotate_afterF",
                   "_TextIndicatorLoPos", "_fatherBI", "_initLoRot", "_lastOpenDir",
                   "_oldLocalRot", "_opened", "_parentConstraint", "m_Enabled",
                   "m_GameObject", "m_Name", "m_Script"}
RATE_FIELDS = {"_spawnLootTag": str, "_spawnRateRange": (int, float), "_stackFactor": (int, float)}


def select(fields, schema, excluded, issues, topic, pattern, identity):
    if not isinstance(fields, dict):
        issues.add("unsupported-fields", topic, pattern, "Expected a field object.", identity)
        return {}
    facts = {}
    for field, expected in schema.items():
        if field not in fields:
            issues.add("missing-field", topic, pattern + "/" + field,
                       "A known field is absent; dependent facts were omitted.", identity)
        elif not isinstance(fields[field], expected) or isinstance(fields[field], bool):
            issues.add("unsupported-field-type", topic, pattern + "/" + field,
                       "A field has an unsupported type; its fact was omitted.", identity)
        else:
            value = fields[field]
            if isinstance(value, float) and not math.isfinite(value):
                issues.add("invalid-number", topic, pattern + "/" + field,
                           "A numeric field is not finite; its fact was omitted.", identity)
            elif expected is dict:
                # These selected fields are 2D integer/float ranges, not free-form
                # bags of future fields. Keep only evidenced coordinates.
                coordinates = select(value, {"x": (int, float), "y": (int, float)}, set(),
                                     issues, topic, pattern + "/" + field, identity)
                facts[field] = coordinates
            elif expected is list and not all(isinstance(tag, str) for tag in value):
                issues.add("unsupported-field-type", topic, pattern + "/" + field,
                           "A string list has unsupported entries; its fact was omitted.", identity)
            else:
                facts[field] = value
    for field in sorted(fields.keys() - schema.keys() - excluded):
        issues.add("new-field", topic, pattern + "/" + field,
                   "A new source field needs an extraction decision; known fields were processed.", identity)
    return facts


def observation(kind, identity, name, facts, path, fields, relationships=(), evidence=()):
    if not isinstance(identity, str) or not identity:
        raise ContractError(f"Missing {kind} source identity in {path}")
    return {"observation_key": digest(json_bytes([kind, identity]))[:32],
            "kind": kind, "source_id": identity, "name": name or identity,
            "facts": facts, "evidence_level": "extracted",
            "relationships": list(relationships),
            "evidence": [{"path": path, "object": identity, "fields": sorted(fields)}, *evidence]}


def relations(record, issues, topic):
    result = []
    for ref in record.get("references", []):
        if ref.get("field") not in ITEM_REFERENCES:
            continue
        if ref.get("status") != "resolved":
            if ref.get("status") != "null":
                issues.add("unresolved-reference", topic, ref["field"],
                           "A selected relationship could not be resolved.", record["id"])
            continue
        targets = ref.get("targets", [ref["target"]] if "target" in ref else [])
        for target in targets:
            result.append({"predicate": ITEM_REFERENCES[ref["field"]], "target_source_id": target,
                           "source_field": ref["field"], "guid": ref.get("guid")})
    return sorted(result, key=lambda r: (r["predicate"], r["target_source_id"]))


def extract(source, issues):
    items_path, tags_path, sets_path, sources_path = INPUTS
    items = list(source.records(items_path))
    tooltip_ids = {r["target"] for item in items for r in item.get("references", [])
                   if r.get("field") == "/_ToolTipText" and r.get("status") == "resolved" and "target" in r}
    tooltips = source.objects(tooltip_ids)
    for item in items:
        identity = item.get("id")
        if not isinstance(identity, str):
            raise ContractError(f"Item without source ID in {items_path}")
        facts = select(item.get("fields"), ITEM_FIELDS, ITEM_EXCLUDED, issues,
                       "items-equipment", "Icon_Info", identity)
        names, evidence = set(), []
        for ref in item.get("references", []):
            if ref.get("field") != "/_ToolTipText" or ref.get("status") != "resolved":
                continue
            tooltip = tooltips.get(ref.get("target"))
            if tooltip:
                infos = tooltip.get("fields", {}).get("_Infos", [])
                for index, info in enumerate(infos):
                    if info.get("languageType") == 2 and info.get("_ItemName"):
                        names.add(info["_ItemName"])
                        evidence.append({"path": source.object_path(tooltip["id"]), "object": tooltip["id"],
                                         "fields": [f"/_Infos/{index}/_ItemName", f"/_Infos/{index}/languageType"]})
        if len(names) != 1:
            issues.add("english-name", "items-equipment", "Tooltip_Text/_Infos",
                       "No unique English item name; the internal name is retained.", identity)
        name = next(iter(names)) if len(names) == 1 else item.get("name")
        row = observation("item", identity, name, facts, items_path, facts,
                          relations(item, issues, "items-equipment"), evidence)
        row["name_status"] = "english" if len(names) == 1 else "internal"
        row["game_objects"] = item.get("game_objects", [])
        yield row

    for table in source.records(tags_path):
        tag, manager = table.get("tag"), table.get("manager")
        if not isinstance(tag, str) or not isinstance(manager, str) or not isinstance(table.get("items"), list):
            raise ContractError(f"Malformed loot tag record: {tags_path}")
        links = []
        for entry in table["items"]:
            if entry.get("status") != "resolved":
                issues.add("unresolved-loot-item", "loot-acquisition", tag,
                           "An eligible item reference could not be resolved.", manager + ":" + str(entry.get("guid")))
            links.append({"predicate": "eligible-item", "guid": entry.get("guid"),
                          "target_source_ids": entry.get("icon_components", []),
                          "source_field": "/_All_Loot_Icons/_all_Icons_Ref"})
        yield observation("loot-tag", manager + "/tag/" + tag, tag, {"tag": tag},
                          tags_path, ["tag", "items"], links)

    for table in source.records(sets_path):
        identity = table.get("id")
        if not isinstance(identity, str) or not isinstance(table.get("rates"), list):
            raise ContractError(f"Malformed loot rate set: {sets_path}")
        rates = [select(rate, RATE_FIELDS, set(), issues, "loot-acquisition", "Loot_Rate_Sets/_LootSpawnRates", identity)
                 for rate in table["rates"]]
        yield observation("loot-table", identity, table.get("name"), {"rates": rates}, sets_path, ["rates"])

    for record in source.records(sources_path):
        identity = record.get("id")
        if not isinstance(identity, str) or not isinstance(record.get("loot_sets"), list):
            raise ContractError(f"Malformed loot source: {sources_path}")
        if record.get("class") != "Object_Interact":
            issues.add("unsupported-source-class", "loot-acquisition", str(record.get("class")),
                       "A loot source class needs an adapter; its source-to-table links are retained.", identity)
            facts = {}
        else:
            facts = select(record.get("fields"), SOURCE_FIELDS, SOURCE_EXCLUDED, issues,
                           "loot-acquisition", "Object_Interact", identity)
        links = [{"predicate": "uses-loot-table", "target_source_id": target, "source_field": "/_LootRateSet"}
                 for target in sorted(record["loot_sets"])]
        yield observation("loot-source", identity, record.get("name"), facts, sources_path, facts, links)
