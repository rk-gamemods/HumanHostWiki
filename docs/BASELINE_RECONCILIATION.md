# Initial exception reconciliation

Initial delivery requires reconciliation of the entire known backlog. Successful
scripts and a published partial reader do not establish a working baseline.
The user explicitly authorized all 193 initial content groups and five article
issues on 2026-09-27. No selection or further authorization is needed for that work.

The initial source is Steam build 25548639, commit
`0bf00fe33781a7357b2d462fdaad49b0c3518b86`. Its run
`f1f4b7855b328dab494753d7e29efee30acd2d9ec1eca73cade4cc44e2124113`
reported 191 unsupported component classes and two relationship groups. All
27,011 unsupported component instances were inventoried locally for their captured
field names/types before extending the contracts. The inventory is diagnostic
material under `.local/baseline-exception-inventory.json`, not wiki content.

## Gameplay contracts reviewed

The paths below are relative to the pinned local codebase. Source code stays there.
Each assembly has an `<assembly>/<assembly>.decompiled.cs` file. Contracts select
serialized configuration; final runtime outcomes and code-dependent explanations
require their own checks.

| Assembly / classes | Evidence and decision | Owning adapter |
| --- | --- | --- |
| Equipment / Equipment_Info, EquipArmorPatch_Info | `EquipBoneType` and `EquipArmorPatch_Info.Start`: armor mounting category and available patch-part references; character transforms, current instances and render bindings omitted | `equipment.py` |
| Trap / Trap_Spike, Trap_Laser, Trap_RotBlade, Trap_SensorSpike | `Trap_Base.MyOnTriggerEnter` and concrete `On_Trigger_Enter`: configured damage, self-damage, trigger flags, timing and trap-specific parameters; effects and current state omitted | `traps.py` |
| Trap / Trap_Mgr | `_Start` maps `_TrapBInames` to `_TrapAlignInters` by index; retain placement names and spacing | `traps.py` |
| Sound_FX / Sound_Mat | Material HP, density, update flag, zone-piece HP and metal flag are gameplay configuration despite the assembly name; retain those fields | `construction.py` |
| Sound_FX / Sound_Object | `SoundMat` uses the material lookup name; retain both serialized material reference and lookup name, and link building configurations through `_soundObj` | `construction.py` |
| Sound_FX / WeaponHit_Set | `HitInfo.hitSoundSpreadDis` is labeled as NPC alert distance; retain it and hit-material identity, omitting audio/decal/particle payloads | `combat.py` |
| Bicycle / SBPScripts.SuspensionManager | `Start` assigns front/rear spring and damping values to joints; retain those values and enable flag | `vehicles.py` |
| Weather / Local_Wheather_Zone | `Awake` builds a runtime chance cache from `_ZoneSets`; retain the settings link, using the already selected WeatherZone_Settings values | `world.py` |

These are 12 of the initial component classes. Unrecognized fields and malformed
selected values still create exceptions while independent facts continue.

## Reviewed technical summaries

The following 16 exact classes use `technical.py`. Captured fields were compared
with their declarations and relevant source behavior. Their instances are read
through the field selector, but only type/count summaries are emitted. New fields
remain actionable; adding a class to this list does not suppress future discovery.

| Assembly / classes | Review evidence and reason |
| --- | --- |
| Assembly-CSharp / NM_Wind | `ApplySettings` writes global vegetation shader values |
| Assembly-CSharp / Reporter | Diagnostic log capture, FPS/memory display and overlay UI; telemetry and UserData excluded |
| Assembly-CSharp / ReporterMessageReceiver | Diagnostic overlay callbacks; no captured domain fields |
| Assembly-CSharp / SentryInitializer | Reporter binding for diagnostics; no telemetry exported |
| Bicycle / SBPScripts.BicycleSounds | `Start`/`Update` connect and update audio-source playback |
| File_Verification / File_Verification | Installation file checks and corruption dialog binding |
| Item_Info / ItemInfo_TerraBlock | Dropped block renderer material binding |
| My_Pool / My_Pool_Core | Runtime object pooling; no captured domain fields |
| Refs_KeepAlive / Refs_KeepAlive | `Start` keeps addressable asset handles alive |
| Trap / Trap_Sound_Set | Empty named audio routing marker |
| Sound_FX / Decal_Fader, Decal_Handler | Decal projector bindings and visual fade controls |
| Sound_FX / Gun_Aim_Reload_Sets, Gun_Fire_Sets | Audio clips and playback volumes |
| Sound_FX / ParticleDecalCollision, Particle_Handler | Decal placement/recycling and particle renderer/color bindings |

## Relationship and article corrections

The wheel and motor model references pointed to GameObjects with both building and
vehicle components. Treating all attached components as competing object identities
created two false ambiguities. The 74 `NoHeadPrefab` references are used as corpse
prefabs by `NPC_Spawner_Mgr`; expecting a living creature was also incorrect.

`prefabs.py` now selects individual GameObject identities reached by the explicit
domain relationships. Resolution prefers the exact identity over attached-component
aliases. This also prevents new material bindings from making vegetation links
ambiguous. Missing targets and unexpected types still remain exceptions.

The five article revisions used ordinary formatting: Combat Perks 432, Craft Perks
572 and Survival Perks 559 use `<u>`; Game Structure 539 uses `<code>`; Vehicle
Building 544 uses `<br />`. All five are populated under the corrected literal
content check. Only these attribute-free tags are accepted, with balanced nesting;
templates, unknown markup, attributes and malformed tags remain unsupported.
This establishes useful link destinations, not the accuracy of their gameplay claims.
Article bodies are discarded after checking.

## Acquisition, inventory and binding review

The next batch reconciles eight gameplay/configuration classes and 30 technical
classes. These decisions concern captured configuration. Code-defined mechanics
and complete gameplay explanations still require their own evidence.

| Assembly / classes | Evidence and decision | Owner |
| --- | --- | --- |
| Merchant / Merchant_Mgr | `BiomeItemSet`, `GetTypeItemRates`, `GetCurrentTypePriceFactor`, `ComputeRandomFactor`: select stock references, quantity ranges, weights, price factors and spawn/refresh parameters; split stock into one evidenced table per biome | `acquisition.py`, `entries.py` |
| Merchant / Merchant_Ins | `IsTerrainFlatEnough` compares the terrain normal angle with `MaxTerrainAngle`; retain the configured limit, omit render/physics bindings | `acquisition.py` |
| UI / Char_Item_Icons | `Init_Icons` uses `_InitItemsRef` for initial inventory and otherwise restores saved inventory; select only the initial item references, names and quantities | `acquisition.py` |
| UI / Item_Slot_Mgr | `Get_Upgrade_Pity_Fail_Count` and `Get_Quality_Factored_*` consume the quality and upgrade arrays; retain array positions and configured level limits. `_HandCraftBullet` is filled by `Tool_Interact_Mgr` at runtime, so its receiver copy is omitted | `inventory.py` |
| UI / UI_Control | `Select_Char` reads initial talent level/name and inventory; dropped-item cleanup reads `DeleteDropItemSeconds`. Retain those choices and belt-scroll setting; omit active UI, current selection and save state | `inventory.py` |
| Item_Info / Item_Info | Class fields distinguish `assetRef_Key`, recyclable `_IconRef`, and engine/tire components from mutable dropped-item and slot state; retain the former links and key | `equipment.py` |
| Player_HotKeys / Hotkey_Sets, Player_HotKeys | Default `KeyCode` values and action-to-setting references; omit live input, remapping widgets and saved overrides | `controls.py` |

The new technical decisions use exact classes and explicit omitted field names:

| Classes | Evidence and reason |
| --- | --- |
| MerchantWindowDisable, Merchant_LookAt | Merchant-window lifecycle and head look-at animation; no stock/pricing parameters |
| ESC_Hide_UI, On_GunAttachWindow_Hide, Loot_Window_Handler, Menu_Hover, Slot_Drag | UI lifecycle and pointer/drag callbacks; no captured gameplay parameters |
| InputFieldScaler, PickProp_IndiScaler, Text_UI_AutoResize | Font, layout and indicator scaling |
| Mat_Slot, Slot_Hover, Slot_Root_Of_Char | Widget and current-slot bindings; item values and initial inventories have separate selected contracts |
| Tag_Menu | `Start` derives sibling tab indices and `On_Click` changes menu selection; these are UI tabs, not item taxonomy |
| Version_Show, Version_Tag | Label visibility and display of `Application.version`; source metadata supplies the actual game version |
| DynamicToolTipSet | Localized tooltip-title bindings; nested unknown fields remain exceptions |
| Notifications / NoticeSlot, NotificationSystem | Notice display, color/fade settings and asset-handle cleanup; notice bodies omitted, nested unknown settings remain exceptions |
| Mgr_Hub / Mgr_Hub | `Awake` wires manager instances and starts their services; domain settings live on those managers |
| Player_HotKeys / Hotkey_Listener, Hotkey_Setter, HotKey_Text_Helper | Runtime remapping and label replacement; defaults are selected by `controls.py` |
| SteamManager / Mod_Mgr, MyMod_Info, WorkshopMgr, Workshop_UI | Mod browser, Steam service and upload widgets; no user mod descriptions, file IDs or upload state exported |
| Weather / Enviro_Editor_Bug_Fix, Skybox_Settings | Editor manager binding and skybox/cloud rendering fields; nested skybox field additions remain exceptions |
| Visual / Reflection_Probe_Mgr | `My_Update` blends reflection-probe multipliers; no weather selection parameters |

The independent source checker previously assumed every `loot-table` came from
`Loot_Rate_Sets`. Merchant stock exposed that assumption. It now compares component
tables at their evidenced source-field path while retaining the older view check.

## Remaining work

The latest source reconciliation in this checkpoint has 125 unsupported component
groups, covering 16,890 occurrences, and no relationship exceptions. All 125 groups
remain authorized initial-delivery work. They are not deferred for user selection.
Complete their evidence review and code corrections, then verify the full normal
update, unchanged repeat, public reader and remaining ADR acceptance gates.

## Future classifier experiment

A lightweight local classifier could suggest presentation-only versus gameplay
configuration for review. The reviewed classes above provide positive and negative
examples: Gun_Fire_Sets contains playback settings, while Sound_Mat contains HP and
density and WeaponHit_Set contains NPC alert distances. Class or assembly names alone
are insufficient. A future test should measure missed gameplay fields, abstention
rate, reviewer time saved and local compute cost against these reviewed labels.
Suggestions must not automatically exclude fields. No classifier is implemented.
