"""Spawn distances, horde settings and biome population references."""

from .schema import NUMBER as N, V2, Ref, component, fields, numbers

SPECS = (
    component("Terrain", "NPC_Horde_Mgr", "spawn-rule", "spawning-populations", {
        **numbers("_HordeZombieAll _MaxAllowActiveZombies _MinSpawnDistance _SpawnRadius _ZombiesPerWaveAdd _ZombiesPioneerCount"),
        "_HordeIntervalHours": V2, "_ReFocusDelayWhenPlayerRespawn": V2,
    }, "_G_Info _GetMaxAllowActiveZombies _NextHordeText _NpcOnFocus"),
    component("Terrain", "NPC_Spawner_Mgr", "population", "spawning-populations", {
        **numbers("_DestroyDismemberBody_Time _SwtichToGPUI_Time _maxDeadRagdolls checkInterval despawnRadius indoorTryGetSpaceTimes noSpawnRadius spawnRadius timeSliceInterval"),
        "NPC_Biomes": [{"bioType": Ref("biome"), "groupBandDis": N,
            "groups": [fields({"biomeIndex": int, "npcBioSetRef": Ref("spawn-set"),
                               "outdoorSum": int, "sampleAll_Indoor": int, "sampleAll_Outdoor": int,
                               "sampleArray_Indoor": [int], "sampleArray_Outdoor": [int]},
                              "gpuCrowdMgr npcBioSetIns npcInsCount")]}],
    }, "G_Info NPC_Top On_TerraNPC_Spawned _inAsync _needReSortTerras"),
    component("Build_System", "TerraTop_NPC_Set", "spawn-rule", "spawning-populations", {
        "NPC_Prefabs": [{"NPC_Prefab": Ref("spawns-prefab"), "NoHeadPrefab": Ref("headless-prefab"),
                         "allowInDoor": int, "rateCount": int}],
    }, "_GPUI_CrowdMgr_Prefab"),
)
