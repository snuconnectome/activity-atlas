import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))


class PublicGuardTests(unittest.TestCase):
    def test_nested_lab_artifact_is_rejected(self):
        guard = importlib.import_module('check_public')
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'_site-lab/data/pub/commits_slim.json'
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps([{'author':'CANARY'}]))
            self.assertTrue(guard.check_site(Path(root)))

    def test_changed_public_payload_is_rejected(self):
        guard=importlib.import_module('check_public')
        contract=importlib.import_module('snapshot_contract')
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'data/pub';folder.mkdir(parents=True)
            row={'org':'snuconnectome','repo':'visible','author_date':'2026-01-01T00:00:00Z',
                 'domain':'infra','wp':'unbound','repo_category':'core'}
            (folder/'commits_slim.json').write_text(json.dumps([row]))
            manifest={'payload_digest':contract.content_digest({'commits_slim.json':[row]})}
            (folder/'manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(guard.check_site(Path(root)),[])
            row['repo']='changed'
            (folder/'commits_slim.json').write_text(json.dumps([row]))
            self.assertTrue(guard.check_site(Path(root)))

    def test_unexpected_author_field_is_rejected(self):
        guard = importlib.import_module('check_public')
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'data/pub/unexpected.json'
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'author_login':'CANARY'}))
            self.assertTrue(guard.check_site(Path(root)))


if __name__ == '__main__':unittest.main()
