"""Pure player-card projection from the reviewed presentation registry."""

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


Registry = dict[str, Any]
_MISSING = object()
_TIERS = {"player", "technical", "hidden"}
_FORMATS = {
    "integer", "round2", "percent", "multiplier", "multiplier_list", "range",
    "text", "signed_text", "per_minute_from_seconds", "positive_integer",
    "yes_no", "coded", "flag", "repair_link", "ingredients", "handmade_ammo",
}
_ENTRY_KEYS = {
    "tier", "label", "format", "unit", "omit", "order", "require", "note",
    "positional", "cases", "evidence",
}


def _pointer(pointer: Any, key: str) -> None:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"{key}: invalid field pointer")


def _conditions(value: Any, key: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{key}: expected an object")
    for pointer, expected in value.items():
        _pointer(pointer, key)
        if isinstance(expected, (dict, list)) and (
            isinstance(expected, dict) or not expected or any(isinstance(v, (dict, list)) for v in expected)
        ):
            raise ValueError(f"{key}.{pointer}: invalid condition")


def _entry(entry: Any, key: str, *, position: bool = False) -> None:
    if not isinstance(entry, dict):
        raise ValueError(f"{key}: expected an object")
    allowed = (_ENTRY_KEYS - {"cases", "positional", "evidence", "require"}) | {"index"} if position else _ENTRY_KEYS
    for name in entry.keys() - allowed:
        raise ValueError(f"{key}.{name}: unknown key")
    if "tier" in entry and (not isinstance(entry["tier"], str) or entry["tier"] not in _TIERS):
        raise ValueError(f"{key}.tier: unknown tier {entry['tier']!r}")
    if "format" in entry and (not isinstance(entry["format"], str) or entry["format"] not in _FORMATS):
        raise ValueError(f"{key}.format: unknown format {entry['format']!r}")
    if "label" in entry:
        label = entry["label"]
        if (not isinstance(label, dict) or not isinstance(label.get("fallback"), str)
                or any(not isinstance(label.get(name), str) for name in ("game", "game_key") if name in label)
                or set(label) - {"game", "game_key", "fallback"}):
            raise ValueError(f"{key}.label: invalid label")
    if "unit" in entry and not isinstance(entry["unit"], str):
        raise ValueError(f"{key}.unit: expected text")
    if "order" in entry and (isinstance(entry["order"], bool) or not isinstance(entry["order"], (int, float))):
        raise ValueError(f"{key}.order: expected a number")
    if "omit" in entry:
        rules = entry["omit"]
        if not isinstance(rules, list):
            raise ValueError(f"{key}.omit: expected a list")
        for rule in rules:
            if rule in ("zero", "empty"):
                continue
            if isinstance(rule, dict) and len(rule) == 1:
                name, threshold = next(iter(rule.items()))
                if name == "equals" or (name == "max_below" and _number(threshold)):
                    continue
            raise ValueError(f"{key}.omit: unknown rule {rule!r}")
    if "require" in entry:
        _conditions(entry["require"], f"{key}.require")
    if "note" in entry:
        note = entry["note"]
        if (not isinstance(note, dict) or not isinstance(note.get("game"), str)
                or set(note) - {"game", "cases"}
                or ("cases" in note and (not isinstance(note["cases"], dict)
                    or any(not isinstance(k, str) or not isinstance(v, str) for k, v in note["cases"].items())))):
            raise ValueError(f"{key}.note: invalid note")
    if position:
        if isinstance(entry.get("index"), bool) or not isinstance(entry.get("index"), int) or entry["index"] < 0:
            raise ValueError(f"{key}.index: expected a nonnegative integer")
    if "positional" in entry:
        positions = entry["positional"]
        if not isinstance(positions, list):
            raise ValueError(f"{key}.positional: expected a list")
        indexes = set()
        for index, item in enumerate(positions):
            _entry(item, f"{key}.positional[{index}]", position=True)
            if item["index"] in indexes:
                raise ValueError(f"{key}.positional[{index}].index: duplicate")
            indexes.add(item["index"])
    if "cases" in entry:
        cases = entry["cases"]
        if not isinstance(cases, list):
            raise ValueError(f"{key}.cases: expected a list")
        for index, case in enumerate(cases):
            case_key = f"{key}.cases[{index}]"
            if (not isinstance(case, dict) or not isinstance(case.get("when"), dict)
                    or not case["when"] or len(case) < 2
                    or set(case) - (_ENTRY_KEYS - {"cases", "evidence"}) - {"when"}):
                raise ValueError(f"{case_key}.when: invalid case shape")
            _conditions(case["when"], f"{case_key}.when")
            _entry({k: v for k, v in case.items() if k != "when"}, case_key)


def load(path: str | Path) -> Registry:
    """Read and validate a presentation registry."""
    registry = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        raise ValueError("schema_version: expected 1")
    if not isinstance(registry.get("kinds"), dict):
        raise ValueError("kinds: expected an object")
    if not isinstance(registry.get("glossaries"), dict):
        raise ValueError("glossaries: expected an object")
    for name in registry.get("formats", {}):
        if name not in _FORMATS:
            raise ValueError(f"formats.{name}: unknown format")
    for kind, definition in registry["kinds"].items():
        if not isinstance(definition, dict) or not isinstance(definition.get("fields"), dict):
            raise ValueError(f"kinds.{kind}.fields: expected an object")
        for pointer, entry in definition["fields"].items():
            key = f"kinds.{kind}.fields.{pointer}"
            _pointer(pointer, key)
            _entry(entry, key)
    return registry


def _lookup(facts: dict, pointer: str) -> Any:
    value = facts
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value.get(part, _MISSING)
        elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
            value = value[int(part)]
        else:
            return _MISSING
        if value is _MISSING:
            return _MISSING
    return value


def _number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _matches(facts: dict, labels: dict, conditions: dict, *, use_labels: bool) -> bool:
    for pointer, expected in conditions.items():
        allowed = expected if isinstance(expected, list) else [expected]
        values = [_lookup(facts, pointer)]
        if use_labels and pointer in labels:
            values.append(labels[pointer])
        if not any(value is not _MISSING and value in allowed for value in values):
            return False
    return True


def _omitted(value: Any, rules: list) -> bool:
    for rule in rules:
        if rule == "zero" and _number(value) and value == 0:
            return True
        if rule == "empty" and (value is None or value == "" or value == [] or value == {}):
            return True
        if isinstance(rule, dict):
            if "equals" in rule and value == rule["equals"]:
                return True
            if "max_below" in rule:
                maximum = value.get("y", _MISSING) if isinstance(value, dict) else value
                if _number(maximum) and maximum < rule["max_below"]:
                    return True
    return False


def _rounded(value: Any, places: int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _round2(value: Any) -> str:
    result = format(_rounded(value, 2), "f").rstrip("0").rstrip(".")
    return "0" if result in ("", "-0") else result


def _display(fmt: str, value: Any, pointer: str, labels: dict, semantic: dict, links: dict) -> str | None | object:
    if fmt in ("ingredients", "handmade_ammo", "flag"):
        return None
    if fmt == "repair_link":
        targets = (target for rel in semantic.get("relationships", []) if rel.get("predicate") == "repair-item"
                   for target in rel.get("targets", []))
        names = [links[target]["name"] for target in sorted(set(targets))
                 if target in links and isinstance(links[target].get("name"), str)]
        return names[0] if names else _MISSING
    if fmt == "integer":
        return f"{int(_rounded(value, 0)):,}"
    if fmt == "positive_integer":
        return f"{int(_rounded(abs(Decimal(str(value))), 0)):,}"
    if fmt == "round2":
        return _round2(value)
    if fmt == "percent":
        return _round2(Decimal(str(value)) * 100) + "%"
    if fmt == "multiplier":
        return "× " + _round2(value)
    if fmt == "multiplier_list":
        return ", ".join("× " + _round2(item) for item in value)
    if fmt == "range":
        start, end = _round2(value["x"]), _round2(value["y"])
        return start if start == end else start + "–" + end
    if fmt == "per_minute_from_seconds":
        return f"{int(_rounded(Decimal(60) / Decimal(str(value)), 0)):,} / min"
    if fmt == "yes_no":
        return "Yes" if value else "No"
    if fmt == "coded":
        value = labels.get(pointer, value)
    return str(value).strip()


def _game_string(game_text: dict, key: str, fallback: str | None, missing: set) -> str | None:
    value = game_text.get(key)
    if not isinstance(value, str):
        missing.add(key)
        return fallback
    return value.strip().rstrip(":").rstrip()


def _stat(pointer: str, value: Any, entry: dict, labels: dict, semantic: dict,
          game_text: dict, links: dict, stats: list, notes: list, pending: set, missing: set) -> None:
    if _omitted(value, entry.get("omit", [])):
        return
    fmt = entry["format"]
    display = _display(fmt, value, pointer, labels, semantic, links)
    if display is _MISSING:
        return
    label = entry["label"]
    game_key = label.get("game", label.get("game_key"))
    text = _game_string(game_text, game_key, label["fallback"], missing) if game_key else label["fallback"]
    if entry.get("unit") and display is not None:
        display += " " + entry["unit"]
    stats.append({"field": pointer, "label": text, "display": display, "order": entry.get("order", 0)})
    if fmt in ("ingredients", "handmade_ammo"):
        pending.add(pointer)
    if "note" in entry:
        note = entry["note"]
        note_key = note.get("cases", {}).get(str(value), note["game"])
        note_text = _game_string(game_text, note_key, None, missing)
        if note_text is not None:
            notes.append({"field": pointer, "text": note_text})


def card(registry: Registry, kind: str, semantic: dict, game_text: dict,
         links: dict | None = None) -> dict | None:
    """Project one semantic record into a deterministic player card."""
    definition = registry["kinds"].get(kind)
    if definition is None:
        return None
    facts = semantic.get("facts", {})
    labels = semantic.get("fact_labels") or {}
    links = links or {}
    eyebrow, stats, notes = [], [], []
    hidden, technical, pending, missing = set(), set(), set(), set()
    for spec in definition.get("card", {}).get("eyebrow", []):
        pointer = spec["field"]
        value = labels.get(pointer, _lookup(facts, pointer))
        glossary = registry["glossaries"][spec["glossary"]]
        wording = glossary.get(str(value)) if value is not _MISSING else None
        if wording is not None and wording not in eyebrow:
            eyebrow.append(wording)
    for pointer, base in definition["fields"].items():
        value = _lookup(facts, pointer)
        if value is _MISSING:
            continue
        entry = base.copy()
        for case in base.get("cases", []):
            if _matches(facts, labels, case["when"], use_labels=True):
                entry.update({key: val for key, val in case.items() if key != "when"})
                break
        if "require" in entry and any(_lookup(facts, key) != wanted
                                      for key, wanted in entry["require"].items()):
            continue
        tier = entry["tier"]
        if tier == "hidden":
            hidden.add(pointer)
        elif tier == "technical":
            technical.add(pointer)
        elif "positional" in entry:
            if isinstance(value, list):
                for position in entry["positional"]:
                    index = position["index"]
                    if index < len(value):
                        item = {**entry, **position}
                        item_pointer = f"{pointer}/{index}"
                        _stat(item_pointer, value[index], item, labels, semantic, game_text,
                              links, stats, notes, pending, missing)
        else:
            _stat(pointer, value, entry, labels, semantic, game_text,
                  links, stats, notes, pending, missing)
    registered = set(definition["fields"])
    technical.update("/" + key.replace("~", "~0").replace("/", "~1")
                     for key in facts if "/" + key.replace("~", "~0").replace("/", "~1") not in registered)
    result = {"eyebrow": eyebrow, "stats": sorted(stats, key=lambda stat: (stat["order"], stat["field"])),
              "notes": sorted(notes, key=lambda note: (note["field"], note["text"])),
              "hidden": sorted(hidden), "technical": sorted(technical), "missing_game_text": sorted(missing)}
    if pending:
        result["pending"] = sorted(pending)
    return result
