"""Serialized keyboard defaults and their action bindings, not saved overrides."""

from .schema import Ref, component

SPECS = (
    component("Player_HotKeys", "Hotkey_Sets", "configuration", "technical-reference", {
        "keyCode": int,
    }, notes="Captured Unity KeyCode value for a default binding; user remapping is not represented."),
    component("Player_HotKeys", "Player_HotKeys", "configuration", "technical-reference", {
        **{name: Ref("hotkey-binding") for name in "A Bag Craft CrouchHold CrounchOnce D FastPutItem FirstPerson FlashLight Jump Map Q_Menu Reload S Sprint TakeAll Talent UseF W".split()},
        **dict.fromkeys("CarBuildMode CarCodeDebug CarCoding CarRighting DeleteCube DownMoveSpace LeftRight OnOffEngine RiseFall Rot_Xa Rot_Xm Rot_Ya Rot_Ym Rot_Za Rot_Zm SetCarCore ShowCarStatus UpMoveSpace alpha_1 alpha_10 alpha_2 alpha_3 alpha_4 alpha_5 alpha_6 alpha_7 alpha_8 alpha_9".split(), int),
    }, "CarVerticalFloat ComfirmNewKeyBind FallbackToLast On_HotkeyChanged On_Hotkey_Changed _HotkeyListener _HotkeySetTooltip hotkeySetters",
       notes="Captured action-to-key defaults and binding links. Direct numeric values are Unity KeyCode values; current input and saved overrides are omitted."),
)
