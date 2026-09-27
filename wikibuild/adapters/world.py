"""Serialized weather configuration and clock settings, without visual payloads."""

from .schema import NUMBER as N, V2, V3, Ref, component, fields, numbers

SPECS = (
    component("Global_Funcs", "Global_Infos", "world-rule", "world-systems", {"minMaxHeight": V2},
       """BuildingPath CommonSetPath DamagedSysHousePath DeletedGrassPath DeletedPath
L_AntiCreatureCol L_AntiWallCol L_Armor L_Battle L_Build L_Bullet L_Creature L_DC
L_DroppedItem L_Ivy L_Preview L_Projectile L_RagDoll L_SFE L_Scene L_Smashed L_Trap L_WheelCol
Mask_1 Mask_10 Mask_10_11 Mask_10_13 Mask_10_14 Mask_10_15 Mask_10_16 Mask_10_16_22
Mask_13_14 Mask_16_21 Mask_18 Mask_1_11 Mask_2 Mask_21 Mask_2_10 Mask_2_10_3
Mask_2_8_9_10_11_13_14_18 Mask_2_8_9_10_13_14 Mask_2_8_9_10_13_14_18 Mask_2_8_9_10_14
Mask_2_8_9_10_14_18 Mask_3_10 Mask_4 Mask_8 Mask_8_10 Mask_8_10_11 Mask_8_10_13
Mask_8_10_13_15 Mask_8_10_18 Mask_8_11 Mask_Armor Mask_Battle Mask_Build Mask_Creature
Mask_Default Mask_Preview Mask_Ragdoll Mask_Scene Mask_Trap Mask_UI Mask_UseF
Mask_ZoneSlice Mask_ZoneSliceBaI MerchantPath NPC_Around_Path NPC_Horde_Path NPC_Points_Path
VehiclePath VehicleRepairPath _DirectLight _DirectLightTrans _GI_On _InterObjsPath
_IsWorldScene _QuitFromButton _Volume _contactShadows _quitButtonPressed _totalGameMinutes
heightLength heightLengthHalf maxHeightPosY midHeightPosY""",
       notes="World vertical bounds (x minimum, y maximum); derived height caches, layer masks, local save paths and live time/state are omitted."),
    component("Weather", "Weather_Controller", "world-rule", "world-systems", {
        "firstWeather": Ref("weather"), **numbers("updateInterval weatherBlendTime"),
        **dict.fromkeys("year month day hour minute".split(), int),
    }, """NPC_GPUISmoothPropers OnPreLoadWeatherData OnZoneChangeReflectTex
On_BeginLoadWeatherData THOR_Thunder WeatherInitAlready _24HourRate _AdaptiveGI_AmbientCorlor
_AdaptiveGI_AmbientCurve _AdaptiveGI_CurveForSnow _AntiProbeTimeCurve _CloudOpacityCurve _GI_On
_SkyboxSets _TVE_Mgr _WetShaders _accumulatorInitialized _adaptiveGI _aroundTerras _buildRate
_cloudLayer _colorAdjust _currSkyboxIndex _currWeatherBlendRate _currWeatherZoneSet
_currentWeather _currentWeatherIndex _currentWeatherZone _enviroMgr _fogTarget _fogVolume
_isLerpParamOrNewWeather _lastMinutes _lastSeconds _previousZonePos _reflectFactor
_sunFlaresGradient _underFeetWeatherZone _volumClouds _volumeLightDensityCurve
_volumeLightLengthCurve _waitToNewWeatherTopName _waitWeatherIndex _waitWeatherSet
_waitWeatherZone currentWeatherContinuedSeconds currentWeatherTargetTime playerUnderRoof
preLoadParticles unityVolume wetnessLevel""",
       notes="Initial weather/clock defaults, update interval and weather blending duration in seconds. Loaded saves override clock state. Current weather, wetness, transition progress and rendering controls are omitted."),
    component("Terrain", "SFE_Mgr", "world-rule", "world-systems", {
        **numbers("_MinDistance _MaxDistance _DestroyDistance _MinRespawnDelay _MaxRespawnDelay _MaxSurfaceAngle _ZombieGridSpacing _ZombieSpawnProbability"),
        "_SpawnPrefabs": [Ref("dungeon-entrance-prefab")], "_ExitTriggerPrefab": Ref("dungeon-exit-prefab"),
    }, "_DungeonCullingMask _EnterConfirmUI _ExitConfirmUI _ExitForceConfirmUI _GrowSpeed _SFELayer _ShrinkSpeed _SignalSmokePrefab _Volume",
       notes="Serialized dungeon-entrance placement distances, respawn delays in seconds and surface-angle limit in degrees. Zombie grid/probability fields have no uses in the captured source and do not establish active population behavior. Smoke animation and UI are omitted."),
    component("Terrain", "SFE_Player_Enter_Handler", "world-rule", "world-systems", {
        "_DungeonAssetReference": Ref("dungeon-prefab"), "_DungeonEntryLocalPos": V3, "_PlayerTag": str,
    }, notes="Dungeon prefab binding and entry position relative to that prefab. The entry handler checks the player tag, alive state and seat state before teleporting."),
    component("Terrain", "SFE_Exit_Trigger", "world-rule", "world-systems", {"_PlayerTag": str},
              notes="Tag accepted by the dungeon exit trigger; the trigger opens confirmation UI."),
    component("Terrain", "Terrain_Loader_Manager", "world-rule", "world-systems", {
        **numbers("_BiomesWidthNum BigTerraCountPerAxis BigTerraWidth _TerraSize DisToLoadChildChunk DisToUnLoadChildChunk CheckChunkDisInterval WorldFloatMaxDistance"),
        "_BaseBigTerrains": {"baseBigTerraTops": [Ref("base-terrain-prefab")], "BigTerraNames": [str]},
        "_BiomesLayers": [{"terrainTops": [Ref("biome-terrain-prefab")], "BigTerraNames": [str]}],
    }, "Mask_13_21 PullBackTheseObjects PullBackTheseObjectsChildren _LD_CornerFadeData _LU_CornerFadeData _RD_CornerFadeData _RU_CornerFadeData _terraWorldSeed neutralizedPlayerMove",
       notes="Serialized terrain-layer order, prefab bindings and streaming dimensions. The check interval is seconds. Player/world seed, live positions, origin-shift bindings and texture blending are omitted."),
    component("Player", "World_Map_Mgr", "world-rule", "world-systems", {
        **numbers("_ClearRadius _ClearIntervalDis _MaxScaleFactor"), "_timeOffsetMinutes": int,
    }, "_BlackBG _BuildTooltip _CompassPro _DragSpeedFactor _DragTrans _EnviroSkyVolume _Flag_Custom _Flag_Custom_Top _GameDaysText _GameTimeText _Map_DirectionalLight _MipMapRectTrans _MipMapRoot _OnOpenCloseMap _OpenSFX _PlayerPosText _Volume _inOpenMap _saveID",
       notes="Map exploration reveal radius/grid spacing, zoom limit and displayed clock offset in minutes. Explored locations, player positions, markers and save identifiers are omitted."),
    component("Weather", "Local_Wheather_Zone", "world-rule", "world-systems", {
        "_ZoneSets": Ref("weather-zone-settings"),
    }, "_WeatherChances", notes="Local weather zone's settings reference; runtime chance cache is excluded."),
    component("Weather", "Weather_Settings", "weather", "world-systems", {
        "weatherName": str, "weatherType": int,
        **numbers("maxContinueSeconds minContinueSeconds maxWetnessLevel thunderFrequency rainSecondsToHide rainSecondsToShow fogDensity"),
    }, """ParticlePrefab ParticleSound ParticleSoundVolume _AGI_Intens_Factor _GI_Intens_Factor
_sunFlareIntens ambientIntensMod playParticleDelay reflectionWeightIndoor reflectionWeightOutdoor
skyIntensity sunMoonColorRate volumCloudCover volumCloudDensity""",
       notes="Serialized weather configuration. fogDensity also feeds Solar_Generator.Generate_Power; it is retained for that gameplay dependency."),
    component("Weather", "WeatherZone_Settings", "world-rule", "world-systems", {
        "_WeatherInfoSets": [fields({"weatherChance": N, "weatherSet": Ref("weather")},
            "cloudLayerColor fogGroundColor fogWholeColor sunColorModAGI volumCloudColor weatherColorFilterAGI weatherColorFilterHGI")],
    }, """BGM_Day BGM_Day_Volume BGM_Emo BGM_Emo_Volume BGM_Night BGM_Night_Volume
_AGI_FarBrightness _AGI_FarColorDirectLRate _AGI_Intense _AGI_IsDenseForest _AGI_IsJungleForest
_AGI_NormalIntens _AGI_Snowland_Use _AGI_SunColorLRate _EmoBGM_Interval _Forest_GI_Factor
_Forest_ILC_BaseFactor _GI_HBAO_Dis _HAO_Radius _HAO_Thick _HGI_Color_factor _HasTraxEffect
_Indoor_Reflect_Factor _Inforest_ILC_factor _Outdoor_GI_Factor _Outdoor_ILC_factor
_Outdoor_Reflect_Factor _SunIntenseCurve _TreeMaxAsFull _exposureAGI _exposureCompenAGI
_exposureCompenHGI _exposureHGI _zoneReflectProbeTex"""),
    component("Enviro3.Runtime", "Enviro.EnviroTimeModule", "time-rule", "world-systems", {
        "Settings": fields(numbers("cycleLengthInMinutes dayLengthModifier nightLengthModifier simulate latitude longitude utcOffset"),
                           "daySerial hourSerial minSerial monthSerial secSerial timeOfDay yearSerial"),
    }, "LST active preset showLocationControls showModuleInspector showSaveLoad showTimeControls"),
)
