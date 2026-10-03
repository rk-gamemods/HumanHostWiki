"""Vehicle part defaults; runtime fuel and saved player code are excluded."""

from .schema import NUMBER as N, V2, V3, Ref, component, fields, numbers

CURVE = {"m_Curve": [{**numbers("time value inSlope outSlope inWeight outWeight"), "weightedMode": int}],
         "m_PreInfinity": int, "m_PostInfinity": int, "m_RotationOrder": int}
BIKE = {
    **numbers("torque topSpeed relaxedSpeed reversingSpeed bunnyHopStrength bunnyHopInterval bunnyHopFullChargeTime brakeStrength oscillationAmount oscillationAffectSteerRatio"),
    **dict.fromkeys("groundConformity inelasticCollision wheelieToggle _useExternalMoveInput _useExternalSprintInput brakeKey bunnyHopKey fastMoveHotKey".split(), int),
    "centerOfMassOffset": V3, "accelerationCurve": CURVE, "steerAngle": CURVE, "leanCurve": CURVE,
    "wheelFrictionSettings": fields({"fFriction": V2, "rFriction": V2}, "fPhysicMaterial rPhysicMaterial"),
    "airTimeSettings": {"freestyle": int, **numbers("airTimeRotationSensitivity heightThreshold groundSnapSensitivity")},
}
BIKE_RUNTIME = """_OnPlayerInput axisAngle bunnyHopAmount bunnyHopInputState crankCurrentQuat
crankLastQuat crankSpeed currentTopSpeed customAccelerationAxis customLeanAxis customSteerAxis
cycleGeometry cycleOscillation deceleration externalMoveInput fPhysicsWheel fWheelRb
isAirborne isReversing isTouchingGround lastBunnyHopTime lastDeceleration lastVelocity
pedalAdjustments pickUpSpeed rPhysicsWheel rWheelRb rawCustomAccelerationAxis rb restingCrank
simulatedSpeed sprint stuntMode turnLeanAmount wayPointSystem wheelieInput wheeliePower"""

SPECS = (
    component("Bicycle", "SBPScripts.BicycleController", "vehicle-rule", "vehicles", BIKE, BIKE_RUNTIME,
       notes="Bicycle movement defaults and curve keys. topSpeed/reversingSpeed compare against rigidbody speed; relaxedSpeed is a multiplier. Friction vectors store static (x) and dynamic (y) coefficients. Acceleration curve input is acceleration control, steering curve input is speed, and lean curve input is lean control. Live input, recorded rides and animation geometry are omitted."),
    component("Bicycle", "SBPScripts.LockBicycleController", "vehicle-rule", "vehicles", {
        "wheelTorque": N, "sprintWheelTorque": N,
        "_useExternalMoveInput": int, "_useExternalSprintInput": int, "fastMoveHotKey": int,
    }, BIKE_RUNTIME + " " + " ".join(name for name in BIKE if name not in {"_useExternalMoveInput", "_useExternalSprintInput", "fastMoveHotKey"}) + " _AS_normal _AS_sprint _OnAllow _OnBicycleRotate _allowRun _normalVolume _sprintVolume",
       notes="Stationary generator-bike rotation defaults. Despite their names, wheelTorque/sprintWheelTorque drive an interpolated wheel rotation rate in degrees per second in Update. This subclass has an empty FixedUpdate and does not use the moving bicycle's propulsion settings. Fuel generation is implemented in Bicycle_Glue.Generate_Power."),
    component("Bicycle_Glue", "Bicycle_Glue", "vehicle-rule", "vehicles", {
        "_Ik_Target_Info": [fields({"BicycleName": str, "BicyclePrefab": Ref("bicycle-prefab")}, """_Handles_Name _Pedal_L_Name _Pedal_R_Name _CharLoPos _Hip_ikTarget_LoPos _Hip_ikTarget_LoEuler _Chest_ikTarget_LoPos _Chest_ikTarget_LoEuler _Hand_L_ikTarget_LoPos _Hand_L_ikTarget_LoEuler _Hand_R_ikTarget_LoPos _Hand_R_ikTarget_LoEuler _IdleFootL_ikTarget_LoPos _IdleFootL_ikTarget_LoEuler _FootL_ikTarget_Under_PedalL_LoPos _FootL_ikTarget_Under_PedalL_LoEuler _FootR_ikTarget_Under_PedalR_LoPos _FootR_ikTarget_Under_PedalR_LoEuler""")],
    }, "_Animator _AnimatorController _Chest_IK _FootL_IK _FootL_IK_Idle _FootR_IK _HandL_IK _HandR_IK _HeadDownFloat _HeadIK_TargetLoPos _Hip_IK _Rig",
       notes="Bicycle-name to instantiated controller-prefab bindings. Rider skeletal targets are omitted; generator output is code-defined rather than stored in these bindings."),
    component("Car", "Car_Control", "vehicle-rule", "vehicles", {
        "maxSteeringAngle": N, "topInfo": Ref("vehicle-top"),
    }, "EngineRunning HandBrake_On HorizontalFloat JumpFloat TireInfos VerticalFloat carCoding",
       notes="Maximum steering angle in degrees and owning vehicle binding. Input, running state and discovered tire instances are omitted."),
    component("Car", "Solar_Generator", "vehicle-rule", "vehicles", {"_BI": Ref("generator-building")},
       notes="Generator building binding. Fuel output depends on code-defined scheduling, daylight, occlusion, weather fog density and engines needing fuel; the binding alone is not an output rate."),
    component("Car", "Train_Rail", "vehicle-rule", "vehicles", {
        **numbers("linkTolerance minLinkDirDot branchLinkTolerance halfWidth"), "next": Ref("next-rail"),
    }, "nodes",
       notes="Rail connection/search tolerances and half-width in meters. minLinkDirDot is a tangent dot-product threshold (0.5 permits a 60-degree bend); next is an optional manual segment link. Centerline geometry is omitted."),
    component("Bicycle", "SBPScripts.SuspensionManager", "vehicle-rule", "vehicles", {
        **numbers("enable frontSpring frontDamper rearSpring rearDamper"),
    }, "fSuspension rSuspension chain frontSuspensionMesh spring",
       notes="Serialized bicycle suspension enable flag and front/rear joint spring and damping parameters."),
    component("Item_Info", "ItemInfo_Engine", "vehicle-rule", "vehicles",
              numbers("EnginePower EngineSpeedFactor FuelMax"), "FuelBar FuelBarText FuelLeft OutOfFuel _originLocalScale"),
    component("Item_Info", "ItemInfo_Tire", "vehicle-rule", "vehicles",
              numbers("TirePowerPercentage reverseSteering steering"),
              "MinusedPowerFromCarTop col_Player lastTopPowerMax wheelCollider wheelMesh"),
    component("Build_System", "Top_Info", "vehicle", "vehicles", {
        **numbers("Allow_BuildMode _MaxVelocity _Type"),
        "Engines": [Ref("engine")], "Tires": [Ref("tire")], "MainSeat": Ref("driver-seat"),
    }, """AlreadySavedCodeToDisk BIsMassUnderTop BelongChunk Builds_All BulletFirstForce BulletFirstVelocity
Car_Core Code_Player Code_Translated ConsistBackVehicle ConsistFrontVehicle ConsistRole Crane Driver
EnginePowerLeft EnginePowerMax FallenChecking InCraneLiftingUp IsInLoading Is_Detecting_Battles
LastSavedRoboPos LoadedInBuildMode Loaded_ConsistBackVehicle Loaded_ConsistFrontVehicle Loaded_Rail_BI_Key
NeedSaveCode NeedSaveEngineInfo NeedSaveRoboCubes NeedSaveRoboPos NeedSaveTireInfo OnCarCreaturesCount
Rail_BI_Key RoboTop_IsDirty RoboTopsFileName TopMassCenter TopOnHit TopRigi _CompassPOI _TempCompassPOI
_lastSavedTopRot _lastTopPosForSaveCheck _lastTopRigidRotV _lastTopRigidV _lastTopRotForSaveCheck
_posCheckInited checkFallen lastTopPos"""),
)
