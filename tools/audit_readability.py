"""Deterministic, read-only inventory of the released public reader packs."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import json
import math
from pathlib import Path
import re


SOURCE_PREDICATES = sorted(("produces-item", "eligible-item", "merchant-stock-item",
                            "disassembly", "collectible-item", "repair-item"))
FLAG_NAMES = ("float_noise", "sentinel_string", "cjk_text", "empty_text",
              "identifier_value", "duplicate_names", "no_source_items",
              "debug_names", "unreadable_targets")
MARKDOWN_KINDS = {"item", "recipe", "combat-rule", "creature", "biome", "workbench"}
DEBUG = re.compile(r"(?i)(^|[^a-z])(test|debug|dummy|temp)([^a-z]|$)|g_mode|gmode")
HEX_KEY = re.compile(r"^(?:[0-9a-f]{32}|e-[0-9a-f]+)$", re.I)
FILE_PATH = re.compile(r"/[^/]+\.[a-z0-9]{1,8}(?:$|[?#])", re.I)
LETTER_DIGIT = re.compile(r"[a-z]\d|\d[a-z]", re.I)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def refs(site, rows, active=()):
    for row in rows:
        if row.get("kind") == "wiki-shard-directory":
            path = row["path"]
            if path in active:
                raise ValueError(f"cyclic shard directory: {path}")
            yield from refs(site, read(site / path)["shards"], (*active, path))
        else:
            yield row


def pack_map(site, index, section):
    result = {}
    for row in refs(site, index.get(section, [])):
        shard = read(site / row["path"])
        overlap = result.keys() & shard.keys()
        if overlap:
            raise ValueError(f"duplicate {section} key: {min(overlap)}")
        result.update(shard)
    return result


def leaves(value, pointer=""):
    if isinstance(value, dict) and value:
        for key in sorted(value):
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            yield from leaves(value[key], pointer + "/" + escaped)
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from leaves(child, pointer + "/" + str(index))
    else:
        yield pointer, value


def group_pointer(pointer):
    return "/" + "/".join("*" if segment.isdecimal() else segment
                             for segment in pointer.split("/")[1:])


def field_label(field):
    text = re.sub(r"^_+", "", field)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).replace("_", " ")
    return text[:1].upper() + text[1:] if text else field


def identifier(value):
    return bool(HEX_KEY.fullmatch(value) or
                ("/" in value and FILE_PATH.search(value)) or
                (value.startswith("bundles/") and "::serialized" in value))


def float_noise(value):
    if not isinstance(value, float) or not math.isfinite(value) or value == 0:
        return False
    digits = len(Decimal(repr(value)).normalize().as_tuple().digits)
    rounded = float(format(value, ".4g"))
    return digits > 7 and abs(value - rounded) / abs(value) <= 1e-6


def filled(value):
    return value is not None and value != "" and value != [] and value != {}


def flag_row(topic, entry, field="", value=None):
    return {"topic": topic, "kind": entry["kind"], "entity_key": entry["entity_key"],
            "name": entry["name"], "field": field, "value": value}


def audit(repositories):
    flags = {name: {"total": 0, "examples": []} for name in FLAG_NAMES}
    inventory = defaultdict(lambda: {"values": set(), "filled": set()})
    kind_counts = Counter()
    topic_counts = Counter()
    names = defaultdict(list)
    text_fields = defaultdict(lambda: {"empty": set(), "filled": set(), "example": None})
    sentinel = defaultdict(lambda: {"zero": [], "nonzero": set()})
    all_entries = {}
    relationships = []

    def add(name, row, amount=1):
        target = flags[name]
        target["total"] += amount
        target["examples"].append(row)

    topics = sorted(path for path in repositories.iterdir()
                    if path.is_dir() and (path / "site" / "reader.json").is_file())
    for topic_dir in topics:
        topic, site = topic_dir.name, topic_dir / "site"
        topic_counts[topic] += 0
        config = read(site / "reader.json")
        index = read(site / config["snapshots"][config["default_snapshot"]]["path"])
        entries = pack_map(site, index, "entries")
        semantics = pack_map(site, index, "semantics")
        provenance = pack_map(site, index, "provenance")
        backlinks = pack_map(site, index, "backlinks")
        incoming = defaultdict(set)
        for key, link in sorted(backlinks.items()):
            incoming[key.split("/", 1)[0]].add(link["predicate"])
        for key, entry in sorted(entries.items()):
            if entry["status"] != "present":
                continue
            entry = {**entry, "entity_key": key}
            kind = entry["kind"]
            topic_counts[topic] += 1
            kind_counts[(topic, kind)] += 1
            all_entries[key] = entry
            names[(topic, kind, entry["name"])].append(key)
            if kind == "item" and not incoming[key].intersection(SOURCE_PREDICATES):
                add("no_source_items", flag_row(topic, entry))
            source_id = provenance.get(entry.get("provenance_id"), {}).get("source_id") or ""
            if DEBUG.search(entry["name"]) or DEBUG.search(source_id):
                add("debug_names", {**flag_row(topic, entry, value=entry["name"]),
                                    "source_id": source_id})
            semantic = semantics[entry["revision_id"]]
            for relation in semantic.get("relationships", []):
                for target in relation.get("targets", []):
                    relationships.append((topic, entry, relation["field"], target))
            for pointer, value in leaves(semantic.get("facts", {})):
                group = group_pointer(pointer)
                field_key = (topic, kind, group)
                state = inventory[field_key]
                if filled(value):
                    state["filled"].add(key)
                    state["values"].add(json_text(value))
                row = flag_row(topic, entry, pointer, value)
                if float_noise(value):
                    add("float_noise", row)
                if isinstance(value, str):
                    if any("\u3400" <= char <= "\u9fff" for char in value):
                        add("cjk_text", row)
                    if identifier(value):
                        add("identifier_value", row)
                    text = text_fields[field_key]
                    text["empty" if value == "" else "filled"].add(key)
                    if value == "" and text["example"] is None:
                        text["example"] = row
                    if value and set(value) == {"0"}:
                        sentinel[field_key]["zero"].append(row)
                    elif value:
                        sentinel[field_key]["nonzero"].add(key)

    for (topic, kind, name), keys in sorted(names.items()):
        if len(keys) > 1:
            add("duplicate_names", {**flag_row(topic, all_entries[keys[0]], value=name),
                                    "keys": sorted(keys)})
    for field_key, state in sorted(text_fields.items()):
        if state["empty"] and state["filled"]:
            add("empty_text", {**state["example"], "field": field_key[2],
                               "empty_count": len(state["empty"]),
                               "filled_count": len(state["filled"])})
    for field_key, state in sorted(sentinel.items()):
        if state["nonzero"]:
            for row in state["zero"]:
                if row["entity_key"] not in state["nonzero"]:
                    add("sentinel_string", row)
    for topic, entry, field, target in sorted(relationships,
                                              key=lambda row: (row[0], row[1]["entity_key"], row[2], row[3])):
        target_name = all_entries.get(target, {}).get("name", "")
        if not target_name or target_name == target or identifier(target_name):
            add("unreadable_targets", {**flag_row(topic, entry, field, target),
                                       "target_name": target_name})

    fields = []
    for (topic, kind, pointer), state in sorted(inventory.items()):
        values = sorted(state["values"])
        segment = next((part for part in reversed(pointer.split("/")) if part != "*"), "")
        label = field_label(segment)
        fields.append({"topic": topic, "kind": kind, "field": pointer,
                       "kind_count": kind_counts[(topic, kind)], "fill_count": len(state["filled"]),
                       "distinct_value_count": len(values),
                       "sample_values": [json.loads(value) for value in values[:5]],
                       "constant": len(values) == 1 and len(state["filled"]) >= 2,
                       "current_label": label,
                       "label_is_identifier": "_" in segment or bool(re.search(r"[a-z0-9][A-Z]", segment))
                       or bool(LETTER_DIGIT.search(label))})
    for name, flag in flags.items():
        rows = sorted(flag["examples"], key=lambda row: (
            row["kind"] != "item",
            not bool(LETTER_DIGIT.search(row["name"])) if name == "duplicate_names" else False,
            len(row["keys"]) if name == "duplicate_names" else 0,
            row["kind"], group_pointer(row["field"]), json_text(row["value"]),
            row["name"], row["entity_key"], json_text(row)))
        examples, seen = [], set()
        for row in rows:
            signature = (row["topic"], row["kind"], group_pointer(row["field"]),
                         json_text(row["value"]))
            if signature not in seen:
                examples.append(row)
                seen.add(signature)
                if len(examples) == 50:
                    break
        if len(examples) < 50:
            chosen = {id(row) for row in examples}
            examples.extend(row for row in rows if id(row) not in chosen)
        flag["examples"] = examples[:50]
    field_counts = Counter(field["kind"] for field in fields)
    for _, kind in kind_counts:
        field_counts[kind] += 0
    return {"summary": {"topics": [path.name for path in topics],
                        "entries": sum(topic_counts.values()), "kinds": len({kind for _, kind in kind_counts}),
                        "entries_per_topic": dict(sorted(topic_counts.items())),
                        "fields_per_kind": dict(sorted(field_counts.items())),
                        "flag_totals": {name: flags[name]["total"] for name in FLAG_NAMES}},
            "no_source_predicates": SOURCE_PREDICATES, "flags": flags, "field_inventory": fields}


def markdown(report):
    summary = report["summary"]
    lines = ["# Readability audit", "", "| Measure | Count |", "| --- | ---: |",
             f"| Topics | {len(summary['topics'])} |", f"| Entries | {summary['entries']} |",
             f"| Kinds | {summary['kinds']} |"]
    for topic, count in summary["entries_per_topic"].items():
        lines.append(f"| Entries: {topic} | {count} |")
    for kind, count in summary["fields_per_kind"].items():
        lines.append(f"| Fields: {kind} | {count} |")
    for name, count in summary["flag_totals"].items():
        lines.append(f"| Flag: {name} | {count} |")
    for name, flag in report["flags"].items():
        lines.extend(["", f"## {name} ({flag['total']})", "",
                      "| Topic | Kind | Entity | Name | Field | Value |",
                      "| --- | --- | --- | --- | --- | --- |"])
        for row in flag["examples"][:20]:
            cells = [row.get(key, "") for key in ("topic", "kind", "entity_key", "name", "field")]
            value = {key: val for key, val in row.items()
                     if key not in {"topic", "kind", "entity_key", "name", "field"}}
            cells.append(json_text(value))
            lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ")
                                           for cell in cells) + " |")
    lines.extend(["", "## Field inventory", "",
                  "| Topic | Kind | Field | Filled / Total | Distinct | Constant | Current label | Identifier label | Samples |",
                  "| --- | --- | --- | ---: | ---: | --- | --- | --- | --- |"])
    for row in report["field_inventory"]:
        if row["kind"] not in MARKDOWN_KINDS:
            continue
        cells = [row["topic"], row["kind"], row["field"],
                 f"{row['fill_count']} / {row['kind_count']}", row["distinct_value_count"],
                 str(row["constant"]).lower(), row["current_label"],
                 str(row["label_is_identifier"]).lower(), json_text(row["sample_values"])]
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ")
                                       for cell in cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repositories", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    repositories, out = args.repositories.resolve(), args.out.resolve()
    if not repositories.is_dir():
        parser.error(f"repositories directory does not exist: {repositories}")
    if out.is_relative_to(repositories):
        parser.error("--out must be outside --repositories")
    report = audit(repositories)
    out.mkdir(parents=True, exist_ok=True)
    (out / "readability.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / "readability.md").write_text(markdown(report), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
