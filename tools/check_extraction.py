"""Independent selected-fact check against committed raw serialized records.

This complements fixtures; it does not establish runtime behavior or full topic
coverage. Uses Git directly, without the adapter or Source implementations.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wikibuild import bounded

# Selected tree scans can traverse the complete catalog path set.
GIT_TREE_TIMEOUT = 600
# Raw conservation checks consume full catalog shards.
GIT_STREAM_TIMEOUT = 1800


# Captured UI/UI.decompiled.cs: DynamicToolTipSet.ToolTipTiles. Every member
# is a Language_Text reference; Unity identity fields are not tooltip bindings.
TOOLTIP_MEMBERS = """_Dura_Title _BlockDura _Damage_Title _HitDown_Title _BladeHit_Title
_GunFireRate_Title _SingleShot_Title _GunMaxMag_Title _GunAmmoType_Title _BowAmmoType_Str
_Quality_Title _BladeHit_Instruct _HeadShot_Instruct _ArrowDamage _ArrowRange _ArrowSpeed
_ShootRange_Title _Recoil_Title _DummyRound_Title _Jam_Title _GatheringTool
_GatheringToolSmallAxe""".split()
TEXT_CLASSES = {"Language_Text", "Tooltip_Text"}
DERIVED_GAP_CODES = {"english-text", "missing-field", "unsupported-field-type", "unresolved-reference"}
TERRAIN_COMPONENT = {"assembly": "Build_System", "class": "Terrain_Block_Info"}
MERCHANT_COMPONENT = {"assembly": "Merchant", "class": "Merchant_Mgr"}
MINEABLE_ITEMS = "Catalog/views/items.jsonl"
MINEABLE_ADDRESSES = "Catalog/addressables.jsonl"


def raw_records(source, commit, path):
    with bounded.stream(["git", "-C", str(source), "show", f"{commit}:{path}"],
                        timeout=GIT_STREAM_TIMEOUT) as process:
        for line in process.stdout:
            yield json.loads(line), hashlib.sha256(line).hexdigest()
        if process.wait():
            raise ValueError(f"Raw source read failed: {path}: {process.stderr.decode('utf-8', errors='replace')}")


def at(value, path):
    for part in path.strip("/").split("/") if path else []:
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def compare_selected(expected, actual, context):
    if isinstance(actual, dict):
        if not isinstance(expected, dict):
            raise ValueError(f"Object shape differs: {context}")
        return sum(compare_selected(expected[key], value, context + "/" + key) for key, value in actual.items())
    if isinstance(actual, list):
        if not isinstance(expected, list) or len(expected) != len(actual):
            raise ValueError(f"List shape differs: {context}")
        return sum(compare_selected(left, right, context + f"/{index}")
                   for index, (left, right) in enumerate(zip(expected, actual)) if right is not None)
    if expected != actual or type(expected) is not type(actual):
        raise ValueError(f"Fact differs: {context}")
    return 1


def scene_prop_counts(entries, table):
    """Independent aggregation from raw placement records, without adapter imports."""
    valid = Counter(entry["protoRefIndex"] for entry in entries
                    if isinstance(entry, dict) and type(entry.get("protoRefIndex")) is int
                    and 0 <= entry["protoRefIndex"] < len(table))
    return {"counts": [{"protoRefIndex": key, "count": valid[key]} for key in sorted(valid)],
            "total_count": len(entries), "unresolved_count": len(entries) - sum(valid.values())}


def english_text(raw):
    """Recompute English facts, source locators and gaps from the pinned object."""
    name = "text" if raw["script"]["class"] == "Language_Text" else "_ItemName"
    facts, evidence, gaps = {name: None}, set(), []
    source_fields = raw.get("fields")
    if not isinstance(source_fields, dict):
        return {}, evidence, [("unsupported-field-type", "")]
    if "_Infos" not in source_fields:
        return facts, evidence, [("missing-field", "/_Infos")]
    infos = source_fields["_Infos"]
    if not isinstance(infos, list):
        return facts, evidence, [("unsupported-field-type", "/_Infos")]
    english = []
    for index, entry in enumerate(infos):
        pointer = f"/_Infos/{index}"
        if not isinstance(entry, dict):
            gaps.append(("unsupported-field-type", pointer))
        elif type(entry.get("languageType")) is not int:
            gaps.append(("unsupported-field-type", pointer + "/languageType"))
        # Captured LanguageType enum: English = 2, independent of list order.
        elif entry["languageType"] == 2:
            english.append((pointer, entry))
    if len(english) != 1:
        return facts, {"/_Infos"}, gaps + [("english-text", "/_Infos")]
    pointer, entry = english[0]
    evidence.add(pointer + "/languageType")
    names = [name]
    if name == "_ItemName" and "_ItemInstruction" in entry:
        names.append("_ItemInstruction")
    for field in names:
        if field not in entry:
            gaps.append(("missing-field", pointer + "/" + field))
        elif not isinstance(entry[field], str):
            facts[field] = None
            gaps.append(("unsupported-field-type", pointer + "/" + field))
        else:
            facts[field] = entry[field]
            evidence.add(pointer + "/" + field)
    return facts, evidence, gaps


def tooltip_references(raw):
    """Recompute the complete selected reference set, including missing edges."""
    links, evidence, gaps = [], set(), []
    source_fields = raw.get("fields")
    if not isinstance(source_fields, dict):
        return {}, links, evidence, [("unsupported-field-type", "")]
    if "data" not in source_fields:
        return {}, links, evidence, [("missing-field", "/data")]
    data = source_fields["data"]
    if not isinstance(data, dict):
        return {}, links, evidence, [("unsupported-field-type", "/data")]
    references = {ref["field"]: ref for ref in raw.get("references", [])}
    for member in TOOLTIP_MEMBERS:
        pointer = "/data/" + member
        if member not in data:
            gaps.append(("missing-field", pointer))
            continue
        value = data[member]
        if isinstance(value, dict) and "m_PathID" in value:
            valid = type(value["m_PathID"]) is int and type(value.get("m_FileID")) is int
            null = value["m_PathID"] == 0
        else:
            valid = isinstance(value, dict) and isinstance(value.get("m_AssetGUID"), str)
            null = valid and not value["m_AssetGUID"]
        if not valid:
            gaps.append(("unsupported-field-type", pointer))
            continue
        evidence.add(pointer)
        if null:
            continue
        ref = references.get(pointer)
        link = {"predicate": "tooltip-text", "source_field": pointer}
        if ref is None:
            links.append({**link, "status": "missing"})
            gaps.append(("unresolved-reference", pointer))
        elif ref.get("status") != "null":
            status = ref.get("status", "unknown")
            links.append({**link, "status": status,
                          "target_source_ids": sorted(ref.get("targets", [ref["target"]] if "target" in ref else [])),
                          **({"guid": ref["guid"]} if "guid" in ref else {})})
            if status != "resolved":
                gaps.append(("unresolved-reference", pointer))
    return {"data": {}}, links, evidence, gaps


def pinned_objects(source, commit, identities):
    """Read only requested objects, streaming each existing pinned shard once."""
    paths = defaultdict(set)
    for identity in identities:
        shard, number = identity.rsplit("#", 1)
        int(number)
        paths["Catalog/objects/" + shard.replace("::", "/") + ".jsonl"].add(identity)
    if not paths:
        return {}
    command = ["git", "-C", str(source), "ls-tree", "-r", "--name-only", "-z", commit, "--", *sorted(paths)]
    with bounded.stream(command, timeout=GIT_TREE_TIMEOUT) as child:
        available = {name.decode("utf-8") for name in child.stdout.records()}
        if child.wait():
            # Match the previous checked command's failure type.
            import subprocess
            raise subprocess.CalledProcessError(child.returncode, command, stderr=child.stderr)
    objects = {}
    for path, wanted in sorted(paths.items()):
        # A catalog reference to an uncaptured object cannot establish a link.
        if path in available:
            for raw, _ in raw_records(source, commit, path):
                if raw["id"] in wanted:
                    objects[raw["id"]] = raw
    return objects


def mineable_entries(raw):
    blocks = raw.get("fields", {}).get("_BlockInfo", [])
    for block_index, block in enumerate(blocks if isinstance(blocks, list) else []):
        entries = block.get("CollectableItems", []) if isinstance(block, dict) else []
        for entry_index, entry in enumerate(entries if isinstance(entries, list) else []):
            yield f"/_BlockInfo/{block_index}/CollectableItems/{entry_index}", entry if isinstance(entry, dict) else {}


def mineable_relationships(source, commit, terrains):
    """Rebuild mining joins from pinned catalog data, never observation targets."""
    names, icons = defaultdict(set), defaultdict(set)
    for item, _ in raw_records(source, commit, MINEABLE_ITEMS):
        if not isinstance(item.get("id"), str):
            continue
        if isinstance(item.get("name"), str):
            names[item["name"]].add(item["id"])
        for identity in item.get("game_objects", []):
            if isinstance(identity, str):
                icons[identity].add(item["id"])
    keys = {entry["ItemBI_refKey"] for raw in terrains for _, entry in mineable_entries(raw)
            if isinstance(entry.get("ItemBI_refKey"), str)}
    addresses = []
    for record, _ in raw_records(source, commit, MINEABLE_ADDRESSES):
        if record.get("resource_type", {}).get("m_ClassName") == "UnityEngine.GameObject":
            matched = keys.intersection(key for key in record.get("keys", []) if isinstance(key, str))
            if matched:
                addresses.append((record, matched))
    prefabs = pinned_objects(source, commit, {target for record, _ in addresses
                                             for target in record.get("targets", []) if isinstance(target, str)})
    members = {identity: [ref["target"] for ref in raw.get("references", [])
                          if re.fullmatch(r"/m_Component/\d+/component", ref.get("field", ""))
                          and ref.get("status") == "resolved" and isinstance(ref.get("target"), str)]
               for identity, raw in prefabs.items() if raw.get("type") == "GameObject"}
    components = pinned_objects(source, commit, {member for group in members.values() for member in group})
    outputs, locators = defaultdict(set), defaultdict(list)
    for identity, member_ids in members.items():
        locators[identity].append({"path": "Catalog/objects/" + identity.rsplit("#", 1)[0].replace("::", "/") + ".jsonl",
                                   "object": identity, "fields": ["/m_Component"]})
        for member in member_ids:
            raw = components.get(member, {})
            script = raw.get("script", {})
            if (script.get("assembly"), script.get("class")) != ("Build_System", "Build_Info"):
                continue
            fields = []
            for ref in raw.get("references", []):
                if (ref.get("status") == "resolved"
                        and re.fullmatch(r"/_Collectable_Info/_Items/\d+/_IconRef", ref.get("field", ""))):
                    fields.append(ref["field"])
                    for target in ref.get("targets", [ref["target"]] if "target" in ref else []):
                        outputs[identity].update(icons.get(target, ()))
            if fields:
                locators[identity].append({"path": "Catalog/objects/" + member.rsplit("#", 1)[0].replace("::", "/") + ".jsonl",
                                           "object": member, "fields": sorted(fields)})
    targets_by_key, evidence_by_key = defaultdict(set), defaultdict(list)
    for record, matched in addresses:
        for key in sorted(matched):
            evidence_by_key[key].append({"path": MINEABLE_ADDRESSES, "entry": record.get("entry"), "fields": ["keys", "targets"]})
            for target in record.get("targets", []):
                targets_by_key[key].update(outputs.get(target, ()))
                evidence_by_key[key].extend(locators.get(target, ()))
    result = {}
    for raw in terrains:
        links, evidence, gaps = [], [], []
        for field, entry in mineable_entries(raw):
            key, name = entry.get("ItemBI_refKey"), entry.get("Name")
            targets = targets_by_key.get(key, set()) if isinstance(key, str) else set()
            if len(targets) == 1:
                resolution, proof = "address", evidence_by_key[key]
            elif not targets and isinstance(name, str) and len(names.get(name, ())) == 1:
                targets, resolution = names[name], "name"
                proof = [{"path": MINEABLE_ITEMS, "fields": ["name", "id"]}]
            else:
                targets, resolution, proof = set(), "unresolved", []
            link = {"predicate": "mineable-item", "source_field": field,
                    "target_source_ids": sorted(targets), "resolution": resolution}
            if not targets:
                link["status"] = "unresolved"
                gaps.append(("mineable-item-gap", field))
            else:
                proof = [*proof, {"path": MINEABLE_ITEMS, "object": next(iter(targets)), "fields": ["id", "name", "game_objects"]}]
                for locator in proof:
                    if locator not in evidence:
                        evidence.append(locator)
            links.append(link)
        result[raw["id"]] = links, evidence, gaps
    return result


def check_derived_gaps(root, run, expected, contracts, complete):
    """Grouped reports have bounded examples; audit counts, not example inclusion."""
    artifact = run.get("exceptions")
    if not artifact:
        raise ValueError("Missing exception report for derived contracts")
    data = (root / artifact["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
        raise ValueError("Exception report does not match its recorded hash")
    actual = Counter()
    for group in json.loads(data)["groups"]:
        if any(group["code"] in codes and group["topic"] == topic
               and (group["pattern"] == cls or group["pattern"].startswith(cls + "/"))
               for (topic, cls), codes in contracts.items()):
            actual[(group["code"], group["topic"], group["pattern"])] += group["occurrences"]
    keys = expected.keys() | actual.keys() if complete else expected.keys()
    for key in sorted(keys):
        if actual[key] < expected[key] or (complete and actual[key] != expected[key]):
            label = "Mineable-item" if key[0] == "mineable-item-gap" else "Derived text"
            raise ValueError(f"{label} gap count differs: {key}; expected {expected[key]}, found {actual[key]}")


def _sample_families(families, complete):
    sample = []
    for _, candidates in sorted(families.items()):
        sample.extend(candidates if complete else
                      (candidates[index] for index in sorted({0, len(candidates) // 2, len(candidates) - 1})))
    return sample


def _build_check_samples(rows, complete):
    families, components_by_object = defaultdict(list), defaultdict(set)
    summaries = [row for row in rows if row.get("fact_scope") == "catalog-type-summary"]
    prefabs = {row["source_id"]: row for row in rows if row.get("fact_scope") == "referenced-prefab-identity"}
    for row in rows:
        if "component" in row:
            for identity in row.get("game_objects", []):
                components_by_object[identity].add(row["source_id"])
        if row.get("fact_scope") not in {"catalog-type-summary", "referenced-prefab-identity", "source-enumeration"}:
            families[(row["kind"], row.get("component", {}).get("class", ""))].append(row)
    sample = _sample_families(families, complete)
    return sample, summaries, prefabs, components_by_object


def _build_pinned_evidence(source, run, sample, prefabs):
    requested = {}
    for row in sample:
        identity = row["source_id"].split("/tag/", 1)[0] if row["kind"] == "loot-tag" else row["evidence"][0]["object"]
        path = "Catalog/objects/" + identity.rsplit("#", 1)[0].replace("::", "/") + ".jsonl"
        requested.setdefault(path, set()).add(identity)
        for evidence in row["evidence"][1:]:
            if "object" not in evidence:
                continue  # Source declarations are checked by check_coded_values below.
            requested.setdefault(evidence["path"], set()).add(evidence["object"])
    objects, hashes = {}, {}
    for row in prefabs.values():
        for evidence in row["evidence"][1:]:
            requested.setdefault(evidence["path"], set()).add(evidence["object"])
    for path, wanted in requested.items():
        for raw, sha in raw_records(source, run["source_commit"], path):
            if raw["id"] in wanted:
                objects[raw["id"]] = raw
                hashes[raw["id"]] = sha
    # Follow the pinned component's owner even if generated evidence omits or
    # substitutes it. Valid joins normally loaded this object in the first pass.
    owners = {}
    for row in sample:
        raw = objects.get(row["evidence"][0].get("object"), {})
        if not row.get("source_field_base") and all(
                raw.get("script", {}).get(key) == value for key, value in MERCHANT_COMPONENT.items()):
            for identity in _merchant_owners(raw):
                if identity not in objects:
                    path = "Catalog/objects/" + identity.rsplit("#", 1)[0].replace("::", "/") + ".jsonl"
                    owners.setdefault(path, set()).add(identity)
    for path, wanted in owners.items():
        for raw, sha in raw_records(source, run["source_commit"], path):
            if raw["id"] in wanted:
                objects[raw["id"]] = raw
                hashes[raw["id"]] = sha
    terrain_records = [objects[row["evidence"][0]["object"]] for row in sample if row.get("component") == TERRAIN_COMPONENT]
    mining = mineable_relationships(source, run["source_commit"], terrain_records) if terrain_records else {}
    return objects, hashes, mining


def _check_loot_eligibility(row, objects):
    manager, tag = row["source_id"].split("/tag/", 1)
    raw = objects[manager]
    table = next(t for t in raw["fields"]["_All_Loot_Icons"] if t["_spawnLootTag"] == tag)
    expected = [ref["m_AssetGUID"] for ref in table["_all_Icons_Ref"]]
    actual = [link["guid"] for link in row["relationships"]]
    if expected != actual:
        raise ValueError(f"Loot eligibility differs: {row['source_id']}")
    return 1


def _merchant_owners(raw):
    return sorted(ref["target"] for ref in raw.get("references", [])
                  if ref.get("field") == "/m_GameObject" and ref.get("status") == "resolved" and "target" in ref)


def _merchant_manager_facts(row, raw, objects):
    """Derive the active flag and exact evidence from the pinned owner join."""
    owners = _merchant_owners(raw)
    if row.get("game_objects", []) != owners:
        raise ValueError(f"Merchant manager owner differs: {row['source_id']}")
    managers = []
    for identity in sorted(set(owners)):
        owner = objects.get(identity, {})
        fields = owner.get("fields", {}) if owner.get("type") == "GameObject" else {}
        if fields.get("m_Name") == "Merchant_Mgr" and type(fields.get("m_IsActive")) is bool:
            managers.append((identity, fields["m_IsActive"]))
    expected, evidence = {}, []
    if len(managers) == 1:
        identity, active = managers[0]
        expected = {"manager_object": "Merchant_Mgr", "manager_active": active}
        path = "Catalog/objects/" + identity.rsplit("#", 1)[0].replace("::", "/") + ".jsonl"
        evidence = [{"path": path, "object": identity, "fields": ["/m_Name", "/m_IsActive"]}]
    if {key for key in row["facts"] if key.startswith("manager_")} != expected.keys():
        raise ValueError(f"Merchant manager facts differ: {row['source_id']}")
    actual = [{key: value for key, value in locator.items() if key != "record_sha256"}
              for locator in row["evidence"][1:] if "object" in locator]
    if actual != evidence:
        raise ValueError(f"Merchant manager evidence differs: {row['source_id']}")
    return expected


def _check_serialized_facts(row, raw, mining, derived_gaps, derived_contracts, objects):
    checks = 0
    if row["kind"] == "loot-table" and "component" not in row:
        if raw["fields"]["_LootSpawnRates"] != row["facts"]["rates"]:
            raise ValueError(f"Loot rates differ: {row['source_id']}")
        checks += 1
    else:
        component = row.get("component", {})
        derived = False
        if component.get("assembly") == "Language" and component.get("class") in TEXT_CLASSES:
            expected, fields, gaps = english_text(raw)
            derived, topic = True, "technical-reference"
        elif component == {"assembly": "UI", "class": "DynamicToolTipSet"}:
            expected, links, fields, gaps = tooltip_references(raw)
            if sorted(links, key=lambda link: link["source_field"]) != sorted(row["relationships"], key=lambda link: link["source_field"]):
                raise ValueError(f"Tooltip references differ: {row['source_id']}")
            derived, topic = True, "items-equipment"
            checks += len(links)
        elif component == TERRAIN_COMPONENT:
            links, evidence, gaps = mining[raw["id"]]
            if sorted(links, key=lambda link: link["source_field"]) != sorted(row["relationships"], key=lambda link: link["source_field"]):
                raise ValueError(f"Mineable-item relationships differ: {row['source_id']}")
            canonical = lambda locator: json.dumps(locator, sort_keys=True)
            if sorted(map(canonical, evidence)) != sorted(map(canonical, row["evidence"][1:])):
                raise ValueError(f"Mineable-item evidence differs: {row['source_id']}")
            topic, cls = "biomes-resources", "Terrain_Block_Info"
            derived_contracts[(topic, cls)] = {"mineable-item-gap"}
            for code, path in gaps:
                derived_gaps[(code, topic, cls + re.sub(r"/\d+(?=/|$)", "/*", path))] += 1
            expected = raw["fields"]
            checks += len(links) + 1
        else:
            expected = at(raw["fields"], row.get("source_field_base", ""))
        if derived:
            if expected != row["facts"]:
                raise ValueError(f"Derived text facts differ: {row['source_id']}")
            if fields != set(row["evidence"][0]["fields"]):
                raise ValueError(f"Derived text evidence differs: {row['source_id']}")
            cls = component["class"]
            derived_contracts[(topic, cls)] = DERIVED_GAP_CODES
            for code, path in gaps:
                pattern = cls + re.sub(r"/\d+(?=/|$)", "/*", path)
                derived_gaps[(code, topic, pattern)] += 1
            checks += 2
        if component == {"assembly": "Build_System", "class": "ScenePropSpawner"}:
            expected = dict(expected)
            for field, table in (("ScenePropsInfo", "PropsRefNoRepeat"), ("ScenePropsInfoBig", "PropsRefNoRepeatBig")):
                if field in row["facts"]:
                    expected[field] = scene_prop_counts(raw["fields"][field], raw["fields"][table])
                    if "/" + field not in row["evidence"][0]["fields"]:
                        raise ValueError("Composition count lacks its source-array evidence")
        if component == MERCHANT_COMPONENT and not row.get("source_field_base"):
            expected = {**expected, **_merchant_manager_facts(row, raw, objects)}
            checks += 2
        checks += compare_selected(expected, row["facts"], row["source_id"])
    return checks


def _check_row_evidence(row, raw, hashes):
    checks = 0
    for evidence in row["evidence"]:
        if "record_sha256" in evidence:
            if evidence["record_sha256"] != hashes[evidence["object"]]:
                raise ValueError(f"Record hash differs: {evidence['object']}")
            checks += 1
    if "component" in row:
        if any(raw["script"][key] != value for key, value in row["component"].items()):
            raise ValueError(f"Component identity differs: {row['source_id']}")
        checks += 1
        component = row.get("component", {})
        for link in row["relationships"]:
            if link["predicate"] in {"defined-by", "coded-value"}:
                continue
            if component == TERRAIN_COMPONENT and link["predicate"] == "mineable-item":
                continue  # The complete derived link set was checked above.
            ref = next((ref for ref in raw.get("references", []) if ref["field"] == link["source_field"]), {})
            actual_targets = sorted(ref.get("targets", [ref["target"]] if "target" in ref else []))
            status = ref.get("status", "unknown") if ref else "missing"
            if link.get("target_source_ids", []) != actual_targets or link.get("status") != status:
                raise ValueError(f"Reference differs: {row['source_id']} {link['source_field']}")
            if link.get("guid") != ref.get("guid"):
                raise ValueError(f"Reference GUID differs: {row['source_id']} {link['source_field']}")
            checks += 1
    return checks


def _check_row_names(row, objects):
    checks = 0
    if row["kind"] == "item" and row["name_status"] == "english":
        names = {entry["_ItemName"] for evidence in row["evidence"][1:]
                 if "object" in evidence
                 for entry in objects[evidence["object"]]["fields"]["_Infos"]
                 if entry["languageType"] == 2 and entry.get("_ItemName")}
        if names != {row["name"]}:
            raise ValueError(f"English name differs: {row['source_id']}")
        checks += 1
    elif row.get("name_status") == "english":
        names = {entry["text"] for evidence in row["evidence"][1:]
                 if "object" in evidence
                 for entry in objects[evidence["object"]]["fields"]["_Infos"]
                 if entry["languageType"] == 2 and entry.get("text")}
        if names != {row["name"]}:
            raise ValueError(f"Definition name differs: {row['source_id']}")
        checks += 1
    return checks


def _build_sample_checks(sample, objects, hashes, mining):
    checks = 0
    derived_gaps, derived_contracts = Counter(), {}
    for row in sample:
        if row["kind"] == "loot-tag":
            checks += _check_loot_eligibility(row, objects)
            continue
        raw = objects[row["evidence"][0]["object"]]
        checks += _check_serialized_facts(row, raw, mining, derived_gaps, derived_contracts, objects)
        checks += _check_row_evidence(row, raw, hashes)
        checks += _check_row_names(row, objects)
    return checks, derived_gaps, derived_contracts


def _build_index_checks(source, run, prefabs, components_by_object, objects, hashes, summaries):
    checks = 0
    totals = Counter()
    for record, _ in raw_records(source, run["source_commit"], "Catalog/views/object-index.jsonl"):
        totals[(record["type"], record.get("assembly"), record.get("class"))] += 1
        if record["id"] in prefabs:
            row = prefabs.pop(record["id"])
            if (record["type"] != "GameObject" or row["facts"] != {"engine_type": "GameObject"}
                    or row["name"] != (record.get("name") or record["id"])
                    or row.get("asset_paths", []) != record.get("paths", [])):
                raise ValueError(f"Referenced prefab differs from its index identity: {record['id']}")
            component_ids = components_by_object[record["id"]]
            if component_ids != {link["target_source_id"] for link in row["relationships"]}:
                raise ValueError(f"Prefab component links differ: {record['id']}")
            if component_ids != {evidence["object"] for evidence in row["evidence"][1:]}:
                raise ValueError(f"Prefab component evidence differs: {record['id']}")
            for evidence in row["evidence"][1:]:
                raw = objects[evidence["object"]]
                targets = {ref.get("target") for ref in raw.get("references", [])
                           if ref.get("field") == "/m_GameObject" and ref.get("status") == "resolved"}
                if targets != {record["id"]}:
                    raise ValueError(f"Prefab component does not belong to object: {evidence['object']}")
                if evidence.get("record_sha256", hashes[raw["id"]]) != hashes[raw["id"]]:
                    raise ValueError(f"Prefab component evidence hash differs: {raw['id']}")
                checks += 1
            checks += 3
    if prefabs:
        raise ValueError("Referenced prefab identities are absent from the index")
    if sum(totals.values()) != run["coverage"]["objects"]:
        raise ValueError("Object coverage total differs")
    for row in summaries:
        facts = row["facts"]
        if totals[(facts["engine_type"], facts["assembly"], facts["class"])] != facts["record_count"]:
            raise ValueError(f"Technical type count differs: {row['name']}")
        checks += 1
    return checks


def check(root, source, complete=False):
    pointer = json.loads((root / ".local/extraction-latest.json").read_text())
    run = json.loads((root / f".local/extractions/runs/{pointer['run_id']}.json").read_text())
    data = (root / run["records"]["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != run["records"]["sha256"]:
        raise ValueError("Selected facts do not match their recorded hash")
    rows = [json.loads(line) for line in data.splitlines()]
    sample, summaries, prefabs, components_by_object = _build_check_samples(rows, complete)
    prefab_count = len(prefabs)
    objects, hashes, mining = _build_pinned_evidence(source, run, sample, prefabs)
    checks, derived_gaps, derived_contracts = _build_sample_checks(sample, objects, hashes, mining)
    if derived_contracts:
        check_derived_gaps(root, run, derived_gaps, derived_contracts, complete)
        checks += 1
    checks += _build_index_checks(source, run, prefabs, components_by_object, objects, hashes, summaries)
    from check_coded_values import check as check_codes
    coded = check_codes(source, run["source_commit"], rows)
    return {"snapshot_id": run["snapshot_id"], "observations_checked": len(sample), "assertions": checks,
            "coded_values": coded,
            "sampling": "all" if complete else "first-middle-last-per-family",
            "prefab_identities_checked": prefab_count,
            "kinds": sorted({row["kind"] for row in sample}), "status": "passed", "type_summaries_checked": len(summaries),
            "scope": "Selected serialized facts, English text and names, tooltip references, mineable items and loot eligibility; not runtime verification"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2] / "HumanHostCodebase")
    parser.add_argument("--all", action="store_true", help="Check every selected observation instead of a sample per family")
    args = parser.parse_args()
    print(json.dumps(check(Path(__file__).resolve().parents[1], args.source, args.all), indent=2))
