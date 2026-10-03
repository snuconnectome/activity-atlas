import importlib
import json
import sys
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))


class SnapshotContractTests(unittest.TestCase):
    def test_PI_and_all_author_paths_are_separate(self):
        paths=importlib.import_module('aa_paths')
        self.assertNotEqual(paths.scope_paths('pi')['raw'],paths.scope_paths('all')['raw'])
        self.assertNotEqual(paths.scope_paths('pi')['derived'],paths.scope_paths('all')['derived'])

    def test_equal_row_count_does_not_imply_equal_input(self):
        contract=importlib.import_module('snapshot_contract')
        a=[{'org':'org','repo':'repo','sha':'a','message':'A'}, {'org':'org','repo':'repo','sha':'c','message':'C'}]
        b=[{'org':'org','repo':'repo','sha':'b','message':'B'}, {'org':'org','repo':'repo','sha':'c','message':'C'}]
        self.assertNotEqual(contract.fingerprint(a,'pi'),contract.fingerprint(b,'pi'))
        self.assertNotEqual(contract.fingerprint(a,'pi'),contract.fingerprint(a,'all'))
        self.assertEqual(contract.fingerprint(a,'pi'),contract.fingerprint(list(reversed(a)),'pi'))

    def test_failed_exchange_preserves_both_generations(self):
        contract=importlib.import_module('snapshot_contract')
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/'live';new=Path(tmp)/'staged'
            old.mkdir();new.mkdir()
            (old/'value').write_text('old');(new/'value').write_text('new')
            with patch.object(contract,'_exchange',side_effect=OSError('injected')):
                with self.assertRaises(OSError):contract.replace_generation(new,old)
            self.assertEqual((old/'value').read_text(),'old')
            self.assertEqual((new/'value').read_text(),'new')

    def test_successful_exchange_replaces_directory_without_stale_files(self):
        contract=importlib.import_module('snapshot_contract')
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/'live';old.mkdir();(old/'stale').write_text('old')
            contract.write_snapshot(old,{'value.json':{'v':'new'}})
            self.assertEqual(json.loads((old/'value.json').read_text()),{'v':'new'})
            self.assertFalse((old/'stale').exists())


if __name__=='__main__':unittest.main()
