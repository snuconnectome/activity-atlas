#!/usr/bin/env python3
"""Inspect the entire deployable artifact, including stale nested build output."""
import argparse
import json
from pathlib import Path
from jsonschema import Draft7Validator, FormatChecker
from snapshot_contract import content_digest

PUBLIC_FILES = {'commits_slim.json', 'topics.json', 'embeddings.json', 'weekly_pulse.json',
                'palette.json', 'taxonomy_coverage.json', 'lifecycle.json', 'drift.json',
                'network.json', 'manifest.json'}
FORBIDDEN_KEYS = {'message', 'author', 'author_login', 'author_canonical', 'display', 'login'}


def check_site(root):
    errors=[]
    for p in root.rglob('*'):
        rel=p.relative_to(root)
        if any(part in {'_site-lab', 'lab', 'raw'} for part in rel.parts):
            errors.append(f'forbidden private path: {rel}')
            continue
        if not p.is_file() or p.suffix != '.json':
            continue
        if 'pub' in rel.parts and p.name not in PUBLIC_FILES:
            errors.append(f'unexpected public data file: {rel}')
        try:
            doc=json.loads(p.read_text())
        except (ValueError, UnicodeError):
            errors.append(f'invalid JSON: {rel}')
            continue
        def forbidden(value):
            if isinstance(value, dict):
                return bool(set(value) & FORBIDDEN_KEYS) or any(forbidden(v) for v in value.values())
            if isinstance(value, list):
                return any(forbidden(v) for v in value)
            return False
        if forbidden(doc):
            errors.append(f'private field in JSON: {rel}')
    schema=json.loads((Path(__file__).resolve().parents[1]/'data/schema.json').read_text())
    for folder in {p.parent for p in root.rglob('manifest.json') if p.parent.name == 'pub'}:
        try:
            manifest=json.loads((folder/'manifest.json').read_text())
            payload={p.name:json.loads(p.read_text()) for p in sorted(folder.glob('*.json')) if p.name!='manifest.json'}
        except (ValueError,UnicodeError):
            continue  # Already reported above.
        if manifest.get('payload_digest') != content_digest(payload):
            errors.append(f'changed or incomplete public generation: {folder.relative_to(root)}')
        checks=[('commits_slim.json',payload.get('commits_slim.json',[]),'commit'),
                ('embeddings.json',payload.get('embeddings.json',[]),'embedding'),
                ('weekly_pulse.json',payload.get('weekly_pulse.json',[]),'weekly_pulse'),
                ('topics.json',payload.get('topics.json',{}).get('topics',[]),'topic')]
        for name,rows,definition in checks:
            validator=Draft7Validator({'$ref':'#/definitions/'+definition,'definitions':schema['definitions']},format_checker=FormatChecker())
            for i,row in enumerate(rows):
                if not validator.is_valid(row):
                    errors.append(f'invalid public contract: {folder.relative_to(root)}/{name} row {i}')
    for folder in {p.parent for p in root.rglob('commits_slim.json') if p.parent.name=='pub'}:
        if not (folder/'manifest.json').exists():
            errors.append(f'missing generation manifest: {folder.relative_to(root)}')
    return errors


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--site',type=Path,default=Path('_site'))
    args=ap.parse_args()
    if not args.site.is_dir():
        ap.error('site directory does not exist')
    errors=check_site(args.site)
    for error in errors[:20]:print(error)
    print(f'Public artifact guard: {len(errors)} errors')
    return int(bool(errors))


if __name__=='__main__':raise SystemExit(main())
