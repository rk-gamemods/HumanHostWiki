"""Read current model artifacts without changing the source repository."""

import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wikibuild import extraction, history, model


def audit(rows):
    """Inspect guide joins without opening raw game assets or writing artifacts."""
    from collections import Counter, defaultdict
    from wikibuild.gameplay import graph
    data = {row["entity_key"]: row for row in rows}
    result = graph(rows)
    names = {key: row["semantic"]["name"] for key, row in data.items()}
    selected = {"Solar Panel", "High-Energy Laser Emitter", "Circular Saw", "Rechargeable Battery", "Chip", "Circuit Board",
                "Magnet", "Bearing", "Pulley", "Plant Fiber", "Campfire", "Gunsmith Workbench"}
    def targets(key, predicate):
        return {target for rel in data[key]["semantic"]["relationships"] if rel["predicate"] == predicate
                for target in rel["targets"]}
    for key, value in result["benches"].items():
        print("BENCH", names[key], json.dumps(value))
    for key, value in result["items"].items():
        if names[key] not in selected:
            continue
        tags = sorted({row["semantic"]["facts"].get("tag") for row in rows
                       if row["semantic"]["kind"] == "loot-tag" and key in targets(row["entity_key"], "eligible-item")})
        loot_biomes = sorted({names[source["biome"]] for source in value["sources"]
                             if source["type"] == "looted" and source["biome"]})
        print("ITEM", names[key], key, json.dumps({"ring": value["earliest_ring"], "tags": tags,
                                                  "loot_biomes": loot_biomes}))
    loot_tags = defaultdict(set)
    table_biomes = defaultdict(set)
    for key, value in result["items"].items():
        for source in value["sources"]:
            if source["type"] == "looted" and source["biome"]:
                for table in targets(source["via"], "uses-loot-table"):
                    table_biomes[table].add(names[source["biome"]])
    for key, row in data.items():
        if row["semantic"]["kind"] == "loot-tag" and row["semantic"]["facts"].get("tag") in {"Desert", "Snowland", "Rainforest", "Ruins"}:
            print("SPECIAL_TAG", row["semantic"]["facts"]["tag"], json.dumps(sorted(names[t] for t in targets(key, "eligible-item"))))
        for rate in row["semantic"]["facts"].get("rates", []):
            if rate.get("_spawnRateRange", 0) > 0:
                loot_tags[rate["_spawnLootTag"]].update(table_biomes[key])
    print("LOOT_TAG_BIOMES", json.dumps({tag: sorted(biomes) for tag, biomes in sorted(loot_tags.items())}))
    print("LOOT_BIOME_COUNTS", json.dumps(dict(sorted(Counter(
        len({names[s["biome"]] for s in item["sources"] if s["type"] == "looted" and s["biome"]})
        for item in result["items"].values() if any(s["type"] == "looted" for s in item["sources"])).items()))))
    grass_rows = [r for r in rows if r["semantic"]["kind"] in {"resource-distribution", "asset", "component"}
                  and "grass" in json.dumps(r["semantic"]).casefold()]
    print("GRASS_RECORD_KINDS", json.dumps(dict(Counter(r["semantic"]["kind"] for r in grass_rows))))
    print("GRASS_PLACEMENT_FACTS", json.dumps([
        {"key": r["entity_key"], "name": r["semantic"]["name"], "facts": r["semantic"]["facts"]}
        for r in grass_rows if any("grass" in field.casefold() and field != "_treeGrassRefs"
                                  for field in r["semantic"]["facts"])]))
    vegetation = {target for key in data for target in targets(key, "vegetation")}
    print("GRASS_VEGETATION", json.dumps([{ "key": key, "name": names[key]}
                                          for key in sorted(vegetation) if "grass" in names[key].casefold()]))
    grass_by_biome = defaultdict(set)
    terrains_without_grass = []
    for key in data:
        biome_keys = targets(key, "biome")
        grass = {target for target in targets(key, "vegetation") if "grass" in names[target].casefold()}
        for biome in biome_keys:
            grass_by_biome[names[biome]].update(grass)
        if biome_keys and not grass:
            terrains_without_grass.append(names[key])
    print("GRASS_BY_BIOME", json.dumps({name: len(keys) for name, keys in sorted(grass_by_biome.items())}))
    print("TERRAINS_WITHOUT_GRASS", json.dumps(terrains_without_grass))


def main():
    root = Path(sys.argv[1])
    run = history.latest(root)
    rows = list(model.rows(extraction.artifact(root, run["models"])))
    print("SNAPSHOT", run["snapshot_id"])
    if sys.argv[2:] == ["--audit"]:
        audit(rows)
        return
    if len(sys.argv) > 2:
        for row in rows:
            semantic = row["semantic"]
            provenance = row.get("provenance", {})
            text = " ".join((semantic["name"], semantic["kind"], row["entity_key"],
                             provenance.get("component", {}).get("class", "")))
            if any((term[1:].lower() in (semantic["name"].lower(), semantic["kind"].lower(), row["entity_key"].lower())
                    if term.startswith("=") else term.lower() in text.lower()) for term in sys.argv[2:]):
                print(json.dumps({"entity_key": row["entity_key"], "semantic": semantic,
                                  "provenance": {key: provenance[key] for key in
                                                 ("source_id", "game_objects", "component", "asset_paths")
                                                 if key in provenance}}))
        return
    from wikibuild.gameplay import graph
    result = graph(rows)
    names = {row["entity_key"]: row["semantic"]["name"] for row in rows}
    counts = {}
    for value in result["biomes"].values():
        group = counts.setdefault(value["name"], {field: set() for field in
                                                  ("mined", "container_loot", "merchant", "harvest")})
        for field in group:
            group[field].update(entry["item"] for entry in value[field])
    print(json.dumps({"rings": [dict(ring, biomes=[names[k] for k in ring["biome_keys"]])
                               for ring in result["rings"]],
                      "biomes": {name: {field: len(entries) for field, entries in group.items()}
                                 for name, group in sorted(counts.items())},
                      "earliest": [{"key": key, "name": names[key], "ring": value["earliest_ring"]}
                                   for group in ("items", "benches") for key, value in result[group].items()
                                   if names[key] in ("Crude Axe", "M1891", "Campfire") or "gunsmith" in names[key].lower()],
                      "items_without_source": len(result["gaps"]["items_without_source"]),
                      "unresolved_benches": [{"key": key, "name": names[key]}
                                             for key in result["gaps"]["unresolved_benches"]],
                      "unmapped_container_bundles": result["gaps"]["unmapped_container_bundles"]}, indent=2))


if __name__ == "__main__":
    main()
