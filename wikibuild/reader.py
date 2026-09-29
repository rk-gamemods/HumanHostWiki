"""Project pinned selected models to an immutable static-reader candidate."""

from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

from . import availability, curation, external_links, extraction, game_text, guide_queries, guides, history, model, packs, pages, presentation, snapshots
from .exceptions import Exceptions
from .storage import ContractError, digest, json_bytes, within, write_changed

DEFAULT_PACK_BYTES = 512 * 1024
ENTITY = re.compile(r"^e-[0-9a-f]{32}$")


def candidate_path(cache_root, candidate_id):
    """Short cache names avoid Windows path overflow; manifests retain full IDs."""
    if not re.fullmatch(r"[0-9a-f]{64}", candidate_id):
        raise ContractError("Invalid reader candidate identity")
    legacy = within(cache_root, f"readers/{candidate_id}")
    return legacy if legacy.exists() else within(cache_root, f"readers/{candidate_id[:24]}")


def contract():
    folder = Path(__file__).parent
    paths = [folder / name for name in ("reader.py", "packs.py", "pages.py", "storage.py", "curation.py", "curated_rules.py", "source.py", "external_links.py", "mediawiki.py", "presentation.py", "game_text.py", "gameplay.py", "names.py", "guide_queries.py", "lint.py")]
    paths.append(folder / "guides.py")
    paths += sorted(path for path in (folder / "web").rglob("*") if path.is_file())
    return {path.relative_to(folder).as_posix(): digest(path.read_bytes() if path.suffix == ".woff2" else path.read_bytes().replace(b"\r\n", b"\n"))
            for path in paths}


def versions(root):
    """Latest decision for each captured snapshot, without discarding prior runs."""
    result, seen, snapshots_seen = [], set(), set()
    current = history.latest(root)
    while current:
        if current["run_id"] in seen:
            raise ContractError("Cycle in identity history")
        seen.add(current["run_id"])
        if current["snapshot_id"] not in snapshots_seen:
            history.read(root, current["run_id"])
            result.append(current)
            snapshots_seen.add(current["snapshot_id"])
        current = history.read(root, current["parent_run"], require_models=False) if current["parent_run"] else None
    if not result:
        raise ContractError("No normalized snapshots; run normalize first")
    return result


def verify(destination, expected_id=None):
    manifest = json.loads((destination / "candidate.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("candidate_id") != digest(json_bytes(manifest["inputs"])):
        raise ContractError("Reader candidate identity differs")
    if expected_id is not None and manifest["candidate_id"] != expected_id:
        raise ContractError("Reader candidate does not match requested inputs")
    actual = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"candidate.json"}:
        raise ContractError("Reader candidate contains missing or unknown files")
    for name, record in manifest["files"].items():
        path = within(destination, name)
        if path.stat().st_size != record["bytes"] or extraction.file_hash(path) != record["sha256"]:
            raise ContractError(f"Reader candidate was modified: {name}")
    return manifest


def load_maps(site, shards):
    values = {}
    for shard in shards:
        path = within(site, shard["path"])
        data = path.read_bytes()
        if len(data) != shard["bytes"] or digest(data) != shard["sha256"]:
            raise ContractError("Reader shard hash differs")
        group = json.loads(data)
        keys = sorted(group)
        if not keys or keys[0] != shard["first"] or keys[-1] != shard["last"] or len(keys) != shard["count"] or set(group).intersection(values):
            raise ContractError("Reader shard membership differs")
        values.update(group)
    return values


def validate_snapshot(stage, snapshot, topics):
    """Validate cross-topic entity membership without loading all facts at once."""
    membership, targets = {}, []
    present, totals, hub_index, hub_search = {}, {}, None, None
    count = 0
    for topic in topics:
        site = within(stage, topic)
        index = json.loads((site / "snapshots" / f"{snapshot}.json").read_text(encoding="utf-8"))
        entries = load_maps(site, index["entries"])
        semantics = load_maps(site, index["semantics"])
        provenance = load_maps(site, index["provenance"])
        searches = load_maps(site, index["search"])
        backlinks = load_maps(site, index["backlinks"])
        cards = load_maps(site, index.get("cards", []))
        owned_cards = {record["card_id"] for record in entries.values() if "card_id" in record}
        if owned_cards - cards.keys():
            raise ContractError("Reader entry card_id is missing from cards")
        if cards.keys() - owned_cards:
            raise ContractError("Reader card has no owning entry")
        players = load_maps(site, index.get("player", []))
        owned_players = {record["player_id"] for record in entries.values() if "player_id" in record}
        if owned_players - players.keys():
            raise ContractError("Reader entry player_id is missing from player")
        if players.keys() - owned_players:
            raise ContractError("Reader player has no owning entry")
        for identity, player in players.items():
            if digest(packs.compact(player)) != identity:
                raise ContractError("Reader player hash differs")
            runs = [run for phrase in player["how"] for run in phrase] + player["used_in"]["items"]
            linked = {run["entity"] for run in runs if "entity" in run}
            if linked != player["links"].keys():
                raise ContractError("Reader player links differ from its runs")
            targets.extend((key, link["topic"]) for key, link in player["links"].items())
        if topic == "hub" and "topic_counts" in index:
            hub_index, hub_search = index, searches
        elif set(entries) != set(searches):
            raise ContractError("Search coverage differs from snapshot entries")
        kinds = Counter()
        for key, record in entries.items():
            if key in membership or record["topic"] != topic or not ENTITY.fullmatch(key):
                raise ContractError("Reader has duplicate or invalid canonical ownership")
            membership[key] = topic
            for note in record.get("explanations", []):
                if (note["entity"] != key or note["topic"] != topic or note["snapshot_id"] != snapshot
                        or note["status"] not in {"passed", "unverified"}):
                    raise ContractError("Explanation leaves its owning entry or snapshot")
                if note["status"] == "passed" and (not isinstance(note["text"], str) or not note["last_verified"]
                                                 or note["last_verified"]["snapshot_id"] != snapshot or note["reasons"]):
                    raise ContractError("Passed explanation lacks its successful check")
                if note["status"] == "unverified" and (note["text"] is not None or not note["reasons"]):
                    raise ContractError("Failed explanation lacks its reason")
            if record["status"] != "present":
                continue
            name = players.get(record.get("player_id"), {}).get("name", record["name"])
            present[key] = {"entity_key": key, "name": name, "kind": record["kind"], "topic": topic,
                            **({"source_name": record["name"]} if name != record["name"] else {})}
            kinds[record["kind"]] += 1
            semantic = semantics[record["revision_id"]]
            if digest(json_bytes(semantic)) != record["revision_id"]:
                raise ContractError("Reader semantic revision hash differs")
            if digest(packs.compact(provenance[record["provenance_id"]])) != record["provenance_id"]:
                raise ContractError("Reader provenance hash differs")
            for link in semantic["relationships"]:
                for target in link["targets"] + link.get("technical_targets", []):
                    if target not in record["links"]:
                        raise ContractError("Reader relationship lacks a route")
                    targets.append((target, record["links"][target]["topic"]))
            count += 1
        totals[topic] = {"total": sum(kinds.values()), "kinds": dict(sorted(kinds.items()))}
        for key, link in backlinks.items():
            if key.split("/", 1)[0] not in entries:
                raise ContractError("Reader backlink has no owning entry")
            targets.append((link["entity"], link["topic"]))
    if any(membership.get(key) != topic for key, topic in targets):
        raise ContractError("Reader relationship leaves its selected snapshot")
    if hub_index is not None:
        if hub_search != present or hub_index["topic_counts"] != totals:
            raise ContractError("Hub search or topic counts differ from present entries")
        identities = set()
        for ref in hub_index["guides"]:
            data = within(stage / "hub", ref["path"]).read_bytes()
            if digest(data) != ref["sha256"] or len(data) != ref["bytes"] or ref["path"] != f"data/{ref['sha256']}.json":
                raise ContractError("Guide pack hash differs")
            pack = json.loads(data)
            if ref["id"] in identities or any(ref[field] != pack["document"][field] for field in ("id", "title", "dek")):
                raise ContractError("Guide metadata differs")
            identities.add(ref["id"])
            linked = {run["entity"] for run in document_runs(pack["document"]) if "entity" in run}
            if linked != pack["links"].keys() or any(key not in present or link != {
                    "name": present[key]["name"], "topic": present[key]["topic"]} for key, link in pack["links"].items()):
                raise ContractError("Guide links leave their present snapshot entries")
    return count


def player_projection(models, registry, text, snapshot, *, snapshot_metadata=None, consume_context=None):
    """Hold one snapshot's N stripped rows, never rows from multiple snapshots.

    Kind filtering is unsafe: names uses every kind and graph traverses generic
    components. Keep semantic data and only the provenance used by those joins.
    The context dies before the existing pack pass; only names and encoded player
    payloads escape. Peak parsed rows: N stripped rows plus one streaming row.
    """
    def rows():
        for row in model.rows(models):
            provenance = row.get("provenance", {})
            yield {"entity_key": row["entity_key"], "semantic": row["semantic"],
                   "provenance": {**{key: provenance[key] for key in ("source_id", "component", "game_objects")
                                     if key in provenance},
                                  "relationships": [{key: link[key] for key in ("predicate", "target_source_ids", "target_source_id")
                                                     if key in link}
                                                    for link in provenance.get("relationships", [])
                                                    if link.get("predicate") == "model"],
                                  "evidence": [{"object": entry["object"]} for entry in provenance.get("evidence", [])
                                               if "object" in entry]}}
    context = guide_queries.build_context(rows(), registry, text, {"snapshot_id": snapshot, **(snapshot_metadata or {})})
    if consume_context:
        consume_context(context)
    players = {}
    rings = {ring["index"] for ring in context["graph"]["rings"]}
    for key, row in context["rows"].items():
        name = context["names"][key]
        how, recipes, ring = [], [], None
        graph = context["graph"]
        if key in graph["items"]:
            # The public helper joins phrases with a separate semicolon run;
            # the reader consumes one array of runs per list item.
            phrase = []
            for run in guide_queries.how_runs(context, key, limit=4):
                if run == {"text": "; "}:
                    if phrase:
                        how.append(phrase)
                    phrase = []
                else:
                    phrase.append(run)
            if phrase:
                how.append(phrase)
            recipes = guide_queries.used_in(context, key)
        progression = next((graph[group][key] for group in ("items", "recipes", "benches") if key in graph[group]), None)
        if progression and any(progression[field] is not None for field in ("earliest_ring", "main_ring")):
            main = progression["main_ring"]
            label = (guide_queries.ring_label(context, main) if main in rings else
                     f"Biome {main + 1}" if main is not None else "Unknown")
            ring = {"earliest": progression["earliest_ring"], "main": main, "label": label}
        if (key not in context["unreleased"] and not how and not recipes and ring is None and name["name"] == row["semantic"]["name"]
                and name["source"] == "game" and name["rule"] is None):
            continue
        selected = recipes[:12]
        targets = {run["entity"] for run in [*(run for phrase in how for run in phrase), *selected] if "entity" in run}
        links = {target: {"name": context["names"][target]["name"],
                          "topic": context["rows"][target]["semantic"]["topic"]} for target in sorted(targets)}
        players[key] = packs.compact({"name": name["name"], "name_source": name["source"], "name_rule": name["rule"],
                                      **({"unreleased": context["unreleased"][key]} if key in context["unreleased"] else {}),
                                      "how": how, "ring": ring, "used_in": {"count": len(recipes), "items": selected},
                                      "links": links})
    return context["names"], players


def hub_inputs(root):
    """Pin design and selected specs, including missing specs that become errors."""
    path = root / "presentation/site.json"
    data = path.read_bytes()
    site = json.loads(data)
    identities = site.get("guides", [])
    if (not isinstance(identities, list) or any(not isinstance(key, str) or
            not re.fullmatch(r"[a-z][a-z0-9-]*", key) for key in identities) or len(set(identities)) != len(identities)):
        raise ContractError("Site guide IDs must be unique path-safe names")
    return site, {"site": digest(data), "guides": {
        key: digest((root / "guides" / (key + ".json")).read_bytes())
        if (root / "guides" / (key + ".json")).is_file() else None for key in identities},
        "issue_templates": {name: digest(content) for name, content in issue_templates(root).items()}}


def issue_templates(root):
    """Read the hub's issue forms as validated, byte-exact release inputs."""
    folder = root / "presentation/issue-templates"
    if folder.is_symlink():
        raise ContractError("Issue template input must be a directory")
    if not folder.exists():
        return {}
    if not folder.is_dir():
        raise ContractError("Issue template input must be a directory")
    result = {}
    for path in sorted(folder.glob("*.yml")):
        if not re.fullmatch(r"[A-Za-z0-9-]+\.yml", path.name) or path.is_symlink() or not path.is_file():
            raise ContractError(f"Invalid issue template input: {path}")
        data = path.read_bytes()
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContractError(f"Issue template is not UTF-8: {path}") from error
        required = ("blank_issues_enabled",) if path.name == "config.yml" else ("name", "description", "body")
        if ("\t" in content or "\x00" in content or
                any(re.search(r"^" + key + r":", content, re.MULTILINE) is None for key in required)):
            raise ContractError(f"Invalid issue template text: {path}")
        result[path.name] = data
    return result


def document_runs(value):
    """Walk rendered run objects, including headings, groups and table cells."""
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            yield value
        else:
            for child in value.values():
                yield from document_runs(child)
    elif isinstance(value, list):
        for child in value:
            yield from document_runs(child)


def project_guides(root, identities, context, output):
    rows, errors, drops = [], [], 0
    for identity in identities:
        try:
            spec = guides.load_spec(root / "guides" / (identity + ".json"))
            if spec["id"] != identity:
                raise guides.GuideError(f"guide {identity}: spec ID differs")
            document = guides.render(spec, guide_queries.QUERIES, context)
        except guides.GuideError as exc:
            errors.append({"id": identity, "error": str(exc)})
            continue
        links = {}
        for run in document_runs(document):
            if "entity" not in run:
                continue
            key = run["entity"]
            if key not in context["rows"]:
                del run["entity"]
                drops += 1
            else:
                links[key] = {"name": context["names"][key]["name"],
                              "topic": context["rows"][key]["semantic"]["topic"]}
        data = packs.compact({"document": document, "links": links})
        sha = digest(data)
        path = f"data/{sha}.json"
        output("hub/" + path, data)
        rows.append({"id": identity, "title": document["title"], "dek": document["dek"],
                     "path": path, "sha256": sha, "bytes": len(data)})
    # ADR-0002 §5: scenery no harvest rule names is reported after every update.
    unmatched = sorted(set(guide_queries.other_scenery_sources(context).values()))
    return rows, {"count": len(rows), "dropped_links": drops, "errors": errors, "other_scenery": unmatched,
                  "features": context["features"]}


def history_rows(root, runs, current_state, topic_ids):
    """Summarize the latest capture of each of the four newest game versions."""
    selected = {}
    for order, run in enumerate(reversed(runs)):
        receipt = snapshots.read(root, run["snapshot_id"])
        build = int(receipt["steam"]["build_id"])
        version = receipt.get("game_version")
        # A capture that recorded no game version cannot be placed among versions. The early
        # captures of build 25548639 did this, and their older extractor would read as game changes.
        if not version:
            continue
        if version not in selected or (build, order) > selected[version][0]:
            selected[version] = ((build, order), run, receipt)

    rows = []
    present_by_row = []
    for _, run, receipt in sorted(selected.values(), key=lambda item: item[0], reverse=True)[:4]:
        state = current_state if run["snapshot_id"] == runs[0]["snapshot_id"] else history.load_state(root, run)
        present = {key: (entry["descriptor"]["topic"], entry["revision_id"])
                   for key, entry in state.items() if entry["status"] == "present"}
        topics = Counter(topic for topic, _ in present.values())
        captured = receipt.get("captured") or receipt.get("captured_at")
        rows.append({"snapshot_id": run["snapshot_id"], "game_version": receipt.get("game_version"),
                     "build_id": receipt["steam"]["build_id"],
                     "captured": captured[:10] if isinstance(captured, str) and re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T)", captured) else None,
                     "total": len(present), "topics": {topic: topics[topic] for topic in sorted(topic_ids)}, "changes": None})
        present_by_row.append(present)

    for index, newer in enumerate(present_by_row[:-1]):
        older = present_by_row[index + 1]
        changes = {kind: 0 for kind in ("new", "changed", "removed")}
        by_topic = {topic: {kind: 0 for kind in changes} for topic in sorted(topic_ids)}
        for key in newer.keys() - older.keys():
            changes["new"] += 1
            by_topic[newer[key][0]]["new"] += 1
        for key in older.keys() - newer.keys():
            changes["removed"] += 1
            by_topic[older[key][0]]["removed"] += 1
        for key in newer.keys() & older.keys():
            if newer[key][1] != older[key][1]:
                changes["changed"] += 1
                by_topic[newer[key][0]]["changed"] += 1
        rows[index]["changes"] = {**changes, "topics": by_topic}
    return rows


def biome_rows(context):
    """Count the progression guide's complete query results for each visible ring."""
    def named(link):
        return {"entity": link["entity"], "name": link["text"]}

    rows = []
    for ring in guide_queries.QUERIES["rings"](context, {}):
        biome = ring["biome"]
        biome = [named(link) for link in biome] if isinstance(biome, list) else (
            named(biome) if isinstance(biome, dict) else [])
        rows.append({"number": int(ring["number"]), "index": int(ring["index"]), "biome": biome,
                     **{field: len(guide_queries.QUERIES["ring." + field](context, ring))
                        for field in ("new_materials", "new_recipes", "new_benches", "exclusive_loot")}})
    return rows


def project_snapshot(root, project, run, stage, output, limit, known, explanations=None, *, registry, site, captured_runs):
    snapshot = run["snapshot_id"]
    state = history.load_state(root, run)
    models = extraction.artifact(root, run["models"])
    routes = {key: {"name": row["descriptor"]["name"], "topic": row["descriptor"]["topic"]} for key, row in state.items()}
    owners = {kind: repo["id"] for repo in project["repositories"] for kind in repo["owns"]}
    topics = [repo["id"] for repo in project["repositories"]]
    notes = defaultdict(list)
    for key, explanation in sorted((explanations or {}).items()):
        if explanation["entity"] in state and explanation["topic"] == state[explanation["entity"]]["descriptor"]["topic"]:
            notes[explanation["entity"]].append(explanation)
    backlinks = defaultdict(list)
    seen = set()
    for row in model.rows(models):
        key, semantic = row["entity_key"], row["semantic"]
        if key in seen or key not in state or state[key]["status"] != "present" or row["snapshot_id"] != snapshot:
            raise ContractError("Model membership does not match the pinned identity state")
        if semantic["topic"] != owners.get(semantic["kind"]) or digest(json_bytes(semantic)) != row["revision_id"] or row["revision_id"] != state[key]["revision_id"]:
            raise ContractError("Model ownership or semantic hash differs")
        seen.add(key)
        for link in semantic["relationships"]:
            for target in link["targets"] + link.get("technical_targets", []):
                if target not in routes or state[target]["status"] != "present":
                    raise ContractError("Model relation names an absent snapshot target")
                backlinks[target].append({"entity": key, **routes[key], "predicate": link["predicate"], "field": link["field"]})
    if seen != {key for key, row in state.items() if row["status"] == "present"}:
        raise ContractError("Model omitted a present identity observation")
    row = semantic = None  # Release the validation pass's last parsed row.

    # labels materializes its input; retain only the two components it joins,
    # never the full collection of semantic records.
    text = game_text.labels(row for row in model.rows(models)
                            if row.get("provenance", {}).get("component") in (
                                {"assembly": "UI", "class": "DynamicToolTipSet"},
                                {"assembly": "Language", "class": "Language_Text"}))
    receipt = snapshots.read(root, snapshot)
    guide_rows, guide_receipt = [], {"count": 0, "dropped_links": 0, "errors": [], "other_scenery": []}
    biomes = []
    def consume_context(context):
        nonlocal guide_rows, guide_receipt, biomes
        guide_rows, guide_receipt = project_guides(root, site.get("guides", []), context, output)
        biomes = biome_rows(context)
    player_names, players = player_projection(models, registry, text, snapshot,
        snapshot_metadata={"game_version": receipt.get("game_version") or "unknown", "build_id": receipt["steam"]["build_id"]},
        consume_context=consume_context)
    hub_search = {}
    maps = {topic: {kind: {} for kind in ("entries", "semantics", "provenance", "search", "backlinks", "cards", "player")} for topic in topics}
    counts = {topic: Counter() for topic in topics}
    groups = {topic: defaultdict(list) for topic in topics}
    for row in model.rows(models):
        key, semantic = row["entity_key"], row["semantic"]
        topic, ledger = semantic["topic"], state[key]
        data = maps[topic]
        data["semantics"][row["revision_id"]] = packs.compact(semantic)
        provenance = packs.compact(row["provenance"])
        provenance_id = digest(provenance)
        data["provenance"][provenance_id] = provenance
        links = {target: routes[target] for link in semantic["relationships"]
                 for target in link["targets"] + link.get("technical_targets", [])}
        reverse = {key + "/" + digest(packs.compact(link)): packs.compact(link) for link in backlinks[key]}
        data["backlinks"].update(reverse)
        record = {"entity_key": key, **routes[key], "kind": semantic["kind"], "status": "present",
                  "revision_id": row["revision_id"], "provenance_id": provenance_id,
                  "first_seen": ledger["first_seen"], "last_changed": ledger["last_changed"],
                  "last_data_checked": ledger["last_data_checked"], "last_verified": ledger["last_verified"],
                  "decision": ledger["decision"], "links": links, "backlink_count": len(reverse)}
        if semantic["kind"] in registry["kinds"]:
            card = packs.compact(presentation.card(registry, semantic["kind"], semantic, text, links))
            card_id = digest(card)
            data["cards"][card_id] = card
            record["card_id"] = card_id
        if key in players:
            record["player_id"] = digest(players[key])
            data["player"][record["player_id"]] = players[key]
        if notes[key]:
            record["explanations"] = notes[key]
        data["entries"][key] = packs.compact(record)
        # Full facts remain in semantic packs. Search stays compact and text only.
        primitive = {name: semantic.get("fact_labels", {}).get("/" + name, value)
                     for name, value in semantic["facts"].items() if value is None or isinstance(value, (str, int, float, bool))}
        brief = {"entity_key": key, **routes[key], "kind": semantic["kind"], "status": "present",
                 "source_id": row["provenance"]["source_id"], "preview": dict(list(primitive.items())[:6])}
        groups[topic][semantic["kind"]].append({**brief, **({"explanations": notes[key]} if notes[key] else {})})
        if player_names[key]["name"] != brief["name"]:
            brief.update(source_name=brief["name"], name=player_names[key]["name"])
        data["search"][key] = packs.compact(brief)
        hub_search[key] = packs.compact({field: brief[field] for field in
                                        ("entity_key", "name", "source_name", "kind", "topic") if field in brief})
        counts[topic][semantic["kind"]] += 1
    for key, ledger in state.items():
        if ledger["status"] == "present":
            continue
        topic = ledger["descriptor"]["topic"]
        record = {"entity_key": key, **routes[key], "kind": ledger["descriptor"]["kind"],
                  "status": ledger["status"], "last_seen": ledger["last_seen"],
                  "last_changed": ledger["last_changed"], "last_verified": ledger["last_verified"],
                  **({"superseded_by": ledger["superseded_by"]} if ledger.get("superseded_by") else {})}
        if notes[key]:
            record["explanations"] = notes[key]
        maps[topic]["entries"][key] = packs.compact(record)
        maps[topic]["search"][key] = packs.compact({name: value for name, value in record.items() if name != "explanations"})
    maps["hub"]["search"] = hub_search
    topic_counts = {topic: {"total": sum(kinds.values()), "kinds": dict(sorted(kinds.items()))}
                    for topic, kinds in counts.items()}
    changes_history = history_rows(root, captured_runs, state, topics)
    for topic, data in maps.items():
        writer = lambda name, value, topic=topic: output(f"{topic}/{name}", value)
        # Reuse whole single-card shards: a removed entry must not leave its card
        # in a later snapshot merely because a surviving card shared its shard.
        card_shards = [shard for key, value in sorted(data.pop("cards").items())
                       for shard in packs.reuse({key: value}, known[topic]["cards"], limit, writer)]
        player_shards = [shard for key, value in sorted(data.pop("player").items())
                         for shard in packs.reuse({key: value}, known[topic]["player"], limit, writer)]
        index = {"schema_version": 1, "snapshot_id": snapshot, "identity_run": run["run_id"],
                 "source_commit": run["source_commit"], "steam": receipt["steam"], "game_version": receipt["game_version"],
                 "game_version_status": receipt.get("game_version_status", "not-recorded-by-source-generator"),
                 "game_version_evidence": receipt.get("game_version_evidence", []),
                 "counts": dict(sorted(counts[topic].items())), "coverage": "partial", "verification": "not-performed",
                 "latest_available_build": receipt["latest_available_game_build"], "change_origin": run["change_origin"],
                 "cards": card_shards,
                 "player": player_shards,
                 **({"guides": guide_rows, "topic_counts": topic_counts, "history": changes_history, "biomes": biomes} if topic == "hub" else {}),
                 **{kind: packs.reuse(values, known[topic][kind], limit, writer) if kind in {"semantics", "provenance"}
                    else packs.write(values, limit, writer) for kind, values in data.items()}}
        writer(f"snapshots/{snapshot}.json", packs.compact(index))
    # Validation streams one topic at a time. Release construction buffers first
    # so parsed validation data does not coexist with the full projection.
    del data, maps, state, routes, backlinks, players, player_names, hub_search
    verified = validate_snapshot(stage, snapshot, topics)
    return {"snapshot_id": snapshot, "build_id": receipt["steam"]["build_id"], "game_version": receipt["game_version"], "identity_run": run["run_id"],
            "observations": verified, "guides": guide_receipt}, groups


def external_views(stage, project, observation, runs, limit, output):
    options = external_links.configuration(project)
    if not options or observation is None:
        return {}
    views = {}
    for topic, route in options["routes"].items():
        def rows():
            if not route["entity_prefixes"]:
                return
            site = within(stage, topic)
            for run in runs:
                snapshot = run["snapshot_id"]
                index = json.loads((site / "snapshots" / f"{snapshot}.json").read_bytes())
                for ref in index["search"]:
                    for row in load_maps(site, [ref]).values():
                        yield snapshot, row
        views[topic] = external_links.project_view(project, observation, topic, rows(), limit,
                                                   lambda name, value, topic=topic: output(f"{topic}/{name}", value))
    return views


def build(root, project, runs=None, max_pack_bytes=DEFAULT_PACK_BYTES, bases=None, cache_root=None, source=None):
    """Caller holds writer_lock. This writes staging only, not child repositories."""
    runs = versions(root) if runs is None else runs
    if not runs or len({run["snapshot_id"] for run in runs}) != len(runs):
        raise ContractError("Reader needs one identity run per selected snapshot")
    source = Path(source) if source else root / project.get("source", {}).get("default_path", "../HumanHostCodebase")
    checked, check_metrics = curation.run(root, project, source, runs)
    curated = {"run_id": checked["run_id"] if checked else None, "metrics": check_metrics,
               "exceptions": checked["exceptions"] if checked else Exceptions().report()}
    bases = bases or {repo["id"]: f"/{repo['id']}/" for repo in project["repositories"]}
    if set(bases) != {repo["id"] for repo in project["repositories"]} or any(not base.endswith("/") for base in bases.values()):
        raise ContractError("Reader bases must name every topic with a trailing slash")
    for base in bases.values():
        parsed = urlsplit(base)
        if parsed.query or parsed.fragment or parsed.username or parsed.password or ".." in parsed.path.split("/") or not (
                (parsed.scheme == "https" and parsed.netloc) or (not parsed.scheme and not parsed.netloc and base.startswith("/"))):
            raise ContractError("Reader base must be an HTTPS site or absolute local URL path")
    registry_path = root / "presentation/fields.json"
    registry_digest = digest(registry_path.read_bytes())
    registry = presentation.load(registry_path)
    site, hub_digests = hub_inputs(root)
    inputs = {"project": project, "runs": [digest(json_bytes(run)) for run in runs], "renderer": contract(),
              "presentation": registry_digest,
              **hub_digests,
              "receipts": [digest(json_bytes(snapshots.read(root, run["snapshot_id"]))) for run in runs],
              "bases": bases, "pack_bytes": max_pack_bytes, "availability": availability.latest(root, project),
              "external_articles": external_links.configured(root, project),
              "curation": checked["run_id"] if checked else None}
    candidate_id = digest(json_bytes(inputs))
    cache_root = Path(cache_root).resolve() if cache_root else within(root, ".local")
    if not cache_root.is_relative_to(within(root, ".local")):
        raise ContractError("Reader cache must remain inside the owning .local directory")
    destination = candidate_path(cache_root, candidate_id)
    pointer = within(cache_root, "reader-latest.json")
    if destination.exists():
        manifest = verify(destination, candidate_id)
        write_changed(pointer, json_bytes({"candidate_id": candidate_id}))
        return {"candidate_id": candidate_id, "path": str(destination), "bytes": manifest["total_bytes"], "reused": True, "curation": curated}
    prior, prior_path = None, None
    if pointer.exists():
        prior_id = json.loads(pointer.read_bytes())["candidate_id"]
        prior_path = candidate_path(cache_root, prior_id)
        prior = verify(prior_path, prior_id)
        if {k: v for k, v in prior["inputs"].items() if k not in {"availability", "external_articles"}} != {
                k: v for k, v in inputs.items() if k not in {"availability", "external_articles"}}:
            prior = None
    stage = within(cache_root, f"reader-stage/{uuid.uuid4().hex}")
    stage.mkdir(parents=True)
    files = {}

    def output(name, data):
        record = {"sha256": digest(data), "bytes": len(data)}
        if name in files:
            if files[name] != record:
                raise ContractError(f"Reader output collision: {name}")
            return
        # The directory is private, new staging. Its final rename is the atomic
        # boundary; per-file temporary suffixes add I/O and exceed Windows paths.
        target = within(stage, name)
        if os.name == "nt" and max(len(str(target)), len(str(within(destination, name)))) >= 260:
            raise ContractError("Reader output exceeds Windows path capacity; use a shorter wiki checkout path")
        target.parent.mkdir(parents=True, exist_ok=True)
        if prior and prior["files"].get(name) == record:
            os.link(within(prior_path, name), target)
            files[name] = record
            return
        with target.open("xb") as stream:
            stream.write(data)
        files[name] = record

    if prior:
        # Observation changes never revisit models or duplicate immutable packs.
        # Hard links are safe because candidates are immutable and verified before
        # reuse. New controls are written separately, never through shared inodes.
        configs, article_packs = {}, set()
        articles_changed = prior["inputs"].get("external_articles") != inputs["external_articles"]
        for repo in project["repositories"]:
            topic = repo["id"]
            configs[topic] = json.loads(within(prior_path, f"{topic}/reader.json").read_bytes())
            if articles_changed:
                article_packs.update(f"{topic}/{ref['path']}" for ref in (configs[topic].get("external_articles") or {}).get("entries", []))
        # A shared content-addressed leaf must survive if gameplay also uses it.
        for name in prior["files"]:
            if article_packs and "/snapshots/" in name:
                topic = name.split("/", 1)[0]
                saved_index = json.loads(within(prior_path, name).read_bytes())
                for kind in ("entries", "semantics", "provenance", "search", "backlinks", "cards", "player", "guides"):
                    article_packs.difference_update(f"{topic}/{ref['path']}" for ref in saved_index.get(kind, []))
        for name, record in prior["files"].items():
            source = within(prior_path, name)
            if name.endswith("/reader.json") or name in article_packs:
                continue
            elif "/reference/" in name:
                output(name, source.read_bytes().replace(("release=" + prior["candidate_id"]).encode(),
                                                         ("release=" + candidate_id).encode()))
            else:
                target = within(stage, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(source, target)
                files[name] = record
        views = (external_views(stage, project, inputs["external_articles"], runs, max_pack_bytes, output)
                 if articles_changed else {topic: config.get("external_articles") for topic, config in configs.items()})
        for topic, config in configs.items():
            config.update(candidate_id=candidate_id, availability=inputs["availability"], external_articles=views.get(topic))
            output(f"{topic}/reader.json", packs.compact(config))
        manifest = {**prior, "candidate_id": candidate_id, "inputs": inputs, "files": files,
                    "total_bytes": sum(record["bytes"] for record in files.values())}
        write_changed(stage / "candidate.json", json_bytes(manifest))
        verify(stage, candidate_id)
        if (contract() != inputs["renderer"] or availability.latest(root, project) != inputs["availability"]
                or digest(registry_path.read_bytes()) != inputs["presentation"]
                or hub_inputs(root)[1] != hub_digests
                or external_links.configured(root, project) != inputs["external_articles"]):
            raise ContractError("Reader inputs changed during observation projection")
        curation.ensure_definitions(root, project, checked)
        os.rename(stage, destination)
        write_changed(pointer, json_bytes({"candidate_id": candidate_id}))
        return {"candidate_id": candidate_id, "path": str(destination), "bytes": manifest["total_bytes"],
                "reused": False, "projection_reused": True, "curation": curated}

    projected, current_groups = {}, None
    all_groups = {repo["id"]: set() for repo in project["repositories"]}
    known = {repo["id"]: {"semantics": {}, "provenance": {}, "cards": {}, "player": {}} for repo in project["repositories"]}
    for index in range(len(runs) - 1, -1, -1):
        run = runs[index]
        # Revalidate pinned artifacts, even if a caller supplied the run.
        extraction.artifact(root, run["state"])
        extraction.artifact(root, run["models"])
        version, groups = project_snapshot(root, project, run, stage, output, max_pack_bytes, known,
                                           checked["snapshots"].get(run["snapshot_id"]) if checked else None,
                                           registry=registry, site=site, captured_runs=runs[index:])
        projected[run["snapshot_id"]] = version
        for topic, kinds in groups.items():
            all_groups[topic].update(kinds)
        if run is runs[0]:
            current_groups = groups
    projected = [projected[run["snapshot_id"]] for run in runs]
    views = external_views(stage, project, inputs["external_articles"], runs, max_pack_bytes, output)
    web = Path(__file__).parent / "web"
    font_files = {file.name: (file.read_bytes() if file.suffix == ".woff2" else
                             file.read_bytes().replace(b"\r\n", b"\n"))
                  for file in sorted((web / "fonts").iterdir()) if file.is_file()}
    font_metadata = {name: {"sha256": digest(data), "bytes": len(data)} for name, data in font_files.items()}
    font_path = "fonts/" + digest(json_bytes(font_metadata)) + "/"
    fonts = {"base": bases["hub"] + font_path, "files": font_metadata}
    for name, data in font_files.items():
        output("hub/" + font_path + name, data)
    topics = [{"id": repo["id"], "title": repo["title"], "base": bases[repo["id"]], "coverage": repo["coverage"]}
              for repo in project["repositories"]]
    for repo in project["repositories"]:
        topic = repo["id"]
        for file in sorted(web.iterdir()):
            if file.is_file():
                output(f"{topic}/{file.name}", file.read_bytes().replace(b"\r\n", b"\n"))
        output(f"{topic}/.nojekyll", b"")
        content = pages.shell(repo["title"], bases[topic], project.get("project", "Unofficial game reference"),
                              fonts_base=fonts["base"])
        output(f"{topic}/index.html", content)
        output(f"{topic}/404.html", content)
        output(f"{topic}/reader.json", packs.compact({"schema_version": 1, "candidate_id": candidate_id,
               "project": project.get("project", "Unofficial game reference"),
               "features": ["shard-directories-v1", "paged-captures-v1", "entrypoint-rollover-v1"],
               "availability": inputs["availability"],
               "fonts": fonts,
               # Every site needs the design data (colours, the report link); only the hub draws relationships.
               "site": site,
               **({"relationships": project.get("relationships", [])} if topic == "hub" else {}),
               "external_articles": views.get(topic),
               "topic": topic, "topics": topics, "versions": projected, "default_snapshot": projected[0]["snapshot_id"],
               "official_links": project["official_links"], "publication": "local-candidate"}))
        for kind in sorted(all_groups[topic]):
            output(f"{topic}/groups/{kind}/index.html", content)
        for kind, records in current_groups[topic].items():
            ordered = sorted(records, key=lambda row: (row["name"].casefold(), row["entity_key"]))
            for offset in range(0, len(ordered), 100):
                output(f"{topic}/reference/{kind}/{offset // 100 + 1:04d}.md",
                       pages.markdown(kind, ordered[offset:offset + 100], projected[0]["snapshot_id"], candidate_id, bases[topic]))
    current = projected[0]["snapshot_id"]
    hub_index = json.loads((stage / "hub/snapshots" / (current + ".json")).read_bytes())
    for ref in hub_index["guides"]:
        pack = json.loads((stage / "hub" / ref["path"]).read_bytes())
        markdown = guides.render_markdown(pack["document"], lambda key: pages.entry(
            bases[pack["links"][key]["topic"]], key, current, candidate_id))
        output(f"hub/reference/guides/{ref['id']}.md", markdown.encode("utf-8"))
    manifest = {"schema_version": 1, "candidate_id": candidate_id, "inputs": inputs,
                "versions": projected, "files": files, "total_bytes": sum(record["bytes"] for record in files.values()),
                "status": "validated-reader-candidate", "wiki_release": "not-created"}
    write_changed(stage / "candidate.json", json_bytes(manifest))
    verify(stage, candidate_id)
    if (contract() != inputs["renderer"] or availability.latest(root, project) != inputs["availability"]
            or digest(registry_path.read_bytes()) != inputs["presentation"]
            or hub_inputs(root)[1] != hub_digests
            or external_links.configured(root, project) != inputs["external_articles"]):
        raise ContractError("Reader inputs changed during generation")
    curation.ensure_definitions(root, project, checked)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.rename(stage, destination)
    write_changed(pointer, json_bytes({"candidate_id": candidate_id}))
    return {"candidate_id": candidate_id, "path": str(destination), "bytes": manifest["total_bytes"], "reused": False, "curation": curated}
