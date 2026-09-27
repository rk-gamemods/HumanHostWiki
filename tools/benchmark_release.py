"""Measure a normal unchanged wiki update and verify all committed output is stable."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.audit_ownership import expand


def observe(root):
    paths = [root / name for name in ("workspace.lock.json", "releases/latest.json",
             ".local/pipeline/latest.json", ".local/reader-latest.json", "identity/latest.json")]
    availability_pointer = root / "availability/latest.json"
    if availability_pointer.exists():
        observation = json.loads(availability_pointer.read_text())["observation_id"]
        paths.extend((availability_pointer, root / "availability" / (observation + ".json")))
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
        heads[topic] = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]).decode().strip()
        assert heads[topic] == record["commit"]
        assert not subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=all"])
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
    result = subprocess.run([sys.executable, str(root / "wiki.py"), "update"], cwd=root,
                            capture_output=True, text=True, check=True)
    elapsed = time.perf_counter() - start
    output = json.loads(result.stdout)
    assert observe(root) == before, "An unchanged update changed commits, output bytes or timestamps"
    print(json.dumps({"status": "passed", "elapsed_seconds": round(elapsed, 3),
                      "repositories": len(before[0]), "stable_files": len(before[1]),
                      "update": output}, indent=2))


if __name__ == "__main__":
    main()
