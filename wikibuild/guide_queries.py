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

from .guide_query_acquisition import (
    _ORDER, _crafted_recipe, _harvest_kind, _harvest_runs,
    _how, _loot_runs, _mining_entry, _scenery_family,
    how_runs, how_short, method, other_scenery_sources,
)
from .guide_query_biome_progression import (
    _positive_fact, _ring_benches, _ring_easier_gathering, _ring_exclusive_loot,
    _ring_materials, _ring_merchants, _ring_recipes, _ring_span,
    _rings, _world_loot_scaling, _world_near_spawn, _world_rings,
    _world_zombie_scaling,
)
from .guide_query_crafting_benches import (
    _bench_cost, _bench_recipes, _bench_summary, _benches,
    _benches_overview,
)
from .guide_query_getting_started import (
    _START_TAGS, _card_stat, _start_benches, _start_benches_intro,
    _start_first_biome, _start_gathering_intro, _start_hand_intro, _start_hand_recipes,
    _start_materials, _start_tools, _starting_closures,
)
from .guide_query_shared import (
    _METHODS, _RAW, _bench_depth, _bench_visible,
    _biome_value, _category, _construction_recipe, _depth_order,
    _depths, _ingredients, _join_runs, _limited_runs,
    _link, _made, _name, _named_runs,
    _number, _raw, _recipe_visible, _ring_biomes,
    _sources, _tag, _text, _visible,
    format_distance, format_percent, ring_label, used_in,
)
from .guide_query_weapons import (
    _AMMO_MATERIALS, _STAT_MEANINGS, _WEAPON_FIELDS, _base_ammo,
    _handmade_ammo_runs, _targets, _weapon_joins, _weapon_keys,
    _weapon_stat, _weapon_stats, _weapons, _weapons_ammo,
    _weapons_bows, _weapons_guns, _weapons_melee, _weapons_stat_labels,
    _weapons_variants, weapon_column_labels,
)
from .guide_query_getting_started import QUERIES as GETTING_STARTED_QUERIES
from .guide_query_biome_progression import QUERIES as BIOME_PROGRESSION_QUERIES
from .guide_query_weapons import QUERIES as WEAPON_QUERIES
from .guide_query_crafting_benches import QUERIES as CRAFTING_BENCH_QUERIES


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


QUERIES = {
    **GETTING_STARTED_QUERIES,
    **BIOME_PROGRESSION_QUERIES,
    **WEAPON_QUERIES,
    **CRAFTING_BENCH_QUERIES,
}
