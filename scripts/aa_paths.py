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
RAW_DIR = DATA_DIR / "raw"
RAW_COMMITS = RAW_DIR / "commits.json"
RAW_STATE = RAW_DIR / "state.json"

# [B] LOCAL DERIVED — topic model and weekly pulse output. Also outside the repo:
# topic labels are n-grams lifted from commit messages, so they inherit whatever
# the messages were. Everything here passes through join.py, which is the only
# place that decides what may be published.
DERIVED_DIR = DATA_DIR / "derived"
DERIVED_TOPICS = DERIVED_DIR / "topics.json"
DERIVED_EMBEDDINGS = DERIVED_DIR / "embeddings.json"
DERIVED_PULSE = DERIVED_DIR / "weekly_pulse.json"

# [C] LAB-INTERNAL — gitignored, rendered locally, never deployed
LAB_DIR = REPO / "data" / "lab"

# [D] PUBLIC — committed and deployed to GitHub Pages
PUB_DIR = REPO / "data" / "pub"

PROFILE_DIRS = {"pub": PUB_DIR, "lab": LAB_DIR}

# Pre-Phase-1 location. Read-only fallback so an existing checkout keeps working
# until the next fetch; nothing ever writes here again.
LEGACY_RAW_COMMITS = REPO / "data" / "raw" / "commits.json"


def raw_commits_path() -> Path:
    """Where to read raw commits from, preferring the XDG location."""
    if RAW_COMMITS.exists():
        return RAW_COMMITS
    return LEGACY_RAW_COMMITS
