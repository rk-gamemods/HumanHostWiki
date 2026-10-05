"""One index pass selects explicit domain contracts and accounts for other objects.

The full index stays in the source repository. Only selected fields and bounded
type summaries are observations. Domain contracts do not infer mechanics from
class names or copy unrecognized field bags.
"""

from collections import Counter
import itertools

from . import acquisition, biomes, characters, combat, construction, controls, crafting, creatures, environment, equipment, inventory, navigation, spawning, survival, technical, traps, vehicles, world
from .items_loot import observation
from .entries import expand, english_labels
from .catalog_policy import category as classify
from .schema import Selection, OMIT
from ..storage import ContractError, digest, json_bytes

NAME = "component-contracts"
VERSION = 1
INPUTS = ("Catalog/views/object-index.jsonl",)
SPECS = tuple(spec for module in (acquisition, biomes, characters, combat, construction, controls, crafting, creatures, environment, equipment, inventory, navigation, spawning, survival, technical, traps, vehicles, world)
              for spec in module.SPECS)
BY_CLASS = {(spec.assembly, spec.name): spec for spec in SPECS}
KINDS = tuple(sorted({spec.kind for spec in SPECS} | {"component", "asset", "unclassified", "recipe", "status-effect"}))
# These classes have selected view contracts or are dependencies of those views.
# This accounts for their role without claiming every field has been interpreted.
VIEW_CLASSES = {("Item_Info", "Icon_Info"), ("UI", "Loot_Mgr"), ("UI", "Loot_Rate_Sets"),
                ("Use_F", "Object_Interact"), ("Language", "Tooltip_Text")}
PAYLOAD_TYPES = {"Texture2D", "Texture3D", "Cubemap", "Mesh", "AudioClip", "VideoClip", "Shader", "ComputeShader"}
MERCHANT_MANAGER_OBJECT = "Merchant_Mgr"


def identity_rule(record):
    spec = BY_CLASS.get((record.get("assembly"), record.get("class")))
    return spec.identity if spec else {}


def spec_for(row):
    key = (row.get("assembly"), row.get("class"))
    if key[0] is not None:
        return BY_CLASS.get(key)
    # Older catalog indexes do not carry assembly. Raw records must prove it.
    matches = [spec for spec in SPECS if spec.name == key[1]]
    return matches[0] if len(matches) == 1 else None


def prepare(source, issues):
    selected, groups, manager_objects, counts = {}, {}, {}, Counter()
    last = None
    for row in source.records(INPUTS[0]):
        identity = row.get("id")
        if not isinstance(identity, str) or not isinstance(row.get("type"), str):
            raise ContractError("Malformed catalog object index")
        if last is not None and identity <= last:
            raise ContractError("Catalog object index must have unique sorted identities")
        last = identity
        cls, assembly = row.get("class"), row.get("assembly")
        if row["type"] == "GameObject" and row.get("name") == MERCHANT_MANAGER_OBJECT:
            manager_objects[identity] = row
            if row.get("record"):
                source.locations[identity] = row["record"]
        spec = spec_for(row)
        if spec or cls in {"Tooltip_Text", "Language_Text"}:
            if row.get("record"):
                source.locations[identity] = row["record"]
        if spec:
            selected[identity] = row
        category = classify(row, spec is not None, VIEW_CLASSES, PAYLOAD_TYPES)
        if spec and spec.summary_only:
            category = "technical-component"
        counts[category] += 1
        key = (row["type"], assembly or "", cls or "", category)
        group = groups.setdefault(key, {"count": 0, "examples": []})
        group["count"] += 1
        if len(group["examples"]) < 8:
            group["examples"].append(identity)
    source.catalog = {"selected": selected, "groups": groups, "manager_objects": manager_objects,
                      "coverage": {"scope": "catalog-accounting; not complete gameplay interpretation",
                                   "objects": sum(counts.values()), "accounting": dict(sorted(counts.items())),
                                   "index": INPUTS[0], "index_sha256": source.dependencies[INPUTS[0]]["sha256"]}}


def record_chunks(identities, locations, byte_limit=2 * 1024 * 1024, count_limit=128):
    """Bound decoded batches by input size; an oversized record runs alone."""
    chunk, total = [], 0
    for identity in identities:
        size = locations[identity].get("bytes")
        # Unknown sizes are isolated. The source reader owns offset/hash/size
        # validation; this planner never substitutes metadata for that check.
        if type(size) is not int or size < 1:
            size = byte_limit
        if chunk and (len(chunk) >= count_limit or total + size > byte_limit):
            yield chunk
            chunk, total = [], 0
        chunk.append(identity)
        total += size
    if chunk:
        yield chunk


def selected_records(source):
    # Keep at most 128 raw records resident. Group by shard so legacy snapshots
    # without offsets require a single stream for each relevant shard.
    ids = sorted(source.catalog["selected"], key=lambda identity: (source.object_path(identity), identity))
    for path, group in itertools.groupby(ids, source.object_path):
        wanted = list(group)
        if all(identity in source.locations for identity in wanted):
            for chunk in record_chunks(wanted, source.locations):
                selection = {identity: spec_for(source.catalog["selected"][identity]).fields.selected
                             for identity in chunk if "members" in source.locations[identity]}
                rows = source.objects(chunk, fields=selection) if selection else source.objects(chunk)
                for identity in chunk:
                    yield identity, rows.get(identity)
                del rows
        else:
            wanted_set = set(wanted)
            for row in source.records(path):
                if row.get("id") in wanted_set:
                    wanted_set.remove(row["id"])
                    yield row["id"], row
            for identity in sorted(wanted_set):
                yield identity, None


def extract(source, issues):
    pending = []
    # Read the small manager GameObject before selected_records can hold a legacy
    # shard stream open. Its active flag is a separate serialized object fact.
    manager_records = source.objects(sorted(source.catalog.get("manager_objects", {}))) if source.catalog.get("manager_objects") else {}
    # Prepare before selected_records can yield from a still-open legacy shard.
    mineable_items = (biomes.prepare_mineable_items(source)
                     if any(spec_for(metadata).name == "Terrain_Block_Info"
                            for metadata in source.catalog["selected"].values()) else None)
    for identity, record in selected_records(source):
        metadata = source.catalog["selected"][identity]
        spec = spec_for(metadata)
        if record is None:
            issues.add("missing-object", spec.topic, spec.name,
                       "An indexed component has no decoded record; its facts were omitted.", identity)
            continue
        script = record.get("script", {})
        if (script.get("assembly"), script.get("class")) != (spec.assembly, spec.name):
            issues.add("component-identity", spec.topic, spec.name,
                       "The decoded component does not match its selected contract; facts were omitted.", identity)
            continue
        selector = Selection(record, spec, issues)
        facts = selector.select(record.get("fields"), spec.fields)
        if facts is OMIT:
            facts = {}
        if spec.summary_only:
            continue
        row = observation(spec.kind, identity, metadata.get("name"), facts, source.object_path(identity),
                          selector.evidence, selector.links)
        row["component"] = {"assembly": spec.assembly, "class": spec.name}
        row["asset_paths"] = metadata.get("paths", [])
        row["fact_scope"] = "serialized-component-configuration"
        row["notes"] = spec.notes
        row["name_status"] = "internal"
        # Component and domain identities are still observations, not matches
        # across builds. m_GameObject is an evidenced within-snapshot join key.
        row["game_objects"] = sorted(ref["target"] for ref in record.get("references", [])
                                     if ref.get("field") == "/m_GameObject" and ref.get("status") == "resolved" and "target" in ref)
        if (spec.assembly, spec.name) == ("Merchant", "Merchant_Mgr"):
            managers = sorted(set(row["game_objects"]) & source.catalog.get("manager_objects", {}).keys())
            if len(managers) == 1:
                manager_id = managers[0]
                manager = manager_records.get(manager_id)
                fields = manager.get("fields", {}) if manager and manager.get("type") == "GameObject" else {}
                if fields.get("m_Name") == MERCHANT_MANAGER_OBJECT and type(fields.get("m_IsActive")) is bool:
                    row["facts"].update(manager_object=MERCHANT_MANAGER_OBJECT, manager_active=fields["m_IsActive"])
                    evidence = {"path": source.object_path(manager_id), "object": manager_id,
                                "fields": ["/m_Name", "/m_IsActive"]}
                    if manager_id in source.locations:
                        evidence["record_sha256"] = source.locations[manager_id]["sha256"]
                    row["evidence"].append(evidence)
        if identity in source.locations:
            row["evidence"][0]["record_sha256"] = source.locations[identity]["sha256"]
        if spec.name == "Terrain_Block_Info":
            biomes.enrich_mineable_items(row, mineable_items, issues)
        if spec.identity.get("kind") == "definition":
            pending.append(row)
        else:
            yield from expand(row, getattr(source, "item_names", {}), {})

    labels = english_labels(source, pending, issues)
    for row in pending:
        yield from expand(row, getattr(source, "item_names", {}), labels)

    for (engine_type, assembly, cls, category), group in sorted(source.catalog["groups"].items()):
        if category == "payload-omitted":
            continue
        key = "catalog-type/" + digest(json_bytes([engine_type, assembly, cls]))[:32]
        kind = "unclassified" if category == "uninterpreted-component" else "component" if cls else "asset"
        facts = {"engine_type": engine_type, "assembly": assembly or None, "class": cls or None,
                 "record_count": group["count"], "coverage": category}
        row = observation(kind, key, cls or engine_type, facts, INPUTS[0], ["type", "assembly", "class"])
        row["examples"] = group["examples"]
        row["fact_scope"] = "catalog-type-summary"
        spec = BY_CLASS.get((assembly, cls))
        if spec and spec.summary_only:
            row["notes"] = spec.notes
        row["evidence"][0].pop("object")
        row["evidence"][0]["selection"] = {"type": engine_type, "assembly": assembly or None, "class": cls or None}
        gaps = [gap for gap in source.catalog["coverage"].get("decode_gaps", [])
                if (gap.get("script", {}).get("assembly"), gap.get("script", {}).get("class")) == (assembly, cls)]
        if gaps:
            row["decode_gaps"] = gaps
        if kind == "unclassified":
            issues.add("unsupported-component", "technical-reference", assembly + "/" + cls,
                       "No domain field contract exists; a bounded technical type summary is retained.",
                       group["examples"][0], count=group["count"])
        yield row
