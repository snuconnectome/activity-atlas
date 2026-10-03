"""Public safety contracts: synthetic fixtures only, no GitHub/token required."""
import contextlib
import importlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
join = importlib.import_module('join')
from snapshot_contract import fingerprint, content_digest


class PublicProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = [self.commit('a', 'visible', 'PUBLIC'),
                    self.commit('b', 'PRIVATE_CANARY', 'PRIVATE'),
                    self.commit('c', 'UNKNOWN_CANARY', 'UNKNOWN')]
        self.write('raw.json', self.raw)
        self.write('manifest.json', {'scope':'pi','complete':True,'source_fingerprint':fingerprint(self.raw,'pi'),
            'observed_from':'2025-10-03T00:00:00Z','observed_through':'2026-01-22T00:00:00Z',
            'collected_at':'2026-01-22T00:00:00Z','repositories_succeeded':3,'repositories_failed':0})
        self.write('repos.json', {'repos': {}})
        self.write('rules.json', {'domain_rules': [], 'category_rules': [], 'species_rules': []})
        self.write('topics.json', {'topics': [{'topic_id': 0, 'label': 'SECRET_TOPIC',
                    'top_words': ['SECRET_TOPIC'], 'size': 3, 'color': '#0072B2'}],
                    'metadata': {'source_n_commits': 3, 'source_fingerprint': fingerprint(self.raw,'pi')}})
        self.write('embeddings.json', [{'sha': c['sha'], 'x': i, 'y': i, 'topic_id': 0}
                                       for i, c in enumerate(self.raw)])
        self.write('pulse.json', [{'week_iso': '2026-W01', 'commit_count': 3, 'top_topics': [0],
                                  'delta_bullets': ['신규 토픽: SECRET_TOPIC', 'PRIVATE_CANARY']}])
        self.write('pulse.meta.json', {'source_fingerprint':fingerprint(self.raw,'pi')})
        topics=json.loads((self.root/'topics.json').read_text())
        topics['metadata']['embedding_digest']=content_digest(json.loads((self.root/'embeddings.json').read_text()))
        self.write('topics.json',topics)
        self.write('pulse.meta.json', {'source_fingerprint':fingerprint(self.raw,'pi'),
            'topics_digest':content_digest(topics),'pulse_digest':content_digest(json.loads((self.root/'pulse.json').read_text()))})
        self.write('inventory.json', [{'org': c['org'], 'repo': c['repo'], 'visibility': c['repo_visibility'],
                                      'pushed_at': c['author_date'], 'archived': False} for c in self.raw])

    @staticmethod
    def commit(sha, repo, visibility):
        return {'sha': sha, 'org': 'snuconnectome', 'repo': repo, 'repo_visibility': visibility,
                'author_date': '2026-01-01T14:31:20Z', 'author_login': 'consenting',
                'author_canonical': 'consenting', 'message': f'{repo} SUBJECT', 'secret_extra': 'EXTRA_CANARY'}

    def write(self, name, value):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value))

    def run_join(self, profile='pub', expected=0, consent=None):
        changes = dict(REPO=self.root, REPOS_IN=self.root/'repos.json', RULES_IN=self.root/'rules.json',
                       DERIVED_TOPICS=self.root/'topics.json', DERIVED_EMBEDDINGS=self.root/'embeddings.json',
                       DERIVED_PULSE=self.root/'pulse.json', RAW_INVENTORY=self.root/'inventory.json',
                       PULSE_META=self.root/'pulse.meta.json', RAW_MANIFEST=self.root/'manifest.json',
                       PROFILE_DIRS={'pub': self.root/'data/pub', 'lab': self.root/'data/lab'},
                       ROSTER=self.root/'missing-roster')
        with patch.multiple(join, create=True, **changes), patch.object(join, 'PRIVATE_REPOS_IN', self.root/'missing-private', create=True), \
             patch.object(join, 'raw_commits_path', return_value=self.root/'raw.json'), \
             patch.object(join, 'load_consent', return_value={'consenting'} if consent is None else consent), \
             patch.object(sys, 'argv', ['join.py', '--profile', profile]), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(join.main(), expected)
        return self.root/'data'/profile

    def test_private_and_unknown_identifiers_absent_from_every_public_file(self):
        output = self.run_join()
        combined = '\n'.join(p.read_text() for p in output.glob('*.json'))
        for forbidden in ('PRIVATE_CANARY', 'UNKNOWN_CANARY', 'SECRET_TOPIC', 'EXTRA_CANARY'):
            self.assertNotIn(forbidden, combined)
        rows = json.loads((output/'commits_slim.json').read_text())
        self.assertEqual(sum(c.get('count', 1) for c in rows), 3)
        public = next(c for c in rows if c.get('repo') == 'visible')
        self.assertEqual(public['subject'], 'visible SUBJECT')
        self.assertFalse((output/'people.json').exists())

    def test_private_rows_cannot_be_linked_by_sha_or_exact_timestamp(self):
        output = self.run_join()
        rows = json.loads((output/'commits_slim.json').read_text())
        restricted = [c for c in rows if c.get('repo') != 'visible']
        self.assertTrue(restricted)
        for c in restricted:
            self.assertNotIn('sha', c)
            self.assertNotIn('subject', c)
            self.assertTrue(c['author_date'].endswith('T00:00:00Z'))
        points = json.loads((output/'embeddings.json').read_text())
        self.assertEqual([e['sha'] for e in points], ['a'])

    def test_collective_nonconsent_does_not_publish_cluster_words(self):
        cs = [dict(self.raw[0], sha=str(i), author_canonical=f'no-consent-{i%2}') for i in range(10)]
        es = [{'sha': c['sha'], 'topic_id': 0} for c in cs]
        doc = {'topics': [{'topic_id': 0, 'label': 'CANARY', 'top_words': ['CANARY'], 'size': 10}]}
        masked, n = join.mask_topic_labels(doc, es, cs, set())
        self.assertEqual(n, 1)
        self.assertNotIn('CANARY', json.dumps(masked))

    def test_consent_withdrawal_removes_previously_allowed_subject(self):
        out=self.run_join()
        self.assertIn('visible SUBJECT',(out/'commits_slim.json').read_text())
        out=self.run_join(consent=set())
        self.assertNotIn('visible SUBJECT',(out/'commits_slim.json').read_text())

    def test_mixed_consent_topic_is_neutral(self):
        cs=[dict(self.raw[0],sha=str(i),author_canonical='consenting' if i<5 else 'nonconsenting') for i in range(10)]
        es=[{'sha':c['sha'],'topic_id':0} for c in cs]
        doc={'topics':[{'topic_id':0,'label':'CANARY','top_words':['CANARY'],'size':10}]}
        masked,n=join.mask_topic_labels(doc,es,cs,{'consenting'})
        self.assertEqual(n,1)
        self.assertNotIn('CANARY',json.dumps(masked))

    def test_unexpected_derived_fields_are_not_published(self):
        topics=json.loads((self.root/'topics.json').read_text())
        points=json.loads((self.root/'embeddings.json').read_text())
        topics['metadata']['secret_extra']='EXTRA_CANARY'
        topics['topics'][0]['secret_extra']='EXTRA_CANARY'
        points[0]['secret_extra']='EXTRA_CANARY'
        topics['metadata']['embedding_digest']=content_digest(points)
        self.write('topics.json',topics);self.write('embeddings.json',points)
        meta=json.loads((self.root/'pulse.meta.json').read_text())
        meta['topics_digest']=content_digest(topics);self.write('pulse.meta.json',meta)
        out=self.run_join()
        self.assertNotIn('EXTRA_CANARY',''.join(p.read_text() for p in out.glob('*.json')))

    def test_lab_profile_retains_context(self):
        output = self.run_join('lab')
        rows = json.loads((output/'commits_slim.json').read_text())
        self.assertEqual(len(rows), 3)
        self.assertEqual({c['repo'] for c in rows}, {'visible', 'PRIVATE_CANARY', 'UNKNOWN_CANARY'})
        self.assertTrue(all(c['author'] == 'consenting' for c in rows))
        self.assertIn('SECRET_TOPIC', (output/'weekly_pulse.json').read_text())

    def test_previous_generation_files_cannot_survive_publication(self):
        self.write('data/pub/stale-secret.json', {'secret': 'PRIVATE_CANARY'})
        output = self.run_join()
        self.assertFalse((output/'stale-secret.json').exists())

    def test_network_counts_are_independent_of_coordinate_budget(self):
        with patch.object(join, 'MAX_SCATTER_POINTS', 1):
            out = self.run_join()
        first = json.loads((out/'network.json').read_text())
        with patch.object(join, 'MAX_SCATTER_POINTS', 2500):
            out = self.run_join()
        self.assertEqual(first, json.loads((out/'network.json').read_text()))
        self.assertEqual(sum(row['count'] for row in first), 3)
        self.assertEqual(sum(sum(row['topic_counts'].values()) for row in first), 3)

    def test_equal_size_changed_input_is_rejected_without_changing_output(self):
        output=self.run_join()
        before=(output/'commits_slim.json').read_bytes()
        self.raw[0]['message']='changed source'
        self.write('raw.json',self.raw)
        self.run_join(expected=1)
        self.assertEqual((output/'commits_slim.json').read_bytes(),before)

    def test_missing_derived_file_cannot_retain_old_generation(self):
        output=self.run_join()
        before=(output/'commits_slim.json').read_bytes()
        (self.root/'topics.json').unlink()
        self.run_join(expected=1)
        self.assertEqual((output/'commits_slim.json').read_bytes(),before)

    def test_missing_or_incomplete_collection_is_rejected(self):
        output=self.run_join()
        before=(output/'commits_slim.json').read_bytes()
        manifest=json.loads((self.root/'manifest.json').read_text())
        manifest['complete']=False
        self.write('manifest.json',manifest)
        self.run_join(expected=1)
        (self.root/'manifest.json').unlink()
        self.run_join(expected=1)
        self.assertEqual((output/'commits_slim.json').read_bytes(),before)

    def test_public_provenance_and_zero_weeks_reach_collection_cutoff(self):
        output=self.run_join()
        manifest=json.loads((output/'manifest.json').read_text())
        self.assertEqual(manifest['scope'],'pi')
        self.assertNotIn('source_fingerprint',manifest)
        pulse=json.loads((output/'weekly_pulse.json').read_text())
        self.assertEqual(pulse[0]['week_iso'],'2026-W04')
        self.assertEqual(pulse[0]['commit_count'],0)

    def test_same_input_with_tampered_analysis_is_rejected(self):
        output=self.run_join()
        before=(output/'commits_slim.json').read_bytes()
        points=json.loads((self.root/'embeddings.json').read_text())
        points[0]['x']=99
        self.write('embeddings.json',points)
        self.run_join(expected=1)
        self.assertEqual((output/'commits_slim.json').read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
