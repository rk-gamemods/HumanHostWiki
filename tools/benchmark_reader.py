"""Measure fresh static projection and repeat in an isolated output cache."""

import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark_extraction import peak_memory
from wikibuild import manifest, reader
from wikibuild.storage import writer_lock


def main():
    project = manifest.load(ROOT)
    # Keep the output root shallow enough for Windows' default path limit.
    parent = ROOT / ".local"
    parent.mkdir(parents=True, exist_ok=True)
    cache = Path(tempfile.mkdtemp(prefix="rb-", dir=parent))
    with writer_lock(ROOT):
        started = time.perf_counter()
        first = reader.build(ROOT, project, cache_root=cache)
        fresh_seconds = time.perf_counter() - started
        pointer = cache / "reader-latest.json"
        stamp = pointer.stat().st_mtime_ns
        site = Path(first["path"])
        files = {path.relative_to(site).as_posix(): path.stat().st_mtime_ns for path in site.rglob("*") if path.is_file()}
        started = time.perf_counter()
        repeated = reader.build(ROOT, project, cache_root=cache)
        repeat_seconds = time.perf_counter() - started
        assert not first["reused"] and repeated["reused"] and first["candidate_id"] == repeated["candidate_id"]
        assert stamp == pointer.stat().st_mtime_ns
        assert files == {path.relative_to(site).as_posix(): path.stat().st_mtime_ns for path in site.rglob("*") if path.is_file()}
        validated = reader.verify(site, first["candidate_id"])
    print(json.dumps({"candidate_id": first["candidate_id"], "fresh_seconds": round(fresh_seconds, 3),
                      "repeat_seconds": round(repeat_seconds, 3), "python_peak_working_set_bytes": peak_memory(),
                      "files": len(validated["files"]), "output_bytes": first["bytes"],
                      "inputs": "Pinned selected models and identity ledger only; raw source is outside this stage",
                      "byte_and_pointer_stability": "passed", "cache": str(cache.relative_to(ROOT))}, indent=2))


if __name__ == "__main__":
    main()
