"""Answer which benches exist, what they cost and what they craft."""

from __future__ import annotations

from .guide_query_acquisition import (
    _how,
)
from .guide_query_shared import (
    _bench_visible, _category, _construction_recipe, _depth_order,
    _ingredients, _link, _made, _name,
    _number, _recipe_visible, ring_label,
)


def _benches(context, scope):
    keys = [key for key, bench in context["graph"]["benches"].items()
            if bench.get("evidence") != "hand-crafting" and _bench_visible(context, key)]
    keys.sort(key=lambda key: (context["graph"]["benches"][key]["main_ring"] is None,
                               context["graph"]["benches"][key]["main_ring"] or 0,
                               _depth_order(context, key), _name(context, key).casefold(), key))
    return [{"bench": _link(context, key)} for key in keys]


def _bench_recipes(context, scope):
    key = scope["bench"]["entity"]
    recipes = [(recipe_key, recipe) for recipe_key, recipe in context["graph"]["recipes"].items()
               if recipe["bench"] == key and recipe["output"] and recipe["output"] not in context["bench_items"]
               and _recipe_visible(context, recipe_key)]
    recipes.sort(key=lambda pair: (_category(context, pair[1]["output"]).casefold(),
                                   _name(context, pair[0]).casefold(), pair[0]))
    return [{"output": _link(context, recipe_key), "category": _category(context, recipe["output"])}
            for recipe_key, recipe in recipes]


def _bench_summary(context, scope):
    key = scope["bench"]["entity"]
    index = context["graph"]["benches"][key]["main_ring"]
    recipe = _construction_recipe(context, key)
    if index is None or recipe is None:
        return None
    return {"ring": ring_label(context, index), "built_at": _made(context, context["graph"]["recipes"][recipe])}


def _bench_cost(context, scope):
    recipe_key = _construction_recipe(context, scope["bench"]["entity"])
    if recipe_key is None:
        return []
    recipe = context["graph"]["recipes"][recipe_key]
    return [{"count": _number(entry["count"]), "item": _link(context, entry["item"]), "how": _how(context, entry["item"])}
            for entry in sorted(recipe["ingredients"], key=lambda entry: (_name(context, entry["item"]).casefold(), entry["item"]))]


def _benches_overview(context, scope):
    result = []
    for bench in _benches(context, scope):
        key = bench["bench"]["entity"]
        recipe_key = _construction_recipe(context, key)
        ingredients = _ingredients(context, context["graph"]["recipes"][recipe_key]) if recipe_key else []
        result.append({"Bench": bench["bench"],
                       "Recipes": str(len(_bench_recipes(context, bench))), "Build cost": ingredients})
    return result


QUERIES = {
    "benches.overview": _benches_overview,
    "benches": _benches,
    "bench.summary": _bench_summary,
    "bench.cost": _bench_cost,
    "bench.recipes": _bench_recipes,
}
