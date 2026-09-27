"""Body/material damage factors and serialized melee/ranged weapon settings."""

from .schema import NUMBER as N, Ref, component, numbers

COMMON = {
    **numbers("_Damage _DamageType _BladeHitProb _HitDownProb _HitFlyForce _DismemberBody _BlowHead _DuraCostPerAttack _DigGetDirtBlock _RepairDis _RepairNoiseDis _RepairValue _repairType _PushBodyDis _HitReactAmplitude"),
    "_matsDamageSetName": str, "_weaponHitSetName": str, "_damageFactorSet": Ref("body-damage-set"),
}
OMITTED = """_1stCamMod _AI_Agent _AimingModeIdleAnim _CharBase _GPUI_Crowd_Prefab _G_Info
_IsToolNoBounce _WeaponPosDatas _arrowDamage _creatureMgr _damage _equipSoundSetName _inBouncingHit
_lastHitIsScene _playerInput _reShotDis _soundMgr _thisToolSlot _toolMgr _tracerBulletForward
_weaponRenders layer_Creature layer_Ragdoll mask_2_8_9_10_14 mask_HitFinal mask_HitNoBI"""

SPECS = (
    component("Hand_Tools", "BodyPartsDamage_Sets", "damage-type", "combat", {
        "_BodyPartsDamageFactor": numbers("armLeg chest head"),
    }, "触发自动编译"),
    component("Hand_Tools", "Mat_Damage_Sets", "damage-type", "combat", {
        "_Mats_Damage": [{"damage": N, "soundMat": Ref("material")}],
    }),
    component("Hand_Tools", "Weapon_Melee", "combat-rule", "combat", {
        **COMMON, **numbers("_StaminaCost _GrassRemoveRadius"), "_ComboDmgFactors": [N],
    }, OMITTED + """ _1stNoAim_Melee_Anims _AimMode_Melee_Anim _BladeDirect _BladeTipDirect _BounceSpeed
_BoxCenter _BoxSize _CamShakeDuration _CamShakeIntens _HandIK_L_LoPos _HandIK_L_LoRot _HandIK_L_Weight
_HandIK_R_LoPos _HandIK_R_LoRot _HandIK_R_W_Walk _HandIK_R_Weight _HitPointTrans _MeleeGripOfChar
_MeleeWeaponMR _MultiHitPointTrans _PossibleAnims _StuckTime _SwingSoundSetName"""),
    component("Hand_Tools", "Weapon_Range", "combat-rule", "combat", {
        **COMMON, **numbers("_AmmoType _AutoFire _BulletSpeed _FireAttractDis _FireDistance _FireRate _GunType _MaxMagCount _RaysPerShot _ShotGunRaysMaxAngle"),
    }, OMITTED + """ _1_Hand_Idle_Hold _1stCamRecoil_Rate _1stGunRecoil_Rate _Bolt _BowAnimancer
_BulletShellPrefab _Fire _FireCamShakeDuration _FireCamShakeIntens _FireCamUpBackDura _FireCamUpDuration
_FireCamUpIntens _FireLeftRightIntens _FireParticleType _GunDirect _HasSlideLock _Mag _PistolHammer
_Reload _RotScopeWhenLoadAmmo _ScopeInfo _ShellLoPos _ShellLoRot _ShellOuter _TracerRoundScale
_TracerSphereColRadius _ZoomAimCamRecoil_Rate _ZoomAimGunRecoil_Rate _aimLine _aim_Reload_SetName
_currScope _fireSounds_SetName _forceFireParPushDis _gunAimDatas"""),
)
