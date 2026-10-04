"""Audit physical URLs against real reader bytes without writing or publishing sites."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time
import tracemalloc
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.audit_shard_index import leaves
from tools.audit_capture_catalog import expand
from tools.audit_external_articles import compare as compare_articles
from tools.audit_fonts import compare as compare_fonts


def audit(candidate, projection, owner):
    """Independent URL/byte conservation check; no builder transforms are reused."""
    manifest = json.loads((candidate / "candidate.json").read_bytes())
    base = f"https://{owner}.github.io/"
    locations = {part.id: base + part.github_name + "/" for part in projection.partitions}
    objects = {locations[item.partition] + item.artifact.path.removeprefix("site/"): item
               for item in projection.placements}
    counts = {"objects": 0, "bytes": 0, "snapshots": 0, "pack_references": 0, "relocated_pack_references": 0}
    for item in objects.values():
        artifact = item.artifact
        data = projection.payloads[artifact.key].read()
        assert len(data) == artifact.bytes and hashlib.sha256(data).hexdigest() == artifact.sha256
        if artifact.path.startswith(("site/data/", "site/runtime/", "site/fonts/")):
            relative = artifact.path.removeprefix("site/")
            if relative.startswith("runtime/"):
                relative = relative.rsplit("/", 1)[1]
            original = manifest["files"][artifact.topic + "/" + relative]
            assert (artifact.sha256, artifact.bytes) == (original["sha256"], original["bytes"])
        counts["objects"] += 1
        counts["bytes"] += len(data)

    for topic, config_ref in projection.configurations.items():
        topic_base = manifest["inputs"]["bases"][topic]

        def resolve(ref):
            item = objects[urljoin(topic_base, ref["path"])]
            assert item.artifact.topic == topic
            assert (item.artifact.sha256, item.artifact.bytes) == (ref["sha256"], ref["bytes"])
            return json.loads(projection.payloads[item.artifact.key].read())

        config = expand(resolve(config_ref), resolve)
        original_config = json.loads((candidate / topic / "reader.json").read_bytes())
        assert config["release_id"] == projection.release_id
        assert {k: v for k, v in config.items() if k not in {"release_id", "publication", "runtime", "snapshots", "external_articles", "fonts"}} == {
            k: v for k, v in original_config.items() if k not in {"publication", "external_articles", "fonts"}}
        def font_bytes(ref):
            item = objects[ref["path"]]
            assert item.artifact.topic == "hub"
            return projection.payloads[item.artifact.key].read()
        compare_fonts(original_config.get("fonts"), config.get("fonts"), font_bytes)
        compare_articles(original_config.get("external_articles"), config.get("external_articles"), resolve)
        for extension, name in config["runtime"].items():
            item = objects[urljoin(topic_base, name)]
            original = manifest["files"][topic + "/reader." + extension]
            assert item.artifact.topic == topic
            assert (item.artifact.sha256, item.artifact.bytes) == (original["sha256"], original["bytes"])
        for snapshot, ref in config["snapshots"].items():
            index = resolve(ref)
            original = json.loads((candidate / topic / "snapshots" / (snapshot + ".json")).read_bytes())
            for kind in ("entries", "semantics", "provenance", "search", "backlinks", "cards", "player", "guides"):
                if kind in {"cards", "player", "guides"} and kind not in original:
                    continue
                if kind != "guides":
                    index[kind] = list(leaves(index[kind], resolve))
                assert len(index[kind]) == len(original[kind])
                for actual, expected in zip(index[kind], original[kind]):
                    item = objects[urljoin(topic_base, actual["path"])]
                    assert item.artifact.topic == topic
                    assert (item.artifact.sha256, item.artifact.bytes) == (expected["sha256"], expected["bytes"])
                    assert {k: v for k, v in actual.items() if k != "path"} == {k: v for k, v in expected.items() if k != "path"}
                    counts["pack_references"] += 1
                    counts["relocated_pack_references"] += actual["path"] != expected["path"]
                index[kind] = original[kind]
            assert index == original
            counts["snapshots"] += 1
    # Every immutable candidate input has a projected counterpart, including an
    # unreferenced pack. No new fact pack may be invented by location projection.
    expected_leaves = {(name.split("/", 1)[0], value["sha256"], value["bytes"])
                       for name, value in manifest["files"].items()
                       if "/data/" in name or "/fonts/" in name or name.endswith(("/reader.js", "/reader.css"))}
    actual_leaves = {(item.artifact.topic, item.artifact.sha256, item.artifact.bytes)
                     for item in objects.values() if item.artifact.path.startswith(("site/data/", "site/runtime/", "site/fonts/"))}
    assert actual_leaves == expected_leaves
    return counts


def check(root):
    from wikibuild import capacity, capacity_projection, manifest, reader, release
    from wikibuild.storage import writer_lock

    started = time.perf_counter()
    tracemalloc.start()
    with writer_lock(root):
        project = manifest.load(root)
        inventory = release.inventory(root, project)
        current = release.read(root, inventory.release_id)
        candidate = reader.candidate_path(root / ".local", current["reader_candidate"])
        same = capacity_projection.build(candidate, inventory.release_id, project["github_owner"],
                                         inventory.partitions, inventory.stored)
        assert not same.created and not list(same.writes())
        unchanged = audit(candidate, same, project["github_owner"])
        limits = capacity.Budgets(file_bytes=capacity.MIB, site_bytes=2 * capacity.MIB,
                                  history_bytes=4 * capacity.MIB, site_reserve_bytes=128 * 1024,
                                  history_reserve_bytes=128 * 1024)
        empty = [capacity.partition(topic, 0) for topic in inventory.topics]
        forced = capacity_projection.build(candidate, inventory.release_id, project["github_owner"], empty, budgets=limits)
        projected = audit(candidate, forced, project["github_owner"])
        assert forced.created and projected["relocated_pack_references"] > 0
        again = capacity_projection.build(candidate, inventory.release_id, project["github_owner"],
                                          forced.partitions, forced.placements, budgets=limits)
        assert not again.created and not list(again.writes())
        assert again.placements == forced.placements and again.configurations == forced.configurations
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {"status": "passed", "release_id": inventory.release_id, "candidate_id": current["reader_candidate"],
            "unchanged": unchanged, "forced": projected, "forced_budgets": asdict(limits),
            "forced_new_partitions": len(forced.created), "replay_new_writes": 0,
            "python_peak_bytes": peak, "elapsed_seconds": round(time.perf_counter() - started, 3),
            "scope": "Reference projection and byte conservation only; no destination writes, provisioning or publication"}


if __name__ == "__main__":
    print(json.dumps(check(Path(__file__).resolve().parents[1]), indent=2))
