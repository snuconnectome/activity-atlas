#!/usr/bin/env python3
"""Join raw commits with the taxonomy, then emit the published projection.

Reads:  $ACTIVITY_ATLAS_DATA_DIR/raw/commits.json   (local only)
        data/taxonomy/repos.json                     (curated, committed)
        data/taxonomy/rules.json                     (fallback patterns)
Writes: data/pub/commits_slim.json
        data/pub/palette.json
        data/pub/taxonomy_coverage.json

Why classification lives here and not in fetch_commits.py
---------------------------------------------------------
It used to be a dict inside the fetcher, so every label change meant refetching
262 repos from GitHub — minutes of API traffic to relabel one string, and
impossible to reproduce anywhere without an admin-scope token. Classification
is a join against local tables, so it belongs in its own step that costs no API
calls at all.

Two axes, deliberately not merged into one:
  wp     — budget/programme axis (WP1..WP5), comparable against MASTER_PLAN's
           40/15/25/10/10 split
  domain — scientific axis (brain foundation model, neural field modelling,
           agentic AI, ...)
They are not 1:1. WP1 alone holds both foundation models and neural fields,
while human/animal work cuts across every WP.

Usage:
    python scripts/join.py
    python scripts/join.py --report     # coverage only, write nothing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

from aa_paths import PUB_DIR, REPO, raw_commits_path

TAXONOMY_DIR = REPO / "data" / "taxonomy"
REPOS_IN = TAXONOMY_DIR / "repos.json"
RULES_IN = TAXONOMY_DIR / "rules.json"

COMMITS_OUT = PUB_DIR / "commits_slim.json"
PALETTE_OUT = PUB_DIR / "palette.json"
COVERAGE_OUT = PUB_DIR / "taxonomy_coverage.json"

SUBJECT_MAX = 80

# Fields carried into the published projection. An allowlist, so a new raw
# field can never leak by default.
KEEP_FIELDS = ("sha", "org", "repo", "author_date")

# Okabe-Ito, matching assets/tokens.css and topic_model.py. Colours are baked
# into the data here so the pages stop carrying hex literals — the same pattern
# topic_model.py already uses for topic colours.
DOMAIN_COLORS = {
    "brain-foundation-model": "#0072B2",
    "neural-field-modeling": "#56B4E9",
    "agentic-ai": "#009E73",
    "clinical-translation": "#D55E00",
    "human-neuro": "#E69F00",
    "animal-neuro": "#CC79A7",
    "education": "#F0E442",
    "infra": "#5A5A6E",
    "unclassified": "#9E9E9E",
}
WP_COLORS = {
    "WP1": "#003380", "WP2": "#009E73", "WP3": "#D55E00",
    "WP4": "#E69F00", "WP5": "#5A5A6E", "PROP": "#CC79A7", "unbound": "#9E9E9E",
}
CATEGORY_COLORS = {
    "proposal": "#003380", "paper": "#0072B2", "education": "#E69F00",
    "tool": "#009E73", "other": "#9E9E9E", "core": "#5A5A6E",
}
ORG_COLORS = {
    "snuconnectome": "#003380", "Transconnectome": "#0072B2", "neurox-org": "#E69F00",
}

# MASTER_PLAN_6YR.md:109-215 budget split. Kept here as a constant with its
# source noted rather than parsed, because it changes about once a programme.
WP_BUDGET_PCT = {"WP1": 40, "WP2": 15, "WP3": 25, "WP4": 10, "WP5": 10}
WP_LABELS = {
    "WP1": "NFM Core", "WP2": "Agentic Science", "WP3": "Clinical Translation",
    "WP4": "Education", "WP5": "Infra & Governance",
    "PROP": "제안서 (수주 활동)", "unbound": "미분류",
}

# Proposal work gets its own bucket on the WP axis rather than being folded into
# the programme it would fund. Two reasons it cannot sit inside a WP: REPO_MAP
# is itself inconsistent about it (k-bfm under WP1, nrf-neuro-ai and IITP under
# WP5), and more importantly, writing a proposal is not the same activity as
# doing the work it proposes — merging them makes the budget comparison claim
# effort that has not happened yet. It carries no planned percentage: the
# 40/15/25/10/10 split covers funded work, not the pursuit of funding.
PROPOSAL_WP = "PROP"


def first_match(rules: list[dict], key: str, text: str) -> tuple[str | None, str | None]:
    """Return (value, pattern) for the first rule whose pattern matches."""
    for rule in rules:
        if re.search(rule["pattern"], text, re.IGNORECASE):
            return rule[key], rule["pattern"]
    return None, None


def classify(full_name: str, curated: dict, rules: dict) -> dict:
    """Resolve one org/repo to its taxonomy row."""
    entry = curated.get(full_name)

    # Match on the repo name alone. Matching "org/repo" made every repo in
    # snuconnectome and Transconnectome hit any rule containing "connectome",
    # which swept unrelated work into human-neuro.
    haystack = full_name.split("/", 1)[1] if "/" in full_name else full_name

    if entry:
        wp = entry.get("wp") or "unbound"
        domain = entry.get("domain")
        source = entry.get("source", "repo_map")
        if not domain:
            # A curated entry already states its programme, so the WP default
            # wins. Only rules flagged override_wp may beat it — those encode
            # facts orthogonal to the programme axis (neural-field methods sit
            # inside WP1; animal work cuts across every WP).
            override, _ = first_match(
                [r for r in rules["domain_rules"] if r.get("override_wp")], "domain", haystack)
            domain = override or rules["wp_to_domain"].get(wp) or "unclassified"
        role = entry.get("wp_role", "S")
        modality = entry.get("modality")
        indication = entry.get("indication")
    else:
        wp = "unbound"
        domain, _ = first_match(rules["domain_rules"], "domain", haystack)
        domain = domain or "unclassified"
        source = "rule" if domain != "unclassified" else "none"
        role = None
        modality = indication = None

    species, _ = first_match(rules["species_rules"], "species", haystack)
    category, _ = first_match(rules["category_rules"], "category", haystack)

    # Proposal work overrides the programme axis but leaves `domain` alone, so a
    # brain-foundation-model proposal still reads as that science in the domain
    # views while staying out of WP1's effort total.
    activity = (entry or {}).get("activity")
    if activity == "proposal":
        wp = PROPOSAL_WP
        category = "proposal"

    return {
        "wp": wp,
        "activity": activity,
        "wp_role": role,
        "domain": domain,
        "species": species,
        "modality": modality,
        "indication": indication,
        "category": category or "core",
        "source": source,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Join raw commits with the taxonomy.")
    ap.add_argument("--report", action="store_true", help="print coverage, write nothing")
    args = ap.parse_args()

    raw_path = raw_commits_path()
    if not raw_path.exists():
        print(f"❌ {raw_path} not found — run scripts/fetch_commits.py first.", file=sys.stderr)
        return 1
    if not REPOS_IN.exists():
        print(f"❌ {REPOS_IN.relative_to(REPO)} not found — run scripts/seed_taxonomy.py.", file=sys.stderr)
        return 1

    commits = json.loads(raw_path.read_text(encoding="utf-8"))
    curated = json.loads(REPOS_IN.read_text(encoding="utf-8"))["repos"]
    rules = json.loads(RULES_IN.read_text(encoding="utf-8"))

    repos = sorted({f"{c['org']}/{c['repo']}" for c in commits})
    taxonomy = {r: classify(r, curated, rules) for r in repos}

    # ── Coverage ─────────────────────────────────────────────────────────
    commits_per_repo = Counter(f"{c['org']}/{c['repo']}" for c in commits)
    by_source = Counter(t["source"] for t in taxonomy.values())
    unclassified = sorted(
        (r for r, t in taxonomy.items() if t["domain"] == "unclassified"),
        key=lambda r: -commits_per_repo[r],
    )

    print(f"Taxonomy join — {len(commits)} commits across {len(repos)} repos")
    print()
    print("  provenance of each repo's label:")
    for src in ("repo_map", "rule", "none"):
        n = by_source.get(src, 0)
        label = {"repo_map": "curated (REPO_MAP seed)", "rule": "pattern rule",
                 "none": "unclassified"}[src]
        print(f"    {label:28s} {n:4d} repos  ({n / len(repos):4.0%})")
    print()
    print("  domain:")
    for dom, n in Counter(t["domain"] for t in taxonomy.values()).most_common():
        commits_n = sum(commits_per_repo[r] for r, t in taxonomy.items() if t["domain"] == dom)
        print(f"    {dom:26s} {n:4d} repos  {commits_n:5d} commits")
    print()
    print("  WP (budget axis):")
    wp_order = ["WP1", "WP2", "WP3", "WP4", "WP5", PROPOSAL_WP, "unbound"]
    counts = Counter(t["wp"] for t in taxonomy.values())
    for wp in [w for w in wp_order if w in counts] + [w for w in counts if w not in wp_order]:
        n = counts[wp]
        commits_n = sum(commits_per_repo[r] for r, t in taxonomy.items() if t["wp"] == wp)
        planned = WP_BUDGET_PCT.get(wp)
        plan_str = f"  plan {planned:2d}%" if planned else "  plan  — "
        actual = commits_n / len(commits)
        print(f"    {wp:8s} {WP_LABELS.get(wp, ''):20s} {n:4d} repos  "
              f"{commits_n:5d} commits ({actual:4.0%}){plan_str}")

    if unclassified:
        print()
        print(f"  ⚠️  {len(unclassified)} repos unclassified. Highest-activity first —")
        print("      add them to data/taxonomy/repos.json or extend rules.json:")
        for r in unclassified[:10]:
            print(f'        "{r}": {{"wp": "WP?", "domain": "?", "source": "manual"}},'
                  f'   # {commits_per_repo[r]} commits')
        if len(unclassified) > 10:
            print(f"        … and {len(unclassified) - 10} more")

    if args.report:
        print("\n(report only — nothing written)")
        return 0

    # ── Emit published projection ────────────────────────────────────────
    slim = []
    for c in commits:
        full = f"{c['org']}/{c['repo']}"
        t = taxonomy[full]
        row = {k: c[k] for k in KEEP_FIELDS if k in c}
        row["subject"] = (c.get("message") or "").split("\n")[0][:SUBJECT_MAX]
        row["repo_category"] = t["category"]     # legacy axis, kept for index.qmd
        row["domain"] = t["domain"]
        row["wp"] = t["wp"]
        slim.append(row)

    leaked = {k for row in slim for k in row} - set(KEEP_FIELDS) - {
        "subject", "repo_category", "domain", "wp"}
    if leaked:
        print(f"\n❌ unexpected fields in output: {sorted(leaked)}", file=sys.stderr)
        return 1

    PUB_DIR.mkdir(parents=True, exist_ok=True)
    COMMITS_OUT.write_text(json.dumps(slim, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    PALETTE_OUT.write_text(json.dumps({
        "domain": DOMAIN_COLORS,
        "wp": WP_COLORS,
        "category": CATEGORY_COLORS,
        "org": ORG_COLORS,
        "wp_labels": WP_LABELS,
        "wp_budget_pct": WP_BUDGET_PCT,
        "wp_order": ["WP1", "WP2", "WP3", "WP4", "WP5", "PROP", "unbound"],
        "_source": "MASTER_PLAN_6YR.md:109-215 for wp_budget_pct; assets/tokens.css for hues",
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    COVERAGE_OUT.write_text(json.dumps({
        "n_commits": len(commits),
        "n_repos": len(repos),
        "by_source": dict(by_source),
        "unclassified_repos": len(unclassified),
        "repos": {r: taxonomy[r] | {"commits": commits_per_repo[r]} for r in repos},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print()
    print(f"✅ {len(slim)} commits → {COMMITS_OUT.relative_to(REPO)}")
    print(f"   palette   → {PALETTE_OUT.relative_to(REPO)}")
    print(f"   coverage  → {COVERAGE_OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
