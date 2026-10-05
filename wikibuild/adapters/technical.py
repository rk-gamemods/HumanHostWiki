"""Selected operating defaults and reviewed technical fields, with drift detection.

Each exact class still goes through Selection: newly captured fields are logged.
Reviewed presentation classes emit only a type/count summary; operating defaults
have explicit selections. No private telemetry, visual settings or empty
per-instance records are exported. These decisions concern serialized
fields; they do not claim to explain every method in the class.
"""

from .schema import NUMBER as N, V3, EnglishText, Ref, component, fields


def reviewed(assembly, name, omitted, reason, inspected=None):
    return component(assembly, name, "component", "technical-reference", inspected or {}, omitted,
                     notes=reason, summary_only=True)


SPECS = (
    component("Language", "Language_Text", "configuration", "technical-reference", {
        "_Infos": EnglishText("text"),
    }, notes="English game text selected by LanguageType.English; other languages are omitted."),
    component("Language", "Tooltip_Text", "configuration", "technical-reference", {
        "_Infos": EnglishText("_ItemName", ("_ItemInstruction",),
                              frozenset({"_ItemType", "_ItemProperty"})),
    }, notes="English item name and optional instruction text. Item type/property display strings and other languages are omitted."),
    component("Optimize", "MeshCombineStudio.MeshCombiner", "configuration", "technical-reference", {
        "addMeshColliders": int, "addMeshCollidersInRange": int,
        "addMeshCollidersBounds": {"m_Center": V3, "m_Extent": V3},
        "physicsMaterial": Ref("collision-material"),
    }, """_Top_Build _isZoneHouseChildMCS _origLodSize _sysHouseBIlodGroup activeOriginal
addMeshCollidersList backFaceBounds backFaceDirection backFaceRotation backFaceT backFaceTriangleMode
cellCount cellOffset cellSize combineConditionSettings combineInRuntime combineMode combineOnStart
combineSwapKey combined combinedActive combined_MRs computeDepthToArray copyBakedLighting
deleteFilesFromSaveFolder disableOverlappingNonCombineGO drawGizmos drawMeshBounds
excludeBackfaceRemovalTag excludeOverlapRemovalTag excludeSingleMeshes foundColliders
foundCombineConditions foundLodGroups foundLodObjects foundObjects instantiatePrefab
instantiatePrefabValid isCombining jobSettings jobSettingsFoldout lodGroupLayer lodGroupsSettings
lodParentHolders makeMeshesUnreadable maxSurfaceHeight meshSaveSettingsFoldout mrDisabledCount
newDrawCalls newTotalColorChannels newTotalNormalChannels newTotalTangentChannels newTotalTriangles
newTotalUv2Channels newTotalUv3Channels newTotalUv4Channels newTotalUvChannels newTotalVertices
noColliders oldPosition oldScale orginalObjectsHideFlags originalDrawCalls originalLODGroups
originalMeshRenderers originalTotalColorChannels originalTotalNormalChannels originalTotalTangentChannels
originalTotalTriangles originalTotalUv2Channels originalTotalUv3Channels originalTotalUv4Channels
originalTotalUvChannels originalTotalVertices outputSettingsFoldout overlapLayerMask overlappingCollidersGO
overlappingNonCombineGO rebakeLighting rebakeLightingMode removeBackFaceTriangles removeOriginalMeshReference
removeOverlappingTriangles removeSamePositionTriangles removeTrianglesBelowSurface
reportFoundObjectsNotOnOverlapLayerMask runtimeSettingsFoldout saveMeshesFolder scaleInLightmap
searchOptions surfaceLayerMask totalMeshCombineJobs unitySettingsFoldout useCombineSwapKey
useCustomInstantiatePrefab useExcludeBackfaceRemovalTag useExcludeOverlapRemovalTag useOriginalObjectsHideFlags
useVertexOutputLimit usedRemoveOriginalMeshRederences validCopyBakedLighting validRebakeLighting
vertexOutputLimit voxelizeLayer weldIncludeNormals weldSnapSize weldSnapVertices weldVertices""",
       notes="Optional generated-mesh collision settings. AddMeshColliders applies the material; the range flag restricts creation to the bounds. Mesh payloads, save paths, rendering/triangle optimization, statistics and live state are omitted. These settings alone do not establish collision geometry."),
    reviewed("Creature", "Char_GPUI_Render", "GPUI_AnimData GPUI_proto _DeadPoseSet _GPUI_Crowd_Prefab _NoHead_BodyPrefab _capColTrigger _swichToGPUI_Time npcInput startTimePoint",
             "Animated/GPU character representation bindings and transition state. Character, spawn, corpse HP and animation timing defaults have dedicated contracts."),
    reviewed("Creature", "Char_GPUI_Render_Mgr", "",
             "Runtime GPU prototype-to-animation-instance registry; no captured settings."),
    reviewed("Creature", "GPUI_Dead_Pose_Set", "_DeadPosesCols_Down _DeadPosesCols_Side _DeadPosesCols_Up _DeadPoses_FaceDown _DeadPoses_FaceSide _DeadPoses_FaceUp",
             "Corpse pose clips and matching collider geometry; corpse HP/expiry are defined separately."),
    reviewed("Creature", "Ladder_Func", "_SoundObj",
             "Ladder contact service with a material/audio binding; movement locking and release are code-defined."),
    reviewed("Creature", "MLSpace.BodyColliderScript", "Collider ParentObject _dismembered _goreBone _lastHitFrame index m_ParentRagdollManager",
             "Ragdoll part indices, collider/bone bindings and live dismemberment state; no independent damage parameters."),
    reviewed("Creature", "PlayerBodyCollider", "Collider ParentObject _dismembered _goreBone _lastHitFrame index m_ParentRagdollManager",
             "Player ragdoll collider bindings and mutable state. Collision fall damage is calculated by OnCollisionEnter rather than these serialized fields."),
    reviewed("Creature", "RootMotion_Handler", "_controller _ragDollMgr",
             "Controller/ragdoll service bindings; OnAnimatorMove derives movement from animation, posture and controller state."),
    reviewed("Hand_Tools", "Bullet_Impact", "_BulletRender _BulletRigid _BulletSphereCol _belongCharBase _belongToolInter _bulletDetectDis _gunRange _initVelocity _origPos _shootRangeSeconds",
             "Pooled bullet bindings and shot-derived runtime values. Weapon_Range initializes detection distance and flight values; weapon defaults have a separate contract."),
    reviewed("G_Save", "G_Config_Setter", """On_SelectChar _CorpseDespawnTime_S _DayLength_S
_DeathDrop_SF _Difficulty_SF _Game24H_S _Horde_Interval_S _Horde_Z_Num_S _IndoorZ_Num_S
_LootInterval_S _LootSpawn_S _MaxCorpseCount_S _OutdoorZ_Num_S _WorldSeed_IF _XP_S
_Z_Anger_SF _Z_DmgBlock_S _Z_DmgCreature_S _Z_Frenzy_SF _Z_Mutant_S _Z_Respawn_S _Z_RunType_SF""",
             "World-configuration UI bindings; difficulty preset values are code-defined in Click_Difficulty_Preset, not values stored in these widget references."),
    reviewed("G_Save", "G_Save_Editor_Setter", "OnSaveSetterValidate",
             "Editor configuration holder; the captured source does not read _ConfigEditor. Its values are not asserted to be active new-game defaults.",
             {"_ConfigEditor": fields({}, "_CorpseDespawnTime _DayLengthFactor _DeadBagDropType _DifficultyIndex _ExpFactor _Game24H_Minutes _Horde_IntervalF _Horde_Z_NumF _InitTalentEngName _InitTalentLv _Loot_Rate_Total _MaxCorpseCount _OutdoorZ_NumF _PlayerCharIndex _Refresh_Loot_Days _SysHouseZ_NumF _TerraWorldSeed _Z_Anger _Z_DmgBlockF _Z_DmgCreatureF _Z_Frenzy _Z_MoveType _Z_Mutant_F _Z_RespawnGameHour")}),
    reviewed("Global_Funcs", "Global_Update", "",
             "Per-frame, fixed-step and interval callback dispatcher; no captured settings."),
    reviewed("Build_System", "Build_Event_Center", """Before_BI_Spawn On_BI_Created
On_BI_Disabled On_BI_FromPool On_BI_MR_Hide On_BI_MR_Show On_Before_Repair_Deploy
On_CarBI_HP_Minus On_CarCore_Smashed On_CarHit_BaI On_CarHit_Creature On_CarHit_Scene
On_Car_Active On_Car_BuildMode On_Car_Spawned On_Delete_Build On_Empty_Hands
On_FinishSavingAllChunkBuildings On_Finish_World_Back On_FinishedFallenCheck
On_GetOff_MainSeat On_GetOn_MainSeat On_Groups_Fallen On_Hand_Item On_Loaded_Car
On_Platform_Down On_RightClick_Build On_RightClick_Build_DetectAround On_Scene_PropBI_Spawned
On_Shards_Smashed On_SysGrass_FadeIn On_SysGrass_StartFadeOut On_TerraResource_BI_Loaded
On_TerraTop_Destroyed On_Tree_Need_Fall""", "Construction event bus; serialized listener bindings are not domain definitions."),
    reviewed("Build_System", "Car_Icon_Handler", "_RoboFileName _TitleLanguageText",
             "Saved vehicle map-icon lifecycle and localized title binding; save filenames are excluded."),
    reviewed("Build_System", "CheckFallen", "InSpreadingConnect Parts_Groups Shards_CoreNow _smashPoints needRunAgainRoboTopFallenCheck topInfo",
             "Runtime support/connectivity traversal; fall-distance defaults are read from Smash_Fallen_Manager."),
    reviewed("Build_System", "GrassSpawnManager", "loaded_GrassSpawners",
             "Registry of loaded grass services and dispatch of deleted-grass saves."),
    reviewed("Build_System", "GrassSpawner", "_inRegistGrass _inUnregistGrass _terraTop _terrain",
             "Terrain bindings and live registration flags; loads and applies saved grass removals."),
    reviewed("Build_System", "TerrainTreeSpawner", "belongTerrain belongTerrainCol originTreeIndexs",
             "Terrain bindings and mutable tree-index cache rebuilt from TerrainData; no independent species distribution settings."),
    reviewed("Build_System", "Init", """AimDot_Icon Delete_Icon EZ_Outline EventCenter
SmashFallenManager _ImpostorShaderName _OnTerraDestroy _OnTerraStart _OnWorldPullBackForBI
_cachedGridMover _npcSpawnInAsync build_System carCore_floatText chunkMgr scenePropManager
systemHouseManager terrainLoaderInLoading terrainTreeManager world_Origin_Neutralized""",
             "Construction service wiring, UI bindings and live world-origin/loading state."),
    reviewed("Build_System", "RotorOnHit", "",
             "Collision callback forwarding to the vehicle TopOnHit component; no serialized damage defaults."),
    reviewed("Build_System", "SaveLoad_Chunk", """IsDirty NeedDelSaveFileRoboNames
NeedSaveBuilding Save_LastProgressTime Save_ProgressCount _InterObjsChunkFile _inSaving
_isDisabled _sysHouseSpawners _terrain _treeSpawner disToTerraBoundsSqt thisChunkIsLoaded
thisChunkSysHouseLoaded""", "Chunk save/load bindings and mutable progress/dirty state; filenames and saved world contents are excluded."),
    reviewed("Terrain", "Terrain_NPC_Script", "_terraTop saveLoadChunk terrain",
             "Terrain population-service bindings; respawn timing is read from world configuration and saved population state."),
    reviewed("Equipment", "Equipment_Mgr", "On_ChainArmor_Smash _armorChainSmashEndColor _armorChainSmashStartColor",
             "Armor visual-effect colors and callbacks. Durability and effect duration enter as method arguments from gameplay components."),
    reviewed("Hand_Tools", "Bullets_Topinfo_Updator", "Bullets_Topinfo",
             "Mutable projectile vehicle registry; the update removes destroyed instances and has no serialized ballistic definition."),
    reviewed("Hand_Tools", "Special_Bow_Aim_LoPos", "",
             "Character-specific bow pose offsets; projectile flight and damage are configured separately.",
             {"_specialAimLoPos": [fields({}, "CharName BowAimLoPos3rd BowPosture BowAimX BowAimX_C BowAimY")]}),
    reviewed("Build_System", "SysHouse_BIs_Info", "",
             "Shared house-piece placement geometry and wall markers. House asset keys and activation parameters are selected from SystemHouseSpawner.",
             {"BIsInfo": [fields({}, "isWall localPos localRot localScale")]}),
    reviewed("Build_System", "ChunkSaveLoad_Manager", """InLoadingChunks InLoadingRoboTopsCount
InLoading_Some_Chunks InSavineChunks LastSaveDeadlineAbortTime MaxProcessTime_PerFrame
OnDisiable_Chunk OnTerraInRange OnTerraSysHouseFarAway On_GetOrigDoorRot On_RestoreInterObj
On_TerraTop_Destroy _TempCarCompassPOI _allChunksList _allChunksWithDisabled _callBackDoorOrigRot
_forceSaveRobo _inAutoOpenCloseDoors _inSavingData chunkPrefab""",
             "Chunk persistence scheduling, per-frame work budget, service bindings and live save queues; no world content definitions."),
    component("SaveData", "SaveDataManager", "configuration", "technical-reference", {
        "_AutoSaveInterval": N, "_AutoSaveIntervalEditor": N,
    }, "FinishedSaveDiggerVoxel On_Save_BeforeQuit _note lastSaveTimePoint save_playerData save_weatherData",
       notes="Autosave interval defaults in seconds; _Start selects the editor interval only when Application.isEditor. Save contents, live progress and timestamps are omitted."),
    component("GameSettings", "GameSettings", "configuration", "technical-reference", {
        "Language": int, "_PlayerHurtEach": int, "_DamageCreatureF": N, "_DamageBlockF": N,
    }, """AO_AutoAjust FPS_text OnGI_Changed OnLodBiasChanged OnResChanged RAM_text VRAM_text _CommitText
_AdaptiveGI _BigResTooltip _CreateWorldLanHelper _DLSS _DLSS_enabled _GI_On _HDcam
_H_Trace _H_TraceAO _IsWorldScene _LoadingImageTop _MaxBudgetMbRate _MinBudgetMB
_NatureRenderCamSet _OnGameSetChanged _OnLanguageChanged _StreamingMipBudget
_TexStrm_MaxLevelReduct _TotalTexRate _WhiteCursor _currTerraLod _grassGPUIPrefebMgr
_rainDropActive _resFactor globalVolume incrementalGCseconds lastPlayerPos
maxDisUpdateStaticShadow maxShadowDistanceSqt updateShadowCamAngle updateShadowLightAngle useStaticShadow""",
       notes="Serialized language and player-friendly-fire defaults. The two damage-factor fields have no uses in the captured source and are not asserted to change damage. Rendering, performance diagnostic UI bindings (including _CommitText) and live player state are omitted."),
    reviewed("GameSettings", "Slot_Hover", "_BackgroundIMG _TextLanguage _TooltipText",
             "Settings tooltip and hover-highlight widget bindings."),
    reviewed("SaveData", "Save_Player_Data", "_BedIconTitle _DeadBagIconTitle _GameSettings _PlayerMgr",
             "Save/load service references and map-label bindings. Player save contents remain local and are not wiki facts."),
    reviewed("SaveData", "Save_Weather_Data", "_WeatherController",
             "Weather save/load service binding; saved clock, weather, wetness and transition state are excluded."),
    reviewed("Car", "CarCodingPanel_Control", "",
             "Vehicle coding-panel buttons forward actions to the active vehicle; no serialized definitions."),
    reviewed("Car", "Car_BuildMode_Switch", "carControl topInfo",
             "Vehicle build-mode service bindings; no independent serialized mode limits."),
    reviewed("Car", "Car_Coding", "_carControl _top_Info",
             "Vehicle scripting service bindings; player-authored programs and runtime evaluation are not catalog facts."),
    reviewed("Car", "Car_Funs", "topInfo",
             "Vehicle command service binding; behavior is implemented in source rather than serialized settings."),
    reviewed("Car", "Code_Translator", "CtrlZ_Mode InSavingCode Origin_Text RichText TopInfo_SavedCode _inputField scrollBar top_Info",
             "Vehicle code editor widgets, undo/save flags and player-authored source; no program text is exported."),
    reviewed("Car", "Car_Mgr", "_Brakes _Engine_Acce_Loop _Engine_Off _Engine_On _Tire_On_Ground _TrainBrakes _TrainCouple _TrainIcon _Train_On_Tracks",
             "Captured fields bind vehicle audio/icons. Solar generation scheduling is code-defined in Begin_Generate_Power, not represented by these fields."),
    reviewed("Car", "Train_Bootstrap", "",
             "Runtime train component setup; Start adds the rail driver, rail layer and build-mode handler. Their code-defined defaults are not serialized on this marker."),
    reviewed("Car", "Main_Seat_Info", "_HeadIK_TargetLoPos",
             "Character seat-pose lookup and animation targets; no seat capacity or control limits.",
             {"_Ik_Target_Info": [fields({}, "CharName _CharLoPos _Hip_ikTarget_LoPos _Hip_ikTarget_LoEuler _Chest_ikTarget_LoPos _Chest_ikTarget_LoEuler _Hand_L_ikTarget_LoPos _Hand_L_ikTarget_LoEuler _Hand_R_ikTarget_LoPos _Hand_R_ikTarget_LoEuler _FootL_ikTarget_LoPos _FootL_ikTarget_LoEuler _FootR_ikTarget_LoPos _FootR_ikTarget_LoEuler")]}),
    reviewed("Build_System", "Battle_Info", """Belong_Group Contacts_SiblingIndex FatherBI
FatherBISysHouseIndex Is_Fallen MaxSize ShardsConnected Smashed _BI_Particle_Color
_RFG _fracturedRoot _rigidBody _soundMatName isDoorAxisBaI lastOnHitTime localPos
nameIndex selfMeshCollider selfMeshRender selfMeshfilter""",
             "Destructible-fragment geometry, parent bindings and mutable contact/damage state. MinusHP updates the parent Build_Info; building/material defaults are selected there."),
    reviewed("Build_System", "Shards_Group", """BI BanJingGroup Connected_1 Connected_2
Core_Now Core_Origin Dictionary_Key Ground_Origin IsSmashGroup Shards SpreadGeneration
_lastFurniPreFallFrame notTriggerOnDestroy""",
             "Runtime fragment connectivity, collapse traversal and saved-group ownership; no independent material or building definition."),
    reviewed("UI", "Craft_Slot", "_IconImage _IconNameText _TagMenu",
             "Crafting menu widget bindings; recipes and quantities are selected from Craft_Items."),
    reviewed("UI", "Craft_Window_Handler", "_belongCraftItem",
             "Craft window lifecycle callback; workbench configuration is selected from Craft_Items."),
    reviewed("Use_F", "Interact_SFX", "",
             "Named interaction-audio routing marker; no serialized parameters beyond Unity identity."),
    reviewed("Use_F", "Use_F", """CarRepositionArrowPrefab EZ_Outline _AirDropIcon
_AirDropIconChecked _ButtonCrateLabel_OK _CursorPos _InputFieldCrateLabel
_InputFieldCrateLabel_Obj _LootBar _LootBarText _LootDeadBodySFX _Pick_Menu
_SavePlayerDataIns _Tag_Menu carCore_floatText""",
             "Interaction service UI, audio and save-service bindings; code-defined interaction mechanics are not inferred from these bindings.",
             {"_InteractSounds": [fields({}, "interactSFX sounds")]}),
    reviewed("Hand_Tools", "Gun_Light_Curves", "GraphIntensityMultiplier GraphTimeMultiplier LightCurve _LightSource",
             "Muzzle-flash light intensity curve and duration; no shot damage or alert radius."),
    reviewed("Hand_Tools", "Drop_Sound_Sets", "",
             "Material-to-drop-audio mapping and playback volumes; no impact damage or alert parameters.",
             {"_DropSounds": [fields({}, "name soundMat audioClips volumes")]}),
    reviewed("Hand_Tools", "Equip_Sound_Sets", "_Equip_Sounds _Equip_Volumes _UnEquip_Sounds _UnEquip_Volumes",
             "Equip and unequip audio clips and playback volumes; audio payloads omitted."),
    reviewed("Hand_Tools", "Melee_Swing_Sound_Set", "_MeleeStartAudios _Melee_SA_Volumes",
             "Swing audio clips and playback volumes; combat timings are selected from Melee_Anim_Sets."),
    reviewed("Hand_Tools", "BulletShell_Drop_Sounds", "_shellDropSoundsName",
             "Spent-shell material/audio lookup; Play_Drop_Sound forwards clip, volume and position only."),
    reviewed("Creature", "Char_VoiceFX", "",
             "Character voice clips and playback volumes; no perception or attack parameters.",
             {"_Char_VoiceFX": fields({}, """Attack_Voices Attack_Volumes Hurt_Voices Hurt_Volumes
Death_Voices Death_Volumes Idle_Voices Idle_Volumes Breath_Voices Breath_Volumes
Jump_Voices Jump_Volumes HitGround_Voices HitGround_Volumes BoneBreak_Voices BoneBreak_Volumes""")}),
    reviewed("Creature", "Skill_Slot", "_DelSkillObj _FrameObj _SkillClass _SkillIconImage _SkillInstruction _SkillLevelText _SkillName _SkillStackText _skillLevel",
             "Skill widget bindings and current slot level; skill definitions and level values are selected separately."),
    reviewed("Creature", "Skill_Slot_Hover", "_HighlightObj _skillSlot",
             "Skill tooltip/highlight bindings; displayed values are read from Skill_Mgr."),
    reviewed("Creature", "Tab_Event", "_SelectFrame isMgr",
             "Skill-menu tab visibility callback; no skill definitions or costs.",
             {"_HideMgr": fields({}, "_tabsFrames _tabForHide")}),
    reviewed("Creature", "IK_Component", """_EyeTrans _IK_LookAtTrans _allowLeftHandIK
_allowRightHandIK _animator _charController _currRealAllowHandIK_L _leftHandIK_Trans
_leftHandIK_Weight _leftHandTarget_w _leftHand_TargetLoPos _leftHand_TargetLoRot
_lerpHandL_Speed _lerpHandR_Speed _origLerpHandR_S _rightHandIK_Trans
_rightHandIK_Weight _rightHandTarget_w""",
             "Animation hand-target bindings, interpolation and live IK state; no attack or perception limits."),
    reviewed("Build_System", "FacingCam", "",
             "Update rotates a display toward the camera; no captured configuration."),
    reviewed("Build_System", "MassCenter_Handler", "_FacingCams _MRs",
             "Mass-center indicator renderer bindings; physical mass is configured on building/material components."),
    reviewed("Optimize", "GPUI_NoneGameObject_Mgr", "_BufferSize _prefabManager",
             "GPU instance-buffer capacity and renderer manager; no world population parameters."),
    reviewed("Optimize", "Imposter_Manager", """QuadHeightFactor QuadMinMaxHeight QuadResFactor
Quad_MR_Prefab RT_Prefab _Cam _ColorMapKey _Speed_Distortion updateCamAngle
updateCamAngleActive updateCheckInterval updateDirectLightAngle volume""",
             "Impostor textures, camera update thresholds and rendering quality; no gameplay configuration."),
    reviewed("Optimize", "MCS_Manager", "_OnZoneSmashShards _cellSizeZoneSmash _delayCombineSecondsZS cellSize delayCombineSeconds meshCombinerBuilding",
             "Mesh-combination batching dimensions, delays and service bindings; no destruction damage settings."),
    reviewed("Optimize", "MeshCombineStudio.CachedComponents", "garbageCollectMesh go mf mr t",
             "Cached object, transform and mesh-renderer bindings; no domain values."),
    reviewed("Optimize", "MeshCombineStudio.GarbageCollectMesh", "mesh",
             "Mesh resource cleanup on destruction; mesh payload omitted."),
    reviewed("Optimize", "MeshCombineStudio.MeshCombinerData", "combined_MRs foundColliders foundLodGroups foundLodObjects foundObjects",
             "Mesh-combination result/cache collections; no world definitions."),
    reviewed("Optimize", "Quad_Lod_Active", "_startFrame",
             "Impostor visibility callback and runtime frame counter; no domain parameters."),
    reviewed("Optimize", "Point_Light_Handler", """_AudioSource _FastLight _HD_Light _HD_Light2
_InitFastLightIntens _InitLightLoPos _InitPointLightIntens _IsCampfire _NeedShadowFlicking
_PointLight _PointLight2 _SelfCol _ShadowFlickAmount _SphereCol _forceUpdateShadow
_lastUpdateShadow1 _spotLight1_LoPosY_NearWall _spotLight2_LoPosY_NearWall""",
             "Light/shadow placement, flicker and audio bindings; campfire flag chooses audio, not fuel consumption."),
    reviewed("Optimize", "Point_Lights_Mgr", "_FakeGI_Range _FakeGI_RangeMax _Fake_GI _SphereDetectRadius _SwitchLerpSpeed _TorchBagSmashSFX _TorchSFX _bagLightOn _closestVisiblePLight _lightsForJob",
             "Visible-light selection, fake illumination and torch audio; no fuel or heat parameters."),
    reviewed("Visual", "AO_AutoAdjustment", """_AdaptiveGI _ExposureCurveMin _Htrace _HtraceAO
_InForestGI_TimeF _RainMats _Snow_Mat _currHour _currTimeRate _inForest_IntensFactor_GI
_origSnowColor _outdoor_IntensFactor_GI _weatherCon forest_HAO_Intens
indoorNight_ILC_Intens indoor_HAO_Intens indoor_ILC_intens inforest_ILC_intens
lerpSpeedAO_Indoor lerpSpeedAO_Outdoor outdoorNight_ILC_intens outdoor_HAO_Intens
outdoor_ILC_intens rateHitBuild rateHitNature rayBI_Dis rayCastInterval volume""",
             "Environmental rendering adaptation: occlusion, illumination, exposure and weather-material appearance."),
    reviewed("Notifications", "NoticeSlot", "backGround iconBGImg iconImg text",
             "Notification display widget and asset-handle cleanup; no gameplay parameters."),
    reviewed("Notifications", "NotificationSystem", "slotInstances slotPrefab",
             "Notification text, color and fade settings; no notice bodies are exported.",
             {"settings": fields({}, "text color fadeTime")}),
    reviewed("Mgr_Hub", "Mgr_Hub", """_AI_Agen_Mgr _AO_AutoAdjustment _BulletsUpdator
_CamController _CarMgr _Char_GPUI_RenderMgr _CodeTranslator _CraftMgr _Creature_Mgr
_EquipmentMgr _GPUI_Dead_Body_Mgr _GPUI_NGO_Mgr _G_ConfigSetter _GameSettings _GlobalInfos
_GrassSpawnMgr _ImposterMgr _InitMgr _Item_Slot_Mgr _Language_Mgr _LootMgr _MCS_Mgr
_Merchant_Mgr _My_Pool_Core _NPCHordeMgr _NPCSpawnMgr _NotificationSystem _PlayerMgr
_PlayerRespawner _Player_HotKeys _PointLightsMgr _SFE_Mgr _SaveDataMgr _SavePlayerDataMgr
_ScenePropMgr _SkillMgr _Smash_Fallen_Mgr _SoundMgr _TerraDigMgr _TerraLoaderMgr
_TerraTreeMgr _ToolMgr _TrapMgr _UI_Control _UseF _WeatherController _WorldMapMgr""",
             "Startup service wiring; domain values belong to the referenced manager configurations."),
    reviewed("Player_HotKeys", "Hotkey_Listener", "",
             "Runtime key-remapping listener; serialized defaults selected separately."),
    reviewed("Player_HotKeys", "Hotkey_Setter", "_ButtonText _HotkeySet",
             "Key-remapping button binding; default key values and action bindings selected separately."),
    reviewed("Player_HotKeys", "HotKey_Text_Helper", "_HotkeySetter _IndexOrLastIndex _Text",
             "Localized hotkey label replacement; no action or key defaults serialized here."),
    reviewed("SteamManager", "Mod_Mgr", "Categories ShowDemoOnSteamFail SteamTimeout WorkshopUI _AudioSource",
             "Mod-browser categories, connection fallback and UI settings; no world or item configuration."),
    reviewed("SteamManager", "MyMod_Info", "_FileId _ModDescription _ModTitle _TooltipText _UploadButton _UploadImage _WorkshopMgr",
             "Workshop editor widgets; no uploads, file IDs, titles or descriptions are exported."),
    reviewed("SteamManager", "WorkshopMgr", "",
             "Steam Workshop query/subscription/publication service; no captured domain fields."),
    reviewed("SteamManager", "Workshop_UI", "_GreenColor _ItemPrefabMyMods _ItemPrefabNewMod _RedColor _TooltipText _UI_ConObj _UploadWindow _WorkshopMgr _YellowColor",
             "Workshop browser and upload dialog presentation; no gameplay parameters."),
    reviewed("Weather", "Enviro_Editor_Bug_Fix", "_enviroMgr",
             "Editor helper with a weather-manager binding; no captured domain values."),
    reviewed("Weather", "Skybox_Settings", "",
             "Skybox textures and volumetric-cloud rendering settings; visual payloads omitted.",
             {"_Skyboxes": [fields({}, "_Skybox _OpacityR _RaymarchDensity _RaymarchAmbient")]}),
    reviewed("Visual", "Reflection_Probe_Mgr", "_LerpSpeed _NightOutdoorProbeFactor _ProbeOutdoorPrefab",
             "Reflection-probe blending and rendering bindings; no weather selection or gameplay values."),
    reviewed("Merchant", "MerchantWindowDisable", "_MerchantMgr",
             "Merchant window lifecycle callback; no captured domain parameters."),
    reviewed("Merchant", "Merchant_LookAt", "_lookAt reverseLook",
             "Merchant head look-at animation binding and direction; no stock or price settings."),
    reviewed("UI", "ESC_Hide_UI", "On_ESC_Hide_UI",
             "Escape-key window lifecycle callback; no captured domain parameters."),
    reviewed("UI", "On_GunAttachWindow_Hide", "On_ESC_Hide_UI",
             "Attachment-window close callback; item parameters live in item configurations."),
    reviewed("UI", "InputFieldScaler", "fixedWidth fontSize keepInitWidthSize",
             "Text-input layout and font settings; presentation fields omitted."),
    reviewed("UI", "Loot_Window_Handler", "",
             "Loot-window close callback; no captured domain fields."),
    reviewed("UI", "Mat_Slot", "_IconImage _IconText _iconInfoPrefab",
             "Material-slot display and runtime item binding; recipe quantities are selected separately."),
    reviewed("UI", "Menu_Hover", "",
             "Pointer-hover event routing; no captured domain fields."),
    reviewed("UI", "PickProp_IndiScaler", "",
             "Pickup-indicator scaling callback; no captured domain fields."),
    reviewed("UI", "Slot_Drag", "",
             "Inventory drag interaction; no captured domain parameters."),
    reviewed("UI", "Slot_Hover", "_HighlightObj _slot_Info",
             "Slot highlight and tooltip display bindings; item configuration selected separately."),
    reviewed("UI", "Slot_Root_Of_Char", "_belongChar _slots",
             "Runtime character/slot ownership bindings; initial inventories selected separately."),
    reviewed("UI", "Tag_Menu", "On_Tag_Deselect On_Tag_Select _activeTarget _currSelectTag _isOn _selectFrame _tagIndex _tagMenus",
             "Menu tab selection and display bindings; no item taxonomy or gameplay parameters."),
    reviewed("UI", "Text_UI_AutoResize", "_Margin _MinWidth _RectTransform _Text _othersRects",
             "Localized-text layout settings and bindings; presentation fields omitted."),
    reviewed("UI", "Version_Show", "_VersionTag",
             "Version-label visibility binding; application version is captured from game metadata."),
    reviewed("UI", "Version_Tag", "_BG_Img _InitHide _VersionText",
             "Application-version label presentation; no independent version value is serialized."),
    reviewed("Assembly-CSharp", "NM_Wind",
             "FlexNoiseWorldSize GustMaskTexture GustScale GustSpeed GustWorldSize NoiseTexture ShiverNoiseWorldSize Turbulence WindSpeed point1 point2 point3 point4",
             "Vegetation shader wind configuration; visual settings omitted."),
    reviewed("Assembly-CSharp", "Reporter",
             "Initialized UserData _DebugLabelColor debugMode fps fpsText images maxSize numOfCircleToShow show size",
             "Diagnostic log overlay; user data, telemetry and UI fields omitted."),
    reviewed("Assembly-CSharp", "ReporterMessageReceiver", "",
             "Diagnostic overlay callbacks; no captured domain fields."),
    reviewed("Assembly-CSharp", "SentryInitializer", "_reporter",
             "Diagnostic reporter binding; no telemetry or runtime log data exported."),
    reviewed("Bicycle", "SBPScripts.BicycleSounds",
             "bodyHitAudioSource freeWheelAudioSource pedallingAudioSource tyreHitFAudioSource tyreHitRAudioSource",
             "Bicycle audio-source bindings; audio payloads omitted."),
    reviewed("File_Verification", "File_Verification", "corruptionDialog",
             "Installation-integrity dialog binding; no domain configuration."),
    reviewed("Item_Info", "ItemInfo_TerraBlock", "_dropModelMat",
             "Dropped terrain block's visual material binding; material payload omitted."),
    reviewed("My_Pool", "My_Pool_Core", "",
             "Runtime object-pool service; no captured domain fields."),
    reviewed("Refs_KeepAlive", "Refs_KeepAlive", "_AssetRefs",
             "Addressable asset lifetime bindings; no gameplay property values."),
    reviewed("Trap", "Trap_Sound_Set", "",
             "Named trap audio routing marker; no captured fields beyond Unity identity."),
    reviewed("Sound_FX", "Decal_Fader", "_FadeOverTime _Projector _destroyDelay",
             "Decal display and fade settings; visual payloads omitted."),
    reviewed("Sound_FX", "Decal_Handler", "_decal_Projector",
             "Decal projector binding; visual payload omitted."),
    reviewed("Sound_FX", "Gun_Aim_Reload_Sets",
             "_AimSounds _AimVolumes _CockSounds _CockVolumes _DryFireSounds _DryFireVolumes _LoadSounds _LoadVolumes _SlideUnlockSounds _SlideUnlockVolumes _UnLoadSounds _UnLoadVolumes",
             "Gun handling audio clips and playback volumes; payloads omitted."),
    reviewed("Sound_FX", "Gun_Fire_Sets", "_FireSounds _FireVolumes",
             "Gunfire audio clips and playback volumes; payloads omitted."),
    reviewed("Sound_FX", "ParticleDecalCollision",
             "DecalPrefabs decalRecycleCount destroyDelay limitAngle maxAngle maxScale minAngle minScale randomRotation",
             "Particle collision decal placement and recycling; visual payloads omitted."),
    reviewed("Sound_FX", "Particle_Handler", "_hasBFX_BloodSettings _originColors _particleRenders _particles",
             "Particle renderer/color bindings; visual payloads omitted."),
)
