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

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
j=importlib.import_module('join');w=importlib.import_module('weekly_pulse')


def event(author,repo,days):
    return {'org':'snuconnectome','repo':repo,'sha':author+repo+str(days),
            'author_canonical':author,'author_login':author,
            'author_date':(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()}


class TimeSemanticsTests(unittest.TestCase):
    def test_recent_sparkline_has_eight_continuous_weeks(self):
        cs=[event('student','repo',140),event('student','repo',0)]
        cards=j.build_people(cs,{},j.person_weeks(cs),{})
        self.assertEqual(cards[0]['recent_repo_counts'],[0,0,0,0,0,0,0,1])

    def test_PI_commit_before_student_arrival_is_not_contact(self):
        cs=[event('jcha9928','repo',140),event('student','repo',0)]
        card=j.build_people(cs,{},j.person_weeks(cs),{})[0]
        self.assertIsNone(card.get('days_since_pi_repo_commit',card.get('days_since_pi_contact')))

    def test_zero_days_does_not_sort_as_unknown(self):
        cs=[event('old','oldrepo',40),event('jcha9928','oldrepo',30),
            event('today','todayrepo',2),event('jcha9928','todayrepo',0)]
        cards=j.build_people(cs,{},j.person_weeks(cs),{})
        self.assertEqual([c['login'] for c in cards],['old','today'])

    def test_pulse_zero_activity_weeks_are_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            cs=[event('student','repo',140),event('student','repo',0)]
            for name,doc in [('raw.json',cs),('topics.json',{'topics':[],'metadata':{'source_fingerprint':w.fingerprint(cs,'pi')}}),('embeddings.json',[])]:
                (root/name).write_text(json.dumps(doc))
            (root/'manifest.json').write_text(json.dumps({'complete':True,'scope':'pi','source_fingerprint':w.fingerprint(cs,'pi'),'observed_through':cs[-1]['author_date']}))
            with patch.multiple(w,RAW_MANIFEST=root/'manifest.json',COMMITS_IN=root/'raw.json',TOPICS_IN=root/'topics.json',EMBEDDINGS_IN=root/'embeddings.json',OUT=root/'out.json',DERIVED_DIR=root),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(w.main(),0)
            pulse=json.loads((root/'out.json').read_text())
            self.assertEqual(len(pulse),21)
            self.assertEqual(sum(c['commit_count'] for c in pulse),2)
            before=(root/'out.json').read_bytes()
            (root/'topics.json').write_text(json.dumps({'topics':[],'metadata':{'source_fingerprint':'stale'}}))
            with patch.multiple(w,RAW_MANIFEST=root/'manifest.json',COMMITS_IN=root/'raw.json',TOPICS_IN=root/'topics.json',EMBEDDINGS_IN=root/'embeddings.json',OUT=root/'out.json',DERIVED_DIR=root),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(w.main(),1)
            self.assertEqual((root/'out.json').read_bytes(),before)

    def test_ISO_year_is_calendar_week_year(self):
        self.assertEqual(w.iso_week('2018-12-31T00:00:00Z'),'2019-W01')
        self.assertEqual(j.iso_week('2021-01-01T00:00:00Z'),'2020-W53')

    def test_partial_author_scope_does_not_assert_succession_risk(self):
        cs=[event('jcha9928','repo',14),event('jcha9928','repo',0)]
        tax={'snuconnectome/repo':{'domain':'brain-foundation-model','wp':'WP1'}}
        inv=[{'org':'snuconnectome','repo':'repo','archived':False,'pushed_at':cs[-1]['author_date']}]
        rows=j.build_lifecycle(cs,tax,inv,j.person_weeks(cs))
        self.assertFalse(rows[0]['succession_risk'])


if __name__=='__main__':unittest.main()
