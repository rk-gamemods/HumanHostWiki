"""Biome identities, resource rules and links to weather/terrain configuration."""

from .schema import NUMBER as N, IndexCounts, Ref, component, numbers

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
