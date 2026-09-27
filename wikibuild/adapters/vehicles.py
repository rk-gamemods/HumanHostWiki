"""Vehicle part defaults; runtime fuel and saved player code are excluded."""

from .schema import Ref, component, numbers

SPECS = (
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
