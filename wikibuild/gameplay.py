"""Pure snapshot acquisition graph, derived from resolved model relationships.

Terrain/Terrain.decompiled.cs:6761,6974,7328-7382 defines cyclic biome
layers of width BigTerraWidth * _BiomesWidthNum. The regular intervals are
[12 + i*width, 12 + (i+1)*width); d < 10 is a separate layer-zero exception.
Distances here describe the first regular cycle, without unit conversion.
Terrain.decompiled.cs:7334-7411 selects _BaseBigTerrains for layer -1 near
the layer-zero border. This playable Base patch is reported as near_spawn,
outside the cyclic ring list, and does not seed either progression ring.

Terrain.decompiled.cs:5591-5633 makes one weighted selection per dig hit:
rate / max(1, sum(rates)), independently for each terrain block definition.
Build_Info._Collectable_Info rolls collectibles independently; these are not
normalized together. Hand_Tools.decompiled.cs:6040-6091 removes grass when a
player hits a GrassSpawner with a positive removal radius, then passes its
count and Tool_Interact_Mgr._PlantFiberIconRef to Item_Slot_Mgr.Pick_Enviro_Item
(UI.decompiled.cs:5367-5407). Neither path gates pickup on biome. Where captured
vegetation cannot prove grass coverage, this rule records an unlocated source.
Only extracted biome placement supplies a progression ring.
UI.decompiled.cs:387 and Craft_Mgr.WorkbenchType (1909-1922) establish that
only HandMade (0) bypasses a bench. Merchant_Mgr.BiomeItemSet.BiomeName names
merchant biomes; randomized prices are deliberately outside this graph.

Loot_Mgr (UI.decompiled.cs:9186-9260) matches each table's _spawnLootTag exactly
to _All_Loot_Icons, then picks an icon within that tag. Shared generic tags really
do permit broad loot; a tag's name is not itself a biome-placement relationship.

No identity is merged by display name. Named biome lookups select terrain-linked
definitions when available. Build_System.decompiled.cs:6985,7005,7018 reaches
Craft_Items through Spawned_BaIs[0].GetChild(0); Craft_Items checks distance from
transform.parent.parent (UI.decompiled.cs:741-746). Captures omit that hierarchy.
After exact prefab/component joins, a unique recipe output's model-prefab name
matching a bench's source name is therefore retained as ``name-matched`` evidence.
Exact output-item names are a final fallback; ambiguous matches remain gaps.
"""

from collections import defaultdict
import json
import math
import re


# Longest token wins, so desert_rocky and winter_forest are not generic desert
# or forest. Snowy bundles describe both winter biomes, not a fabricated biome.
BUNDLE_BIOMES = {
    "desert_rocky": ("Desert_Rocky",), "desert": ("Desert",),
    "mossy": ("Forest",), "mountain": ("Mountain",),
    "snowy": ("Winter_Forest", "Winter_Town"),
    "winter_forest": ("Winter_Forest",), "winter_town": ("Winter_Town",),
    "swamp": ("Swamp",), "rainforest": ("Tropical",),
    "tropical_jungle": ("Tropical",), "warzone": ("Warzone",),
    "war": ("Warzone",), "wasteland": ("Wasteland",), "base": ("Base",),
    "forest": ("Forest",), "baseterrain": ("Base",),
    "winterforest": ("Winter_Forest",), "wintertown": ("Winter_Town",),
}

GRASS_CODE_EVIDENCE = "biome-independent-grass-cutting"


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _unique(entries):
    """Canonical ordering also removes duplicate paths to the same source."""
    keyed = {json.dumps(entry, sort_keys=True, allow_nan=False): entry for entry in entries}
    return [keyed[key] for key in sorted(keyed)]


class _Snapshot:
    def __init__(self, rows):
        self.rows = {}
        for row in rows:
            key = row["entity_key"]
            if key in self.rows:
                raise ValueError(f"Duplicate snapshot entity: {key}")
            self.rows[key] = row
        self.rows = dict(sorted(self.rows.items()))
        self.sem = {key: row["semantic"] for key, row in self.rows.items()}
        self.by_object = defaultdict(set)
        for key, row in self.rows.items():
            provenance = row.get("provenance", {})
            for identity in provenance.get("game_objects", []):
                self.by_object[identity].add(key)

    def facts(self, key):
        return self.sem.get(key, {}).get("facts", {})

    def links(self, key, predicate):
        return [link for link in self.sem.get(key, {}).get("relationships", [])
                if link["predicate"] == predicate]

    def targets(self, key, predicate):
        return {target for link in self.links(key, predicate) for target in link.get("targets", [])
                if target in self.sem}

    def components(self, key):
        """Exact prefab/component join; never traverse technical summary targets."""
        provenance = self.rows[key].get("provenance", {})
        return ({key} | self.targets(key, "cataloged-component")
                | self.by_object.get(provenance.get("source_id"), set()))

    def walk(self, starts, predicates):
        seen, pending = set(), list(starts)
        while pending:
            key = pending.pop()
            if key in seen or key not in self.sem:
                continue
            seen.add(key)
            pending.extend(self.components(key) - seen)
            for predicate in predicates:
                pending.extend(self.targets(key, predicate) - seen)
        return seen


def _geography(data, biomes):
    """Preserve layer order; _BaseBigTerrains (layer -1) is a separate patch."""
    configurations = []
    base_keys = set()
    for key in data.sem:
        base_keys.update(data.walk(data.targets(key, "base-terrain-prefab"), {"biome"}) & biomes.keys())
    if len(base_keys) > 1:
        raise ValueError("Conflicting near-spawn terrain biomes")
    base = next(iter(base_keys), None)
    for key in data.sem:
        facts = data.facts(key)
        layers = facts.get("_BiomesLayers")
        if not layers:
            continue
        width = facts.get("BigTerraWidth", 0) * facts.get("_BiomesWidthNum", 0)
        if not _number(width) or width <= 0:
            raise ValueError("Biome ring width must be positive and finite")
        rings = []
        for index, _ in enumerate(layers):
            prefabs = {target for link in data.links(key, "biome-terrain-prefab")
                       if link.get("field", "").startswith(f"/_BiomesLayers/{index}/")
                       for target in link.get("targets", [])}
            reached = data.walk(prefabs, {"biome"})
            keys = sorted((reached & biomes.keys()) - base_keys)
            rings.append({"index": index, "layer": index, "biome_keys": keys,
                          "start_distance": 12 + index * width,
                          "end_distance": 12 + (index + 1) * width})
        configurations.append(rings)
    distinct = _unique(configurations)
    if len(distinct) > 1:
        raise ValueError("Conflicting nonempty terrain layer configurations")
    rings = distinct[0] if distinct else []
    for ring in rings:
        for biome in ring["biome_keys"]:
            old = biomes[biome]["ring"]
            biomes[biome]["ring"] = ring["index"] if old is None else min(old, ring["index"])
    return rings, base


def _mining(data, key):
    """Normalize per block, including weights whose item target is unresolved."""
    links = {link.get("field"): link for link in data.links(key, "mineable-item")}
    for block_index, block in enumerate(data.facts(key).get("_BlockInfo", [])):
        entries = block.get("CollectableItems", [])
        rates = [entry.get("RandomRate", 0) for entry in entries]
        if any(not _number(rate) or rate < 0 for rate in rates):
            continue
        denominator = max(1, math.fsum(rates))
        weights = defaultdict(list)
        for index, rate in enumerate(rates):
            link = links.get(f"/_BlockInfo/{block_index}/CollectableItems/{index}", {})
            targets = link.get("targets", [])
            if len(targets) == 1 and rate > 0:
                weights[targets[0]].append(rate)
        for item, values in sorted(weights.items()):
            yield item, math.fsum(values) / denominator


def _bench_construction(data, items, recipes, benches, hand):
    """Resolve exact prefab identity before explicitly labelled name fallbacks.

    Name matching never combines different nonempty serialized bundle scopes.
    Multiple outputs with the same name are ambiguous, not interchangeable.
    The output retains the item and model key so a guide can inspect the join.
    """
    candidates = defaultdict(dict)
    produced = {value["output"] for value in recipes.values()} & items.keys()
    models = {item: data.targets(item, "model") for item in items}
    for item, prefabs in models.items():
        for prefab in sorted(prefabs):
            for bench in data.walk({prefab}, {"cataloged-component"}) & benches.keys():
                candidates[bench].setdefault(item, prefab)

    def same_scope(left, right):
        first = data.rows[left].get("provenance", {}).get("source_id", "").split("::", 1)[0].split("#", 1)[0]
        second = data.rows[right].get("provenance", {}).get("source_id", "").split("::", 1)[0].split("#", 1)[0]
        return not first or not second or first == second

    for key, bench in benches.items():
        bench.update({"construction_item": None, "model": None, "evidence": None, "gap_reason": None})
        if key in hand:
            bench["evidence"] = "hand-crafting"
            continue
        evidence = "extracted"
        matches = candidates[key]
        if not matches:
            evidence = "name-matched"
            name = data.sem[key]["name"]
            matches = {item: prefab for item in sorted(produced) for prefab in sorted(models[item])
                       if data.sem[prefab]["name"] == name and same_scope(key, prefab)}
            if not matches:
                matches = {item: None for item in sorted(produced) if data.sem[item]["name"] == name}
        if len(matches) != 1:
            bench["gap_reason"] = "ambiguous-construction-item" if matches else "no-construction-item-join"
            continue
        item, prefab = next(iter(matches.items()))
        bench.update({"construction_item": item, "model": prefab, "evidence": evidence})
        builders = sorted(recipe for recipe, value in recipes.items() if value["output"] == item)
        if builders:
            bench["built_by_recipe"] = builders[0]
        else:
            bench["gap_reason"] = "no-construction-recipe"


def graph(rows):
    """Return sorted JSON data without I/O or mutation of the input iterable.

    Unknown means no proven reachable ring, not ring zero. Relaxation starts
    with direct geographic sources and only lowers finite ring values. Thus a
    closed cycle stays null and a seeded cycle reaches its least reachable ring.
    Dismantled sources use the donor item as ``via`` and inherit its ring.
    ``items_without_source`` means no recorded acquisition edge, even unknown
    geography counts as an edge. ``blocked_by`` lists direct ingredient items
    with no reachable ring; missing bench joins live in ``unresolved_benches``.
    Recipe bench null means hand crafting or missing owner; missing owners are
    retained but never treated as hand crafting. Mining entries are conditional
    on the selected block definition, not averaged across terrain textures.
    Item ``biomes`` lists direct geographic acquisition; ``loot_biomes`` lists
    only container loot, for loot exclusivity guides. Neither list proves global
    exclusivity if ``has_unmapped_loot`` is true. Crafting and dismantling do not
    manufacture geographic placements from their earliest-ring estimates.

    ``main_ring`` chooses the highest per-hit mining chance among ring biomes
    (ties choose the earliest ring), then takes the earliest alternative from
    other acquisition types. Crafting takes the maximum ingredient and bench
    main ring; dismantling inherits the donor's main ring. Both dimensions use
    independent fixed points. Base and unknown-biome sources seed neither.
    Item ``near_spawn`` marks direct Base acquisition, without crafting closure;
    ``near_spawn_chance_per_hit`` is its best Base mining chance, or null when
    no Base mining is recorded. Top-level ``near_spawn.biome`` is null when
    the loader's base-terrain-prefab relationship has no resolved biome.
    """
    data = _Snapshot(rows)
    items = {key: {"sources": [], "earliest_ring": None, "main_ring": None, "used_in": []}
             for key, value in data.sem.items() if value["kind"] == "item"}
    biomes = {key: {"name": value["name"], "ring": None, "mined": [],
                    "container_loot": [], "merchant": [], "harvest": []}
              for key, value in data.sem.items() if value["kind"] == "biome"}
    benches = {key: {"built_by_recipe": None, "earliest_ring": None, "main_ring": None}
               for key, value in data.sem.items() if value["kind"] == "workbench"}
    rings, base = _geography(data, biomes)
    names = defaultdict(set)
    for key, value in biomes.items():
        names[value["name"].casefold()].add(key)

    def named_biomes(name):
        matches = names.get(name.casefold(), set())
        linked = {key for key in matches if biomes[key]["ring"] is not None or key == base}
        return linked or matches

    def source(item, kind, via, biome=None, bench=None, evidence="extracted"):
        if item in items:
            items[item]["sources"].append({"type": kind, "via": via, "biome": biome,
                                           "bench": bench, "evidence": evidence})

    # Terrain_Top owns the biome and its resource references. Support direct
    # biome references too, without crossing through unrelated material links.
    membership = defaultdict(set)
    paths = {"vegetation", "scene-props", "scene-prop", "scene-prop-prefab", "terrain-block-set"}
    for key in data.sem:
        owners = data.targets(key, "biome") & biomes.keys()
        if key in biomes:
            owners.add(key)
        if owners:
            for target in data.walk({key}, paths):
                membership[target].update(owners)
    fibers = {target for key in data.sem for link in data.links(key, "gathered-item")
              if link.get("field") == "/_PlantFiberIconRef" for target in link.get("targets", [])}
    for key, semantic in data.sem.items():
        places = sorted(membership[key]) or [None]
        for item, chance in _mining(data, key):
            if item not in items:
                continue
            for biome in places:
                source(item, "mined", key, biome)
                if biome:
                    biomes[biome]["mined"].append({"item": item, "chance_per_hit": chance, "block_set": key})
        # Item_Info._IconRef is a model identity, not an independent harvest.
        if semantic["kind"] != "building-piece":
            continue
        harvest = set()
        for link in data.links(key, "collectible-item"):
            match = re.fullmatch(r"/_Collectable_Info/_Items/(\d+)/_IconRef", link.get("field", ""))
            if match:
                definitions = data.facts(key).get("_Collectable_Info", {}).get("_Items", [])
                index = int(match[1])
                if index >= len(definitions):
                    continue
                definition = definitions[index]
                rate = definition.get("_RandomRate")
                count = definition.get("_CollectMinMaxCount", {}).get("y")
                if not _number(rate) or rate <= 0 or (_number(count) and count <= 0):
                    continue
                harvest.update(link.get("targets", []))
        for item in sorted(harvest & items.keys()):
            for biome in places:
                source(item, "harvested", key, biome)
                if biome:
                    biomes[biome]["harvest"].append({"item": item, "source": key})
    # Grass is identified only among referenced vegetation prefabs, not material
    # names or the generic _treeGrassRefs field (which also contains rocks).
    vegetation = {target for key in data.sem for target in data.targets(key, "vegetation")}
    grass = {key for key in vegetation if data.sem[key]["kind"] == "asset"
             and "grass" in data.sem[key]["name"].casefold()}
    grass_names = {biomes[biome]["name"] for key in grass for biome in membership[key]}
    every_biome = bool(biomes) and {value["name"] for value in biomes.values()} <= grass_names
    grass_evidence = ("grass in every biome's vegetation" if every_biome else "grass in biome's vegetation")
    for key in sorted(grass):
        for item in sorted(fibers & items.keys()):
            for biome in sorted(membership[key]):
                source(item, "harvested", key, biome, evidence=grass_evidence)
                biomes[biome]["harvest"].append({"item": item, "source": key})
    for key in data.sem:
        for rel in data.links(key, "gathered-item"):
            if rel.get("field") == "/_PlantFiberIconRef" and not every_biome:
                for item in sorted(set(rel.get("targets", [])) & fibers):
                    source(item, "harvested", key, evidence=GRASS_CODE_EVIDENCE)

    tags = defaultdict(set)
    for key, semantic in data.sem.items():
        if semantic["kind"] == "loot-tag":
            tags[data.facts(key).get("tag")].update(data.targets(key, "eligible-item") & items.keys())
    unmapped = set()
    for key, semantic in data.sem.items():
        if semantic["kind"] == "loot-source" and data.links(key, "uses-loot-table"):
            source_id = data.rows[key].get("provenance", {}).get("source_id", "")
            bundle = source_id.split("::", 1)[0].rsplit("/", 1)[-1]
            matches = [token for token in BUNDLE_BIOMES
                       if re.search(r"(?:^|_)" + token + r"(?:_|\.|$)", bundle.casefold())]
            places = set()
            if matches:
                token = sorted(matches, key=lambda token: (-len(token), token))[0]
                for name in BUNDLE_BIOMES[token]:
                    places.update(named_biomes(name))
            if not places:
                unmapped.add(bundle)
            loot = set()
            for table in data.targets(key, "uses-loot-table"):
                for rate in data.facts(table).get("rates", []):
                    weight = rate.get("_spawnRateRange")
                    if _number(weight) and weight > 0:
                        loot.update(tags.get(rate.get("_spawnLootTag"), set()))
            for item in sorted(loot):
                for biome in sorted(places) or [None]:
                    source(item, "looted", key, biome, evidence=("inferred-from-bundle-name" if biome else "extracted"))
                    if biome:
                        biomes[biome]["container_loot"].append({"item": item, "container": key})
        if semantic["kind"] == "loot-table" and data.links(key, "merchant-stock-item"):
            places = named_biomes(data.facts(key).get("BiomeName", ""))
            for item in sorted(data.targets(key, "merchant-stock-item") & items.keys()):
                for biome in sorted(places) or [None]:
                    source(item, "merchant", key, biome)
                    if biome:
                        biomes[biome]["merchant"].append({"item": item})
    for donor in items:
        for rule in data.targets(donor, "disassembly"):
            for item in data.targets(rule, "yields-item-asset"):
                source(item, "dismantled", donor)

    recipes, incomplete, hand = {}, set(), set()
    for key in benches:
        if data.facts(key).get("_workbenchType") == 0:
            hand.add(key)
            benches[key]["earliest_ring"] = 0
            benches[key]["main_ring"] = 0
    for key, semantic in data.sem.items():
        if semantic["kind"] != "recipe":
            continue
        outputs = data.targets(key, "produces-item") & items.keys()
        owners = data.targets(key, "defined-by") & benches.keys()
        owner = next(iter(owners)) if len(owners) == 1 else None
        bench = None if owner in hand else owner
        if len(outputs) != 1 or owner is None:
            incomplete.add(key)
        ingredients = defaultdict(int)
        links = defaultdict(set)
        for link in data.links(key, "consumes-item-asset"):
            links[link.get("field")].update(link.get("targets", []))
        for index, entry in enumerate(data.facts(key).get("matsData", [])):
            count = entry.get("matNeedCount")
            targets = links.get(f"/matsData/{index}/matIcon", set())
            if not _number(count) or count < 0 or len(targets) != 1:
                incomplete.add(key)
            if _number(count) and count > 0:
                for item in sorted(targets):
                    ingredients[item] += count
                    if item not in items:
                        incomplete.add(key)
        count = data.facts(key).get("craftNum")
        if not _number(count) or count <= 0:
            incomplete.add(key)
        output = next(iter(outputs)) if len(outputs) == 1 else None
        recipes[key] = {"output": output, "count": count, "bench": bench,
                        "ingredients": [{"item": item, "count": count} for item, count in sorted(ingredients.items())],
                        "earliest_ring": None, "main_ring": None, "blocked_by": []}
        for item in ingredients.keys() & items.keys():
            items[item]["used_in"].append(key)
        if output is not None:
            source(output, "crafted", key, bench=bench)

    _bench_construction(data, items, recipes, benches, hand)

    def lower(record, field, candidate):
        if candidate is None:
            return False
        current = record[field]
        if current is None or candidate < current:
            record[field] = candidate
            return True
        return False

    best_mining = {}
    base_chances = {}
    for biome, value in biomes.items():
        for entry in value["mined"]:
            item, chance = entry["item"], entry["chance_per_hit"]
            if biome == base:
                base_chances[item] = max(base_chances.get(item, 0), chance)
            if value["ring"] is not None:
                candidate = (-chance, value["ring"])
                if item not in best_mining or candidate < best_mining[item]:
                    best_mining[item] = candidate

    for key, value in items.items():
        value["sources"] = _unique(value["sources"])
        value["used_in"] = sorted(set(value["used_in"]))
        value["biomes"] = sorted({entry["biome"] for entry in value["sources"] if entry["biome"]})
        value["loot_biomes"] = sorted({entry["biome"] for entry in value["sources"]
                                       if entry["type"] == "looted" and entry["biome"]})
        value["has_unmapped_loot"] = any(entry["type"] == "looted" and entry["biome"] is None
                                         for entry in value["sources"])
        value["near_spawn"] = base is not None and base in value["biomes"]
        value["near_spawn_chance_per_hit"] = base_chances.get(key)
    for field in ("earliest_ring", "main_ring"):
        changed = True
        while changed:
            changed = False
            for key, value in recipes.items():
                requirements = [items.get(entry["item"], {}).get(field) for entry in value["ingredients"]]
                requirements.append(benches[value["bench"]][field] if value["bench"] else 0)
                if key not in incomplete and all(ring is not None for ring in requirements):
                    changed |= lower(value, field, max(requirements))
            for key in benches.keys() - hand:
                item = benches[key]["construction_item"]
                if item is not None:
                    changed |= lower(benches[key], field, items[item][field])
            for key, value in items.items():
                if field == "main_ring" and key in best_mining:
                    changed |= lower(value, field, best_mining[key][1])
                for entry in value["sources"]:
                    if entry["type"] == "crafted":
                        candidate = recipes[entry["via"]][field]
                    elif entry["type"] == "dismantled":
                        candidate = items[entry["via"]][field]
                    elif entry["type"] == "mined" and field == "main_ring":
                        continue  # Only the strongest mining chance contributes.
                    else:
                        candidate = biomes[entry["biome"]]["ring"] if entry["biome"] else None
                    changed |= lower(value, field, candidate)
    for key in benches.keys() - hand:
        bench = benches[key]
        builders = [recipe for recipe, value in recipes.items()
                    if bench["construction_item"] is not None and value["output"] == bench["construction_item"]]
        if builders:
            bench["built_by_recipe"] = min(builders, key=lambda recipe: (
                recipes[recipe]["earliest_ring"] is None, recipes[recipe]["earliest_ring"] or 0, recipe))
        if bench["earliest_ring"] is None and bench["gap_reason"] is None:
            bench["gap_reason"] = "construction-item-unreachable"
    for key, value in recipes.items():
        value["blocked_by"] = sorted({entry["item"] for entry in value["ingredients"]
                                      if items.get(entry["item"], {}).get("earliest_ring") is None})
    for value in biomes.values():
        for field in ("mined", "container_loot", "merchant", "harvest"):
            value[field] = _unique(value[field])
    near_spawn = {"biome": base, **{field: list(biomes[base][field]) if base else []
                                   for field in ("mined", "container_loot", "harvest")}}
    return {"rings": rings, "near_spawn": near_spawn, "biomes": biomes, "items": items,
            "recipes": recipes, "benches": benches,
            "gaps": {"items_without_source": sorted(key for key, value in items.items() if not value["sources"]),
                     "unresolved_benches": sorted(key for key, bench in benches.items() if bench["gap_reason"]),
                     "unmapped_container_bundles": sorted(unmapped)}}
