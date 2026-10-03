"""Production launches belong to the process owner, including imported aliases."""

import ast
from pathlib import Path
import unittest


ALLOWLIST = {
    "wikibuild/bounded.py": "Owns registered jobs/groups, deadlines and bounded reaping.",
    "tools/run_tests.py": "Owns isolated worker jobs/groups and bounded interruption cleanup.",
}
LAUNCHES = {"run", "Popen", "check_output", "call"}


def direct_launches(code):
    tree = ast.parse(code)
    modules, launches = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(item.asname or item.name for item in node.names if item.name == "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            launches.update(item.asname or item.name for item in node.names if item.name in LAUNCHES)

    def is_launch(node):
        return (isinstance(node, ast.Name) and node.id in launches or
                isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in modules and node.attr in LAUNCHES)

    # Include assignments such as launch = subprocess.Popen or launch = run.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and is_launch(node.value):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in launches:
                        launches.add(target.id)
                        changed = True
    return [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call) and is_launch(node.func)]


class ProcessLintTests(unittest.TestCase):
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
