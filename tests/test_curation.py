"""Committed authored inputs, captured fact checks and isolated failure history."""

import copy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_reader
from wikibuild import curation, curated_rules, pages, reader
from wikibuild.storage import ContractError, digest, git, json_bytes


class CurationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_reader.ReaderTests()
        self.fixture.setUp()
        self.root, self.project = self.fixture.root, self.fixture.project
        self.project['repositories'][1]['path'] = 'repositories/items'
        self.repo = self.root / 'repositories/items'
        self.repo.mkdir(parents=True)
        self.init_git(self.repo)
        self.path = self.repo / 'curated/weight.json'
        self.path.parent.mkdir()
        self.definition = {'schema_version': 1, 'entity': self.fixture.a, 'title': 'Configured weight',
                           'since': self.fixture.old['snapshot_id'], 'scope': 'selected-data', 'code': [],
                           'facts': {'weight': {'path': '/weight', 'type': 'integer', 'min': 1, 'max': 4}},
                           'text': ['Configured value: ', {'fact': 'weight'}, '. <script>literal</script>']}
        self.commit_definition()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        try:
            shutil.rmtree(self.root)
        except PermissionError:
            print(f'Retained protected curation fixture: {self.root}')
        self.fixture.folder._finalizer.detach()

    def init_git(self, path):
        git(path, 'init', '-q')
        git(path, 'config', 'user.name', 'Curated fixture')
        git(path, 'config', 'user.email', 'wiki@example.invalid')
        git(path, 'config', 'core.autocrlf', 'false')

    def commit_definition(self, value=None):
        self.path.write_bytes(json_bytes(self.definition if value is None else value))
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'Update authored explanation')

    def run_checks(self):
        return curation.run(self.root, self.project, self.root / 'source', self.fixture.runs)

    def note(self, result, snapshot=None, key='items/weight'):
        return result['snapshots'][snapshot or self.fixture.new['snapshot_id']][key]

    def new_weight(self, weight, build='200'):
        row = self.fixture.observation(self.fixture.a, 'Item')
        row['semantic']['facts']['weight'] = weight
        row['revision_id'] = digest(json_bytes(row['semantic']))
        self.fixture.new = self.fixture.make_run(build, [row])
        self.fixture.runs = [self.fixture.new, self.fixture.old]

    def test_real_input_first_pass_and_noop_reuse_have_stable_receipts_and_no_dependency_reads(self):
        result, metrics = self.run_checks()
        self.assertFalse(metrics['reused'])
        self.assertGreater(metrics['model_bytes_read'], 0)
        self.assertEqual(metrics['source_bytes_read'], 0)
        note = self.note(result)
        self.assertEqual(note['status'], 'passed')
        self.assertEqual(note['last_verified']['build_id'], '200')
        self.assertEqual(note['text'], 'Configured value: 3. <script>literal</script>')
        self.assertEqual(note['checks'][0]['value_sha256'], digest(json_bytes(3)))
        pointer = self.root / 'curation/latest.json'
        before = (pointer.read_bytes(), pointer.stat().st_mtime_ns)
        with patch.object(curation, 'selected', side_effect=AssertionError('Repeated model scan')), patch.object(curation, 'code_hashes', side_effect=AssertionError('Repeated code read')):
            again, metrics = self.run_checks()
        self.assertEqual(result, again)
        self.assertTrue(metrics['reused'])
        self.assertEqual(before, (pointer.read_bytes(), pointer.stat().st_mtime_ns))

    def test_failed_check_keeps_last_success_while_other_explanation_passes(self):
        other = copy.deepcopy(self.definition)
        other['facts']['weight']['max'] = 10
        (self.path.parent / 'range.json').write_bytes(json_bytes(other))
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'Independent explanation')
        self.new_weight(5)
        result, _ = self.run_checks()
        failed = self.note(result)
        self.assertEqual(failed['status'], 'unverified')
        self.assertIsNone(failed['text'])
        self.assertEqual(failed['last_verified']['build_id'], '100')
        self.assertEqual(self.note(result, key='items/range')['status'], 'passed')
        self.assertEqual(result['exceptions']['group_count'], 1)
        self.assertIn('above-maximum', failed['reasons'][0])
        site = Path(reader.build(self.root, self.project, self.fixture.runs)['path'])
        index = json.loads((site / 'items/snapshots' / (self.fixture.new['snapshot_id'] + '.json')).read_bytes())
        records = reader.load_maps(site / 'items', index['entries'])
        semantics = reader.load_maps(site / 'items', index['semantics'])
        self.assertEqual(semantics[records[self.fixture.a]['revision_id']]['facts']['weight'], 5)
        self.assertEqual(len(records[self.fixture.a]['explanations']), 2)
        self.assertIsNone(records[self.fixture.a]['last_verified'])
        self.assertEqual({x['status'] for x in records[self.fixture.a]['explanations']}, {'passed', 'unverified'})
        search = reader.load_maps(site / 'items', index['search'])
        self.assertNotIn('explanations', search[self.fixture.a])

    def test_new_definition_and_extractor_correction_invalidate_only_expected_checks(self):
        first, _ = self.run_checks()
        self.definition['facts']['weight']['max'] = 8
        self.commit_definition()
        self.new_weight(6)
        corrected, _ = self.run_checks()
        self.assertNotEqual(first['run_id'], corrected['run_id'])
        self.assertEqual(self.note(corrected)['text'], 'Configured value: 6. <script>literal</script>')
        self.assertNotEqual(self.note(first)['definition_sha256'], self.note(corrected)['definition_sha256'])

    def test_new_capture_reuses_unchanged_historical_checks_without_model_scans(self):
        first, _ = self.run_checks()
        middle = self.fixture.new
        self.new_weight(5, '300')
        self.fixture.runs.insert(1, middle)
        original = curation.selected
        scanned = []

        def track(root, run, active):
            scanned.append(run['snapshot_id'])
            return original(root, run, active)

        with patch.object(curation, 'selected', side_effect=track):
            result, metrics = self.run_checks()
        self.assertEqual(scanned, [self.fixture.new['snapshot_id']])
        self.assertEqual(metrics['snapshots_reused'], 2)
        self.assertEqual(result['snapshots'][middle['snapshot_id']], first['snapshots'][middle['snapshot_id']])
        self.assertEqual(self.note(result)['last_verified']['build_id'], '200')

    def test_missing_fields_entities_and_type_changes_do_not_invent_values(self):
        for value in [True, '3', None]:
            with self.subTest(value=value):
                self.new_weight(value)
                result, _ = self.run_checks()
                self.assertEqual(self.note(result)['status'], 'unverified')
                self.assertIn('type-changed', self.note(result)['reasons'][0])
        self.definition['facts']['weight']['path'] = '/missing'
        self.commit_definition()
        result, _ = self.run_checks()
        self.assertIn('fact-not-captured', self.note(result)['reasons'][0])
        self.definition['entity'] = 'e-' + 'f' * 32
        self.commit_definition()
        result, _ = self.run_checks()
        self.assertIn('target-entry-missing', self.note(result)['reasons'][0])

    def test_code_changes_are_detected_from_captured_git_source(self):
        source = self.root / 'source'
        source.mkdir()
        self.init_git(source)
        path = source / 'Item.cs'
        path.write_bytes(b'class Item { const int Limit = 3; }\n')
        self.definition.update(scope='code-backed', code=[{'path': 'Item.cs', 'sha256': digest(path.read_bytes())}])
        self.commit_definition()
        git(source, 'add', '.')
        git(source, 'commit', '-qm', 'Old game code')
        self.fixture.old['source_commit'] = git(source, 'rev-parse', 'HEAD')
        path.write_bytes(b'class Item { const int Limit = 4; }\n')
        git(source, 'add', '.')
        git(source, 'commit', '-qm', 'New game code')
        self.fixture.new['source_commit'] = git(source, 'rev-parse', 'HEAD')
        result, metrics = self.run_checks()
        self.assertGreater(metrics['source_bytes_read'], 0)
        self.assertEqual(self.note(result, self.fixture.old['snapshot_id'])['status'], 'passed')
        self.assertEqual(self.note(result)['status'], 'unverified')
        self.assertIn('code-changed-or-missing', self.note(result)['reasons'][0])
        self.assertEqual(self.note(result)['last_verified']['build_id'], '100')
        self.assertNotIn('class Item', json.dumps(result))

    def test_malformed_definition_preserves_previous_checked_text_and_unsafe_expression_is_never_run(self):
        first, _ = self.run_checks()
        self.definition['text'] = [{'eval': "__import__('os').system('no')"}]
        self.commit_definition()
        result, _ = self.run_checks()
        note = self.note(result)
        self.assertEqual(note['status'], 'unverified')
        self.assertEqual(note['last_verified'], self.note(first)['last_verified'])
        self.assertIn('invalid-definition', note['reasons'][0])

    def test_since_boundary_does_not_backfill_older_snapshots(self):
        self.definition['since'] = self.fixture.new['snapshot_id']
        self.commit_definition()
        result, _ = self.run_checks()
        self.assertEqual(result['snapshots'][self.fixture.old['snapshot_id']], {})
        self.assertEqual(self.note(result)['status'], 'passed')

    def test_unknown_baseline_is_an_exception_and_never_grants_a_successful_check(self):
        self.definition['since'] = 'build-999-' + 'f' * 12
        self.commit_definition()
        result, _ = self.run_checks()
        self.assertEqual(self.note(result)['status'], 'unverified')
        self.assertIsNone(self.note(result)['last_verified'])
        self.assertIn('starting-snapshot-not-captured', self.note(result)['reasons'])

    def test_removed_entry_keeps_failed_explanation_out_of_compact_search(self):
        self.fixture.new = self.fixture.make_run('200', [], absent={self.fixture.a: 'not-present'})
        self.fixture.runs = [self.fixture.new, self.fixture.old]
        built = reader.build(self.root, self.project, self.fixture.runs)
        site = Path(built['path']) / 'items'
        index = json.loads((site / 'snapshots' / (self.fixture.new['snapshot_id'] + '.json')).read_bytes())
        entry = reader.load_maps(site, index['entries'])[self.fixture.a]
        self.assertEqual(entry['status'], 'not-present')
        self.assertEqual(entry['explanations'][0]['status'], 'unverified')
        self.assertEqual(entry['explanations'][0]['last_verified']['build_id'], '100')
        search = reader.load_maps(site, index['search'])[self.fixture.a]
        self.assertNotIn('explanations', search)

    def test_render_expansion_is_bounded_and_preserves_last_success(self):
        first, _ = self.run_checks()
        self.definition['text'] = ['é' * 8192, {'fact': 'weight'}]
        self.commit_definition()
        result, _ = self.run_checks()
        self.assertEqual(self.note(result)['status'], 'unverified')
        self.assertIn('rendered-text-exceeds-16-KiB', self.note(result)['reasons'])
        self.assertEqual(self.note(result)['last_verified'], self.note(first)['last_verified'])
        self.assertEqual(result['exceptions']['group_count'], 1)
        self.assertEqual(curated_rules.render({'text': ['é' * 8192]}, {}), 'é' * 8192)

    def test_definition_change_during_generation_preserves_previous_pointer(self):
        self.run_checks()
        pointer = self.root / 'curation/latest.json'
        before = pointer.read_bytes()
        self.new_weight(6)
        original = curation.selected

        def change_definition(*args):
            result = original(*args)
            self.path.write_text('{}')
            return result

        with patch.object(curation, 'selected', side_effect=change_definition):
            with self.assertRaisesRegex(ContractError, 'Commit curated'):
                self.run_checks()
        self.assertEqual(pointer.read_bytes(), before)

    def test_dirty_input_and_changed_receipt_are_execution_failures(self):
        self.path.write_text('{}')
        with self.assertRaisesRegex(ContractError, 'Commit curated'):
            self.run_checks()
        self.path.write_bytes(json_bytes(self.definition))
        result, _ = self.run_checks()
        receipt = self.root / 'curation/runs' / (result['run_id'] + '.json')
        value = json.loads(receipt.read_bytes())
        value['payload']['snapshots'] = {}
        receipt.write_bytes(json_bytes(value))
        with self.assertRaisesRegex(ContractError, 'receipt differs'):
            self.run_checks()

    def test_interrupted_pointer_promotion_reuses_prepared_receipt_then_advances(self):
        original = curation.write_changed
        pointer = self.root / 'curation/latest.json'

        def fail_pointer(path, data):
            if path == pointer:
                raise OSError('pointer interruption')
            return original(path, data)

        with patch.object(curation, 'write_changed', side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, 'pointer interruption'):
                self.run_checks()
        with patch.object(curation, 'selected', side_effect=AssertionError('Repeated model scan')):
            result, metrics = self.run_checks()
        self.assertTrue(metrics['reused'])
        self.assertEqual(json.loads(pointer.read_bytes())['run_id'], result['run_id'])

    def test_markdown_renders_authored_text_literally_and_json_pointer_handles_escapes(self):
        result, _ = self.run_checks()
        text = pages.markdown('item', [{'entity_key': self.fixture.a, 'name': 'Item', 'status': 'present',
                                       'explanations': [self.note(result)]}], self.fixture.new['snapshot_id'], 'r', '/items/').decode()
        self.assertIn('&lt;script&gt;literal&lt;/script&gt;', text)
        self.assertNotIn('<script>literal', text)
        self.assertEqual(curated_rules.pointer({'a/b': {'~key': [7]}}, '/a~1b/~0key/0'), 7)


if __name__ == '__main__':
    unittest.main()
