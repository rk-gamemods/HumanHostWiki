#!/usr/bin/env python3
"""Human Host Wiki local workspace commands. Python standard library only."""

import argparse
import os
from pathlib import Path
import sys
import threading
import time

from wikibuild import bounded, extraction, history, manifest, navigation, pipeline, publication, reader, release, run_timing, snapshots, storage, workspace
from wikibuild.storage import ContractError, json_bytes, within, writer_lock, write_changed

# Backstop for every wait without its own bound. A normal update takes minutes; the
# slowest legitimate publication (every topic at its 30-minute Pages deadline) is
# about two hours.
UPDATE_DEADLINE = 4 * 3600
CLEANUP_GRACE = 60
TIMING_CLAIM_SECONDS = 5
_cleanup_files = set()
_cleanup_lock = threading.Lock()


def register_cleanup(path):
    """Register a command-owned temporary file, never journaled staging."""
    path = Path(path).absolute()
    with _cleanup_lock:
        _cleanup_files.add(path)
    return path


def unregister_cleanup(path):
    with _cleanup_lock:
        _cleanup_files.discard(Path(path).absolute())


def cleanup_registered_files():
    with _cleanup_lock:
        paths = list(_cleanup_files)
    errors = []
    for path in paths:
        try:
            path.unlink(missing_ok=True)
            unregister_cleanup(path)
        except OSError as exc:
            errors.append(f"temporary file {path}: {exc}")
    return errors


def deadline(seconds, command, stop=os._exit, timing=None, report=False):
    """Supervise timeout cleanup, then exit 124 even if cleanup blocks.

    Stages remain journaled; failed publications must be abandoned before a fresh run.
    The returned Timer retains cancel/join compatibility with existing callers.
    """
    expired = threading.Event()

    def expire():
        # Claim synchronously: a delayed diagnostic worker cannot lose to success
        # and still terminate that successfully finalized command with exit 124.
        expires = time.monotonic() + CLEANUP_GRACE
        errors = []
        claimed = timing is None
        if timing is not None:
            acquired = timing.lock.acquire(timeout=min(TIMING_CLAIM_SECONDS, CLEANUP_GRACE))
            if acquired:
                try:
                    if not timing.claim("timed-out"):
                        return
                    claimed = True
                except BaseException as exc:
                    errors.append(f"timeout timing record: timing could not be recorded: {exc}")
                finally:
                    timing.lock.release()
            else:
                errors.append("timeout timing record: recorder lock was unavailable; timing could not be recorded")
        # Main must await cleanup even when no recorder state could be claimed.
        expired.set()
        previous = bounded.begin_shutdown()
        pending = {"owned child trees", "writer owner metadata", "registered temporary files"}

        def clean():
            for label, action in (("owned child trees", bounded.terminate_all),
                                  ("writer owner metadata", storage.cleanup_writer_owners),
                                  ("registered temporary files", cleanup_registered_files)):
                try:
                    errors.extend(action())
                except BaseException as exc:
                    errors.append(f"{label}: {exc}")
                finally:
                    pending.discard(label)

        try:
            cleanup = threading.Thread(target=clean, name="wiki-timeout-cleanup", daemon=True)
            cleanup.start()
            attempt = None
            if timing is not None and claimed:
                def save_timeout():
                    try:
                        timing.finish("timed-out")
                        if report and timing.record is not None:
                            print(run_timing.table(timing.record), flush=True)
                    except (Exception, KeyboardInterrupt) as exc:
                        run_timing.warning(f"Wiki timeout timing could not be saved: {exc}")
                # Diagnostics must not defeat the watchdog on a blocked filesystem
                # while another thread is already saving the selected terminal record.
                attempt = threading.Thread(target=save_timeout, name="wiki-timeout-timing", daemon=True)
                attempt.start()
            cleanup.join(max(0.0, expires - time.monotonic()))
            if attempt is not None:
                attempt.join(min(1.0, max(0.0, expires - time.monotonic())))
                if attempt.is_alive():
                    errors.append("timeout timing record: save did not finish")
            errors.extend(f"{label}: cleanup did not finish within {CLEANUP_GRACE:g}s" for label in sorted(pending))

            def diagnostic():
                for error in errors:
                    print(f"WARNING: Wiki timeout could not clean {error}", file=sys.stderr, flush=True)
                print(f"ERROR: wiki {command} exceeded its {seconds / 3600:g}-hour deadline and was stopped. "
                      + ("Run py -3 wiki.py abandon-publication before rehearsing and publishing afresh."
                         if command == "publish" else "Its stages are journaled; rerun the normal command to recover."),
                      file=sys.stderr, flush=True)

            # A blocked diagnostic pipe must not defeat the cleanup grace either.
            reporter = threading.Thread(target=diagnostic, name="wiki-timeout-report", daemon=True)
            reporter.start()
            reporter.join(1)
        finally:
            try:
                stop(124)
            finally:
                bounded.end_shutdown(previous)
    timer = threading.Timer(seconds, expire)
    timer.expired = expired
    timer.daemon = True
    timer.start()
    return timer


def run(root, args, timing=None):
    if args.command == "timing":
        return run_timing.latest(root, args.last)
    if args.command not in {"update", "publish"}:
        return _run(root, args)
    timing = timing or run_timing.Recorder(root, args.command, getattr(args, "release", None),
                                         getattr(args, "capture_timing", None))
    outcome, result = "failed", None
    try:
        result = _run(root, args, timing)
        outcome = "succeeded"
        return result
    finally:
        timing.finish(outcome, result)


def _run(root, args, timing=None):
    project = manifest.load(root)
    if args.command == "validate":
        states = [workspace.inspect(root, repo) for repo in workspace.repositories(root, project)]
        return {"valid": True, "repositories": len(states), "pipeline": manifest.stage_order(project),
                "checkout_states": {state["id"]: state["state"] for state in states}}
    if args.command == "status":
        return {"repositories": [workspace.inspect(root, repo) for repo in workspace.repositories(root, project)]}
    if args.command == "publication-pins":
        return publication.pin_report(root, workspace.repositories(root, project))
    if args.command == "plan":
        return {"stages": project["pipeline"], "note": "The decompile command runs capture, selected extraction, identity history, rendering, capacity allocation and a coordinated local release, followed by release and reader retention. Publication is a separate operator step: rehearse the explicit release against live state, then run py -3 wiki.py publish --release <id> from clean, merged, CI-green main. See docs/PUBLICATION.md for the gate and docs/ACCEPTANCE.md for delivery evidence."}
    if args.command == "check-lock":
        result = workspace.checkout_lock(root, project, check=True)
        return {"lock": "current", "repositories": len(result["repositories"])}
    if args.command == "map":
        output = within(root, "docs/REPOSITORIES.md")
        data = manifest.repository_map(project)
        if args.check:
            if not output.exists() or output.read_bytes() != data:
                raise ContractError("Repository map is stale; run py -3 wiki.py map")
            return {"map": "current"}
        with writer_lock(root):
            changed = write_changed(output, data)
        return {"map": str(output), "changed": changed}
    with writer_lock(root):
        if args.command == "abandon-publication":
            return publication.abandon(root)
        if args.command == "publish":
            identity = args.release
            result, metrics = publication.run(root, project, release.read(root, identity),
                progress=lambda message: print(message, file=sys.stderr, flush=True), timing_sink=timing)
            return {"status": result["status"], "release_id": identity, "hub": result.get("hub"), "metrics": metrics}
        if args.command == "update":
            source = Path(args.source) if args.source else root / project["source"]["default_path"]
            return pipeline.run(root, project, source, progress=lambda stage: print(f"Wiki: {stage}", file=sys.stderr, flush=True), timing_sink=timing)
        if args.command == "lock":
            result = workspace.checkout_lock(root, project)
            return {"lock": result["kind"], "repositories": len(result["repositories"])}
        if args.command == "init-repositories":
            return {"created": workspace.initialize(root, project), "remotes_created": 0,
                    "note": "New repositories contain uncommitted seed files; review and commit them locally."}
        if args.command in {"refresh", "extract", "normalize"}:
            source = Path(args.source) if args.source else root / project["source"]["default_path"]
            receipt = snapshots.register(root, project, source)
            if args.command in {"extract", "normalize"}:
                result, metrics = extraction.run(root, project, source, receipt)
                if args.command == "normalize":
                    normalized, history_metrics = history.run(root, source, receipt, result)
                    return {"identity": normalized, "metrics": history_metrics,
                            "extraction": {"run_id": result["run_id"], "exceptions": result["exceptions"], "metrics": metrics}}
                return {**result, "metrics": metrics}
            return {"snapshot_id": receipt["snapshot_id"], "status": receipt["status"],
                    "wiki_verification": receipt["wiki_verification"], "game_version": receipt["game_version"]}
        if args.command == "build":
            receipt = snapshots.read(root, args.snapshot) if args.snapshot else None
            return navigation.build(root, project, receipt)
        if args.command == "reader":
            return reader.build(root, project)
    raise ContractError("Unknown command")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["validate", "status", "plan", "init-repositories", "lock", "check-lock"]:
        sub.add_parser(command)
    sub.add_parser("publish", help="Publish a rehearsed release from clean, CI-green main").add_argument("--release", required=True)
    sub.add_parser("abandon-publication", help="Scrap an incomplete publication journal locally; no remote calls")
    sub.add_parser("publication-pins", help="Report unprovenanced publication pins and manual retirement commands; read-only")
    sub.add_parser("timing", help="Show saved run timings without changing state").add_argument("--last", type=int, default=1)
    sub.add_parser("map").add_argument("--check", action="store_true")
    refresh = sub.add_parser("refresh", help="Register the current local catalog input; does not re-extract game data")
    refresh.add_argument("--source", help="Existing local codebase repository; default from project.json")
    extract = sub.add_parser("extract", help="Extract supported facts and report exceptions; does not publish")
    extract.add_argument("--source", help="Existing local codebase repository; default from project.json")
    normalize = sub.add_parser("normalize", help="Reconcile selected identities and semantic revisions; does not publish")
    normalize.add_argument("--source", help="Existing local codebase repository; default from project.json")
    build = sub.add_parser("build", help="Build a local architecture/navigation preview, not gameplay articles")
    build.add_argument("--snapshot", help="Registered snapshot ID for the preview provenance banner")
    sub.add_parser("reader", help="Project normalized snapshots to a static reader candidate; does not publish")
    update = sub.add_parser("update", help="Run supported wiki stages and report unresolved content")
    update.add_argument("--source", help="Captured local codebase; default from project.json")
    update.add_argument("--operator-report", action="store_true", help="Print the grouped exception list after supported stages finish")
    update.add_argument("--capture-timing", help="Optional humanhost.capture-timing.v1 receipt")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    timing = (run_timing.Recorder(root, args.command, getattr(args, "release", None), getattr(args, "capture_timing", None))
              if args.command in {"update", "publish"} else None)
    show_timing = args.command == "publish" or (args.command == "update" and args.operator_report)
    watchdog = deadline(UPDATE_DEADLINE, args.command, timing=timing, report=show_timing) if timing else None
    def timed_out():
        return timing is not None and (timing.outcome == "timed-out" or watchdog.expired.is_set())
    try:
        result = run(root, args, timing)
        if watchdog:
            watchdog.cancel()
            # Expiry can be waiting for the recorder lock before it sets outcome.
            watchdog.join(CLEANUP_GRACE + 2)
        if timed_out():
            return 124
        if args.command == "update" and args.operator_report:
            # The command table replaces the legacy stage-only Time section.
            report_result = {key: value for key, value in result.items() if key != "timings"}
            sys.stdout.buffer.write(pipeline.operator_report(root, report_result).encode("utf-8"))
        elif args.command == "timing":
            sys.stdout.buffer.write(result.encode("utf-8"))
        else:
            sys.stdout.buffer.write(json_bytes(result))
    except (ContractError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 124 if timed_out() else 1
    finally:
        if watchdog:
            watchdog.cancel()
            # Keep an active supervisor alive through claim, cleanup and exit.
            watchdog.join(CLEANUP_GRACE + 2)
        if show_timing and timing.record is not None:
            try:
                sys.stdout.buffer.write(run_timing.table(timing.record).encode("utf-8"))
            except (Exception, KeyboardInterrupt) as exc:
                run_timing.warning(f"Wiki timing could not be printed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
