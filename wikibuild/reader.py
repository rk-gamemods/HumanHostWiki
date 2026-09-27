"""Project pinned selected models to an immutable static-reader candidate."""

from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

from . import availability, curation, external_links, extraction, history, model, packs, pages, snapshots
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
    paths = [folder / name for name in ("reader.py", "packs.py", "pages.py", "storage.py", "curation.py", "curated_rules.py", "source.py", "external_links.py", "mediawiki.py")]
    paths += sorted((folder / "web").glob("*"))
    return {path.relative_to(folder).as_posix(): digest(path.read_bytes().replace(b"\r\n", b"\n")) for path in paths}


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
    count = 0
    for topic in topics:
        site = within(stage, topic)
        index = json.loads((site / "snapshots" / f"{snapshot}.json").read_text(encoding="utf-8"))
        entries = load_maps(site, index["entries"])
        semantics = load_maps(site, index["semantics"])
        provenance = load_maps(site, index["provenance"])
        searches = load_maps(site, index["search"])
        backlinks = load_maps(site, index["backlinks"])
        if set(entries) != set(searches):
            raise ContractError("Search coverage differs from snapshot entries")
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
        for key, link in backlinks.items():
            if key.split("/", 1)[0] not in entries:
                raise ContractError("Reader backlink has no owning entry")
            targets.append((link["entity"], link["topic"]))
    if any(membership.get(key) != topic for key, topic in targets):
        raise ContractError("Reader relationship leaves its selected snapshot")
    return count


def project_snapshot(root, project, run, stage, output, limit, known, explanations=None):
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

    maps = {topic: {kind: {} for kind in ("entries", "semantics", "provenance", "search", "backlinks")} for topic in topics}
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
        if notes[key]:
            record["explanations"] = notes[key]
        data["entries"][key] = packs.compact(record)
        # Full facts remain in semantic packs. Search stays compact and text only.
        primitive = {name: value for name, value in semantic["facts"].items() if value is None or isinstance(value, (str, int, float, bool))}
        brief = {"entity_key": key, **routes[key], "kind": semantic["kind"], "status": "present",
                 "source_id": row["provenance"]["source_id"], "preview": dict(list(primitive.items())[:6])}
        data["search"][key] = packs.compact(brief)
        groups[topic][semantic["kind"]].append({**brief, **({"explanations": notes[key]} if notes[key] else {})})
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
    receipt = snapshots.read(root, snapshot)
    for topic, data in maps.items():
        writer = lambda name, value, topic=topic: output(f"{topic}/{name}", value)
        index = {"schema_version": 1, "snapshot_id": snapshot, "identity_run": run["run_id"],
                 "source_commit": run["source_commit"], "steam": receipt["steam"], "game_version": receipt["game_version"],
                 "game_version_status": receipt.get("game_version_status", "not-recorded-by-source-generator"),
                 "game_version_evidence": receipt.get("game_version_evidence", []),
                 "counts": dict(sorted(counts[topic].items())), "coverage": "partial", "verification": "not-performed",
                 "latest_available_build": receipt["latest_available_game_build"], "change_origin": run["change_origin"],
                 **{kind: packs.reuse(values, known[topic][kind], limit, writer) if kind in {"semantics", "provenance"}
                    else packs.write(values, limit, writer) for kind, values in data.items()}}
        writer(f"snapshots/{snapshot}.json", packs.compact(index))
    # Validation streams one topic at a time. Release construction buffers first
    # so parsed validation data does not coexist with the full projection.
    del data, maps, state, routes, backlinks
    verified = validate_snapshot(stage, snapshot, topics)
    return {"snapshot_id": snapshot, "build_id": receipt["steam"]["build_id"], "game_version": receipt["game_version"], "identity_run": run["run_id"],
            "observations": verified}, groups


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
    inputs = {"project": project, "runs": [digest(json_bytes(run)) for run in runs], "renderer": contract(),
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
                for kind in ("entries", "semantics", "provenance", "search", "backlinks"):
                    article_packs.difference_update(f"{topic}/{ref['path']}" for ref in saved_index[kind])
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
                or external_links.configured(root, project) != inputs["external_articles"]):
            raise ContractError("Reader inputs changed during observation projection")
        curation.ensure_definitions(root, project, checked)
        os.rename(stage, destination)
        write_changed(pointer, json_bytes({"candidate_id": candidate_id}))
        return {"candidate_id": candidate_id, "path": str(destination), "bytes": manifest["total_bytes"],
                "reused": False, "projection_reused": True, "curation": curated}

    projected, current_groups = {}, None
    all_groups = {repo["id"]: set() for repo in project["repositories"]}
    known = {repo["id"]: {"semantics": {}, "provenance": {}} for repo in project["repositories"]}
    for run in reversed(runs):
        # Revalidate pinned artifacts, even if a caller supplied the run.
        extraction.artifact(root, run["state"])
        extraction.artifact(root, run["models"])
        version, groups = project_snapshot(root, project, run, stage, output, max_pack_bytes, known,
                                           checked["snapshots"].get(run["snapshot_id"]) if checked else None)
        projected[run["snapshot_id"]] = version
        for topic, kinds in groups.items():
            all_groups[topic].update(kinds)
        if run is runs[0]:
            current_groups = groups
    projected = [projected[run["snapshot_id"]] for run in runs]
    views = external_views(stage, project, inputs["external_articles"], runs, max_pack_bytes, output)
    web = Path(__file__).parent / "web"
    topics = [{"id": repo["id"], "title": repo["title"], "base": bases[repo["id"]], "coverage": repo["coverage"]}
              for repo in project["repositories"]]
    for repo in project["repositories"]:
        topic = repo["id"]
        for file in web.iterdir():
            output(f"{topic}/{file.name}", file.read_bytes().replace(b"\r\n", b"\n"))
        output(f"{topic}/.nojekyll", b"")
        content = pages.shell(repo["title"], bases[topic])
        output(f"{topic}/index.html", content)
        output(f"{topic}/404.html", content)
        output(f"{topic}/reader.json", packs.compact({"schema_version": 1, "candidate_id": candidate_id,
               "features": ["shard-directories-v1", "paged-captures-v1", "entrypoint-rollover-v1"],
               "availability": inputs["availability"],
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
    manifest = {"schema_version": 1, "candidate_id": candidate_id, "inputs": inputs,
                "versions": projected, "files": files, "total_bytes": sum(record["bytes"] for record in files.values()),
                "status": "validated-reader-candidate", "wiki_release": "not-created"}
    write_changed(stage / "candidate.json", json_bytes(manifest))
    verify(stage, candidate_id)
    if (contract() != inputs["renderer"] or availability.latest(root, project) != inputs["availability"]
            or external_links.configured(root, project) != inputs["external_articles"]):
        raise ContractError("Reader inputs changed during generation")
    curation.ensure_definitions(root, project, checked)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.rename(stage, destination)
    write_changed(pointer, json_bytes({"candidate_id": candidate_id}))
    return {"candidate_id": candidate_id, "path": str(destination), "bytes": manifest["total_bytes"], "reused": False, "curation": curated}
