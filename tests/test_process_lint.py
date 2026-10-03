"""Import-based process policy, without inferred assignment or parameter provenance."""

import ast
from pathlib import Path
import unittest


ALLOWLIST = {
    "wikibuild/bounded.py": "Owns registered jobs/groups, deadlines and bounded reaping.",
    "tools/run_tests.py": "Owns isolated worker jobs/groups and bounded interruption cleanup.",
}
SAFE = {"TimeoutExpired", "CalledProcessError", "CompletedProcess", "SubprocessError",
        "PIPE", "DEVNULL", "STDOUT"}
PROCESS_MODULES = {"subprocess", "pty", "multiprocessing"}
ASYNC_LAUNCHES = {"create_subprocess_exec", "create_subprocess_shell"}


def os_launch(name):
    return name in {"system", "popen", "startfile", "fork", "forkpty"} or name.startswith(
        ("spawn", "exec", "posix_spawn"))


def import_bindings(node):
    if isinstance(node, ast.Import):
        for item in node.names:
            yield item.asname or item.name.split(".")[0], (
                item.name if item.asname else item.name.split(".")[0], None)
    elif isinstance(node, ast.ImportFrom):
        module = "." * node.level + (node.module or "")
        for item in node.names:
            yield item.asname or item.name, (module, item.name)


def scope_nodes(node):
    """Walk one lexical scope, excluding nested function/class/lambda bodies."""
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from scope_nodes(child)


def direct_launches(code):
    """Return violations of the explicit import and cross-module access policy.

    Parameters, assigned aliases, computed attribute names and arbitrary factory
    results carry no import provenance. A module passed to a parameter is outside
    this static check; obtaining subprocess by name or .subprocess is still banned.
    """
    tree = ast.parse(code)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    # Module imports remain visible to functions declared before those imports.
    module_bindings = {name: provenance for node in scope_nodes(tree)
                       for name, provenance in import_bindings(node)}

    class Check(ast.NodeVisitor):
        def __init__(self):
            self.scopes = [module_bindings]
            self.class_scopes = set()
            self.failures = set()

        def provenance(self, name):
            for scope in reversed(self.scopes):
                if name in scope:
                    return scope[name]
            return None

        def reject(self, node):
            self.failures.add(node.lineno)

        def visit_Import(self, node):
            for item in node.names:
                if item.name.split(".")[0] in {"multiprocessing", "pty"}:
                    self.reject(node)
            self.scopes[-1].update(import_bindings(node))

        def visit_ImportFrom(self, node):
            module = "." * node.level + (node.module or "")
            root = module.split(".")[0]
            for item in node.names:
                if (root in {"multiprocessing", "pty"} or
                        root == "subprocess" and item.name not in SAFE or
                        root == "os" and (item.name == "*" or os_launch(item.name)) or
                        root == "asyncio" and (item.name == "*" or item.name in ASYNC_LAUNCHES) or
                        item.name in PROCESS_MODULES):
                    self.reject(node)
            self.scopes[-1].update(import_bindings(node))

        def visit_Name(self, node):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                # Assignments mask imports; they never copy another name's provenance.
                self.scopes[-1][node.id] = None
                return
            binding = self.provenance(node.id)
            if binding is None:
                return
            module, member = binding
            parent = parents.get(node)
            attribute = parent.attr if isinstance(parent, ast.Attribute) and parent.value is node else None
            target = member if member is not None else attribute
            root = module.split(".")[0]
            if (root == "subprocess" and target not in SAFE or
                    root == "os" and target is not None and os_launch(target) or
                    root == "asyncio" and target in ASYNC_LAUNCHES or
                    # A from-import of another module's os/asyncio is the same access.
                    member == "os" and attribute is not None and os_launch(attribute) or
                    member == "asyncio" and attribute in ASYNC_LAUNCHES):
                self.reject(node)

        def visit_Attribute(self, node):
            if (node.attr in PROCESS_MODULES or
                    isinstance(node.value, ast.Attribute) and (
                        node.value.attr == "os" and os_launch(node.attr) or
                        node.value.attr == "asyncio" and node.attr in ASYNC_LAUNCHES)):
                self.reject(node)
            self.generic_visit(node)

        def visit_Call(self, node):
            dynamic = isinstance(node.func, ast.Name) and node.func.id == "__import__"
            if isinstance(node.func, ast.Name):
                dynamic |= self.provenance(node.func.id) == ("importlib", "import_module")
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                dynamic |= (node.func.attr == "import_module" and
                            self.provenance(node.func.value.id) == ("importlib", None))
            if dynamic:
                argument = node.args[0] if node.args else next(
                    (item.value for item in node.keywords if item.arg == "name"), None)
                if (not isinstance(argument, ast.Constant) or not isinstance(argument.value, str) or
                        argument.value.lstrip(".").split(".")[0] in PROCESS_MODULES):
                    self.reject(node)
            self.generic_visit(node)

        def visit_Assign(self, node):
            self.visit(node.value)
            for target in node.targets:
                self.visit(target)

        def visit_AnnAssign(self, node):
            self.visit(node.annotation)
            if node.value is not None:
                self.visit(node.value)
            self.visit(node.target)

        def visit_FunctionDef(self, node):
            for expression in [*node.decorator_list, *node.args.defaults,
                               *[value for value in node.args.kw_defaults if value is not None]]:
                self.visit(expression)
            if node.returns is not None:
                self.visit(node.returns)
            self.scopes[-1][node.name] = None
            self.visit_function_body(node, node.body)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_function_body(self, node, body):
            local = {child.id: None for child in scope_nodes(node)
                     if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del))}
            local.update({name: None for child in scope_nodes(node) for name, _ in import_bindings(child)})
            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            arguments += [arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None]
            for argument in arguments:
                if argument.annotation is not None:
                    self.visit(argument.annotation)
                local[argument.arg] = None
            enclosing = self.scopes
            # Methods/lambdas resolve outer function/module names, not class attributes.
            self.scopes = [scope for scope in enclosing if id(scope) not in self.class_scopes] + [local]
            for statement in body:
                self.visit(statement)
            self.scopes = enclosing

        def visit_Lambda(self, node):
            for default in [*node.args.defaults, *[v for v in node.args.kw_defaults if v is not None]]:
                self.visit(default)
            self.visit_function_body(node, [node.body])

        def visit_ClassDef(self, node):
            for expression in [*node.decorator_list, *node.bases, *[v.value for v in node.keywords]]:
                self.visit(expression)
            self.scopes[-1][node.name] = None
            local = {}
            self.scopes.append(local)
            self.class_scopes.add(id(local))
            for statement in node.body:
                self.visit(statement)
            self.scopes.pop()
            self.class_scopes.remove(id(local))

        def visit_ListComp(self, node):
            self.visit(node.generators[0].iter)
            enclosing = self.scopes
            self.scopes = [scope for scope in enclosing if id(scope) not in self.class_scopes] + [{}]
            for index, generator in enumerate(node.generators):
                if index:
                    self.visit(generator.iter)
                self.visit(generator.target)
                for condition in generator.ifs:
                    self.visit(condition)
            if isinstance(node, ast.DictComp):
                self.visit(node.key)
                self.visit(node.value)
            else:
                self.visit(node.elt)
            self.scopes = enclosing

        visit_SetComp = visit_ListComp
        visit_DictComp = visit_ListComp
        visit_GeneratorExp = visit_ListComp

    check = Check()
    check.visit(tree)
    return sorted(check.failures)


class ProcessLintTests(unittest.TestCase):
    def assert_rejected(self, fixtures):
        for name, code in fixtures.items():
            with self.subTest(route=name):
                self.assertTrue(direct_launches(code), code)

    def test_subprocess_provenance_rejects_every_unsafe_use(self):
        self.assert_rejected({
            "module alias": 'import subprocess as sp; sp.Popen([])',
            "alias named bounded": 'import subprocess as bounded; bounded.run([])',
            "from-import alias": 'from subprocess import Popen as P; P([])',
            "unused unsafe import": 'from subprocess import check_call',
            "wildcard": 'from subprocess import *',
            "module passed to parameter": 'import subprocess\ndef f(bounded): bounded.Popen([])\nf(subprocess)',
            "module assignment": 'import subprocess as sp; alias = sp',
            "unsafe attribute value": 'import subprocess as sp; launcher = sp.run',
            "unknown subprocess member": 'import subprocess; subprocess.future_launcher',
            "unsafe literal getattr": 'import subprocess; getattr(subprocess, "Popen")',
            "bare module": 'import subprocess; consume(subprocess)',
            "from-import non-launch utility": 'from subprocess import list2cmdline',
        })

    def test_all_safe_subprocess_names_are_allowed(self):
        for name in sorted(SAFE):
            for code in (f'import subprocess as sp; sp.{name}',
                         f'from subprocess import {name} as safe; consume(safe)'):
                with self.subTest(code=code):
                    self.assertEqual(direct_launches(code), [])
        self.assertEqual(direct_launches('import subprocess'), [])

    def test_os_provenance_rejects_all_launch_forms(self):
        members = ("system", "popen", "startfile", "fork", "forkpty", "spawnl", "spawnlp", "spawnle",
                   "spawnlpe", "spawnv", "spawnvp", "spawnve", "spawnvpe", "execl", "execlp", "execle",
                   "execlpe", "execv", "execvp", "execve", "execvpe", "posix_spawn", "posix_spawnp")
        self.assert_rejected({name: f'import os as operating; operating.{name}'
                              for name in members})
        self.assert_rejected({
            "from-import": 'from os import system as execute; execute("git status")',
            "from-import unused": 'from os import startfile',
            "wildcard": 'from os import *',
        })

    def test_asyncio_provenance_rejects_process_creation(self):
        self.assert_rejected({
            "module alias exec": 'import asyncio as aio; aio.create_subprocess_exec("git")',
            "module shell": 'import asyncio; asyncio.create_subprocess_shell("git status")',
            "from-import alias": 'from asyncio import create_subprocess_exec as launch; launch("git")',
            "from-import unused": 'from asyncio import create_subprocess_shell',
            "wildcard": 'from asyncio import *',
        })

    def test_multiprocessing_and_pty_imports_are_rejected(self):
        self.assert_rejected({
            "multiprocessing": 'import multiprocessing',
            "multiprocessing alias": 'import multiprocessing as bounded',
            "multiprocessing child": 'import multiprocessing.context as context',
            "multiprocessing from-import": 'from multiprocessing import Process as P',
            "multiprocessing child from-import": 'from multiprocessing.managers import BaseManager',
            "multiprocessing wildcard": 'from multiprocessing import *',
            "pty": 'import pty',
            "pty alias": 'import pty as terminal',
            "pty from-import": 'from pty import fork',
            "pty wildcard": 'from pty import *',
        })

    def test_cross_module_access_is_rejected_without_provenance(self):
        self.assert_rejected({
            "allowlisted exporter": 'import tools.run_tests as rt; rt.subprocess.Popen([])',
            "owner exporter": 'from wikibuild import bounded; bounded.subprocess.Popen([])',
            "parameter obtains module": 'def f(bounded): bounded.Popen([])\nf(client.subprocess)',
            "unknown exporter": 'client.subprocess',
            "pty exporter": 'client.pty',
            "multiprocessing exporter": 'client.multiprocessing',
            "os exporter": 'client.os.system("git status")',
            "os factory": 'factory().os.startfile("git")',
            "asyncio exporter": 'client.asyncio.create_subprocess_exec("git")',
            "asyncio factory": 'factory().asyncio.create_subprocess_shell("git status")',
            "parameter named bounded": 'def f(bounded): bounded.subprocess.Popen([])',
            "from-import exporter": 'from tools.run_tests import subprocess as sp',
            "from-import os exporter": 'from client import os as operating; operating.system("git status")',
            "from-import asyncio exporter": 'from client import asyncio as aio; aio.create_subprocess_exec("git")',
        })

    def test_dynamic_imports_are_rejected(self):
        self.assert_rejected({
            "builtin": '__import__("subprocess").run([])',
            "builtin pty": '__import__("pty")',
            "builtin multiprocessing": '__import__("multiprocessing.context")',
            "builtin non-literal": '__import__(module)',
            "builtin formatted string": '__import__(f"{module}")',
            "builtin keyword": '__import__(name="subprocess")',
            "importlib": 'import importlib; importlib.import_module("subprocess")',
            "importlib alias": 'import importlib as imports; imports.import_module("pty")',
            "importlib child": 'import importlib; importlib.import_module("multiprocessing.managers")',
            "importlib non-literal": 'import importlib; importlib.import_module(module)',
            "importlib from-import": 'from importlib import import_module as load; load("subprocess")',
            "importlib keyword": 'import importlib; importlib.import_module(name=module)',
            "importlib unknown arguments": 'import importlib; importlib.import_module(**options)',
        })

    def test_legitimate_names_and_owned_primitives_are_allowed(self):
        for code in ('client.call()', 'database.execute()', 'record.execution_status',
                     'import subprocess; subprocess.TimeoutExpired',
                     'from wikibuild import bounded; bounded.run(["git"], timeout=30)',
                     'from wikibuild import bounded; bounded.stream(["git"], timeout=600)',
                     'import wikibuild.bounded as owner; owner.run(["git"], timeout=30)',
                     'from . import bounded; bounded.run(["git"], timeout=30)',
                     'import os; os.replace("a", "b")', 'import os; os.environ',
                     'import asyncio; asyncio.get_running_loop()',
                     'import sys; from wikibuild import bounded; bounded.run([sys.executable], timeout=30)',
                     '__import__("json")', 'import importlib; importlib.import_module("json")',
                     'text = "subprocess.run([])"'):
            with self.subTest(code=code):
                self.assertEqual(direct_launches(code), [])

    def test_parameters_assignments_and_attributes_do_not_gain_provenance(self):
        # A parameter may carry a module at runtime. Static lint cannot infer
        # that type: reject its acquisition (covered above), not generic names.
        for code in ('def f(bounded): bounded.Popen([])',
                     'import subprocess as bounded\ndef f(bounded): bounded.Popen([])',
                     'import os; alias = os; alias.system("git status")',
                     'import os as database; database = client; database.execute()',
                     'client.Popen([])', 'import shutil; shutil.which("git").Popen([])',
                     'def f():\n    import os as operating\n    operating = client\n    operating.execute()',
                     'client = factory()\nclass C:\n    import subprocess as client\n    def f(self): client.call()',
                     'import subprocess as client\n[client.call() for client in clients]',
                     'client.execution_status', 'alias = client; alias = alias.child',
                     'import os; attribute = "system"; getattr(os, attribute)("git status")'):
            with self.subTest(code=code):
                self.assertEqual(direct_launches(code), [])

    def test_imports_inside_functions_and_forward_module_imports_are_tracked(self):
        self.assert_rejected({
            "local import": 'def f():\n    import subprocess as sp\n    sp.run([])',
            "local from-import": 'def f():\n    from os import system as launch\n    launch("git status")',
            "later global import": 'def f(): sp.run([])\nimport subprocess as sp',
            "parameter rebound by import": 'def f(bounded):\n    import subprocess as bounded\n    bounded.run([])',
        })

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
