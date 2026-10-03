"""Unresolved wiki content is a successful-run report, never a swallowed bug."""

from .storage import digest, json_bytes


class Exceptions:
    def __init__(self):
        self.groups = {}

    def add(self, code, topic, pattern, message, source, *, count=1):
        identity = digest(json_bytes([code, topic, pattern]))[:24]
        group = self.groups.setdefault(identity, {
            "id": identity, "code": code, "topic": topic, "pattern": pattern,
            "message": message, "occurrences": 0, "examples": [],
        })
        if group["message"] != message:
            raise ValueError(f"Conflicting exception definition: {identity}")
        group["occurrences"] += count
        # Keep bounded, order-independent examples; aggregate every occurrence.
        group["examples"] = sorted(set(group["examples"] + [source]))[:8]

    def records(self):
        return [self.groups[key] for key in sorted(self.groups)]

    def report(self):
        records = self.records()
        return {"schema_version": 1, "kind": "unresolved-wiki-content", "groups": records,
                "group_count": len(records), "occurrences": sum(r["occurrences"] for r in records),
                "next_action": "Ask the user how to handle these exceptions after supported work completes."
                if records else "No unresolved wiki content in the implemented extraction scope."}
