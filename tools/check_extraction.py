"""Independent selected-fact check against committed raw serialized records.

This complements fixtures; it does not establish runtime behavior or full topic
coverage. Uses Git directly, without the adapter or Source implementations.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def blob(source, commit, path):
    return subprocess.run(["git", "-C", str(source), "show", f"{commit}:{path}"],
                          check=True, capture_output=True).stdout


def check(root, source):
    pointer = json.loads((root / ".local/extraction-latest.json").read_text())
    run = json.loads((root / f".local/extractions/runs/{pointer['run_id']}.json").read_text())
    data = (root / run["records"]["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != run["records"]["sha256"]:
        raise ValueError("Selected facts do not match their recorded hash")
    rows = [json.loads(line) for line in data.splitlines()]
    sample = []
    for kind in sorted({row["kind"] for row in rows}):
        candidates = [row for row in rows if row["kind"] == kind]
        sample.extend(candidates[index] for index in sorted({0, len(candidates) // 2, len(candidates) - 1}))
    requested = {}
    for row in sample:
        identity = row["source_id"].split("/tag/", 1)[0] if row["kind"] == "loot-tag" else row["source_id"]
        path = "Catalog/objects/" + identity.rsplit("#", 1)[0].replace("::", "/") + ".jsonl"
        requested.setdefault(path, set()).add(identity)
        for evidence in row["evidence"][1:]:
            requested.setdefault(evidence["path"], set()).add(evidence["object"])
    objects = {}
    for path, wanted in requested.items():
        for line in blob(source, run["source_commit"], path).splitlines():
            raw = json.loads(line)
            if raw["id"] in wanted:
                objects[raw["id"]] = raw
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
        raw = objects[row["source_id"]]
        if row["kind"] == "loot-table":
            if raw["fields"]["_LootSpawnRates"] != row["facts"]["rates"]:
                raise ValueError(f"Loot rates differ: {row['source_id']}")
            checks += 1
        else:
            for field, actual in row["facts"].items():
                if raw["fields"][field] != actual:
                    raise ValueError(f"Fact differs: {row['source_id']} {field}")
                checks += 1
        if row["kind"] == "item" and row["name_status"] == "english":
            names = {entry["_ItemName"] for evidence in row["evidence"][1:]
                     for entry in objects[evidence["object"]]["fields"]["_Infos"]
                     if entry["languageType"] == 2 and entry.get("_ItemName")}
            if names != {row["name"]}:
                raise ValueError(f"English name differs: {row['source_id']}")
            checks += 1
    return {"snapshot_id": run["snapshot_id"], "observations_checked": len(sample), "assertions": checks,
            "kinds": sorted({row["kind"] for row in sample}), "status": "passed",
            "scope": "Selected serialized facts, English names and loot eligibility; not runtime verification"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2] / "HumanHostCodebase")
    args = parser.parse_args()
    print(json.dumps(check(Path(__file__).resolve().parents[1], args.source), indent=2))
