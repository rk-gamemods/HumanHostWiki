"""The dependency review separates import-only drift from member changes."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

from wikibuild.code_dependencies import Document, runtime

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("review_code_dependencies", ROOT / "tools/review_code_dependencies.py")
review_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review_tool)

BASE = b"using System;\npublic class Item_Slot_Mgr {\n  string Build(string a, int b) { return a + b; }\n}\n"
SELECTOR = {"kind": "method", "member": "Build", "parameters": ["string", "int"], "type": "Item_Slot_Mgr"}


@unittest.skipUnless(runtime(), "C# parser runtime is not installed")
class ReviewCodeDependenciesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        self.git("init", "-q")
        self.revisions = {}
        for name, data in (("base", BASE),
                           ("import", BASE.replace(b"using System;\n", b"using System;\nusing EPOOutline;\n")),
                           ("member", BASE.replace(b"a + b", b"b + a")),
                           ("member-import", BASE.replace(b"a + b", b"b + a").replace(
                               b"using System;\n", b"using System;\nusing EPOOutline;\n")),
                           ("broken", b"public class Item_Slot_Mgr {")):
            (self.repo / "UI").mkdir(exist_ok=True)
            (self.repo / "UI/UI.decompiled.cs").write_bytes(data)
            self.git("add", "-A")
            self.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", name)
            self.revisions[name] = self.git("rev-parse", "HEAD").strip()
        reviewed = Document(BASE).select(SELECTOR)["sha256"]
        self.rules = {"ammo-address": ("UI/UI.decompiled.cs", ({"sha256": reviewed, "symbol": SELECTOR},))}

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, check=True, text=True).stdout

    def review(self, new, old="base"):
        original = review_tool.RULES
        review_tool.RULES = self.rules
        try:
            return review_tool.review(self.repo, self.revisions[old], self.revisions[new])
        finally:
            review_tool.RULES = original

    def test_classifies_unchanged_import_only_and_member_drift(self):
        self.assertEqual("unchanged", self.review("base")[0]["status"])
        imported = self.review("import")[0]
        self.assertEqual("context-only", imported["status"])
        self.assertEqual(["using EPOOutline ;"], imported["context_added"])
        self.assertEqual([], imported["context_removed"])
        self.assertIn("Build", imported["member_identifiers"])
        self.assertNotEqual(self.rules["ammo-address"][1][0]["sha256"], imported["new_sha256"])
        self.assertEqual("member-changed", self.review("member")[0]["status"])

    def test_unreviewed_old_capture_cannot_hide_a_member_change(self):
        # Reviewed at base; the body changed at "member"; an import arrived later.
        self.assertEqual("old-unreviewed", self.review("member-import", old="member")[0]["status"])
        self.assertEqual("member-changed", self.review("member-import")[0]["status"])

    def test_unparseable_captures_are_reported_not_raised(self):
        self.assertEqual("missing", self.review("broken")[0]["status"])
        self.assertEqual("old-unreviewed", self.review("import", old="broken")[0]["status"])

    def test_missing_member_is_reported(self):
        self.rules["ammo-address"][1][0]["symbol"] = {**SELECTOR, "member": "Gone"}
        self.assertEqual("missing", self.review("base")[0]["status"])


if __name__ == "__main__":
    unittest.main()
