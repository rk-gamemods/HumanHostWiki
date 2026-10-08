"""Independently compare public reader packs with every pinned normalized row."""

from collections import Counter
import argparse
import copy
import hashlib
import json
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(value):
    return sha((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())


def migration_record(root, identity):
    if identity is None:
        return None
    value = read(root / "identity/migration.json")
    assert value["migration_id"] == identity
    assert fingerprint({key: item for key, item in value.items() if key != "migration_id"}) == identity
    return value


def expected_models(root, run, migration):
    """Audit frozen rows and independently apply only receipt-pinned assignment repairs."""
    repairs = {row["old_key"]: row for row in (migration or {}).get("repairs", [])
               if row["run_id"] == run["run_id"]}
    rekeys = {key: proof["entity_key"] for key, proof in repairs.items()}
    expected, seen = {}, set()
    checksum, size = hashlib.sha256(), 0
    with (root / run["models"]["path"]).open("rb") as stream:
        for line in stream:
            checksum.update(line)
            size += len(line)
            row = json.loads(line)
            old = row["entity_key"]
            assert old not in seen and fingerprint(row["semantic"]) == row["revision_id"]
            seen.add(old)
            if old in repairs:
                proof = repairs[old]
                assert proof["snapshot_id"] == run["snapshot_id"]
                assert proof["source_id"] == row["provenance"]["source_id"]
                assert proof["observation_key"] == row["provenance"]["observation_key"]
                assert proof["topic"] == row["semantic"]["topic"]
            if repairs:
                row = copy.deepcopy(row)
                row["entity_key"] = rekeys.get(old, old)
                for relation in row["semantic"]["relationships"]:
                    for gap in relation.get("gaps", []):
                        candidates = [*gap.get("candidates", []), gap.get("technical_summary")]
                        assert all(rekeys.get(key, key) == key for key in candidates)
                    for field in ("targets", "technical_targets"):
                        if field in relation:
                            relation[field] = sorted({rekeys.get(key, key) for key in relation[field]})
                for target in row["provenance"].get("resolved_targets", []):
                    if "target_entity" in target:
                        target["target_entity"] = rekeys.get(target["target_entity"], target["target_entity"])
                row["revision_id"] = fingerprint(row["semantic"])
            assert row["entity_key"] not in expected
            expected[row["entity_key"]] = row
    assert repairs.keys() <= seen
    assert size == run["models"]["bytes"] and checksum.hexdigest() == run["models"]["sha256"]
    return expected


def maps(site, shards):
    result = {}
    for shard in shards:
        data = (site / shard["path"]).read_bytes()
        assert len(data) == shard["bytes"] and sha(data) == shard["sha256"]
        values = json.loads(data)
        assert not set(values).intersection(result)
        result.update(values)
    return result


def check(root, site=None):
    root = Path(root)
    if site is None:
        candidate_id = read(root / ".local/reader-latest.json")["candidate_id"]
        site = root / ".local/readers" / candidate_id
        if not site.exists():
            site = root / ".local/readers" / candidate_id[:24]
    else:
        site = Path(site)
        candidate_id = read(site / "candidate.json")["candidate_id"]
    manifest = read(site / "candidate.json")
    inputs = manifest["inputs"]
    canonical = (json.dumps(inputs, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    assert sha(canonical) == candidate_id
    assert {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()} == set(manifest["files"]) | {"candidate.json"}
    for path, record in manifest["files"].items():
        data = (site / path).read_bytes()
        assert len(data) == record["bytes"] and sha(data) == record["sha256"]
        suffix = Path(path).suffix
        assert suffix in {".json", ".html", ".md", ".js", ".css", ""} or (
            suffix in {".woff2", ".txt"} and path.startswith("hub/fonts/"))
    migration = migration_record(root, inputs.get("identity_migration"))
    checked, checks = 0, 0
    for version in manifest["versions"]:
        run = read(root / "identity/runs" / (version["identity_run"] + ".json"))
        expected = expected_models(root, run, migration)
        actual_keys, expected_reverse, actual_reverse = set(), Counter(), Counter()
        hub_search, topic_search, topic_counts = None, {}, {}
        for row in expected.values():
            for relation in row["semantic"]["relationships"]:
                for target in relation["targets"] + relation.get("technical_targets", []):
                    expected_reverse[(target, row["entity_key"], relation["predicate"], relation["field"])] = 1
        for topic in inputs["project"]["repositories"]:
            folder = site / topic["id"]
            index = read(folder / "snapshots" / (version["snapshot_id"] + ".json"))
            entries, semantics, provenance, search, reverse = [maps(folder, index[kind]) for kind in ("entries", "semantics", "provenance", "search", "backlinks")]
            players = maps(folder, index.get("player", []))
            assert index.get("redirects", {}) == {key: proof["entity_key"] for key, proof in
                (migration or {}).get("redirects", {}).items() if proof["topic"] == topic["id"]}
            is_hub = topic.get("role") == "hub" or topic["id"] == "hub"
            if is_hub:
                hub_search = search
                declared_counts = index["topic_counts"]
            else:
                assert set(entries) == set(search)
            kinds = Counter()
            for key, value in entries.items():
                if value["status"] != "present":
                    assert key not in expected
                    continue
                original = expected[key]
                assert value["name"] == original["semantic"]["name"]
                assert value["kind"] == original["semantic"]["kind"]
                assert value["topic"] == original["semantic"]["topic"]
                assert value["revision_id"] == original["revision_id"]
                assert semantics[value["revision_id"]] == original["semantic"]
                assert provenance[value["provenance_id"]] == original["provenance"]
                display = players.get(value.get("player_id"), {}).get("name", value["name"])
                assert search[key]["name"] == display
                assert search[key]["entity_key"] == key
                assert search[key]["kind"] == original["semantic"]["kind"]
                assert search[key]["topic"] == original["semantic"]["topic"]
                assert search[key].get("source_name", value["name"]) == value["name"]
                if display != value["name"]:
                    assert search[key]["source_name"] == value["name"]
                topic_search[key] = {field: search[key][field] for field in
                    ("entity_key", "name", "source_name", "kind", "topic") if field in search[key]}
                kinds[value["kind"]] += 1
                assert value["last_verified"] is None
                assert key not in actual_keys
                actual_keys.add(key)
                checks += 9
            topic_counts[topic["id"]] = {"total": sum(kinds.values()), "kinds": dict(kinds)}
            for key, value in reverse.items():
                target = key.split("/", 1)[0]
                assert target in entries and value["entity"] in expected
                actual_reverse[(target, value["entity"], value["predicate"], value["field"])] += 1
        assert actual_keys == set(expected)
        assert actual_reverse == expected_reverse
        if hub_search is not None:
            assert hub_search == topic_search and declared_counts == topic_counts
        checked += len(actual_keys)
        checks += 2
    return {"candidate_id": candidate_id, "observations_checked": checked, "assertions": checks,
                      "files": len(manifest["files"]), "output_bytes": manifest["total_bytes"],
                      "largest_pack_bytes": max((value["bytes"] for key, value in manifest["files"].items() if "/data/" in key), default=0),
                      "status": "passed", "scope": "Complete selected model conservation and reverse-edge equality; not runtime gameplay verification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, help="Audit an explicit immutable reader candidate")
    args = parser.parse_args()
    print(json.dumps(check(Path(__file__).resolve().parents[1], args.candidate), indent=2))


if __name__ == "__main__":
    main()
