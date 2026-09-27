"""Player/NPC movement, interaction timing and physical character defaults."""

from .schema import NUMBER as N, V3, Ref, component, fields, numbers
from .animation import ANIMATION_TRANSITION as TRANSITION

CONTROLLER = {
    **numbers("mass _FallenDamageFactor _moveSpeed _rotSmoothTime crouchLowerDis _jumpSpeed _jumpSpeedSprint JumpDownForce JumpCoolDown delayJumpTime _airControlRate _JumpCostStamina slopeLimit slideGravity groundFriction airFriction gravity _footStepSoundMaxDis"),
    "_CharFaction": int, "char_Status": Ref("character-status"),
    "_charSkills": Ref("character-skills"), "_charMover": Ref("movement-collider"),
}
BASE_ANIMS = fields({name: TRANSITION for name in "Run Run_BareHand Sprint Crouch CrouchS Swim SwimS BoneBreak_Move".split()},
                    "Stand_Idle Stand_AimIdle Stand_AimIdle_Bow Crouch_Idle Swim_Idle")
STRAFE_ANIMS = fields({name: TRANSITION for name in """Run_F_1stMelee Run_L_1stMelee Run_R_1stMelee
Run_B_1stMelee Run_FL_1stMelee Run_FR_1stMelee Run_BL_1stMelee Run_BR_1stMelee Run_F_1stGun
Run_L_1stGun Run_R_1stGun Run_B_1stGun Run_FL_1stGun Run_FR_1stGun Run_BL_1stGun Run_BR_1stGun
Run_R_3rd_Pistol Run_F_3rdMelee Run_L_3rdMelee Run_R_3rdMelee Run_B_3rdMelee Run_FL_3rdMelee
Run_FR_3rdMelee Run_BL_3rdMelee Run_BR_3rdMelee Run_F_3rdRange Run_L_3rdRange Run_R_3rdRange
Run_B_3rdRange Run_FL_3rdRange Run_FR_3rdRange Run_BL_3rdRange Run_BR_3rdRange Bow_L_3rdRange
Crouch_L Crouch_R Crouch_B Crouch_FL Crouch_FR Crouch_BL Crouch_BR CrouchS_L CrouchS_R
CrouchS_B CrouchS_FL CrouchS_FR CrouchS_BL CrouchS_BR""".split()},
    "Jump_F Jump_L Jump_FL Jump_R Jump_FR Jump_B_l Jump_B_r Jump_F_s Jump_L_s Jump_FL_s Jump_R_s Jump_FR_s")
INTERACTION = fields(numbers("""StandLootSpeed StandLootFade CrouchLootSpeed CrouchLootFade
Stand_Pick_Speed_Low Stand_Pick_Fade_Low Stand_Pick_Speed_High Stand_Pick_Fade_High
Crouch_Pick_Speed Crouch_Pick_Fade RunPickSpeed RunPickFade RunPickSpeed_2 RunPickFade_2
RunPickSpeed_3 RunPickFade_3"""),
    "StandLootClip CrouchLootClip Stand_Pick_Clip_Low Stand_Pick_Clip_High Crouch_Pick_Clip RunPickClip RunPickClip_2 RunPickClip_3")

# Exact reviewed exclusions are shared only between these two source classes.
CONTROLLER_OMITTED = """OnPutBackItem OnTakeOutItem OnTakeOutNullItem Pressed_Crouch Pressed_FastMove Pressed_Jump
Pressed_MeleeAttack Pressed_Move _0FrictionMat _1stInAimingMode _3rd_Animancer _BodyPosture
_CapColPushDis _CharBreathAudioSource _CharGPUIRender _CharVoiceAudioSource _Char_VoiceFX_Set
_EquipBones _GripR_IK _Grip_L _Grip_L_HoldGun _Grip_R _Hair _HasBreathAudio _HasShield
_Head_For_Blink _IK _In1stZoomMode _InAimingMode _InAir _InFirstPerson _InMeleeAttacking
_InZoomAimMode _IsBareHand _Jump _Land _NPC_Enabled _NotAllowPlay _On3rdHoldShiled _OnFallGround
_OnStandUp _OnToolCreatedDestroy _On_AimingMode _On_Char_Died _On_Char_DiedToPool _On_Char_Update
_On_HandIK_StartEnd _On_Hand_Item _On_Ragdoll_FallGround _On_Ragdoll_GetUp _SpineToHeadDirect
_UpperBodyMask _UseIK _aimIK _allowOnSeatCharAction _antiHitReActRate _assetGUID _bareHandAimClip
_bowParentCons _canControl _capTrigger _charHighestY _crouchUpMask _currJumpClip _currJumpForce
_deadTimeP _fingersIK_L _fingersIK_R _finishedPush _focusEnemy _hasMeleeOrRangedWeapon _hasPistolGun
_hasWeaponSpace _horizontal _inGetHandItem_OutOrBack _inReloading _inSfeScene _isFallGround
_isPlayer _isUnderRoof _lastEquipHelmetFrame _lastFocusTimeForSilentHit _lastFootstepTime
_lastHeadShotTimeP _lastHitCreature _lastHitDamage _lastHitRagdoll _lastHitRagdollForArmor
_lastHitTimeP _lastIsUnderRoof _lastOnCarEulerY _leftFootAudioSource _leftGrip _leftGrip_HoldGun
_leftHandCol _limbIK_L _limbIK_L_Target _limbIK_R _limbIK_R_Target _lodGroup _lookAtIK _mask_8_10
_meleeAntiWall _moveSpeedFactor _newTakeOutItem_Prefab _oldCapHeight _onRoboSeatBI _onRoboSeatTop
_origCapColPushDis _originCapThick _pushBoxCol _pushCapCol _ragDollMgr _releasedFastMove
_ridingBicycle _rigBuilder _rigIKs _rigIKs_HoldGun _rightFootAudioSource _rightHandCol
_rootM_TargetSpeed _rootMotionHandler _snowTarget _soundMgr _soundModByAction _targetLookAtWeight
_vertical _wetTarget animator capCol currAnimClip_BaseLayer currAnimClip_UpLayer
currAnimSpeed_BaseLayer currAnimSpeed_UpLayer currCharState curr_Idle curr_Move_B curr_Move_BL
curr_Move_BR curr_Move_F curr_Move_FL curr_Move_FR curr_Move_L curr_Move_R faceViewForward
forceUpdateAnim_BaseLayer forceUpdateAnim_UpLayer heightLength2Time_P10 heightLengthPlus5
interFrame_AntiFall lastValidPos momentum moveDirect originMoveSpeed references rigidBody
viewForward2D viewForward_MoveDirect_Angle"""
PLAYER_OMITTED = """Exit1stZoom ExitZoom OnEnter1stPerson OnFinishEnter1stPerson OnFinishEnterZoom TryEnter1stZoom
TryEnterZoom _1stGunCamLoPos _AimDot _AimlineTrans _EquipRenders _FlashLight _GunTrans
_GunZoomAimLoPos_NoScope _GunZoomAimLoRot _HelmetRenders _In1stHoldShield _InBuildingMode
_JustBrokenGun _OnGround _On_1st_Hold_Shield _On_Force_Stop_Loot _On_PutBack_HandItem
_On_TakeOut_HandItem _Others _TVE_GrassPush _TraxMgr _crateInputOn _currGunCross _currScopeCross
_facingCar _fastZoom _fastZoomSecond _feetGroundLoaded _groundCol _gunMeshRenders
_hideShieldForInteractAnim _hideSkinMeshAtZoomAim _initWeatherZoneBgmV _isGamePaused
_isShownBuildToolTipUI _noJump _offLadder _onHitRecoverRate _origAimlineLoRot _origVigIntense
_origVigSmooth _redDotAimObj _releasedBuildRightClick _steeringController _suppressLeftHandIK
_suppressMoveAnim _suppressRigIKWeight _suppressRightHandIK _targetChromaticIntens _targetScopeFOV
_targetVignetteIntens _targetVignetteSmooth _vignette"""
ZOMBIE_OMITTED = """_IdleVoiceChance _MoveVoiceChance _hitWallTarget _inRunning _isRushAttack _mutantLevel
_npcSpawnSource _spawnInOutDoorPointsIndex use_GPUI_Crowd"""

SPECS = (
    component("Creature", "Player_Input", "ai-rule", "creatures-ai", {
        **CONTROLLER, "_ceilHeightMod": N, "_RightClickCamDis": N, "_faceViewForward": int,
        "_Base_Anim": BASE_ANIMS, "_Srafe_Move_Anim": STRAFE_ANIMS, "_Interact_Anim": INTERACTION,
    }, CONTROLLER_OMITTED + " " + PLAYER_OMITTED,
       notes="Player controller prefab defaults for movement, jumping, stamina and interaction timing. Runtime actions, equipment, skills and root-motion clips can change movement. Clip payloads, current input/state and player positions are omitted; timing markers retain Animancer defaults."),
    component("Creature", "Zombie_Input", "ai-rule", "creatures-ai", {
        **CONTROLLER, "_FoundTargetWalkSpeedF": N, "is_Boss": int, "is_BareFoot": int,
        "_NPC_Anims_Set": Ref("npc-animation-settings"), "_ZombieHpBarName": str,
    }, CONTROLLER_OMITTED + " " + ZOMBIE_OMITTED,
       notes="Zombie controller prefab defaults and animation-setting binding. The target-found walking factor applies while not running. Difficulty, time of day, mutations and runtime state may modify behavior; voice playback, current targets and live state are omitted."),
    component("Creature", "NPC_Anims_Settings", "ai-rule", "creatures-ai", {
        "_NPC_Anim": fields({name: [TRANSITION] for name in "Walks Runs Crouchs CrouchsF Swims SwimsF MoveAttacks".split()}, "Stand_Idles Crouch_Idles Swim_Idles"),
        "_zombieTrapAnims": [fields({"speed": N, "endRate": N}, "clip")],
    }, "references", notes="NPC movement/attack transitions and trap animation speed/end fraction. Normalized times and default markers do not establish real durations without the omitted clips."),
    component("Creature", "Player_Mgr", "ai-rule", "creatures-ai", {
        "_PlayerChars": [Ref("player-character-prefab")], "_InitPlayerPos": [V3], "_MaxBeBiteCount": int,
    }, "OnPlayerInitOnGround _BagForFlashLight _BuildTooltipUI _FlashLightOffSFX _FlashLightOnSFX _FoodRect _FoodText _ForceGetUpUI _GPUIprefabMgr _LadderTooltip_Down _LadderTooltip_Up _TireWindowOn _WaterRect _WaterText _flashLightIns",
       notes="Player character prefab choices, initial position candidates and bite-count limit. GetRandomInitPlayerPos chooses a candidate using the world seed. These are template positions, not a player's saved location."),
    component("Creature", "CMF.Mover", "ai-rule", "creatures-ai", {
        **numbers("colliderHeight colliderThickness stepHeightRatio"), "colliderOffset": V3,
        **dict.fromkeys("sensorType sensorArrayRows sensorArrayRayCount sensorArrayRowsAreOffset".split(), int),
    }, "isGrounded isInDebugMode raycastArrayPreviewPositions sensor",
       notes="Ground movement collider and sensor defaults. RecalculateColliderDimensions combines height, offset and step ratio; these raw fields are not final world-space capsule bounds."),
    component("Creature", "My_Ragdoll_Hum", "ai-rule", "creatures-ai", {
        **numbers("blendTime hitTimeInterval hitReactionTimeModifier velocityModifier"),
        "enableGetUpAnimation": int, "hitInterval": int,
    }, "RagdollBones SkinedRenders _ChestBoxCollider _DeadBodyLoot _GetUpFaceGround _GetUpFaceSky _LODGroup _LeftKneeIndex _RightKneeIndex _allBodyScripts _animancer _animator _controller _goreSimulator _headBodyScript _rootMotionHandler _standUpSeconds activeColLayerName blendRate inactiveColLayerName m_OrientTransform",
       notes="Ragdoll blend/reaction interval defaults and get-up option. Runtime hit handling can override the reaction modifier, and stand-up duration is derived from animation, so live state and clip/bone geometry are omitted."),
    component("Creature", "GPUI_Dead_Body_Mgr", "ai-rule", "creatures-ai", {
        "_deadBodyMaxHP": int, "_ShowBodyRange": N, "_HideBodyRange": N,
    }, "On_DeSpawnGPUI_DeadBody On_SpawnGPUI_DeadBody _BloodBleedSpeed _BloodGroundDecals _BloodSmashParticle _BloodSmashSFXs _BloodSmashSFXs_V _BodyHitBloodParticle _OnGetDeadBodyPrefab _On_BodyIns_Smashed _On_BodyRef_Loaded _On_DeadBody_Spawned _On_Fade_BloodDecal _On_PutBack_DeadBody _bloodDecalUnderFadeSeconds _deadBodyPrefab _gpuCrowdMgr _saveID _world_Origin_Neutralized",
       notes="Corpse maximum HP and display activation ranges. Corpse expiry is read from world configuration; saved corpses, world positions and blood effects are omitted."),
)
