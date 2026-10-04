"""Validate snapshot shards and their cross-topic reader targets."""

from collections import Counter
import json
import re

from . import packs
from .storage import ContractError, digest, json_bytes, within

ENTITY = re.compile(r"^e-[0-9a-f]{32}$")


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


def guide_targets_leave_snapshot(linked, links, present):
    return linked != links.keys() or any(key not in present or link != {
        "name": present[key]["name"], "topic": present[key]["topic"]} for key, link in links.items())


def load_snapshot_maps(site, index):
    targets = []
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
    return entries, semantics, provenance, searches, backlinks, players, targets

def validate_explanations(key, topic, snapshot, notes):
    for note in notes:
        if (note["entity"] != key or note["topic"] != topic or note["snapshot_id"] != snapshot
                or note["status"] not in {"passed", "unverified"}):
            raise ContractError("Explanation leaves its owning entry or snapshot")
        if note["status"] == "passed" and (not isinstance(note["text"], str) or not note["last_verified"]
                                         or note["last_verified"]["snapshot_id"] != snapshot or note["reasons"]):
            raise ContractError("Passed explanation lacks its successful check")
        if note["status"] == "unverified" and (note["text"] is not None or not note["reasons"]):
            raise ContractError("Failed explanation lacks its reason")

def validate_entries(topic, snapshot, entries, semantics, provenance, backlinks, players, membership, present, targets):
    kinds, count = Counter(), 0
    for key, record in entries.items():
        if key in membership or record["topic"] != topic or not ENTITY.fullmatch(key):
            raise ContractError("Reader has duplicate or invalid canonical ownership")
        membership[key] = topic
        validate_explanations(key, topic, snapshot, record.get("explanations", []))
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
    total = {"total": sum(kinds.values()), "kinds": dict(sorted(kinds.items()))}
    for key, link in backlinks.items():
        if key.split("/", 1)[0] not in entries:
            raise ContractError("Reader backlink has no owning entry")
        targets.append((link["entity"], link["topic"]))
    return count, total

def validate_guides(stage, hub_index, present):
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
        if guide_targets_leave_snapshot(linked, pack["links"], present):
            raise ContractError("Guide links leave their present snapshot entries")


def validate_snapshot(stage, snapshot, topics):
    """Validate cross-topic entity membership without loading all facts at once."""
    membership, targets = {}, []
    present, totals, hub_index, hub_search = {}, {}, None, None
    count = 0
    for topic in topics:
        site = within(stage, topic)
        index = json.loads((site / "snapshots" / f"{snapshot}.json").read_text(encoding="utf-8"))
        entries, semantics, provenance, searches, backlinks, players, player_targets = load_snapshot_maps(site, index)
        targets.extend(player_targets)
        if topic == "hub" and "topic_counts" in index:
            hub_index, hub_search = index, searches
        elif set(entries) != set(searches):
            raise ContractError("Search coverage differs from snapshot entries")
        topic_count, totals[topic] = validate_entries(topic, snapshot, entries, semantics, provenance, backlinks,
                                                     players, membership, present, targets)
        count += topic_count
        # Release topic facts before the next topic's loading phase.
        del entries, semantics, provenance, searches, backlinks, players, player_targets
    if any(membership.get(key) != topic for key, topic in targets):
        raise ContractError("Reader relationship leaves its selected snapshot")
    if hub_index is not None:
        if hub_search != present or hub_index["topic_counts"] != totals:
            raise ContractError("Hub search or topic counts differ from present entries")
        validate_guides(stage, hub_index, present)
    return count
