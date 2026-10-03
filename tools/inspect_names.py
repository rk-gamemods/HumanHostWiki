"""Read-only survey and audit of player names against the main model snapshot."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wikibuild import extraction, model, presentation
from wikibuild.game_text import labels
from wikibuild.gameplay import graph


MAIN = Path("C:/Users/Admin/Documents/GIT/GameMods/HumanHostMods/HumanHostWiki")
REGISTRY = Path(__file__).resolve().parents[1] / "presentation" / "fields.json"


def load_rows():
    latest = json.loads((MAIN / "identity/latest.json").read_text(encoding="utf-8"))
    run_id = latest.get("run_id") or latest.get("latest") or next(iter(latest.values()))
    run = json.loads((MAIN / f"identity/runs/{run_id}.json").read_text(encoding="utf-8"))
    return list(model.rows(extraction.artifact(MAIN, run["models"])))


def survey(rows):
    print("rows", len(rows), "kinds", dict(Counter(row["semantic"]["kind"] for row in rows)))
    by_source = defaultdict(list)
    by_object = defaultdict(list)
    inbound = defaultdict(list)
    for row in rows:
        prov = row.get("provenance", {})
        by_source[prov.get("source_id")].append(row)
        for obj in prov.get("game_objects", []):
            by_object[obj].append(row)
        for link in row["semantic"].get("relationships", []):
            for target in link.get("targets", []):
                inbound[target].append((row["semantic"]["kind"], row["semantic"]["name"], link["predicate"]))
    for kind, name in (("item", "M1891"), ("item", "Military Helmet"),
                       ("item", "Obsidian"), ("workbench", "WB_Campfire"),
                       ("workbench", "WB_Furnace"), ("loot-source", "DeadBodyLoot"),
                       ("loot-source", "0"), ("loot-table", "0"),
                       ("combat-rule", "Pipe_Rusty_02"), ("combat-rule", "Knife_Iron_Hit_Set")):
        examples = [r for r in rows if r["semantic"]["kind"] == kind and r["semantic"]["name"] == name]
        print("MATCH", kind, name, "count", len(examples))
        for row in examples[:2]:
            prov = row.get("provenance", {})
            key = row["entity_key"]
            print("EXAMPLE", key, "source", prov.get("source_id"), "objects", prov.get("game_objects"),
                  "evidence_objects", [e.get("object") for e in prov.get("evidence", [])],
                  "facts", str(row["semantic"].get("facts", {}))[:300],
                  "links", [(l["predicate"], l.get("field"), l.get("targets")) for l in row["semantic"].get("relationships", [])],
                  "inbound", inbound[key][:6])
            related = {r["entity_key"]: r for identity in [prov.get("source_id"), *prov.get("game_objects", []),
                                                            *(e.get("object") for e in prov.get("evidence", []))]
                       for r in by_source[identity] + by_object[identity]}
            print("RELATED", [(r["semantic"]["kind"], r["semantic"]["name"],
                               r.get("provenance", {}).get("component"),
                               str(r["semantic"].get("facts", {}))[:100]) for r in related.values()][:12])


def audit(rows):
    from wikibuild.lint import jargon
    from wikibuild.names import _compute, _shape, _tooltip

    acquisition = graph(rows)
    details = {}
    result = _compute(rows, presentation.load(REGISTRY), labels(rows), acquisition, details)
    by_key = {row["entity_key"]: row for row in rows}
    print("by rule", dict(sorted(Counter(v["rule"] for v in result.values()).items(), key=lambda p: str(p[0]))))
    print("by source", dict(Counter(v["source"] for v in result.values())))
    print("humanized by kind", details["humanized_by_kind"])
    for label, needle in (("M1891", "M1891"), ("helmets", "Military Helmet"),
                          ("M1A", "M1A"), ("Glass", "Glass"), ("Copper Alloy", "Copper Alloy")):
        print(label, [(key, value["name"]) for key, value in result.items()
                      if by_key[key]["semantic"]["name"] == needle and
                      by_key[key]["semantic"]["kind"] == "item"])
    groups = defaultdict(list)
    for key, value in result.items():
        if value["rule"] == "ordinal":
            stem = value["name"].rsplit(" (variant ", 1)[0]
            sem = by_key[key]["semantic"]
            groups[(sem["topic"], sem["kind"], stem)].append(key)
    ordered = sorted(((len(keys), *group) for group, keys in groups.items()), reverse=True)
    print("variant groups", len(ordered), "largest 5", ordered[:5])
    item_groups = [group for group in ordered if group[2] == "item"]
    print("item variant groups", len(item_groups), "largest 10", item_groups[:10])
    print("biomes", sorted((row["semantic"]["name"], result[row["entity_key"]]["name"])
                           for row in rows if row["semantic"]["kind"] == "biome"))
    by_source = defaultdict(list)
    for row in rows:
        by_source[row["provenance"]["source_id"]].append(row)
    block_shapes = Counter()
    for row in rows:
        if row["semantic"]["kind"] != "item" or row["semantic"]["facts"].get("_Tag") != "BuildMat":
            continue
        tooltip = _tooltip(row, by_key, by_source)
        shape = _shape(row, by_key, by_source)
        title = tooltip["semantic"]["name"] if tooltip else ""
        numbered = title.split("_", 1)[0].isdecimal()
        block_shapes["numbered block" if numbered else "other construction"] += 1
        if numbered and not shape:
            print("MISSING BLOCK SHAPE", row["entity_key"], row["semantic"]["name"], title)
    print("building shape coverage", dict(block_shapes))
    for key, recipe in acquisition["recipes"].items():
        output = by_key.get(recipe["output"], {}).get("semantic", {})
        if output.get("name") == "Biochemical Workbench":
            print("biochemical workbench glass", key,
                  [(entry["item"], result[entry["item"]]["name"], entry["count"])
                   for entry in recipe["ingredients"]
                   if by_key[entry["item"]]["semantic"]["name"] == "Glass"])
    if "--all-variants" in sys.argv:
        for group in ordered:
            print("VARIANT", group)
    remaining = [(key, value["name"], jargon(value["name"])) for key, value in result.items()
                 if jargon(value["name"])]
    print("lint", len(remaining), remaining[:10])
    print("lint rules", dict(Counter(finding["rule"] for _, _, hits in remaining for finding in hits)))
    final_groups = defaultdict(list)
    for key, value in result.items():
        sem = by_key[key]["semantic"]
        final_groups[(sem["topic"], sem["kind"], value["name"])].append(key)
    duplicates = [(group, len(keys)) for group, keys in final_groups.items() if len(keys) > 1]
    print("remaining duplicate names", len(duplicates), duplicates[:10])
    for needle in ("Pipe_Rusty_02", "Axe_Combo_2", "Z_Attack_01", "Knife_Iron_Hit_Set", "Tool_Interact_Mgr"):
        print("COMBAT", needle, sorted({value["name"] for key, value in result.items()
                                        if by_key[key]["semantic"]["kind"] == "combat-rule"
                                        and by_key[key]["semantic"]["name"] == needle}))
    loot_sources = {key: value for key, value in result.items()
                    if by_key[key]["semantic"]["kind"] == "loot-source"}
    loot_names = defaultdict(Counter)
    for value in loot_sources.values():
        name = value["name"]
        if value["rule"] == "ordinal":
            name = name.rsplit(" (variant ", 1)[0]
        loot_names[value.get("family", "unmatched")][name] += 1
    for family, counts in sorted(loot_names.items()):
        print("LOOT FAMILY", json.dumps({"family": family, "count": sum(counts.values()),
                                          "names": dict(sorted(counts.items()))}, ensure_ascii=False))
    print("loot sources still ordinal", sum(value["rule"] == "ordinal" for value in loot_sources.values()))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--count-tests" in sys.argv:
        import unittest

        suite = unittest.TestLoader().discover(str(Path(__file__).resolve().parents[1] / "tests"),
                                               pattern="test_*.py")
        print("discovered tests", suite.countTestCases())
        sys.exit(0)
    records = load_rows()
    if "--survey" in sys.argv:
        survey(records)
    else:
        audit(records)
