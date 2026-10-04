Historical evidence from 2026-09-27, build 25548639. For current status, see [ACCEPTANCE.md](ACCEPTANCE.md).

# Original exception inventory: reconciliation

This ledger closes the original 193 content groups and five article issues for
`build-25548639-1080b929da89` (application 0.8.315). It compares the original
inventory with explicit class contracts and the already audited selected output.
Every row has a rule, scope decision and evidence. Exact selected/excluded field
names and reviewed reasons are in [the machine-readable ledger](baseline-inventory-reconciliation.json).

Evidence: `delivery-coded-source-audit.json` checked every selected value and
all 527 type summaries against the captured source; its 365,969 assertions passed.
`delivery-coded-history-audit.json` checked canonical edges and provenance
(449,827 assertions). Both are retained under `.local/`. The reconciliation also
checked exact per-class counts and every originally inventoried top-level field.
New types/fields still produce exceptions under `components.py` and `schema.py`.

| Original class group | Instances | Owning rule | Output | Selected / excluded fields |
| --- | ---: | --- | --- | ---: |
| `Assembly-CSharp/NM_Wind` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 17 |
| `Assembly-CSharp/Reporter` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 15 |
| `Assembly-CSharp/ReporterMessageReceiver` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Assembly-CSharp/SentryInitializer` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Bicycle/SBPScripts.BicycleController` | 2 | [vehicles.py](../wikibuild/adapters/vehicles.py) | vehicles/vehicle-rule | 24 / 41 |
| `Bicycle/SBPScripts.BicycleSounds` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 9 |
| `Bicycle/SBPScripts.LockBicycleController` | 1 | [vehicles.py](../wikibuild/adapters/vehicles.py) | vehicles/vehicle-rule | 5 / 69 |
| `Bicycle/SBPScripts.SuspensionManager` | 1 | [vehicles.py](../wikibuild/adapters/vehicles.py) | vehicles/vehicle-rule | 5 / 9 |
| `Bicycle_Glue/Bicycle_Glue` | 3 | [vehicles.py](../wikibuild/adapters/vehicles.py) | vehicles/vehicle-rule | 1 / 16 |
| `Build_System/Battle_Info` | 4045 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 24 |
| `Build_System/Build_Event_Center` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 39 |
| `Build_System/Build_System` | 2 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 7 / 56 |
| `Build_System/Car_Icon_Handler` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Build_System/CheckFallen` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 10 |
| `Build_System/ChunkSaveLoad_Manager` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 24 |
| `Build_System/FacingCam` | 7 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Build_System/GrassSpawnManager` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Build_System/GrassSpawner` | 320 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 8 |
| `Build_System/Init` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 23 |
| `Build_System/MassCenter_Handler` | 3 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Build_System/RotorOnHit` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Build_System/SaveLoad_Chunk` | 321 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 18 |
| `Build_System/ScenePropManager` | 2 | [biomes.py](../wikibuild/adapters/biomes.py) | biomes-resources/resource-distribution | 8 / 13 |
| `Build_System/ScenePropSpawner` | 640 | [biomes.py](../wikibuild/adapters/biomes.py) | biomes-resources/resource-distribution | 4 / 11 |
| `Build_System/Shards_Group` | 4101 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 17 |
| `Build_System/Smash_Fallen_Manager` | 2 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 12 / 35 |
| `Build_System/SysHouse_BIs_Info` | 217 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 4 |
| `Build_System/SystemHouseManager` | 2 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 6 / 12 |
| `Build_System/SystemHouseSpawner` | 3589 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 4 / 21 |
| `Build_System/TerrainTreeManager` | 2 | [biomes.py](../wikibuild/adapters/biomes.py) | biomes-resources/resource-distribution | 6 / 18 |
| `Build_System/TerrainTreeSpawner` | 320 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `Build_System/Terrain_Data_Top` | 80 | [biomes.py](../wikibuild/adapters/biomes.py) | biomes-resources/resource-distribution | 1 / 5 |
| `Build_System/TopOnHit` | 2 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 2 / 20 |
| `Camera/CamController` | 1 | [controls.py](../wikibuild/adapters/controls.py) | technical-reference/configuration | 23 / 68 |
| `Car/CarCodingPanel_Control` | 18 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Car/Car_BuildMode_Switch` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Car/Car_Coding` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Car/Car_Control` | 1 | [vehicles.py](../wikibuild/adapters/vehicles.py) | vehicles/vehicle-rule | 2 / 11 |
| `Car/Car_Funs` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Car/Car_Mgr` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 13 |
| `Car/Code_Translator` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 12 |
| `Car/Main_Seat_Info` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 5 |
| `Car/Solar_Generator` | 1 | [vehicles.py](../wikibuild/adapters/vehicles.py) | vehicles/vehicle-rule | 1 / 4 |
| `Car/Train_Bootstrap` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Car/Train_Rail` | 3 | [vehicles.py](../wikibuild/adapters/vehicles.py) | vehicles/vehicle-rule | 5 / 5 |
| `CompassPro/CompassNavigatorPro.BeaconAnimator` | 1 | [navigation.py](../wikibuild/adapters/navigation.py) | reviewed technical summary | 0 / 7 |
| `CompassPro/CompassNavigatorPro.CompassBarMeshModifier` | 1 | [navigation.py](../wikibuild/adapters/navigation.py) | reviewed technical summary | 0 / 4 |
| `CompassPro/CompassNavigatorPro.CompassButtonHandler` | 2 | [navigation.py](../wikibuild/adapters/navigation.py) | reviewed technical summary | 0 / 4 |
| `CompassPro/CompassNavigatorPro.CompassPro` | 2 | [navigation.py](../wikibuild/adapters/navigation.py) | world-systems/world-rule | 15 / 120 |
| `CompassPro/CompassNavigatorPro.CompassProFogVolume` | 2 | [navigation.py](../wikibuild/adapters/navigation.py) | world-systems/world-rule | 3 / 4 |
| `CompassPro/CompassNavigatorPro.CompassProPOI` | 100 | [navigation.py](../wikibuild/adapters/navigation.py) | world-systems/world-rule | 9 / 31 |
| `CompassPro/CompassNavigatorPro.MiniMapInteraction` | 1 | [navigation.py](../wikibuild/adapters/navigation.py) | reviewed technical summary | 0 / 4 |
| `Creature/CMF.Mover` | 77 | [characters.py](../wikibuild/adapters/characters.py) | creatures-ai/ai-rule | 8 / 8 |
| `Creature/Char_GPUI_Render` | 148 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 13 |
| `Creature/Char_GPUI_Render_Mgr` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Creature/Char_VoiceFX` | 22 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 4 |
| `Creature/GPUI_Dead_Body_Mgr` | 2 | [characters.py](../wikibuild/adapters/characters.py) | creatures-ai/ai-rule | 3 / 23 |
| `Creature/GPUI_Dead_Pose_Set` | 10 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 10 |
| `Creature/IK_Component` | 3 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 22 |
| `Creature/Ladder_Func` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Creature/MLSpace.BodyColliderScript` | 1110 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 11 |
| `Creature/My_Ragdoll_Hum` | 77 | [characters.py](../wikibuild/adapters/characters.py) | creatures-ai/ai-rule | 6 / 25 |
| `Creature/NPC_Anims_Settings` | 12 | [characters.py](../wikibuild/adapters/characters.py) | creatures-ai/ai-rule | 2 / 5 |
| `Creature/PlayerBodyCollider` | 45 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 11 |
| `Creature/Player_Input` | 3 | [characters.py](../wikibuild/adapters/characters.py) | creatures-ai/ai-rule | 28 / 221 |
| `Creature/Player_Mgr` | 2 | [characters.py](../wikibuild/adapters/characters.py) | creatures-ai/ai-rule | 3 / 19 |
| `Creature/RootMotion_Handler` | 77 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Creature/Skill_Slot` | 5 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 13 |
| `Creature/Skill_Slot_Hover` | 5 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Creature/Tab_Event` | 12 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 6 |
| `Creature/Zombie_Input` | 74 | [characters.py](../wikibuild/adapters/characters.py) | creatures-ai/ai-rule | 27 / 171 |
| `Enviro3.Runtime/Enviro.EnviroConfiguration` | 1 | [environment.py](../wikibuild/adapters/environment.py) | world-systems/world-rule | 2 / 16 |
| `Enviro3.Runtime/Enviro.EnviroLightingModule` | 2 | [environment.py](../wikibuild/adapters/environment.py) | reviewed technical summary | 1 / 15 |
| `Enviro3.Runtime/Enviro.EnviroManager` | 2 | [environment.py](../wikibuild/adapters/environment.py) | world-systems/world-rule | 4 / 42 |
| `Enviro3.Runtime/Enviro.EnviroQuality` | 1 | [environment.py](../wikibuild/adapters/environment.py) | reviewed technical summary | 4 / 10 |
| `Enviro3.Runtime/Enviro.EnviroQualityModule` | 2 | [environment.py](../wikibuild/adapters/environment.py) | reviewed technical summary | 1 / 9 |
| `Enviro3.Runtime/Enviro.EnviroSkyModule` | 2 | [environment.py](../wikibuild/adapters/environment.py) | reviewed technical summary | 1 / 14 |
| `Enviro3.Runtime/Enviro.EnviroWeatherModule` | 2 | [environment.py](../wikibuild/adapters/environment.py) | world-systems/world-rule | 1 / 11 |
| `Enviro3.Runtime/Enviro.EnviroWeatherType` | 12 | [environment.py](../wikibuild/adapters/environment.py) | world-systems/world-rule | 9 / 16 |
| `Equipment/EquipArmorPatch_Info` | 12 | [equipment.py](../wikibuild/adapters/equipment.py) | items-equipment/equipment | 1 / 5 |
| `Equipment/Equipment_Info` | 87 | [equipment.py](../wikibuild/adapters/equipment.py) | items-equipment/equipment | 1 / 14 |
| `Equipment/Equipment_Mgr` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `File_Verification/File_Verification` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `G_Save/G_Config_Setter` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 26 |
| `G_Save/G_Save_Editor_Setter` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 5 |
| `GameSettings/GameSettings` | 3 | [technical.py](../wikibuild/adapters/technical.py) | technical-reference/configuration | 4 / 43 |
| `GameSettings/Slot_Hover` | 49 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `Global_Funcs/Global_Infos` | 3 | [world.py](../wikibuild/adapters/world.py) | world-systems/world-rule | 1 / 90 |
| `Global_Funcs/Global_Update` | 3 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Hand_Tools/Arrow_Impact` | 3 | [combat.py](../wikibuild/adapters/combat.py) | combat/combat-rule | 4 / 16 |
| `Hand_Tools/BulletShell_Drop_Sounds` | 5 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Hand_Tools/Bullet_Impact` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 14 |
| `Hand_Tools/Bullets_Topinfo_Updator` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Hand_Tools/Drop_Sound_Sets` | 4 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 4 |
| `Hand_Tools/Equip_Sound_Sets` | 11 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 8 |
| `Hand_Tools/Gun_Light_Curves` | 5 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 8 |
| `Hand_Tools/Melee_Anim_Sets` | 119 | [combat.py](../wikibuild/adapters/combat.py) | combat/combat-rule | 15 / 11 |
| `Hand_Tools/Melee_Swing_Sound_Set` | 6 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Hand_Tools/Scope_Info_Sets` | 7 | [combat.py](../wikibuild/adapters/combat.py) | items-equipment/equipment | 2 / 7 |
| `Hand_Tools/Special_Bow_Aim_LoPos` | 3 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 4 |
| `Hand_Tools/Tool_Interact_Mgr` | 2 | [combat.py](../wikibuild/adapters/combat.py) | combat/combat-rule | 11 / 51 |
| `Item_Info/ItemInfo_TerraBlock` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Item_Info/Item_Info` | 4340 | [equipment.py](../wikibuild/adapters/equipment.py) | technical-reference/configuration | 4 / 6 |
| `Merchant/MerchantWindowDisable` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Merchant/Merchant_Ins` | 4 | [acquisition.py](../wikibuild/adapters/acquisition.py) | spawning-populations/spawn-rule | 1 / 9 |
| `Merchant/Merchant_LookAt` | 3 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Merchant/Merchant_Mgr` | 1 | [acquisition.py](../wikibuild/adapters/acquisition.py) | loot-acquisition/loot-source | 9 / 23 |
| `Mgr_Hub/Mgr_Hub` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 51 |
| `My_Pool/My_Pool_Core` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Notifications/NoticeSlot` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 8 |
| `Notifications/NotificationSystem` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 6 |
| `Optimize/GPUI_NoneGameObject_Mgr` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Optimize/Imposter_Manager` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 17 |
| `Optimize/MCS_Manager` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 10 |
| `Optimize/MeshCombineStudio.CachedComponents` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 9 |
| `Optimize/MeshCombineStudio.GarbageCollectMesh` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Optimize/MeshCombineStudio.MeshCombiner` | 1 | [technical.py](../wikibuild/adapters/technical.py) | technical-reference/configuration | 4 / 112 |
| `Optimize/MeshCombineStudio.MeshCombinerData` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 9 |
| `Optimize/Point_Light_Handler` | 4 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 22 |
| `Optimize/Point_Lights_Mgr` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 14 |
| `Optimize/Quad_Lod_Active` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Player/Player_Respawner` | 2 | [survival.py](../wikibuild/adapters/survival.py) | skills-survival/survival-rule | 2 / 25 |
| `Player/World_Map_Mgr` | 2 | [world.py](../wikibuild/adapters/world.py) | world-systems/world-rule | 4 / 23 |
| `Player_HotKeys/HotKey_Text_Helper` | 14 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `Player_HotKeys/Hotkey_Listener` | 3 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Player_HotKeys/Hotkey_Sets` | 38 | [controls.py](../wikibuild/adapters/controls.py) | technical-reference/configuration | 1 / 4 |
| `Player_HotKeys/Hotkey_Setter` | 38 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Player_HotKeys/Player_HotKeys` | 3 | [controls.py](../wikibuild/adapters/controls.py) | technical-reference/configuration | 47 / 12 |
| `Refs_KeepAlive/Refs_KeepAlive` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `SaveData/SaveDataManager` | 2 | [technical.py](../wikibuild/adapters/technical.py) | technical-reference/configuration | 2 / 10 |
| `SaveData/Save_Player_Data` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 8 |
| `SaveData/Save_Weather_Data` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Sound_FX/Decal_Fader` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `Sound_FX/Decal_Handler` | 31 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Sound_FX/Gun_Aim_Reload_Sets` | 8 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 16 |
| `Sound_FX/Gun_Fire_Sets` | 8 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `Sound_FX/ParticleDecalCollision` | 28 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 13 |
| `Sound_FX/Particle_Handler` | 162 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 8 |
| `Sound_FX/SoundTerrain_Sets` | 11 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 1 / 5 |
| `Sound_FX/Sound_Mat` | 193 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 5 / 12 |
| `Sound_FX/Sound_Mgr` | 2 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 2 / 34 |
| `Sound_FX/Sound_Object` | 4189 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 2 / 4 |
| `Sound_FX/Sound_Terrain` | 320 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 2 / 7 |
| `Sound_FX/WeaponHit_Set` | 24 | [combat.py](../wikibuild/adapters/combat.py) | combat/combat-rule | 1 / 4 |
| `SteamManager/Mod_Mgr` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 9 |
| `SteamManager/MyMod_Info` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 11 |
| `SteamManager/WorkshopMgr` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `SteamManager/Workshop_UI` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 13 |
| `Terrain/SFE_Exit_Trigger` | 1 | [world.py](../wikibuild/adapters/world.py) | world-systems/world-rule | 1 / 4 |
| `Terrain/SFE_Mgr` | 2 | [world.py](../wikibuild/adapters/world.py) | world-systems/world-rule | 10 / 13 |
| `Terrain/SFE_Player_Enter_Handler` | 1 | [world.py](../wikibuild/adapters/world.py) | world-systems/world-rule | 3 / 4 |
| `Terrain/Terrain_Dig` | 2 | [construction.py](../wikibuild/adapters/construction.py) | construction/construction-rule | 4 / 18 |
| `Terrain/Terrain_Loader_Manager` | 2 | [world.py](../wikibuild/adapters/world.py) | world-systems/world-rule | 10 / 13 |
| `Terrain/Terrain_NPC_Script` | 320 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `Trap/Trap_Laser` | 1 | [traps.py](../wikibuild/adapters/traps.py) | combat/combat-rule | 9 / 16 |
| `Trap/Trap_Mgr` | 2 | [traps.py](../wikibuild/adapters/traps.py) | construction/construction-rule | 2 / 9 |
| `Trap/Trap_RotBlade` | 2 | [traps.py](../wikibuild/adapters/traps.py) | combat/combat-rule | 10 / 11 |
| `Trap/Trap_SensorSpike` | 1 | [traps.py](../wikibuild/adapters/traps.py) | combat/combat-rule | 10 / 11 |
| `Trap/Trap_Sound_Set` | 13 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Trap/Trap_Spike` | 11 | [traps.py](../wikibuild/adapters/traps.py) | combat/combat-rule | 7 / 8 |
| `UI/Char_Item_Icons` | 19 | [acquisition.py](../wikibuild/adapters/acquisition.py) | loot-acquisition/loot-source | 1 / 5 |
| `UI/Craft_Mgr` | 2 | [crafting.py](../wikibuild/adapters/crafting.py) | crafting-processing/processing-rule | 1 / 17 |
| `UI/Craft_Slot` | 11 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `UI/Craft_Window_Handler` | 11 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `UI/DynamicToolTipSet` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 4 |
| `UI/ESC_Hide_UI` | 46 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `UI/InputFieldScaler` | 4 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `UI/Item_Slot_Mgr` | 3 | [inventory.py](../wikibuild/adapters/inventory.py) | items-equipment/equipment | 9 / 53 |
| `UI/Loot_Window_Handler` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `UI/Mat_Slot` | 11 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `UI/Menu_Hover` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `UI/On_GunAttachWindow_Hide` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `UI/PickProp_IndiScaler` | 87 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `UI/Slot_Drag` | 223 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `UI/Slot_Hover` | 315 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `UI/Slot_Info` | 276 | [inventory.py](../wikibuild/adapters/inventory.py) | items-equipment/equipment | 5 / 24 |
| `UI/Slot_Root_Of_Char` | 4 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 6 |
| `UI/Tag_Menu` | 52 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 12 |
| `UI/Text_UI_AutoResize` | 16 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 9 |
| `UI/UI_Control` | 3 | [inventory.py](../wikibuild/adapters/inventory.py) | world-systems/world-rule | 3 / 119 |
| `UI/Version_Show` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `UI/Version_Tag` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `Use_F/G_Mode` | 2 | [acquisition.py](../wikibuild/adapters/acquisition.py) | technical-reference/configuration | 1 / 9 |
| `Use_F/Interact_SFX` | 139 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 4 |
| `Use_F/Use_F` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 19 |
| `Visual/AO_AutoAdjustment` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 32 |
| `Visual/Reflection_Probe_Mgr` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 7 |
| `Weather/Enviro_Editor_Bug_Fix` | 2 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 0 / 5 |
| `Weather/Local_Wheather_Zone` | 80 | [world.py](../wikibuild/adapters/world.py) | world-systems/world-rule | 1 / 5 |
| `Weather/Skybox_Settings` | 1 | [technical.py](../wikibuild/adapters/technical.py) | reviewed technical summary | 1 / 4 |
| `Weather/Weather_Controller` | 2 | [world.py](../wikibuild/adapters/world.py) | world-systems/world-rule | 8 / 55 |

## Relationships and articles

| Original case | Rule and verification | Result |
| --- | --- | --- |
| `model`: 2 ambiguous wheel/motor links | `adapters/prefabs.py` emits exact GameObject identities; identity resolution prefers those over component aliases. `tests/test_prefabs.py` and complete source/history audits verify targets. | Resolved |
| `headless-prefab`: 74 links | `adapters/spawning.py` treats corpse prefabs as assets; `prefabs.py` retains those identities. All 74 links retained; complete source/history audits verify canonical targets. | Resolved |
| Human Host:Content/Game Content/Perks/Combat Perks (revision 432) | `mediawiki.py` accepts balanced attribute-free `u`, `code`, and `br` formatting; focused regression plus pinned revision receipt. | Populated |
| Human Host:Content/Game Content/Perks/Craft Perks (revision 572) | `mediawiki.py` accepts balanced attribute-free `u`, `code`, and `br` formatting; focused regression plus pinned revision receipt. | Populated |
| Human Host:Content/Game Content/Perks/Survival Perks (revision 559) | `mediawiki.py` accepts balanced attribute-free `u`, `code`, and `br` formatting; focused regression plus pinned revision receipt. | Populated |
| Human Host:Guides/Modding/Game Structure (revision 539) | `mediawiki.py` accepts balanced attribute-free `u`, `code`, and `br` formatting; focused regression plus pinned revision receipt. | Populated |
| Human Host:Guides/Vehicle Building (revision 544) | `mediawiki.py` accepts balanced attribute-free `u`, `code`, and `br` formatting; focused regression plus pinned revision receipt. | Populated |

## Scope and omissions

72 original classes produce selected domain/configuration records. 119 have
reviewed technical summaries, with explicit field exclusions for UI, rendering,
audio, bindings or transient runtime state. They retain names, counts and scope
notes. They are not silently discarded or passed through a catch-all rule.
All 414,343 source objects remain accounted for. The catalog separately records
45,518 omitted payload objects and three editor-only decoding gaps. Those gaps
remain visible; unavailable editor assemblies are not invented or decoded.
Article checks establish useful link destinations, not gameplay accuracy.
