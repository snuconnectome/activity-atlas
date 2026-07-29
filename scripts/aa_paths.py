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

# [D] PUBLIC DERIVED — committed and deployed to GitHub Pages
PUB_DIR = REPO / "data" / "pub"

# Pre-Phase-1 location. Read-only fallback so an existing checkout keeps working
# until the next fetch; nothing ever writes here again.
LEGACY_RAW_COMMITS = REPO / "data" / "raw" / "commits.json"


def raw_commits_path() -> Path:
    """Where to read raw commits from, preferring the XDG location."""
    if RAW_COMMITS.exists():
        return RAW_COMMITS
    return LEGACY_RAW_COMMITS
