"""Item quality, upgrade configuration and new-character selection.

UI assembly ownership does not make these gameplay settings presentation-only.
Mutable slots, save identifiers, current quality and menus are excluded.
"""

from .schema import NUMBER as N, Ref, component, fields

SPECS = (
    component("UI", "DynamicToolTipSet", "equipment", "items-equipment", {
        # UI/UI.decompiled.cs: DynamicToolTipSet.ToolTipTiles contains only
        # these Language_Text references; data is the serialized wrapper.
        "data": fields({name: Ref("tooltip-text") for name in """
_Dura_Title _BlockDura _Damage_Title _HitDown_Title _BladeHit_Title _GunFireRate_Title
_SingleShot_Title _GunMaxMag_Title _GunAmmoType_Title _BowAmmoType_Str _Quality_Title
_BladeHit_Instruct _HeadShot_Instruct _ArrowDamage _ArrowRange _ArrowSpeed
_ShootRange_Title _Recoil_Title _DummyRound_Title _Jam_Title _GatheringTool
_GatheringToolSmallAxe""".split()}),
    }, "m_Enabled m_GameObject m_Name m_Script",
       notes="Item tooltip title and instruction bindings to the game's localized text records."),
    component("UI", "Slot_Info", "equipment", "items-equipment", {
        "_slotIndex": int, "_SlotType": int, "_NeedSwapCheck": int,
        "_slotTag": str, "_slotTag2": str,
    }, """Image ModelPrefab Selected Stack_Text _BackGroundIcon _DurabilityBar _QualityImage
_SlotBelongBI_Info _SlotRootOfChar _assetRefForSplit _equip_Ins _forceNewDuraData
_iconInfoPrefab _inLoading _initAlready _isEmptySlot _qualityIndex _runtimeSmashAgent
_skipReleaseOnNextLoad _slotRootTag""",
       notes="Serialized slot index, type and swap restrictions. Current item, stack, quality, durability and save ownership are omitted."),
    component("UI", "Item_Slot_Mgr", "equipment", "items-equipment", {
        "_MaxCraftLevel": int, "_MaxLootLevel": int,
        "_EquipUpgradePityFailCounts": [int], "_EquipUpgradeSuccessRates": [N],
        **{name: [N] for name in "_qualityBladeHitFactors _qualityDamageFactors _qualityDuraFactors _qualityHitDownFactors _qualityRandomRates".split()},
    }, """On_Campfire_Enable UI_IconAfterSplit _ArrowIndicator _DecomposeMenu
_DismantleMenu _DismantleOkMenu _DropItemIndicator _DyToolTipSet _EquipMenu
_GameSettings _GunAttachMenu _GunAttachSlots _GunAttachWindow _HandCraftBullet
_IconSplitPrefab _ItemMenuTop _OnPickItem _On_DelOnHandItem _On_GunAttachSlot_Swap
_On_Gun_Ammo_Unloaded _On_PickBI _On_Pick_EnviroBI _On_Slot_Combined _On_Slot_Swap
_Player_BeltRoot _QualityTooltipColors _RepairMenu _SplitStackMenu _TerraBlockDropMesh
_UnloadAmmoMenu _UpgradeBtnToolTipText _UpgradeFailedNoticeText _UpgradeMenu
_UpgradeNotFoundNoticeText _UpgradeOkMenu _UpgradeOkToolTipText _UpgradePityToolTipText
_UpgradeSuccessSFX _UseClickIcon _UseMenu _allSlots_NPC _allSlots_Player
_craftDuraPercent _lastEnableMenus _randomItemQualityIndex _saveID _slotQualitySprites
_slotsBag_Player _slotsBelt_Player _slotsEquip_Player""",
       notes="Serialized item-quality and equipment-upgrade parameters, preserving tier order. The _OnPickItem runtime event, current quality, upgrade attempts and saved slot contents are omitted."),
    component("UI", "UI_Control", "world-rule", "world-systems", {
        "DeleteDropItemSeconds": N, "_EnableScrollWheelBeltSwitch": int,
        "_CharInfos": [fields({"initTalentName": Ref("initial-talent-name"),
                               "initTalentLv": int, "charInitItems": Ref("initial-inventory")},
                              "videoPlayer titleObj")],
    }, """Audio_UIs Build_Instruction CodingButton CodingPanel DisplayWindow Esc_GameMenu
EventSystem GameSetting_UIs GameSettingsTop Graphic_UIs Language_UIs LastBelt_Selected
NoticeBoxText NoticeBoxText_ForGetOnCarSeat NoticeBoxTop NoticeBoxTop_ForGetOnCarSeat
NowActived_SlotHighLight NowActived_ToolTip OnQuitGameButtonPressed OnShowingUIs
On_AudioSliding On_ClickR_Merchant On_ESC_Press On_GameSetting_Changed SelectedBeltIndex
TerraBlock_Instruction TireSetting TireSlider TireText TireToggle TireToggle_Reverse
UI_Bag UI_Belt UI_CharacterSkill UI_InputField_Split UI_Mouse_Target UI_VehicleMass
UI_VehiclePowerBar UI_VehiclePowerTextCurr UI_VehiclePowerTextMax UI_VehicleStatusTop
UI_VehicleVelocity UseF_Object _AS_BGM _AS_CampFire _BGMs _BackMainMenuTooltipWindow
_BikeUI _ButtonClick_AS _BuyInputWindow _CharSelectTop _CharSelect_L _CharSelect_R
_CompassBar _Equip_Slots _ExitTooltipText1 _ExitTooltipText2 _Full_Dura_Color _GameMenu
_HP_Bar _HP_Text _HitBlock_Top _HitCreature_Top _Hotkey_UIs _InitItemSlot _IsWorldScene
_LSS_ForceQuitUI _Load_Window _LoadingImageTop _ManualSaveTop _MerchantWindow
_ModBrowserCanvas _NewGameConfig _NewGamePlayButton _NoticeTop _OnClickManualSave
_OnESC _PauseButton _Pick_Menu _Player_Bag_Slots _Player_Belt_Slots
_QuitGameStartSceneTWindow _QuitGameTooltipWindow _ResumeButton _SellInputWindow
_SinglePlay_1 _SinglePlay_2 _SkillSlot _Stamina_Bar _ToolTipPrefab _TurnOffCar
_TurnOnCar _UI_PlayerButtonBar _UI_PlayerMenu _VideoBackground _VramTooltipWindow
_WorkshopTop _Zero_Dura_Color _crateInputOn _inputField_Debug _inputField_Debug_Scrollbar
_isGamePaused _lastManulSaveID _lastRemoveShowUI_Frame _noGameSetFile _origBGM_V
_origCampFire_V _pickPropIndis _pickPropIndisFrame _randomSeedInput _syncGameSettingUIs
_worldMapEnabled filled_PixelRes_SelectField filled_TexRes_SelectField selected_Belt_Slot""",
       notes="Serialized dropped-item lifetime in seconds, belt-scroll setting, and initial talent/inventory choices. Current character and save data are omitted."),
)
