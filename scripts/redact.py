#!/usr/bin/env python3
"""Redact raw commits into the publishable slim form.

Reads:  data/raw/commits.json   (local-only; never committed, never published)
Writes: data/pub/commits_slim.json

Why this exists
---------------
`data/raw/commits.json` carries full commit message bodies (mean ~550 chars,
max ~2500) for repos that are overwhelmingly PRIVATE. Publishing it — which is
what `_quarto.yml` used to do via `resources: data/**/*.json` — leaks
unsubmitted paper titles, unannounced grants, and internal discussion to the
open web.

Everything the four pages actually render needs only a one-line subject. So
raw stays out of the repo and this script produces the redacted projection
that gets committed and deployed.

Usage:
    python scripts/redact.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMITS_IN = REPO / "data" / "raw" / "commits.json"
PUB_DIR = REPO / "data" / "pub"
COMMITS_OUT = PUB_DIR / "commits_slim.json"

SUBJECT_MAX = 80

# Fields carried through to the published projection. Anything not listed here
# is dropped — an allowlist, so a new raw field can never leak by default.
KEEP_FIELDS = (
    "sha",
    "org",
    "repo",
    "author_date",
    "repo_category",
    "additions",
    "deletions",
    "files_count",
)


def subject_of(message: str) -> str:
    """First line of a commit message, capped. Matches what latent.qmd rendered."""
    return (message or "").split("\n")[0][:SUBJECT_MAX]


def redact(commit: dict) -> dict:
    out = {k: commit[k] for k in KEEP_FIELDS if k in commit}
    out["subject"] = subject_of(commit.get("message", ""))
    return out


def main() -> int:
    if not COMMITS_IN.exists():
        print(f"❌ {COMMITS_IN.relative_to(REPO)} not found.", file=sys.stderr)
        print("   Run scripts/fetch_commits.py first (local only).", file=sys.stderr)
        return 1

    commits = json.loads(COMMITS_IN.read_text(encoding="utf-8"))
    slim = [redact(c) for c in commits]

    PUB_DIR.mkdir(parents=True, exist_ok=True)
    COMMITS_OUT.write_text(
        json.dumps(slim, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    leaked = [k for c in slim for k in c if k not in KEEP_FIELDS and k != "subject"]
    if leaked:
        print(f"❌ unexpected fields in output: {sorted(set(leaked))}", file=sys.stderr)
        return 1

    longest = max((len(c["subject"]) for c in slim), default=0)
    print(f"✅ redacted {len(slim)} commits → {COMMITS_OUT.relative_to(REPO)}")
    print(f"   message bodies dropped · longest subject {longest}/{SUBJECT_MAX} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
