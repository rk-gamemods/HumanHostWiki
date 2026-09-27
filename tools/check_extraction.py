"""Independent selected-fact check against committed raw serialized records.

This complements fixtures; it does not establish runtime behavior or full topic
coverage. Uses Git directly, without the adapter or Source implementations.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess


def raw_records(source, commit, path):
    process = subprocess.Popen(["git", "-C", str(source), "show", f"{commit}:{path}"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for line in process.stdout:
            yield json.loads(line), hashlib.sha256(line).hexdigest()
    finally:
        process.stdout.close()
        error = process.stderr.read().decode("utf-8", errors="replace")
        process.stderr.close()
        if process.wait():
            raise ValueError(f"Raw source read failed: {path}: {error}")


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


def check(root, source, complete=False):
    pointer = json.loads((root / ".local/extraction-latest.json").read_text())
    run = json.loads((root / f".local/extractions/runs/{pointer['run_id']}.json").read_text())
    data = (root / run["records"]["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != run["records"]["sha256"]:
        raise ValueError("Selected facts do not match their recorded hash")
    rows = [json.loads(line) for line in data.splitlines()]
    sample, families, components_by_object = [], defaultdict(list), defaultdict(set)
    summaries = [row for row in rows if row.get("fact_scope") == "catalog-type-summary"]
    prefabs = {row["source_id"]: row for row in rows if row.get("fact_scope") == "referenced-prefab-identity"}
    prefab_count = len(prefabs)
    for row in rows:
        if "component" in row:
            for identity in row.get("game_objects", []):
                components_by_object[identity].add(row["source_id"])
        if row.get("fact_scope") not in {"catalog-type-summary", "referenced-prefab-identity", "source-enumeration"}:
            families[(row["kind"], row.get("component", {}).get("class", ""))].append(row)
    for _, candidates in sorted(families.items()):
        sample.extend(candidates if complete else
                      (candidates[index] for index in sorted({0, len(candidates) // 2, len(candidates) - 1})))
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
    checks = 0
    for row in sample:
        if row["kind"] == "loot-tag":
            manager, tag = row["source_id"].split("/tag/", 1)
            raw = objects[manager]
            table = next(t for t in raw["fields"]["_All_Loot_Icons"] if t["_spawnLootTag"] == tag)
            expected = [ref["m_AssetGUID"] for ref in table["_all_Icons_Ref"]]
            actual = [link["guid"] for link in row["relationships"]]
            if expected != actual:
                raise ValueError(f"Loot eligibility differs: {row['source_id']}")
            checks += 1
            continue
        raw = objects[row["evidence"][0]["object"]]
        if row["kind"] == "loot-table" and "component" not in row:
            if raw["fields"]["_LootSpawnRates"] != row["facts"]["rates"]:
                raise ValueError(f"Loot rates differ: {row['source_id']}")
            checks += 1
        else:
            expected = at(raw["fields"], row.get("source_field_base", ""))
            if row.get("component") == {"assembly": "Build_System", "class": "ScenePropSpawner"}:
                expected = dict(expected)
                for field, table in (("ScenePropsInfo", "PropsRefNoRepeat"), ("ScenePropsInfoBig", "PropsRefNoRepeatBig")):
                    if field in row["facts"]:
                        expected[field] = scene_prop_counts(raw["fields"][field], raw["fields"][table])
                        if "/" + field not in row["evidence"][0]["fields"]:
                            raise ValueError("Composition count lacks its source-array evidence")
            checks += compare_selected(expected, row["facts"], row["source_id"])
        for evidence in row["evidence"]:
            if "record_sha256" in evidence:
                if evidence["record_sha256"] != hashes[evidence["object"]]:
                    raise ValueError(f"Record hash differs: {evidence['object']}")
                checks += 1
        if "component" in row:
            if any(raw["script"][key] != value for key, value in row["component"].items()):
                raise ValueError(f"Component identity differs: {row['source_id']}")
            checks += 1
            for link in row["relationships"]:
                if link["predicate"] in {"defined-by", "coded-value"}:
                    continue
                ref = next((ref for ref in raw["references"] if ref["field"] == link["source_field"]), {})
                actual_targets = sorted(ref.get("targets", [ref["target"]] if "target" in ref else []))
                if link.get("target_source_ids", []) != actual_targets or link.get("status") != ref.get("status", "missing"):
                    raise ValueError(f"Reference differs: {row['source_id']} {link['source_field']}")
                if link.get("guid") != ref.get("guid"):
                    raise ValueError(f"Reference GUID differs: {row['source_id']} {link['source_field']}")
                checks += 1
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
    from check_coded_values import check as check_codes
    coded = check_codes(source, run["source_commit"], rows)
    return {"snapshot_id": run["snapshot_id"], "observations_checked": len(sample), "assertions": checks,
            "coded_values": coded,
            "sampling": "all" if complete else "first-middle-last-per-family",
            "prefab_identities_checked": prefab_count,
            "kinds": sorted({row["kind"] for row in sample}), "status": "passed", "type_summaries_checked": len(summaries),
            "scope": "Selected serialized facts, English names and loot eligibility; not runtime verification"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2] / "HumanHostCodebase")
    parser.add_argument("--all", action="store_true", help="Check every selected observation instead of a sample per family")
    args = parser.parse_args()
    print(json.dumps(check(Path(__file__).resolve().parents[1], args.source, args.all), indent=2))
