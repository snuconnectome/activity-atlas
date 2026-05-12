"""Fetch commits across 3 GitHub organizations → data/raw/commits.json.

Reuses the gh-api pattern from lab-monitor/backend/app/services/github_service.py
(lines 78-117), stripped of SQLAlchemy and async, with full commit records
instead of just counts.

Authentication: relies on `gh auth status` — must have `repo` scope.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ORGS = ["snuconnectome", "Transconnectome", "neurox-org"]
AUTHOR = "snuconnectome"  # active gh account (Type: User)

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "commits.json"
LOOKBACK_DAYS = 365  # last 12 months

# TODO(human): Map each `org/repo` to one of: proposal | paper | education | core | tool | other
# Run this script once with the dict empty; the summary at the bottom will print
# every repo that appeared. Copy that list here with the right label for each.
# Categories are defined in data/schema.json (commit.repo_category enum).
REPO_CATEGORIES: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def fetch_org_commits(org: str, author: str, since: str, until: str) -> list[dict]:
    """Search commits by author within an org, paginated.

    Uses `gh api --paginate --slurp` to combine every page into one JSON array
    of response objects, each containing an "items" key.
    """
    query = f"author:{author}+org:{org}+author-date:{since}..{until}"
    cmd = [
        "gh", "api",
        "-H", "Accept: application/vnd.github.cloak-preview+json",
        f"/search/commits?q={query}&per_page=100",
        "--paginate",
        "--slurp",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"  ⚠️  gh api failed for {org}: {proc.stderr.strip()}", file=sys.stderr)
        return []
    pages = json.loads(proc.stdout) if proc.stdout.strip() else []
    items: list[dict] = []
    for page in pages:
        items.extend(page.get("items", []))
    return items


def normalize(item: dict, org: str) -> dict:
    """Convert raw gh search/commits response to our locked schema row."""
    repo_full = item.get("repository", {}).get("full_name", "")
    repo_name = repo_full.split("/", 1)[1] if "/" in repo_full else repo_full
    commit = item.get("commit", {})
    return {
        "sha": item.get("sha", ""),
        "org": org,
        "repo": repo_name,
        "author_date": commit.get("author", {}).get("date", ""),
        "message": commit.get("message", "").strip(),
        # additions/deletions/files require per-commit detail calls.
        # Deferred — set null for v1; can backfill in Phase 7 if needed.
        "additions": None,
        "deletions": None,
        "files_count": None,
        "repo_category": REPO_CATEGORIES.get(repo_full, "core"),
    }


def main() -> int:
    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    until = today.isoformat()

    print(f"Activity Atlas — fetching commits {since} → {until}")
    print(f"  Author: {AUTHOR}")
    print(f"  Orgs:   {', '.join(ORGS)}")
    print()

    all_commits: list[dict] = []
    for org in ORGS:
        items = fetch_org_commits(org, AUTHOR, since, until)
        rows = [normalize(it, org) for it in items]
        all_commits.extend(rows)
        print(f"  → {org:20s} {len(rows):4d} commits")

    # Sort newest-first for human readability when diffing the JSON
    all_commits.sort(key=lambda c: c["author_date"], reverse=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(all_commits, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"✅ Wrote {len(all_commits)} commits → {OUTPUT.relative_to(Path.cwd())}")

    if not REPO_CATEGORIES:
        unique = sorted({f"{c['org']}/{c['repo']}" for c in all_commits})
        print()
        print("⚠️  REPO_CATEGORIES is empty — every commit defaulted to 'core'.")
        print("    Repos found (paste into REPO_CATEGORIES with a label each):")
        print()
        for r in unique:
            print(f'        "{r}": "core",')
        print()
        print("    Categories: proposal | paper | education | core | tool | other")

    return 0


if __name__ == "__main__":
    sys.exit(main())
