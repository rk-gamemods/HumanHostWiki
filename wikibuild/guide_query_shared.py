"""Shared visibility, formatting, recipe and bench joins for player guides."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


_METHODS = {"mined": "Mining", "harvested": "Gathering",
            "looted": "Scavenging", "merchant": "Buying"}
_RAW = set(_METHODS)


def _number(value, places=0):
    rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return (format(rounded, "f").rstrip("0").rstrip(".") or "0") if places else format(rounded, "f")


def format_distance(metres) -> str:
    """Format world units as metres or kilometres, rounding half up.

    A no-break space keeps the number and its unit on one line.
    """
    if Decimal(str(metres)) < 1000:
        return f"{_number(metres)} m"
    return f"{_number(Decimal(str(metres)) / 1000, 1)} km"


def format_percent(fraction) -> str:
    """Format a fraction as a percentage with at most two decimal places."""
    return f"{_number(Decimal(str(fraction)) * 100, 2)}%"


def _name(context, key):
    return context["names"][key]["name"]


def _link(context, key, text=None):
    return {"text": _name(context, key) if text is None else text, "entity": key}


def _visible(context, key):
    """Filter guide records without changing the underlying gameplay graph."""
    if key not in context["rows"] or key in context["excluded"]:
        return False
    item = context["graph"]["items"].get(key)
    return item is None or bool(item["sources"])


def _recipe_visible(context, key):
    """Omit a recipe as a whole rather than present an incomplete ingredient cost."""
    recipe = context["graph"]["recipes"][key]
    return (_visible(context, key) and _visible(context, recipe["output"])
            and (recipe["bench"] is None or _visible(context, recipe["bench"]))
            and all(_visible(context, entry["item"]) for entry in recipe["ingredients"]))


def _bench_visible(context, key):
    item = context["graph"]["benches"][key].get("construction_item")
    return _visible(context, key) and _visible(context, item) and _construction_recipe(context, key) is not None


def _sources(context, item_key):
    if not _visible(context, item_key):
        return []
    return [source for source in context["graph"]["items"][item_key]["sources"]
            if _visible(context, source["via"])
            and (not source["biome"] or _visible(context, source["biome"]))
            and (not source["bench"] or _bench_visible(context, source["bench"]))
            and (source["type"] != "crafted" or _recipe_visible(context, source["via"]))]


def ring_label(context, index) -> str:
    """Return the table label for a reliable acquisition ring."""
    ring = next(r for r in context["graph"]["rings"] if r["index"] == index)
    biomes = sorted((_name(context, key) for key in ring["biome_keys"]), key=str.casefold)
    # The game counts biomes from 1 ("There are 10 biomes in total", "Biome 10 = max loot quality").
    return f"Biome {index + 1} ({' and '.join(biomes)})" if biomes else f"Biome {index + 1}"


def used_in(context, item_key) -> list:
    """Return distinct visible consuming recipes, sorted by player name."""
    recipes = [key for key in context["graph"]["items"][item_key]["used_in"] if _recipe_visible(context, key)]
    return [_link(context, key) for key in sorted(recipes, key=lambda k: (_name(context, k).casefold(), k))]


def _ring_biomes(context, index):
    return set(next(r["biome_keys"] for r in context["graph"]["rings"] if r["index"] == index))


def _text(value):
    return {"text": value}


def _join_runs(groups, separator=", ", last=" and "):
    result = []
    for index, runs in enumerate(groups):
        if index:
            result.append(_text(last if index == len(groups) - 1 else separator))
        result.extend(runs)
    return result


def _named_runs(context, keys, limit=3):
    keys = sorted({key for key in keys if _visible(context, key)}, key=lambda key: (_name(context, key).casefold(), key))
    return _join_runs([[_link(context, key)] for key in keys[:limit]])


def _limited_runs(groups, more="more", limit=3):
    """Join a capped list with one conjunction, including its remainder."""
    selected = groups[:limit]
    if len(groups) > limit:
        count = len(groups) - limit
        suffix = ("other place" if count == 1 else "other places") if more == "places" else more
        selected = [*selected, [_text(f"{count} {suffix}")]]
    return _join_runs(selected)


def _raw(context, key):
    item = context["graph"]["items"][key]
    return bool(item["used_in"] and any(source["type"] in _RAW for source in item["sources"]))


def _category(context, key):
    tag = _tag(context, key)
    return context["registry"]["glossaries"]["item-category"].get(str(tag)) or "Other"


def _tag(context, key):
    facts = context["rows"][key]["semantic"].get("facts", {})
    return (context["rows"][key]["semantic"].get("fact_labels") or {}).get("/_Tag", facts.get("_Tag"))


def _ingredients(context, recipe):
    return [_link(context, entry["item"], f"{_number(entry['count'])} × {_name(context, entry['item'])}")
            for entry in sorted(recipe["ingredients"], key=lambda e: (_name(context, e["item"]).casefold(), e["item"]))
            if _visible(context, entry["item"])]


def _depths(context):
    """Resolve minimum construction depths without recursively entering cycles."""
    data = context["graph"]
    items = {key: 0 for key in data["items"] if _raw(context, key)}
    benches = {None: 0}

    def lower(values, key, candidate):
        if key not in values or candidate < values[key]:
            values[key] = candidate
            return True
        return False

    changed = True
    while changed:
        changed = False
        for recipe in data["recipes"].values():
            if recipe["main_ring"] is None or recipe["bench"] not in benches:
                continue
            costs = [items.get(entry["item"]) for entry in recipe["ingredients"]]
            if all(depth is not None for depth in costs):
                changed |= lower(items, recipe["output"], max([benches[recipe["bench"]], *costs]))
        for key, bench in data["benches"].items():
            for recipe_key in context["recipes_by_output"].get(bench.get("construction_item"), []):
                recipe = data["recipes"][recipe_key]
                costs = [items.get(entry["item"]) for entry in recipe["ingredients"]]
                if recipe["main_ring"] is not None and all(depth is not None for depth in costs):
                    changed |= lower(benches, key, 1 + max(costs, default=0))
    return benches


def _bench_depth(context, bench):
    return context["bench_depths"].get(bench)


def _depth_order(context, bench):
    depth = _bench_depth(context, bench)
    return depth is None, depth or 0


def _construction_recipe(context, bench_key):
    """Choose a build recipe by main ring, then bench depth and player name."""
    graph = context["graph"]
    keys = context["recipes_by_output"].get(graph["benches"][bench_key].get("construction_item"), [])
    keys = [key for key in keys if _recipe_visible(context, key)]
    if not keys:
        return None
    return min(keys, key=lambda key: (graph["recipes"][key]["main_ring"] is None,
                                      graph["recipes"][key]["main_ring"] or 0,
                                      _depth_order(context, graph["recipes"][key]["bench"]),
                                      _name(context, key).casefold(), key))


def _biome_value(context, ring):
    links = [_link(context, key) for key in sorted(ring["biome_keys"], key=lambda key: (_name(context, key).casefold(), key))
             if _visible(context, key)]
    return (links[0] if len(links) == 1 else links) if links else "Unknown biome"


def _made(context, recipe):
    bench = recipe["bench"]
    return {"runs": [_text("at the "), _link(context, bench)] if bench else [_text("by hand")]}
