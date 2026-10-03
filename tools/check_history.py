"""Independently verify normalized observations, revision hashes and identity state.

Imports no identity, model, history or source-reader implementation. This validates
record conservation and graph/provenance integrity, not every matching decision's
real-world interpretation or gameplay behavior.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def checked(root, descriptor):
    path = (root / descriptor["path"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Artifact escaped the wiki root")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    if sha.hexdigest() != descriptor["sha256"] or path.stat().st_size != descriptor["bytes"]:
        raise ValueError("Artifact hash/size differs")
    return path


def records(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def check(root, source):
    pointer = json.loads((root / "identity/latest.json").read_text())
    run = json.loads((root / f"identity/runs/{pointer['run_id']}.json").read_text())
    extracted = json.loads((root / f".local/extractions/runs/{run['extraction_run']}.json").read_text())
    observations = {row["observation_key"]: row for row in records(checked(root, extracted["records"]))}
    states = {row["entity_key"]: row for row in records(checked(root, run["state"]))}
    models_path = checked(root, run["models"])
    seen, aliases, summaries = set(), {}, {}
    assertions = 0
    for row in records(models_path):
        entity, semantic, provenance = row["entity_key"], row["semantic"], row["provenance"]
        key = provenance["observation_key"]
        if key in seen or key not in observations:
            raise ValueError("Duplicate or unknown normalized observation")
        seen.add(key)
        original = observations[key]
        for field in ("kind", "topic", "name", "facts", "evidence_level"):
            if semantic[field] != original[field]:
                raise ValueError(f"Selected observation changed during normalization: {field}: {key}")
            assertions += 1
        if semantic.get('fact_labels', {}) != original.get('fact_labels', {}):
            raise ValueError('Readable coded labels changed during normalization')
        expected = hashlib.sha256((json.dumps(semantic, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()).hexdigest()
        if expected != row["revision_id"] or states[entity]["revision_id"] != expected:
            raise ValueError("Semantic revision hash or state differs")
        if states[entity]["status"] != "present" or row["snapshot_id"] != run["snapshot_id"]:
            raise ValueError("Current observation has wrong presence or snapshot")
        if provenance["source_id"] != original["source_id"]:
            raise ValueError("Source identifier changed")
        aliases[entity] = {original["source_id"], *original.get("game_objects", [])}
        if original.get("fact_scope") == "catalog-type-summary":
            facts = original["facts"]
            summaries[entity] = (facts["engine_type"], facts.get("assembly"), facts.get("class"))
        for evidence in provenance["evidence"]:
            dependency = extracted["dependencies"][evidence["path"]]
            if evidence["git_blob"] != dependency["git_blob"]:
                raise ValueError("Evidence does not name its pinned blob")
            assertions += 1
        assertions += 3
    if seen != observations.keys():
        raise ValueError("An extracted observation was lost")
    if len(seen) != sum(state["status"] == "present" for state in states.values()):
        raise ValueError("Presence ledger differs from model coverage")
    technical = {}
    for row in records(models_path):
        for link in row["semantic"]["relationships"]:
            for target in link.get("targets", []) + link.get("technical_targets", []):
                if target not in aliases:
                    raise ValueError("Relationship leaves the selected snapshot")
                assertions += 1
        for target in row["provenance"]["resolved_targets"]:
            if target["status"] == "resolved":
                if target["target_source_id"] not in aliases[target["target_entity"]]:
                    raise ValueError("Canonical edge does not match its raw target")
                assertions += 1
            elif target["status"] == "technical-summary":
                expected = summaries[target["target_entity"]]
                prior = technical.setdefault(target["target_source_id"], expected)
                if prior != expected:
                    raise ValueError("A source target acquired conflicting type summaries")
    process = subprocess.Popen(["git", "-C", str(source), "show", run["source_commit"] + ":Catalog/views/object-index.jsonl"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for line in process.stdout:
        record = json.loads(line)
        if record["id"] in technical:
            expected = technical.pop(record["id"])
            if (record["type"], record.get("assembly"), record.get("class")) != expected:
                raise ValueError("Technical edge has the wrong source type")
            assertions += 1
    process.stdout.close()
    error = process.stderr.read().decode(errors="replace")
    process.stderr.close()
    if process.wait():
        raise ValueError("Could not inspect pinned object index: " + error)
    if technical:
        raise ValueError("A technical target is missing from the pinned catalog")
    return {"run_id": run["run_id"], "snapshot_id": run["snapshot_id"], "observations_checked": len(seen),
            "assertions": assertions, "status": "passed",
            "scope": "All selected observations, semantic hashes, canonical edge targets and provenance; not runtime verification"}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root.parent / "HumanHostCodebase")
    print(json.dumps(check(root, parser.parse_args().source), indent=2))
