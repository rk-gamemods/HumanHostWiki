"""Answer where items come from and group their acquisition sources."""

from __future__ import annotations

from collections import defaultdict
import re
from .guide_query_shared import (
    _METHODS, _depth_order, _join_runs, _limited_runs,
    _link, _name, _named_runs, _ring_biomes,
    _sources, _text, _visible, format_percent,
)


_ORDER = ("mined", "harvested", "crafted", "looted", "merchant", "dismantled")


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
