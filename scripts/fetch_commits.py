#!/usr/bin/env python3
"""Fetch commits across 3 GitHub organizations → local raw store.

Writes: $ACTIVITY_ATLAS_DATA_DIR/raw/commits.json  (default ~/.local/share/activity-atlas)
        $ACTIVITY_ATLAS_DATA_DIR/raw/state.json    (per-repo incremental cursor)

Never writes into the repo. Raw rows carry full commit message bodies for repos
that are overwhelmingly private; scripts/join.py produces the publishable
projection and attaches the taxonomy.

This script assigns no categories. Classification is a join against local
tables (data/taxonomy/), so relabelling costs zero API calls.

Why per-repo REST instead of /search/commits
--------------------------------------------
The search endpoint caps any single query at 1,000 results and is limited to 30
requests/minute. Transconnectome alone has >5,000 commits in a 12-month window,
so search silently truncated most of them — and the old code could not tell a
truncated result from a complete one. `/repos/{org}/{repo}/commits` is GA, uses
the 5,000/hour core budget, and returns the author login that search-based
collection was discarding.

The repo-walk shape is ported from lab-ai-usage/scripts/github_collector.py
(active_repos + repo_commits, lines 30-59), including its identity rule: commits
without a GitHub login are excluded rather than falling back to the free-text
commit.author.name, which splits one person across two rows.

Authentication: `gh auth login` with `repo` scope (plus org membership to see
private repos).

Usage:
    python scripts/fetch_commits.py              # incremental
    python scripts/fetch_commits.py --full       # ignore cursors, refetch window
    python scripts/fetch_commits.py --dry-run    # estimate requests, write nothing
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aa_paths import RAW_COMMITS, RAW_DIR, RAW_INVENTORY, RAW_STATE, raw_commits_path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ORGS = ["snuconnectome", "Transconnectome", "neurox-org"]

# ⚠️ "snuconnectome" is BOTH an org (above) and a user login (below). Keep the
# two apart when reading this file — conflating them yields a silent zero.
#
# The PI commits under two accounts. Measured 2026-07-29 over 90 days in
# Transconnectome alone: jcha9928 262 commits, snuconnectome 228. Collecting
# only one of them hid more than half of his own activity.
PI_LOGINS = ["jcha9928", "snuconnectome"]

# login → canonical login. The PI's own pair is hardcoded because it predates
# the roster; the rest come from lab-ai-usage/roster.json's __aliases__ so a
# second account belonging to one student does not read as two people. The
# original login stays on every row, so the merge is auditable and reversible
# without refetching.
ROSTER = Path("/home/juke/git/lab-ai-usage/roster.json")
ALIASES = {"snuconnectome": "jcha9928"}
if ROSTER.exists():
    try:
        ALIASES.update(json.loads(ROSTER.read_text(encoding="utf-8")).get("__aliases__", {}))
    except json.JSONDecodeError:
        print("⚠️  roster.json unreadable — alias merge limited to the PI", file=sys.stderr)

# Ported verbatim from lab-ai-usage/scripts/github_collector.py:65-66
BOT_LOGINS = {
    "claude", "web-flow", "github-actions", "github-actions[bot]",
    "dependabot[bot]", "renovate[bot]",
}

LOOKBACK_DAYS = 365

# ---------------------------------------------------------------------------
# gh plumbing
# ---------------------------------------------------------------------------

def gh(args: list[str], jq: str | None = None) -> tuple[str | None, str | None]:
    """Run gh, returning (stdout, error). Ported from github_collector.py:20-27."""
    cmd = ["gh"] + args
    if jq:
        cmd += ["--jq", jq]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None, (proc.stderr or "").strip()
    return proc.stdout, None


def list_repos(org: str) -> tuple[list[dict], str | None]:
    """Every repo in the org, active or not.

    The dormant ones matter: a repo with no commits in a year is exactly what
    the lifecycle view needs to surface, and filtering them out here would make
    them invisible rather than obviously idle.
    """
    out, err = gh([
        "repo", "list", org, "--limit", "500",
        "--json", "name,pushedAt,isArchived,visibility",
    ])
    if err:
        return [], err
    return (json.loads(out) if out and out.strip() else []), None


def is_active(repo: dict, since_iso: str) -> bool:
    return not repo.get("isArchived") and (repo.get("pushedAt") or "") >= since_iso


def repo_commits(org: str, repo: str, since_iso: str) -> tuple[list[dict], str | None]:
    """All commits in one repo since `since_iso`, with author login.

    --paginate emits one JSON object per line once --jq projects the array.
    """
    out, err = gh(
        ["api", "--paginate", f"repos/{org}/{repo}/commits?since={since_iso}&per_page=100"],
        jq='.[] | {sha: .sha, login: (.author.login // ""), '
           'date: .commit.author.date, msg: .commit.message}',
    )
    if err:
        # An empty repo answers 409 Git Repository is empty — not a failure.
        if "409" in err or "empty" in err.lower():
            return [], None
        return [], err
    commits = []
    for line in (out or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            commits.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return commits, None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def canonical(login: str) -> str:
    return ALIASES.get(login, login)


def normalize(raw: dict, org: str, repo: str, visibility: str) -> dict:
    """Raw gh commit → schema `commit_raw` row (data/schema.json 0.2.0)."""
    login = raw.get("login", "")
    return {
        "sha": raw.get("sha", ""),
        "org": org,
        "repo": repo,
        "author_login": login,
        "author_canonical": canonical(login),
        "author_date": raw.get("date", ""),
        "message": (raw.get("msg") or "").strip(),
        "repo_visibility": visibility,
        # additions/deletions/files need /stats/contributors (1 call per repo,
        # not 1 per commit as previously documented). Deferred on priority, not
        # cost — commit counts must be trustworthy first.
        "additions": None,
        "deletions": None,
        "files_count": None,
    }


def load_state() -> dict:
    if RAW_STATE.exists():
        try:
            return json.loads(RAW_STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("  ⚠️  state.json unreadable — treating as a full fetch", file=sys.stderr)
    return {}


def load_existing() -> list[dict]:
    """Rows already in the store, minus any predating schema 0.2.0.

    Pre-0.2.0 rows have no author_login at all — search-based collection threw
    it away — so they cannot be attributed and must be refetched rather than
    merged forward.
    """
    path = raw_commits_path()
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    current = [r for r in rows if "author_login" in r]
    dropped = len(rows) - len(current)
    if dropped:
        print(f"  ℹ️  dropped {dropped} pre-0.2.0 rows (no author attribution); refetching")
    return current


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch commits across orgs into the local raw store.")
    ap.add_argument("--full", action="store_true",
                    help="ignore per-repo cursors and refetch the whole window")
    ap.add_argument("--dry-run", action="store_true",
                    help="report repo counts and request estimate, write nothing")
    ap.add_argument("--all-authors", action="store_true",
                    help="keep every contributor, not just the PI (Phase 4; lab-internal only)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {} if args.full else load_state()

    keep_logins = None if args.all_authors else {canonical(x) for x in PI_LOGINS}

    print(f"Activity Atlas — fetching commits since {window_start[:10]}")
    print(f"  Orgs:    {', '.join(ORGS)}")
    print(f"  Authors: {'ALL contributors' if args.all_authors else ', '.join(PI_LOGINS) + f' → {canonical(PI_LOGINS[0])}'}")
    print(f"  Mode:    {'full' if args.full else 'incremental'}")
    print(f"  Store:   {RAW_COMMITS}")
    print()

    # ── Discover repos ───────────────────────────────────────────────────
    targets: list[tuple[str, str, str]] = []   # (org, repo, visibility)
    inventory: list[dict] = []                 # every repo, dormant included
    failed_orgs: list[str] = []
    for org in ORGS:
        repos, err = list_repos(org)
        if err:
            print(f"  ❌ {org:20s} repo list failed: {err}", file=sys.stderr)
            failed_orgs.append(org)
            continue
        active = [r for r in repos if is_active(r, window_start)]
        for r in repos:
            inventory.append({
                "org": org,
                "repo": r["name"],
                "pushed_at": r.get("pushedAt"),
                "archived": bool(r.get("isArchived")),
                "visibility": r.get("visibility", "UNKNOWN"),
                "active": is_active(r, window_start),
            })
        for r in active:
            targets.append((org, r["name"], r.get("visibility", "UNKNOWN")))
        private_n = sum(1 for r in active if r.get("visibility") == "PRIVATE")
        print(f"  → {org:20s} {len(active):4d} active / {len(repos)} total "
              f"({private_n} private)")

    if failed_orgs:
        print(f"\n❌ repo discovery failed for: {', '.join(failed_orgs)}", file=sys.stderr)
        print("   Refusing to overwrite the store with a partial result.", file=sys.stderr)
        return 1

    print(f"\n  {len(targets)} repos to walk (~{len(targets)} + pagination requests)")
    if args.dry_run:
        print("\n(dry run — nothing written)")
        return 0

    # ── Walk repos ───────────────────────────────────────────────────────
    existing = load_existing()
    by_sha = {c["sha"]: c for c in existing if c.get("sha")}
    kept_before = len(by_sha)

    failed_repos: list[str] = []
    skipped_identity = 0
    new_rows = 0

    for i, (org, repo, visibility) in enumerate(targets, 1):
        full = f"{org}/{repo}"
        since = window_start if args.full else state.get(full, window_start)
        raws, err = repo_commits(org, repo, since)
        if err:
            print(f"  ⚠️  {full}: {err}", file=sys.stderr)
            failed_repos.append(full)
            continue

        for raw in raws:
            login = raw.get("login", "")
            if not login or login in BOT_LOGINS:
                skipped_identity += 1
                continue
            if keep_logins is not None and canonical(login) not in keep_logins:
                continue
            row = normalize(raw, org, repo, visibility)
            if row["sha"] and row["sha"] not in by_sha:
                new_rows += 1
            by_sha[row["sha"]] = row

        # Advance the cursor only for repos that answered successfully.
        state[full] = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        if i % 25 == 0:
            print(f"  … {i}/{len(targets)} repos")

    commits = sorted(by_sha.values(), key=lambda c: c["author_date"], reverse=True)

    # ── Write ────────────────────────────────────────────────────────────
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    RAW_COMMITS.write_text(
        json.dumps(commits, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    RAW_STATE.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    RAW_INVENTORY.write_text(
        json.dumps(sorted(inventory, key=lambda r: (r["org"], r["repo"])),
                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ── Report ───────────────────────────────────────────────────────────
    by_author: dict[str, int] = {}
    for c in commits:
        by_author[c["author_login"]] = by_author.get(c["author_login"], 0) + 1

    print()
    print(f"✅ {len(commits)} commits in store ({kept_before} before, {new_rows} new)")
    print(f"   → {RAW_COMMITS}")
    if skipped_identity:
        print(f"   {skipped_identity} commits skipped (no GitHub login, or bot)")
    print()
    print("   By original login:")
    for login, n in sorted(by_author.items(), key=lambda kv: -kv[1]):
        merged = canonical(login)
        arrow = f" → {merged}" if merged != login else ""
        print(f"     {login:24s}{arrow:>16s}  {n:5d}")

    if failed_repos:
        print()
        print(f"❌ {len(failed_repos)} repos failed — data is INCOMPLETE:", file=sys.stderr)
        for f in failed_repos[:10]:
            print(f"     {f}", file=sys.stderr)
        if len(failed_repos) > 10:
            print(f"     … and {len(failed_repos) - 10} more", file=sys.stderr)
        print("   Their cursors were not advanced; rerun to retry.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
