"""Render supported guides from a local snapshot without changing the source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from wikibuild import extraction, game_text, guide_queries, guides, history, lint, model, presentation, snapshots


def load_context(root):
    """Read the latest validated model artifact and its input receipt in place."""
    run = history.latest(root)
    if run is None:
        raise ValueError(f"No identity run in {root}")
    rows = list(model.rows(extraction.artifact(root, run["models"])))
    receipt = snapshots.read(root, run["snapshot_id"])
    snapshot = {"game_version": receipt.get("game_version") or "unknown",
                "build_id": str(receipt["steam"]["build_id"])}
    registry = presentation.load(REPO / "presentation" / "fields.json")
    return guide_queries.build_context(rows, registry, game_text.labels(rows), snapshot)


def query_names(spec):
    """Return every block and repeat query needed to render a spec."""
    return {block["query"] for section in spec["sections"] for block in section["blocks"] if "query" in block} | {
        section["repeat"] for section in spec["sections"] if "repeat" in section}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO, help="Wiki checkout containing identity and snapshots")
    parser.add_argument("--out", type=Path, default=REPO / ".local" / "guides")
    parser.add_argument("--guides", help="Comma-separated guide IDs; default: all supported specs")
    args = parser.parse_args(argv)
    specs = {path.stem: guides.load_spec(path) for path in sorted((REPO / "guides").glob("*.json"))}
    if args.guides:
        ids = args.guides.split(",")
        unknown = set(ids) - set(specs)
        if unknown or not ids or len(ids) != len(set(ids)):
            parser.error(f"Invalid guide selection: {args.guides}")
    else:
        ids = [guide_id for guide_id, spec in specs.items() if query_names(spec) <= guide_queries.QUERIES.keys()]
    missing = {name for guide_id in ids for name in query_names(specs[guide_id]) if name not in guide_queries.QUERIES}
    if missing:
        parser.error("Queries not implemented: " + ", ".join(sorted(missing)))
    context = load_context(args.root.resolve())
    findings = []
    rendered = []
    counts = {}

    def counted(name, function):
        def query(context, scope):
            result = function(context, scope)
            location = f"{name}[{scope['index']}]" if "index" in scope else name
            if "bench" in scope:
                location = f"{name}[{scope['bench']['text']}]"
            counts[location] = len(result) if isinstance(result, list) else int(result is not None)
            return result
        return query

    queries = {name: counted(name, function) for name, function in guide_queries.QUERIES.items()}
    for guide_id in ids:
        document = guides.render(specs[guide_id], queries, context)
        markdown = guides.render_markdown(document, lambda key: "/entry/" + key)
        rendered.append((guide_id, document, markdown))
        for pointer, value in guides.text_runs(document):
            for finding in lint.jargon(value):
                findings.append({"guide": guide_id, "pointer": pointer, **finding})
    args.out.mkdir(parents=True, exist_ok=True)
    for guide_id, document, markdown in rendered:
        (args.out / f"{guide_id}.json").write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        (args.out / f"{guide_id}.md").write_text(markdown, encoding="utf-8", newline="\n")
        print(f"{guide_id}: {len(document['sections'])} sections")
    print("Rows per query: " + json.dumps(counts, sort_keys=True))
    if "progression-by-biome" in ids:
        missing_fields = [field for field in ("_MutantLvDisInterval", "_Z_Mutant_F", "_QualityCapDistanceInterval")
                          if not any(field in row["semantic"].get("facts", {}) for row in context["rows"].values())]
        print("Uncaptured scaling fields: " + ", ".join(missing_fields))
    if "getting-started" in ids:
        keys = [row["Item"]["entity"] for row in guide_queries.QUERIES["start.tools_and_weapons"](context, {})]
        labels = {column: sorted({stat["label"] for key in keys for stat in (context["cards"][key] or {}).get("stats", [])
                                  if stat["field"] == pointer})
                  for column, pointer in {"Damage": "/_baseDamage", "Durability": "/_BaseMaxDurability"}.items()}
        print("Column labels: " + json.dumps(labels, ensure_ascii=False, sort_keys=True))
    if "choosing-a-weapon" in ids:
        print("Weapon column labels: " + json.dumps(guide_queries.weapon_column_labels(context), ensure_ascii=False, sort_keys=True))
        print("Stat meanings: " + json.dumps(guide_queries.QUERIES["weapons.stat_labels"](context, {}), ensure_ascii=False))
    print(f"Jargon findings: {len(findings)}")
    for finding in findings:
        print(json.dumps(finding, ensure_ascii=False, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
