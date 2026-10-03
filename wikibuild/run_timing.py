"""Best-effort command diagnostics, deliberately outside wiki identities."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import threading
from time import perf_counter
import uuid

from .storage import json_bytes, within


def warning(message):
    try:
        print(f"WARNING: {message}", file=sys.stderr, flush=True)
    except (Exception, KeyboardInterrupt):
        pass


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def capture(path):
    """Validate the complete v1 receipt before retaining its bounded summary."""
    if path is None:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != "humanhost.capture-timing.v1":
            raise ValueError("unsupported capture timing schema")
        for key in ("started_at", "finished_at", "output_path"):
            if not isinstance(value[key], str):
                raise ValueError(f"{key} must be a string")
        for key in ("started_at", "finished_at"):
            if datetime.fromisoformat(value[key].replace("Z", "+00:00")).utcoffset() is None:
                raise ValueError(f"{key} must include a timezone")
        if not number(value["seconds"]):
            raise ValueError("seconds must be finite and nonnegative")
        if value["outcome"] not in ("succeeded", "failed", "reused"):
            raise ValueError("invalid capture outcome")
        for key in ("error", "output_commit"):
            if value[key] is not None and not isinstance(value[key], str):
                raise ValueError(f"{key} must be a string or null")
        if not isinstance(value["game"], str):
            raise ValueError("game must be a string")
        for key in ("phases", "assemblies"):
            if not isinstance(value[key], list):
                raise ValueError(f"{key} must be an array")
            for row in value[key]:
                if (not isinstance(row, dict) or not isinstance(row["name"], str)
                        or not number(row["seconds"]) or row["outcome"] not in ("succeeded", "failed", "reused")):
                    raise ValueError(f"invalid {key} entry")
        return {"seconds": value["seconds"], "outcome": value["outcome"],
                "phases": [{key: row[key] for key in ("name", "seconds", "outcome")} for row in value["phases"]]}
    except (Exception, KeyboardInterrupt) as exc:
        warning(f"Capture timing ignored: {exc}")
        return None


class Values(dict):
    """Keep observation metadata off the existing numeric timing dictionaries."""
    def __init__(self, *args, lock=None, clock=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.active, self.outcomes = {}, {}
        self.lock = lock if lock is not None else threading.RLock()
        self.clock = clock

    def now(self):
        return (self.clock or perf_counter)()

    @contextmanager
    def observe(self, key):
        with self.lock:
            self.active[key] = self.now()
        outcome = "failed"
        try:
            yield
            outcome = "succeeded"
        finally:
            with self.lock:
                now = self.now()
                self[key] = self.get(key, 0.0) + (now - self.active.pop(key))
                self.outcomes[key] = outcome

    def rows(self, prefix="", basis="wall", outcome="timed-out"):
        with self.lock:
            now = self.now()
            return [{"name": prefix + key, "seconds": self.get(key, 0.0) + (now - self.active[key] if key in self.active else 0.0),
                     "outcome": outcome if key in self.active else self.outcomes.get(key, "not-run"), "basis": basis}
                    for key in dict.fromkeys([*self, *self.active]) if number(self.get(key, 0.0))]


def publication_rows(timing, outcome):
    top = {row["name"]: row for row in timing.rows(outcome=outcome)}
    rows = [top[key] for key in ("gate", "prepare") if key in top]
    rows.extend(timing["phases"].rows(outcome=outcome))
    for group in ("repositories", "rollback"):
        for name, values in list(timing[group].items()):
            prefix = name + (" rollback" if group == "rollback" else "")
            detail = {row["name"]: row for row in values.rows(outcome=outcome)}
            for label, keys in (("push", ("push_main", "push_pages")), ("Pages wait", ("pages_build",)), ("verify", ("verify",))):
                selected = [detail[key] for key in keys]
                states = [row["outcome"] for row in selected]
                state = next((s for s in ("timed-out", "failed") if s in states),
                             "succeeded" if "succeeded" in states else "not-run")
                rows.append({"name": f"{prefix}: {label}", "seconds": sum(row["seconds"] for row in selected),
                             "outcome": state, "basis": "repository-sum"})
    return rows


class Recorder:
    def __init__(self, root, command, release_id=None, capture_path=None):
        self.root, self.command, self.release_id = Path(root), command, release_id
        self.lock = threading.RLock()
        with self.lock:
            self.started = datetime.now(timezone.utc)
            self.clock = perf_counter()
        self.capture = capture(capture_path)
        self.stages = Values(lock=self.lock)
        self.publication = None
        self.record, self.path = None, None
        self.outcome, self.record_error = None, None
        self.saving = False

    def enter(self, name):
        with self.lock:
            if self.outcome is not None:
                return
            now = perf_counter()
            for key, started in self.stages.active.items():
                self.stages[key] = self.stages.get(key, 0.0) + (now - started)
                self.stages.outcomes[key] = "succeeded"
            self.stages.active = {name: now}

    def claim(self, outcome):
        """Select the terminal state and freeze timing, without any file I/O."""
        with self.lock:
            if self.outcome is not None:
                return False
            self.outcome = outcome
            try:
                rows = (publication_rows(self.publication, outcome) if self.publication is not None
                        else self.stages.rows(outcome=outcome))
                self.record = {"schema": "humanhost.wiki-timing.v1", "command": self.command,
                    "started_at": self.started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
                    "seconds": perf_counter() - self.clock, "outcome": outcome,
                    "release_id": self.release_id, "stages": rows, "capture": self.capture}
            except (Exception, KeyboardInterrupt) as exc:
                self.record_error = exc
            return True

    def finish(self, outcome, result=None):
        """Save once, releasing the state lock before potentially blocked storage."""
        with self.lock:
            if self.outcome is None and result:
                self.release_id = result.get("release_id", self.release_id)
            self.claim(outcome)
            if self.saving:
                return self.record
            self.saving = True
            record, error = self.record, self.record_error
        try:
            if error is not None:
                raise error
            path = save(self.root, record)
            with self.lock:
                self.path = path
        except (Exception, KeyboardInterrupt) as exc:
            warning(f"Wiki timing could not be saved: {exc}")
        return record


def save(root, record):
    """Expose complete bytes with an exclusive hard link, never replace a record."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = within(root, f".local/runs/wiki-{record['command']}-{stamp}-{uuid.uuid4().hex[:8]}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    created = False
    try:
        with temporary.open("xb") as output:
            created = True
            output.write(json_bytes(record))
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        if created:
            temporary.unlink()
    return path


def table(record):
    captured = record.get("capture")
    rows = [("capture: " + row["name"], row["seconds"], row["outcome"], "wall")
            for row in (captured or {}).get("phases", [])]
    rows += [("wiki: " + row["name"], row["seconds"], row["outcome"], row.get("basis", "wall"))
             for row in record["stages"]]
    total = record["seconds"] + (captured or {}).get("seconds", 0.0)
    largest = sorted((row for row in rows if row[3] == "wall"), key=lambda row: row[1], reverse=True)[:3]
    rows += [("Capture total", (captured or {}).get("seconds", 0.0), "", ""),
             ("Wiki total", record["seconds"], record["outcome"], ""), ("Combined total", total, "", "")]
    width = max(20, *(len(row[0]) for row in rows))
    lines = [f"Run timing: {record['command']} {record['started_at']}",
             f"{'Item':<{width}}  {'Seconds':>10}  {'Outcome':<10}  Basis"]
    lines += [f"{name:<{width}}  {seconds:>10.2f}  {outcome:<10}  {basis}" for name, seconds, outcome, basis in rows]
    lines.append("Largest items (share of combined wall time):")
    lines += [f"{name:<{width}}  {(100 * seconds / total if total else 0):>9.1f}%" for name, seconds, _, _ in largest]
    lines.append("Repository sums overlap parallel wall phases; excluded from largest items.")
    return "\n".join(lines) + "\n"


def latest(root, last=1):
    if last < 1:
        raise ValueError("--last must be positive")
    paths = sorted(within(root, ".local/runs").glob("wiki-*.json"),
                   key=lambda path: path.name.split("-", 2)[2], reverse=True)
    records = []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["schema"] != "humanhost.wiki-timing.v1":
                raise ValueError("unsupported wiki timing schema")
            rendered = table(record)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warning(f"Wiki timing record ignored ({path.name}): {exc}")
            continue
        records.append(rendered)
        if len(records) == last:
            break
    return "\n".join(records) if records else "No wiki timing records.\n"
