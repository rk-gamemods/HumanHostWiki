"""Workbench definitions, recipe ingredients and disassembly yields."""

from .schema import NUMBER as N, V2, Ref, component, fields

RECIPE = {
    "craftNum": int, "craftSeconds": N, "iconInfo": Ref("produces-item"),
    "iconRef": Ref("produces-item-asset"),
    "matsData": [{"matNeedCount": int, "matIcon": Ref("consumes-item-asset")}],
}
CRAFT = {
    "_workbenchType": int, "_mustKeepOpen": int,
    "_CraftItemsData": [fields({"perIconData": [RECIPE]}, "BigCategory DisplayName LayoutCellSize LayoutSpacing")],
}
CRAFT_UI = """_AllBigButtons _CraftSlotProto _CraftWindow_Title _Craft_Window
_Grid_CraftIcon _InputNumber _MatSlotProto _MaxCountButton _MaxCountTooltip
_ProgressBar _ProgressBarItemName _ProgressBarNumber _belongBIkey _cancelCraftIcon
_craftButtonImg _craftCount _inCrafting _slotInfos"""

SPECS = (
    component("UI", "Craft_Items", "workbench", "crafting-processing", CRAFT, CRAFT_UI),
    component("UI", "Special_Workbench", "workbench", "crafting-processing", CRAFT,
              CRAFT_UI + " _ActiveParticles _AudioSource _EmissiveMrMatsIndex _FastLight _LerpSeconds _Light1 _Light2 _LightHandlerObj _SphereCol"),
    component("Item_Info", "Disassemble_Set", "processing-rule", "crafting-processing", {
        "resourceInfo": [{"getNumRange": V2, "leftDuraAsNumber": int, "iconRef": Ref("yields-item-asset")}],
    }),
)
