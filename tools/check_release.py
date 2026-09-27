"""Audit committed release bytes against the candidate without importing the builder."""

import hashlib
import json
from pathlib import Path
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args])


def contained(root, name):
    path = root / name
    assert not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), name
    return path


def check(root):
    release_id = read(root / "releases/latest.json")["release_id"]
    manifest = read(root / "releases" / (release_id + ".json"))
    assert manifest["release_id"] == sha(canonical(manifest["inputs"])) == release_id
    assert manifest["manifest_sha256"] == sha(canonical({k: v for k, v in manifest.items() if k != "manifest_sha256"}))
    candidate_id = manifest["reader_candidate"]
    candidate = root / ".local/readers" / candidate_id
    if not candidate.exists():
        candidate = candidate.with_name(candidate_id[:24])
    candidate_manifest = read(candidate / "candidate.json")
    assert sha(canonical(candidate_manifest["inputs"])) == candidate_id
    assert manifest["versions"] == candidate_manifest["versions"]
    assert manifest["routes"] == candidate_manifest["inputs"]["bases"]
    counts = {"repositories": 0, "owned_files": 0, "owned_bytes": 0, "candidate_files": 0, "historical_configs": 0}
    for topic, record in manifest["repositories"].items():
        path = contained(root, record["path"])
        assert git(path, "rev-parse", "HEAD").decode().strip() == record["commit"]
        assert git(path, "rev-parse", record["commit"] + "^{tree}").decode().strip() == record["tree"]
        assert not git(path, "status", "--porcelain=v1", "--untracked-files=all")
        # Compare to the pinned Git tree as well as the working bytes; Git stat
        # caching must not hide an altered file from this audit.
        blobs = {}
        algorithm = git(path, "rev-parse", "--show-object-format").decode().strip()
        for item in git(path, "ls-tree", "-rz", record["commit"]).split(b"\0"):
            if item:
                meta, name = item.split(b"\t", 1)
                mode, kind, oid = meta.split()
                if kind == b"blob":
                    blobs[name.decode()] = oid.decode()
        owner_data = (path / ".wiki-output.json").read_bytes()
        assert sha(owner_data) == record["ownership_sha256"]
        assert git(path, "show", record["commit"] + ":.wiki-output.json") == owner_data
        owner = json.loads(owner_data)
        assert owner["repository_id"] == topic and owner["release_id"] == release_id
        files = owner["files"]
        assert sha(canonical(files)) == record["files_sha256"]
        assert len(files) == record["file_count"]
        assert sum(v["bytes"] for v in files.values()) == record["output_bytes"]
        assert sum(v["bytes"] for k, v in files.items() if k.startswith("site/")) == record["site_bytes"]
        for folder in ("site", "reference"):
            actual = {p.relative_to(path).as_posix() for p in (path / folder).rglob("*") if p.is_file()}
            assert actual == {name for name in files if name.startswith(folder + "/")}
        for name, expected in files.items():
            data = contained(path, name).read_bytes()
            assert len(data) == expected["bytes"] and sha(data) == expected["sha256"], name
            object_hash = hashlib.new(algorithm, b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            assert blobs[name] == object_hash, name
        site = path / "site"
        config = read(site / "reader.json")
        assert config == read(site / "releases" / (release_id + ".json"))
        original = read(candidate / topic / "reader.json")
        assert {k: v for k, v in config.items() if k not in {"release_id", "runtime", "snapshots", "publication"}} == {
            k: v for k, v in original.items() if k != "publication"}
        assert config["candidate_id"] == candidate_id and config["release_id"] == release_id
        assert {t["id"]: t["base"] for t in config["topics"]} == manifest["routes"]
        for name, expected in candidate_manifest["files"].items():
            if not name.startswith(topic + "/"):
                continue
            relative = name[len(topic) + 1:]
            data = contained(candidate, name).read_bytes()
            assert len(data) == expected["bytes"] and sha(data) == expected["sha256"]
            if relative == "reader.json":
                continue
            if relative.startswith("snapshots/"):
                target = contained(site, config["snapshots"][Path(relative).stem]["path"])
            elif relative in {"reader.js", "reader.css"}:
                target = contained(site, config["runtime"][Path(relative).suffix[1:]])
            elif relative.startswith("reference/"):
                target = contained(path, relative)
                data = data.replace(("release=" + candidate_id).encode(), ("release=" + release_id).encode())
            else:
                target = contained(site, relative)
            assert target.read_bytes() == data, relative
            counts["candidate_files"] += 1
        # Every retained release must still reach its indexes, data and runtime.
        for config_path in (site / "releases").glob("*.json"):
            old = read(config_path)
            assert old["release_id"] == config_path.stem
            for name in old["runtime"].values():
                data = contained(site, name).read_bytes()
                assert sha(data) == Path(name).parts[1]
            for snapshot, index_ref in old["snapshots"].items():
                data = contained(site, index_ref["path"]).read_bytes()
                assert sha(data) == index_ref["sha256"] and len(data) == index_ref["bytes"]
                index = json.loads(data)
                assert index["snapshot_id"] == snapshot
                for kind in ("entries", "semantics", "provenance", "search", "backlinks"):
                    for pack in index[kind]:
                        assert files["site/" + pack["path"]] == {"bytes": pack["bytes"], "sha256": pack["sha256"]}
            counts["historical_configs"] += 1
        counts["repositories"] += 1
        counts["owned_files"] += len(files)
        counts["owned_bytes"] += record["output_bytes"]
    return {"status": "passed", "release_id": release_id, **counts,
            "scope": "Committed bytes, candidate conservation and retained release reachability; not gameplay or deployment verification"}


if __name__ == "__main__":
    print(json.dumps(check(Path(__file__).resolve().parents[1]), indent=2))
