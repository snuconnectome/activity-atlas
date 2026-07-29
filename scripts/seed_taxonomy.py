#!/usr/bin/env python3
"""One-shot seeder: agentic-ai/docs/REPO_MAP.md → data/taxonomy/repos.json.

This is NOT a pipeline stage. Run it once, hand-check the result, commit it,
and from then on `data/taxonomy/repos.json` is the atlas's source of truth.

Why not parse REPO_MAP.md on every run
--------------------------------------
Measured 2026-07-29: it names 123 repos, covering ~38% of the 262 currently
active ones, and `neurox-org` is absent entirely. Its tables also differ per
WP (WP1 carries a Modality column, WP3 an Indication column, WP2/4/5 neither),
cells hold comma-separated repo lists, and the Org column uses the shorthands
both/trans/snu. A parser wired into the pipeline would break every time someone
edits the document, and 62% of repos would silently read as unclassified.

So REPO_MAP stays what it is — a narrative document maintained by hand — and
the atlas keeps its own machine-readable table, with join.py reporting drift.

Usage:
    python scripts/seed_taxonomy.py --dry-run
    python scripts/seed_taxonomy.py            # writes, refuses to clobber
    python scripts/seed_taxonomy.py --force    # overwrite, losing manual edits
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from aa_paths import REPO

REPO_MAP = Path("/home/juke/git/agentic-ai/docs/REPO_MAP.md")
TAXONOMY_DIR = REPO / "data" / "taxonomy"
REPOS_OUT = TAXONOMY_DIR / "repos.json"

ORGS = ["snuconnectome", "Transconnectome", "neurox-org"]

# REPO_MAP's Org shorthand → candidate real orgs, in preference order.
ORG_SHORTHAND = {
    "snu": ["snuconnectome"],
    "trans": ["Transconnectome"],
    "both": ["Transconnectome", "snuconnectome"],
    "(new)": ["Transconnectome", "snuconnectome"],
    "(local)": [],
    "(local/snu)": ["snuconnectome"],
}

WP_HEADING = re.compile(r"^###\s+(WP\d)\s*·\s*(.+?)\s*$")
# Any other heading closes the current WP section. Without this, the tables in
# "Legacy / Archived", "By integration need", and "Open questions" get absorbed
# into WP5 and their prose cells become phantom repo names.
OTHER_HEADING = re.compile(r"^#{2,3}\s+")
ROLE_RE = re.compile(r"\*\*(P|S|R)\*\*|^\s*(P|S|R)\b")


def gh_repos(org: str) -> list[str]:
    proc = subprocess.run(
        ["gh", "repo", "list", org, "--limit", "500", "--json", "name"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        print(f"  ⚠️  could not list {org}: {proc.stderr.strip()}", file=sys.stderr)
        return []
    return [r["name"] for r in json.loads(proc.stdout or "[]")]


def parse_repo_map(text: str) -> list[dict]:
    """Extract (repo, org_hint, role, extra, wp) rows from the WP tables."""
    rows: list[dict] = []
    wp = None
    for line in text.splitlines():
        m = WP_HEADING.match(line)
        if m:
            wp = m.group(1)
            continue
        if OTHER_HEADING.match(line):
            wp = None
            continue
        if wp is None or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0].lower() == "repo" or set(cells[0]) <= {"-", ":"}:
            continue  # header or separator

        repo_cell, org_cell, role_cell = cells[0], cells[1], cells[2]
        extra = cells[3] if len(cells) > 3 else ""

        role_m = ROLE_RE.search(role_cell)
        role = (role_m.group(1) or role_m.group(2)) if role_m else "S"

        for name in (n.strip().strip("`*") for n in repo_cell.split(",")):
            if not name or "*" in name:      # skip glob entries like SNU-Psychology-Chatbot-*.md
                continue
            rows.append({
                "name": name,
                "org_hint": org_cell.strip().lower(),
                "role": role,
                "extra": extra.strip().strip("—").strip(),
                "wp": wp,
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed data/taxonomy/repos.json from REPO_MAP.md")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite an existing repos.json")
    args = ap.parse_args()

    if not REPO_MAP.exists():
        print(f"❌ {REPO_MAP} not found", file=sys.stderr)
        return 1
    if REPOS_OUT.exists() and not args.force and not args.dry_run:
        print(f"❌ {REPOS_OUT.relative_to(REPO)} already exists.", file=sys.stderr)
        print("   Seeding is one-shot; it would discard manual classifications.", file=sys.stderr)
        print("   Pass --force only if you mean to lose them.", file=sys.stderr)
        return 1

    rows = parse_repo_map(REPO_MAP.read_text(encoding="utf-8"))
    print(f"REPO_MAP: {len(rows)} repo mentions across WP tables")

    print("Resolving org shorthands against live repo lists ...")
    live: dict[str, set[str]] = {}
    lower_index: dict[str, list[tuple[str, str]]] = {}
    for org in ORGS:
        names = gh_repos(org)
        live[org] = set(names)
        for n in names:
            lower_index.setdefault(n.lower(), []).append((org, n))
        print(f"  {org:20s} {len(names)} repos")

    resolved: dict[str, dict] = {}
    ambiguous: list[str] = []
    unmatched: list[str] = []

    for row in rows:
        candidates = lower_index.get(row["name"].lower(), [])
        if not candidates:
            unmatched.append(row["name"])
            continue
        preferred = ORG_SHORTHAND.get(row["org_hint"], ORGS)
        picks = [c for c in candidates if c[0] in preferred] or candidates
        if row["org_hint"] == "both":
            picks = candidates                       # genuinely mirrored in both orgs
        elif len(picks) > 1:
            ambiguous.append(row["name"])
            picks = picks[:1]

        for org, real_name in picks:
            key = f"{org}/{real_name}"
            entry = resolved.setdefault(key, {
                "wp": row["wp"], "wp_role": row["role"], "wp_secondary": [],
                "modality": None, "indication": None, "note": row["extra"] or None,
                "source": "repo_map",
            })
            if entry["wp"] != row["wp"] and row["wp"] not in entry["wp_secondary"]:
                # e.g. MBBN is listed under both WP1 and WP3
                entry["wp_secondary"].append(row["wp"])
            if row["wp"] == "WP1":
                entry["modality"] = row["extra"] or None
            elif row["wp"] == "WP3":
                entry["indication"] = row["extra"] or None

    print()
    print(f"  resolved      {len(resolved)} org/repo keys")
    print(f"  unmatched     {len(unmatched)} names in REPO_MAP with no live repo")
    print(f"  ambiguous     {len(ambiguous)} names present in >1 org (took first)")
    multi = [k for k, v in resolved.items() if v["wp_secondary"]]
    print(f"  multi-WP      {len(multi)}  {multi[:4]}")

    total_live = sum(len(v) for v in live.values())
    print(f"  coverage      {len(resolved)}/{total_live} live repos ({len(resolved)/total_live:.0%})")

    if args.dry_run:
        print("\n(dry run — nothing written)")
        if unmatched:
            print(f"\nunmatched sample: {sorted(set(unmatched))[:12]}")
        return 0

    doc = {
        "version": "1.0.0",
        "_note": (
            "Seeded once from agentic-ai/docs/REPO_MAP.md, then maintained here. "
            "REPO_MAP is not read at runtime. `source` records how each entry was "
            "assigned: repo_map | rule | manual."
        ),
        "repos": dict(sorted(resolved.items())),
    }
    TAXONOMY_DIR.mkdir(parents=True, exist_ok=True)
    REPOS_OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n✅ wrote {len(resolved)} entries → {REPOS_OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
