"""Enforce the local component contract without importing application modules."""

import argparse
import ast
from dataclasses import dataclass
import fnmatch
from importlib.util import resolve_name
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from wikibuild import bounded

# Inventory and diff scans include pending files throughout the checkout.
GIT_TIMEOUT = 600


@dataclass(frozen=True)
class Component:
    name: str
    description: str
    paths: tuple[str, ...]
    tests: tuple[str, ...]
    depends_on: tuple[str, ...]


@dataclass
class Contract:
    components: dict[str, Component]
    known_violations: list[dict[str, str]]


def load_contract(path: Path) -> Contract:
    data = json.loads(path.read_text(encoding="utf-8"))
    components = {}
    for item in data["components"]:
        name = item["name"]
        if not isinstance(name, str) or not name or name in components:
            raise ValueError(f"Invalid or duplicate component name: {name!r}")
        description = item["description"]
        if not isinstance(description, str) or not description.strip() or "\n" in description:
            raise ValueError(f"{name}: description must be one nonempty line")
        for field in ("paths", "tests", "depends_on"):
            values = item[field]
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                raise ValueError(f"{name}: {field} must be a list of nonempty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{name}: duplicate {field} entry")
        for field in ("paths", "tests"):
            for pattern in item[field]:
                if "\\" in pattern or ".." in pattern.split("/") or pattern.startswith("/"):
                    raise ValueError(f"{name}: invalid repository-relative glob: {pattern}")
                valid = pattern.startswith("tests/") if field == "tests" else (
                    pattern in {"wiki.py", "project.json", "README.md", "AGENTS.md",
                                "snapshots/README.md", "releases/README.md"}
                    or pattern.startswith(("wikibuild/", "tools/", "docs/")))
                if not valid:
                    raise ValueError(f"{name}: {field} glob outside its roots: {pattern}")
        components[name] = Component(name, description, tuple(item["paths"]),
                                     tuple(item["tests"]), tuple(item["depends_on"]))
    if not components:
        raise ValueError("No components declared")
    known = data.get("known_violations", [])
    if not isinstance(known, list):
        raise ValueError("known_violations must be a list")
    seen = set()
    for violation in known:
        if not isinstance(violation, dict) or any(not isinstance(violation.get(key), str) or not violation[key].strip()
               for key in ("source", "target", "reason")):
            raise ValueError("Known violations need source, target and a one-line reason")
        if "\n" in violation["reason"]:
            raise ValueError("Known violation reason must be one line")
        edge = (violation["source"], violation["target"])
        if edge in seen:
            raise ValueError(f"Duplicate known violation: {edge[0]} -> {edge[1]}")
        seen.add(edge)
    return Contract(components, known)


def git_output(root: Path, *args: str) -> list[str]:
    result = bounded.run(["git", "-C", str(root), *args], timeout=GIT_TIMEOUT)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return [p.decode("utf-8", errors="surrogateescape") for p in result.stdout.split(b"\0") if p]


def repository_files(root: Path) -> list[str]:
    # Include pending additions so the checker also protects an unstaged worktree.
    return sorted(set(git_output(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")))


def in_scope(path: str) -> bool:
    return path in {"wiki.py", "project.json", "README.md", "AGENTS.md",
                    "snapshots/README.md", "releases/README.md"} or path.startswith(
                        ("wikibuild/", "tools/", "tests/", "docs/"))


def owners(contract: Contract, path: str) -> list[str]:
    return [component.name for component in contract.components.values()
            if any(fnmatch.fnmatchcase(path, glob) for glob in (*component.paths, *component.tests))]


def dependency_errors(contract: Contract) -> list[str]:
    errors = []
    for component in contract.components.values():
        for dependency in component.depends_on:
            if dependency not in contract.components:
                errors.append(f"{component.name}: unknown dependency {dependency}")
    visited, active = set(), []

    def visit(name):
        if name in active:
            errors.append("Dependency cycle: " + " -> ".join(active[active.index(name):] + [name]))
            return
        if name in visited or name not in contract.components:
            return
        active.append(name)
        for dependency in contract.components[name].depends_on:
            visit(dependency)
        active.pop()
        visited.add(name)

    for name in contract.components:
        visit(name)
    return errors


def module_name(path: str) -> str:
    parts = path.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def import_edges(root: Path, files: list[str]) -> set[tuple[str, str]]:
    """Resolve imports statically, including local test fixture and tool imports."""
    modules = {module_name(path): path for path in files if path.endswith(".py")}
    edges = set()
    for path in files:
        if not path.endswith(".py") or not (root / path).is_file():
            continue
        tree = ast.parse((root / path).read_text(encoding="utf-8-sig"), filename=path)
        module = module_name(path)
        package = module if path.endswith("/__init__.py") else module.rpartition(".")[0]
        importlib_names = {"importlib"}
        dynamic_functions = {"__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                importlib_names.update(alias.asname or alias.name for alias in node.names
                                       if alias.name == "importlib")
            elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
                dynamic_functions.update(alias.asname or alias.name for alias in node.names
                                         if alias.name == "import_module")

        def resolve(name):
            if name in modules:
                return modules[name]
            # Existing tests use bare sibling names under unittest discovery.
            if path.startswith("tests/") and "tests." + name in modules:
                return modules["tests." + name]
            if path.startswith("tools/") and "tools." + name in modules:
                return modules["tools." + name]
            return None

        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [resolve(alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package.split(".") if package else []
                    if node.level > len(parts):
                        raise ValueError(f"{path}:{node.lineno}: relative import escapes its package")
                    base = ".".join(parts[:len(parts) - node.level + 1])
                    if node.module:
                        base += "." + node.module
                else:
                    base = node.module or ""
                # A from-import can select submodules or symbols of its base module.
                targets = [resolve(base + "." + alias.name) or resolve(base) for alias in node.names]
            elif isinstance(node, ast.Call) and (
                    isinstance(node.func, ast.Name) and node.func.id in dynamic_functions
                    or isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in importlib_names):
                argument = node.args[0] if node.args else next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "name"), None)
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    name = argument.value
                    builtin = isinstance(node.func, ast.Name) and node.func.id == "__import__"
                    level = node.args[4] if len(node.args) > 4 else next(
                        (keyword.value for keyword in node.keywords if keyword.arg == "level"), None)
                    if builtin and level is not None and not (
                            isinstance(level, ast.Constant) and level.value == 0):
                        # __import__ needs globals/level to establish its package;
                        # unresolved forms must not silently lose project edges.
                        targets = ["wikibuild.*"]
                    else:
                        package_arg = node.args[1] if len(node.args) > 1 else next(
                            (keyword.value for keyword in node.keywords if keyword.arg == "package"), None)
                        if name.startswith("."):
                            if not isinstance(package_arg, ast.Constant) or not isinstance(package_arg.value, str):
                                targets = ["wikibuild.*"]
                                name = None
                            else:
                                try:
                                    name = resolve_name(name, package_arg.value)
                                except (ImportError, ValueError) as error:
                                    raise ValueError(f"{path}:{node.lineno}: unresolved relative dynamic import") from error
                        if name is not None:
                            target = resolve(name)
                            if target is None and (name == "wikibuild" or name.startswith("wikibuild.")):
                                raise ValueError(f"{path}:{node.lineno}: unresolved project dynamic import: {name}")
                            targets = [target]
                else:
                    # An unknown name may select the project package. Require an
                    # explicit exception rather than silently losing its edges.
                    targets = ["wikibuild.*"]
            for target in targets:
                if target and target != path:
                    edges.add((path, target))
    return edges


def undeclared_edges(contract: Contract, edges: set[tuple[str, str]]) -> set[tuple[str, str]]:
    violations = set()
    for source, target in edges:
        source_owners, target_owners = owners(contract, source), owners(contract, target)
        if len(source_owners) != 1 or len(target_owners) != 1:
            continue  # Ownership errors are reported separately.
        origin, destination = source_owners[0], target_owners[0]
        if origin != destination and destination not in contract.components[origin].depends_on:
            violations.add((source, target))
    return violations


def check(root: Path, contract: Contract, files: list[str] | None = None) -> list[str]:
    files = repository_files(root) if files is None else files
    errors = dependency_errors(contract)
    for path in files:
        if not in_scope(path):
            continue
        matches = owners(contract, path)
        if not matches:
            errors.append(f"Unowned file: {path}")
        elif len(matches) > 1:
            errors.append(f"Multiple owners for {path}: {', '.join(matches)}")
    for component in contract.components.values():
        for pattern in component.tests:
            if not any(fnmatch.fnmatchcase(path, pattern) and (root / path).is_file() for path in files):
                errors.append(f"{component.name}: test glob matches nothing: {pattern}")
    edges = import_edges(root, [p for p in files if in_scope(p)])
    violations = undeclared_edges(contract, edges)
    dynamic = {(source, target) for source, target in edges
               if target == "wikibuild.*"}
    violations.update(dynamic)
    known = {(v["source"], v["target"]) for v in contract.known_violations}
    for source, target in sorted(violations - known):
        if target == "wikibuild.*":
            errors.append(f"Non-literal dynamic import: {source} -> {target}; declare a known violation")
        else:
            origin, destination = owners(contract, source)[0], owners(contract, target)[0]
            errors.append(f"Undeclared import: {source} ({origin}) -> {target} ({destination})")
    for source, target in sorted(known - violations):
        errors.append(f"Stale known violation: {source} -> {target}; remove it from components.json")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        contract = load_contract(args.root / "components.json")
        errors = check(args.root, contract)
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as error:
        print(f"Component check failed: {error}", file=sys.stderr)
        return 1
    if errors:
        print("Component check failed:\n" + "\n".join(f"  {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Components OK: {len(contract.components)} components, "
          f"{len(contract.known_violations)} existing import exceptions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
