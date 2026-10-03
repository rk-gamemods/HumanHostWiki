"""Read-only capacity rehearsal over actual published objects; creates no partitions."""

from collections import defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wikibuild import capacity, capacity_inventory, manifest
from wikibuild.storage import writer_lock


def check(root):
    started = time.perf_counter()
    tracemalloc.start()
    with writer_lock(root):
        inventory = capacity_inventory.read(root, manifest.load(root))
    artifacts = [stored.artifact for stored in inventory.stored]
    same = capacity.allocate(inventory.topics, inventory.partitions, inventory.stored, artifacts)
    assert not same.created and set(same.reused) == {artifact.key for artifact in artifacts}
    assert set(same.placements) == set(inventory.stored)
    # Force real derived objects across small partitions without touching their
    # existing ownership, writing copies, or making any remote calls.
    budgets = capacity.Budgets(file_bytes=capacity.MIB, site_bytes=2 * capacity.MIB,
                               history_bytes=4 * capacity.MIB, site_reserve_bytes=128 * 1024,
                               history_reserve_bytes=128 * 1024)
    empty = [capacity.partition(topic, 0) for topic in inventory.topics]
    divided = capacity.allocate(inventory.topics, empty, [], artifacts, budgets)
    assert {placed.artifact for placed in divided.placements} == set(artifacts)
    site_totals, blobs = defaultdict(int), defaultdict(dict)
    topics = {part.id: part.topic for part in divided.partitions}
    for placed in divided.placements:
        artifact = placed.artifact
        assert topics[placed.partition] == artifact.topic
        if artifact.path.startswith("site/"):
            site_totals[placed.partition] += artifact.bytes
        blobs[placed.partition][artifact.sha256] = artifact.bytes
    for part in divided.partitions:
        assert part.site_bytes == site_totals[part.id] <= budgets.site_bytes - budgets.site_reserve_bytes
        assert part.history_bytes == sum(blobs[part.id].values()) <= budgets.history_bytes - budgets.history_reserve_bytes
    replay = capacity.allocate(inventory.topics, divided.partitions, divided.placements, artifacts, budgets)
    assert not replay.created and replay.partitions == divided.partitions and replay.placements == divided.placements
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {"status": "passed", "release_id": inventory.release_id, "logical_topics": len(inventory.topics),
            "immutable_objects": len(artifacts), "immutable_bytes": sum(value.bytes for value in artifacts),
            "unchanged_new_partitions": len(same.created), "forced_budgets": asdict(budgets),
            "forced_new_partitions": len(divided.created), "forced_total_partitions": len(divided.partitions),
            "replay_new_partitions": len(replay.created), "python_peak_bytes": peak,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "measured_repositories": [asdict(value) for value in inventory.partitions],
            "scope": "Verified input ownership and pure placement only; no repository creation, projection or publication"}


if __name__ == "__main__":
    print(json.dumps(check(Path(__file__).resolve().parents[1]), indent=2))
