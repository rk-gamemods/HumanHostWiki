"""Unresolved wiki content is a successful-run report, never a swallowed bug."""

from .storage import digest, json_bytes


class Exceptions:
    def __init__(self):
        self.groups = {}
        self.switched_off = {}

    def add(self, code, topic, pattern, message, source, *, count=1):
        self._add(self.groups, code, topic, pattern, message, source, count)

    def for_switched_off(self, feature):
        """Collect drift inside a feature the capture ships switched off.

        No player can reach such a feature, so its drift is reported for the
        record but does not stop the update. The caller must prove the switch
        is off from the same capture; a switched-on feature uses ``add``.
        """
        parent = self

        class Sink:
            def add(self, code, topic, pattern, message, source, *, count=1):
                parent._add(parent.switched_off, code, topic, pattern, message, source, count, feature=feature)
        return Sink()

    @staticmethod
    def _add(groups, code, topic, pattern, message, source, count, **extra):
        identity = digest(json_bytes([code, topic, pattern, *extra.values()]))[:24]
        group = groups.setdefault(identity, {
            "id": identity, "code": code, "topic": topic, "pattern": pattern,
            "message": message, "occurrences": 0, "examples": [], **extra,
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
        result = {"schema_version": 1, "kind": "unresolved-wiki-content", "groups": records,
                  "group_count": len(records), "occurrences": sum(r["occurrences"] for r in records),
                  "next_action": "Ask the user how to handle these exceptions after supported work completes."
                  if records else "No unresolved wiki content in the implemented extraction scope."}
        # Omitted when empty so reports for unaffected snapshots keep their identity.
        if self.switched_off:
            result["switched_off"] = [self.switched_off[key] for key in sorted(self.switched_off)]
        return result
