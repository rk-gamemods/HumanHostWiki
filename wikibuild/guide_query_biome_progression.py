"""Answer what changes across biomes and distances from spawn."""

from __future__ import annotations

from collections import Counter
import math
from .guide_query_acquisition import (
    _how, how_runs, method,
)
from .guide_query_shared import (
    _METHODS, _bench_visible, _biome_value, _category,
    _depth_order, _link, _made, _name,
    _raw, _recipe_visible, _ring_biomes, _sources,
    _visible, format_distance, format_percent, used_in,
)


def _world_rings(context, scope):
    rings = context["graph"]["rings"]
    if not rings:
        return None
    return {"ring_width": format_distance(rings[0]["end_distance"] - rings[0]["start_distance"]),
            "ring_count": str(len(rings))}


def _world_near_spawn(context, scope):
    graph = context["graph"]
    if graph["near_spawn"]["biome"] is None:
        return None
    chances = [item["near_spawn_chance_per_hit"] for key, item in graph["items"].items()
               if item["near_spawn_chance_per_hit"] is not None
               and any(other["chance_per_hit"] > item["near_spawn_chance_per_hit"]
                       for data in graph["biomes"].values() if data["ring"] is not None
                       for other in data["mined"] if other["item"] == key)]
    if not chances:
        return None
    chance = min(Counter(chances).items(), key=lambda pair: (-pair[1], pair[0]))[0]
    return {"near_spawn_chance": format_percent(chance)}


def _positive_fact(context, field):
    values = [row["semantic"]["facts"][field] for row in context["rows"].values()
              if field in row["semantic"].get("facts", {})]
    if not values or any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in values):
        return None
    return values[0] if len(set(values)) == 1 else None


def _world_zombie_scaling(context, scope):
    """Terrain/Terrain.decompiled.cs:1456-1461 divides the interval by _Z_Mutant_F.

    Level one extends 512 metres from spawn; then distance adds levels.
    Terrain.decompiled.cs:2071-2073 adds health; Hand_Tools.decompiled.cs:4231-4232
    adds damage per level. Emit only with both captured distance controls.
    """
    interval = _positive_fact(context, "_MutantLvDisInterval")
    factor = _positive_fact(context, "_Z_Mutant_F")
    return {"zombie_level_step": format_distance(interval / factor)} if interval and factor else None


def _world_loot_scaling(context, scope):
    """UI/UI.decompiled.cs:8948-8977 ramps quality by _QualityCapDistanceInterval.

    The simple guide sentence requires a captured positive interval. The game
    ramps each higher tier through the half interval around successive steps.
    """
    interval = _positive_fact(context, "_QualityCapDistanceInterval")
    return {"quality_step": format_distance(interval)} if interval else None


def _rings(context, scope):
    return [{"index": str(ring["index"]), "number": str(ring["index"] + 1), "biome": _biome_value(context, ring),
             "start_distance": format_distance(ring["start_distance"]),
             "end_distance": format_distance(ring["end_distance"])}
            for ring in context["graph"]["rings"] if not ring["biome_keys"] or any(_visible(context, key) for key in ring["biome_keys"])]


def _ring_span(context, scope):
    return scope


def _ring_materials(context, scope):
    index = int(scope["index"])
    keys = [key for key, item in context["graph"]["items"].items()
            if item["main_ring"] == index and _raw(context, key) and _visible(context, key)]
    keys.sort(key=lambda key: (list(_METHODS.values()).index(method(context, key)),
                               -len(used_in(context, key)), _name(context, key).casefold(), key))
    return [{"item": _link(context, key), "how": _how(context, key, index), "method": method(context, key)} for key in keys]


def _ring_easier_gathering(context, scope):
    index = int(scope["index"])
    current = _ring_biomes(context, index)
    earlier = {biome for ring in context["graph"]["rings"] if ring["index"] < index
               for biome in ring["biome_keys"]}
    new_materials = {row["item"]["entity"] for row in _ring_materials(context, scope)}
    keys = []
    for key in context["graph"]["items"]:
        if key in new_materials or not _visible(context, key):
            continue
        located = {source["biome"] for source in _sources(context, key)
                   if source["type"] == "harvested" and source["biome"] is not None}
        if located & current and not located & earlier:
            keys.append(key)
    keys.sort(key=lambda key: (_name(context, key).casefold(), key))
    return [{"item": _link(context, key),
             "how": {"runs": how_runs(context, key, ring=index, gathering_only=True)}} for key in keys]


def _ring_recipes(context, scope):
    index = int(scope["index"])
    recipes = [(key, recipe) for key, recipe in context["graph"]["recipes"].items()
               if recipe["main_ring"] == index and recipe["output"] and _recipe_visible(context, key)
               and recipe["output"] not in context["bench_items"]]
    recipes.sort(key=lambda pair: (_category(context, pair[1]["output"]).casefold(),
                                   _name(context, pair[0]).casefold(), pair[0]))
    return [{"output": _link(context, key),
             "made": _made(context, recipe),
             "category": _category(context, recipe["output"])} for key, recipe in recipes]


def _ring_benches(context, scope):
    index = int(scope["index"])
    keys = [key for key, bench in context["graph"]["benches"].items()
            if bench["main_ring"] == index and bench.get("built_by_recipe") and _bench_visible(context, key)]
    keys.sort(key=lambda key: (_depth_order(context, key),
                               _name(context, key).casefold(), key))
    return [{"bench": _link(context, key)} for key in keys]


def _ring_exclusive_loot(context, scope):
    index = int(scope["index"])
    biomes = _ring_biomes(context, index)
    graph = context["graph"]
    keys = []
    for key, item in graph["items"].items():
        located = {biome for biome in item["loot_biomes"] if graph["biomes"][biome]["ring"] is not None}
        if located and located <= biomes and not item["has_unmapped_loot"] and _visible(context, key):
            keys.append(key)
    keys.sort(key=lambda key: (_name(context, key).casefold(), key))
    return [{"item": _link(context, key), "how": _how(context, key, index)} for key in keys]


def _ring_merchants(context, scope):
    biomes = _ring_biomes(context, int(scope["index"]))
    count = len({entry["item"] for biome in biomes for entry in context["graph"]["biomes"][biome]["merchant"]
                 if _visible(context, entry["item"])})
    return {"merchant_count": str(count),
            "merchant_plural": "kind of item" if count == 1 else "kinds of items"} if count else None


QUERIES = {
    "world.rings": _world_rings,
    "world.near_spawn": _world_near_spawn,
    "world.zombie_scaling": _world_zombie_scaling,
    "world.loot_quality_scaling": _world_loot_scaling,
    "rings": _rings,
    "ring.span": _ring_span,
    "ring.new_materials": _ring_materials,
    "ring.easier_gathering": _ring_easier_gathering,
    "ring.new_recipes": _ring_recipes,
    "ring.new_benches": _ring_benches,
    "ring.exclusive_loot": _ring_exclusive_loot,
    "ring.merchant_summary": _ring_merchants,
}
