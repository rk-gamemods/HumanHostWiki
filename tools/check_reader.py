"""Independently compare public reader packs with every pinned normalized row."""

from collections import Counter
import hashlib
import json
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def maps(site, shards):
    result = {}
    for shard in shards:
        data = (site / shard["path"]).read_bytes()
        assert len(data) == shard["bytes"] and sha(data) == shard["sha256"]
        values = json.loads(data)
        assert not set(values).intersection(result)
        result.update(values)
    return result


def main():
    root = Path(__file__).resolve().parents[1]
    candidate_id = read(root / ".local/reader-latest.json")["candidate_id"]
    site = root / ".local/readers" / candidate_id
    if not site.exists():
        site = root / ".local/readers" / candidate_id[:24]
    manifest = read(site / "candidate.json")
    inputs = manifest["inputs"]
    canonical = (json.dumps(inputs, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    assert sha(canonical) == candidate_id
    assert {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()} == set(manifest["files"]) | {"candidate.json"}
    for path, record in manifest["files"].items():
        data = (site / path).read_bytes()
        assert len(data) == record["bytes"] and sha(data) == record["sha256"]
        assert Path(path).suffix in {".json", ".html", ".md", ".js", ".css", ""}
    checked, checks = 0, 0
    for version in manifest["versions"]:
        run = read(root / "identity/runs" / (version["identity_run"] + ".json"))
        expected = {}
        with (root / run["models"]["path"]).open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                expected[row["entity_key"]] = row
        actual_keys, expected_reverse, actual_reverse = set(), Counter(), Counter()
        for row in expected.values():
            for relation in row["semantic"]["relationships"]:
                for target in relation["targets"] + relation.get("technical_targets", []):
                    expected_reverse[(target, row["entity_key"], relation["predicate"], relation["field"])] = 1
        for topic in inputs["project"]["repositories"]:
            folder = site / topic["id"]
            index = read(folder / "snapshots" / (version["snapshot_id"] + ".json"))
            entries, semantics, provenance, search, reverse = [maps(folder, index[kind]) for kind in ("entries", "semantics", "provenance", "search", "backlinks")]
            assert set(entries) == set(search)
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
                assert search[key]["name"] == value["name"]
                assert value["last_verified"] is None
                assert key not in actual_keys
                actual_keys.add(key)
                checks += 9
            for key, value in reverse.items():
                target = key.split("/", 1)[0]
                assert target in entries and value["entity"] in expected
                actual_reverse[(target, value["entity"], value["predicate"], value["field"])] += 1
        assert actual_keys == set(expected)
        assert actual_reverse == expected_reverse
        checked += len(actual_keys)
        checks += 2
    print(json.dumps({"candidate_id": candidate_id, "observations_checked": checked, "assertions": checks,
                      "files": len(manifest["files"]), "output_bytes": manifest["total_bytes"],
                      "largest_pack_bytes": max(value["bytes"] for key, value in manifest["files"].items() if "/data/" in key),
                      "status": "passed", "scope": "Complete selected model conservation and reverse-edge equality; not runtime gameplay verification"}, indent=2))


if __name__ == "__main__":
    main()
