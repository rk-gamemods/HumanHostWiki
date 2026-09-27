"""Measure normal-update reader sharing and independently check retained bytes."""

import hashlib
import json
from pathlib import Path
import sys
import time
import tracemalloc
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import wiki
from wikibuild import pipeline, reader_retention
from wikibuild.storage import writer_lock


def inspect():
    """Hash actual files independently of candidate manifests and compactor helpers."""
    files, inodes = {}, {}
    for path in sorted((ROOT / ".local/readers").rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("Redirected benchmark input")
        sha = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                sha.update(chunk)
        info = path.stat()
        files[path.relative_to(ROOT).as_posix()] = {"sha256": sha.hexdigest(), "bytes": info.st_size}
        inodes[info.st_dev, info.st_ino] = info.st_size
    return files, sum(inodes.values())


def main():
    print("Inventorying actual reader bytes before the normal update", flush=True)
    before, before_bytes = inspect()
    measurements = {}
    original = reader_retention.run

    def measured(root):
        tracemalloc.start()
        started = time.perf_counter()
        try:
            result = original(root)
            measurements.update(seconds=round(time.perf_counter() - started, 6),
                                python_peak_allocated_bytes=tracemalloc.get_traced_memory()[1], metrics=result)
            return result
        finally:
            tracemalloc.stop()

    with patch.object(reader_retention, "run", side_effect=measured):
        result = wiki.run(ROOT, SimpleNamespace(command="update", source=None))
    operator = pipeline.operator_report(ROOT, result)
    (ROOT / ".local/reader-retention-operator-report.txt").write_text(operator, encoding="utf-8")
    print("Checking every retained reader file independently", flush=True)
    after, after_bytes = inspect()
    assert all(after.get(name) == value for name, value in before.items()), "Reader path or bytes changed"
    assert not measurements["metrics"]["retained"], measurements
    with writer_lock(ROOT):
        started = time.perf_counter()
        repeated = reader_retention.run(ROOT)
        repeat_seconds = time.perf_counter() - started
    assert repeated["reused"] and repeated["linked_files"] == repeated["verified_bytes"] == 0, repeated
    evidence = {"pipeline": result, "first_compaction": measurements,
                "repeat_seconds": round(repeat_seconds, 6), "repeat": repeated,
                "existing_files_conserved": len(before), "new_files": len(set(after) - set(before)),
                "unique_inode_bytes_before": before_bytes, "unique_inode_bytes_after": after_bytes,
                "logical_bytes_before": sum(value["bytes"] for value in before.values()),
                "measurement_scope": "Unique-inode file lengths include manifests; excludes filesystem allocation overhead. Peak allocations cover the compactor only."}
    output = ROOT / ".local/reader-retention-benchmark.json"
    output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
