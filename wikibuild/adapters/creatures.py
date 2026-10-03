"""AI and creature configuration. Mutable targeting/path state is excluded."""

from .schema import Ref, component, numbers

SPECS = (
    component("AI", "Zombie_Agent", "creature", "creatures-ai", {
        **numbers("_FrontViewDis _MeleeAttackInterval _NPC_CapRadius _contactDisToTarget _moveType _randomWalkInterval _walkTriggerChance"),
        "_NPC_Input": Ref("controller"), "_zombieInput": Ref("zombie-controller"),
    }, """_InHitWall _On_NPC_MeleeAttack _On_NPC_StopMeleeAttack _Seeker _allowFocusTarget
_contactDisSqt _endAttkTimeP _finishedMeleeAttack _focusCharController _focusCollider _focusPlayer
_focusTrans _focusWallCollider _frontViewDisSqt _isMeleeAttacking _lastCheckStuckPos _lastCheckStuckTime
_lastTargetPos _mask_8_10 _pathStatus"""),
    component("AI", "AI_Agen_Mgr", "ai-rule", "creatures-ai",
              numbers("_FollowDis _MaxAllowActiveZombies _MaxDisToOrigSpawnPoint _MaxFollowDisCha"),
              "On_Sound_Played _GridMover _lastBoxOverlapFrame _zombieActive"),
    component("Creature", "Creature_Mgr", "ai-rule", "creatures-ai",
              numbers("_FastMoveFactor _MutantLvAttckBlockPerTime _MutantLvAttckPerTime _MutantLvDisInterval _MutantLvHpPerTime _ToRunDisSqt _ToRunModeDis_WhileAroundZombieDied _FootstepSoundMaxDisSqt _RoarSoundMaxDisSqt _Move_Mid_F _Move_Slow_F"),
              """On_Add_To_World_PullBack_Objects On_Remove_From_World_PullBack_Objects On_Zombie_Died
_1stTakeItemAnim _1stUnHoldShieldAnim _CharWetProperties _DayTimeChanged _ESC_Menu _FootMask _FootMaskArry
_IsDayTime _LoadingImageText _LoadingImageTop _LookAtTarget _OnGetBIkey _On_Char_Died _On_HitReactWhenAttack
_On_Player_NoneZombieNPC_Step _On_Switch_To_GPUI _RagdollTop _RightHandPutItemAnim _RollBackBarTop _Volume
_charFixedUpdates _endReposCarTime _gotBIkey _hasShowingUI _inLoadingChunkBIs _inLoadingFurni _inLoadingProps
_inLoadingSysHouses _inReposCar _isWorldPullingBack _neutralizedPlayerMove _none_GPUI_Chars
_oldWeatherZoneSpawned _origLookTargetParent _stuckPosBuffer _stuckPosCount _stuckPosEndIndex char_GPUI_Render_Mgr"""),
)
