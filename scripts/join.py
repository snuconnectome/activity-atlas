#!/usr/bin/env python3
"""Join raw commits with the taxonomy, then emit the published projection.

Reads:  $ACTIVITY_ATLAS_DATA_DIR/raw/commits.json   (local only)
        data/taxonomy/repos.json                     (curated, committed)
        data/taxonomy/rules.json                     (fallback patterns)
Writes: data/<profile>/*.json   (profile = pub | lab)

`pub` is what gets committed and deployed. `lab` carries author names and commit
subjects and is gitignored — it exists so the same pages can be rendered locally
against the full picture.

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
from pathlib import Path

from aa_paths import (
    DERIVED_EMBEDDINGS, DERIVED_PULSE, DERIVED_TOPICS,
    PROFILE_DIRS, PUB_DIR, REPO, raw_commits_path,
)

TAXONOMY_DIR = REPO / "data" / "taxonomy"
REPOS_IN = TAXONOMY_DIR / "repos.json"
RULES_IN = TAXONOMY_DIR / "rules.json"

SUBJECT_MAX = 80

# Fields carried into the published projection. An allowlist, so a new raw
# field can never leak by default.
KEEP_FIELDS = ("sha", "org", "repo", "author_date")

# Okabe-Ito, matching assets/tokens.css and topic_model.py. Colours are baked
# into the data here so the pages stop carrying hex literals — the same pattern
# topic_model.py already uses for topic colours.
DOMAIN_COLORS = {
    "brain-foundation-model": "#0072B2",
    "quantum-ml": "#7B4EA8",
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
    "WP4": "#E69F00", "WP5": "#5A5A6E",
    "PROP": "#CC79A7", "QML": "#7B4EA8", "unbound": "#9E9E9E",
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
    "PROP": "제안서 (수주 활동)", "QML": "양자 ML (WP 밖)", "unbound": "미분류",
}

# Proposal work gets its own bucket on the WP axis rather than being folded into
# the programme it would fund. Two reasons it cannot sit inside a WP: REPO_MAP
# is itself inconsistent about it (k-bfm under WP1, nrf-neuro-ai and IITP under
# WP5), and more importantly, writing a proposal is not the same activity as
# doing the work it proposes — merging them makes the budget comparison claim
# effort that has not happened yet. It carries no planned percentage: the
# 40/15/25/10/10 split covers funded work, not the pursuit of funding.
PROPOSAL_WP = "PROP"

# Quantum ML has grown into a real line — a dozen repos — with no budget line in
# MASTER_PLAN's five WPs. Filing it under one of them would hide that; leaving it
# in 미분류 would read as a classification gap rather than a portfolio fact. So it
# gets its own bucket, with no planned percentage, and a matching domain value so
# it is visible on the scientific axis too.
QUANTUM_WP = "QML"
QUANTUM_DOMAIN = "quantum-ml"


# Consent roster. lab-ai-usage/participants.json is the lab's existing gate;
# absence from it means no consent, which is the safe default rather than an
# error — a new lab member must never be published by virtue of not being listed.
PARTICIPANTS = Path("/home/juke/git/lab-ai-usage/participants.json")

# A cluster label is n-grams lifted from commit messages. If one non-consenting
# person wrote most of a cluster, publishing its label republishes their words
# under a thin disguise, so the label is replaced with a neutral id.
TOPIC_MIN_SIZE = 8
TOPIC_MAX_SINGLE_SHARE = 0.60


def load_consent() -> set[str]:
    """GitHub logins that have consented to having their text published."""
    if not PARTICIPANTS.exists():
        print(f"  ⚠️  {PARTICIPANTS} not found — treating every author as non-consenting",
              file=sys.stderr)
        return set()
    doc = json.loads(PARTICIPANTS.read_text(encoding="utf-8"))
    return {k for k, v in doc.items()
            if not k.startswith("_") and isinstance(v, dict) and v.get("consent_version")}


def may_publish_text(author: str, consent: set[str]) -> bool:
    return author in consent


def read_derived(path):
    if not path.exists():
        print(f"  ⚠️  {path.name} not found — skipping (run topic_model.py / weekly_pulse.py)",
              file=sys.stderr)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def mask_topic_labels(topics_doc, embeddings, commits, consent):
    """Replace labels that a single non-consenting author dominates."""
    sha_author = {c["sha"]: (c.get("author_canonical") or c.get("author_login") or "")
                  for c in commits}
    per_topic: dict[int, Counter] = {}
    for e in embeddings:
        per_topic.setdefault(e["topic_id"], Counter())[sha_author.get(e["sha"], "")] += 1

    masked = 0
    for t in topics_doc.get("topics", []):
        tid = t["topic_id"]
        authors = per_topic.get(tid, Counter())
        total = sum(authors.values())
        if not total:
            continue
        risky = [(a, n) for a, n in authors.items()
                 if a not in consent and n / total > TOPIC_MAX_SINGLE_SHARE]
        if risky or (total < TOPIC_MIN_SIZE and any(a not in consent for a in authors)):
            t["label"] = f"topic-{tid}" if tid != -1 else "outliers"
            t["top_words"] = []
            masked += 1
    return topics_doc, masked


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
        if not domain and wp != "unbound":
            # A curated entry already states its programme, so the WP default
            # wins. Only rules flagged override_wp may beat it — those encode
            # facts orthogonal to the programme axis (neural-field methods sit
            # inside WP1; animal work cuts across every WP).
            override, _ = first_match(
                [r for r in rules["domain_rules"] if r.get("override_wp")], "domain", haystack)
            domain = override or rules["wp_to_domain"].get(wp) or "unclassified"
        elif not domain:
            # Curated but with no WP — proposal entries are the main case. There
            # is no programme default to inherit, so resolve the science the same
            # way an uncurated repo would. Without this, marking a repo as a
            # proposal silently erased its domain: k-bfm-neurox went from
            # brain-foundation-model to unclassified.
            domain, _ = first_match(rules["domain_rules"], "domain", haystack)
            domain = domain or "unclassified"
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

    # Quantum work with no curated WP lands in its own bucket. A curated WP is
    # respected — ai-coscientist-qml is WP2 agentic tooling that happens to be a
    # quantum variant, and REPO_MAP says so.
    if domain == QUANTUM_DOMAIN and wp == "unbound":
        wp = QUANTUM_WP

    # Proposal work overrides the programme axis but leaves `domain` alone, so a
    # brain-foundation-model proposal still reads as that science in the domain
    # views while staying out of WP1's effort total. It also outranks the quantum
    # bucket: lukor-2-qml is a bid, not quantum work already under way.
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
    ap.add_argument("--profile", choices=["pub", "lab"], default="pub",
                    help="pub = publishable projection (default); "
                         "lab = lab-internal, carries author names and subjects")
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
    wp_order = ["WP1", "WP2", "WP3", "WP4", "WP5", PROPOSAL_WP, QUANTUM_WP, "unbound"]
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

    consent = load_consent()
    out_dir = PROFILE_DIRS[args.profile]
    public = args.profile == "pub"

    # ── Commit rows ──────────────────────────────────────────────────────
    slim = []
    suppressed_subjects = 0
    for c in commits:
        full = f"{c['org']}/{c['repo']}"
        t = taxonomy[full]
        row = {k: c[k] for k in KEEP_FIELDS if k in c}
        author = c.get("author_canonical") or c.get("author_login") or ""

        if public and not may_publish_text(author, consent):
            # The person's activity still counts; their words do not.
            row["subject"] = ""
            suppressed_subjects += 1
        else:
            row["subject"] = (c.get("message") or "").split("\n")[0][:SUBJECT_MAX]

        if not public:
            row["author"] = author

        row["repo_category"] = t["category"]     # legacy axis, kept for index.qmd
        row["domain"] = t["domain"]
        row["wp"] = t["wp"]
        slim.append(row)

    allowed = set(KEEP_FIELDS) | {"subject", "repo_category", "domain", "wp"}
    if not public:
        allowed.add("author")
    leaked = {k for row in slim for k in row} - allowed
    if leaked:
        print(f"\n❌ unexpected fields in output: {sorted(leaked)}", file=sys.stderr)
        return 1
    if public and any("author" in row for row in slim):
        print("\n❌ author identity present in the public projection", file=sys.stderr)
        return 1

    # ── Topic / pulse projections ────────────────────────────────────────
    topics_doc = read_derived(DERIVED_TOPICS)
    embeddings = read_derived(DERIVED_EMBEDDINGS)
    pulse = read_derived(DERIVED_PULSE)

    masked_topics = 0
    if topics_doc and public:
        topics_doc, masked_topics = mask_topic_labels(topics_doc, embeddings or [], commits, consent)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "commits_slim.json").write_text(
        json.dumps(slim, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for name, payload in (("topics.json", topics_doc),
                          ("embeddings.json", embeddings),
                          ("weekly_pulse.json", pulse)):
        if payload is not None:
            (out_dir / name).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    (out_dir / "palette.json").write_text(json.dumps({
        "domain": DOMAIN_COLORS,
        "wp": WP_COLORS,
        "category": CATEGORY_COLORS,
        "org": ORG_COLORS,
        "wp_labels": WP_LABELS,
        "wp_budget_pct": WP_BUDGET_PCT,
        "wp_order": ["WP1", "WP2", "WP3", "WP4", "WP5", "PROP", "QML", "unbound"],
        "_source": "MASTER_PLAN_6YR.md:109-215 for wp_budget_pct; assets/tokens.css for hues",
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    (out_dir / "taxonomy_coverage.json").write_text(json.dumps({
        "n_commits": len(commits),
        "n_repos": len(repos),
        "by_source": dict(by_source),
        "unclassified_repos": len(unclassified),
        "repos": {r: taxonomy[r] | {"commits": commits_per_repo[r]} for r in repos},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print()
    print(f"✅ profile={args.profile}: {len(slim)} commits → {out_dir.relative_to(REPO)}/")
    if public:
        print(f"   비동의 저자 subject 비공개: {suppressed_subjects}건")
        print(f"   비동의 저자 우세 토픽 라벨 마스킹: {masked_topics}개")
    else:
        print("   ⚠️ lab 프로파일 — 저자 실명과 커밋 제목이 들어 있습니다. 커밋 금지.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
