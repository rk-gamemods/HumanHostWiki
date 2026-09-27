"""Skill definitions, progression and survival defaults."""

from .schema import NUMBER as N, Ref, component, fields, numbers

SKILL_DATA = fields({
    "_name": Ref("localized-name"), "_instruct": Ref("localized-description"),
    "_values": [{"_replaceStrs": [N]}], **numbers("buffPeriod isBuff maxLv stackableBuff"),
}, "icon")
SKILL = fields({"_class": Ref("skill-class"), "_skill": SKILL_DATA})
SPECS = (
    component("Creature", "All_Skills_Set", "skill", "skills-survival", {
        "_CraftSkills": [SKILL], "_FightSkills": [SKILL], "_SurviveSkills": [SKILL],
    }),
    component("Creature", "Char_Status", "survival-rule", "skills-survival", {
        **numbers("_DnaDmgMaxHp_Factor _EnableFoodWater _foodCostPerTime _foodWaterInterval _maxFood _maxHP _maxStamina _maxWater _origMaxHP _origMaxStamina _origStamRege _stamRegePerSec _waterCostPerTime"),
        "_CharSkill": Ref("character-skills"),
    }, "_Controller _On_HP_Changed _On_StaminaChanged _costedMaxHP _currHP _currStamina _currWetness _currentFood _currentWater _playerVig"),
    component("Creature", "Skill_Mgr", "survival-rule", "skills-survival", {
        **numbers("_BaseExpToLv2 _ExpIncreasePerLv _ExponentialFactor _GrowthType _MaxLevel _maxCraftLevel _maxLootLevel"),
        "_SkillSets": Ref("skills"),
        **{name: SKILL_DATA for name in "_Bleeding_Debuff _BoneBreak_Debuff _BoneBreak_Heal _DnaDmg_Skill _Infection_Debuff _Medical_Bandage _NanoRepair_Capsule _NeuroRush_Pill _PainKiller _Stamina_Capsule _Stimulant_Capsule _TearWounded_Debuff".split()},
    }, """_AdrMatAlpha _AdrMatDistortion _AdrlinAS _AdrlinScreenVFX _BuffColor _BuffSlotPrefab _Buff_Root
_Canvas _CraftSkillRoot _DeBuffColor _DeBuff_Root _DelSkillWindow _DnaMaxLvAlertWindow _EXP_Bar _EXP_Text
_FightSkillRoot _LevelUpRoot _LevelUpVFX _LevelUp_CraftRoot _LevelUp_FightRoot _LevelUp_SurviveRoot
_MinerSoundMats _SFX _SilentIcon _SilentText _SkillSlotPrefab _SkillToolTipPrefab _SurviveSkillRoot
_WoodJackSoundMats _currTargetGray _seed"""),
    component("Creature", "Char_Skills", "survival-rule", "skills-survival", {
        **numbers("""_HpRegeInterval _addedMaxHp _adrlinAntiHitDown_Add _adrlinMeleeDmg_Factor
_adrlinPeriod _adrlinStaCost_Factor _adrlinTriggerHpRate _adrlinWaterCost_Factor _antiBodySerum_Rate
_antiBodySerum_Seconds _architect_Rate _armorHitDmgTakeRate _armorReflectDmgDuraRate _armorShareDmgRate
_bareBluntHitDownProb_Factor _bareHandDamage_Add _bladeHitDamage_Add _bladeHitProb_Factor _bowDamage_Factor
_bowDrop_Factor _chainReinforceSeconds _craftLevel _craftSkillLevel _duraCostPerAttack_Mod _fakeDeathCD
_fakeDeathHpRate _fighterHitDown_Add _fireDistance_Add _fireRecoil_Factor _fireSpread_Factor
_flashDodgeStaCost _flashDodge_Rate _foodWaterDecrease_Factor _gunDamage_Factor _lootCountRateBoost
_lootOpenSpeedRate _lootQualityRateBoost _maxHP_Factor _maxStamina_Factor _mechanicDmg_Rate _mechanic_RangeSqt
_meleeDamage_Factor _minerDmg_Factor _moraleAboveRate _moraleDmg_Factor _painKillerOnDmgFactor _repair_Factor
_sapperDmg_Rate _sapper_RangeSqt _silenceStepDmg_Factor _silentStepReduce_Factor _silentStepViewReduce_Factor
_softLandDmgReduce_Factor _staminaRege_Factor _stoneSkinDmgReduce_Factor _tearWoundedDmgRate
_woodJackDmg_Factor _woodJackYield_Factor"""),
        "_adrlin_Skill": SKILL_DATA, "_fakeDeath_Skill": SKILL_DATA, "_morale_Skill": SKILL_DATA,
    }, "_Data _On_LootLevel_Changed _boneBreak _medicalBandage"),
)
