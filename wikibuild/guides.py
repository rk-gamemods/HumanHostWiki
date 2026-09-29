"""Validate guide specs and render query results without embedding markup.

Document payloads: ``sentence`` and ``sources`` have ``runs``; ungrouped
``list``, ``checklist``, ``steps`` and ``definitions`` have ``items`` (lists of
runs); ``table`` has ``columns`` and ``rows`` (column-name to runs mappings).
Grouped row blocks have ``groups`` instead of ``items`` or ``rows``. Each group
has ``label`` runs, ``items`` or ``rows``, and optional ``more`` runs. An empty
fallback uses ``runs`` on any block type. A run is ``{"text": str}`` or
``{"text": str, "entity": "e-<32 hex>"}``.
"""

from __future__ import annotations

import json
import re
import string
from pathlib import Path


class GuideError(ValueError):
    """A spec or query result cannot be rendered as a guide."""


_TOP_KEYS = {"schema_version", "id", "title", "dek", "audience", "rule", "sections"}
_SECTION_KEYS = {"id", "heading", "blocks", "repeat"}
_BLOCK_KEYS = {
    "type", "title", "template", "query", "item", "columns", "group_by",
    "limit_per_group", "more", "empty", "optional",
}
_ROW_TYPES = {"list", "checklist", "steps", "table", "definitions"}
_TYPES = _ROW_TYPES | {"sentence", "sources"}
_ENTITY = re.compile(r"e-[0-9a-fA-F]{32}\Z")
_FIELD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
_FORMATTER = string.Formatter()


def _error(where, message):
    raise GuideError(f"{where}: {message}")


def _keys(value, allowed, required, where):
    if not isinstance(value, dict):
        _error(where, "expected an object")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        _error(where, f"unknown keys: {', '.join(sorted(unknown))}")
    if missing:
        _error(where, f"missing keys: {', '.join(sorted(missing))}")


def _nonempty_string(value, where):
    if not isinstance(value, str) or not value:
        _error(where, "expected a non-empty string")


def _template(value, where):
    _nonempty_string(value, where)
    try:
        parts = list(_FORMATTER.parse(value))
    except ValueError as exc:
        _error(where, f"invalid template: {exc}")
    for _, field, format_spec, conversion in parts:
        if field is not None and (not _FIELD.fullmatch(field) or format_spec or conversion):
            _error(where, f"invalid template field: {field!r}")


def _validate(spec):
    _keys(spec, _TOP_KEYS, {"id", "title", "sections"}, "guide")
    guide = spec["id"]
    _nonempty_string(guide, "guide id")
    _nonempty_string(spec["title"], f"guide {guide} title")
    for key in ("dek", "audience", "rule"):
        if key in spec and not isinstance(spec[key], str):
            _error(f"guide {guide}", f"{key} must be a string")
    if "schema_version" in spec and (type(spec["schema_version"]) is not int or spec["schema_version"] != 1):
        _error(f"guide {guide}", "unsupported schema_version")
    if not isinstance(spec["sections"], list):
        _error(f"guide {guide}", "sections must be a list")
    ids = set()
    for section in spec["sections"]:
        _keys(section, _SECTION_KEYS, {"id", "heading", "blocks"}, f"guide {guide} section")
        sid = section["id"]
        _nonempty_string(sid, f"guide {guide} section id")
        where = f"guide {guide} section {sid}"
        if sid in ids:
            _error(where, "duplicate section id")
        ids.add(sid)
        _template(section["heading"], f"{where} heading")
        if "repeat" in section:
            _nonempty_string(section["repeat"], f"{where} repeat")
        if not isinstance(section["blocks"], list):
            _error(where, "blocks must be a list")
        for number, block in enumerate(section["blocks"]):
            bwhere = f"{where} block {number}"
            _keys(block, _BLOCK_KEYS, {"type"}, bwhere)
            kind = block["type"]
            if not isinstance(kind, str) or kind not in _TYPES:
                _error(bwhere, f"unknown block type: {kind!r}")
            required = {"template"} if kind in {"sentence", "sources"} else {"columns"} if kind == "table" else {"item"}
            if kind != "sources":
                required.add("query")
            _keys(block, _BLOCK_KEYS, required | {"type"}, bwhere)
            for key in required - {"columns"}:
                if key in {"template", "item"}:
                    _template(block[key], f"{bwhere} {key}")
                else:
                    _nonempty_string(block[key], f"{bwhere} {key}")
            if "columns" in block:
                columns = block["columns"]
                if (kind != "table" or not isinstance(columns, list) or not columns
                        or any(not isinstance(column, str) or not column for column in columns)
                        or len(columns) != len(set(columns))):
                    _error(bwhere, "columns must be a non-empty list of unique names on a table")
                for column in columns:
                    _nonempty_string(column, f"{bwhere} column")
            for key in ("title", "group_by", "empty"):
                if key in block:
                    _nonempty_string(block[key], f"{bwhere} {key}")
            if "more" in block:
                _template(block["more"], f"{bwhere} more")
            if "optional" in block and type(block["optional"]) is not bool:
                _error(bwhere, "optional must be a boolean")
            if "limit_per_group" in block and (type(block["limit_per_group"]) is not int or block["limit_per_group"] < 1):
                _error(bwhere, "limit_per_group must be a positive integer")
            if kind not in _ROW_TYPES and any(k in block for k in ("group_by", "limit_per_group", "more")):
                _error(bwhere, "grouping requires a row block")
            if "limit_per_group" in block and "group_by" not in block:
                _error(bwhere, "limit_per_group requires group_by")
            if "more" in block and "limit_per_group" not in block:
                _error(bwhere, "more requires limit_per_group")
            if kind == "sources" and "query" in block:
                _error(bwhere, "sources cannot have a query")
            if kind not in {"sentence", "sources"} and "template" in block:
                _error(bwhere, "template belongs to sentence or sources")
            if kind not in _ROW_TYPES and ("item" in block or "columns" in block):
                _error(bwhere, "row fields belong to row blocks")


def load_spec(path) -> dict:
    """Read and validate one UTF-8 JSON guide specification."""
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GuideError(f"guide {path}: {exc}") from exc
    _validate(spec)
    return spec


def _pieces(value, where):
    if isinstance(value, list):
        result = []
        for index, part in enumerate(value):
            if index:
                result.append({"text": ", "})
            result.extend(_pieces(part, where))
        return result
    if isinstance(value, dict):
        if set(value) != {"text", "entity"} or not isinstance(value["text"], str) or not isinstance(value["entity"], str) or not _ENTITY.fullmatch(value["entity"]):
            _error(where, "invalid link value")
        return [{"text": value["text"], "entity": value["entity"]}]
    if isinstance(value, str) or (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return [{"text": str(value)}]
    _error(where, f"invalid template value: {type(value).__name__}")


def _join_runs(pieces):
    runs = []
    for piece in pieces:
        if not piece["text"]:
            continue
        if runs and "entity" not in piece and "entity" not in runs[-1]:
            runs[-1]["text"] += piece["text"]
        else:
            runs.append(piece.copy())
    return runs


def _fill(template, values, where):
    pieces = []
    for literal, field, _, _ in _FORMATTER.parse(template):
        pieces.append({"text": literal})
        if field is not None:
            if field not in values:
                _error(where, f"missing variable {field!r}")
            pieces.extend(_pieces(values[field], where))
    return _join_runs(pieces)


def _query(queries, name, context, scope, where):
    try:
        function = queries[name]
    except KeyError:
        _error(where, f"unknown query {name!r}")
    if not callable(function):
        _error(where, f"query {name!r} is not callable")
    return function(context, scope)


def _rows(value, where):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        _error(where, "query must return a list of row objects")
    return value


def _render_rows(block, rows, where):
    kind = block["type"]
    if kind == "table":
        columns = block["columns"]
        return [{column: _fill("{" + column + "}", row, where) for column in columns} for row in rows]
    return [_fill(block["item"], row, where) for row in rows]


def _render_block(block, queries, context, scope, where):
    kind = block["type"]
    result = {"type": kind}
    if "title" in block:
        result["title"] = block["title"]
    if kind == "sources":
        snapshot = context["snapshot"]
        result["runs"] = _fill(block["template"], snapshot, where)
        return result
    value = _query(queries, block["query"], context, scope, where)
    if kind == "sentence":
        empty = value is None
        if not empty and not isinstance(value, dict):
            _error(where, "sentence query must return an object or None")
    else:
        rows = _rows(value, where)
        empty = not rows
    if empty:
        if "empty" in block:
            result["runs"] = _fill(block["empty"], {}, where)
            return result
        if block.get("optional", False):
            return None
        _error(where, "required query returned no content")
    if kind == "sentence":
        result["runs"] = _fill(block["template"], value, where)
        return result
    if kind == "table":
        result["columns"] = block["columns"][:]
    payload = "rows" if kind == "table" else "items"
    if "group_by" not in block:
        result[payload] = _render_rows(block, rows, where)
        return result
    groups = []
    by_label = {}
    for row in rows:
        key = block["group_by"]
        if key not in row:
            _error(where, f"missing group field {key!r}")
        label = _join_runs(_pieces(row[key], where))
        display = "".join(run["text"] for run in label)
        if display not in by_label:
            group = {"label": label, payload: []}
            by_label[display] = group
            groups.append(group)
        by_label[display][payload].append(row)
    for group in groups:
        group_rows = group[payload]
        limit = block.get("limit_per_group", len(group_rows))
        group[payload] = _render_rows(block, group_rows[:limit], where)
        remaining = len(group_rows) - limit
        if remaining > 0:
            group["more"] = _fill(block.get("more", "{remaining} more"), {"remaining": remaining}, where)
    result["groups"] = groups
    return result


def render(spec, queries, context) -> dict:
    """Render a validated spec with caller-supplied query functions."""
    _validate(spec)
    guide = spec["id"]
    try:
        snapshot = context["snapshot"]
        if not isinstance(snapshot, dict):
            raise KeyError("snapshot")
        output_snapshot = {key: snapshot[key] for key in ("game_version", "build_id")}
    except (KeyError, TypeError) as exc:
        _error(f"guide {guide}", f"missing snapshot field {exc}")
    document = {"id": guide, "title": spec["title"], "dek": spec.get("dek", ""), "sections": [], "snapshot": output_snapshot}
    for section in spec["sections"]:
        sid = section["id"]
        where = f"guide {guide} section {sid}"
        scopes = [{}]
        if "repeat" in section:
            scopes = _rows(_query(queries, section["repeat"], context, {}, where), where)
        for index, scope in enumerate(scopes):
            section_id = f"{sid}-{index}" if "repeat" in section else sid
            instance_where = f"guide {guide} section {section_id}"
            rendered = {"id": section_id, "heading": _fill(section["heading"], scope, instance_where), "blocks": []}
            for number, block in enumerate(section["blocks"]):
                item = _render_block(block, queries, context, scope, f"{instance_where} block {number} ({block['type']})")
                if item is not None:
                    rendered["blocks"].append(item)
            if rendered["blocks"] or sid == "sources":
                document["sections"].append(rendered)
    return document


def _escape(text, *, cell=False):
    text = text.replace("\\", "\\\\")
    for character in ("*", "_", "[", "]", "`", "<", ">"):
        text = text.replace(character, "\\" + character)
    if cell:
        text = text.replace("|", "\\|").replace("\n", " ")
    return text


def _markdown_runs(runs, href, *, cell=False):
    parts = []
    for run in runs:
        label = _escape(run["text"], cell=cell)
        if "entity" in run:
            parts.append(f"[{label}]({href(run['entity'])})")
        else:
            parts.append(label)
    return "".join(parts)


def _definition(runs, href):
    label = []
    meaning = []
    target = label
    for run in runs:
        if target is label and ": " in run["text"]:
            before, after = run["text"].split(": ", 1)
            if before:
                label.append({**run, "text": before})
            if after:
                meaning.append({**run, "text": after})
            target = meaning
        else:
            target.append(run)
    if target is label:
        return _markdown_runs(runs, href)
    return f"**{_markdown_runs(label, href)}**: {_markdown_runs(meaning, href)}"


def _markdown_items(kind, items, href):
    lines = []
    for item in items:
        content = _definition(item, href) if kind == "definitions" else _markdown_runs(item, href)
        marker = "- [ ] " if kind == "checklist" else "1. " if kind == "steps" else "- "
        lines.append(marker + content)
    return lines


def _markdown_table(columns, rows, href):
    lines = ["| " + " | ".join(_escape(c, cell=True) for c in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_runs(row[c], href, cell=True) for c in columns) + " |")
    return lines


def render_markdown(document, href) -> str:
    """Render a guide document as readable Markdown with entity links."""
    lines = ["# " + _escape(document["title"])]
    if document.get("dek"):
        lines.extend(["", _escape(document["dek"])])
    for section in document["sections"]:
        lines.extend(["", "## " + _markdown_runs(section["heading"], href)])
        for block in section["blocks"]:
            lines.append("")
            if "title" in block:
                lines.extend(["### " + _escape(block["title"]), ""])
            if "runs" in block:
                lines.append(_markdown_runs(block["runs"], href))
                continue
            kind = block["type"]
            if "groups" in block:
                for number, group in enumerate(block["groups"]):
                    if number:
                        lines.append("")
                    lines.append("#### " + _markdown_runs(group["label"], href))
                    lines.append("")
                    if kind == "table":
                        lines.extend(_markdown_table(block["columns"], group["rows"], href))
                    else:
                        lines.extend(_markdown_items(kind, group["items"], href))
                    if "more" in group:
                        lines.extend(["", _markdown_runs(group["more"], href)])
            elif kind == "table":
                lines.extend(_markdown_table(block["columns"], block["rows"], href))
            else:
                lines.extend(_markdown_items(kind, block["items"], href))
    return "\n".join(lines) + "\n"


def text_runs(document):
    """Yield JSON pointers and visible text from every guide text location."""
    for key in ("title", "dek"):
        if key in document:
            yield f"/{key}", document[key]
    for si, section in enumerate(document["sections"]):
        base = f"/sections/{si}"
        for ri, run in enumerate(section["heading"]):
            yield f"{base}/heading/{ri}/text", run["text"]
        for bi, block in enumerate(section["blocks"]):
            path = f"{base}/blocks/{bi}"
            if "title" in block:
                yield f"{path}/title", block["title"]
            if "runs" in block:
                for ri, run in enumerate(block["runs"]):
                    yield f"{path}/runs/{ri}/text", run["text"]
                continue
            if "columns" in block:
                for ci, column in enumerate(block["columns"]):
                    yield f"{path}/columns/{ci}", column
            groups = block.get("groups")
            containers = [(path, block)] if groups is None else [(f"{path}/groups/{gi}", group) for gi, group in enumerate(groups)]
            for prefix, container in containers:
                for field in ("label", "more"):
                    for ri, run in enumerate(container.get(field, [])):
                        yield f"{prefix}/{field}/{ri}/text", run["text"]
                for field in ("items", "rows"):
                    for row_index, row in enumerate(container.get(field, [])):
                        if isinstance(row, dict):
                            for column, runs in row.items():
                                escaped = column.replace("~", "~0").replace("/", "~1")
                                for ri, run in enumerate(runs):
                                    yield f"{prefix}/{field}/{row_index}/{escaped}/{ri}/text", run["text"]
                        else:
                            for ri, run in enumerate(row):
                                yield f"{prefix}/{field}/{row_index}/{ri}/text", run["text"]
