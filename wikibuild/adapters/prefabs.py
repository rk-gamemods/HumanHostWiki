"""Individual identities for explicitly selected prefab references.

An item model is a GameObject, not an arbitrary component attached to it. A
headless corpse prefab is not a living AI agent. Select only GameObjects reached
by explicit domain relationships, retaining no unrelated objects or payloads.
"""

from collections import defaultdict

from .items_loot import observation

NAME = "referenced-prefabs"
VERSION = 1
INPUTS = ("Catalog/views/object-index.jsonl",)
KINDS = ("asset",)
REQUIRED_PREFABS = {"model", "headless-prefab"}


def prepare(source, issues):
    source.prefab_targets = set()
    source.required_prefab_targets = set()
    source.prefab_components = defaultdict(dict)


def observe(source, row):
    """Collect small join keys while the preceding adapters stream their results."""
    if row.get("fact_scope") == "referenced-prefab-identity":
        return
    for link in row.get("relationships", []):
        targets = link.get("target_source_ids",
                           [link["target_source_id"]] if link.get("target_source_id") else [])
        source.prefab_targets.update(targets)
        if link["predicate"] in REQUIRED_PREFABS:
            source.required_prefab_targets.update(targets)
    if "component" in row:
        for identity in row.get("game_objects", []):
            source.prefab_components[identity][row["source_id"]] = {
                **row["evidence"][0], "fields": ["/m_GameObject"]}


def extract(source, issues):
    if not source.prefab_targets:
        return
    missing = set(source.prefab_targets)
    # Targets are discovered during component extraction. A second streaming
    # index pass avoids holding the entire object index or raw prefab records.
    for metadata in source.records(INPUTS[0]):
        identity = metadata["id"]
        if identity not in missing:
            continue
        missing.remove(identity)
        if metadata["type"] != "GameObject":
            if identity in source.required_prefab_targets:
                issues.add("prefab-target-type", "technical-reference", metadata["type"],
                           "A selected prefab reference no longer targets a GameObject.", identity)
            continue
        row = observation("asset", identity, metadata.get("name"),
                          {"engine_type": "GameObject"}, INPUTS[0], ["id", "name", "type"])
        row["asset_paths"] = metadata.get("paths", [])
        row["fact_scope"] = "referenced-prefab-identity"
        row["name_status"] = "internal"
        row["notes"] = "Identity of a referenced prefab; component links include only cataloged configurations."
        components = source.prefab_components.get(identity, {})
        row["relationships"] = [{"predicate": "cataloged-component", "target_source_id": component,
                                 "source_field": "/m_GameObject", "source_object": component,
                                 "direction": "inverse"} for component in sorted(components)]
        row["evidence"].extend(components[key] for key in sorted(components))
        yield row
    for identity in sorted(missing & source.required_prefab_targets):
        issues.add("missing-prefab", "technical-reference", "referenced-prefab",
                   "A selected prefab reference is absent from the object index.", identity)
