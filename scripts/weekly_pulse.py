"""Weekly Pulse — rule-based delta narrative for each ISO week.

Reads:  data/raw/commits.json + data/pub/topics.json + data/pub/embeddings.json
Writes: data/pub/weekly_pulse.json

Runs LOCALLY, not in CI: its input includes local-only raw commits.

For each ISO week with >= 1 commit, generates:
- commit_count
- top_topics (top-3 by frequency)
- delta_bullets: rule-based lines describing changes vs the previous week
  (new repos, new topics, commit count delta, dominant org shift)
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime


# A "notable" week is judged against recent weeks, not a fixed count. The old
# constant 4 was set when the dataset held 82 commits (~2.7/week); at the real
# volume (median 46/week) it fired in 38 of 40 weeks, so the flag carried no
# information. Rolling median + 1.5·MAD keeps it rare and self-calibrating as
# activity grows. Still rule-based — no model decides what is notable.
BURST_WINDOW_WEEKS = 12
BURST_MAD_MULTIPLIER = 1.5
BURST_MIN_HISTORY = 4      # below this, don't claim to know the baseline
BURST_FLOOR = 4            # tiny-dataset guard, matches the original constant


from aa_paths import PUB_DIR, REPO, raw_commits_path

COMMITS_IN = raw_commits_path()
TOPICS_IN = PUB_DIR / "topics.json"
EMBEDDINGS_IN = PUB_DIR / "embeddings.json"
OUT = PUB_DIR / "weekly_pulse.json"


def median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    mid = n // 2
    return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2


def burst_threshold(history: list[int]) -> float | None:
    """Rolling median + 1.5·MAD over the trailing weeks, or None if too short."""
    window = history[-BURST_WINDOW_WEEKS:]
    if len(window) < BURST_MIN_HISTORY:
        return None
    med = median(window)
    mad = median([abs(x - med) for x in window])
    return max(med + BURST_MAD_MULTIPLIER * mad, med + 1, BURST_FLOOR)


def iso_week(iso_dt: str) -> str:
    """Convert ISO datetime → 'YYYY-Wnn'."""
    dt = datetime.fromisoformat(iso_dt.replace("Z", "+00:00"))
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def main() -> int:
    if not COMMITS_IN.exists():
        print(f"ERROR: {COMMITS_IN} not found.", file=sys.stderr)
        return 1
    if not TOPICS_IN.exists():
        print(f"ERROR: {TOPICS_IN} not found. Run topic_model.py first.", file=sys.stderr)
        return 1

    commits = json.loads(COMMITS_IN.read_text(encoding="utf-8"))
    topics_doc = json.loads(TOPICS_IN.read_text(encoding="utf-8"))
    embeddings = json.loads(EMBEDDINGS_IN.read_text(encoding="utf-8"))

    # Maps
    topic_label = {t["topic_id"]: t["label"] for t in topics_doc["topics"]}
    sha_to_topic = {e["sha"]: e["topic_id"] for e in embeddings}

    # Group commits by ISO week
    by_week: dict[str, list[dict]] = defaultdict(list)
    for c in commits:
        if not c.get("author_date"):
            continue
        by_week[iso_week(c["author_date"])].append(c)

    weeks = sorted(by_week.keys())
    pulse: list[dict] = []
    burst_weeks = 0

    for i, week in enumerate(weeks):
        cs = by_week[week]
        cs_prev = by_week[weeks[i - 1]] if i > 0 else []

        # Aggregates
        commit_count = len(cs)
        repo_counter = Counter(f"{c['org']}/{c['repo']}" for c in cs)
        topic_counter = Counter(
            sha_to_topic.get(c["sha"], -1) for c in cs
        )
        org_counter = Counter(c["org"] for c in cs)

        repos_prev = {f"{c['org']}/{c['repo']}" for c in cs_prev}
        topics_prev = {sha_to_topic.get(c["sha"], -1) for c in cs_prev}

        # Top-3 topics (exclude -1 outlier unless dominant)
        ranked_topics = topic_counter.most_common()
        top_topics = [tid for tid, _ in ranked_topics if tid != -1][:3]
        if not top_topics and -1 in topic_counter:
            top_topics = [-1]

        # Rule-based delta bullets
        bullets: list[str] = []

        # 1. Headline count
        diff = commit_count - len(cs_prev)
        diff_str = f"+{diff}" if diff > 0 else (f"{diff}" if diff < 0 else "±0")
        bullets.append(f"{commit_count} commits ({diff_str} vs 전주)")

        # 2. New repos this week
        new_repos = [r for r in repo_counter if r not in repos_prev]
        if new_repos:
            shown = ", ".join(f"`{r}`" for r in new_repos[:3])
            more = f" + {len(new_repos) - 3} more" if len(new_repos) > 3 else ""
            bullets.append(f"신규 활동 repo: {shown}{more}")

        # 3. New topics
        new_topics = [t for t in topic_counter if t not in topics_prev and t != -1]
        if new_topics:
            shown = ", ".join(topic_label.get(t, f"topic-{t}") for t in new_topics[:3])
            bullets.append(f"신규 토픽: {shown}")

        # 4. Dominant org
        if org_counter:
            top_org, top_org_n = org_counter.most_common(1)[0]
            if top_org_n >= commit_count * 0.6 and commit_count >= 2:
                bullets.append(f"무게중심: `{top_org}` ({top_org_n}/{commit_count})")

        # 5. Burst flag, relative to the trailing baseline
        threshold = burst_threshold([by_week[w].__len__() for w in weeks[:i]])
        if threshold is not None and commit_count >= threshold:
            bullets.append(f"🔥 notable burst (최근 {BURST_WINDOW_WEEKS}주 기준 ≥ {threshold:.0f})")
            burst_weeks += 1

        # 6. Top repo this week (if there's a clear leader)
        if repo_counter:
            top_repo, top_repo_n = repo_counter.most_common(1)[0]
            if top_repo_n >= 2 and top_repo_n >= commit_count * 0.5:
                bullets.append(f"주요 repo: `{top_repo}` ({top_repo_n}건)")

        pulse.append({
            "week_iso": week,
            "commit_count": commit_count,
            "top_topics": top_topics,
            "delta_bullets": bullets,
        })

    # Sort newest-first for the page
    pulse.sort(key=lambda p: p["week_iso"], reverse=True)

    OUT.write_text(
        json.dumps(pulse, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"✅ Weekly pulse: {len(pulse)} weeks → {OUT.relative_to(REPO)}")
    if pulse:
        print(f"   🔥 burst flagged in {burst_weeks}/{len(pulse)} weeks "
              f"({burst_weeks / len(pulse):.0%}) — rolling median + {BURST_MAD_MULTIPLIER}·MAD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
