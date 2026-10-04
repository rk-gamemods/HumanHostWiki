"""Answer weapon stats, ammunition sources and variant differences."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from .guide_query_acquisition import (
    _crafted_recipe, how_runs, how_short,
)
from .guide_query_shared import (
    _join_runs, _link, _name, _sources,
    _tag, _text, _visible,
)


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


QUERIES = {
    "weapons.stat_labels": _weapons_stat_labels,
    "weapons.melee": _weapons_melee,
    "weapons.guns": _weapons_guns,
    "weapons.bows": _weapons_bows,
    "weapons.ammo_sources": _weapons_ammo,
    "weapons.variants": _weapons_variants,
}
