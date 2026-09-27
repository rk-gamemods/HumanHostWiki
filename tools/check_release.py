"""Audit committed release bytes against the candidate without importing the builder."""

import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urljoin


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
    origins, ownership, locations = {}, {}, {}
    owner_name = candidate_manifest["inputs"]["project"]["github_owner"]
    for identity, record in manifest["repositories"].items():
        path = contained(root, record["path"])
        assert git(path, "rev-parse", "HEAD").decode().strip() == record["commit"]
        assert git(path, "rev-parse", record["commit"] + "^{tree}").decode().strip() == record["tree"]
        assert not git(path, "status", "--porcelain=v1", "--untracked-files=all")
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
        assert git(path, "cat-file", "blob", record["commit"] + ":.wiki-output.json") == owner_data
        owner = json.loads(owner_data)
        assert owner["repository_id"] == identity
        logical = manifest.get("physical", {}).get(identity, {}).get("topic", identity)
        if identity == logical:
            assert owner["release_id"] == release_id
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
        origin = f"https://{owner_name}.github.io/{record['github_name']}/"
        assert origin not in origins
        origins[origin] = (logical, path)
        ownership[path] = files
        allocated = owner.get("capacity_objects", [name for name in files if name.startswith(
            ("site/data/", "site/objects/", "site/runtime/", "site/releases/"))])
        assert len(allocated) == len(set(allocated))
        for name in allocated:
            assert (logical, name) not in locations
            locations[(logical, name)] = contained(path, name)
        counts["repositories"] += 1
        counts["owned_files"] += len(files)
        counts["owned_bytes"] += record["output_bytes"]

    def public(topic, reference):
        name = reference["path"] if isinstance(reference, dict) else reference
        url = urljoin(manifest["routes"][topic], name)
        matches = [(base, owner, path) for base, (owner, path) in origins.items() if url.startswith(base)]
        assert len(matches) == 1, url
        base, owner, path = matches[0]
        assert owner == topic, url
        relative = "site/" + url[len(base):]
        assert relative in ownership[path]
        data = contained(path, relative).read_bytes()
        if isinstance(reference, dict):
            assert sha(data) == reference["sha256"] and len(data) == reference["bytes"], url
        return data

    def configuration(topic, name):
        value = json.loads(public(topic, name))
        expected = value["release_id"]
        for depth in range(4):
            if value.get("kind") != "wiki-release-reference":
                assert value["release_id"] == expected
                return value
            value = json.loads(public(topic, value["target"]))
        raise AssertionError("Release reference chain did not terminate")

    configs = {}
    for topic in manifest["routes"]:
        config = configuration(topic, "reader.json")
        assert config == configuration(topic, "releases/" + release_id + ".json")
        original = read(candidate / topic / "reader.json")
        assert {k: v for k, v in config.items() if k not in {"release_id", "runtime", "snapshots", "publication"}} == {
            k: v for k, v in original.items() if k != "publication"}
        assert config["candidate_id"] == candidate_id and config["release_id"] == release_id
        assert {t["id"]: t["base"] for t in config["topics"]} == manifest["routes"]
        configs[topic] = config
    for name, expected in candidate_manifest["files"].items():
        topic, relative = name.split("/", 1)
        data = contained(candidate, name).read_bytes()
        assert len(data) == expected["bytes"] and sha(data) == expected["sha256"]
        config = configs[topic]
        if relative == "reader.json":
            continue
        if relative.startswith("snapshots/"):
            index = json.loads(public(topic, config["snapshots"][Path(relative).stem]))
            original = json.loads(data)
            for kind in ("entries", "semantics", "provenance", "search", "backlinks"):
                assert len(index[kind]) == len(original[kind])
                for actual, before in zip(index[kind], original[kind]):
                    assert {k: v for k, v in actual.items() if k != "path"} == {k: v for k, v in before.items() if k != "path"}
                    assert public(topic, actual) == contained(candidate / topic, before["path"]).read_bytes()
                index[kind] = original[kind]
            assert index == original
        elif relative in {"reader.js", "reader.css"}:
            assert public(topic, config["runtime"][Path(relative).suffix[1:]]) == data
        elif relative.startswith("reference/"):
            path = contained(root, manifest["repositories"][topic]["path"])
            assert contained(path, relative).read_bytes() == data.replace(("release=" + candidate_id).encode(), ("release=" + release_id).encode())
        elif relative.startswith("data/"):
            assert locations[(topic, "site/" + relative)].read_bytes() == data
        else:
            assert public(topic, relative) == data
        counts["candidate_files"] += 1
    # Full configs have one allocated location. Front stubs do not count as
    # duplicate configurations and must resolve to the same pinned bytes above.
    for (topic, name), path in locations.items():
        if not name.startswith("site/releases/"):
            continue
        old = read(path)
        assert old["release_id"] == path.stem
        for name in old["runtime"].values():
            assert sha(public(topic, name)) == name.split("/")[-2]
        for snapshot, index_ref in old["snapshots"].items():
            index = json.loads(public(topic, index_ref))
            assert index["snapshot_id"] == snapshot
            for kind in ("entries", "semantics", "provenance", "search", "backlinks"):
                for pack in index[kind]:
                    public(topic, pack)
        counts["historical_configs"] += 1
    return {"status": "passed", "release_id": release_id, **counts,
            "scope": "Committed bytes, candidate conservation and retained release reachability; not gameplay or deployment verification"}


if __name__ == "__main__":
    print(json.dumps(check(Path(__file__).resolve().parents[1]), indent=2))
