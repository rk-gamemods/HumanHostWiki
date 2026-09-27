"""Independently audit candidate article matching from search rows and saved observations."""

import hashlib
import json
from pathlib import Path
import sys
import unicodedata
from urllib.parse import urlencode


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def check(candidate):
    manifest = json.loads((candidate / "candidate.json").read_bytes())
    assert hashlib.sha256(canonical(manifest["inputs"])).hexdigest() == manifest["candidate_id"]
    project = manifest["inputs"]["project"]
    settings, observation = project.get("external_articles"), manifest["inputs"].get("external_articles")
    counts = {"topic_checks": 0, "eligible_entries": 0, "explicit_entry_checks": 0, "populated_entry_links": 0}
    if not settings or observation is None:
        return {"status": "not-configured", **counts}
    catalog = observation["catalog"]

    def read(topic, path, reference=None):
        full = candidate / topic / path
        assert not full.is_symlink() and full.resolve().is_relative_to(candidate.resolve())
        raw = full.read_bytes()
        metadata = reference or manifest["files"][topic + "/" + path]
        assert len(raw) == metadata["bytes"] and hashlib.sha256(raw).hexdigest() == metadata["sha256"]
        return json.loads(raw)

    def records(topic, refs):
        seen = set()
        for ref in refs:
            rows = read(topic, ref["path"], ref)
            assert rows and min(rows) == ref["first"] and max(rows) == ref["last"] and len(rows) == ref["count"]
            assert not seen.intersection(rows)
            seen.update(rows)
            yield from rows.items()

    def title_check(title):
        result = {"title": title, "checked_at": observation["checked_at"]}
        if title not in catalog["pages"]:
            return {**result, "status": "missing" if catalog["inventory_complete"] else "unavailable",
                    "reason": "absent-from-complete-index" if catalog["inventory_complete"] else "incomplete-index"}
        record = catalog["pages"][title]
        result.update(status=record["status"], reason=record["reason"], revision=record["metadata"]["revision"])
        if record["status"] == "populated":
            target = record.get("destination", title)
            revision = catalog["pages"][target]["metadata"]["revision"]
            result.update(destination=target, destination_revision=revision,
                url=settings["source"]["api_url"][:-len("api.php")] + "index.php?" + urlencode({"title": target, "oldid": revision}))
        return result

    def normalize(name):
        return " ".join(unicodedata.normalize("NFKC", name).replace("_", " ").split()).casefold()

    for repo in project["repositories"]:
        topic = repo["id"]
        config = read(topic, "reader.json")
        view = config.get("external_articles")
        route = settings["routes"].get(topic)
        if not route:
            assert view is None
            continue
        assert view["schema_version"] == 1
        assert view["observation_id"] == hashlib.sha256(canonical(observation)).hexdigest()
        assert view["checked_at"] == observation["checked_at"]
        assert view["kinds"] == sorted(route["entity_prefixes"])
        assert view["default_status"] == ("missing" if catalog["inventory_complete"] else "unavailable")
        assert view["topics"] == [title_check(title) for title in route["titles"]]
        counts["topic_checks"] += len(view["topics"])
        expected = {}
        for version in config["versions"] if route["entity_prefixes"] else []:
            snapshot = version["snapshot_id"]
            index = read(topic, "snapshots/" + snapshot + ".json")
            for entity, row in records(topic, index["search"]):
                prefixes = route["entity_prefixes"].get(row["kind"])
                if not prefixes or row["status"] != "present":
                    continue
                counts["eligible_entries"] += 1
                titles = sorted(title for title in catalog["pages"]
                    if any(title.startswith(prefix + "/") for prefix in prefixes)
                    and normalize(title.split(":", 1)[1].rsplit("/", 1)[-1]) == normalize(row["name"]))
                if not titles:
                    continue
                if len(titles) == 1 and catalog["inventory_complete"]:
                    result = title_check(titles[0])
                    result.pop("checked_at")
                else:
                    result = {"status": "unavailable", "candidates": titles,
                              "reason": "ambiguous-title" if catalog["inventory_complete"] else "incomplete-index"}
                expected[snapshot + "/" + entity] = result
        actual = dict(records(topic, view["entries"]))
        assert actual == expected, topic
        counts["explicit_entry_checks"] += len(actual)
        counts["populated_entry_links"] += sum(row["status"] == "populated" for row in actual.values())
    return {"status": "passed", "candidate_id": manifest["candidate_id"], **counts,
            "scope": "Offline title matching, scope, revision links and observation binding; not article accuracy or gameplay verification"}


if __name__ == "__main__":
    print(json.dumps(check(Path(sys.argv[1]).resolve()), indent=2))
