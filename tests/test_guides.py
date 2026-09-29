"""Contract tests for data-driven guide rendering."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from wikibuild.guides import GuideError, load_spec, render, render_markdown, text_runs


ROOT = Path(__file__).resolve().parents[1]
ENTITY = "e-" + "a" * 32
SECOND = "e-" + "b" * 32


def fixture():
    spec = {
        "id": "field-guide", "title": "Field guide", "dek": "A compact test.",
        "sections": [
            {"id": "start", "heading": "Start", "blocks": [
                {"type": "sentence", "query": "welcome", "template": "Bring {items}."},
                {"type": "list", "query": "empty", "item": "{name}", "title": "Missing gear", "empty": "No gear yet."},
                {"type": "list", "query": "empty", "item": "{name}", "optional": True},
                {"type": "definitions", "query": "definitions", "item": "{label}: {meaning}"},
                {"type": "checklist", "query": "tasks", "item": "{task}", "title": "Tasks",
                 "group_by": "category", "limit_per_group": 1, "more": "{remaining} more tasks"},
                {"type": "steps", "query": "steps", "item": "Use {tool}."},
                {"type": "table", "query": "table", "columns": ["Item", "Cost"]},
            ]},
            {"id": "place", "repeat": "places", "heading": "Region {name}", "blocks": [
                {"type": "sentence", "query": "place.summary", "template": "Found {count} things."},
            ]},
            {"id": "sources", "heading": "Sources", "blocks": [
                {"type": "sources", "template": "Game {game_version}, build {build_id}."},
            ]},
            {"id": "unavailable", "heading": "Unavailable", "blocks": [
                {"type": "sentence", "query": "none", "template": "{value}", "optional": True},
            ]},
        ],
    }
    queries = {
        "welcome": lambda context, scope: {"items": [{"text": "stone", "entity": ENTITY}, 2]},
        "empty": lambda context, scope: [],
        "definitions": lambda context, scope: [{"label": "Damage", "meaning": "Hit strength"}],
        "tasks": lambda context, scope: [
            {"category": "Tools", "task": {"text": "Pick", "entity": SECOND}},
            {"category": "Food", "task": "Berry"},
            {"category": "Tools", "task": "Axe"},
        ],
        "steps": lambda context, scope: [{"tool": "hammer"}],
        "table": lambda context, scope: [{"Item": {"text": "Pick", "entity": SECOND}, "Cost": ["wood", 3]}],
        "places": lambda context, scope: [{"name": {"text": "North", "entity": ENTITY}, "count": 2}],
        "place.summary": lambda context, scope: scope,
        "none": lambda context, scope: None,
    }
    context = {"snapshot": {"game_version": "1.0", "build_id": 42}}
    return spec, queries, context


GOLDEN = f"""# Field guide

A compact test.

## Start

Bring [stone](/entry/{ENTITY}), 2.

### Missing gear

No gear yet.

- **Damage**: Hit strength

### Tasks

#### Tools

- [ ] [Pick](/entry/{SECOND})

1 more tasks

#### Food

- [ ] Berry

1. Use hammer.

| Item | Cost |
| --- | --- |
| [Pick](/entry/{SECOND}) | wood, 3 |

## Region [North](/entry/{ENTITY})

Found 2 things.

## Sources

Game 1.0, build 42.
"""


class GuideTests(unittest.TestCase):
    def test_real_specs_validate(self):
        paths = sorted((ROOT / "guides").glob("*.json"))
        self.assertEqual(len(paths), 4)
        for path in paths:
            with self.subTest(path=path.name):
                spec = load_spec(path)
                self.assertEqual(spec["id"], path.stem)

    def test_all_block_types_markdown_and_determinism(self):
        spec, queries, context = fixture()
        document = render(spec, queries, context)
        self.assertEqual([s["id"] for s in document["sections"]], ["start", "place-0", "sources"])
        self.assertEqual([b["type"] for b in document["sections"][0]["blocks"]],
                         ["sentence", "list", "definitions", "checklist", "steps", "table"])
        self.assertEqual(document["sections"][0]["blocks"][0]["runs"], [
            {"text": "Bring "}, {"text": "stone", "entity": ENTITY}, {"text": ", 2."}])
        self.assertEqual(document["sections"][0]["blocks"][5]["rows"][0]["Cost"], [{"text": "wood, 3"}])
        self.assertEqual(render_markdown(document, lambda key: "/entry/" + key), GOLDEN)
        encoded = json.dumps(document, sort_keys=True)
        self.assertEqual(encoded, json.dumps(render(spec, queries, context), sort_keys=True))

    def test_text_runs_cover_all_visible_text(self):
        spec, queries, context = fixture()
        document = render(spec, queries, context)
        entries = list(text_runs(document))
        paths = [path for path, _ in entries]
        text = [value for _, value in entries]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("/title", paths)
        self.assertIn("/dek", paths)
        self.assertTrue(any("/heading/" in path for path in paths))
        self.assertTrue(any(path.endswith("/title") and "blocks" in path for path in paths))
        self.assertTrue(any("/runs/" in path for path in paths))
        self.assertTrue(any("/columns/" in path for path in paths))
        self.assertTrue(any("/rows/" in path for path in paths))
        self.assertTrue(any("/more/" in path for path in paths))
        self.assertIn("stone", text)
        self.assertIn("Pick", text)
        self.assertIn("1 more tasks", text)

    def test_required_empty_and_missing_variable_name_location(self):
        spec, queries, context = fixture()
        spec["sections"][0]["blocks"][1].pop("empty")
        with self.assertRaisesRegex(GuideError, "field-guide section start block 1.*required query"):
            render(spec, queries, context)
        spec, queries, context = fixture()
        spec["sections"][0]["blocks"][0]["template"] = "{absent}"
        with self.assertRaisesRegex(GuideError, "field-guide section start block 0.*missing variable 'absent'"):
            render(spec, queries, context)

    def test_sentence_empty_and_optional(self):
        spec, queries, context = fixture()
        spec["sections"][0]["blocks"][0]["empty"] = "No supplies."
        queries["welcome"] = lambda context, scope: None
        result = render(spec, queries, context)
        self.assertEqual(result["sections"][0]["blocks"][0]["runs"], [{"text": "No supplies."}])
        del spec["sections"][0]["blocks"][0]["empty"]
        with self.assertRaisesRegex(GuideError, "field-guide section start block 0.*required query"):
            render(spec, queries, context)

    def test_load_spec_rejects_unknown_and_missing_fields(self):
        spec, _, _ = fixture()
        invalid = []
        changed = copy.deepcopy(spec)
        changed["unexpected"] = True
        invalid.append(changed)
        changed = copy.deepcopy(spec)
        changed["sections"][0]["blocks"][0]["type"] = "chart"
        invalid.append(changed)
        changed = copy.deepcopy(spec)
        del changed["sections"][0]["blocks"][0]["query"]
        invalid.append(changed)
        changed = copy.deepcopy(spec)
        changed["sections"][0]["blocks"][0]["surprise"] = 1
        invalid.append(changed)
        changed = copy.deepcopy(spec)
        del changed["title"]
        invalid.append(changed)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.json"
            for candidate in invalid:
                with self.subTest(candidate=candidate):
                    path.write_text(json.dumps(candidate), encoding="utf-8")
                    with self.assertRaises(GuideError):
                        load_spec(path)


if __name__ == "__main__":
    unittest.main()
