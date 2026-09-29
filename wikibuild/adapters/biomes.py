"""Biome identities, resource rules and links to weather/terrain configuration."""

from collections import defaultdict
import re

from .schema import NUMBER as N, IndexCounts, Ref, component, numbers

ADDRESSABLES = "Catalog/addressables.jsonl"
ITEMS = "Catalog/views/items.jsonl"
ICON_FIELD = re.compile(r"/_Collectable_Info/_Items/\d+/_IconRef")

SPECS = (
    component("Build_System", "Terrain_Data_Top", "resource-distribution", "biomes-resources", {
        "_terrainDatas": [Ref("terrain-data-asset")],
    }, "_microSplatMat", notes="Terrain-data asset bindings only; terrain geometry and texture payloads remain local."),
    component("Build_System", "TerrainTreeManager", "resource-distribution", "biomes-resources", {
        "_VegetationSoundMats": [Ref("material")], "_GrassSoundMat": Ref("material"),
        **numbers("_InitDis _UnloadDis radiusTree checkTreeInterval"),
    }, "In_LoadTreeSpawners _AO_AutoAjust _GI_On _InBlendingTerraEdge _inDestroyTerraTop _inRegTerra _inUnRegTerra _interFactor _playerPosChaSqt _prefabManager _radiusTreeShadow _radiusTreeShadowSqt _treeAroundSum _treeAroundSum5M",
       notes="Vegetation material bindings and terrain/tree activation distances; check interval in seconds. These are streaming/interaction settings, not a species spawn probability."),
    component("Build_System", "ScenePropManager", "resource-distribution", "biomes-resources", {
        **numbers("aroundPlayerDisBig aroundPlayerDisDecal aroundPlayerDistance disToPutBackPool disToPutBackPoolBig disToPutBackPoolDecal forceCheckTimeAfterTeleported spawnIntervalSeconds"),
    }, "_foundTerrasAround insAroundPlayer insAroundPlayerBig insAroundPlayerDecal loaded_PropSpawners prototypesAround prototypesAroundBig prototypesAroundDecal saveDataManagerObj",
       notes="Scene-prop activation and pooling distances, check interval and post-teleport force-check duration. These do not imply renewable resource respawn times."),
    component("Build_System", "ScenePropSpawner", "resource-distribution", "biomes-resources", {
        "PropsRefNoRepeat": [Ref("scene-prop-prefab")], "PropsRefNoRepeatBig": [Ref("scene-prop-prefab")],
        "ScenePropsInfo": IndexCounts("PropsRefNoRepeat", "localPos localEuler localScale"),
        "ScenePropsInfoBig": IndexCounts("PropsRefNoRepeatBig", "localPos localEuler localScale"),
    }, "DecalsInfo DecalsRefNoRepeat _inRegistProps _inUnregistProps belongTerrain isDirty terraCol",
       notes="Scene-prop prefab tables and counts grouped by prototype index. Each source placement contributes to total_count; invalid indices contribute to unresolved_count. These describe configured composition, not renewable respawn or current world populations. Repeated placement rows, geometry, visual decals and mutable world state are omitted."),
    component("Build_System", "Big_Terra_Bio_Type", "biome", "biomes-resources", {}),
    component("Build_System", "Terrain_Block_Info", "resource-distribution", "biomes-resources", {
        "_BlockInfo": [{"CollectableItems": [{"ItemBI_refKey": str, "Name": str, "RandomRate": N}]}],
    }),
    component("Build_System", "Terrain_Top", "resource-distribution", "biomes-resources", {
        "_BiomesType": Ref("biome"), "_TerrainBlockSet": Ref("terrain-block-set"),
        "_localWeatherZone": Ref("weather-zone"), "_scenePropsTopRef": Ref("scene-props"),
        "_terrainDatasTopRef": Ref("terrain-data"), "_treeGrassRefs": [Ref("vegetation")],
    }, """TerrainTopIsOnDestroy _4terrasPerTreeInsCount _BioBlendTexIndex _BlendOverRockTex _DirtTexIndex
_RockUndergroundTexIndex _saveLoadChunks _scenePropSpawners _sysHouseSpawners terraTreeSpawners terrains"""),
)


def prepare_mineable_items(source):
    """Join exact terrain addresses through prefab collectable refs to item IDs."""
    terrain_ids = [identity for identity, metadata in source.catalog["selected"].items()
                   if metadata.get("class") == "Terrain_Block_Info"
                   and metadata.get("assembly") in (None, "Build_System")]
    keys = set()
    for record in source.objects(terrain_ids).values():
        if record.get("script", {}).get("assembly") != "Build_System" or record["script"].get("class") != "Terrain_Block_Info":
            continue
        for block in record.get("fields", {}).get("_BlockInfo", []):
            if not isinstance(block, dict):
                continue
            for entry in block.get("CollectableItems", []):
                if isinstance(entry, dict) and isinstance(entry.get("ItemBI_refKey"), str):
                    keys.add(entry["ItemBI_refKey"])

    by_name, by_object = defaultdict(set), defaultdict(set)
    for item in source.records(ITEMS):
        if not isinstance(item.get("id"), str):
            continue
        if isinstance(item.get("name"), str):
            by_name[item["name"]].add(item["id"])
        for object_id in item.get("game_objects", []):
            if isinstance(object_id, str):
                by_object[object_id].add(item["id"])

    addresses = defaultdict(list)
    for entry in source.records(ADDRESSABLES):
        if entry.get("resource_type", {}).get("m_ClassName") != "UnityEngine.GameObject":
            continue
        for key in entry.get("keys", []):
            if isinstance(key, str) and key in keys:
                addresses[key].append(entry)

    prefab_ids = {target for entries in addresses.values() for entry in entries
                  for target in entry.get("targets", []) if isinstance(target, str)}
    prefabs = source.objects(prefab_ids)
    component_ids = {ref["target"] for prefab in prefabs.values()
                     if prefab.get("type") == "GameObject"
                     for ref in prefab.get("references", [])
                     if re.fullmatch(r"/m_Component/\d+/component", ref.get("field", ""))
                     and ref.get("status") == "resolved" and isinstance(ref.get("target"), str)}
    components = source.objects(component_ids)
    by_address = {}
    for key, entries in addresses.items():
        targets, evidence = set(), []
        for entry in entries:
            evidence.append({"path": ADDRESSABLES, "entry": entry.get("entry"), "fields": ["keys", "targets"]})
            for prefab_id in entry.get("targets", []):
                prefab = prefabs.get(prefab_id)
                if not prefab or prefab.get("type") != "GameObject":
                    continue
                evidence.append({"path": source.object_path(prefab_id), "object": prefab_id,
                                 "fields": ["/m_Component"]})
                for ref in prefab.get("references", []):
                    component = components.get(ref.get("target")) if ref.get("status") == "resolved" else None
                    script = component.get("script", {}) if component else {}
                    if script.get("assembly") != "Build_System" or script.get("class") != "Build_Info":
                        continue
                    icon_refs = [icon for icon in component.get("references", [])
                                 if ICON_FIELD.fullmatch(icon.get("field", "")) and icon.get("status") == "resolved"]
                    for icon in icon_refs:
                        for icon_object in icon.get("targets", [icon["target"]] if "target" in icon else []):
                            targets.update(by_object.get(icon_object, ()))
                    if icon_refs:
                        evidence.append({"path": source.object_path(component["id"]), "object": component["id"],
                                         "fields": sorted(icon["field"] for icon in icon_refs)})
        by_address[key] = (targets, evidence)
    return by_address, by_name


def enrich_mineable_items(row, resolved, issues):
    """Keep one link or explicit gap per selected CollectableItems entry."""
    by_address, by_name = resolved
    for block_index, block in enumerate(row["facts"].get("_BlockInfo", [])):
        if not isinstance(block, dict):
            continue
        for entry_index, entry in enumerate(block.get("CollectableItems", [])):
            field = f"/_BlockInfo/{block_index}/CollectableItems/{entry_index}"
            entry = entry if isinstance(entry, dict) else {}
            key, name = entry.get("ItemBI_refKey"), entry.get("Name")
            targets, evidence = by_address.get(key, (set(), []))
            evidence = list(evidence)
            if len(targets) == 1:
                path = "address"
            elif not targets and isinstance(name, str) and len(by_name.get(name, ())) == 1:
                targets, evidence, path = by_name[name], [{"path": ITEMS, "fields": ["name", "id"]}], "name"
            else:
                targets, evidence, path = set(), [], "unresolved"
            link = {"predicate": "mineable-item", "source_field": field,
                    "resolution": path, "target_source_ids": sorted(targets)}
            if not targets:
                link["status"] = "unresolved"
                issues.add("mineable-item-gap", "biomes-resources",
                           "Terrain_Block_Info/_BlockInfo/*/CollectableItems/*",
                           "A mineable entry has no unique item target by address or exact name.", row["source_id"])
            else:
                evidence.append({"path": ITEMS, "object": next(iter(targets)), "fields": ["id", "name", "game_objects"]})
                for locator in evidence:
                    if locator not in row["evidence"]:
                        row["evidence"].append(locator)
            row["relationships"].append(link)
