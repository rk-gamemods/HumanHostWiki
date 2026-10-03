"""Production launches belong to the process owner, including imported aliases."""

import ast
from pathlib import Path
import unittest


ALLOWLIST = {
    "wikibuild/bounded.py": "Owns registered jobs/groups, deadlines and bounded reaping.",
    "tools/run_tests.py": "Owns isolated worker jobs/groups and bounded interruption cleanup.",
}
LAUNCHES = {"run", "Popen", "check_output", "call", "check_call", "getoutput", "getstatusoutput"}
PROCESS_TYPES = {"Process", "BaseProcess", "ForkProcess", "SpawnProcess", "ForkServerProcess"}
MANAGER_TYPES = {"BaseManager", "SyncManager"}


def launch_route(name):
    module, _, member = name.partition(".")
    if module == "subprocess":
        return member in LAUNCHES
    if module in {"os", "posix", "nt"}:
        return (member in {"system", "popen", "fork", "forkpty"} or
                member.startswith(("spawn", "exec", "posix_spawn")))
    if module == "asyncio":
        return member.rsplit(".", 1)[-1] in {"create_subprocess_exec", "create_subprocess_shell",
                                            "subprocess_exec", "subprocess_shell"}
    if module == "multiprocessing":
        parts = member.split(".")
        return (parts[-1] in (PROCESS_TYPES - {"BaseProcess"}) | {"Pool", "Manager", "Popen", "_Popen"} or
                parts[-1] == "start" and any(p in PROCESS_TYPES | MANAGER_TYPES
                                             for p in parts[:-1]))
    return (name in {"pty.spawn", "pty.fork", "concurrent.futures.ProcessPoolExecutor"})


def direct_launches(code):
    tree = ast.parse(code)
    aliases, wildcards = {}, set()

    def bind(name, values):
        previous = aliases.setdefault(name, set())
        added = values - previous
        previous.update(added)
        return bool(added)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                bind(item.asname or item.name.split(".")[0], {item.name if item.asname else item.name.split(".")[0]})
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for item in node.names:
                if item.name == "*":
                    wildcards.add(node.module)
                else:
                    bind(item.asname or item.name, {f"{node.module}.{item.name}"})

    def resolve(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, set()) | {
                f"{module}.{node.id}" for module in wildcards
                if launch_route(f"{module}.{node.id}") or node.id in {"get_context", "get_event_loop", "get_running_loop"}}
        if isinstance(node, ast.Attribute):
            return {f"{base}.{node.attr}" for base in resolve(node.value)}
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
                attribute = node.args[1]
                if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str):
                    return {f"{base}.{attribute.value}" for base in resolve(node.args[0])}
            callees = resolve(node.func)
            result = set()
            for name in callees:
                if name == "multiprocessing.get_context":
                    result.add("multiprocessing.context")
                elif name in {"asyncio.get_event_loop", "asyncio.get_running_loop"}:
                    result.add("asyncio.loop")
                elif name.startswith("multiprocessing.") and (
                        name.rsplit(".", 1)[-1] in PROCESS_TYPES | MANAGER_TYPES or name.endswith("Context")):
                    # Keep process/manager instance types for later .start().
                    result.add(name)
            return result
        return set()

    # Resolve module aliases, callable aliases, context factories and instances.
    # Union rather than overwrite conditional bindings so shadowing cannot hide
    # a launch. This check intentionally treats ambiguous aliases conservatively.
    # Cyclic attribute assignments must not make the linter itself unbounded.
    for _ in range(sum(1 for _ in ast.walk(tree)) + 1):
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                values = resolve(node.value)
                for target in targets:
                    if isinstance(target, ast.Name):
                        changed |= bind(target.id, values)
            elif isinstance(node, ast.ClassDef):
                for base in node.bases:
                    changed |= bind(node.name, resolve(base))
        if not changed:
            break
    return [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call)
            and any(launch_route(name) for name in resolve(node.func))]


class ProcessLintTests(unittest.TestCase):
    def test_shell_launch_is_rejected(self):
        self.assertEqual(len(direct_launches('import os as operating; operating.system("git status")')), 1)

    def test_all_production_launches_are_owned(self):
        root = Path(__file__).resolve().parents[1]
        failures, seen = [], set()
        for directory in ("wikibuild", "tools"):
            for path in sorted((root / directory).rglob("*.py")):
                name = path.relative_to(root).as_posix()
                calls = direct_launches(path.read_text(encoding="utf-8"))
                if name in ALLOWLIST:
                    self.assertTrue(ALLOWLIST[name].strip())
                    self.assertTrue(calls, f"Stale subprocess allowlist: {name}")
                    seen.add(name)
                else:
                    failures.extend(f"{name}:{line}" for line in calls)
        self.assertEqual(seen, set(ALLOWLIST))
        self.assertEqual(failures, [], "Use bounded.run/stream: " + ", ".join(failures))

    def test_aliases_cannot_bypass_the_rule(self):
        for code in ("import subprocess; subprocess.run([])",
                     "import subprocess as sp; sp.Popen([])",
                     "from subprocess import check_output as output; output([])",
                     "from subprocess import call; call([])",
                     "import subprocess as sp; launch = sp.Popen; launch([])"):
            with self.subTest(code=code):
                self.assertEqual(len(direct_launches(code)), 1)
        self.assertEqual(direct_launches('text = "subprocess.run([])"'), [])

    def test_every_launch_route_has_a_negative_fixture(self):
        fixtures = {
            "check_call": 'import subprocess as sp; sp.check_call([])',
            "getoutput": 'from subprocess import getoutput as output; output("git status")',
            "getstatusoutput": 'import subprocess; subprocess.getstatusoutput("git status")',
            "mixed aliases": 'import subprocess as sp; from subprocess import Popen as P; P([]); sp.run([])',
            "module assignment": 'import subprocess as sp; alias = sp; launch = alias.Popen; launch([])',
            "wildcard subprocess": 'from subprocess import *; check_call([])',
            "wildcard os": 'from os import *; system("git status")',
            "os.system": 'import os; os.system("git status")',
            "os.popen": 'from os import popen as pipe; pipe("git status")',
            "os.spawnl": 'import os; os.spawnl(0, "git", "git")',
            "os.spawnlp": 'import os; os.spawnlp(0, "git", "git")',
            "os.spawnle": 'import os; os.spawnle(0, "git", "git", {})',
            "os.spawnlpe": 'import os; os.spawnlpe(0, "git", "git", {})',
            "os.spawnv": 'import os; os.spawnv(0, "git", [])',
            "os.spawnvp": 'import os; os.spawnvp(0, "git", [])',
            "os.spawnve": 'import os; os.spawnve(0, "git", [], {})',
            "os.spawnvpe": 'import os; os.spawnvpe(0, "git", [], {})',
            "os.execl": 'import os; os.execl("git", "git")',
            "os.execlp": 'import os; os.execlp("git", "git")',
            "os.execle": 'import os; os.execle("git", "git", {})',
            "os.execlpe": 'import os; os.execlpe("git", "git", {})',
            "os.execv": 'import os; os.execv("git", [])',
            "os.execvp": 'import os; os.execvp("git", [])',
            "os.execve": 'import os; os.execve("git", [], {})',
            "os.execvpe": 'import os; os.execvpe("git", [], {})',
            "os.posix_spawn": 'import os; os.posix_spawn("git", [], {})',
            "os.posix_spawnp": 'from os import posix_spawnp as spawn; spawn("git", [], {})',
            "os.fork": 'import os; os.fork()',
            "os.forkpty": 'import os; os.forkpty()',
            "asyncio exec": 'import asyncio as aio; aio.create_subprocess_exec("git")',
            "asyncio shell": 'from asyncio import create_subprocess_shell as launch; launch("git status")',
            "asyncio submodule": 'from asyncio import subprocess as processes; processes.create_subprocess_exec("git")',
            "wildcard asyncio": 'from asyncio import *; create_subprocess_exec("git")',
            "asyncio loop": 'import asyncio; loop = asyncio.get_running_loop(); loop.subprocess_exec(None, "git")',
            "multiprocessing Process": 'from multiprocessing import Process as P; p = P(); p.start()',
            "multiprocessing Pool": 'import multiprocessing as mp; mp.Pool()',
            "multiprocessing Manager": 'import multiprocessing as mp; mp.Manager()',
            "multiprocessing context": 'import multiprocessing as mp; ctx = mp.get_context("spawn"); ctx.Process().start()',
            "multiprocessing SpawnProcess": 'from multiprocessing.context import SpawnProcess as P; P().start()',
            "multiprocessing ForkProcess": 'from multiprocessing.context import ForkProcess as P; P().start()',
            "multiprocessing ForkServerProcess": 'from multiprocessing.context import ForkServerProcess as P; P().start()',
            "multiprocessing SpawnContext": 'from multiprocessing.context import SpawnContext as C; ctx = C(); ctx.Process().start()',
            "multiprocessing Popen": 'from multiprocessing.popen_spawn_win32 import Popen as P; P(None)',
            "wildcard multiprocessing": 'from multiprocessing import *; Process().start()',
            "manager start": 'from multiprocessing.managers import BaseManager as M; manager = M(); manager.start()',
            "derived manager": 'from multiprocessing.managers import BaseManager\nclass M(BaseManager): pass\nm = M(); m.start()',
            "process executor": 'from concurrent.futures import ProcessPoolExecutor as E; E()',
            "pty.spawn": 'import pty as terminal; terminal.spawn(["git"])',
            "pty.fork": 'from pty import fork as child; child()',
            "wildcard pty": 'from pty import *; spawn(["git"])',
            "literal getattr": 'import subprocess as sp; launch = getattr(sp, "Popen"); launch([])',
        }
        for name, code in fixtures.items():
            with self.subTest(route=name):
                self.assertTrue(direct_launches(code), code)

    def test_non_launch_operations_remain_allowed(self):
        self.assertEqual(direct_launches('import os; os.replace("a", "b")'), [])
        self.assertEqual(direct_launches('import subprocess; subprocess.CompletedProcess([], 0)'), [])
        self.assertEqual(direct_launches('from concurrent.futures import ThreadPoolExecutor; ThreadPoolExecutor()'), [])
        self.assertEqual(direct_launches('import asyncio; asyncio.get_running_loop()'), [])

    def test_alias_cycles_finish_and_still_reject_a_launch(self):
        self.assertTrue(direct_launches('import subprocess as sp; sp = sp.namespace; sp.Popen([])'))
        self.assertTrue(direct_launches('import multiprocessing as mp; p = mp.Process(); p = p.start()'))
