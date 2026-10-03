"""Select component tests and run each unittest module in an isolated process."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.check_components import (ROOT, Contract, dependency_errors, git_output,
                                    load_contract, module_name, owners, repository_files)


FULL_SUITE_FILES = {"components.json", "tools/run_tests.py", "tools/check_components.py"}


@dataclass
class Plan:
    selected: dict[str, list[str]]
    explanation: list[str]
    full: bool = False


def changed_files(root: Path, base: str = "origin/main") -> list[str]:
    return sorted(set(git_output(root, "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD")
                      + git_output(root, "diff", "--name-only", "--no-renames", "-z", "HEAD")
                      + git_output(root, "ls-files", "--others", "--exclude-standard", "-z")))


def docs_only(path: str) -> bool:
    return path.startswith("docs/") or path.endswith(".md")


def select_changed(contract: Contract, files: list[str]) -> Plan:
    selected, explanation, full = {}, [], []
    for path in sorted(set(files)):
        if (path in FULL_SUITE_FILES or path.startswith(".github/")
                or fnmatch.fnmatchcase(path, "requirements*.txt")):
            full.append(f"shared test/CI configuration changed: {path}")
        elif docs_only(path):
            explanation.append(f"documentation only: {path}")
        else:
            matches = owners(contract, path)
            if len(matches) != 1:
                full.append(f"no unique owner: {path}")
            else:
                selected.setdefault(matches[0], []).append(f"changed: {path}")
    if full:
        return Plan({name: list(full) for name in contract.components}, full + explanation, full=True)

    # The declared DAG is the desired architecture. Exceptions are real imports
    # today, so conservatively include their consumers until those repairs land.
    dependencies = {name: set(c.depends_on) for name, c in contract.components.items()}
    for violation in contract.known_violations:
        origins, destinations = owners(contract, violation["source"]), owners(contract, violation["target"])
        if len(origins) == len(destinations) == 1:
            dependencies[origins[0]].add(destinations[0])
    frontier = list(selected)
    while frontier:
        dependency = frontier.pop(0)
        for name in contract.components:
            if name not in selected and dependency in dependencies[name]:
                selected[name] = [f"depends on selected component: {dependency}"]
                frontier.append(name)
    if not files:
        explanation.append("no changed files")
    return Plan(selected, explanation)


def test_modules(root: Path, contract: Contract, plan: Plan, files: list[str]) -> list[str]:
    patterns = [glob for name in plan.selected for glob in contract.components[name].tests]
    return sorted({module_name(path) for path in files
                   if path.startswith("tests/") and Path(path).name.startswith("test")
                   and path.endswith(".py") and (root / path).is_file()
                   and (plan.full or any(fnmatch.fnmatchcase(path, glob) for glob in patterns))})


@dataclass
class Result:
    module: str
    seconds: float
    returncode: int
    output: str
    tests: int
    skipped: int


def worker_environment(root: Path, temporary_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(HHWIKI_TEST_ROOT=str(temporary_root), TEMP=str(temporary_root),
                       TMP=str(temporary_root), TMPDIR=str(temporary_root), PYTHONUNBUFFERED="1")
    # Preserve discovery-era bare imports of sibling fixture modules.
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
        str(root), str(root / "tests"), environment.get("PYTHONPATH"))))
    return environment


def run_module(root: Path, module: str, temporary_root: Path) -> Result:
    started = perf_counter()
    try:
        process = subprocess.run([sys.executable, "-m", "unittest", module], cwd=root,
                                 env=worker_environment(root, temporary_root),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace")
        output = process.stdout
        count = re.search(r"Ran (\d+) tests? in", output)
        skipped = re.search(r"OK \(skipped=(\d+)\)", output)
        return Result(module, perf_counter() - started, process.returncode, output,
                      int(count[1]) if count else 0, int(skipped[1]) if skipped else 0)
    except OSError as error:
        return Result(module, perf_counter() - started, 1, str(error), 0, 0)


def execute(root: Path, modules: list[str], workers: int) -> int:
    started = perf_counter()
    results = []
    if not modules:
        print("No tests selected.")
        return 0
    parent = root / ".local"
    parent.mkdir(parents=True, exist_ok=True)
    while True:
        run_root = parent / uuid.uuid4().hex[:4]
        try:
            run_root.mkdir()
            break
        except FileExistsError:
            continue
    run_root = run_root.resolve()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {}
            for index, module in enumerate(modules):
                # Keep paths short: release fixtures contain long immutable hashes.
                temporary_root = run_root / format(index, "x")
                temporary_root.mkdir()
                pending[pool.submit(run_module, root, module, temporary_root)] = module
            for future in as_completed(pending):
                result = future.result()
                results.append(result)
                state = "PASS" if result.returncode == 0 else "FAIL"
                print(f"{state} {result.module}: {result.tests} tests, "
                      f"{result.skipped} skipped, {result.seconds:.3f}s", flush=True)
                if result.returncode:
                    print(result.output, end="" if result.output.endswith("\n") else "\n", flush=True)
    finally:
        try:
            shutil.rmtree(run_root)
        except OSError as error:
            print(f"Retained test temporary root {run_root}: {error}", file=sys.stderr)
    print("\nModule durations (slowest first):")
    for result in sorted(results, key=lambda item: (-item.seconds, item.module)):
        print(f"{result.seconds:9.3f}s  {result.module}  {'FAIL' if result.returncode else 'PASS'}")
    failures = sum(result.returncode != 0 for result in results)
    print(f"Summary: {len(results)} modules, {sum(r.tests for r in results)} tests, "
          f"{sum(r.skipped for r in results)} skipped, {failures} failed modules; "
          f"wall {perf_counter() - started:.3f}s with {workers} workers")
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--changed", nargs="?", const="origin/main", metavar="BASE")
    selection.add_argument("--component", nargs="+", metavar="NAME")
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true", help="print selection and reasons without running")
    parser.add_argument("--json", action="store_true", help="machine-readable plan; requires --list")
    parser.add_argument("-j", type=int, default=os.cpu_count() or 1, metavar="N")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.j < 1:
        parser.error("-j must be at least 1")
    if args.json and not args.list:
        parser.error("--json requires --list")
    try:
        root = args.root.resolve()
        contract = load_contract(root / "components.json")
        errors = dependency_errors(contract)
        if errors:
            raise ValueError("; ".join(errors))
        files = repository_files(root)
        if args.all:
            plan = Plan({name: ["explicit --all"] for name in contract.components}, [], full=True)
        elif args.component:
            unknown = set(args.component) - contract.components.keys()
            if unknown:
                raise ValueError("Unknown components: " + ", ".join(sorted(unknown)))
            plan = Plan({name: ["explicit --component"] for name in args.component}, [])
        else:
            plan = select_changed(contract, changed_files(root, args.changed or "origin/main"))
        modules = test_modules(root, contract, plan, files)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Test planning failed: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"components": plan.selected, "modules": modules,
                          "explanation": plan.explanation}, sort_keys=True))
    else:
        print("Test plan:")
        for reason in plan.explanation:
            print(f"  {reason}")
        for name, reasons in sorted(plan.selected.items()):
            print(f"  {name}: {'; '.join(reasons)}")
        print(f"Selected {len(modules)} modules from {len(plan.selected)} components.")
        if args.list:
            for module in modules:
                print(f"  {module}")
    return 0 if args.list else execute(root, modules, args.j)


if __name__ == "__main__":
    raise SystemExit(main())
