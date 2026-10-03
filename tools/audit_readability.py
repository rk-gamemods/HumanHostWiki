"""Deterministic, read-only inventory of the released public reader packs."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import json
import math
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wikibuild.lint import card_findings, jargon


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
WALK_FIXED = (
    ("items-equipment", "e-045871a35c62b6aa04edaddb21311d64", "Crude Axe"),
    ("items-equipment", "e-803183af8309a1cafa059d159bc19440", "M1891"),
    ("items-equipment", "e-4a99806629a6f91085258cc598e7d8c6", "M1891 (second record)"),
    ("combat", "e-48ad79eff54f66a6d7e47cb9ee2207ee", "M1891_01"),
    ("crafting-processing", "e-f98a0303b71ff71009057e8de511e96d", "recipe"),
    ("items-equipment", "e-77168f52db5f228bedfc3deb4b3e791d", "Ammo Type 7.62x54mm"),
)
WALK_LIMIT = 24
WALK_METRICS = ("visible_lines", "facts_visible", "relationships", "one_click_leaves",
                "jargon_tokens", "raw_floats", "bare_numbers", "identifier_labels", "jargon_ratio")
JARGON = re.compile(r"_|[0-9a-f]{8,}|e-[0-9a-f]+|::", re.I)
CAMEL_CASE = re.compile(r"[a-z0-9][A-Z]")
RAW_FLOAT = re.compile(r"(?<![\w.])\d+\.(\d+)(?![\w.])")
BARE_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")


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


def visible_value(value):
    if value is None:
        return "Not set"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list)):
        if not value:
            return "None recorded"
        return f"{len(value)} {'entries' if isinstance(value, list) else 'fields'}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def nested_leaves(value):
    if isinstance(value, dict):
        return sum(nested_leaves(child) for child in value.values())
    if isinstance(value, list):
        return sum(nested_leaves(child) for child in value)
    return 1


def jargon_token(token):
    return bool(JARGON.search(token) or CAMEL_CASE.search(token) or
                ("/" in token and FILE_PATH.search(token)))


def walk_page(topic, key, record, semantic, snapshot):
    name = record["name"]
    lines = [record["kind"].replace("-", " "), name]
    for label, value in (("Snapshot", snapshot), ("Status", record.get("status")),
                         ("Last substantive change", record.get("last_changed")),
                         ("Last data check", record.get("last_data_checked")),
                         ("Last gameplay verification", record.get("last_verified") or "Not performed")):
        lines.append(f"{label}: {value or 'Not recorded'}")
    lines.append(f"Evidence: {semantic.get('evidence_level', 'Not recorded')}")
    notes = semantic.get("notes") or []
    for note in notes if isinstance(notes, list) else [notes]:
        lines.append(str(note).replace("\n", " "))
    if semantic.get("fact_scope"):
        lines.append(f"Scope: {semantic['fact_scope']}")
    lines.append("Extracted facts")
    facts = semantic.get("facts", {})
    labels = semantic.get("fact_labels", {})
    one_click_leaves = 0
    bare_numbers = 0
    identifier_labels = 0
    for field, value in facts.items():
        pointer = "/" + field
        shown = visible_value(labels.get(pointer, value))
        lines.append(f"{field_label(field)}: {shown}")
        if pointer not in labels and isinstance(value, (dict, list)) and value:
            one_click_leaves += nested_leaves(value)
        bare_numbers += bool(BARE_NUMBER.fullmatch(shown))
        identifier_labels += "_" in field or bool(CAMEL_CASE.search(field))
    lines.append("Relationships")
    relations = semantic.get("relationships", [])
    for relation in relations:
        targets = [record.get("links", {}).get(target, {}).get("name", target)
                   for target in relation.get("targets", [])]
        targets.extend("Technical summary: " + record.get("links", {}).get(target, {}).get("name", target)
                       for target in relation.get("technical_targets", []))
        if not targets and not relation.get("gaps"):
            targets.append("No target recorded")
        lines.append(f"{relation['predicate'].replace('-', ' ')}: {', '.join(targets)} "
                     f"Source field: {relation['field']}")
    if record.get("backlink_count"):
        lines.append(f"Referenced by {record['backlink_count']} relationships")
    jargon_tokens = 0
    for index, line in enumerate(lines):
        if index == 1:
            continue
        head, separator, _ = line.partition(" Source field: ")
        jargon_tokens += sum(jargon_token(token) for token in head.split())
        jargon_tokens += bool(separator)
    all_tokens = sum(len(line.split()) for line in lines)
    raw_floats = sum(len(match.group(1).lstrip("0").rstrip("0")) > 4
                     for line in lines for match in RAW_FLOAT.finditer(line))
    return {"key": key, "topic": topic, "kind": record["kind"], "name": name,
            "visible_lines": len(lines), "facts_visible": len(facts),
            "relationships": len(relations), "one_click_leaves": one_click_leaves,
            "jargon_tokens": jargon_tokens, "raw_floats": raw_floats,
            "bare_numbers": bare_numbers, "identifier_labels": identifier_labels,
            "jargon_ratio": round(jargon_tokens / all_tokens, 4) if all_tokens else 0.0,
            "lines": lines}


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
    walk_fixed = {}
    walk_candidates = {}
    fixed_keys = {(topic, key) for topic, key, _ in WALK_FIXED}

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
        snapshot = config["default_snapshot"]
        index = read(site / config["snapshots"][snapshot]["path"])
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
            page = (topic, key, entry, semantic, snapshot)
            if (topic, key) in fixed_keys:
                walk_fixed[(topic, key)] = page
            walk_candidates.setdefault((topic, kind), page)
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
    selected = []
    missing = []
    chosen = set()
    for topic, key, name in WALK_FIXED:
        page = walk_fixed.get((topic, key))
        if page is None:
            missing.append({"topic": topic, "key": key, "name": name})
        elif key not in chosen:
            selected.append(page)
            chosen.add(key)
    for topic in sorted(topic_counts):
        kinds = sorted((kind for owner, kind in kind_counts if owner == topic),
                       key=lambda kind: (-kind_counts[(topic, kind)], kind))
        for kind in kinds[:2]:
            if len(selected) >= WALK_LIMIT:
                break
            page = walk_candidates[(topic, kind)]
            if page[1] not in chosen:
                selected.append(page)
                chosen.add(page[1])
        if len(selected) >= WALK_LIMIT:
            break
    walk = [walk_page(*page) for page in selected]
    return {"summary": {"topics": [path.name for path in topics],
                        "entries": sum(topic_counts.values()), "kinds": len({kind for _, kind in kind_counts}),
                        "entries_per_topic": dict(sorted(topic_counts.items())),
                        "fields_per_kind": dict(sorted(field_counts.items())),
                        "flag_totals": {name: flags[name]["total"] for name in FLAG_NAMES}},
            "no_source_predicates": SOURCE_PREDICATES, "flags": flags, "field_inventory": fields,
            "walk": walk, "walk_missing": missing}


def audit_cards(candidate):
    """Inspect current cards in a reader candidate without rebuilding them."""
    registry = read(Path(__file__).resolve().parents[1] / "presentation" / "fields.json")
    definitions = registry["kinds"]
    registered = carded = stats = 0
    unclassified = Counter()
    missing_text = Counter()
    rule_counts = Counter()
    jargon_rows = []
    name_rows = []
    topics = sorted(path for path in candidate.iterdir() if path.is_dir() and (path / "reader.json").is_file())
    if not topics:
        raise ValueError(f"candidate has no topic readers: {candidate}")
    for site in topics:
        config = read(site / "reader.json")
        snapshot = config["default_snapshot"]
        index_path = (config.get("snapshots") or {}).get(snapshot, {}).get(
            "path", f"snapshots/{snapshot}.json")
        index = read(site / index_path)
        entries = pack_map(site, index, "entries")
        cards = pack_map(site, index, "cards")
        for entity, entry in sorted(entries.items()):
            if entry.get("status") != "present" or entry.get("kind") not in definitions:
                continue
            registered += 1
            card_id = entry.get("card_id")
            if card_id is None:
                continue
            carded += 1
            card = cards[card_id]
            kind = entry["kind"]
            fields = definitions[kind]["fields"]
            coded_fields = {pointer for pointer, spec in fields.items()
                            if spec.get("format") == "coded" or
                            any(case.get("format") == "coded" for case in spec.get("cases", []))}
            stats += len(card.get("stats", []))
            for field in card.get("technical", []):
                if field not in fields:
                    unclassified[(kind, field)] += 1
            missing_text.update(set(card.get("missing_game_text", [])))
            name = entry["name"]
            for finding in card_findings(card, coded_fields=coded_fields):
                rule_counts[finding["rule"]] += 1
                jargon_rows.append({"entity": entity, "name": name, "field": finding["field"],
                                    "rule": finding["rule"], "match": finding["match"]})
            name_hits = jargon(name)
            if name_hits:
                name_rows.append({"entity": entity, "name": name, "topic": site.name,
                                  "findings": name_hits})
    jargon_rows.sort(key=lambda row: (row["entity"], row["field"], row["rule"], row["match"]))
    name_rows.sort(key=lambda row: (row["entity"], row["topic"]))
    return {
        "counts": {"entries_registered_kind": registered, "entries_with_card": carded,
                   "player_stats_total": stats},
        "unclassified_fields": [{"kind": kind, "field": field, "count": count}
                                for (kind, field), count in sorted(unclassified.items(),
                                                                   key=lambda item: (-item[1], *item[0]))],
        "missing_game_text": [{"key": key, "count": count}
                              for key, count in sorted(missing_text.items(),
                                                       key=lambda item: (-item[1], item[0]))],
        "jargon": {"total": sum(rule_counts.values()), "by_rule": dict(sorted(rule_counts.items())),
                   "examples": jargon_rows[:50]},
        "names": {"total": len(name_rows), "examples": name_rows[:50]},
    }


def walk_markdown(report):
    lines = ["## Page walk", ""]
    if report["walk_missing"]:
        lines.append("Missing fixed keys: " + ", ".join(row["key"] for row in report["walk_missing"]))
        lines.append("")
    columns = ("Key", "Topic", "Kind", "Name", *WALK_METRICS)
    lines.extend(["| " + " | ".join(columns) + " |",
                  "| " + " | ".join("---:" if column in WALK_METRICS else "---"
                                   for column in columns) + " |"])
    for page in report["walk"]:
        cells = [page["key"], page["topic"], page["kind"], page["name"]]
        cells.extend(f"{page['jargon_ratio']:.4f}" if metric == "jargon_ratio"
                     else str(page[metric]) for metric in WALK_METRICS)
        lines.append("| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ")
                                       for cell in cells) + " |")
    for page in report["walk"]:
        fence = "`" * max(3, 1 + max((len(match.group()) for line in page["lines"]
                                       for match in re.finditer(r"`+", line)), default=0))
        lines.extend(["", f"### {page['name']} ({page['key']})", "", fence + "text",
                      *page["lines"], fence])
    return "\n".join(lines) + "\n"


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
    result = "\n".join(lines) + "\n" + "\n" + walk_markdown(report)
    if "cards" in report:
        result += cards_markdown(report["cards"])
    return result


def cards_markdown(cards):
    counts = cards["counts"]
    lines = ["", "## Cards", "", "| Measure | Count |", "| --- | ---: |",
             f"| Entries with a registered kind | {counts['entries_registered_kind']} |",
             f"| Entries with a card | {counts['entries_with_card']} |",
             f"| Player stats | {counts['player_stats_total']} |",
             f"| Jargon findings | {cards['jargon']['total']} |",
             f"| Names with jargon | {cards['names']['total']} |",
             "", "### Unclassified fields", "", "| Kind | Field | Count |",
             "| --- | --- | ---: |"]
    for row in cards["unclassified_fields"]:
        lines.append(f"| {row['kind']} | {row['field']} | {row['count']} |")
    lines.extend(["", "### Missing game text", "", "| Key | Count |", "| --- | ---: |"])
    for row in cards["missing_game_text"]:
        lines.append(f"| {row['key']} | {row['count']} |")
    lines.extend(["", "### Jargon examples", "", "| Entity | Name | Field | Rule | Match |",
                  "| --- | --- | --- | --- | --- |"])
    for row in cards["jargon"]["examples"]:
        lines.append("| " + " | ".join(str(row[key]).replace("|", "\\|").replace("\n", " ")
                                         for key in ("entity", "name", "field", "rule", "match")) + " |")
    lines.extend(["", "### Names with jargon", "", "| Entity | Topic | Name | Findings |",
                  "| --- | --- | --- | --- |"])
    for row in cards["names"]["examples"]:
        lines.append("| " + " | ".join(str(value).replace("|", "\\|").replace("\n", " ")
                                         for value in (row["entity"], row["topic"], row["name"],
                                                       json_text(row["findings"]))) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repositories", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    repositories, out = args.repositories.resolve(), args.out.resolve()
    candidate = args.candidate.resolve() if args.candidate else None
    if not repositories.is_dir():
        parser.error(f"repositories directory does not exist: {repositories}")
    if out.is_relative_to(repositories):
        parser.error("--out must be outside --repositories")
    if candidate is not None:
        if not candidate.is_dir():
            parser.error(f"candidate directory does not exist: {candidate}")
        if out.is_relative_to(candidate):
            parser.error("--out must be outside --candidate")
    report = audit(repositories)
    if candidate is not None:
        report["cards"] = audit_cards(candidate)
    out.mkdir(parents=True, exist_ok=True)
    (out / "readability.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out / "readability.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    (out / "readability-walk.md").write_text(walk_markdown(report), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
