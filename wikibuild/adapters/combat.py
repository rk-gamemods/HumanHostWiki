"""Body/material damage factors and serialized melee/ranged weapon settings."""

from .schema import NUMBER as N, V3, Ref, component, fields, numbers
from .animation import ANIMATION_TRANSITION

COMMON = {
    **numbers("_Damage _DamageType _BladeHitProb _HitDownProb _HitFlyForce _DismemberBody _BlowHead _DuraCostPerAttack _DigGetDirtBlock _RepairDis _RepairNoiseDis _RepairValue _repairType _PushBodyDis _HitReactAmplitude"),
    "_matsDamageSetName": str, "_weaponHitSetName": str, "_damageFactorSet": Ref("body-damage-set"),
}
OMITTED = """_1stCamMod _AI_Agent _AimingModeIdleAnim _CharBase _GPUI_Crowd_Prefab _G_Info
_IsToolNoBounce _WeaponPosDatas _arrowDamage _creatureMgr _damage _equipSoundSetName _inBouncingHit
_lastHitIsScene _playerInput _reShotDis _soundMgr _thisToolSlot _toolMgr _tracerBulletForward
_weaponRenders layer_Creature layer_Ragdoll mask_2_8_9_10_14 mask_HitFinal mask_HitNoBI"""

SPECS = (
    component("Hand_Tools", "Arrow_Impact", "combat-rule", "combat", {
        **numbers("_ArrowDamage _ArrowSpeed _flyGravityScale"), "_weaponHitSetName": str,
    }, "_BowBoxCol _BowRigid _BowSphereCol _arrowIconGUID _belongCharBase _belongToolInter _bowDetectDis _flyTrail _hitCharCol _origForce _trailWidth _weaponHitSet",
       notes="Arrow prefab damage multiplier, base speed, gravity scale and material-hit preset key. Bow draw and range modifiers change the runtime values; these are not final shot damage or speed. Shooter state and trail rendering are omitted."),
    component("Hand_Tools", "Melee_Anim_Sets", "combat-rule", "combat", {
        **numbers("_AnimSpeed _NPC_AttkEndRate _SwingReDirect_AnimLengthRate _SwingReDirect_3rd_Rate _LengthRate_ForFixInterval _BounceEndSeconds _BounceEndSeconds_Aim _3rdAimLerpIdle_Rate _KeepCheckSeconds _KeepCheckSeconds_1stNoAim"),
        **dict.fromkeys("_HasShieldAnim _IsNpcHitDownAnim _HasFootAnimation".split(), int),
        **{name: ANIMATION_TRANSITION for name in ("_AnimTrans", "_AnimTransForShield")},
    }, "_1stAxis_Crouch _1stAxis_Stand _1stNoAimAxis_Crouch _1stNoAimAxis_Stand _3rdAxis_Crouch _3rdAxis_Stand references",
       notes="Serialized attack timing and normalized animation-event positions. Keep-check and bounce fields are seconds; event positions and rate fields are relative. The encoded float: nan marker preserves Animancer's default timing sentinel. Clip duration and runtime conditions are not evaluated, so these are not computed attack rates."),
    component("Hand_Tools", "Scope_Info_Sets", "equipment", "items-equipment", {
        "scopeType": int, "camFovRate": N,
    }, "chromaticIntense vignetteIntens vignetteSmooth",
       notes="Serialized scope type and camera field-of-view multiplier. Weapon_Range multiplies the original camera FOV by camFovRate; it also uses the value for scoped mouse sensitivity. Visual overlays are omitted."),
    component("Hand_Tools", "Tool_Interact_Mgr", "combat-rule", "combat", {
        "_HandCraftBullet": [{"BulletMat": str, **numbers("Damage_F Dummy_Rate Range_F Recoil_F Stuck_Rate")}],
        "_AllMetalSoundMats": [Ref("material")], "_AllRockSoundMats": [Ref("material")],
        "_MatsDamageSets": [Ref("material-damage-set")], "_WeaponHitSets": [Ref("weapon-hit-set")],
        "_ScopeSets": [Ref("scope-setting")], "_1stDefaultAnim": Ref("melee-animation"),
        "_PlantFiberIconRef": Ref("gathered-item"), "_HitDeadBodySoundMat": Ref("material"),
        "_CarHitSceneHitSet": Ref("weapon-hit-set"), "_SmashGrassSet": Ref("weapon-hit-set"),
    }, """OnDeadBodyDestroy _AmmoUI_MachineGun _AmmoUI_Pistol _AmmoUI_Rifle _AmmoUI_ShotGun
_ArmorReflectStabSFXs _ArrowTrailMat _Bite_FalldownSFXs _BowCirBar _BowCircle _BowIns_Top
_BrokenSoundVolume _BulletImpact _ComboDamageText _Cross4 _CrossHair _DropSoundSets
_Dud_SFXs _EquipSoundSets _ExecuteIcon _ExecuteIconSFX _Finger_Trigger_LoPos
_Finger_Trigger_LoRot _GunAimReloadSets _GunFireSets _HeadshotIcon _HeadshotIconSFX
_IdleForBow _InvisibleBlockSFX _ItemBrokenSound _ItemSmashedSound _Jam_Icon _Jam_SFXs
_MeleeSwingSound_Sets _RepairHammerSFX _RepairShowText _ScopeCross_X12 _ScopeCross_X2
_ScopeCross_X4 _ScopeCross_X6 _ScopeCross_X8 _ShotGunCircle _SmashSoundVolume
_crossOrigLoPos _gunFireParticleInfos _rayPointGPUIChars _weaponDamaged""",
       notes="Serialized handmade ammunition modifiers, material classifications and combat preset bindings. Runtime hit results, UI and audiovisual payloads are omitted."),
    component("Sound_FX", "WeaponHit_Set", "combat-rule", "combat", {
        "HitSettings": [fields({"hitSoundMat": Ref("material"), "hitSoundMatName": str,
                                "hitSoundSpreadDis": N},
            "hitAudioClips hitAudioVolumes hitParticles hitP_Scales hitDecals decal_Scales")],
    }, notes="Serialized impact alert distance by hit material; audio and visual payloads are omitted."),
    component("Hand_Tools", "BodyPartsDamage_Sets", "damage-type", "combat", {
        "_BodyPartsDamageFactor": numbers("armLeg chest head"),
    }, "触发自动编译"),
    component("Hand_Tools", "Mat_Damage_Sets", "damage-type", "combat", {
        "_Mats_Damage": [{"damage": N, "soundMat": Ref("material")}],
    }),
    component("Hand_Tools", "Weapon_Melee", "combat-rule", "combat", {
        **COMMON, **numbers("_StaminaCost _GrassRemoveRadius _StuckTime _BounceSpeed"), "_ComboDmgFactors": [N],
        "_1stNoAim_Melee_Anims": [Ref("melee-animation")], "_AimMode_Melee_Anim": Ref("melee-animation"),
        "_PossibleAnims": [Ref("melee-animation")], "_BoxCenter": V3, "_BoxSize": V3, "_BladeDirect": int,
    }, OMITTED + """ _BladeTipDirect
_CamShakeDuration _CamShakeIntens _HandIK_L_LoPos _HandIK_L_LoRot _HandIK_L_Weight
_HandIK_R_LoPos _HandIK_R_LoRot _HandIK_R_W_Walk _HandIK_R_Weight _HitPointTrans _MeleeGripOfChar
_MeleeWeaponMR _MultiHitPointTrans _SwingSoundSetName"""),
    component("Hand_Tools", "Weapon_Range", "combat-rule", "combat", {
        **COMMON, **numbers("_AmmoType _AutoFire _BulletSpeed _FireAttractDis _FireDistance _FireRate _GunType _MaxMagCount _RaysPerShot _ShotGunRaysMaxAngle"),
    }, OMITTED + """ _1_Hand_Idle_Hold _1stCamRecoil_Rate _1stGunRecoil_Rate _Bolt _BowAnimancer
_BulletShellPrefab _Fire _FireCamShakeDuration _FireCamShakeIntens _FireCamUpBackDura _FireCamUpDuration
_FireCamUpIntens _FireLeftRightIntens _FireParticleType _GunDirect _HasSlideLock _Mag _PistolHammer
_Reload _RotScopeWhenLoadAmmo _ScopeInfo _ShellLoPos _ShellLoRot _ShellOuter _TracerRoundScale
_TracerSphereColRadius _ZoomAimCamRecoil_Rate _ZoomAimGunRecoil_Rate _aimLine _aim_Reload_SetName
_currScope _fireSounds_SetName _forceFireParPushDis _gunAimDatas"""),
)
