import unittest
from unittest.mock import patch

from wikibuild.code_dependencies import Document, SelectionError, runtime, validate
from wikibuild.storage import ContractError


class CodeDependencyTests(unittest.TestCase):
    selector = {"kind": "method", "type": "Game.Generator", "member": "Generate", "parameters": ["float"]}

    def fingerprint(self, data, selector=None):
        return Document(data.encode()).select(selector or self.selector)["sha256"]

    def test_member_check_ignores_unrelated_members_and_whitespace_but_detects_behavior(self):
        original = 'namespace Game { class Generator { void Generate(float factor) { Fuel += factor * 0.15f; } int Unrelated = 3; } }'
        expected = self.fingerprint(original)
        self.assertEqual(expected, self.fingerprint(original.replace('Unrelated = 3', 'Unrelated = 7')))
        self.assertEqual(expected, self.fingerprint(original.replace('Fuel +=', '// explanation\n Fuel  += ')))
        self.assertNotEqual(expected, self.fingerprint(original.replace('0.15f', '0.20f')))
        self.assertNotEqual(expected, self.fingerprint(original.replace('+=', '-=')))

    def test_nameless_tuple_declarator_does_not_break_field_selection(self):
        # Parser error recovery can produce a field declarator with no name (build 25675256).
        selector = {"kind": "field", "type": "A", "member": "count"}
        self.assertTrue(self.fingerprint('class A { public int count; var (x, y) = pair; }', selector))

    def test_alias_and_enclosing_type_changes_are_dependencies(self):
        original = 'using Fuel = Model.A; namespace Game { class Generator : First { void Generate(float factor) { } } }'
        expected = self.fingerprint(original)
        self.assertNotEqual(expected, self.fingerprint(original.replace('Model.A', 'Model.B')))
        self.assertNotEqual(expected, self.fingerprint(original.replace(': First', ': Second')))

    def test_qualified_owner_overloads_and_strings_cannot_select_another_member(self):
        source = 'namespace Other { class Generator { void Generate(float factor) { } } } namespace Game { class Generator { void Generate(int factor) { } void Generate(float factor) { string s = "} // not a comment"; } } }'
        expected = self.fingerprint(source)
        self.assertEqual(expected, self.fingerprint(source.replace('Generate(int factor) { }', 'Generate(int factor) { Changed(); }')))
        self.assertNotEqual(expected, self.fingerprint(source.replace('not a comment', 'changed string')))
        with self.assertRaisesRegex(SelectionError, 'member-missing'):
            self.fingerprint(source, {**self.selector, 'parameters': ['double']})

    def test_type_and_field_checks_cover_defaults_with_nested_and_file_scoped_namespaces(self):
        source = 'namespace Game; class Save { public class Config { public int Count = 3; public float Rate = 1f; } }'
        field = {'kind': 'field', 'type': 'Game.Save.Config', 'member': 'Count'}
        full = {'kind': 'type', 'type': 'Game.Save.Config'}
        self.assertEqual(self.fingerprint(source, field), self.fingerprint(source.replace('Rate = 1f', 'Rate = 2f'), field))
        self.assertNotEqual(self.fingerprint(source, full), self.fingerprint(source.replace('Rate = 1f', 'Rate = 2f'), full))
        self.assertNotEqual(self.fingerprint(source, field), self.fingerprint(source.replace('Count = 3', 'Count = 4'), field))

    def test_ambiguous_missing_and_malformed_source_fail_explicitly(self):
        cases = [('namespace Game { class Generator { void Generate(float factor) { } void Generate(float factor) { } } }', 'member-ambiguous'),
                 ('namespace Game { class Generator { } class Generator { } }', 'type-ambiguous'),
                 ('namespace Game { class Changed { } }', 'type-missing'),
                 ('namespace Game { class Generator { void Generate(float factor) {', 'parse-error')]
        for source, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(SelectionError, reason):
                self.fingerprint(source)

    def test_selector_schema_and_runtime_dependency_mismatch_fail(self):
        for selector in ({}, {'kind': []}, {**self.selector, 'execute': 'unsafe'}, {**self.selector, 'parameters': 'float'}):
            with self.subTest(selector=selector), self.assertRaises(ContractError):
                validate(selector)
        with patch('wikibuild.code_dependencies.metadata.version', return_value='999'):
            self.assertNotEqual(runtime()['required'], runtime()['installed'])
            with self.assertRaisesRegex(ContractError, 'pinned parser'):
                Document(b'class Test {}')

    def test_parameter_modifiers_properties_and_constructors(self):
        source = 'class A { A(int value) { } int Count { get; set; } void Use(ref int value, out float total, in double input, params string[] rest) { total = 0; } }'
        selectors = [{'kind': 'constructor', 'type': 'A', 'member': 'A', 'parameters': ['int']},
                     {'kind': 'property', 'type': 'A', 'member': 'Count'},
                     {'kind': 'method', 'type': 'A', 'member': 'Use',
                      'parameters': ['ref int', 'out float', 'in double', 'params string[]']}]
        for selector in selectors:
            with self.subTest(selector=selector):
                self.assertEqual(len(self.fingerprint(source, selector)), 64)
        with self.assertRaisesRegex(SelectionError, 'encoding'):
            Document(b'class A { string x = "\xff"; }')


if __name__ == '__main__':
    unittest.main()
