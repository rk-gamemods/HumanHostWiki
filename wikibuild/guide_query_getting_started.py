"""Answer what players can gather, craft and build when starting out."""

from __future__ import annotations

from .guide_query_acquisition import (
    _how, method,
)
from .guide_query_shared import (
    _METHODS, _bench_visible, _biome_value, _category,
    _construction_recipe, _depth_order, _ingredients, _link,
    _name, _raw, _recipe_visible, _ring_biomes,
    _visible, used_in,
)


_START_TAGS = {"MeleeWeapon", "Gun", "Bow", "工具"}


def _starting_closures(context):
    """Least fixed point of recipes and bench chains with ring-zero natural leaves."""
    data = context["graph"]
    if not data["rings"]:
        return set(), set()
    biomes = _ring_biomes(context, 0)
    items = {key for key, item in data["items"].items() if item["main_ring"] == 0
             and any(source["type"] in {"mined", "harvested"} and source["biome"] in biomes
                     for source in item["sources"])}
    recipes, benches = set(), {None}
    changed = True
    while changed:
        before = len(items), len(recipes), len(benches)
        for key, recipe in data["recipes"].items():
            if recipe["main_ring"] == 0 and recipe["bench"] in benches and all(
                    entry["item"] in items for entry in recipe["ingredients"]):
                recipes.add(key)
                items.add(recipe["output"])
        for key, bench in data["benches"].items():
            if bench["main_ring"] == 0 and any(recipe in recipes for recipe in
                    context["recipes_by_output"].get(bench.get("construction_item"), [])):
                benches.add(key)
        changed = before != (len(items), len(recipes), len(benches))
    return recipes, benches


def _card_stat(context, key, pointer):
    return next((stat["display"] for stat in (context["cards"][key] or {}).get("stats", [])
                 if stat["field"] == pointer and stat["display"] is not None), "")


def _start_first_biome(context, scope):
    rings = context["graph"]["rings"]
    return {"first_biome": _biome_value(context, rings[0])} if rings else None


def _start_materials(context, scope):
    graph = context["graph"]
    keys = [key for key, item in graph["items"].items() if item["main_ring"] == 0 and _raw(context, key) and _visible(context, key)]
    keys.sort(key=lambda key: (list(_METHODS.values()).index(method(context, key)),
                               -len(used_in(context, key)), _name(context, key).casefold(), key))
    return [{"item": _link(context, key), "how": _how(context, key, 0), "method": method(context, key)} for key in keys]


def _start_gathering_intro(context, scope):
    return {}


def _start_hand_recipes(context, scope):
    graph = context["graph"]
    recipes = [(key, recipe) for key, recipe in graph["recipes"].items()
               if recipe["bench"] is None and recipe["main_ring"] is not None
               and _recipe_visible(context, key)
               and recipe["output"] not in context["bench_items"]
               and all(graph["items"][entry["item"]]["main_ring"] == 0 for entry in recipe["ingredients"])]
    recipes.sort(key=lambda pair: (_name(context, pair[1]["output"]).casefold(), _name(context, pair[0]).casefold(), pair[0]))
    return [{"output": _link(context, recipe["output"]), "ingredients": _ingredients(context, recipe),
             "category": _category(context, recipe["output"])}
            for _, recipe in recipes]


def _start_hand_intro(context, scope):
    return {} if _start_hand_recipes(context, scope) else None


def _start_benches(context, scope):
    graph = context["graph"]
    benches = [(key, bench) for key, bench in graph["benches"].items()
               if bench["main_ring"] == 0 and bench.get("built_by_recipe") and _bench_visible(context, key)]
    benches.sort(key=lambda pair: (_depth_order(context, pair[0]),
                                   _name(context, pair[0]).casefold(), pair[0]))
    return [{"bench": _link(context, key),
             "ingredients": _ingredients(context, graph["recipes"][_construction_recipe(context, key)]),
             "unlock_count": str(sum(recipe["bench"] == key and _recipe_visible(context, recipe_key)
                                     for recipe_key, recipe in graph["recipes"].items()))}
            for key, bench in benches]


def _start_benches_intro(context, scope):
    return {} if _start_benches(context, scope) else None


def _start_tools(context, scope):
    graph = context["graph"]
    result = []
    for key, item in graph["items"].items():
        semantic = context["rows"][key]["semantic"]
        tag = (semantic.get("fact_labels") or {}).get("/_Tag", semantic.get("facts", {}).get("_Tag"))
        if tag not in _START_TAGS or not _visible(context, key):
            continue
        recipes = [(recipe_key, graph["recipes"][recipe_key]) for recipe_key in
                   sorted(source["via"] for source in item["sources"] if source["type"] == "crafted")]
        recipes.sort(key=lambda pair: (_depth_order(context, pair[1]["bench"]), _name(context, pair[0]).casefold(), pair[0]))
        for recipe_key, recipe in recipes:
            if recipe_key not in context["starting_recipes"] or not _recipe_visible(context, recipe_key):
                continue
            bench = recipe["bench"]
            result.append((_depth_order(context, bench), _name(context, key).casefold(), recipe_key,
                           {"Item": _link(context, key), "Damage": _card_stat(context, key, "/_baseDamage"),
                            "Durability": _card_stat(context, key, "/_BaseMaxDurability"),
                            "Made at": _link(context, bench) if bench else "By hand",
                            "Ingredients": _ingredients(context, recipe)}))
            break
    return [row for _, _, _, row in sorted(result)]


QUERIES = {
    "start.first_biome": _start_first_biome,
    "start.materials": _start_materials,
    "start.gathering_intro": _start_gathering_intro,
    "start.hand_intro": _start_hand_intro,
    "start.benches_intro": _start_benches_intro,
    "start.hand_recipes": _start_hand_recipes,
    "start.benches": _start_benches,
    "start.tools_and_weapons": _start_tools,
}
