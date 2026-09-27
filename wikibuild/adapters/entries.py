"""Project selected nested definitions into recipe, skill and status entries."""

import copy

from .items_loot import observation


def under(field, prefix):
    return field == prefix or field.startswith(prefix + "/")


def child(parent, kind, prefix, facts, name, name_status="internal", extra_evidence=()):
    evidence = copy.deepcopy(parent["evidence"][0])
    evidence["fields"] = [field for field in evidence["fields"] if under(field, prefix)]
    links = [link for link in parent["relationships"] if under(link["source_field"], prefix)]
    result = observation(kind, parent["source_id"] + prefix, name, facts,
                         evidence["path"], (), links)
    result["evidence"] = [evidence, *extra_evidence]
    result["parent_source_id"] = parent["source_id"]
    result["source_field_base"] = prefix
    result["component"] = parent["component"]
    result["fact_scope"] = "serialized-definition"
    result["name_status"] = name_status
    result["notes"] = parent["notes"]
    result["relationships"].append({"predicate": "defined-by", "target_source_id": parent["source_id"],
                                    "source_field": prefix})
    return result


def label(parent, prefix, labels):
    names, evidence = set(), []
    for link in parent["relationships"]:
        if link["predicate"] != "localized-name" or not under(link["source_field"], prefix):
            continue
        for target in link.get("target_source_ids", []):
            if target in labels:
                names.add(labels[target]["name"])
                evidence.append(labels[target]["evidence"])
    if len(names) == 1:
        return next(iter(names)), "english", evidence
    return prefix.strip("/").replace("/", " "), "internal", []


def expand(parent, item_names, localized):
    cls = parent["component"]["class"]
    if cls in {"Craft_Items", "Special_Workbench"}:
        facts = parent["facts"].pop("_CraftItemsData", [])
        for category, group in enumerate(facts):
            if not isinstance(group, dict):
                continue
            for index, recipe in enumerate(group.get("perIconData", [])):
                if not isinstance(recipe, dict):
                    continue
                prefix = f"/_CraftItemsData/{category}/perIconData/{index}"
                targets = [target for link in parent["relationships"]
                           if link["predicate"] == "produces-item" and under(link["source_field"], prefix)
                           for target in link.get("target_source_ids", [])]
                names = {item_names[target] for target in targets if target in item_names}
                name = next(iter(names)) if len(names) == 1 else f"{parent['name']} recipe {category + 1}.{index + 1}"
                row = child(parent, "recipe", prefix, recipe, name,
                            "linked-item" if len(names) == 1 else "internal")
                yield row
        remove_nested(parent, ["/_CraftItemsData"])
        yield parent
    elif cls == "All_Skills_Set":
        for family in ("_CraftSkills", "_FightSkills", "_SurviveSkills"):
            for index, skill in enumerate(parent["facts"].get(family, [])):
                if not isinstance(skill, dict):
                    continue
                prefix = f"/{family}/{index}"
                name, status, evidence = label(parent, prefix, localized)
                row = child(parent, "skill", prefix, skill, name, status, evidence)
                row["family"] = family
                yield row
        # The technical type summary accounts for the source container; no empty
        # gameplay entry or duplicate list of every skill is emitted.
    elif cls == "Skill_Mgr":
        prefixes = []
        for field in sorted(list(parent["facts"])):
            if not isinstance(parent["facts"][field], dict):
                continue
            prefix = "/" + field
            name, status, evidence = label(parent, prefix, localized)
            yield child(parent, "status-effect", prefix, parent["facts"].pop(field), name, status, evidence)
            prefixes.append(prefix)
        remove_nested(parent, prefixes)
        yield parent
    else:
        yield parent


def remove_nested(parent, prefixes):
    parent["relationships"] = [link for link in parent["relationships"]
                               if not any(under(link["source_field"], prefix) for prefix in prefixes)]
    parent["evidence"][0]["fields"] = [field for field in parent["evidence"][0]["fields"]
                                        if not any(under(field, prefix) for prefix in prefixes)]


def english_labels(source, pending, issues):
    identities = {target for row in pending for link in row["relationships"] if link["predicate"] == "localized-name"
                  for target in link.get("target_source_ids", [])}
    labels = {}
    records = source.objects(identities)
    for identity in sorted(identities):
        record = records.get(identity, {})
        script = record.get("script", {})
        infos = record.get("fields", {}).get("_Infos", [])
        if (script.get("assembly"), script.get("class")) != ("Language", "Language_Text") or not isinstance(infos, list):
            infos = []
        candidates = [(index, info["text"]) for index, info in enumerate(infos)
                      if isinstance(info, dict) and info.get("languageType") == 2 and isinstance(info.get("text"), str) and info["text"]]
        if len({name for _, name in candidates}) != 1:
            issues.add("english-name", "skills-survival", "Language_Text/_Infos",
                       "No unique English definition name; an internal label is retained.", identity)
            continue
        index, name = candidates[0]
        labels[identity] = {"name": name, "evidence": {"path": source.object_path(identity), "object": identity,
            "fields": [f"/_Infos/{index}/text", f"/_Infos/{index}/languageType"],
            **({"record_sha256": source.locations[identity]["sha256"]} if identity in source.locations else {})}}
    return labels
