"""Building defaults and item links; transforms/renderers/runtime damage omitted."""

from .schema import NUMBER as N, V2, V3, Ref, component, numbers

SPECS = (
    component("Build_System", "Build_System", "construction-rule", "construction", {
        "Crane_Time": int, "_EmptyRotorBaseMass": N, "_longTrackBI_Name": str, "_shortTrackBI_Name": str,
        "MechPlatformRef": Ref("mechanic-platform-prefab"), "_VehicleTopPrefab": Ref("vehicle-top-prefab"),
        "_DoorUpShortCubeBI": Ref("door-support-building"),
    }, """AllowRightClickBuild Build_TopInfo DamagedBIsRender EZ_Outline InRightClickDetectAround
In_DiggerFallenCheck ItemName OnRoboBISmashFallContactCrane On_RightClickDelete_CarCoreBI
PreviewBlue PreviewBlues PreviewIgnoresOverlap PreviewPrefabBI PreviewRed PreviewReds
PreviewTransform PreviewWhite PreviewWhites Robops SpriteBlue SpriteRed TireMaterial
_BeltPutBackSounds _BeltTakeOutSounds _BuildAlignText _BuildIndicatorPrefab _Green
_InBuildingMode _InShowCarUI _MassCenterPrefab _NoItemStr _OnDelBI _OnStackAboveTerrain
_OnStackUnderTerrain _PreviewArrowPrefab _PreviewResetAFX _PreviewResetTooltipPrefab _Red
_Tool_Interact_Mgr _facesNow _lastStartTime _successDepoly _trainRailPreviewRef
_trainRailPreviewTip _trainRailQ_ActiveTip _trainRailQ_DeActiveTip lastHitNormal lastHitPoint
lastPlayerPos mr_Preview mr_TireArrow overlap""",
       notes="Construction defaults and supporting prefab/track keys. Empty-rotor mass is used when the rotor building mass is zero. Preview state, player position and audiovisual bindings are omitted."),
    component("Build_System", "Smash_Fallen_Manager", "construction-rule", "construction", {
        **numbers("DeletePieceSeconds _FallenDisFurni _FallenDistance _PlaneAngleRange _ShardFallCreatureDamageMax _SliceSize _SliceSizeFall _TreeFallAttractZombieDis _TreeFallBaIDamage _TreeFallCreatureDamage"),
        "_TreeLog_IconRefs": [Ref("tree-log-item")], "_TreeLog_Prefabs": [Ref("tree-log-prefab")],
    }, """DelAfterThread_BigFallenTop InFallenCheckTops InSmashingTops _0bounceMat
_BigWallFallCamShakeIntens _BigWallFallParticle _BigWall_ConcreteDebris _BigWall_Metal_Fall_SFX
_BigWall_RockGlass_Fall_SFX _DefaultHitBloodVFX _Ground_Debris_Sets _HitParticleRecycle
_InnerMatSets _MCS_CombieShards _MeleeDecalRecycle _OnWeaponBloodDecal _OnZoneHouseBIspawn
_OnZoneSmash _PlanesParent _RangeDecalRecycle _ShatterTemplate_MC _ShatterTemplate_MF
_ShatterTemplate_MR _ShatterTemplate_RB _StartMCScombineBIchilds _TreeFallCamShakeDuration
_TreeFallCamShakeIntens _TreeHitGroundSFXs _TreeHitGroundVFX _attctZombies _hitNPC""",
       notes="Fracture/support settings, debris lifetime in seconds, falling-tree damage and alert distance, maximum falling-shard damage and log item/prefab bindings. Runtime fracture results and visual debris are omitted."),
    component("Build_System", "TopOnHit", "construction-rule", "construction", {
        "DamageFactor": N, "ImmuneMinDamage": N,
    }, """Col_topInfo_origin Col_top_Info HitSituation NeedCheckTops OnSmashing Smashed_BIs
This_topInfo_origin This_top_Info _IsFromPlayer _hitBaIWallInterval _lastHitBaITimeForPushWall
_lastRuntimeFractureTimeP _lastVeloWhenHitBaI _pressedWS lastOnHitFrame smashPoints""",
       notes="Collision-damage multiplier and immunity threshold defaults. Final damage also depends on collision speed, mass and hit context; live collision results and participants are omitted."),
    component("Terrain", "Terrain_Dig", "construction-rule", "construction", {
        "_fallenDis": int, "addPull": N, "digPush": N, "_BlockModelRef": Ref("terrain-block-prefab"),
    }, "On_Digger_TreeFall UI_Canvas _EnableDebug _FixTesseSeamPrefab _InLoadingData _TerraBlockDropMesh _cachedGridMover diggerBufferSize diggerMaster diggerMasterRuntime saveDataManagerObj testConnectCube testEmptyCube testSupportCube",
       notes="Terrain support-check distance, surface-normal offsets for adding/removing terrain, and dropped-block prefab binding. Voxel data, debug geometry, work buffers and save state are omitted."),
    component("Build_System", "SystemHouseManager", "construction-rule", "construction", {
        **numbers("_DespawnBI_Dis _DespawnFurniBI_Dis _SpawnBI_Dis _SpawnFurniBI_Dis _disCheckFurniInterval _disCheckInterval"),
    }, "All_SysBuildingTops InLoadingSystemHouse SysTopsDisCheck _MaxProcessTimePerFrame _despawnBI_Dis_Sqt _inSpawningFurni _spawnBI_Dis_Sqt repairedSysHouseBIs",
       notes="House and furniture activation distances and polling intervals in seconds. These control streaming rather than destroyed-building regeneration."),
    component("Build_System", "SystemHouseSpawner", "construction-rule", "construction", {
        **numbers("_AroundHouseDisInterval _IndoorDisInterval"), "BIsAssetKey": [str],
        "BIsInfo_Ref": Ref("house-layout"),
    }, """BIsInfo DamagedTimePoint RepairedTimePoint SysHouseBelongChunk SysHouseBelongTerrainTop
_aroundHouseDisInterSqt _furniBI_0_HP _furniBI_Refs _furniBI_Siblings _furniBIsInfo
_unload_Already boundBox damagedBIsSibling initDamagedBIsCount load_FullHP_BIs_Already
repairedBIsSibling sysHouseTopSibiling""",
       notes="House part asset keys, shared layout binding and sampling-distance parameters. Transform geometry, spawned furniture caches, damage and repaired save state are omitted."),
    component("Sound_FX", "SoundTerrain_Sets", "construction-rule", "construction", {
        "_TextureSoundMatsName": [str],
    }, "_TextureParticleColors",
       notes="Terrain-texture index to material lookup names, preserving texture order; particle colors are omitted."),
    component("Sound_FX", "Sound_Terrain", "construction-rule", "construction", {
        "_SoundTerra_Set": Ref("terrain-material-table"), "_terraDataTopRef": Ref("terrain-data"),
    }, "_TexSoundMatsRuntime _terrain _terrainCol",
       notes="Terrain material-table and terrain-data bindings. The live material array is rebuilt by Sound_Terrain.Start and is omitted."),
    component("Sound_FX", "Sound_Mgr", "construction-rule", "construction", {
        "_All_Sound_Mats": [Ref("material")], "_SFE_SoundMatName": str, "_Layer0SoundMatName": str,
    }, """_AudioSourcePrefab _BossFootAFXs _ChaseBGMs _ChaseBGMs_Volume _ClosePack_Audio
_CombatBGM_Source _Common_UI_Sounds _Decompose_Audio _Dismantle_Audio _EmoBGM_Source
_Footstep_Library _GunAttachClose_SFX _GunAttachOpen_SFX _JumpLand_Library _MusicVolume
_OpenPack_Audio _PlayerFrictionGroundSFXs _PlayerFrictionGroundVolume _PlayerGearMoveSFXs
_Repair_Audio _ShieldOnSFXs _Slot_Drag_Audios _Slot_Drop_Audios _SoundVolume
_emoBgmIntervalRange _inCombatBGM _inLerpBioEmoBGM _indoorRate _lastEmoBgmEndTime
_nextEmoBgmInterval""",
       notes="Shared material registry, underground material lookup key and layer-zero ground material lookup key. Empty keys remain empty. Audio playback libraries, music and runtime state are omitted."),
    component("Build_System", "Build_Info", "building-piece", "construction", {
        **numbers("CanBeRepair MaxSize NoRotate Shards_HP_All _AlignToSurface _Build_Mass _Ground_Debris_Type _IsFurniBI _ItemType _NoRuntimeSmash _Type _interactType _isBigProp _isDynamicBI _origBaI_HP _origHP_All"),
        "Size": V3, "ItemInfo": Ref("item-component"), "_soundObj": Ref("material-binding"),
        "_Collectable_Info": {"_CollectType": int, "_Items": [{"_CollectMinMaxCount": V2,
            "_IconRef": Ref("collectible-item"), "_RandomRate": N}]},
    }, """BaIsExistStatus BaIs_All BaIs_HP_Lefts BelongChunk CJ ContactBIs DamagedRender DelEmptyBI
Dictionary_Key FatherRotor_BI GPUI_MatrixIndex IsCoding LastBounds LastCycleDir Origin_LocalPos Origin_LocalRot
RotorMassCenter RotorRigi ShardsFallenCount ShardsSmashedCount Shards_HP_Left SpawnedAlready Spawned_BaIs
SysHouseBISibling SysHouseTop SysHouseTopSibling _ManualActiveSysHouseBI _ParticleColor _PreviewCoreShrink
_convexModel _isFromPool _isGPUIsysHouseGrass _lastHPLeft _lastHitBigWallTime _name _poolInsParent_Handler
_skinnedMR belongTerrain lodGroup scenePropIndex scenePropSpawner selfMeshCollider selfMeshRenderer
selfMeshfilter shards_Groups terraTreeSpawner top_Info treeHeightScale treeWidthScale"""),
    component("Sound_FX", "Sound_Mat", "construction-rule", "construction", {
        **numbers("_ThisMatHP _MatDensity _AllowUpdateBI_MassHP _HP_ZoneSmashBI _IsMetal"),
    }, "_SmashAudioClips _SmashAudioVolumes _SmashParticles _SmashP_Scales _BuildAudioClips _BuildAudioVolumes _BuildParticles _DigParticles",
       notes="Serialized material HP and density parameters, not final building durability or mass."),
    component("Sound_FX", "Sound_Object", "construction-rule", "construction", {
        "_SoundMat": Ref("material"), "_soundMatName": str,
    }, notes="Material binding: serialized material reference and lookup name."),
)
