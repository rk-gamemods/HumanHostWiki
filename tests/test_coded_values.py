"""Source-defined labels, graph edges, invalid codes and the captured field contract."""
from collections import defaultdict
from types import SimpleNamespace
import unittest

from wikibuild.adapters import coded_values as coded
from wikibuild.adapters.items_loot import observation
from wikibuild.exceptions import Exceptions
from wikibuild import model


class CodedValuesTests(unittest.TestCase):
    def definitions(self, source):
        result = coded.Definitions()
        result.parse(source.encode(), 'Game', 'Game/Game.decompiled.cs')
        return result

    def test_inherited_and_nested_enum_fields_use_declaring_scope(self):
        definitions = self.definitions('''namespace World {
          class Base { public enum Kind { None, Rifle = 5, Shotgun } public Kind type; }
          class Child : Base { public Detail[] details; public bool active;
            public class Detail { public Base.Kind kind; } }
          class Other { public enum Kind { Wrong = 5 } }
        }''')
        fields = definitions.selected('Game', 'World.Child', {'type': int, 'active': int, 'details': [{'kind': int}]})
        self.assertEqual(('Game', 'World.Base.Kind'), fields['/type']['enum'])
        self.assertEqual(('Game', 'World.Base.Kind'), fields['/details/*/kind']['enum'])
        self.assertIsNone(fields['/active']['enum'])
        self.assertEqual('Shotgun', definitions.enums[('Game', 'World.Base.Kind')]['values'][6])

    def subject(self, declaration='None, Rifle = 5, Shotgun'):
        definitions = self.definitions('class Weapon { public enum Kind { ' + declaration + ' } public Kind type; public bool active; }')
        state = {'definitions': definitions, 'fields': {('Game', 'Weapon'): definitions.selected('Game', 'Weapon', {'type': int, 'active': int})},
                 'used': {}, 'ammo': defaultdict(set), 'ammo_valid': False}
        return SimpleNamespace(coded=state)

    def row(self, value=5):
        row = observation('weapon', 'object#1', 'Rifle', {'type': value, 'active': 1}, 'Catalog/objects/object.jsonl', ['type', 'active'])
        row.update(component={'assembly': 'Game', 'class': 'Weapon'}, topic='combat')
        return row

    def test_named_values_form_graph_edges_preserve_numeric_provenance(self):
        source, issues, row = self.subject(), Exceptions(), self.row()
        coded.enrich(source, row, issues)
        self.assertEqual({'/type': 'Rifle', '/active': 'Yes'}, row['fact_labels'])
        self.assertEqual(5, row['facts']['type'])
        target = next(coded.extract(source, issues))
        target['topic'] = 'technical-reference'
        assignments = {row['observation_key']: 'weapon', target['observation_key']: 'kind'}
        dependencies = {e['path']: {'git_blob': 'hash'} for e in row['evidence']}
        projected = model.project(row, 'weapon', model.targets_index([row, target], assignments), {}, dependencies, issues)
        self.assertEqual(['kind'], projected['semantic']['relationships'][0]['targets'])
        self.assertEqual(5, projected['provenance']['coded_facts']['/type'])
        self.assertEqual(0, issues.report()['group_count'])
        self.assertNotIn('source_numeric_value', target['facts'])
        self.assertEqual(5, target['evidence'][0]['numeric_value'])

    def test_unknown_and_ambiguous_codes_log_exceptions_without_guessing(self):
        for source, row in [(self.subject(), self.row(9)), (self.subject('Rifle = 5, AlsoRifle = 5'), self.row())]:
            issues = Exceptions()
            coded.enrich(source, row, issues)
            self.assertTrue(row['fact_labels']['/type'].startswith('Unresolved code'))
            self.assertEqual([], row['relationships'])
            self.assertEqual(1, issues.report()['group_count'])

    def test_missing_declaration_does_not_turn_back_into_a_numeric_label(self):
        source, issues, row = self.subject(), Exceptions(), self.row()
        source.coded['fields'][('Game', 'Weapon')]['/type'] = {'error': 'missing declaration'}
        coded.enrich(source, row, issues)
        self.assertEqual('Unresolved code (5)', row['fact_labels']['/type'])
        self.assertEqual(1, issues.report()['group_count'])

    def test_nested_values_and_ammo_names(self):
        self.assertEqual([('/rows/0/type', 5), ('/rows/1/type', 6)], list(coded.values({'rows': [{'type': 5}, {'type': 6}]}, '/rows/*/type')))
        self.assertEqual('7.62x54mm', coded.readable('_7_62x54mm'))
        self.assertEqual('.45 ACP', coded.readable('_45ACP'))
        self.assertEqual('Carpentry Workbench', coded.readable('CarpentryWorkbench'))

    def test_changed_or_missing_ammo_helpers_fail_the_relationship_guard(self):
        self.assertFalse(coded.ammo_rule_valid(b'class Item_Slot_Mgr {}'))


if __name__ == '__main__':
    unittest.main()
