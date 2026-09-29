"""Real independent Git repos exercise release history and interrupted commits."""

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import test_reader
from wikibuild import git_transaction, reader, release, workspace
from wikibuild.storage import ContractError, git, json_bytes
from tools.check_release import check as independent_check


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_reader.ReaderTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.project = copy.deepcopy(self.fixture.project)
        self.project['github_owner'] = 'wiki-fixture'
        for repo in self.project['repositories']:
            repo.update(path='repositories/' + repo['id'], role='hub' if repo['id'] == 'hub' else 'topic', github_name='Wiki-' + repo['id'])
        workspace.initialize(self.root, self.project)
        for repo in self.project['repositories']:
            path = self.root / repo['path']
            git(path, 'config', 'user.name', 'Wiki fixture')
            git(path, 'config', 'user.email', 'wiki@example.invalid')
            git(path, 'add', '.')
            git(path, 'commit', '-m', 'Initialize fixture')
        workspace.checkout_lock(self.root, self.project)
        self.candidate = reader.build(self.root, self.project, self.fixture.runs, bases=release.bases(self.project))
        self.addCleanup(self.cleanup)

    def cleanup(self):
        try:
            shutil.rmtree(self.root)
        except PermissionError:
            # Windows Git object protection is not overridden for test cleanup.
            print(f'Retained protected release fixture: {self.root}')
        self.fixture.folder._finalizer.detach()

    def run_release(self):
        return release.run(self.root, self.project, self.candidate)

    def heads(self):
        return {repo['id']: git(self.root / repo['path'], 'rev-parse', 'HEAD') for repo in self.project['repositories']}

    def new_candidate(self):
        self.project['official_links'] = [{'title': 'Fixture', 'url': 'https://example.invalid/'}]
        workspace.checkout_lock(self.root, self.project)
        self.candidate = reader.build(self.root, self.project, self.fixture.runs, bases=release.bases(self.project))

    def test_commits_are_exact_repeat_is_noop_and_authored_files_survive(self):
        (self.root / 'repositories/items/notes.md').write_text('Authored explanation')
        git(self.root / 'repositories/items', 'add', 'notes.md')
        git(self.root / 'repositories/items', 'commit', '-m', 'Author notes')
        workspace.checkout_lock(self.root, self.project)
        before = self.heads()
        result, metrics = self.run_release()
        self.assertFalse(metrics['reused'])
        self.assertNotEqual(before, self.heads())
        self.assertEqual(result['publication'], 'not-published')
        release.verify(self.root, result)
        audit = independent_check(self.root)
        self.assertEqual(audit['repositories'], len(self.project['repositories']))
        workspace.checkout_lock(self.root, self.project, check=True)
        latest = self.root / 'releases/latest.json'
        stamp = latest.stat().st_mtime_ns
        heads = self.heads()
        again, metrics = self.run_release()
        self.assertTrue(metrics['reused'])
        self.assertEqual(again, result)
        self.assertEqual(heads, self.heads())
        self.assertEqual(stamp, latest.stat().st_mtime_ns)
        self.assertEqual((self.root / 'repositories/items/notes.md').read_text(), 'Authored explanation')
        candidate_index = json.loads((Path(self.candidate['path']) / 'items/snapshots' /
                                      (self.fixture.new['snapshot_id'] + '.json')).read_bytes())
        pack = self.root / 'repositories/items/site' / candidate_index['cards'][0]['path']
        original = pack.read_bytes()
        pack.write_bytes(original + b' ')
        with self.assertRaises(AssertionError):
            independent_check(self.root)
        pack.write_bytes(original)

    def test_prior_release_data_and_runtime_remain_available_without_pack_duplication(self):
        first, _ = self.run_release()
        folder = self.root / 'repositories/items/site'
        data = {p.name: p.read_bytes() for p in (folder / 'data').iterdir()}
        old_config = (folder / 'releases' / (first['release_id'] + '.json')).read_bytes()
        self.new_candidate()
        second, _ = self.run_release()
        self.assertNotEqual(first['release_id'], second['release_id'])
        self.assertEqual(old_config, (folder / 'releases' / (first['release_id'] + '.json')).read_bytes())
        self.assertEqual(data, {p.name: p.read_bytes() for p in (folder / 'data').iterdir()})
        config = json.loads(old_config)
        self.assertTrue((folder / config['runtime']['js']).is_file())
        for record in config['snapshots'].values():
            self.assertTrue((folder / record['path']).is_file())
        self.assertEqual(independent_check(self.root)['historical_configs'], 2 * len(self.project['repositories']))

    def test_reviewed_explanation_after_published_baseline_preserves_old_release_and_repeats(self):
        first, _ = self.run_release()
        repo = self.root / 'repositories/items'
        path = repo / 'curated/weight.json'
        path.parent.mkdir()
        path.write_bytes(json_bytes({'schema_version': 1, 'entity': self.fixture.a,
            'title': 'Configured weight', 'since': self.fixture.old['snapshot_id'],
            'scope': 'selected-data', 'facts': {'weight': {'path': '/weight', 'type': 'integer'}},
            'text': ['Configured weight: ', {'fact': 'weight'}], 'code': []}))
        git(repo, 'add', 'curated')
        git(repo, 'commit', '-qm', 'Reviewed explanation')
        authored_commit = git(repo, 'rev-parse', 'HEAD')
        self.candidate = reader.build(self.root, self.project, self.fixture.runs, bases=release.bases(self.project))
        with self.assertRaises(ContractError):
            self.run_release()  # An unadopted child commit remains drift.
        workspace.checkout_lock(self.root, self.project)
        with self.assertRaisesRegex(ContractError, 'Release checkout differs'):
            release.verify(self.root, first)  # Publication of the old release stays strict.
        second, _ = self.run_release()
        self.assertNotEqual(first['release_id'], second['release_id'])
        self.assertEqual(git(repo, 'rev-parse', 'HEAD^'), authored_commit)
        release.verify(self.root, first, check_checkout=False)
        release.verify(self.root, second)
        self.assertEqual(self.run_release()[0], second)
        self.assertEqual(independent_check(self.root)['historical_configs'], 2 * len(self.project['repositories']))

    def test_reviewed_successor_cannot_change_generated_outputs(self):
        first, _ = self.run_release()
        repo = self.root / 'repositories/items'
        path = repo / 'README.md'
        path.write_text('Changed generated content')
        git(repo, 'add', 'README.md')
        git(repo, 'commit', '-qm', 'Generated output drift')
        workspace.checkout_lock(self.root, self.project)
        with self.assertRaises(ContractError):
            release.verify(self.root, first, reviewed_project=self.project)
        self.assertEqual(path.read_text(), 'Changed generated content')

    def test_failure_between_children_preserves_previous_release_then_resumes(self):
        first, _ = self.run_release()
        self.new_candidate()
        original = git_transaction.promote
        count = 0

        def fail_second(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('interrupted between repositories')
            return original(*args)

        with patch.object(git_transaction, 'promote', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'interrupted'):
                self.run_release()
        self.assertEqual(json.loads((self.root / 'releases/latest.json').read_text())['release_id'], first['release_id'])
        result, _ = self.run_release()
        self.assertNotEqual(result['release_id'], first['release_id'])
        release.verify(self.root, result)

    def test_failure_after_ref_update_is_detected_as_completed_on_retry(self):
        original = git_transaction.git
        failed = False

        def fail_after_ref(path, *args):
            nonlocal failed
            value = original(path, *args)
            if args[0] == 'update-ref' and not failed:
                failed = True
                raise OSError('after ref update')
            return value

        with patch.object(git_transaction, 'git', side_effect=fail_after_ref):
            with self.assertRaisesRegex(OSError, 'after ref'):
                self.run_release()
        before = self.heads()
        result, _ = self.run_release()
        self.assertEqual(before['items'], result['repositories']['items']['commit'])
        release.verify(self.root, result)

    def test_failure_during_file_promotion_resumes_exact_prepared_commit(self):
        original = git_transaction.os.replace
        count = 0

        def fail_once(src, dst):
            nonlocal count
            if 'release-writes' in str(src):
                count += 1
                if count == 3:
                    raise OSError('during file promotion')
            return original(src, dst)

        with patch.object(git_transaction.os, 'replace', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'during file'):
                self.run_release()
        self.assertFalse((self.root / 'releases/latest.json').exists())
        result, _ = self.run_release()
        release.verify(self.root, result)

    def test_unknown_ignored_file_and_dirty_checkout_are_preserved(self):
        folder = self.root / 'repositories/items/site'
        folder.mkdir()
        unknown = folder / 'authored.local.json'
        unknown.write_text('private authored data')
        before = self.heads()
        with self.assertRaisesRegex(ContractError, 'Unknown file'):
            self.run_release()
        self.assertEqual(before, self.heads())
        self.assertEqual(unknown.read_text(), 'private authored data')
        unknown.unlink()
        note = self.root / 'repositories/items/README.md'
        note.write_text('User editing')
        with self.assertRaisesRegex(ContractError, 'dirty'):
            self.run_release()
        self.assertEqual(note.read_text(), 'User editing')

    def test_interrupted_transaction_refuses_unexpected_edits_and_modified_journal(self):
        with patch.object(git_transaction, 'promote', side_effect=OSError('stop')):
            with self.assertRaises(OSError):
                self.run_release()
        pointer = json.loads((self.root / '.local/releases/pending.json').read_text())
        plan = self.root / pointer['stage'] / 'plan.json'
        plan.write_bytes(plan.read_bytes() + b' ')
        with self.assertRaisesRegex(ContractError, 'journal was modified'):
            self.run_release()
        self.assertFalse((self.root / 'releases/latest.json').exists())

    def test_resume_preserves_unrelated_staged_edits(self):
        with patch.object(git_transaction, 'promote', side_effect=OSError('stop')):
            with self.assertRaises(OSError):
                self.run_release()
        path = self.root / 'repositories/items'
        before = self.heads()
        note = path / 'README.md'
        note.write_text('User change while stopped')
        git(path, 'add', 'README.md')
        with self.assertRaisesRegex(ContractError, 'index changed'):
            self.run_release()
        self.assertEqual(before, self.heads())
        self.assertEqual(note.read_text(), 'User change while stopped')


if __name__ == '__main__':
    unittest.main()
