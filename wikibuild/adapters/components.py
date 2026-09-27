"""One index pass selects explicit domain contracts and accounts for other objects.

The full index stays in the source repository. Only selected fields and bounded
type summaries are observations. Domain contracts do not infer mechanics from
class names or copy unrecognized field bags.
"""

from collections import Counter
import itertools

from . import biomes, combat, construction, crafting, creatures, equipment, spawning, survival, technical, traps, vehicles, world
from .items_loot import observation
from .entries import expand, english_labels
from .catalog_policy import category as classify
from .schema import Selection, OMIT
from ..storage import ContractError, digest, json_bytes

NAME = "component-contracts"
VERSION = 1
INPUTS = ("Catalog/views/object-index.jsonl",)
SPECS = tuple(spec for module in (biomes, combat, construction, crafting, creatures, equipment, spawning, survival, technical, traps, vehicles, world)
              for spec in module.SPECS)
BY_CLASS = {(spec.assembly, spec.name): spec for spec in SPECS}
KINDS = tuple(sorted({spec.kind for spec in SPECS} | {"component", "asset", "unclassified", "recipe", "status-effect"}))
# These classes have selected view contracts or are dependencies of those views.
# This accounts for their role without claiming every field has been interpreted.
VIEW_CLASSES = {("Item_Info", "Icon_Info"), ("UI", "Loot_Mgr"), ("UI", "Loot_Rate_Sets"),
                ("Use_F", "Object_Interact"), ("Language", "Tooltip_Text")}
PAYLOAD_TYPES = {"Texture2D", "Texture3D", "Cubemap", "Mesh", "AudioClip", "VideoClip", "Shader", "ComputeShader"}


def spec_for(row):
    key = (row.get("assembly"), row.get("class"))
    if key[0] is not None:
        return BY_CLASS.get(key)
    # Older catalog indexes do not carry assembly. Raw records must prove it.
    matches = [spec for spec in SPECS if spec.name == key[1]]
    return matches[0] if len(matches) == 1 else None


def prepare(source, issues):
    selected, groups, counts = {}, {}, Counter()
    last = None
    for row in source.records(INPUTS[0]):
        identity = row.get("id")
        if not isinstance(identity, str) or not isinstance(row.get("type"), str):
            raise ContractError("Malformed catalog object index")
        if last is not None and identity <= last:
            raise ContractError("Catalog object index must have unique sorted identities")
        last = identity
        cls, assembly = row.get("class"), row.get("assembly")
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
    source.catalog = {"selected": selected, "groups": groups,
                      "coverage": {"scope": "catalog-accounting; not complete gameplay interpretation",
                                   "objects": sum(counts.values()), "accounting": dict(sorted(counts.items())),
                                   "index": INPUTS[0], "index_sha256": source.dependencies[INPUTS[0]]["sha256"]}}


def selected_records(source):
    # Keep at most 128 raw records resident. Group by shard so legacy snapshots
    # without offsets require a single stream for each relevant shard.
    ids = sorted(source.catalog["selected"], key=lambda identity: (source.object_path(identity), identity))
    for path, group in itertools.groupby(ids, source.object_path):
        wanted = list(group)
        if all(identity in source.locations for identity in wanted):
            for start in range(0, len(wanted), 128):
                chunk = wanted[start:start + 128]
                rows = source.objects(chunk)
                for identity in chunk:
                    yield identity, rows.get(identity)
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
        if identity in source.locations:
            row["evidence"][0]["record_sha256"] = source.locations[identity]["sha256"]
        if spec.name in {"All_Skills_Set", "Skill_Mgr"}:
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
