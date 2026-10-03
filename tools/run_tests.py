"""Select component tests and run each unittest module in an isolated process."""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import fnmatch
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from time import perf_counter

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.check_components import (ROOT, Contract, dependency_errors, git_output,
                                    load_contract, module_name, owners, repository_files)
from tests._support import remove_tree


FULL_SUITE_FILES = {"components.json", "tools/run_tests.py", "tools/check_components.py",
                    "tests/__init__.py", "tests/_support.py", "wikibuild/__init__.py",
                    "wikibuild/adapters/__init__.py"}

POWERSHELL_WORKER = """
import subprocess, sys, unittest
script, shell, support_root = sys.argv[1:]
sys.path.insert(0, support_root)
from tests._support import fixture_dir
class PowerShellTests(unittest.TestCase):
    def test_script(self):
        root = fixture_dir(self, 'ps')
        result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', script,
                                 '-FixtureRoot', str(root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
unittest.main(argv=[script])
"""


@dataclass
class Plan:
    selected: dict[str, list[str]]
    explanation: list[str]
    full: bool = False


def changed_files(root: Path, base: str = "origin/main") -> list[str]:
    return sorted(set(git_output(root, "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD")
                      + git_output(root, "diff", "--name-only", "--no-renames", "-z", "HEAD")
                      + git_output(root, "ls-files", "--others", "--exclude-standard", "-z")))


def select_changed(contract: Contract, files: list[str]) -> Plan:
    selected, explanation, full = {}, [], []
    for path in sorted(set(files)):
        if (path in FULL_SUITE_FILES or path.startswith(".github/")
                or fnmatch.fnmatchcase(path, "requirements*.txt")):
            full.append(f"shared test/CI configuration changed: {path}")
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
        if len(origins) == 1 and violation["target"] == "wikibuild.*":
            dependencies[origins[0]].update(name for name, component in contract.components.items()
                                           if any(path.startswith("wikibuild/") for path in component.paths))
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
    return sorted({path if path.endswith(".ps1") else module_name(path) for path in files
                   if path.startswith("tests/") and (path.endswith(".ps1") or
                       (Path(path).name.startswith("test") and path.endswith(".py")))
                   and (root / path).is_file()
                   and (plan.full or any(fnmatch.fnmatchcase(path, glob) for glob in patterns))})


@dataclass
class Result:
    module: str
    seconds: float
    returncode: int
    output: str
    tests: int
    skipped: int
    unsupported: bool = False


def test_platforms(root: Path, module: str) -> set[str]:
    """A test file may declare supported sys.platform values in its header."""
    path = root / (module if module.endswith(".ps1") else module.replace(".", "/") + ".py")
    with path.open(encoding="utf-8-sig") as stream:
        for _ in range(10):
            line = stream.readline()
            if line.startswith("# HHWIKI-PLATFORMS:"):
                platforms = {value.strip() for value in line.partition(":")[2].split(",")}
                if not platforms or not platforms <= {"win32", "linux", "darwin"}:
                    raise ValueError(f"Invalid platform requirement in {path}: {line.strip()}")
                return platforms
    return set()


def windows_components(root: Path, contract: Contract, files: list[str]) -> set[str]:
    """Include process/availability and tests supporting Windows without Linux."""
    names = {"process", "availability"} & contract.components.keys()
    for name in contract.components:
        plan = Plan({name: []}, [])
        for module in test_modules(root, contract, plan, files):
            platforms = test_platforms(root, module)
            if "win32" in platforms and "linux" not in platforms:
                names.add(name)
                break
    return names


def worker_environment(root: Path, temporary_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(HHWIKI_TEST_ROOT=str(temporary_root), TEMP=str(temporary_root),
                       TMP=str(temporary_root), TMPDIR=str(temporary_root), PYTHONUNBUFFERED="1",
                       PYTHONDONTWRITEBYTECODE="1")
    # Preserve discovery-era bare imports of sibling fixture modules.
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
        str(root), str(root / "tests"), environment.get("PYTHONPATH"))))
    return environment


class WindowsJob:
    """Own a worker's descendants, including children holding inherited pipes."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Limits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("minimum", ctypes.c_size_t),
                        ("maximum", ctypes.c_size_t), ("active", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Limits), ("io", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                    ctypes.c_void_p, wintypes.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            import ctypes
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class Workers:
    """Serialize launch/cancel so no child can escape an interrupted executor."""
    def __init__(self):
        self.lock = threading.Lock()
        self.stopped = False
        self.active = {}

    def start(self, command, **kwargs):
        with self.lock:
            if self.stopped:
                raise OSError("Worker cancelled before launch")
            job = WindowsJob() if os.name == "nt" else None
            process = None
            try:
                if job:
                    # Wait for assignment before executing any test code that
                    # could spawn a child. POSIX setsid happens before exec.
                    barrier = "import runpy,sys; sys.stdin.buffer.read(1); "
                    if command[1] == "-c":
                        command = [command[0], "-c", barrier + command[2], *command[3:]]
                    else:
                        command = [sys.executable, "-c", barrier +
                                   "sys.argv[0]='unittest'; runpy.run_module('unittest',run_name='__main__')",
                                   command[-1]]
                    kwargs["stdin"] = subprocess.PIPE
                process = subprocess.Popen(command, start_new_session=os.name != "nt", **kwargs)
                if job:
                    job.assign(process)
                    process.stdin.write(b"\n")
                    process.stdin.close()
            except BaseException:
                if process:
                    process.kill()
                    process.wait(timeout=5)
                if job:
                    job.close()
                raise
            self.active[process] = job
            return process

    def finish(self, process):
        with self.lock:
            if process not in self.active:
                return
            job = self.active.pop(process)
            if job:
                job.close()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        process.wait(timeout=5)

    def cancel(self):
        with self.lock:
            self.stopped = True
            processes = list(self.active)
            for process, job in self.active.items():
                if job:
                    job.close()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            self.active.clear()
        deadline = perf_counter() + 5
        for process in processes:
            process.wait(timeout=max(0.01, deadline - perf_counter()))


def run_module(root: Path, module: str, temporary_root: Path, children: Workers | None = None) -> Result:
    started = perf_counter()
    children = children or Workers()
    process = None
    try:
        platforms = test_platforms(root, module)
        if platforms and sys.platform not in platforms:
            result = Result(module, 0, 0, f"{sys.platform} unsupported; requires {', '.join(sorted(platforms))}",
                            1, 1, unsupported=True)
        else:
            log = temporary_root / ".worker-output"
            # A file keeps inherited pipe handles and large output from blocking shutdown.
            with log.open("wb") as stream:
                if module.endswith(".ps1"):
                    shell = shutil.which("pwsh")
                    if not shell:
                        raise OSError(f"PowerShell 7 (pwsh) is required for {module}")
                    command = [sys.executable, "-c", POWERSHELL_WORKER, str(root / module), shell, str(ROOT)]
                else:
                    command = [sys.executable, "-m", "unittest", module]
                process = children.start(command, cwd=root,
                                         env=worker_environment(root, temporary_root),
                                         stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                try:
                    process.wait()
                finally:
                    children.finish(process)
            output = log.read_text(encoding="utf-8", errors="replace")
            count = re.search(r"Ran (\d+) tests? in", output)
            skipped = re.search(r"OK \(skipped=(\d+)\)", output)
            result = Result(module, 0, process.returncode, output,
                            int(count[1]) if count else 0, int(skipped[1]) if skipped else 0)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result = Result(module, 0, 1, str(error), 0, 0)
    finally:
        try:
            remove_tree(temporary_root)
        except OSError as error:
            # Preserve unittest output and make worker cleanup part of its result.
            cleanup_error = str(error)
        else:
            cleanup_error = None
    if cleanup_error:
        result.returncode = 1
        result.output += f"\nWorker cleanup failed: {cleanup_error}\n"
    result.seconds = perf_counter() - started
    return result


def execute(root: Path, modules: list[str], workers: int, fail_fast: bool = False) -> int:
    started = perf_counter()
    results = []
    if not modules:
        print("No tests selected.")
        return 0
    base = Path(tempfile.gettempdir()) / "hhw"
    base.mkdir(parents=True, exist_ok=True)
    while True:
        parent = base / f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        try:
            os.mkdir(parent)
            break
        except FileExistsError:
            continue
    temporary_roots = []
    index = 0
    children = Workers()
    pool = ThreadPoolExecutor(max_workers=workers)
    pending = {}
    interrupted = False
    try:
        try:
            for module in modules:
                # Keep paths short: release fixtures contain long immutable hashes.
                while True:
                    temporary_root = parent / f"w{index}"
                    index += 1
                    try:
                        os.mkdir(temporary_root)
                        break
                    except FileExistsError:
                        continue  # Never overwrite another invocation's root.
                temporary_roots.append(temporary_root)
                pending[pool.submit(run_module, root, module, temporary_root, children)] = module
            remaining = set(pending)
            while remaining:
                completed, remaining = wait(remaining, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in completed:
                    result = future.result()
                    results.append(result)
                    state = "FAIL" if result.returncode else "SKIP-UNSUPPORTED" if result.unsupported else "PASS"
                    print(f"{state} {result.module}: {result.tests} tests, "
                          f"{result.skipped} skipped, {result.seconds:.3f}s", flush=True)
                    if result.unsupported:
                        print(f"  {result.output}", flush=True)
                    if result.returncode:
                        print(result.output, end="" if result.output.endswith("\n") else "\n", flush=True)
                        if fail_fast:
                            remaining.clear()
                            break
        except KeyboardInterrupt:
            interrupted = True
            print("Interrupted; terminating test workers.", file=sys.stderr, flush=True)
    finally:
        for future in pending:
            future.cancel()
        children.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        for temporary_root in temporary_roots:
            if temporary_root.exists():
                try:
                    remove_tree(temporary_root)
                except OSError as error:
                    print(f"Worker cleanup failed: {error}", file=sys.stderr)
    leftovers = sorted(parent.iterdir())
    for path in leftovers:
        print(f"Leftover test fixture: {path}", file=sys.stderr)
    cleanup_failed = False
    if not leftovers:
        try:
            parent.rmdir()
        except OSError as error:
            cleanup_failed = True
            print(f"Invocation cleanup failed: {parent}: {error}", file=sys.stderr)
    print("\nModule durations (slowest first):")
    for result in sorted(results, key=lambda item: (-item.seconds, item.module)):
        state = "FAIL" if result.returncode else "SKIP-UNSUPPORTED" if result.unsupported else "PASS"
        print(f"{result.seconds:9.3f}s  {result.module}  {state}")
    failures = sum(result.returncode != 0 for result in results)
    print(f"Summary: {len(results)} modules, {sum(r.tests for r in results)} tests, "
          f"{sum(r.skipped for r in results)} skipped, {failures} failed modules; "
          f"wall {perf_counter() - started:.3f}s with {workers} workers")
    return 130 if interrupted else 1 if failures or leftovers or cleanup_failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--changed", nargs="?", const="origin/main", metavar="BASE")
    selection.add_argument("--component", nargs="+", metavar="NAME")
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--list", action="store_true", help="print selection and reasons without running")
    parser.add_argument("--json", action="store_true", help="machine-readable plan; requires --list")
    parser.add_argument("-j", type=int, default=os.cpu_count() or 1, metavar="N")
    parser.add_argument("--fail-fast", action="store_true", help="stop and terminate workers on the first failed module")
    parser.add_argument("--windows-relevant", action="store_true",
                        help="restrict selected components to process, availability and owners of tests supporting win32 without linux")
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
        if args.windows_relevant:
            relevant = windows_components(root, contract, files)
            plan = Plan({name: reasons for name, reasons in plan.selected.items() if name in relevant},
                        plan.explanation + ["restricted to Windows-relevant components"])
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
    return 0 if args.list else execute(root, modules, args.j, args.fail_fast)


if __name__ == "__main__":
    raise SystemExit(main())
