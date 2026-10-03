"""Synthetic repositories prove ownership, imports and test selection boundaries."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests._support import fixture_parent
from tools import check_components as checker, run_tests as runner


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=fixture_parent("architecture"))
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
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
                          "from . import a", "from .a import value"):
            with self.subTest(statement=statement):
                self.put("wikibuild/b.py", statement + "\n")
                self.assertTrue(any("Undeclared import: wikibuild/b.py (b) -> wikibuild/a.py (a)" in e
                                    for e in self.errors()))

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

    def test_docs_only_selects_nothing(self):
        plan = runner.select_changed(self.contract(), ["docs/ARCHITECTURE.md", "README.md", "AGENTS.md"])
        self.assertEqual(plan.selected, {})

    def test_contract_and_shared_configuration_select_all(self):
        contract = self.contract()
        for path in ("components.json", "tools/run_tests.py", "tools/check_components.py",
                     ".github/workflows/ci.yml", "requirements-source.txt", "unknown.json"):
            with self.subTest(path=path):
                self.assertEqual(set(runner.select_changed(contract, [path]).selected), {"a", "b", "c"})
        self.put("tests/test_unowned.py", "")
        plan = runner.select_changed(contract, ["tests/test_unowned.py"])
        self.assertEqual(runner.test_modules(self.root, contract, plan, self.files()),
                         ["tests.test_a", "tests.test_b", "tests.test_c", "tests.test_unowned"])

    def test_known_imports_also_select_consumers_without_looping(self):
        self.data["known_violations"] = [dict(source="wikibuild/a.py", target="wikibuild/c.py", reason="Existing cycle.")]
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
                self.assertEqual(fixture_parent("fixture"), root)

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
        self.assertEqual(list((self.root / ".local").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
