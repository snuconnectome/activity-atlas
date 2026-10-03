import json
import unittest
from pathlib import Path
from jsonschema import Draft7Validator, FormatChecker


class PublicSchemaTests(unittest.TestCase):
    def test_committed_public_rows_follow_the_published_contract(self):
        repo=Path(__file__).resolve().parents[1]
        schema=json.loads((repo/'data/schema.json').read_text())
        cases=[('commits_slim.json',None,'commit'),('embeddings.json',None,'embedding'),
               ('weekly_pulse.json',None,'weekly_pulse'),('topics.json','topics','topic')]
        for filename,key,definition in cases:
            with self.subTest(file=filename):
                doc=json.loads((repo/'data/pub'/filename).read_text())
                rows=doc[key] if key else doc
                val=Draft7Validator({'$ref':'#/definitions/'+definition,'definitions':schema['definitions']},format_checker=FormatChecker())
                errors=[(i,list(e.path)) for i,row in enumerate(rows) for e in val.iter_errors(row)]
                self.assertEqual(errors[:5],[])



if __name__=='__main__':unittest.main()
