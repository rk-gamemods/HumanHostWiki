"""Explain why reviewed C# dependency hashes changed between two captures.

Read-only. For each reviewed dependency (currently the ammunition address rule
in wikibuild/adapters/coded_contract.py) it compares the old and new captured
revisions and reports one of:

  unchanged       the new capture still matches the recorded hash
  context-only    member tokens are identical; only file-level context such as
                  `using` directives changed. Check the listed context lines,
                  and any imported namespace's type names, before rebaselining.
  member-changed  the member's own tokens changed; review its behavior.
  missing         the member cannot be selected in the new capture.

It prints the new hash for each dependency and, for context-only drift, which
identifiers the member uses that the new context could rebind. It never edits
the contract; record reviewed hashes by hand.

Run from HumanHostWiki:
  py -3 tools/review_code_dependencies.py --old <commit> --new <commit>
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wikibuild import bounded  # noqa: E402
from wikibuild.code_dependencies import Document, SelectionError  # noqa: E402
from wikibuild.adapters.coded_contract import AMMO_RULE  # noqa: E402

RULES = {"ammo-address": ("UI/UI.decompiled.cs", AMMO_RULE)}
GIT_TIMEOUT = 120


def show(source, revision, path):
    result = bounded.run(["git", "-C", str(source), "show", f"{revision}:{path}"], timeout=GIT_TIMEOUT)
    if result.returncode:
        raise SystemExit(f"Cannot read {path} at {revision}: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def parts(document, selector):
    """Return (context, member tokens, sha256) using the contract's own selection."""
    selected = document.select(selector)
    owner, context = document.types[selector["type"]][0]
    body = owner.child_by_field_name("body")
    node = next(child for child in (body.named_children if body is not None else [])
                if child.start_point.row + 1 == selected["line"])
    return context, document.tokens(node), selected["sha256"]


def text(tokens):
    return " ".join(token[1] for token in tokens)


def review(source, old, new):
    report = []
    for rule, (path, dependencies) in RULES.items():
        documents = {revision: Document(show(source, revision, path)) for revision in (old, new)}
        for dependency in dependencies:
            selector, row = dependency["symbol"], {"rule": rule, "path": path, "symbol": dependency["symbol"]}
            try:
                new_context, new_tokens, new_sha = parts(documents[new], selector)
            except SelectionError as exc:
                report.append({**row, "status": "missing", "reason": str(exc)})
                continue
            row["new_sha256"] = new_sha
            if new_sha == dependency["sha256"]:
                report.append({**row, "status": "unchanged"})
                continue
            try:
                old_context, old_tokens, _ = parts(documents[old], selector)
            except SelectionError as exc:
                report.append({**row, "status": "member-changed", "reason": f"old capture: {exc}"})
                continue
            if old_tokens != new_tokens:
                report.append({**row, "status": "member-changed"})
                continue
            old_lines = [text(item) for item in old_context]
            new_lines = [text(item) for item in new_context]
            identifiers = sorted({token[1] for token in new_tokens if token[0] == "identifier"})
            report.append({**row, "status": "context-only",
                           "context_added": [line for line in new_lines if line not in old_lines],
                           "context_removed": [line for line in old_lines if line not in new_lines],
                           "member_identifiers": identifiers})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=Path("..") / "HumanHostCodebase",
                        help="Local capture repository (default: ../HumanHostCodebase)")
    parser.add_argument("--old", required=True, help="Capture commit the hashes were reviewed against")
    parser.add_argument("--new", required=True, help="Capture commit to review")
    args = parser.parse_args()
    report = review(args.source, args.old, args.new)
    print(json.dumps(report, indent=2))
    return 0 if all(row["status"] == "unchanged" for row in report) else 1


if __name__ == "__main__":
    sys.exit(main())
