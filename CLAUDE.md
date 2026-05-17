# CLAUDE.md — Activity Atlas Onboarding

> Onboarding guide for Claude Code (and any AI agent) joining this project.
> Optimized for fast context loading: read this once and you have most of
> what you need.

## TL;DR

- **Project**: Weekly-evolving viz dashboard of one researcher's GitHub activity across `snuconnectome`, `Transconnectome`, `neurox-org`
- **Live**: https://snuconnectome.github.io/activity-atlas/
- **Stack**: Quarto + Observable Plot + D3 + Cytoscape.js + Python (BERTopic + UMAP)
- **Cadence**: GitHub Actions cron every **Monday 08:00 UTC** + `workflow_dispatch` + push to `main` (paths-filtered)
- **State**: V1 shipped 2026-05-13 (autonomous ~3h), browser-verified across all 4 pages

## Why this project exists in one sentence

Make the researcher's own work patterns (proposal bursts, paper cycles, teaching, tool building) visible enough that 6-months-late realizations become 6-weeks-early.

## Architecture (one diagram)

```
GitHub Actions cron (Mon 08:00 UTC) + workflow_dispatch + push:main
   │
   ▼
Python pipeline (scripts/)
  ├─ fetch_commits.py    → data/raw/commits.json      [LOCAL ONLY — see Refresh workflow]
  ├─ topic_model.py      → data/topics.json + data/embeddings.json
  └─ weekly_pulse.py     → data/weekly_pulse.json
   │
   ▼
Quarto render (5 pages)
  ├─ index.qmd       Overview     — calendar heatmap + stream + category bars
  ├─ latent.qmd      Latent       — UMAP scatter (D3 zoom/pan) + topic chips
  ├─ network.qmd     Network      — Cytoscape force-directed + d3-sankey
  ├─ pulse.qmd       Pulse        — rule-based weekly delta
  └─ about.qmd       About        — meta page
   │
   ▼
GitHub Pages (gh-pages artifact) — https://snuconnectome.github.io/activity-atlas/
```

## Repository layout

```
activity-atlas/
├── scripts/              # Python pipeline (3 scripts, stdlib + ML deps only)
│   ├── fetch_commits.py
│   ├── topic_model.py
│   └── weekly_pulse.py
├── data/                 # Versioned JSON outputs (diffable across CI runs)
│   ├── schema.json       # ★ LOCKED data contracts — change carefully
│   ├── raw/commits.json  # Commit metadata from gh api
│   ├── topics.json       # Cluster definitions + clustering_method metadata
│   ├── embeddings.json   # UMAP 2D projection per commit
│   └── weekly_pulse.json # Per-ISO-week aggregates + delta bullets
├── assets/
│   └── tokens.css        # SNU Blue + Okabe-Ito palette, namespaced as --aa-*
├── index.qmd | latent.qmd | network.qmd | pulse.qmd | about.qmd
├── _quarto.yml           # Multi-page site config; theme=cosmo + tokens.css
├── requirements.txt      # bertopic, sentence-transformers, umap-learn, hdbscan, sklearn
├── .github/workflows/build.yml  # Weekly cron + manual dispatch; deploys to Pages
├── .venv/                # Local Python venv (gitignored)
└── _site/                # Quarto output (gitignored)
```

## Data contracts (`data/schema.json` is the source of truth)

| File | Shape | Producer | Consumer |
|------|-------|----------|----------|
| `data/raw/commits.json` | `[{sha, org, repo, author_date, message, additions, deletions, files_count, repo_category}]` | `fetch_commits.py` | `topic_model.py`, all 4 pages |
| `data/topics.json` | `{topics: [{topic_id, label, top_words, size, color}], metadata: {clustering_method, n_commits, model, generated_at}}` | `topic_model.py` | `latent.qmd`, `network.qmd`, `pulse.qmd`, `index.qmd` |
| `data/embeddings.json` | `[{sha, x, y, topic_id}]` | `topic_model.py` | `latent.qmd`, `network.qmd` |
| `data/weekly_pulse.json` | `[{week_iso, commit_count, top_topics, delta_bullets}]` | `weekly_pulse.py` | `pulse.qmd` |

Changing any field requires updating every producer + consumer + `data/schema.json`.

## Local development

```bash
# One-time setup
python3 -m venv .venv && .venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Quarto (if missing — Linux ARM64 example)
QV=$(gh api repos/quarto-dev/quarto-cli/releases/latest --jq '.tag_name' | sed 's/^v//')
curl -sL "https://github.com/quarto-dev/quarto-cli/releases/download/v${QV}/quarto-${QV}-linux-arm64.tar.gz" -o /tmp/quarto.tar.gz
mkdir -p ~/.local/quarto && tar -xzf /tmp/quarto.tar.gz -C ~/.local/quarto --strip-components=1

# Refresh data (requires `gh auth login` with `repo` scope)
.venv/bin/python scripts/fetch_commits.py
.venv/bin/python scripts/topic_model.py
.venv/bin/python scripts/weekly_pulse.py

# Render + preview
~/.local/quarto/bin/quarto preview      # localhost server
~/.local/quarto/bin/quarto render       # build _site/ only
```

## Refresh workflow (production data updates)

CI does **NOT** run `fetch_commits.py`. Why: cross-org commit search needs a `repo + admin:org` token; storing that as a workflow secret is a credential-leakage risk (auto-mode classifier rejects it — see `feedback_gh_pat_workflow_secret_denial.md`).

So refresh runs **locally** and pushes the JSON:

```bash
.venv/bin/python scripts/fetch_commits.py
git add data/raw/commits.json
git commit -m "chore(data): refresh"
git push    # CI auto-rebuilds topics + viz from new commits.json
```

CI re-runs `topic_model.py` + `weekly_pulse.py` + `quarto render` + Pages deploy on every push that touches paths in `.github/workflows/build.yml`'s `paths` filter (including `data/raw/commits.json`).

## TODO(human) anchors — domain decisions only the user can make

These are intentional hand-off points where the user's judgment beats any LLM:

| # | File | Variable | What to fill |
|---|------|----------|--------------|
| 1 | `README.md` § "Why this exists" | (free prose) | Personal voice 4–8 lines (currently a Claude draft in Korean) |
| 2 | `scripts/fetch_commits.py` | `REPO_CATEGORIES` | 23 `org/repo` → `proposal | paper | education | core | tool | other`. 3 guesses to verify: `Setup_arpah`, `AI4Psych_writing`, `decoding-annual-report` |
| 3 | `scripts/topic_model.py` | (cluster labels) | KMeans fallback labels auto-generated from TF-IDF top words; rename when you see misfits in `latent.qmd` |
| 4 | `scripts/weekly_pulse.py` | `WEEKLY_PULSE_NOTABLE_THRESHOLD` | Currently 4 commits/week. Adjust based on your typical burst size. |

## Known gotchas

### Plot.cell vs. time data (caught in first ship)

`Plot.cell()` defaults x to a **band scale**. Passing time-valued data throws `scale incompatible with channel: time !== band` at runtime and the calendar silently fails to render. **Solution in `index.qmd`**: pre-compute ISO-week strings (`d3.utcFormat("%Y-W%V")`) as the x domain and fill every day in the 12-month window so empty cells appear.

### Plot.sankey does NOT exist (caught in first ship)

`@observablehq/plot@0.6.x` does **not** ship a Sankey mark. `Plot.sankey()` throws `is not a function`. **Solution in `network.qmd`**: `import { sankey, sankeyLinkHorizontal, sankeyJustify } from "https://cdn.jsdelivr.net/npm/d3-sankey@0.12.3/+esm"` and render manual SVG (rect for nodes + path with `sankeyLinkHorizontal` for links). Verify any future "Plot.X" suggestion against the actual API before relying on it.

### N=82 BERTopic typically degenerates → KMeans fallback

HDBSCAN with default `min_cluster_size=5` on 75 preprocessed commits usually collapses to 0–2 topics + huge `-1` outlier blob, OR throws when BERTopic API drifts. `scripts/topic_model.py` has a hard-coded fallback: if `unique_topics < 3` OR `>70% in -1` OR primary path raises, switch to `KMeans(n_clusters=6)` and label clusters via TF-IDF top words. The chosen path is recorded in `topics.json#/metadata/clustering_method` so the dashboard knows.

### GitHub Pages CDN cache during verification

After deploy, the same URL may serve cached content for several minutes. Use a cache-busting query string when re-verifying: `https://snuconnectome.github.io/activity-atlas/?nocache=YYYYMMDD-N`. Without this, you'll see the *old* error you just fixed and assume the fix didn't work.

### HuggingFace model download in CI

`paraphrase-multilingual-MiniLM-L12-v2` is ~440 MB. The workflow uses `actions/cache@v4` keyed on `hashFiles('requirements.txt')` with cache paths `~/.cache/huggingface` + `~/.cache/torch`. First run takes ~3 min; subsequent runs ~2 min 40 s (cache hit).

### codex exec hangs on stdin (autonomous agent gotcha)

`codex exec "PROMPT"` (with `--dangerously-bypass-approvals-and-sandbox` or not) blocks waiting for stdin when launched from a non-TTY context. Output stays 0 bytes until kill. Always redirect:

```bash
codex --dangerously-bypass-approvals-and-sandbox exec --skip-git-repo-check "..." </dev/null > log 2>&1
```

For *this project's* viz verification, prefer **Playwright MCP** directly (faster, 0 LLM tokens) over `codex exec`. See `feedback_browser_viz_runtime_verification.md`.

### Quarto / esm.sh import URLs are version-pinned

Pages import `d3@7`, `@observablehq/plot@0.6.16`, `cytoscape@3.30.0`, `d3-sankey@0.12.3` via esm.sh. If any upstream breaks, pin to a known-good minor version rather than `@latest`.

## Verification protocol — required before claiming "works"

**Pass 1 (cheap — file shipped):**
```bash
curl -s https://snuconnectome.github.io/activity-atlas/ | grep -oE 'd3@7|cytoscape|kpi-row|topic-chips'
```

**Pass 2 (necessary — JS runtime + DOM):**
Navigate each page with a real browser (Playwright preferred). For each:
- `console.errors.length === 0` (or `=== 1` if favicon 404)
- Page-specific DOM counts match expected:

| Page | Selectors | Expected |
|------|-----------|----------|
| index | `.kpi-tile` · `#calendar svg rect` · `#stream svg` · `#category-bars svg` | 4 · ~196 · ≥1 · ≥1 |
| latent | `#umap-svg circle` · `.topic-chip` · `#topic-table tr` | 75 · 6 · 6 |
| network | `#cy canvas` · `#sankey svg rect` · `#sankey svg path` · `#sankey svg text` | 3 · 9 · 14 · 9 |
| pulse | `details.pulse-week` · first `details[open]` · first `ul li` count | 10 · true · 4 |

Always cache-bust the URL (`?nocache=...`) during verification. **Pass 1 alone is not sufficient** — the two silent JS bugs above slipped through Pass 1 on first ship.

## Anti-patterns (do NOT do)

- **Do not** add `auto-LLM-narrative` to the Weekly Pulse. At ~2.7 commits/week it produces hallucinated padding. Rule-based delta is the v1 contract.
- **Do not** store the user's `gh auth token` as a workflow secret to enable CI-side fetch. Use the local-refresh pattern.
- **Do not** ship to `gh-pages` without browser verification of all 4 pages. HTML markers are a necessary but insufficient gate.
- **Do not** add new visualization libraries without checking the import URL on esm.sh and verifying the API surface (e.g., "Plot has Sankey" was wrong).
- **Do not** scaffold a `scripts/refresh.sh` or other "automation wrappers" — the 3-line refresh sequence in this doc is the contract; wrappers drift.

## Related memory entries (cross-session context)

- `activity_atlas_project.md` — Project summary
- `feedback_low_n_bertopic_kmeans_fallback.md` — Why KMeans fallback exists
- `feedback_gh_pat_workflow_secret_denial.md` — Why CI doesn't fetch
- `feedback_browser_viz_runtime_verification.md` — Why Pass 2 is required

## Reference

- Master plan: `~/.claude/plans/quizzical-munching-muffin.md` (private to user's local machine)
- Live URL: https://snuconnectome.github.io/activity-atlas/
- Issues/PRs: https://github.com/snuconnectome/activity-atlas
