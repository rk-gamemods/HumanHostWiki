"""Deterministic player guide queries over one snapshot's gameplay graph.

The context caches the graph, names, and item/combat cards. Query functions are pure:
they do not read files or mutate the supplied graph. All rings below are main
rings, the reliable acquisition ring rather than a chance near spawn.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
import math
import re

from .gameplay import graph
from .names import player_names
from .presentation import card


_METHODS = {"mined": "Mining", "harvested": "Gathering",
            "looted": "Scavenging", "merchant": "Buying"}
_ORDER = ("mined", "harvested", "crafted", "looted", "merchant", "dismantled")
_RAW = set(_METHODS)
_START_TAGS = {"MeleeWeapon", "Gun", "Bow", "工具"}
_WEAPON_FIELDS = {
    "MeleeWeapon": {"Damage": "/_baseDamage", "Execute": "/_baseBladeHitProb",
                    "Knockdown": "/_baseHitDownProb", "Durability": "/_BaseMaxDurability"},
    "Gun": {"Type": "/_GunType", "Damage": "/_baseDamage", "Fire rate": "/_fireRate",
            "Capacity": "/_maxMagCount", "Ammo": "/_ammoType"},
    "Bow": {"Arrow Damage": "/_baseDamage", "Speed": "/_ArrowSpeed", "Durability": "/_BaseMaxDurability"},
}
_AMMO_MATERIALS = ("Copper", "Steel", "Titanium", "Chrome", "Tungsten")
# Used only when the card has no registry/game note for that field.
_STAT_MEANINGS = {
    "Damage": "Base damage before quality bonuses.",
    "Execute": "Chance for a hit to trigger an execute attack.",
    "Knockdown": "Chance for a hit to knock the target down.",
    "Durability": "Maximum durability before quality bonuses.",
    "Type": "The gun's weapon class.",
    "Fire rate": "Shots per minute.",
    "Single Shot": "Fires one shot at a time.",
    "Capacity": "Rounds held before reloading.",
    "Ammo": "Ammunition the gun uses.",
    "Arrow Damage": "Arrow damage as a percentage of the arrow's base damage.",
    "Speed": "Arrow launch speed in metres per second.",
}


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


def build_context(rows, registry, game_text, snapshot) -> dict:
    """Build all guide joins once for a model snapshot."""
    rows = list(rows)
    by_key = dict(sorted((row["entity_key"], row) for row in rows))
    features = {}
    disabled_types = set()
    for name, feature in registry.get("features", {}).items():
        if name == "about":
            continue
        managers = [row for row in rows
                    if row["semantic"].get("facts", {}).get("manager_object") == feature["manager_object"]]
        active = len(managers) == 1 and managers[0]["semantic"]["facts"].get("manager_active") is True
        status = ("active" if active else "manager-object-missing" if not managers else
                  "ambiguous-manager-object" if len(managers) > 1 else "inactive")
        features[name] = {"manager_object": feature["manager_object"], "live": active, "status": status}
        if not active:
            disabled_types.update(feature["source_types"])
    gameplay = graph(rows, disabled_source_types=disabled_types)
    unreleased = {}
    for name, feature in registry.get("features", {}).items():
        if name == "about" or features[name]["live"]:
            continue
        for source_type in feature["source_types"]:
            for source in gameplay["disabled_sources"].get(source_type, []):
                item, via = source["item"], source["via"]
                if not gameplay["items"][item]["sources"]:
                    unreleased.setdefault(item, name)
                unreleased.setdefault(via, name)
                for link in by_key[via]["semantic"].get("relationships", []):
                    if link["predicate"] == "defined-by":
                        for target in link.get("targets", []):
                            unreleased.setdefault(target, name)
    names = player_names(rows, registry, game_text, gameplay)
    cards = {key: card(registry, "item", by_key[key]["semantic"], game_text)
             for key in gameplay["items"]}
    context = {"rows": by_key, "graph": gameplay, "names": names, "cards": cards,
               "features": features, "unreleased": unreleased,
               "registry": registry, "game_text": game_text,
               "snapshot": {key: str(value) for key, value in snapshot.items()}}
    guide_rules = registry.get("guides", {})
    context["harvest_patterns"] = [(re.compile(rule["match"], re.IGNORECASE), rule["family"])
                                   for rule in guide_rules.get("harvest_families", [])]
    patterns = [re.compile(pattern) for pattern in guide_rules.get("exclude_patterns", [])]
    context["excluded"] = {key for key, row in by_key.items()
                           if names[key]["name"] in guide_rules.get("exclude_names", [])
                           or any(pattern.search(name) for pattern in patterns
                                  for name in (names[key]["name"], row["semantic"].get("name") or ""))}
    context["bench_items"] = {bench["construction_item"] for bench in gameplay["benches"].values()
                              if bench.get("construction_item")}
    context["grass_fibers"] = {target for row in rows
                               for link in row["semantic"].get("relationships", [])
                               if link["predicate"] == "gathered-item" and link.get("field") == "/_PlantFiberIconRef"
                               for target in link.get("targets", [])}
    context["recipes_by_output"] = defaultdict(list)
    for key, recipe in gameplay["recipes"].items():
        if recipe["output"]:
            context["recipes_by_output"][recipe["output"]].append(key)
    context["bench_depths"] = _depths(context)
    context["starting_recipes"], context["starting_benches"] = _starting_closures(context)
    context["weapon_combat"], context["weapon_ammo"] = _weapon_joins(context)
    for key in sorted({key for keys in context["weapon_combat"].values() for key in keys}):
        cards[key] = card(registry, "combat-rule", by_key[key]["semantic"], game_text)
    return context


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


def _scenery_family(name):
    tokens = name.lower().split()
    if tokens and tokens[0] in {"sm", "prefab"}:
        tokens.pop(0)
    while tokens:
        # Numbered duct turns are model variants, just like var/lod suffixes.
        if len(tokens) >= 2 and tokens[-1] == "turn" and tokens[-2].isdigit():
            del tokens[-2:]
        elif re.fullmatch(r"(?:\d+|var\d+|lod\d+|[a-z])", tokens[-1]):
            tokens.pop()
        else:
            break
    tokens = [token for token in tokens if not re.fullmatch(r"(?:\d+|var\d+|lod\d+)", token)]
    return " ".join(tokens) or name.lower()


def _harvest_kind(context, item_key, source_key):
    family = _scenery_family(_name(context, source_key))
    # Registry rules decide first; a mineral node is a mineral by rule, not by sharing the item's name.
    for pattern, kind in context["harvest_patterns"]:
        if pattern.search(family):
            return kind, family
    # A source named after the item itself (a torch on a wall) is that item lying in the world.
    item_name = context["rows"][item_key]["semantic"]["name"]
    item_name = re.sub(r"(?:[_ ]*Icon)$", "", item_name, flags=re.IGNORECASE)
    item_words = {word.casefold() for word in re.split(r"[_\s]+", item_name) if word}
    if set(family.casefold().split()) <= item_words:
        return "ones found in the world", family
    return "other scenery", family


def other_scenery_sources(context):
    """Return distinct unmatched harvest sources and their model families."""
    unmatched = {}
    for item_key, item in context["graph"]["items"].items():
        if item_key in context["grass_fibers"]:
            continue
        for source in item["sources"]:
            if source["type"] == "harvested":
                kind, family = _harvest_kind(context, item_key, source["via"])
                if kind == "other scenery":
                    unmatched[source["via"]] = family
    return unmatched


def _harvest_runs(context, item_key, sources):
    kinds = defaultdict(set)
    for source in sources:
        kind, _ = _harvest_kind(context, item_key, source["via"])
        kinds[kind].add(source["via"])
    ordered = sorted(kinds, key=lambda name: (name == "other scenery", -len(kinds[name]), name))
    selected = [[_text(name)] for name in ordered[:3]]
    if len(ordered) > 3:
        remainder = len(ordered) - 3
        selected.append([_text(f"{remainder} more {'kind' if remainder == 1 else 'kinds'}")])
    return [_text("gathered from ")] + _join_runs(selected)


def _loot_runs(context, sources, ring):
    data = context["graph"]
    if ring is not None:
        sources = [source for source in sources if source["biome"] in _ring_biomes(context, ring)]
    if not sources:
        return []
    families = defaultdict(set)
    for source in sources:
        info = context["names"][source["via"]]
        # Family labels are collective nouns, not aliases for a single entity.
        family = info.get("family")
        families[(family or info["name"], None if family else source["via"])].add(source["via"])
    ordered = sorted(families, key=lambda pair: (-len(families[pair]), pair[0].casefold(), pair[1] or ""))
    chosen = ordered[:3]
    result = [_text("found in ")] + _limited_runs([
        [_link(context, key)] if key else [_text(name)] for name, key in ordered], more="places")
    ring_biomes = {source["biome"] for source in sources if source["biome"] in data["biomes"]
                  and data["biomes"][source["biome"]]["ring"] is not None}
    if ring is None and len(ring_biomes) >= 8:
        return result + [_text(", almost everywhere")]
    selected_sources = set().union(*(families[family] for family in chosen))
    places = defaultdict(set)
    for source in sources:
        if source["biome"] and (ring is not None or source["via"] in selected_sources):
            places[source["biome"]].add(source["via"])
    biomes = sorted(places, key=lambda key: (-len(places[key]), _name(context, key).casefold(), key))
    if biomes:
        result += [_text(" in ")] + _join_runs([[_link(context, key)] for key in biomes[:2]])
    return result


def how_runs(context, item_key, ring=None, limit=2, *, gathering_only=False) -> list:
    """Return text/entity runs for at most two lowercase acquisition phrases.

    Join the runs without additional punctuation. Phrases already contain their
    semicolon separator. ``ring`` is a main-ring index and scopes mining and
    source locations. Harvested scenery with no known biome counts in every
    ring. Sources from other rings are omitted; if none remain, use the
    unscoped phrase. Generic scenery/loot families and grass are prose;
    named items, containers, benches and biomes retain their entity links.
    Gathering-only phrases use located scenery so a ring lists what is there.
    """
    limit = min(2, max(0, limit))
    if not limit:
        return []
    gameplay = context["graph"]
    sources = _sources(context, item_key)
    if gathering_only:
        sources = [source for source in sources if source["type"] == "harvested" and source["biome"] is not None]
    if ring is not None:
        biomes = _ring_biomes(context, ring)
        sources = [source for source in sources if (
            gameplay["recipes"][source["via"]]["main_ring"] == ring if source["type"] == "crafted"
            else gameplay["items"][source["via"]]["main_ring"] == ring if source["type"] == "dismantled"
            else (source["type"] == "harvested" and source["biome"] is None) or source["biome"] in biomes)]
    phrases = []
    for kind in _ORDER:
        group = [source for source in sources if source["type"] == kind]
        if not group:
            continue
        result = []
        if kind == "mined":
            entry = _mining_entry(context, item_key, ring)
            if entry is None:
                continue
            chance, biome, _ = entry
            result = [_text("mined in "), _link(context, biome), _text(f" ({format_percent(chance)} of dig hits)")]
        elif kind == "harvested":
            if item_key in context["grass_fibers"]:
                result = [_text("cut from grass")]
            else:
                result = _harvest_runs(context, item_key, group)
        elif kind == "crafted":
            recipe = _crafted_recipe(context, group)
            bench = recipe["bench"]
            # A null bench on an incomplete recipe is not proof of hand crafting.
            if bench:
                result = [_text("crafted at the "), _link(context, bench)]
            elif recipe["main_ring"] is not None:
                result = [_text("crafted by hand")]
        elif kind == "looted":
            result = _loot_runs(context, group, ring)
        elif kind == "merchant":
            biomes = {source["biome"] for source in group if source["biome"]}
            if ring is not None:
                biomes &= _ring_biomes(context, ring)
            if biomes:
                biome = min(biomes, key=lambda key: (gameplay["biomes"][key]["ring"] is None,
                                                    gameplay["biomes"][key]["ring"] or 0, _name(context, key).casefold(), key))
                result = [_text("sold by merchants in "), _link(context, biome)]
        else:
            result = [_text("salvaged from ")] + _named_runs(context, [source["via"] for source in group])
        if result:
            phrases.append(result)
        if len(phrases) >= limit:
            break
    if not phrases and ring is not None:
        return how_runs(context, item_key, limit=limit, gathering_only=gathering_only)
    return _join_runs(phrases, separator="; ", last="; ")


def _mining_entry(context, item_key, ring=None):
    entries = [(entry["chance_per_hit"], biome, entry["block_set"])
               for biome, data in context["graph"]["biomes"].items() if _visible(context, biome)
               for entry in data["mined"] if entry["item"] == item_key and _visible(context, entry["block_set"])
               and (ring is None or biome in _ring_biomes(context, ring))]
    return min(entries, key=lambda e: (-e[0], _name(context, e[1]).casefold(), e[2])) if entries else None


def _crafted_recipe(context, sources):
    recipes = context["graph"]["recipes"]
    keys = [source["via"] for source in sources if source["type"] == "crafted"]
    if not keys:
        return None
    key = min(keys, key=lambda key: (recipes[key]["main_ring"] is None, recipes[key]["main_ring"] or 0,
                                    _depth_order(context, recipes[key]["bench"]), _name(context, key).casefold(), key))
    return recipes[key]


def how_short(context, item_key) -> list:
    """Return up to three compact acquisition parts as linked runs for tables.

    Parts follow the usual source order and use `` · `` separators. Lists use
    :func:`how_runs` for full source details; the compact vocabulary covers
    mining, crafting, loot, merchants and salvage.
    """
    sources = _sources(context, item_key)
    parts = []
    for kind in _ORDER:
        group = [source for source in sources if source["type"] == kind]
        if not group:
            continue
        part = []
        if kind == "mined":
            entry = _mining_entry(context, item_key)
            if entry:
                part = [_text("Mined in "), _link(context, entry[1])]
        elif kind == "crafted":
            recipe = _crafted_recipe(context, group)
            if recipe["bench"]:
                part = [_link(context, recipe["bench"])]
            elif recipe["main_ring"] is not None:
                part = [_text("By hand")]
        elif kind == "looted":
            places = defaultdict(set)
            for source in group:
                if source["biome"]:
                    places[source["biome"]].add(source["via"])
            if sum(context["graph"]["biomes"][key]["ring"] is not None for key in places) >= 8:
                part = [_text("Loot, almost everywhere")]
            elif places:
                biomes = sorted(places, key=lambda key: (-len(places[key]), _name(context, key).casefold(), key))
                part = [_text("Loot in ")] + _join_runs([[_link(context, key)] for key in biomes[:2]])
            else:
                part = [_text("Loot")]
        elif kind == "merchant":
            part = [_text("Merchants")]
        elif kind == "dismantled":
            part = [_text("Salvage")]
        if part:
            parts.append(part)
        if len(parts) == 3:
            break
    return _join_runs(parts, separator=" · ", last=" · ")


def _how(context, item_key, ring=None):
    return {"runs": how_runs(context, item_key, ring)}


def method(context, item_key) -> str:
    """Choose Mining, Gathering, Scavenging or Buying for a raw material.

    Crafting and dismantling do not define raw material groups. Raise ValueError
    for an item with no direct material source instead of inventing a method.
    """
    kinds = {source["type"] for source in context["graph"]["items"][item_key]["sources"]}
    for kind, label in _METHODS.items():
        if kind in kinds:
            return label
    raise ValueError(f"Item has no raw material source: {item_key}")


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


def _biome_value(context, ring):
    links = [_link(context, key) for key in sorted(ring["biome_keys"], key=lambda key: (_name(context, key).casefold(), key))
             if _visible(context, key)]
    return (links[0] if len(links) == 1 else links) if links else "Unknown biome"


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


def _made(context, recipe):
    bench = recipe["bench"]
    return {"runs": [_text("at the "), _link(context, bench)] if bench else [_text("by hand")]}


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


def _targets(context, key, predicate, field=None):
    return {target for link in context["rows"][key]["semantic"].get("relationships", [])
            if (predicate is None or link["predicate"] == predicate) and (field is None or link.get("field") == field)
            for target in link.get("targets", []) if target in context["rows"]}


def _weapon_joins(context):
    """Follow item model -> combat component -> ammo enum -> ammunition items.

    Match names' combat-user association through direct relationships, a model
    asset's components, or a shared provenance game object. Bow Speed uses the
    joined combat card's /_ArrowSpeed; no item-stat or name-match fallback.
    The ammo enum's ammunition-item links implement Item_Slot_Mgr's address
    rule (adapters/coded_values.py:235-257), including handmade ammo variants.
    Never infer an ammo item or gun type by matching a weapon's display name.
    """
    combats, ammunition = {}, {}
    by_object = defaultdict(set)
    for key, row in context["rows"].items():
        if row["semantic"]["kind"] == "combat-rule":
            for identity in row.get("provenance", {}).get("game_objects", []):
                by_object[identity].add(key)
    for key in context["graph"]["items"]:
        if _tag(context, key) not in _WEAPON_FIELDS:
            continue
        direct = _targets(context, key, None)
        models = {target for target in direct if context["rows"][target]["semantic"]["kind"] == "asset"}
        candidates = direct | {component for model in models for component in _targets(context, model, None)}
        for identity in context["rows"][key].get("provenance", {}).get("game_objects", []):
            candidates.update(by_object[identity])
        combats[key] = sorted(candidate for candidate in candidates
                              if context["rows"][candidate]["semantic"]["kind"] == "combat-rule")
        ammo_types = {target for combat in combats[key]
                      for target in _targets(context, combat, "coded-value", "/_AmmoType")}
        ammunition[key] = sorted({item for ammo_type in ammo_types
                                  for item in _targets(context, ammo_type, "ammunition-item")
                                  if item in context["graph"]["items"]},
                                 key=lambda item: (_name(context, item).casefold(), item))
    return combats, ammunition


def _weapon_stats(context, key, pointer):
    owners = context["weapon_combat"][key] if pointer in {"/_GunType", "/_ArrowSpeed"} else [key]
    return [(owner, stat) for owner in owners for stat in (context["cards"].get(owner) or {}).get("stats", [])
            if stat["field"] == pointer]


def _weapon_stat(context, key, pointer):
    # A card flag has no numeric display: its label is the entire visible stat.
    values = {stat["label"] if stat["display"] is None else stat["display"]
              for _, stat in _weapon_stats(context, key, pointer)}
    return next(iter(values)) if len(values) == 1 else ""


def _weapon_keys(context, tag):
    keys = [key for key in context["graph"]["items"] if _tag(context, key) == tag and _visible(context, key)]

    def order(key):
        ring = context["graph"]["items"][key]["main_ring"]
        # Sort the displayed damage, so equal visible values tie on name.
        display = _weapon_stat(context, key, "/_baseDamage")
        damage = Decimal(display.replace(",", "").removesuffix("%")) if display else Decimal(0)
        return ring is None, ring or 0, -damage, _name(context, key).casefold(), key

    return sorted(keys, key=order)


def _weapons(context, tag):
    result = []
    for key in _weapon_keys(context, tag):
        row = {"Weapon": _link(context, key)}
        for column, pointer in _WEAPON_FIELDS[tag].items():
            if column == "Ammo":
                base = _base_ammo(context, key)
                row[column] = _link(context, base) if base else ""
            else:
                row[column] = _weapon_stat(context, key, pointer)
        row["How to get it"] = {"runs": how_short(context, key)}
        result.append(row)
    return result


def _weapons_melee(context, scope):
    return _weapons(context, "MeleeWeapon")


def _weapons_guns(context, scope):
    return _weapons(context, "Gun")


def _weapons_bows(context, scope):
    return _weapons(context, "Bow")


def weapon_column_labels(context) -> dict:
    """Report actual card labels by guide column, for wording review."""
    result = defaultdict(set)
    for tag, fields in _WEAPON_FIELDS.items():
        for key in _weapon_keys(context, tag):
            for column, pointer in fields.items():
                result[column].update(stat["label"] for _, stat in _weapon_stats(context, key, pointer))
    return {column: sorted(values) for column, values in sorted(result.items())}


def _weapons_stat_labels(context, scope):
    result = []
    seen = set()
    for tag, fields in _WEAPON_FIELDS.items():
        for column, pointer in fields.items():
            meanings = defaultdict(set)
            fallbacks = {}
            for key in _weapon_keys(context, tag):
                for owner, stat in _weapon_stats(context, key, pointer):
                    notes = [note["text"] for note in context["cards"][owner]["notes"] if note["field"] == pointer]
                    meanings[stat["label"]].update(notes)
                    fallbacks[stat["label"]] = _STAT_MEANINGS[
                        "Single Shot" if pointer == "/_fireRate" and stat["display"] is None else column]
            for label, notes in sorted(meanings.items()):
                if label not in seen:
                    seen.add(label)
                    meaning = " ".join(sorted(notes)) if notes else fallbacks[label]
                    if meaning.startswith(label + ":"):
                        meaning = meaning[len(label) + 1:].lstrip()
                    result.append({"label": label, "meaning": meaning})
    return result


def _base_ammo(context, gun_key):
    keys = [key for key in context["weapon_ammo"][gun_key] if _visible(context, key)]
    return min(keys, key=lambda key: (any(source["type"] == "crafted" for source in context["graph"]["items"][key]["sources"]),
                                      _name(context, key).casefold(), key)) if keys else None


def _handmade_ammo_runs(context, keys):
    """Group crafted ammo variants by bench, using their named materials."""
    by_bench = defaultdict(list)
    for key in sorted(keys, key=lambda key: (_name(context, key).casefold(), key)):
        recipe = _crafted_recipe(context, _sources(context, key))
        names = (_name(context, key), context["rows"][key]["semantic"].get("name") or "")
        material = next((material for material in _AMMO_MATERIALS
                         if any(f"({material})" in name for name in names)), None)
        if recipe and material:
            by_bench[recipe["bench"]].append((_AMMO_MATERIALS.index(material), material, key))
    parts = []
    for bench, variants in sorted(by_bench.items(), key=lambda pair: (min(pair[1]), pair[0] or "")):
        material_runs = _join_runs([[_link(context, key, material)] for _, material, key in sorted(variants)])
        ending = [_text(" rounds at the "), _link(context, bench)] if bench else [_text(" rounds by hand")]
        parts.append([_text("handmade ")] + material_runs + ending)
    return _join_runs(parts, separator="; ", last="; ")


def _weapons_ammo(context, scope):
    groups = defaultdict(set)
    for gun in _weapon_keys(context, "Gun"):
        base = _base_ammo(context, gun)
        if base:
            groups[base].update(key for key in context["weapon_ammo"][gun] if key != base and _visible(context, key))
    result = []
    for base, variants in sorted(groups.items(), key=lambda pair: (_name(context, pair[0]).casefold(), pair[0])):
        runs = how_runs(context, base)
        handmade = _handmade_ammo_runs(context, variants)
        if handmade:
            runs = runs + ([_text("; ")] if runs else []) + handmade
        result.append({"ammo": _link(context, base), "how": {"runs": runs}})
    return result


def _weapons_variants(context, scope):
    groups = defaultdict(list)
    for tag in _WEAPON_FIELDS:
        for key in _weapon_keys(context, tag):
            groups[context["rows"][key]["semantic"].get("name", "").strip().casefold()].append(key)
    result = []
    for base, keys in sorted(groups.items()):
        if not base or len(keys) < 2:
            continue
        keys.sort(key=lambda key: (_name(context, key).casefold(), key))
        phrases = []
        acquisition = [how_runs(context, key, limit=1) for key in keys]
        different_stat = None
        if all(runs == acquisition[0] for runs in acquisition):
            fields = dict.fromkeys(pointer for tag in _WEAPON_FIELDS for pointer in _WEAPON_FIELDS[tag].values())
            for pointer in fields:
                values = [_weapon_stat(context, key, pointer) for key in keys]
                if all(values) and len(set(values)) > 1:
                    different_stat = pointer
                    break
        for index, key in enumerate(keys):
            kinds = {source["type"] for source in context["graph"]["items"][key]["sources"]}
            prefix = [_text("one is " if index == 0 else "the other is ")] if len(keys) == 2 else [_link(context, key), _text(" is ")]
            if different_stat:
                label = _weapon_stats(context, key, different_stat)[0][1]["label"]
                value = _weapon_stat(context, key, different_stat)
                subject = "one" if index == 0 else "the other"
                phrases.append([_text(f"{subject} has {label} {value}")] if len(keys) == 2
                               else [_link(context, key), _text(f" has {label} {value}")])
                continue
            how = [_text("only found as loot")] if kinds == {"looted"} else acquisition[index]
            phrases.append(prefix + how if how else [_link(context, key), _text(" has no recorded acquisition source")])
        result.append({"name": [_link(context, key) for key in keys],
                       "difference": {"runs": _join_runs(phrases, separator="; ", last="; ")}})
    return result


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
    "start.first_biome": _start_first_biome, "start.materials": _start_materials,
    "start.gathering_intro": _start_gathering_intro,
    "start.hand_intro": _start_hand_intro, "start.benches_intro": _start_benches_intro,
    "start.hand_recipes": _start_hand_recipes, "start.benches": _start_benches,
    "start.tools_and_weapons": _start_tools, "world.rings": _world_rings,
    "world.near_spawn": _world_near_spawn, "world.zombie_scaling": _world_zombie_scaling,
    "world.loot_quality_scaling": _world_loot_scaling, "rings": _rings,
    "ring.span": _ring_span, "ring.new_materials": _ring_materials,
    "ring.easier_gathering": _ring_easier_gathering,
    "ring.new_recipes": _ring_recipes, "ring.new_benches": _ring_benches,
    "ring.exclusive_loot": _ring_exclusive_loot, "ring.merchant_summary": _ring_merchants,
    "weapons.stat_labels": _weapons_stat_labels, "weapons.melee": _weapons_melee,
    "weapons.guns": _weapons_guns, "weapons.bows": _weapons_bows,
    "weapons.ammo_sources": _weapons_ammo, "weapons.variants": _weapons_variants,
    "benches.overview": _benches_overview, "benches": _benches,
    "bench.summary": _bench_summary, "bench.cost": _bench_cost, "bench.recipes": _bench_recipes,
}
