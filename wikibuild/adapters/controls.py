"""Serialized keyboard defaults and their action bindings, not saved overrides."""

from .schema import V3, Ref, component, numbers

SPECS = (
    component("Camera", "CamController", "configuration", "technical-reference", {
        **numbers("_StartDistance _MinDesiredDistance _MaxDesiredDistance _MaxCarDesiredDistance _MouseSpeed _MouseSpeedScope _MouseSpeedRate _MouseSpeedScopeRate _DesiredisSpeed _DisChangeSpeed yMin yMax _MaxMouseDeltaTime _LagSpikeThreshold _LagSmoothWindow _LagMouseClampMultiplier _CamColRadius _1stMeleeCrouchDis _UpDownOffset _AimOffsetRight"),
        "_CamOffset": V3, "_AllowCameraCollision": int, "_AllowScrollDistance": int,
    }, """OnCameraAboveWater OnCameraUnderWater _AimToTargetDis _CamOffsetNew _CamRootTrans
_ClipMask _CurrentDistance _DesiredDistance _GPUI_Cull_Cam _IK_LookAtTrans _In1stPerson
_In1stZoom _InAimZoom _InAimingMode _InScopeZoom _LookDownCamLoPos _LookDownCamLoPos_C
_LookMidCamLoPos _LookMidCamLoPos_C _LookUpCamLoPos _LookUpCamLoPos_C _allow1stPersonMod
_allowLerpOffset _angleCharNoneAimMode _backFollowRate _camF_MoveDirect_Angle _camFace
_camFollowTrans _changeItem _charAttacking _charCanControll _charInStand _charIsDead
_charOnCarSeat _charOnSeat _cursorVisible _faceCam _fastMoveReloading _gunIsAimingAir
_headTrans _initCamRot _isBowOnHand _isFallGround _isMeleeWeapon _isPistolOnHand
_lookUpDownAngle _mainCam _mainCamTrans _maxAimDis _mouseY_Invert _origAimOffsetRight
_origCamFov _origMouseSpeed _originCamOffset _playerCrouch _playerTop _pressed_Move
_reloading _rotSmoothTime _startGetUp _useCamShake _viewForwardAngle x y""",
       notes="Camera distance, collision, offset and input-smoothing defaults. Vertical angle limits are degrees; current aim, camera position and player state are omitted. User settings and gameplay can override defaults."),
    component("Player_HotKeys", "Hotkey_Sets", "configuration", "technical-reference", {
        "keyCode": int,
    }, notes="Captured Unity KeyCode value for a default binding; user remapping is not represented."),
    component("Player_HotKeys", "Player_HotKeys", "configuration", "technical-reference", {
        **{name: Ref("hotkey-binding") for name in "A Bag Craft CrouchHold CrounchOnce D FastPutItem FirstPerson FlashLight Jump Map Q_Menu Reload S Sprint TakeAll Talent UseF W".split()},
        **dict.fromkeys("CarBuildMode CarCodeDebug CarCoding CarRighting DeleteCube DownMoveSpace LeftRight OnOffEngine RiseFall Rot_Xa Rot_Xm Rot_Ya Rot_Ym Rot_Za Rot_Zm SetCarCore ShowCarStatus UpMoveSpace alpha_1 alpha_10 alpha_2 alpha_3 alpha_4 alpha_5 alpha_6 alpha_7 alpha_8 alpha_9".split(), int),
    }, "CarVerticalFloat ComfirmNewKeyBind FallbackToLast On_HotkeyChanged On_Hotkey_Changed _HotkeyListener _HotkeySetTooltip hotkeySetters",
       notes="Captured action-to-key defaults and binding links. Direct numeric values are Unity KeyCode values; current input and saved overrides are omitted."),
)
