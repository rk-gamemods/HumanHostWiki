"""Reviewed presentation and infrastructure fields, with drift detection.

Each exact class still goes through Selection: newly captured fields are logged.
Only its type/count summary is emitted. No private telemetry, visual settings or
per-instance empty records are exported. These decisions concern serialized
fields; they do not claim to explain every method in the class.
"""

from .schema import component, fields


def reviewed(assembly, name, omitted, reason, inspected=None):
    return component(assembly, name, "component", "technical-reference", inspected or {}, omitted,
                     notes=reason, summary_only=True)


SPECS = (
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
    reviewed("UI", "DynamicToolTipSet", "",
             "Localized tooltip heading bindings; item and weapon values are selected separately.",
             {"data": fields({}, """_Dura_Title _BlockDura _Damage_Title _HitDown_Title
_BladeHit_Title _GunFireRate_Title _SingleShot_Title _GunMaxMag_Title _GunAmmoType_Title
_BowAmmoType_Str _Quality_Title _BladeHit_Instruct _HeadShot_Instruct _ArrowDamage
_ArrowRange _ArrowSpeed _ShootRange_Title _Recoil_Title _DummyRound_Title _Jam_Title
_GatheringTool _GatheringToolSmallAxe""")}),
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
