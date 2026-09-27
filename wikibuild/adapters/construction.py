"""Building defaults and item links; transforms/renderers/runtime damage omitted."""

from .schema import NUMBER as N, V2, V3, Ref, component, numbers

SPECS = (
    component("Sound_FX", "SoundTerrain_Sets", "construction-rule", "construction", {
        "_TextureSoundMatsName": [str],
    }, "_TextureParticleColors",
       notes="Terrain-texture index to material lookup names, preserving texture order; particle colors are omitted."),
    component("Sound_FX", "Sound_Terrain", "construction-rule", "construction", {
        "_SoundTerra_Set": Ref("terrain-material-table"), "_terraDataTopRef": Ref("terrain-data"),
    }, "_TexSoundMatsRuntime _terrain _terrainCol",
       notes="Terrain material-table and terrain-data bindings. The live material array is rebuilt by Sound_Terrain.Start and is omitted."),
    component("Sound_FX", "Sound_Mgr", "construction-rule", "construction", {
        "_All_Sound_Mats": [Ref("material")], "_SFE_SoundMatName": str,
    }, """_AudioSourcePrefab _BossFootAFXs _ChaseBGMs _ChaseBGMs_Volume _ClosePack_Audio
_CombatBGM_Source _Common_UI_Sounds _Decompose_Audio _Dismantle_Audio _EmoBGM_Source
_Footstep_Library _GunAttachClose_SFX _GunAttachOpen_SFX _JumpLand_Library _MusicVolume
_OpenPack_Audio _PlayerFrictionGroundSFXs _PlayerFrictionGroundVolume _PlayerGearMoveSFXs
_Repair_Audio _ShieldOnSFXs _Slot_Drag_Audios _Slot_Drop_Audios _SoundVolume
_emoBgmIntervalRange _inCombatBGM _inLerpBioEmoBGM _indoorRate _lastEmoBgmEndTime
_nextEmoBgmInterval""",
       notes="Shared material registry and underground material lookup key. Audio playback libraries, music and runtime state are omitted."),
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
