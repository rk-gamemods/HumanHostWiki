"""Merchant stock/pricing configuration and initial character inventories.

Reviewed against Merchant_Mgr.BiomeItemSet, GetTypeItemRates and
Char_Item_Icons.Init_Icons in captured build 25548639. Audio, menu widgets and
current inventory/save data are omitted; ordered stock entries retain evidence.
"""

from .schema import NUMBER as N, V2, Ref, component, fields, numbers

STOCK_ITEM = {"iconRef": Ref("merchant-stock-item"), "randomSampleCount": N,
              "countRange": {"x": int, "y": int}}
STOCK_TYPE = {"typeNameLangu": Ref("stock-category-name"), "priceFactor": N,
              "typeItems": [STOCK_ITEM]}
BIOME_STOCK = {"BiomeName": str, "Items": [STOCK_TYPE],
               "MerchantPrefabs": [fields({"merchantRef": Ref("merchant-prefab")}, "voiceRefs voiceTexts")]}
PRICE_GROUP = {"factorRange": V2, "probability": N}

SPECS = (
    component("Merchant", "Merchant_Mgr", "loot-source", "loot-acquisition", {
        "_BiomeItemSet": [BIOME_STOCK],
        "_BuyPriceFactorGroups": [PRICE_GROUP], "_SellPriceFactorGroups": [PRICE_GROUP],
        **numbers("_SpawnDis _DespawnDis _MerchantDisInterval _MaxMerchantCount _MerchantCellHostProb _RefreshIntervalMinutes"),
    }, """_BuyInput _BuyInputWindow _BuyPriceSum _CostPrice _GreenColor _InsParent
_MT_AudioSource _MerchantWindow _PlayerCoinText _ProfitLabel _ProfitRate _RedColor
_RefreshCountdownText _SellInput _SellInputWindow _SellPriceSum _TempSellPriceLabel
_TypeSelectField _VoiceTextSlot""",
       notes="Serialized merchant stock and price-factor configuration. Buy and sell are from the merchant's perspective; generated stock and transaction prices are not evaluated."),
    component("Merchant", "Merchant_Ins", "spawn-rule", "spawning-populations", {
        "MaxTerrainAngle": N,
    }, "_Colliders _MainMeshRender _Renderers _Rigid _VoicePosition",
       notes="Configured terrain-angle limit for merchant placement, in degrees; geometry and runtime placement checks are not evaluated."),
    component("UI", "Char_Item_Icons", "loot-source", "loot-acquisition", {
        "_InitItemsRef": [{"IconRef": Ref("initial-item"), "itemName": str, "stack": int}],
    }, "_allSlots",
       notes="Serialized initial inventory entries; existing saved inventory and runtime slot state are not represented."),
)
