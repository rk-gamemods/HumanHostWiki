"""Synthetic repositories prove ownership, imports and test selection boundaries."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from tests import _support
from tests._support import fixture_dir, remove_tree

from tools import check_components as checker, run_tests as runner


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_dir(self, "arch")
        self.data = {"components": [], "known_violations": []}
        self.put("wikibuild/__init__.py", "")
        self.put("tests/__init__.py", "")
        for name, deps, code in (("a", [], ""), ("b", ["a"], "from . import a\n"),
                                 ("c", ["b"], "from wikibuild.b import value\n")):
            self.put(f"wikibuild/{name}.py", code)
            self.put(f"tests/test_{name}.py", "import unittest\nclass Case(unittest.TestCase):\n"
                     "    def test_ok(self):\n        self.assertTrue(True)\n")
            paths = [f"wikibuild/{name}.py"]
            tests = [f"tests/test_{name}.py"]
            if name == "a":
                paths.append("wikibuild/__init__.py")
                tests.append("tests/__init__.py")
            self.data["components"].append(dict(name=name, description=f"Component {name}",
                                               paths=paths, tests=tests, depends_on=deps))

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def contract(self):
        self.put("components.json", json.dumps(self.data))
        return checker.load_contract(self.root / "components.json")

    def files(self):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())

    def errors(self):
        return checker.check(self.root, self.contract(), self.files())

    def test_valid_contract_is_repeatable(self):
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.errors(), [])

    def test_unowned_file(self):
        self.put("wikibuild/unowned.py", "")
        self.assertIn("Unowned file: wikibuild/unowned.py", self.errors())

    def test_double_owner(self):
        self.data["components"][1]["paths"].append("wikibuild/a.py")
        self.assertTrue(any("Multiple owners for wikibuild/a.py: a, b" in e for e in self.errors()))

    def test_undeclared_import_in_each_supported_form(self):
        self.data["components"][1]["depends_on"] = []
        for statement in ("import wikibuild.a", "from wikibuild import a", "from wikibuild.a import value",
                          "from . import a", "from .a import value",
                          'import importlib; importlib.import_module("wikibuild.a")',
                          'import importlib as loader; loader.import_module(name="wikibuild.a")',
                          'from importlib import import_module as load; load("wikibuild.a")',
                          '__import__("wikibuild.a")'):
            with self.subTest(statement=statement):
                self.put("wikibuild/b.py", statement + "\n")
                self.assertTrue(any("Undeclared import: wikibuild/b.py (b) -> wikibuild/a.py (a)" in e
                                    for e in self.errors()))

    def test_unknown_dynamic_import_requires_an_explicit_exception(self):
        for statement in ('import importlib; importlib.import_module("wikibuild." + name)',
                          '__import__(name)', 'from importlib import import_module; import_module(name)'):
            with self.subTest(statement=statement):
                self.put("wikibuild/b.py", statement + "\n")
                self.assertTrue(any("Non-literal dynamic import: wikibuild/b.py" in error
                                    for error in self.errors()))
                self.data["known_violations"] = [dict(source="wikibuild/b.py", target="wikibuild.*",
                                                    reason="Explicit plugin loader pending static dispatch.")]
                self.assertEqual(self.errors(), [])
                self.data["known_violations"] = []
        self.put("wikibuild/b.py", 'import importlib; importlib.import_module("json")\n')
        self.assertEqual(self.errors(), [])

    def test_relative_dynamic_imports_are_dependency_edges(self):
        self.data["components"][1]["depends_on"] = []
        for statement in (
                'import importlib; importlib.import_module(".a", package="wikibuild")',
                'import importlib as loader; loader.import_module(name=".a", package="wikibuild")',
                'from importlib import import_module as load; load(".a", "wikibuild")',
                'import importlib; importlib.import_module("..a", package="wikibuild.nested")'):
            with self.subTest(statement=statement):
                self.put("wikibuild/b.py", statement + "\n")
                self.assertTrue(any("Undeclared import: wikibuild/b.py (b) -> wikibuild/a.py (a)" in error
                                    for error in self.errors()))
                self.data["components"][1]["depends_on"] = ["a"]
                self.assertEqual(self.errors(), [])
                self.data["components"][1]["depends_on"] = []

    def test_unresolved_project_dynamic_imports_fail_closed(self):
        for statement in (
                'import importlib; importlib.import_module(".missing", package="wikibuild")',
                'import importlib; importlib.import_module("wikibuild.missing")',
                '__import__("wikibuild.missing")',
                'import importlib; importlib.import_module("..a", package="wikibuild")'):
            with self.subTest(statement=statement):
                self.put("wikibuild/b.py", statement + "\n")
                with self.assertRaisesRegex(ValueError, "unresolved .*dynamic import"):
                    self.errors()
        for statement in (
                'import importlib; importlib.import_module(".a", package=package)',
                'import importlib; importlib.import_module(".a")',
                '__import__("a", globals(), level=1)'):
            with self.subTest(statement=statement):
                self.put("wikibuild/b.py", statement + "\n")
                self.assertTrue(any("Non-literal dynamic import" in error for error in self.errors()))

    def test_relative_parent_import(self):
        self.data["components"][1]["paths"] = ["wikibuild/nested/**"]
        (self.root / "wikibuild/b.py").unlink()
        self.put("wikibuild/nested/__init__.py", "from .. import a\n")
        self.data["components"][2]["depends_on"] = ["b"]
        self.put("wikibuild/c.py", "from wikibuild.nested import value\n")
        self.assertEqual(self.errors(), [])
        self.data["components"][1]["depends_on"] = []
        self.assertTrue(any("Undeclared import: wikibuild/nested/__init__.py" in e for e in self.errors()))

    def test_dependency_cycle(self):
        self.data["components"][0]["depends_on"] = ["c"]
        self.assertTrue(any("Dependency cycle: a -> c -> b -> a" in e for e in self.errors()))

    def test_known_violation_is_allowed_but_cannot_be_stale(self):
        self.data["components"][1]["depends_on"] = []
        self.data["known_violations"] = [dict(source="wikibuild/b.py", target="wikibuild/a.py",
                                              reason="Existing reverse import pending repair.")]
        self.assertEqual(self.errors(), [])
        self.put("wikibuild/b.py", "")
        self.assertTrue(any("Stale known violation: wikibuild/b.py -> wikibuild/a.py" in e for e in self.errors()))

    def test_empty_test_glob(self):
        self.data["components"][0]["tests"].append("tests/test_missing*.py")
        self.assertIn("a: test glob matches nothing: tests/test_missing*.py", self.errors())

    def test_changed_selection_with_dependency_chain(self):
        contract = self.contract()
        plan = runner.select_changed(contract, ["wikibuild/a.py"])
        self.assertEqual(set(plan.selected), {"a", "b", "c"})
        self.assertEqual(plan.selected["c"], ["depends on selected component: b"])
        self.assertEqual(runner.test_modules(self.root, contract, plan, self.files()),
                         ["tests.test_a", "tests.test_b", "tests.test_c"])
        self.assertEqual(set(runner.select_changed(contract, ["wikibuild/c.py"]).selected), {"c"})

    def test_documents_select_their_consumers(self):
        self.data["components"][2]["paths"].append("docs/**")
        self.put("docs/ARCHITECTURE.md", "# Architecture\n")
        contract = self.contract()
        plan = runner.select_changed(contract, ["docs/ARCHITECTURE.md"])
        self.assertEqual(set(plan.selected), {"c"})
        self.assertEqual(runner.test_modules(self.root, contract, plan, self.files()), ["tests.test_c"])
        actual = checker.load_contract(runner.ROOT / "components.json")
        for path in ("docs/ARCHITECTURE.md", "README.md", "AGENTS.md", "project.json",
                     "snapshots/README.md", "releases/README.md"):
            with self.subTest(path=path):
                selected = runner.select_changed(actual, [path])
                self.assertIn("tests.test_foundation", runner.test_modules(
                    runner.ROOT, actual, selected, checker.repository_files(runner.ROOT)))

    def test_powershell_tests_are_selected_and_run_with_private_fixtures(self):
        script = "tests/Test-Offline.ps1"
        self.data["components"][0]["tests"].append("tests/*.ps1")
        self.put(script, "param([string]$FixtureRoot)\n"
                 "$ErrorActionPreference = 'Stop'\n"
                 "if (-not (Test-Path -LiteralPath $FixtureRoot -PathType Container)) { throw 'No fixture' }\n"
                 "Set-Content -LiteralPath (Join-Path $FixtureRoot 'owned.txt') -Value 'private'\n")
        contract = self.contract()
        plan = runner.select_changed(contract, [script])
        self.assertIn(script, runner.test_modules(self.root, contract, plan, self.files()))
        self.assertNotIn(script, runner.test_modules(self.root, contract,
                                                   runner.Plan({'c': []}, []), self.files()))
        path = fixture_dir(self, "worker")
        result = runner.run_module(self.root, script, path)
        if runner.shutil.which("pwsh"):
            self.assertEqual(result.returncode, 0, result.output)
            self.assertEqual(result.tests, 1)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pwsh", result.output)
        self.assertFalse(path.exists())
        if runner.shutil.which("pwsh"):
            self.put(script, "param([string]$FixtureRoot)\nthrow 'offline script failure'\n")
            path = fixture_dir(self, "worker")
            result = runner.run_module(self.root, script, path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("offline script failure", result.output)
            self.assertEqual(result.tests, 1)
            self.assertFalse(path.exists())

    def test_windows_only_tests_skip_before_resolving_pwsh_on_linux(self):
        script = "tests/Test-Windows.ps1"
        self.put(script, "# HHWIKI-PLATFORMS: win32\nthrow 'must not execute'\n")
        path = fixture_dir(self, "worker")
        with patch.object(runner.sys, "platform", "linux"), \
                patch.object(runner.shutil, "which", side_effect=AssertionError("must skip first")):
            result = runner.run_module(self.root, script, path)
        self.assertEqual(result.returncode, 0, result.output)
        self.assertTrue(result.unsupported)
        self.assertEqual((result.tests, result.skipped), (1, 1))
        self.assertIn("linux unsupported; requires win32", result.output)
        self.assertFalse(path.exists())
        with patch.object(runner.sys, "platform", "linux"), \
                patch.object(runner.tempfile, "gettempdir", return_value=str(self.root)), \
                patch("builtins.print") as output:
            self.assertEqual(runner.execute(self.root, [script], 1), 0)
        self.assertTrue(any("SKIP-UNSUPPORTED" in str(call) for call in output.call_args_list))

    def test_windows_ci_selection_includes_every_windows_only_test_owner(self):
        self.put("tests/test_c.py", "# HHWIKI-PLATFORMS: win32\n")
        self.assertEqual(runner.windows_components(self.root, self.contract(), self.files()), {"c"})
        self.put("tests/test_c.py", "# HHWIKI-PLATFORMS: linux, win32\n")
        self.assertEqual(runner.windows_components(self.root, self.contract(), self.files()), set())
        self.put("tests/test_c.py", "# HHWIKI-PLATFORMS: unknown\n")
        with self.assertRaisesRegex(ValueError, "Invalid platform requirement"):
            runner.windows_components(self.root, self.contract(), self.files())
        actual = checker.load_contract(runner.ROOT / "components.json")
        self.assertTrue({"process", "availability"} <= runner.windows_components(
            runner.ROOT, actual, checker.repository_files(runner.ROOT)))

    def test_contract_and_shared_configuration_select_all(self):
        contract = self.contract()
        for path in ("components.json", "tools/run_tests.py", "tools/check_components.py",
                     ".github/workflows/ci.yml", "requirements-source.txt", "unknown.json",
                     "tests/__init__.py", "tests/_support.py", "wikibuild/__init__.py",
                     "wikibuild/adapters/__init__.py"):
            with self.subTest(path=path):
                plan = runner.select_changed(contract, [path])
                self.assertTrue(plan.full)
                self.assertEqual(set(plan.selected), {"a", "b", "c"})
        self.put("tests/test_unowned.py", "")
        plan = runner.select_changed(contract, ["tests/test_unowned.py"])
        self.assertEqual(runner.test_modules(self.root, contract, plan, self.files()),
                         ["tests.test_a", "tests.test_b", "tests.test_c", "tests.test_unowned"])

    def test_known_imports_also_select_consumers_without_looping(self):
        self.data["known_violations"] = [dict(source="wikibuild/a.py", target="wikibuild/c.py", reason="Existing cycle.")]
        self.assertEqual(set(runner.select_changed(self.contract(), ["wikibuild/c.py"]).selected), {"a", "b", "c"})
        self.data["known_violations"][0]["target"] = "wikibuild.*"
        self.assertEqual(set(runner.select_changed(self.contract(), ["wikibuild/c.py"]).selected), {"a", "b", "c"})

    def test_changed_files_include_committed_staged_unstaged_and_untracked(self):
        calls = []

        def git(root, *args):
            calls.append(args)
            if "main...HEAD" in args:
                return ["wikibuild/a.py", "old.py"]
            if "HEAD" in args:
                return ["tests/test_b.py", "wiki.py"]
            return ["tools/new.py"]

        with patch.object(runner, "git_output", side_effect=git):
            self.assertEqual(runner.changed_files(self.root, "main"),
                             ["old.py", "tests/test_b.py", "tools/new.py", "wiki.py", "wikibuild/a.py"])
        self.assertIn("--no-renames", calls[0])
        self.assertIn("--others", calls[2])

    def test_each_worker_receives_its_own_temp_root(self):
        first, second = self.root / "first", self.root / "second"
        first.mkdir()
        second.mkdir()
        env_a = runner.worker_environment(self.root, first)
        env_b = runner.worker_environment(self.root, second)
        self.assertNotEqual(env_a["HHWIKI_TEST_ROOT"], env_b["HHWIKI_TEST_ROOT"])
        for env, root in ((env_a, first), (env_b, second)):
            for name in ("TEMP", "TMP", "TMPDIR", "HHWIKI_TEST_ROOT"):
                self.assertEqual(env[name], str(root))
            with patch.dict(os.environ, env):
                self.assertEqual(fixture_dir(self, "fixture").parent, root)

    def test_parallel_execution_keeps_full_failure_output_and_exits_nonzero(self):
        self.put("tests/test_a.py", "import unittest\nclass Case(unittest.TestCase):\n"
                 "    def test_bad(self):\n        self.fail('synthetic failure detail')\n")
        command = [sys.executable, str(runner.ROOT / "tools/run_tests.py"), "--root", str(self.root), "--all", "-j", "2"]
        self.contract()
        # File inventory is a real Git read, without needing commits or Git objects.
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("synthetic failure detail", result.stdout)
        self.assertIn("Traceback", result.stdout)
        self.assertIn("PASS tests.test_b: 1 tests", result.stdout)
        self.assertIn("1 failed modules", result.stdout)
        self.assertFalse((self.root / ".local").exists())

    def test_concurrent_invocations_clean_only_their_own_roots(self):
        ready, release = self.root / "ready", self.root / "release"
        first_parent, second_parent = self.root / "first-parent", self.root / "second-parent"
        self.put("tests/test_a.py", "import os,time,unittest\nfrom pathlib import Path\n"
                 "class Case(unittest.TestCase):\n    def test_wait(self):\n"
                 f"        Path({str(first_parent)!r}).write_text(str(Path(os.environ['HHWIKI_TEST_ROOT']).parent))\n"
                 f"        Path({str(ready)!r}).touch()\n"
                 "        deadline=time.monotonic()+10\n"
                 f"        while not Path({str(release)!r}).exists() and time.monotonic()<deadline: time.sleep(.01)\n"
                 f"        self.assertTrue(Path({str(release)!r}).exists())\n")
        self.put("tests/test_b.py", "import os,unittest\nfrom pathlib import Path\n"
                 "class Case(unittest.TestCase):\n    def test_ok(self):\n"
                 f"        Path({str(second_parent)!r}).write_text(str(Path(os.environ['HHWIKI_TEST_ROOT']).parent))\n")
        self.contract()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        environment = os.environ.copy()
        environment.update(TEMP=str(self.root), TMP=str(self.root), TMPDIR=str(self.root))
        command = [sys.executable, str(runner.ROOT / "tools/run_tests.py"),
                   "--root", str(self.root), "-j", "1", "--component"]
        first = subprocess.Popen([*command, "a"], env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists(), "First invocation did not start")
            second = subprocess.run([*command, "b"], env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            first_root, second_root = Path(first_parent.read_text()), Path(second_parent.read_text())
            self.assertNotEqual(first_root, second_root)
            self.assertTrue(first_root.exists(), "Second invocation removed the first invocation's root")
            self.assertFalse(second_root.exists())
        finally:
            release.touch()
            try:
                output = first.communicate(timeout=15)[0]
            except subprocess.TimeoutExpired:
                first.kill()
                first.communicate()
                raise
        self.assertEqual(first.returncode, 0, output.decode(errors="replace"))
        self.assertFalse(first_root.exists())
        self.assertEqual(list((self.root / "hhw").iterdir()), [])

    def hanging_worker(self):
        pids = self.root / "worker-pids.json"
        self.put("tests/test_a.py", "import json,os,subprocess,sys,time,unittest\n"
                 "from pathlib import Path\nclass Case(unittest.TestCase):\n"
                 "    def test_hang(self):\n"
                 "        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                 f"        Path({str(pids)!r}).write_text(json.dumps([os.getpid(),child.pid]))\n"
                 "        time.sleep(120)\n")
        return pids

    def assert_processes_stopped(self, pids):
        for pid in json.loads(pids.read_text()):
            if os.name == "nt":
                import ctypes
                api = ctypes.WinDLL("kernel32", use_last_error=True)
                api.OpenProcess.restype = ctypes.c_void_p
                handle = api.OpenProcess(0x1000, False, pid)
                if not handle:
                    self.assertEqual(ctypes.get_last_error(), 87)
                    continue
                try:
                    code = ctypes.c_ulong()
                    self.assertTrue(api.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)))
                    self.assertNotEqual(code.value, 259, f"Worker tree still running: {pid}")
                finally:
                    api.CloseHandle(ctypes.c_void_p(handle))
            else:
                # A dead orphan can briefly await init's reap; it cannot hold fixtures.
                status = Path(f"/proc/{pid}/stat")
                if status.exists():
                    self.assertEqual(status.read_text().split()[2], "Z")

    def test_failure_fast_reaps_hanging_worker_and_descendant(self):
        pids = self.hanging_worker()
        self.put("tests/test_b.py", "import time,unittest\nfrom pathlib import Path\n"
                 "class Case(unittest.TestCase):\n    def test_bad(self):\n"
                 "        deadline=time.monotonic()+5\n"
                 f"        while not Path({str(pids)!r}).exists() and time.monotonic()<deadline: time.sleep(.01)\n"
                 "        self.fail('stop the hanging worker')\n")
        self.contract()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        environment = os.environ.copy()
        environment.update(TEMP=str(self.root), TMP=str(self.root), TMPDIR=str(self.root))
        started = time.monotonic()
        result = subprocess.run([sys.executable, str(runner.ROOT / "tools/run_tests.py"),
                                 "--root", str(self.root), "--all", "-j", "2", "--fail-fast"],
                                env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("stop the hanging worker", result.stdout)
        self.assertLess(time.monotonic() - started, 10)
        self.assert_processes_stopped(pids)
        self.assertEqual(list((self.root / "hhw").iterdir()), [])

    def test_keyboard_interrupt_reaps_hanging_worker_and_descendant(self):
        pids = self.hanging_worker()
        self.put("interrupt.py", "import _thread,sys,threading,time\nfrom pathlib import Path\n"
                 f"sys.path.insert(0,{str(runner.ROOT)!r})\nfrom tools import run_tests\n"
                 "def interrupt():\n"
                 "    deadline=time.monotonic()+5\n"
                 f"    while not Path({str(pids)!r}).exists() and time.monotonic()<deadline: time.sleep(.01)\n"
                 "    _thread.interrupt_main()\nthreading.Thread(target=interrupt,daemon=True).start()\n"
                 f"raise SystemExit(run_tests.execute(Path({str(self.root)!r}), ['tests.test_a'], 1))\n")
        environment = os.environ.copy()
        environment.update(TEMP=str(self.root), TMP=str(self.root), TMPDIR=str(self.root))
        result = subprocess.run([sys.executable, str(self.root / "interrupt.py")],
                                env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 130, result.stdout + result.stderr)
        self.assertIn("Interrupted; terminating test workers.", result.stderr)
        self.assert_processes_stopped(pids)
        self.assertEqual(list((self.root / "hhw").iterdir()), [])

    def test_fixture_is_unique_and_cleanup_survives_setup_failure(self):
        case = unittest.TestCase()
        with patch.dict(os.environ, {"HHWIKI_TEST_ROOT": str(self.root)}), \
                patch.object(_support.tempfile, "mkdtemp", side_effect=AssertionError("owner-only ACL")):
            first = fixture_dir(case, "fixture")
            second = fixture_dir(case, "fixture")
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, self.root)
        self.assertTrue(case.doCleanups())
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        created = []

        class BrokenSetup(unittest.TestCase):
            def setUp(case):
                created.append(fixture_dir(case, "setup"))
                raise RuntimeError("setup failed")

            def runTest(case):
                raise AssertionError("setup should have failed")

        result = unittest.TestResult()
        BrokenSetup().run(result)
        self.assertEqual(len(result.errors), 1)
        self.assertFalse(created[0].exists())

    def test_default_fixture_root_is_outside_repository_and_class_cleanup_works(self):
        class Case(unittest.TestCase):
            pass

        with patch.dict(os.environ), patch.object(_support.tempfile, "gettempdir", return_value=str(self.root)):
            os.environ.pop("HHWIKI_TEST_ROOT", None)
            path = fixture_dir(Case, "class")
        self.assertEqual(path.parent, self.root / "hhw")
        self.assertFalse(path.is_relative_to(runner.ROOT))
        Case.doClassCleanups()
        self.assertEqual(Case.tearDown_exceptions, [])
        self.assertFalse(path.exists())

    def test_fixture_parent_inside_repository_fails_before_creation(self):
        for parent in (runner.ROOT, runner.ROOT / ".local/rejected-fixture",
                       runner.ROOT / "tests/../.local/rejected-fixture"):
            with self.subTest(parent=parent), patch.dict(os.environ, {"HHWIKI_TEST_ROOT": str(parent)}), \
                    patch.object(_support.os, "mkdir", side_effect=AssertionError("must reject before mkdir")):
                with self.assertRaisesRegex(ValueError, "Fixture parent must be outside repository"):
                    fixture_dir(self, "rejected")
        with patch.dict(os.environ), patch.object(_support.tempfile, "gettempdir", return_value=str(runner.ROOT)), \
                patch.object(_support.os, "mkdir", side_effect=AssertionError("must reject before mkdir")):
            os.environ.pop("HHWIKI_TEST_ROOT", None)
            with self.assertRaisesRegex(ValueError, "Fixture parent must be outside repository"):
                fixture_dir(self, "rejected")
        alias = self.root / "checkout-alias"
        if os.name == "nt":
            subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(alias), str(runner.ROOT)],
                           check=True, capture_output=True)
            self.addCleanup(alias.rmdir)  # Remove this junction, never its target.
        else:
            alias.symlink_to(runner.ROOT, target_is_directory=True)
            self.addCleanup(alias.unlink)
        with patch.dict(os.environ, {"HHWIKI_TEST_ROOT": str(alias / ".local/rejected-fixture")}), \
                patch.object(_support.os, "mkdir", side_effect=AssertionError("must reject redirected parent")):
            with self.assertRaisesRegex(ValueError, "Fixture parent must be outside repository"):
                fixture_dir(self, "rejected")

    def test_remove_tree_clears_read_only_files_and_is_repeatable(self):
        path = fixture_dir(self, "readonly")
        obj = path / "object"
        obj.write_bytes(b"Git object")
        obj.chmod(stat.S_IREAD)
        remove_tree(path)
        remove_tree(path)
        self.assertFalse(path.exists())

    def test_git_query_cache_observes_mutations_and_reads_live_git_blob_bytes(self):
        def git(*arguments):
            return subprocess.run(["git", "-C", str(self.root), *arguments],
                                  capture_output=True, check=True).stdout

        git("init", "-q")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        self.put("note.txt", "First\n")
        git("add", "note.txt")
        git("commit", "-qm", "First")
        _support.cache_git_queries(self, self.root)
        first = git("rev-parse", "HEAD")
        with patch.object(subprocess, "Popen", side_effect=AssertionError("uncached command")):
            self.assertEqual(git("rev-parse", "HEAD"), first)
        status = git("status", "--porcelain=v1")
        self.put("note.txt", "Second\n")
        self.assertNotEqual(git("status", "--porcelain=v1"), status)
        git("add", "note.txt")
        git("commit", "-qm", "Second")
        self.assertNotEqual(git("rev-parse", "HEAD"), first)
        self.assertEqual(git("config", "--get", "user.name").strip(), b"Fixture")
        git("config", "user.name", "Changed")
        self.assertEqual(git("config", "--get", "user.name").strip(), b"Changed")
        self.assertEqual(git("cat-file", "blob", "HEAD:note.txt"), b"Second\n")
        self.assertEqual(git("cat-file", "blob", first.decode().strip() + ":note.txt"), b"First\n")
        self.put('note.txt', 'Third\n')
        git('add', 'note.txt')
        git('commit', '-qm', 'Third')
        self.assertEqual(git('cat-file', 'blob', 'HEAD:note.txt'), b'Third\n')
        tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
        message = b'Input still reaches real Git\n\nFixture stdin bytes\n'
        commit = subprocess.run(['git', '-C', str(self.root), 'commit-tree', tree],
                                input=message, capture_output=True, check=True).stdout.decode().strip()
        self.assertEqual(git('cat-file', 'commit', commit).split(b'\n\n', 1)[1], message)
        with patch.object(subprocess, "Popen", side_effect=AssertionError("uncached command")):
            for arguments in (("status", "--porcelain=v1"),):
                with self.subTest(arguments=arguments), self.assertRaisesRegex(AssertionError, "uncached"):
                    git(*arguments)

    def test_checkout_query_cache_detects_edits_staging_unknown_files_and_deletions(self):
        parent = self.root / 'repositories'
        parent.mkdir()
        with patch.dict(os.environ, {'HHWIKI_TEST_ROOT': str(parent)}):
            repo = fixture_dir(self, 'git')
        original = subprocess.run
        def git(*arguments):
            command = ['git', '-C', str(repo), *arguments]
            result = subprocess.run(command, capture_output=True, check=True).stdout
            if arguments[0] in {'status', 'write-tree', 'diff-files', 'ls-files'}:
                expected = original(command, capture_output=True, check=True).stdout
                self.assertEqual(result, expected)
            return result
        git('init', '-q')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        (repo / '.gitignore').write_text('.local/\n')
        note = repo / 'note'
        note.write_text('First')
        git('add', '.')
        git('commit', '-qm', 'First')
        _support.cache_git_queries(self, self.root)
        clean = git('status', '--porcelain=v1', '--untracked-files=all')
        tree = git('write-tree')
        note.write_text('Second')
        self.assertNotEqual(git('status', '--porcelain=v1', '--untracked-files=all'), clean)
        self.assertTrue(git('diff-files', '--name-only', '-z'))
        git('add', 'note')
        self.assertNotEqual(git('write-tree'), tree)
        (repo / 'unknown').write_text('Private file')
        self.assertIn(b'unknown', git('ls-files', '--others', '--exclude-standard', '-z'))
        note.unlink()
        self.assertIn(b'D', git('status', '--porcelain=v1', '--untracked-files=all'))

    def test_remove_tree_retries_sharing_violations_and_reports_exhaustion(self):
        path = fixture_dir(self, "busy")
        busy = OSError("sharing violation")
        busy.winerror = 32
        real_remove = _support.shutil.rmtree
        with patch.object(_support.shutil, "rmtree", side_effect=[busy, None]) as remove, \
                patch.object(_support.time, "sleep"):
            remove_tree(path)
        self.assertEqual(remove.call_count, 2)
        with patch.object(_support.shutil, "rmtree", side_effect=busy), \
                patch.object(_support.time, "monotonic", side_effect=[0, 0, 6]), \
                patch.object(_support.time, "sleep"):
            with self.assertRaisesRegex(OSError, str(path).replace("\\", "\\\\")):
                remove_tree(path)
        real_remove(path)

    def test_failed_fixture_cleanup_fails_the_running_test(self):
        class Case(unittest.TestCase):
            def runTest(case):
                fixture_dir(case, "fails")

        with patch.dict(os.environ, {"HHWIKI_TEST_ROOT": str(self.root)}), \
                patch.object(_support, "remove_tree", side_effect=OSError("cleanup failure")):
            result = unittest.TestResult()
            Case().run(result)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("cleanup failure", result.errors[0][1])

    def test_worker_removes_leaked_readonly_files_after_module_failure(self):
        path = fixture_dir(self, "worker")
        obj = path / "object"
        obj.write_bytes(b"Git object")
        obj.chmod(stat.S_IREAD)
        self.put("tests/test_a.py", "import unittest\nclass Case(unittest.TestCase):\n"
                 "    def test_bad(self):\n        self.fail('worker failure')\n")
        result = runner.run_module(self.root, "tests.test_a", path)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.tests, 1)
        self.assertFalse(path.exists())

    def test_worker_cleanup_failure_is_nonzero_and_leftovers_fail_runner(self):
        path = fixture_dir(self, "worker")
        with patch.object(runner, "remove_tree", side_effect=OSError("cleanup failure")):
            result = runner.run_module(self.root, "tests.test_a", path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Worker cleanup failed", result.output)
        with patch.object(runner.tempfile, "gettempdir", return_value=str(self.root)), \
                patch.object(runner, "run_module", return_value=runner.Result("tests.test_a", 0, 0, "", 1, 0)), \
                patch.object(runner, "remove_tree", side_effect=OSError("cleanup failure")), \
                patch("builtins.print") as output:
            self.assertEqual(runner.execute(self.root, ["tests.test_a"], 1), 1)
        self.assertTrue(any("Leftover test fixture:" in str(call) for call in output.call_args_list))


if __name__ == "__main__":
    unittest.main()
