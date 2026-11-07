"""Cumulative per-topic change log: real semantic changes per captured game version.

The log replaces published history. Each entry compares the current identity run
with the newest earlier run captured from a different snapshot. Identity revisions
decide what changed; provenance, source ids and per-run bookkeeping never count.
Committed files under changes/ let the next update append without old state.
"""

from collections import Counter
from html import escape
import json
import re

from . import history, identity_migration, model, packs, snapshots
from .storage import ContractError, digest, json_bytes, within, write_changed

SCHEMA_VERSION = 1
# A changed value larger than this is summarized by size and hash, keeping each
# update's log in kilobytes even when a long list is rewritten.
VALUE_BYTES = 240
TOPIC = re.compile(r"[a-z][a-z0-9-]*")


def path(root, topic):
    if TOPIC.fullmatch(topic) is None:
        raise ContractError(f"Invalid change log topic: {topic}")
    return within(root, f"changes/{topic}.json")


def read(root, topic):
    target = path(root, topic)
    if not target.exists():
        return {"schema_version": SCHEMA_VERSION, "topic": topic, "versions": []}
    value = json.loads(target.read_bytes())
    snapshots_seen = [entry.get("snapshot_id") for entry in value.get("versions", [])]
    if (value.get("schema_version") != SCHEMA_VERSION or value.get("topic") != topic
            or not isinstance(value.get("versions"), list) or len(set(snapshots_seen)) != len(snapshots_seen)):
        raise ContractError(f"Invalid change log: {target}")
    return value


def run_record(root, run_id):
    """Read a run receipt without requiring its state or models to be retained."""
    target = within(root, f"identity/runs/{run_id}.json")
    if not target.exists():
        return None
    value = json.loads(target.read_text(encoding="utf-8"))
    if value.get("run_id") != run_id:
        raise ContractError("Identity run receipt differs")
    return value


def base_run(root, run):
    """Newest ancestor captured from another snapshot; corrections of one capture are skipped."""
    seen, current = {run["run_id"]}, run
    while current.get("parent_run"):
        if current["parent_run"] in seen:
            raise ContractError("Cycle in identity history")
        seen.add(current["parent_run"])
        current = run_record(root, current["parent_run"])
        if current is None:
            return None
        if current["snapshot_id"] != run["snapshot_id"]:
            return current
    return None


def retained(root, record):
    return within(root, record["path"]).is_file()


def flatten(value, prefix=""):
    if isinstance(value, dict) and value:
        for key in sorted(value):
            yield from flatten(value[key], prefix + "/" + str(key).replace("~", "~0").replace("/", "~1"))
    else:
        yield prefix, value


def fields(semantic):
    """Readable paths for every semantic value; relationships are keyed by predicate and field."""
    relations = {}
    for relation in semantic.get("relationships", []):
        rest = {key: value for key, value in relation.items() if key not in {"predicate", "field"}}
        relations[relation["predicate"] + relation["field"]] = rest
    result = dict(flatten({key: value for key, value in semantic.items() if key != "relationships"}))
    for name, rest in sorted(relations.items()):
        result.update(("/relationships/" + name + pointer, value) for pointer, value in flatten(rest))
    return result


def shown(value):
    data = packs.compact(value)
    return value if len(data) <= VALUE_BYTES else {"omitted_bytes": len(data), "sha256": digest(data)}


def difference(old, new):
    before, after = fields(old), fields(new)
    result = {}
    for name in sorted(before.keys() | after.keys()):
        if before.get(name, ...) != after.get(name, ...):
            result[name] = {**({"old": shown(before[name])} if name in before else {}),
                            **({"new": shown(after[name])} if name in after else {})}
    return result


def semantics(models, keys):
    return {row["entity_key"]: row["semantic"] for row in model.rows(models) if row["entity_key"] in keys}


def inputs(root, run, migration, scratch):
    """Current-key state and models, or None when the run's state was pruned."""
    if not retained(root, run["state"]):
        return None, None
    if not retained(root, run["models"]):
        return history.load_state(root, run), None
    scratch.parent.mkdir(parents=True, exist_ok=True)
    return identity_migration.reader_inputs(root, run, migration, scratch)


def summary(root, run):
    receipt = snapshots.read(root, run["snapshot_id"])
    captured = receipt.get("captured") or receipt.get("captured_at")
    return {"snapshot_id": run["snapshot_id"], "game_version": receipt.get("game_version"),
            "build_id": receipt["steam"]["build_id"],
            **({"captured": captured[:10]} if isinstance(captured, str) and re.match(r"^\d{4}-\d{2}-\d{2}", captured) else {})}


def row(key, entry):
    return {"entity_key": key, "name": entry["descriptor"]["name"], "kind": entry["descriptor"]["kind"]}


def compute(root, run, migration=None):
    """Return {topic: entry} for one run. Missing older state yields an initial entry."""
    scratch = within(root, ".local/history/changes")
    state, models = inputs(root, run, migration, scratch / ("current-" + run["run_id"] + ".jsonl"))
    if state is None:
        raise ContractError("Current identity state is missing")
    present = {key: entry for key, entry in state.items() if entry["status"] == "present"}
    base = base_run(root, run)
    old_state, old_models = (inputs(root, base, migration, scratch / ("base-" + base["run_id"] + ".jsonl"))
                             if base else (None, None))
    counts = Counter(entry["descriptor"]["topic"] for entry in present.values())
    topics = set(counts) | {entry["descriptor"]["topic"] for entry in (old_state or {}).values()}
    head = summary(root, run)
    result = {topic: {**head, "count": counts[topic], "previous": None} for topic in topics}
    if old_state is not None:
        previous = summary(root, base)
        old = {key: entry for key, entry in old_state.items() if entry["status"] == "present"}
        added_keys, removed_keys = present.keys() - old.keys(), old.keys() - present.keys()
        # A record that only moved to a new key keeps its revision; pair and drop both.
        signature = lambda entries, key: (entries[key]["descriptor"]["topic"], entries[key]["revision_id"])
        moved = Counter(signature(present, key) for key in added_keys) & Counter(signature(old, key) for key in removed_keys)
        pending = Counter(moved)
        for key in sorted(added_keys):
            if pending[signature(present, key)]:
                pending[signature(present, key)] -= 1
                added_keys.discard(key)
        pending = Counter(moved)
        for key in sorted(removed_keys):
            if pending[signature(old, key)]:
                pending[signature(old, key)] -= 1
                removed_keys.discard(key)
        changed_keys = {key for key in present.keys() & old.keys() if present[key]["revision_id"] != old[key]["revision_id"]}
        new_values = semantics(models, changed_keys) if models is not None and changed_keys else {}
        old_values = semantics(old_models, changed_keys) if old_models is not None and changed_keys else {}
        for topic in topics:
            result[topic].update(previous=previous, added=[], removed=[], changed=[])
        for key in sorted(added_keys):
            result[present[key]["descriptor"]["topic"]]["added"].append(row(key, present[key]))
        for key in sorted(removed_keys):
            status = state[key]["status"] if key in state else "not-present"
            result[old[key]["descriptor"]["topic"]]["removed"].append({**row(key, old[key]), "status": status})
        for key in sorted(changed_keys):
            change = row(key, present[key])
            if key in new_values and key in old_values:
                change["fields"] = difference(old_values[key], new_values[key])
            result[present[key]["descriptor"]["topic"]]["changed"].append(change)
    for leftover in scratch.glob("*.jsonl") if scratch.exists() else ():
        leftover.unlink()
    return result


def record(root, run=None):
    """Caller holds writer_lock. Prepend this run's entry to every topic log that lacks it."""
    run = run or history.latest(root)
    if run is None:
        return {"recorded": [], "reused": True}
    existing = sorted(item.stem for item in within(root, "changes").glob("*.json")) if within(root, "changes").is_dir() else []
    logs = {topic: read(root, topic) for topic in existing}
    if logs and all(any(entry["snapshot_id"] == run["snapshot_id"] for entry in log["versions"]) for log in logs.values()):
        return {"recorded": [], "reused": True}
    entries = compute(root, run, identity_migration.read(root))
    recorded = []
    for topic, entry in sorted(entries.items()):
        log = logs.get(topic) or read(root, topic)
        if any(item["snapshot_id"] == run["snapshot_id"] for item in log["versions"]):
            continue
        log["versions"].insert(0, entry)
        target = path(root, topic)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_changed(target, json_bytes(log))
        recorded.append(topic)
    return {"recorded": recorded, "reused": not recorded}


def label(entry):
    version = entry.get("game_version")
    return (f"Version {version}" if version else "Version unknown") + f", Steam build {entry['build_id']}"


def markdown(title, log, base, link):
    """Plain change list for one topic; link(base, key) gives the current entry URL."""
    lines = [f"# {escape(title)} changes", "",
             "Changes between captured game versions. Only extracted facts are compared.", ""]
    if not log["versions"]:
        lines += ["No changes recorded yet.", ""]
    for entry in log["versions"]:
        lines += [f"## {escape(label(entry))}", ""]
        if entry.get("previous") is None:
            lines += [f"First recorded capture: {entry['count']} entries. Earlier versions were not compared.", ""]
            continue
        lines += [f"Compared with {escape(label(entry['previous']))}. "
                  f"{len(entry['added'])} added, {len(entry['removed'])} removed, {len(entry['changed'])} changed.", ""]
        for heading, rows in (("Added", entry["added"]), ("Removed", entry["removed"]), ("Changed", entry["changed"])):
            if not rows:
                continue
            lines += [f"### {heading}", ""]
            for item in rows:
                name = escape(item["name"])
                text = f'<a href="{escape(link(base, item["entity_key"]), quote=True)}">{name}</a>' if heading != "Removed" else name
                detail = ", ".join(escape(field.lstrip("/")) for field in item.get("fields", {}))
                lines.append(f"- {text} ({escape(item['kind'])})" + (f": {detail}" if detail else ""))
            lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")
