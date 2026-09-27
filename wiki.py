#!/usr/bin/env python3
"""Human Host Wiki local workspace commands. Python standard library only."""

import argparse
import json
from pathlib import Path
import sys

from wikibuild import extraction, manifest, navigation, snapshots, workspace
from wikibuild.storage import ContractError, json_bytes, within, writer_lock, write_changed


def run(root, args):
    project = manifest.load(root)
    if args.command == "validate":
        states = [workspace.inspect(root, repo) for repo in project["repositories"]]
        return {"valid": True, "repositories": len(states), "pipeline": manifest.stage_order(project),
                "checkout_states": {state["id"]: state["state"] for state in states}}
    if args.command == "status":
        return {"repositories": [workspace.inspect(root, repo) for repo in project["repositories"]]}
    if args.command == "plan":
        return {"stages": project["pipeline"], "note": "Registration and selected item/loot extraction are implemented; build renders the architecture preview. Full normalization and release remain unfinished."}
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
        if args.command == "lock":
            result = workspace.checkout_lock(root, project)
            return {"lock": result["kind"], "repositories": len(result["repositories"])}
        if args.command == "init-repositories":
            return {"created": workspace.initialize(root, project), "remotes_created": 0,
                    "note": "New repositories contain uncommitted seed files; review and commit them locally."}
        if args.command in {"refresh", "extract"}:
            source = Path(args.source) if args.source else root / project["source"]["default_path"]
            receipt = snapshots.register(root, project, source)
            if args.command == "extract":
                result, metrics = extraction.run(root, project, source, receipt)
                return {**result, "metrics": metrics}
            return {"snapshot_id": receipt["snapshot_id"], "status": receipt["status"],
                    "wiki_verification": receipt["wiki_verification"], "game_version": receipt["game_version"]}
        if args.command == "build":
            receipt = snapshots.read(root, args.snapshot) if args.snapshot else None
            return navigation.build(root, project, receipt)
    raise ContractError("Unknown command")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["validate", "status", "plan", "init-repositories", "lock", "check-lock"]:
        sub.add_parser(command)
    sub.add_parser("map").add_argument("--check", action="store_true")
    refresh = sub.add_parser("refresh", help="Register the current local catalog input; does not re-extract game data")
    refresh.add_argument("--source", help="Existing local codebase repository; default from project.json")
    extract = sub.add_parser("extract", help="Extract supported facts and report exceptions; does not publish")
    extract.add_argument("--source", help="Existing local codebase repository; default from project.json")
    build = sub.add_parser("build", help="Build a local architecture/navigation preview, not gameplay articles")
    build.add_argument("--snapshot", help="Registered snapshot ID for the preview provenance banner")
    args = parser.parse_args()
    try:
        result = run(Path(__file__).resolve().parent, args)
    except (ContractError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(json_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
