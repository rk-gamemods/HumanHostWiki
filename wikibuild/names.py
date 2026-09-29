"""Pure, deterministic player names for one projected model snapshot."""

from collections import defaultdict
import re

from . import presentation
from .lint import jargon


def _links(row, predicate=None):
    return (link for link in row["semantic"].get("relationships", [])
            if predicate is None or link.get("predicate") == predicate)


def _targets(row, predicate):
    return {target for link in _links(row, predicate) for target in link.get("targets", [])}


def _humanize(value, *, scenery=False):
    # Model and detail-level tokens name a file, not a thing; variant numbers stay.
    # They are dropped before the case split (odd casing such as "lOD0") and after it ("PrefabPine").
    if scenery:
        # A trailing "$2" is Unity's suffix for a duplicate object name.
        parts = re.sub(r"[_/\\-]+", " ", re.sub(r"\$\d+$", "", str(value))).split()
        parts = [part for part in parts if part.casefold() not in {"sm", "prefab"}]
        if parts and re.fullmatch(r"lod\d+", parts[-1], re.IGNORECASE):
            parts.pop()
        value = " ".join(parts)
    value = re.sub(r"([a-z0-9])([A-Z])|([A-Z])([A-Z][a-z])", r"\1\3 \2\4", str(value))
    words = re.sub(r"[_/\\-]+", " ", value).split()
    if len(words) >= 2 and [part.casefold() for part in words[-2:]] == ["hit", "set"]:
        words = words[:-2]
    if scenery:
        words = [word for word in words if word.casefold() not in {"sm", "prefab"}]
        if words and re.fullmatch(r"lod\d+", words[-1], re.IGNORECASE):
            words.pop()
    return " ".join(words).capitalize() or "Unnamed record"


def _creature(name):
    match = re.search(r"Z_Man_(\d+)", name)
    if match:
        return f"Male zombie (type {int(match[1])})"
    match = re.search(r"Z_Woman_(\d+)", name)
    if match:
        return f"Female zombie (type {int(match[1])})"
    if "ZBoss" in name:
        match = re.search(r"(\d+)(?!.*\d)", name)
        return f"Boss zombie (type {int(match[1])})" if match else "Boss zombie"
    return _humanize(name)


def _text_target(row, by_key, by_source, component, predicate=None):
    """A unique English text target, either a resolved link or evidence object."""
    candidates = []
    for link in _links(row, predicate):
        if len(link.get("targets", [])) == 1 and not link.get("gaps"):
            candidates.extend(by_key[key] for key in link["targets"] if key in by_key)
    for evidence in row.get("provenance", {}).get("evidence", []):
        candidates.extend(by_source.get(evidence.get("object"), []))
    return [target for target in candidates if target.get("provenance", {}).get("component") == component]


def _tooltip(row, by_key, by_source):
    candidates = _text_target(row, by_key, by_source, {"assembly": "Language", "class": "Tooltip_Text"}, "tooltip-text")
    return next(iter({candidate["semantic"]["name"]: candidate for candidate in candidates}.values()), None) if len({candidate["entity_key"] for candidate in candidates}) == 1 else None


def _shape(row, by_key, by_source):
    if row["semantic"].get("facts", {}).get("_Tag") != "BuildMat":
        return None
    target = _tooltip(row, by_key, by_source)
    if target is None:
        return None
    title = target["semantic"]["name"]
    # The two numeric fields identify the material family, not the shape.
    # Internal material names can differ from English (Rust_Iron is Scrap Metal).
    match = re.fullmatch(
        r"\d+_\d+_(Block(?:_Small)?(?:_1\.\d+)?|"
        r"Triangle(?:_CornerS?|_Small(?:_1\.\d+)?|_1\.\d+)?|"
        r"Half_Cylinder_[SML]|Pyramid_(?:Squat|Tall)|Steps(?:_Curved)?|Cuboid)"
        r"_.+_Tooltip", title)
    if not match:
        # Timber pieces carry lengths, whose decimal point is not a fraction.
        dimension = re.fullmatch(r"Plank_(?:Pillar|Wall)_(\d+(?:\.\d+)?)m_Tooltip", title)
        return f"{dimension[1]} m" if dimension else None
    shape = _humanize(match[1])
    sizes = {"l": "large", "m": "medium", "s": "small"}
    shape = re.sub(r"(?<= )[lms]$", lambda letter: sizes[letter[0]], shape)
    return re.sub(r"(?<=\d)\.(?=\d)", "/", shape)


def _construction_item(row, items_by_tooltip, by_key):
    """Use a unique BuildMat tooltip title, checking a model link when present."""
    candidates = items_by_tooltip.get(row["semantic"].get("name"), set())
    if len(candidates) != 1:
        return None
    item = by_key[next(iter(candidates))]
    model_targets = {target for link in item.get("provenance", {}).get("relationships", [])
                     if link.get("predicate") == "model"
                     for target in link.get("target_source_ids",
                                            [link.get("target_source_id")]) if target}
    game_objects = set(row.get("provenance", {}).get("game_objects", []))
    if model_targets and game_objects and model_targets.isdisjoint(game_objects):
        return None
    return item["entity_key"]


def _biome_name(row, sources):
    original = row["semantic"]["name"]
    return sources["biome"]["names"].get(original, _humanize(original))


def _bundle_name(row):
    source_id = row.get("provenance", {}).get("source_id", "")
    match = re.search(r"(?:^|/)bundles/([^/]+)\.bundle(?:::|$)", source_id)
    return match[1] if match else ""


def _loot_family_names(by_key, sources, graph):
    """Join ordered bundle families to the graph's recorded loot geography.

    Repeated biome entities share the registry's player name. A bundle may
    span both winter biomes; retain both instead of choosing an arbitrary one.
    """
    places = defaultdict(set)
    for item in graph.get("items", {}).values():
        for source in item.get("sources", []):
            biome = by_key.get(source.get("biome"))
            if source.get("type") == "looted" and biome is not None:
                places[source["via"]].add(_biome_name(biome, sources))

    spec = sources["loot-source"]
    result = {}
    for key, row in sorted(by_key.items()):
        if row["semantic"]["kind"] != "loot-source":
            continue
        bundle = _bundle_name(row)
        if not bundle:
            continue
        family = next((rule for rule in spec["families"]
                       if re.search(rule["match"], bundle)), None)
        if family is None:
            continue
        biome = " and ".join(sorted(places[key]))
        template = spec["record_name"] if biome else spec["no_biome_name"]
        result[key] = {"name": template.format(singular=family["singular"], biome=biome),
                       "source": "wiki", "rule": "loot-family", "family": family["family"]}
    return result


def _recipe_order(row):
    indexed = []
    for link in _links(row, "consumes-item-asset"):
        match = re.fullmatch(r"/matsData/(\d+)/matIcon", link.get("field", ""))
        if match and len(link.get("targets", [])) == 1:
            indexed.append((int(match[1]), link["targets"][0]))
    return [target for _, target in sorted(indexed)]


def _stat_candidates(keys, rows, registry, game_text):
    cards = {key: presentation.card(registry, rows[key]["semantic"]["kind"],
                                    rows[key]["semantic"], game_text) for key in keys}
    positions = sorted({(stat["order"], stat["field"]) for card in cards.values() if card
                        for stat in card["stats"]})
    for order, field in positions:
        stats = {key: next((stat for stat in (cards[key] or {}).get("stats", [])
                            if (stat["order"], stat["field"]) == (order, field)), None)
                 for key in keys}
        if any(stat is not None and not isinstance(stat.get("display"), str)
               for stat in stats.values()):
            continue
        displays = {key: None if stat is None else stat["display"] for key, stat in stats.items()}
        if len(set(map(str, displays.values()))) > 1:
            return {key: f"{stat['label']} {stat['display']}" for key, stat in stats.items()
                    if stat and stat["display"] is not None}
    return {}


def _disambiguate(result, rows, registry, game_text, graph, by_key, by_source):
    rules = [rule["id"] for rule in registry["names"]["rules"]]
    for rule in rules:
        groups = defaultdict(list)
        for key, value in result.items():
            sem = rows[key]["semantic"]
            groups[(sem["topic"], sem["kind"], value["name"])].append(key)
        for (_, kind, base), keys in sorted(groups.items()):
            if len(keys) < 2:
                continue
            keys.sort()
            suffixes = {}
            if rule == "acquisition" and kind == "item":
                for key in keys:
                    types = {entry["type"] for entry in graph.get("items", {}).get(key, {}).get("sources", [])}
                    if "crafted" in types:
                        suffixes[key] = "crafted"
                    elif types and types <= {"looted", "merchant"}:
                        suffixes[key] = "loot"
            elif rule == "building-shape" and kind == "item":
                suffixes = {key: shape for key in keys if (shape := _shape(rows[key], by_key, by_source))}
            elif rule == "distinguishing-stat":
                suffixes = _stat_candidates(keys, rows, registry, game_text)
            elif rule == "ordinal":
                if kind in {"building-piece", "construction-rule"}:
                    topic = rows[keys[0]]["semantic"]["topic"]
                    occupied = {value["name"] for other, value in result.items()
                                if other not in keys and rows[other]["semantic"]["topic"] == topic
                                and rows[other]["semantic"]["kind"] == kind}
                    index = 1
                    for key in keys:
                        while f"{base} (variant {index})" in occupied:
                            index += 1
                        suffixes[key] = f"variant {index}"
                        occupied.add(f"{base} (variant {index})")
                        index += 1
                else:
                    suffixes = {key: f"variant {index}" for index, key in enumerate(keys, 1)}
            if not suffixes:
                continue
            candidates = {key: f"{base} ({suffix})" for key, suffix in suffixes.items()}
            counts = defaultdict(int)
            for candidate in candidates.values():
                counts[candidate] += 1
            for key, candidate in candidates.items():
                if counts[candidate] == 1:
                    result[key] = {**result[key], "name": candidate, "rule": rule}


def _compute(rows, registry, game_text, graph, audit=None):
    rows = list(rows)
    by_key = {row["entity_key"]: row for row in rows}
    if len(by_key) != len(rows):
        raise ValueError("Duplicate snapshot entity key")
    result = {}
    sources = registry["names"]["sources"]
    loot_names = _loot_family_names(by_key, sources, graph)
    inbound = defaultdict(set)
    by_object = defaultdict(set)
    by_source = defaultdict(list)
    for key, row in by_key.items():
        by_source[row.get("provenance", {}).get("source_id")].append(row)
        for link in _links(row):
            for target in link.get("targets", []):
                inbound[target].add(key)
        for identity in row.get("provenance", {}).get("game_objects", []):
            by_object[identity].add(key)

    items_by_tooltip = defaultdict(set)
    for key, row in by_key.items():
        if (row["semantic"]["kind"] == "item"
                and row["semantic"].get("facts", {}).get("_Tag") == "BuildMat"):
            tooltip = _tooltip(row, by_key, by_source)
            if tooltip:
                title = tooltip["semantic"].get("name", "")
                if title.endswith("_Tooltip"):
                    items_by_tooltip[title[:-len("_Tooltip")]].add(key)

    def put(key, name, source="game", rule=None):
        result[key] = {"name": name, "source": source, "rule": rule}

    humanized_keys = set()

    def clean_identifiers():
        for entity, value in result.items():
            if any(hit["rule"] == "identifier" for hit in jargon(value["name"])):
                replacement = _humanize(value["name"])
                if replacement != value["name"]:
                    humanized_keys.add(entity)
                value.update(name=replacement, source="wiki", rule="humanize")

    for key in sorted(by_key):
        row = by_key[key]
        sem = row["semantic"]
        kind, original = sem["kind"], sem.get("name") or ""
        if kind in {"recipe", "combat-rule", "loot-table"}:
            continue
        if kind == "workbench":
            candidates = _text_target(row, by_key, by_source,
                                      {"assembly": "Language", "class": "Language_Text"})
            for identity in row.get("provenance", {}).get("game_objects", []):
                candidates.extend(by_key[other] for other in by_object[identity]
                                  if by_key[other].get("provenance", {}).get("component") ==
                                  {"assembly": "Language", "class": "Language_Text"})
            titles = {candidate["semantic"].get("facts", {}).get("text") for candidate in candidates}
            titles.discard(None)
            if len(titles) == 1:
                put(key, next(iter(titles)).strip(), "game", "workbench-title")
            else:
                put(key, sources["workbench"]["fallback"].get(original, _humanize(original)), "wiki", "workbench-fallback")
        elif kind == "biome":
            name = _biome_name(row, sources)
            if _bundle_name(row) == "icons_common_scenes_all":
                put(key, name + " (scene)", "wiki", "biome-scene")
            else:
                put(key, name, "wiki", "biome")
        elif kind == "creature":
            put(key, _creature(original), "wiki", "creature")
        elif kind == "loot-source":
            if key in loot_names:
                result[key] = loot_names[key]
            else:
                put(key, _humanize(original), "wiki", "loot-source")
        else:
            if sem.get("name_status") == "internal":
                replacement = _humanize(original, scenery=kind in {"building-piece", "construction-rule"})
                if replacement != original:
                    humanized_keys.add(key)
                put(key, replacement, "wiki", "humanize")
            else:
                put(key, original, "game")
    clean_identifiers()
    _disambiguate(result, by_key, registry, game_text, graph, by_key, by_source)

    for key, row in sorted(by_key.items()):
        if row["semantic"]["kind"] not in {"building-piece", "construction-rule"}:
            continue
        item = _construction_item(row, items_by_tooltip, by_key)
        if item is not None:
            put(key, result[item]["name"], "wiki", "construction-item")

    recipes_by_output = defaultdict(list)
    for key, recipe in graph.get("recipes", {}).items():
        if recipe.get("output"):
            recipes_by_output[recipe["output"]].append(key)
    for key, row in sorted(by_key.items()):
        if row["semantic"]["kind"] != "recipe":
            continue
        recipe = graph.get("recipes", {}).get(key, {})
        output = recipe.get("output")
        name = result[output]["name"] if output in result else row["semantic"].get("name", "")
        peers = sorted(recipes_by_output.get(output, [])) if output else []
        rule = "recipe-output" if output in result else None
        if len(peers) > 1:
            others = {ingredient for peer in peers if peer != key for ingredient in _recipe_order(by_key[peer])}
            unique = next((item for item in _recipe_order(row) if item not in others and item in result), None)
            if unique:
                name += " from " + result[unique]["name"]
                rule = "recipe-ingredient"
            elif recipe.get("bench") in result:
                name += " at the " + result[recipe["bench"]]["name"]
                rule = "recipe-bench"
        put(key, name, "wiki" if rule else "game", rule)

    for key, row in sorted(by_key.items()):
        kind = row["semantic"]["kind"]
        if kind not in {"combat-rule", "loot-table"}:
            continue
        original = row["semantic"].get("name") or ""
        if kind == "loot-table":
            containers = sorted(source for source in inbound[key] if by_key[source]["semantic"]["kind"] == "loot-source")
            if original.isdecimal() and containers:
                put(key, result[containers[0]]["name"], "wiki", "loot-table-container")
            else:
                put(key, original, "game")
            continue
        users = {source for source in inbound[key] if by_key[source]["semantic"]["kind"] in {"item", "creature"}}
        for identity in row.get("provenance", {}).get("game_objects", []):
            users.update(source for source in by_object[identity]
                         if by_key[source]["semantic"]["kind"] in {"item", "creature"})
        for source in inbound[key]:
            if by_key[source]["semantic"]["kind"] == "asset":
                users.update(owner for owner in inbound[source]
                             if by_key[owner]["semantic"]["kind"] in {"item", "creature"})
        if original == "Tool_Interact_Mgr":
            put(key, "Handmade ammo", "wiki", "combat-handmade-ammo")
        elif len(users) == 1:
            put(key, result[next(iter(users))]["name"] + " combat", "wiki", "combat-user")
        elif re.fullmatch(r"Z_Attack_\d+", original):
            put(key, "Zombie attack " + str(int(original.rsplit("_", 1)[1])), "wiki", "combat-pattern")
        elif original.startswith(("Z_Man_", "Z_Woman_", "ZBoss")):
            put(key, _creature(original) + " combat", "wiki", "combat-pattern")
        else:
            put(key, _humanize(original), "wiki", "combat-humanize")

    clean_identifiers()
    if audit is not None:
        changed_by_kind = defaultdict(int)
        for key in humanized_keys:
            changed_by_kind[by_key[key]["semantic"]["kind"]] += 1
        audit["humanized_by_kind"] = dict(sorted(changed_by_kind.items()))
    _disambiguate(result, by_key, registry, game_text, graph, by_key, by_source)
    return dict(sorted(result.items()))


def player_names(rows, registry, game_text, graph):
    """Return one player name, source, and applied rule per entity key."""
    return _compute(rows, registry, game_text, graph)
