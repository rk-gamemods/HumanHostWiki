"""Resolve item tooltip labels from one snapshot's model rows, without I/O."""


def labels(model_rows):
    """Return member names mapped to unambiguous English Language_Text facts.

    Rows use model.project's entity_key/semantic/provenance shape. Repeated
    tooltip sets must agree; missing, unresolved or conflicting text is omitted.
    Source relationship paths retain the serialized /data wrapper.
    """
    rows = list(model_rows)
    by_entity = {row["entity_key"]: row for row in rows}
    candidates = {}
    for row in rows:
        if row.get("provenance", {}).get("component") != {"assembly": "UI", "class": "DynamicToolTipSet"}:
            continue
        for link in row["semantic"].get("relationships", []):
            if link["predicate"] != "tooltip-text":
                continue
            field = link["field"]
            member = field.removeprefix("/data/") if field.startswith("/data/") else field.removeprefix("/")
            if not member or "/" in member:
                continue
            text = None
            targets = link.get("targets", [])
            if len(targets) == 1 and not link.get("gaps") and not link.get("technical_targets"):
                target = by_entity.get(targets[0], {})
                if target.get("provenance", {}).get("component") == {"assembly": "Language", "class": "Language_Text"}:
                    value = target["semantic"]["facts"].get("text")
                    if isinstance(value, str):
                        text = value
            candidates.setdefault(member, set()).add(text)
    return {member: next(iter(values)) for member, values in sorted(candidates.items())
            if len(values) == 1 and None not in values}
