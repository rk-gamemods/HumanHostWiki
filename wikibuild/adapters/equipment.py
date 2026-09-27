"""Armor mounting categories and the parts available to an armor patch.

Equipment_Info.EquipBoneType and EquipArmorPatch_Info.Start establish these
fields in build 25548639. Character transforms, audio, renderers and mutable
instances are presentation/runtime data, not armor statistics.
"""

from .schema import Ref, component

SPECS = (
    component("Item_Info", "Item_Info", "configuration", "technical-reference", {
        "assetRef_Key": str, "_IconRef": Ref("collectible-item"),
        "Info_Engine": Ref("engine"), "Info_Tire": Ref("tire"),
    }, "_drop_IconGUID _slot_Obj",
       notes="Serialized item-model identity and collectible-item/vehicle-part bindings; runtime drop and slot state are omitted."),
    component("Equipment", "Equipment_Info", "equipment", "items-equipment", {
        "_EquipBoneType": int,
    }, "_EquipTransOfChars _UseShieldAimRot _ChestCrouchLoPos _ChestCrouchLoRot _SoundMat _ShieldOn_SFX _belongSlot _belongBodyCol _armorCols _armorRenders",
       notes="Serialized armor mounting category; protection and durability come from the associated item configuration."),
    component("Equipment", "EquipArmorPatch_Info", "equipment", "items-equipment", {
        "_ArmorPartsPrefabs": [Ref("armor-part")],
    }, "_ArmorPartsIns",
       notes="Available armor patch parts. Runtime selection depends on the inventory slot's armor tag."),
)
