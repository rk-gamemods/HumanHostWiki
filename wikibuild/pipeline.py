"""Operator-invoked stages, durable recovery and a final content-exception report."""

import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from time import perf_counter
import traceback

from . import availability, curation, external_links, extraction, history, physical, reader, reader_retention, release, release_retention, snapshots
from .storage import ContractError, digest, json_bytes, within, write_changed


def immutable(path, value):
    data = json_bytes(value)
    if path.exists() and path.read_bytes() != data:
        raise ContractError(f"Pipeline receipt differs: {path}")
    write_changed(path, data)


def read(root, run_id):
    if not isinstance(run_id, str) or len(run_id) != 64 or any(c not in "0123456789abcdef" for c in run_id):
        raise ContractError("Invalid pipeline run identity")
    result = json.loads(within(root, f".local/pipeline/runs/{run_id}.json").read_text(encoding="utf-8"))
    content = {key: value for key, value in result.items() if key != "run_id"}
    if result.get("schema_version") != 1 or result.get("run_id") != run_id or digest(json_bytes(content)) != run_id:
        raise ContractError("Pipeline result identity or schema differs")
    return result


def report(reports, previous=None):
    """Bounded examples come from stage reports; keep stage ownership explicit."""
    old = {group["key"]: group for group in (previous or {}).get("groups", [])}
    groups = []
    for stage, source in sorted(reports.items()):
        if source.get("kind") != "unresolved-wiki-content":
            raise ContractError(f"Invalid content exception report from {stage}")
        for group in source["groups"]:
            row = {**group, "stage": stage, "key": stage + ":" + group["id"]}
            prior = old.get(row["key"])
            row["change"] = ("new" if prior is None else "unchanged" if row == {
                key: value for key, value in prior.items() if key != "change"} else "changed")
            groups.append(row)
    groups.sort(key=lambda row: (row["topic"], row["stage"], row["code"], row["pattern"]))
    keys = {row["key"] for row in groups}
    return {"schema_version": 1, "kind": "unresolved-wiki-content", "groups": groups,
            "group_count": len(groups), "occurrences": sum(row["occurrences"] for row in groups),
            "resolved_since_previous": sorted(set(old) - keys),
            "next_action": "Present these exceptions to the user and ask how to proceed."
            if groups else "No unresolved content in the implemented scope."}


def run(root, project, source, progress=None):
    """Caller holds writer_lock. Stage receipts survive a later stage's failure."""
    started = datetime.now(timezone.utc)
    clock = perf_counter()
    timings, stage_clock = {}, None
    status, failed_stage = "execution-failure", None

    def enter(name):
        nonlocal stage, stage_clock
        now = perf_counter()
        if stage_clock is not None:
            timings[stage] = now - stage_clock
        stage, stage_clock = name, now

    stage, completed, reports, metrics = "resume", {}, {}, {}
    previous, request_key, receipt = None, None, None
    try:
        source = Path(source).resolve()
        pointer = within(root, ".local/pipeline/latest.json")
        current = read(root, json.loads(pointer.read_text())["run_id"]) if pointer.exists() else None
        enter("register")
        if progress:
            progress(stage)
        receipt = snapshots.register(root, project, source)
        completed[stage] = {"snapshot_id": receipt["snapshot_id"], "source_commit": receipt["source_commit"]}
        enter("availability")
        observed, metrics[stage] = availability.refresh(root, project, receipt["steam"], progress)
        if observed:
            completed[stage] = {"status": observed["status"], "observation_id": digest(json_bytes(observed))}
        enter("external-articles")
        article_options = external_links.configuration(project)
        articles = None
        if article_options:
            if progress:
                progress(stage)
            articles, metrics[stage] = external_links.refresh(root, article_options["source"], progress,
                cache_seconds=article_options["cache_seconds"], retry_seconds=article_options["retry_seconds"])
            completed[stage] = {"observation_id": digest(json_bytes(articles)), **external_links.summary(articles)}
        contracts = {"pipeline": digest(Path(__file__).read_bytes().replace(b"\r\n", b"\n")),
                     "availability": availability.contract(), "retention": release_retention.contract(),
                     "reader_retention": reader_retention.contract(),
                     "external_articles": external_links.contract(),
                     "extraction": extraction.contract(root, project), "identity": history.contract(),
                     "reader": reader.contract(), "release": release.contract()}
        reviewed = history.corrections(root)
        authored = curation.definition_inputs(curation.definitions(root, project))
        request_key = digest(json_bytes([receipt, project, contracts, reviewed, observed, articles, authored]))
        request_path = within(root, f".local/pipeline/requests/{request_key}.json")
        if request_path.exists():
            request = json.loads(request_path.read_text(encoding="utf-8"))
            if request.get("request_key") != request_key:
                raise ContractError("Pipeline request identity differs")
            baseline = request["previous_run"]
            if current and current["request_key"] == request_key and current["previous_run"] != baseline:
                raise ContractError("Pipeline request baseline differs from its completed result")
            if current and current["request_key"] != request_key and current["run_id"] != baseline:
                raise ContractError("An earlier pipeline request cannot rewind later results")
            if not current and baseline:
                raise ContractError("Pipeline last-success pointer is missing; preserve and investigate receipts")
            previous = read(root, baseline) if baseline else None
        else:
            previous = current
            immutable(request_path, {"request_key": request_key, "previous_run": current["run_id"] if current else None})

        enter("normalize")
        if progress:
            progress(stage)
        extracted, metrics[stage] = extraction.run(root, project, source, receipt)
        completed[stage] = {"run_id": extracted["run_id"], "counts": extracted["counts"]}
        reports[stage] = json.loads(extraction.artifact(root, extracted["exceptions"]).read_text(encoding="utf-8"))
        enter("identity")
        if progress:
            progress(stage)
        normalized, metrics[stage] = history.run(root, source, receipt, extracted)
        completed[stage] = {"run_id": normalized["run_id"], "counts": normalized["counts"]}
        reports[stage] = normalized["exceptions"]
        enter("project")
        if progress:
            progress(stage)
        projected = reader.build(root, project, bases=release.bases(project), source=source,
                                 max_pack_bytes=min(reader.DEFAULT_PACK_BYTES, physical.budgets(project).file_bytes))
        metrics["curation"] = projected["curation"]["metrics"]
        reports["curation"] = projected["curation"]["exceptions"]
        completed[stage] = {"candidate_id": projected["candidate_id"], "bytes": projected["bytes"]}
        metrics[stage] = {"reused": projected["reused"]}
        if projected.get("projection_reused"):
            metrics[stage]["projection_reused"] = True
        enter("verify")
        if progress:
            progress(stage)
        # Each stage validates its own artifacts, including when reusing them.
        # These final checks establish the common input, not gameplay verification.
        extraction.ensure_source(source, receipt["source_commit"])
        if contracts != {"pipeline": digest(Path(__file__).read_bytes().replace(b"\r\n", b"\n")),
                         "availability": availability.contract(), "retention": release_retention.contract(),
                         "reader_retention": reader_retention.contract(),
                         "external_articles": external_links.contract(),
                         "extraction": extraction.contract(root, project), "identity": history.contract(),
                         "reader": reader.contract(), "release": release.contract()}:
            raise ContractError("Pipeline rules changed during processing")
        if history.corrections(root) != reviewed:
            raise ContractError("Reviewed mappings changed during processing")
        if availability.latest(root, project) != observed:
            raise ContractError("Availability evidence changed during processing")
        if external_links.configured(root, project) != articles:
            raise ContractError("External article evidence changed during processing")
        if curation.definition_inputs(curation.definitions(root, project)) != authored:
            raise ContractError("Curated definitions changed during processing")
        completed[stage] = {"scope": "stage-artifacts-and-stable-source", "gameplay_verified": False}
        enter("release")
        if progress:
            progress(stage)
        released, metrics[stage] = release.run(root, project, projected)
        completed[stage] = {"release_id": released["release_id"], "publication": released["publication"]}
        enter("retention")
        if progress:
            progress(stage)
        metrics[stage] = release_retention.run(root)
        enter("reader-retention")
        if progress:
            progress(stage)
        metrics[stage] = reader_retention.run(root)
        content_report = report(reports, previous["exceptions"] if previous else None)
        remaining = []
        if content_report["group_count"]:
            remaining.append("content-exceptions")
        if articles and (completed["external-articles"]["unresolved"] or not completed["external-articles"]["inventory_complete"]):
            remaining.append("external-article-issues")
        remaining.append("publish")
        next_step = f"After successful rehearsal: py -3 wiki.py publish --release {released['release_id']}"
        result = {"schema_version": 1, "request_key": request_key,
                  "previous_run": previous["run_id"] if previous else None,
                  "source_commit": receipt["source_commit"], "snapshot_id": receipt["snapshot_id"],
                  "diff_base": previous["source_commit"] if previous else None,
                  "contracts": contracts, "completed": completed,
                  "exceptions": content_report,
                  "status": "git-release-ready", "wiki_release": released["release_id"],
                  "release_id": released["release_id"], "next_step": next_step,
                  "remaining": remaining}
        run_id = digest(json_bytes(result))
        result["run_id"] = run_id
        enter("promote")
        immutable(within(root, f".local/pipeline/runs/{run_id}.json"), result)
        read(root, run_id)
        write_changed(pointer, json_bytes({"run_id": run_id}))
        invocation = {"run_id": run_id, "snapshot_id": result["snapshot_id"], "status": result["status"],
                "report": str(within(root, f".local/pipeline/runs/{run_id}.json")),
                "reader": projected["path"], "exception_groups": result["exceptions"]["group_count"],
                "wiki_release": result["wiki_release"], "release_id": result["release_id"],
                "next_step": result["next_step"], "remaining": result["remaining"], "metrics": metrics,
                "timings": timings}
        status = result["status"]
        return invocation
    except (Exception, KeyboardInterrupt) as exc:
        failed_stage = stage
        if stage_clock is not None:
            timings[stage] = perf_counter() - stage_clock
            stage_clock = None
        if hasattr(exc, "publication_timing"):
            metrics.setdefault("publish", {})["timing"] = exc.publication_timing
        location = None
        repository = Path(__file__).resolve().parent.parent
        for frame in traceback.extract_tb(exc.__traceback__):
            try:
                relative = Path(frame.filename).resolve().relative_to(repository)
            except ValueError:
                continue
            location = {"path": relative.as_posix(), "function": frame.name, "line": frame.lineno}
        failure = {"schema_version": 1, "kind": "execution-failure", "request_key": request_key,
                   "snapshot_id": receipt["snapshot_id"] if receipt else None, "failed_stage": stage,
                   "completed": completed, "error": {"type": type(exc).__name__, "message": str(exc), "location": location},
                   "content_exceptions": report(reports),
                   "next_action": "Report the execution failure separately; diagnose and repair, then rerun the normal command."}
        failure_path = within(root, f".local/pipeline/failures/{digest(json_bytes(failure))}.json")
        try:
            immutable(failure_path, failure)
        except (OSError, ValueError) as save_error:
            failure_error = ContractError(f"Wiki stage {stage} failed: {exc}. Failure receipt could not be saved: {save_error}")
        else:
            failure_error = ContractError(f"Wiki stage {stage} failed: {exc}. Failure report: {failure_path}")
        failure_error.timings, failure_error.metrics = timings, metrics
        raise failure_error from exc
    finally:
        if stage_clock is not None:
            timings[stage] = perf_counter() - stage_clock
        total = perf_counter() - clock
        if failed_stage is None and status != "execution-failure":
            invocation["total_seconds"] = total
        try:
            finished = datetime.now(timezone.utc)
            timing_path = within(root, f".local/pipeline/timings/{finished.strftime('%Y%m%dT%H%M%S.%fZ')}-{status}.json")
            timing_path.parent.mkdir(parents=True, exist_ok=True)
            with timing_path.open("xb") as output:
                output.write(json_bytes({"started_utc": started.isoformat(), "finished_utc": finished.isoformat(),
                    "total_seconds": total, "stages": timings, "failed_stage": failed_stage,
                    "publication": metrics.get("publish", {}).get("timing", {})}))
        except (Exception, KeyboardInterrupt) as timing_error:
            try:
                print(f"Wiki timing could not be saved: {timing_error}", file=sys.stderr)
            except (Exception, KeyboardInterrupt):
                pass  # Timing is diagnostic; it must never change the run's outcome.


def operator_report(root, result):
    saved = read(root, result["run_id"])
    lines = [f"Wiki supported stages completed for {saved['snapshot_id']}.",
             (f"Status: published at {saved['completed']['publish']['hub']}."
              if saved["status"] == "published" else "Status: local Git release ready."),
             f"Git release: {saved['wiki_release']}",
             f"Report: {result['report']}", f"Reader: {result['reader']}",
             f"Unresolved content: {saved['exceptions']['group_count']} groups, {saved['exceptions']['occurrences']} occurrences."]
    receipt = snapshots.read(root, saved["snapshot_id"])
    lines.insert(5, f"Application version: {receipt['game_version'] or 'unknown'} ({receipt['game_version_status']}).")
    if "availability" in saved["completed"]:
        observed = availability.read(root, saved["completed"]["availability"]["observation_id"])
        lines.insert(6, availability.describe(observed, receipt["steam"]))
        if observed["status"] == "unavailable":
            lines.insert(7, f"Availability check failure detail: {within(root, '.local/availability-error.json')}")
    for group in saved["exceptions"]["groups"]:
        lines.append(f"- [{group['topic']}/{group['stage']}] {group['code']}: {group['pattern']} "
                     f"({group['occurrences']}; {group['change']})")
    articles = saved["completed"].get("external-articles")
    if articles:
        lines.append("External article checks: " + ", ".join(f"{count} {status}" for status, count in sorted(articles["counts"].items())))
        if not articles["inventory_complete"]:
            lines.append("External article index unavailable or incomplete; missing articles could not be confirmed.")
        for row in articles["unresolved"]:
            lines.append(f"- [external-articles] {row['title']}: {row['reason']} (revision {row['revision']})")
        if articles["unresolved"] or not articles["inventory_complete"]:
            lines.append("Present these external article issues to the user and ask how to proceed.")
    lines.append(saved["exceptions"]["next_action"])
    if "next_step" in saved:
        lines.append(saved["next_step"])
    for retained in result.get("metrics", {}).get("retention", {}).get("retained", []):
        lines.append(f"Staging cleanup issue [{retained['stage']}]: {retained['reason']}")
    for retained in result.get("metrics", {}).get("reader-retention", {}).get("retained", []):
        lines.append(f"Reader cache cleanup issue [{retained['candidate']}]: {retained['reason']}")
    if "timings" in result:
        lines.extend(["", "Time", f"Total: {result['total_seconds']:.2f} s wall-clock."])
        for stage, seconds in result["timings"].items():
            lines.append(f"- {stage}: {seconds:.2f} s")
        timing = result.get("metrics", {}).get("publish", {}).get("timing", {})
        rows = dict(timing.get("repositories", {}))
        rows.update({f"{name} (rollback)": row for name, row in timing.get("rollback", {}).items()})
        categories = [("Upload (pushes)", lambda row: row["push_main"] + row["push_pages"]),
                      ("GitHub Pages processing", lambda row: row["pages_build"]),
                      ("Public verification", lambda row: row["verify"]),
                      ("Other publish work", lambda row: max(0.0, row["total"] - row["push_main"] -
                       row["push_pages"] - row["pages_build"] - row["verify"]))]
        for label, seconds in categories:
            values = {name: seconds(row) for name, row in rows.items()}
            slowest = max(values, key=values.get) if values else None
            detail = f"{slowest}, {values[slowest]:.2f} s" if slowest else "none"
            lines.append(f"Publish {label}: {sum(values.values()):.2f} repository-seconds; slowest repository: {detail}.")
        phases = timing.get("phases", {})
        parallel = sum(seconds for name, seconds in phases.items() if name.startswith("topics-") or name == "current")
        lines.append(f"Publish parallel phases: {parallel:.2f} s wall-clock.")
        for name, seconds in phases.items():
            lines.append(f"- publish {name}: {seconds:.2f} s wall-clock")
        lines.append(f"Publish prepare: {timing.get('prepare', 0.0):.2f} s; resume: {timing.get('resume', 0.0):.2f} s wall-clock.")
        deployment = sum(seconds for name, seconds in phases.items()
                         if name.startswith("topics-") or name in {"hub", "rollback", "current"})
        overhead = max(0.0, result["timings"].get("publish", 0.0) - deployment)
        lines.append(f"Other publish work outside deployment phases: {overhead:.2f} s wall-clock.")
        lines.append("Per-repository sums can exceed wall-clock when parallel workers overlap; category sums are not a wall-clock split.")
    return "\n".join(lines) + "\n"
