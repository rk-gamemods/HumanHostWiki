"""Measure a normal unchanged wiki update and verify all committed output is stable."""

import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.audit_ownership import expand
from wikibuild import bounded

# Benchmark metadata uses local revision and checkout plumbing.
GIT_TIMEOUT = 60
# The benchmark child performs a full unattended update and its retention stages.
UPDATE_TIMEOUT = 3600


def git(repo, *args):
    result = bounded.run(["git", "-C", str(repo), *args], timeout=GIT_TIMEOUT)
    result.check_returncode()
    return result.stdout


def run_update(root):
    result = bounded.run([sys.executable, str(root / "wiki.py"), "update"], cwd=root, timeout=UPDATE_TIMEOUT)
    result.check_returncode()
    return result.stdout.decode()


def observe(root):
    paths = [root / name for name in ("workspace.lock.json", "releases/latest.json",
             ".local/pipeline/latest.json", ".local/reader-latest.json", "identity/latest.json")]
    for directory in ("availability", "external-links"):
        pointer = root / directory / "latest.json"
        if pointer.exists():
            observation = json.loads(pointer.read_text())["observation_id"]
            paths.extend((pointer, root / directory / (observation + ".json")))
    latest = json.loads((root / "releases/latest.json").read_text())
    manifest_path = root / "releases" / (latest["release_id"] + ".json")
    paths.append(manifest_path)
    publication_pointer = root / 'publications/latest.json'
    if publication_pointer.exists():
        paths.append(publication_pointer)
        published = json.loads(publication_pointer.read_text())['payload']['release_id']
        paths.append(root / 'publications' / (published + '.json'))
    manifest = json.loads(manifest_path.read_text())
    heads = {}
    for topic, record in manifest["repositories"].items():
        repo = root / record["path"]
        heads[topic] = git(repo, "rev-parse", "HEAD").decode().strip()
        assert heads[topic] == record["commit"]
        assert not git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        owner = repo / ".wiki-output.json"
        paths.append(owner)
        receipt, parts = expand(json.loads(owner.read_text()), lambda name: (repo / name).read_bytes())
        paths.extend(repo / name for name in receipt["files"])
        paths.extend(repo / name for name in parts)
    files = {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths}
    return heads, files


def main():
    root = Path(__file__).resolve().parents[1]
    before = observe(root)
    start = time.perf_counter()
    result = run_update(root)
    elapsed = time.perf_counter() - start
    output = json.loads(result)
    assert observe(root) == before, "An unchanged update changed commits, output bytes or timestamps"
    print(json.dumps({"status": "passed", "elapsed_seconds": round(elapsed, 3),
                      "repositories": len(before[0]), "stable_files": len(before[1]),
                      "update": output}, indent=2))


if __name__ == "__main__":
    main()
