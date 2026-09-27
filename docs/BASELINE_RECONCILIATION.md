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

## Remaining work

The latest source reconciliation in this checkpoint has 163 unsupported component
groups, covering 22,143 occurrences, and no relationship exceptions. All 163 groups
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
