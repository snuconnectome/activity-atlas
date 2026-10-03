"""Shared path resolution for the Activity Atlas pipeline.

Raw commit data never lives in the repo. It carries full message bodies for
mostly-private repos, so it goes to an XDG data directory instead — the same
pattern scripts/workmem.py already uses for private working-memory items.

Override with ACTIVITY_ATLAS_DATA_DIR (useful for tests and for keeping a
second machine's fetch separate).
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# [A] PRIVATE RAW — outside the repo, never committed, never published
DATA_DIR = Path(
    os.environ.get("ACTIVITY_ATLAS_DATA_DIR", Path.home() / ".local" / "share" / "activity-atlas")
).expanduser()
SCOPE = os.environ.get('ACTIVITY_ATLAS_SCOPE', 'pi')


def scope_paths(scope):
    if scope not in {'pi', 'all'}:
        raise ValueError('ACTIVITY_ATLAS_SCOPE must be pi or all')
    base = DATA_DIR / 'scopes' / scope
    return {'raw': base / 'raw', 'derived': base / 'derived'}


RAW_DIR = scope_paths(SCOPE)['raw']
RAW_COMMITS = RAW_DIR / "commits.json"
RAW_STATE = RAW_DIR / "state.json"
RAW_INVENTORY = RAW_DIR / "repos.json"

# [B] LOCAL DERIVED — topic model and weekly pulse output. Also outside the repo:
# topic labels are n-grams lifted from commit messages, so they inherit whatever
# the messages were. Everything here passes through join.py, which is the only
# place that decides what may be published.
DERIVED_DIR = scope_paths(SCOPE)['derived']
DERIVED_TOPICS = DERIVED_DIR / "topics.json"
DERIVED_EMBEDDINGS = DERIVED_DIR / "embeddings.json"
DERIVED_PULSE = DERIVED_DIR / "weekly_pulse.json"
DERIVED_REGISTRY = DERIVED_DIR / "topic_registry.json"

# [C] LAB-INTERNAL — gitignored, rendered locally, never deployed
LAB_DIR = REPO / "data" / "lab"

# [D] PUBLIC — committed and deployed to GitHub Pages
PUB_DIR = REPO / "data" / "pub"
PRIVATE_TAXONOMY = DATA_DIR / "taxonomy" / "repos.json"

PROFILE_DIRS = {"pub": PUB_DIR, "lab": LAB_DIR}

RAW_MANIFEST = RAW_DIR / 'manifest.json'


def raw_commits_path() -> Path:
    """The explicitly selected scope; legacy stores require a fresh fetch."""
    return RAW_COMMITS
