"""Biome identities, resource rules and links to weather/terrain configuration."""

from .schema import NUMBER as N, Ref, component

SPECS = (
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
