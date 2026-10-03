#!/usr/bin/env python3
"""Join raw commits with the taxonomy, then emit the published projection.

Reads:  $ACTIVITY_ATLAS_DATA_DIR/scopes/<scope>/raw/commits.json   (local only)
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
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time_axis import calendar_weeks
from snapshot_contract import replace_generation, fingerprint, event_key, content_digest

from aa_paths import (
    DERIVED_EMBEDDINGS, DERIVED_PULSE, DERIVED_TOPICS, RAW_INVENTORY,
    PROFILE_DIRS, PUB_DIR, REPO, PRIVATE_TAXONOMY, SCOPE, RAW_MANIFEST, raw_commits_path,
)

ROSTER = Path("/home/juke/git/lab-ai-usage/roster.json")

TAXONOMY_DIR = REPO / "data" / "taxonomy"
REPOS_IN = TAXONOMY_DIR / "repos.json"
PRIVATE_REPOS_IN = PRIVATE_TAXONOMY
PULSE_META = DERIVED_PULSE.with_suffix('.meta.json')
RULES_IN = TAXONOMY_DIR / "rules.json"

SUBJECT_MAX = 80

# Fields carried into the published projection. An allowlist, so a new raw
# field can never leak by default.
KEEP_FIELDS = ("sha", "event_id", "org", "repo", "author_date")

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

# Topic labels inherit every contributing source's publication restrictions.


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


# The scatter draws one SVG circle per point. Beyond a few thousand the page stops
# being readable before it stops being fast — points overplot into a solid mass —
# so thin uniformly per topic, which preserves each cluster's shape and relative
# size rather than favouring the largest.
MAX_SCATTER_POINTS = 2500


def downsample_embeddings(embeddings: list[dict]) -> tuple[list[dict], int]:
    if len(embeddings) <= MAX_SCATTER_POINTS:
        return embeddings, 0
    by_topic: dict[int, list[dict]] = {}
    for e in embeddings:
        by_topic.setdefault(e["topic_id"], []).append(e)
    keep_ratio = MAX_SCATTER_POINTS / len(embeddings)
    kept: list[dict] = []
    for tid, rows in by_topic.items():
        # Deterministic stride, not random sampling: the same input must give
        # the same picture on every rebuild.
        n = max(1, round(len(rows) * keep_ratio))
        stride = len(rows) / n
        kept.extend(rows[int(i * stride)] for i in range(n))
    return kept, len(embeddings) - len(kept)


# A person-repo-week records one person's GitHub participation in one repo
# during one ISO week. It measures observed activity breadth, not hours, cost,
# productivity, or a budget allocation. Touching more repositories increases it.
def iso_week(iso_dt: str) -> str:
    from datetime import datetime
    y, w, _ = datetime.fromisoformat(iso_dt.replace("Z", "+00:00")).isocalendar()
    return f"{y}-W{w:02d}"


def person_weeks(commits: list[dict]) -> set[tuple[str, str, str]]:
    """(author, org/repo, ISO week) triples."""
    return {
        ((c.get("author_canonical") or c.get("author_login") or ""),
         f"{c['org']}/{c['repo']}",
         iso_week(c["author_date"]))
        for c in commits if c.get("author_date")
    }


# A repo with one contributor is not automatically a problem — a personal
# research log or a solo first-author draft is meant to be solo. Succession risk
# only means something for work others must be able to pick up.
SOLO_RISK_DOMAINS = {"brain-foundation-model", "quantum-ml", "neural-field-modeling",
                     "clinical-translation", "agentic-ai", "human-neuro", "animal-neuro"}
LOG_REPO_RE = re.compile(r"log|journal|weekly|diary|notes?$|report", re.IGNORECASE)


def read_derived(path):
    if not path.exists():
        print(f"  ⚠️  {path.name} not found — skipping (run topic_model.py / weekly_pulse.py)",
              file=sys.stderr)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_lifecycle(commits, taxonomy, inventory, pw, scope="unknown"):
    """Per-repo state for the lifecycle / succession view."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    last_commit, by_repo = {}, {}
    for c in commits:
        k = f"{c['org']}/{c['repo']}"
        by_repo.setdefault(k, []).append(c)
        d = c.get("author_date", "")
        if d > last_commit.get(k, ""):
            last_commit[k] = d

    weeks_by_repo: dict[str, Counter] = {}
    for author, repo, _wk in pw:
        weeks_by_repo.setdefault(repo, Counter())[author] += 1

    rows = []
    seen = set()
    for inv in inventory:
        k = f"{inv['org']}/{inv['repo']}"
        seen.add(k)
        t = taxonomy.get(k) or classify_fallback(k)
        weeks = weeks_by_repo.get(k, Counter())
        # One-off drive-by commits should not read as shared ownership, so a
        # contributor must have touched the repo in at least two distinct weeks.
        committed = [a for a, n in weeks.items() if n >= 2]
        stamp = last_commit.get(k) or inv.get("pushed_at") or ""
        days = None
        if stamp:
            try:
                days = (now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).days
            except ValueError:
                days = None
        is_log = bool(LOG_REPO_RE.search(inv["repo"]))
        rows.append({
            "repo": k,
            "org": inv["org"],
            "domain": t["domain"],
            "wp": t["wp"],
            "archived": inv["archived"],
            "idle_days": days,
            "contributors": len(committed),
            "person_weeks": sum(weeks.values()),
            "commits": len(by_repo.get(k, [])),
            # Succession risk is only asserted where solo ownership is a real
            # hazard: research code and tooling, not logs or personal drafts.
            "succession_risk": (
                scope == 'all' and len(committed) == 1 and not is_log and not inv["archived"]
                and t["domain"] in SOLO_RISK_DOMAINS
                and days is not None and days < 180
            ),
        })
    return sorted(rows, key=lambda r: -(r["person_weeks"] or 0))


def classify_fallback(_key):
    return {"domain": "unclassified", "wp": "unbound"}


def build_people(commits, taxonomy, pw, roster, observed_through=None):
    """Per-person cards. Lab profile only — never emitted publicly."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    pi = {"jcha9928"}
    by_author: dict[str, list[dict]] = {}
    for c in commits:
        by_author.setdefault(c.get("author_canonical") or c.get("author_login") or "", []).append(c)

    # Shared-repository commit proxy, not evidence of contact or review.
    pi_last: dict[str, str] = {}
    for c in by_author.get("jcha9928", []):
        k = f"{c['org']}/{c['repo']}"
        if c["author_date"] > pi_last.get(k, ""):
            pi_last[k] = c["author_date"]

    weeks_by_author: dict[str, set] = {}
    for author, repo, wk in pw:
        weeks_by_author.setdefault(author, set()).add((repo, wk))

    rows = []
    for author, rows_ in by_author.items():
        if author in pi or not author:
            continue
        repos = sorted({f"{c['org']}/{c['repo']}" for c in rows_})
        first_activity = {r: min(c['author_date'] for c in rows_ if f"{c['org']}/{c['repo']}" == r) for r in repos}
        contact = max((pi_last.get(r, "") for r in repos
                       if pi_last.get(r, '') >= first_activity[r]), default="")
        since = None
        if contact:
            since = (now - datetime.fromisoformat(contact.replace("Z", "+00:00"))).days

        # Sparkline is weekly *repo count*, not commit count: a commit-count
        # sparkline reads as a productivity chart no matter how it is labelled.
        weeks = weeks_by_author.get(author, set())
        recent = Counter(wk for _r, wk in weeks)
        from datetime import timedelta
        cutoff = observed_through or max(c['author_date'] for c in commits)
        start = (datetime.fromisoformat(cutoff.replace('Z','+00:00')) - timedelta(weeks=7)).isoformat()
        last8 = [recent.get(w, 0) for w in calendar_weeks(start, cutoff)]

        doms = Counter(taxonomy.get(f"{c['org']}/{c['repo']}", {}).get("domain", "")
                       for c in rows_)
        rows.append({
            "login": author,
            "display": roster.get(author) or author,
            "in_roster": author in roster,
            "repos": repos[:12],
            "n_repos": len(repos),
            "active_weeks": len({wk for _r, wk in weeks}),
            "recent_repo_counts": last8,
            "domains": [d for d, _ in doms.most_common(3) if d],
            "days_since_pi_repo_commit": since,
            "last_activity": max(c["author_date"] for c in rows_)[:10],
        })
    # Sorted by PI attention debt, longest first. Never by volume.
    return sorted(rows, key=lambda r: (r['days_since_pi_repo_commit'] is None,
                  r['days_since_pi_repo_commit'] or 0), reverse=True)


def build_drift(taxonomy, commits_per_repo, rules):
    """Unclassified repos, most active first, with the rule that would fire."""
    rows = []
    for repo, t in taxonomy.items():
        if t["wp"] != "unbound" and t["domain"] != "unclassified":
            continue
        name = repo.split("/", 1)[1]
        suggestion, pattern = first_match(rules["domain_rules"], "domain", name)
        rows.append({
            "repo": repo,
            "commits": commits_per_repo.get(repo, 0),
            "domain": t["domain"],
            "wp": t["wp"],
            "suggested_domain": suggestion,
            "matched_pattern": pattern,
        })
    return sorted(rows, key=lambda r: -r["commits"])


def publication_mode(commit):
    """Identity may be published only for a positively known public repository.

    Author consent does not grant permission to publish private repo content.
    Unknown visibility uses the same aggregate-only policy as private data.
    """
    return "full" if commit.get("repo_visibility") == "PUBLIC" else "aggregate_only"


def mask_topic_labels(topics_doc, embeddings, commits, consent):
    """A label inherits restrictions from every source event, not its majority."""
    sha_author = {c.get('event_id', c['sha']): (c.get("author_canonical") or c.get("author_login") or "")
                  for c in commits}
    sources = {c.get('event_id', c['sha']): c for c in commits}
    per_topic: dict[int, Counter] = {}
    restricted = set()
    for e in embeddings:
        key = e.get('event_id', e['sha'])
        per_topic.setdefault(e["topic_id"], Counter())[sha_author.get(key, "")] += 1
        source = sources.get(key)
        if source is None or publication_mode(source) != "full":
            restricted.add(e["topic_id"])

    masked = 0
    for t in topics_doc.get("topics", []):
        tid = t["topic_id"]
        authors = per_topic.get(tid, Counter())
        total = sum(authors.values())
        if not total or tid in restricted or any(a not in consent for a in authors):
            t["label"] = f"topic-{tid}" if tid != -1 else "outliers"
            t["top_words"] = []
            masked += 1
    return topics_doc, masked


def public_pulse(commits, embeddings, topics_doc, observed_through=None, observed_from=None):
    """Rebuild public prose from counts and already-approved labels.

    Never copy private derived narrative and attempt string redaction: labels
    and repo names may appear in any free-text bullet.
    """
    assignments = {e.get('event_id', e['sha']): e['topic_id'] for e in embeddings}
    labels = {t['topic_id']: t['label'] for t in topics_doc['topics']}
    weeks = {}
    for c in commits:
        weeks.setdefault(iso_week(c['author_date']), []).append(c)
    output = []
    previous = 0
    dates = [c['author_date'] for c in commits]
    for week in calendar_weeks(observed_from or min(dates), observed_through or max(dates)) if dates else []:
        rows = weeks.get(week, [])
        topics = Counter(assignments.get(c.get('event_id',c['sha']), -1) for c in rows)
        top = [tid for tid, _ in topics.most_common() if tid != -1][:3]
        bullets = [f"{len(rows)} commits ({len(rows)-previous:+d} vs 전주)"]
        if top:
            bullets.append('주요 토픽: ' + ', '.join(labels.get(t, f'topic-{t}') for t in top))
        output.append({'week_iso': week, 'commit_count': len(rows), 'top_topics': top, 'delta_bullets': bullets})
        previous = len(rows)
    return output[::-1]


def network_projection(commits, taxonomy, embeddings, public):
    """Full topic counts, independent of the Latent coordinate sample."""
    assignments = {e.get('event_id', e['sha']): e['topic_id'] for e in embeddings}
    groups = {}
    for c in commits:
        full = f"{c['org']}/{c['repo']}"
        t = taxonomy[full]
        name = c['repo'] if not public or publication_mode(c) == 'full' else None
        key = (c['org'], name, t['domain'])
        g = groups.setdefault(key, {'org': c['org'], 'repo': name, 'domain': t['domain'], 'count': 0, 'topic_counts': {}})
        g['count'] += 1
        tid = assignments.get(c.get('event_id',c['sha']), -1)
        if tid != -1:
            g['topic_counts'][str(tid)] = g['topic_counts'].get(str(tid), 0) + 1
    return list(groups.values())


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
    if PRIVATE_REPOS_IN.exists():
        curated.update(json.loads(PRIVATE_REPOS_IN.read_text(encoding="utf-8"))["repos"])
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
        print(f"    {label:28s} {n:4d} repos  ({n / max(1,len(repos)):4.0%})")
    print()
    print("  domain:")
    for dom, n in Counter(t["domain"] for t in taxonomy.values()).most_common():
        commits_n = sum(commits_per_repo[r] for r, t in taxonomy.items() if t["domain"] == dom)
        print(f"    {dom:26s} {n:4d} repos  {commits_n:5d} commits")
    print()
    print("  WP (activity classification):")
    wp_order = ["WP1", "WP2", "WP3", "WP4", "WP5", PROPOSAL_WP, QUANTUM_WP, "unbound"]
    counts = Counter(t["wp"] for t in taxonomy.values())
    for wp in [w for w in wp_order if w in counts] + [w for w in counts if w not in wp_order]:
        n = counts[wp]
        commits_n = sum(commits_per_repo[r] for r, t in taxonomy.items() if t["wp"] == wp)
        planned = WP_BUDGET_PCT.get(wp)
        plan_str = f"  plan {planned:2d}%" if planned else "  plan  — "
        actual = commits_n / max(1,len(commits))
        print(f"    {wp:8s} {WP_LABELS.get(wp, ''):20s} {n:4d} repos  "
              f"{commits_n:5d} commits ({actual:4.0%}){plan_str}")

    if unclassified:
        print()
        print(f"  ⚠️  {len(unclassified)} repos unclassified. Highest-activity first —")
        print("      add them to data/taxonomy/repos.json or extend rules.json:")
        report_repos = [r for r in unclassified if args.profile == 'lab' or any(
            f"{c['org']}/{c['repo']}" == r and publication_mode(c) == 'full' for c in commits)]
        for r in report_repos[:10]:
            print(f'        "{r}": {{"wp": "WP?", "domain": "?", "source": "manual"}},'
                  f'   # {commits_per_repo[r]} commits')
        if len(unclassified) > len(report_repos):
            print(f"        {len(unclassified) - len(report_repos)} aggregate-only repo names omitted")

    if args.report:
        print("\n(report only — nothing written)")
        return 0

    consent = load_consent()
    out_dir = PROFILE_DIRS[args.profile]
    public = args.profile == "pub"

    # ── Topic / pulse projections ────────────────────────────────────────
    topics_doc = read_derived(DERIVED_TOPICS)
    embeddings = read_derived(DERIVED_EMBEDDINGS)
    pulse = read_derived(DERIVED_PULSE)
    pulse_meta = read_derived(PULSE_META)
    if topics_doc is None or embeddings is None or pulse is None or pulse_meta is None or not RAW_INVENTORY.exists():
        print('❌ Missing required analysis or inventory; previous projection preserved.', file=sys.stderr)
        return 1
    expected_fingerprint = fingerprint(commits, SCOPE)
    collection = read_derived(RAW_MANIFEST)
    if not collection or collection.get('complete') is not True or collection.get('scope') != SCOPE or collection.get('source_fingerprint') != expected_fingerprint:
        print('❌ Missing, incomplete, or mismatched collection manifest; previous projection preserved.', file=sys.stderr)
        return 1
    if topics_doc.get('metadata', {}).get('source_fingerprint') != expected_fingerprint or pulse_meta.get('source_fingerprint') != expected_fingerprint:
        print('❌ Analysis belongs to another input snapshot; previous projection preserved.', file=sys.stderr)
        return 1
    if topics_doc['metadata'].get('embedding_digest') != content_digest(embeddings) or pulse_meta.get('topics_digest') != content_digest(topics_doc) or pulse_meta.get('pulse_digest') != content_digest(pulse):
        print('❌ Mixed or changed analysis artifacts; previous projection preserved.', file=sys.stderr)
        return 1
    # Legacy synthetic fixtures use SHA; current collectors/model output use
    # repository event IDs. Reject unknown and duplicate points before writing.
    event_mode = any('event_id' in e for e in embeddings)
    if event_mode:
        for c in commits:c['event_id'] = event_key(c)
    source_keys = {c.get('event_id', c['sha']) for c in commits}
    point_keys = [e.get('event_id', e['sha']) for e in embeddings]
    if not set(point_keys) <= source_keys or len(point_keys) != len(set(point_keys)):
        print('❌ Unknown or duplicate analysis event references.', file=sys.stderr)
        return 1
    full_embeddings = embeddings or []

    dropped_points = 0
    scatter_shas: set[str] = set()
    if embeddings:
        if public:
            allowed_shas = {c.get('event_id', c['sha']) for c in commits if publication_mode(c) == 'full'}
            embeddings = [e for e in embeddings if e.get('event_id', e['sha']) in allowed_shas]
        embeddings, dropped_points = downsample_embeddings(embeddings)
        scatter_shas = {e.get('event_id', e["sha"]) for e in embeddings}

    # Refuse to project a topic model built from a different commit set. This
    # is the failure that nearly shipped: after switching the raw store back to
    # PI-only, a stale lab-wide topics/embeddings pair was still on disk, and
    # join.py happily emitted it as the public projection.
    if topics_doc:
        meta = topics_doc.get("metadata", {})
        src_n = meta.get("source_n_commits")
        if src_n is not None and src_n != len(commits):
            print(f"\n❌ topics.json was built from {src_n} commits but the raw store "
                  f"holds {len(commits)}.", file=sys.stderr)
            print("   Re-run topic_model.py and weekly_pulse.py before joining.", file=sys.stderr)
            return 1

    masked_topics = 0
    if topics_doc and public:
        topics_doc, masked_topics = mask_topic_labels(topics_doc, full_embeddings, commits, consent)
        pulse = public_pulse(commits, full_embeddings, topics_doc, collection['observed_through'], collection['observed_from'])
        # Explicit public contracts prevent new private producer fields from
        # silently becoming public, including metadata and coordinate records.
        topics_doc = {'topics': [{k:t[k] for k in ('topic_id','label','top_words','size','color','slot') if k in t}
                                 for t in topics_doc['topics']],
            'metadata': {k:v for k,v in topics_doc['metadata'].items() if k in {
                'source_n_commits','clustering_method','n_commits','model','generated_at'}}}
        embeddings = [{k:e[k] for k in ('event_id','sha','x','y','topic_id') if k in e} for e in embeddings]
        # Input hashes and author cardinality are private provenance.
        topics_doc['metadata'].pop('source_fingerprint', None)
        topics_doc['metadata'].pop('source_n_authors', None)
        topics_doc['metadata'].pop('embedding_digest', None)

    # ── Commit rows ──────────────────────────────────────────────────────
    # sha and subject exist only so the scatter can look up a hovered point.
    # Carrying them on every row cost 655 KB of payload at lab scale for rows
    # nothing could ever hover, so they ride only on rows the scatter draws.
    slim = []
    aggregate_rows = {}
    suppressed_subjects = 0
    for c in commits:
        full = f"{c['org']}/{c['repo']}"
        t = taxonomy[full]
        on_scatter = c.get('event_id', c["sha"]) in scatter_shas
        row = {k: c[k] for k in KEEP_FIELDS if k in c and (k not in {"sha", 'event_id'} or on_scatter)}
        author = c.get("author_canonical") or c.get("author_login") or ""

        if public and publication_mode(c) != 'full':
            # No private repo pseudonym, SHA, exact time, subject, or coordinate.
            key = (c['org'], c['author_date'][:10], t['domain'], t['wp'], t['category'])
            group = aggregate_rows.setdefault(key, {'org': c['org'],
                'author_date': c['author_date'][:10] + 'T00:00:00Z',
                'domain': t['domain'], 'wp': t['wp'], 'repo_category': t['category'],
                'count': 0, 'aggregate_only': True})
            group['count'] += 1
            continue

        if on_scatter:
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
    slim.extend(aggregate_rows.values())

    allowed = set(KEEP_FIELDS) | {"subject", "repo_category", "domain", "wp", "count", "aggregate_only"}
    if not public:
        allowed.add("author")
    leaked = {k for row in slim for k in row} - allowed
    if leaked:
        print(f"\n❌ unexpected fields in output: {sorted(leaked)}", file=sys.stderr)
        return 1
    if public and any("author" in row for row in slim):
        print("\n❌ author identity present in the public projection", file=sys.stderr)
        return 1

    destination = out_dir
    scratch = REPO / 'data' / 'tmp'
    scratch.mkdir(parents=True, exist_ok=True)
    out_dir = Path(tempfile.mkdtemp(prefix=f'{args.profile}-', dir=scratch))
    # No indent on the two large payloads: pretty-printing commits_slim cost
    # 2.4 MB of leading spaces at lab scale, all of it downloaded by the browser.
    (out_dir / "commits_slim.json").write_text(
        json.dumps(slim, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (out_dir / 'network.json').write_text(json.dumps(network_projection(
        commits, taxonomy, full_embeddings, public), ensure_ascii=False) + '\n', encoding='utf-8')

    for name, payload, compact in (("topics.json", topics_doc, False),
                                   ("embeddings.json", embeddings, True),
                                   ("weekly_pulse.json", pulse, False)):
        if payload is not None:
            kwargs = ({"separators": (",", ":")} if compact else {"indent": 2})
            (out_dir / name).write_text(
                json.dumps(payload, ensure_ascii=False, **kwargs) + "\n", encoding="utf-8")

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

    # ── Views: lifecycle, people, drift ──────────────────────────────────
    pw = person_weeks(commits)
    inventory = []
    if RAW_INVENTORY.exists():
        inventory = json.loads(RAW_INVENTORY.read_text(encoding="utf-8"))
    else:
        print("  ⚠️  raw/repos.json not found — dormant repos will be missing "
              "from the lifecycle view. Re-run fetch_commits.py.", file=sys.stderr)
        inventory = [{"org": r.split("/")[0], "repo": r.split("/", 1)[1],
                      "pushed_at": None, "archived": False,
                      "visibility": "UNKNOWN", "active": True} for r in repos]

    safe_repos = {f"{c['org']}/{c['repo']}" for c in commits if not public or publication_mode(c) == 'full'}
    safe_inventory = [r for r in inventory if not public or r.get('visibility') == 'PUBLIC']
    (out_dir / "lifecycle.json").write_text(json.dumps(
        build_lifecycle(commits, taxonomy, safe_inventory, pw, scope=collection['scope']),
        ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    (out_dir / "drift.json").write_text(json.dumps(
        build_drift({r: t for r, t in taxonomy.items() if r in safe_repos}, commits_per_repo, rules),
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # People cards carry names, so they exist in the lab profile only. A stale
    # copy must not survive a switch from lab to pub.
    people_path = out_dir / "people.json"
    if public:
        people_path.unlink(missing_ok=True)
    else:
        roster = {}
        if ROSTER.exists():
            roster = {k: v for k, v in json.loads(ROSTER.read_text(encoding="utf-8")).items()
                      if not k.startswith("__")}
        people_path.write_text(json.dumps(
            build_people(commits, taxonomy, pw, roster, observed_through=collection['observed_through']),
            indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    (out_dir / "taxonomy_coverage.json").write_text(json.dumps({
        "n_commits": len(commits),
        "n_repos": len(repos),
        "by_source": dict(by_source),
        "unclassified_repos": len(unclassified),
        "aggregate_only_repos": len(repos) - len(safe_repos),
        "repos": {r: taxonomy[r] | {"commits": commits_per_repo[r]} for r in repos if r in safe_repos},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest = {k: collection[k] for k in ('scope', 'complete', 'observed_from',
        'observed_through', 'collected_at', 'repositories_succeeded', 'repositories_failed')}
    manifest.update({'schema_version': '0.3.0', 'n_commits': len(commits),
        'published_at': datetime.now(timezone.utc).isoformat(),
        'payload_digest': content_digest({p.name: json.loads(p.read_text()) for p in sorted(out_dir.glob('*.json'))})})
    (out_dir/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    replace_generation(out_dir, destination)
    out_dir = destination

    print()
    print(f"✅ profile={args.profile}: {len(commits)} commits, {len(slim)} output rows → {out_dir.relative_to(REPO)}/")
    if dropped_points:
        print(f"   산점도 다운샘플: {dropped_points}점 제외 → {len(embeddings)}점")
    if public:
        print(f"   비동의 저자 subject 비공개: {suppressed_subjects}건")
        print(f"   제한된 출처 토픽 라벨 마스킹: {masked_topics}개")
    else:
        print("   ⚠️ lab 프로파일 — 저자 실명과 커밋 제목이 들어 있습니다. 커밋 금지.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
