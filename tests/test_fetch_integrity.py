import contextlib
import importlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
fetch = importlib.import_module('fetch_commits')


class FetchIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.raw=self.root/'raw/commits.json';self.raw.parent.mkdir()
        self.now=datetime.now(timezone.utc)
        self.old={'sha':'old','org':'snuconnectome','repo':'one','author_login':'student',
                  'author_canonical':'student','author_date':(self.now-timedelta(days=500)).isoformat(),'message':'fixture'}
        self.raw.write_text(json.dumps([self.old]))

    def run_fetch(self, argv, fail=False, visibility='PUBLIC', extra=None):
        repos=[{'name':n,'pushedAt':self.now.isoformat(),'isArchived':False,'visibility':visibility} for n in ['one','two']]
        def list_repos(org):return (repos if org=='snuconnectome' else [],None)
        def commits(org,name,*unused):
            if fail and name=='two':return [],'fixture API failure'
            return [{'sha':'same','login':'jcha9928','date':self.now.isoformat(),'msg':'fixture'}] + (extra or []),None
        changes={'RAW_DIR':self.raw.parent,'RAW_COMMITS':self.raw,'RAW_STATE':self.raw.parent/'state.json',
                 'RAW_INVENTORY':self.raw.parent/'repos.json'}
        with patch.multiple(fetch,**changes),patch.object(fetch,'scope_paths',return_value={'raw':self.raw.parent}),patch.object(fetch,'raw_commits_path',return_value=self.raw), \
             patch.object(fetch,'list_repos',side_effect=list_repos),patch.object(fetch,'repo_commits',side_effect=commits), \
             patch.object(sys,'argv',['fetch_commits.py']+argv),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            return fetch.main()

    def test_full_PI_replaces_scope_and_expired_rows(self):
        self.assertEqual(self.run_fetch(['--full']),0)
        rows=json.loads(self.raw.read_text())
        self.assertTrue(all(c['author_login']=='jcha9928' for c in rows))
        self.assertTrue(all(c['sha']!='old' for c in rows))

    def test_same_SHA_retains_both_repository_associations(self):
        self.assertEqual(self.run_fetch(['--full']),0)
        rows=[c for c in json.loads(self.raw.read_text()) if c['sha']=='same']
        self.assertEqual(len(rows),2)
        self.assertEqual({c['repo'] for c in rows},{'one','two'})

    def test_failed_fetch_preserves_previous_snapshot(self):
        (self.raw.parent/'state.json').write_text('{}')
        (self.raw.parent/'repos.json').write_text('[]')
        (self.raw.parent/'manifest.json').write_text('{"previous":true}')
        snapshot={p.name:p.read_bytes() for p in self.raw.parent.iterdir()}
        before=self.raw.read_bytes()
        self.assertEqual(self.run_fetch(['--full'],fail=True),1)
        self.assertEqual(self.raw.read_bytes(),before)
        self.assertEqual({p.name:p.read_bytes() for p in self.raw.parent.iterdir()},snapshot)

    def test_refetched_events_outside_window_are_excluded(self):
        extra=[{'sha':str(days),'login':'jcha9928','date':(self.now-timedelta(days=days)).isoformat(),'msg':'fixture'} for days in [500,-2]]
        self.assertEqual(self.run_fetch(['--full'],extra=extra),0)
        self.assertEqual({c['sha'] for c in json.loads(self.raw.read_text())},{'same'})

    def test_malformed_API_output_is_a_failure(self):
        with patch.object(fetch,'gh',return_value=('not-json',None)):
            self.assertIsNotNone(fetch.repo_commits('org','repo','2026-01-01T00:00:00Z')[1])

    def test_visibility_downgrade_applies_to_existing_rows(self):
        self.old.update(author_login='jcha9928',author_canonical='jcha9928',
                        author_date=self.now.isoformat(),repo_visibility='PUBLIC')
        self.raw.write_text(json.dumps([self.old]))
        self.assertEqual(self.run_fetch([],visibility='PRIVATE'),0)
        self.assertTrue(all(c['repo_visibility']=='PRIVATE' for c in json.loads(self.raw.read_text())))


if __name__=='__main__':unittest.main()
