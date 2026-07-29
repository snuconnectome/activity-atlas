# Activity Atlas

[![Build](https://github.com/snuconnectome/activity-atlas/actions/workflows/build.yml/badge.svg)](https://github.com/snuconnectome/activity-atlas/actions/workflows/build.yml)
[![Pages](https://img.shields.io/badge/live-snuconnectome.github.io%2Factivity--atlas-0072B2)](https://snuconnectome.github.io/activity-atlas/)

Weekly-evolving visualization of one researcher's GitHub activity across
three organizations — `snuconnectome`, `Transconnectome`, `neurox-org` —
built in the style of digital journalism: clean visuals, interactive
exploration, and rule-based weekly storytelling.

**[🌐 Live site →](https://snuconnectome.github.io/activity-atlas/)** · rebuilds every Monday 08:00 UTC + on push to `main`

---

## Why this exists

<!-- DRAFT by Claude — please refine in your own voice. Original TODO(human) guidance:
     What pattern in your work do you most want to see? What would change if you
     noticed it 6 months earlier? Who else (lab members, collaborators, your
     future self) might benefit from seeing this? -->

지난 8개월간 세 개 organization에 흩어진 82건의 commit을 돌아보면,
무엇이 어디로 흘러갔는지 내 머릿속에서도 이미 흐릿해진다.
제안서 마감 burst, 논문 review cycle, 강의 자료, 학생 협업 —
이 흐름들이 어떤 주제로 묶이는지, 어느 주에 무게중심이 어디 있었는지를
정량으로, 그리고 시각적으로 보고 싶다.

작년 가을에 이 그림이 있었다면 핵심 thread에 더 일찍 집중했을 것이고,
마감 직전 burst를 한두 주 평탄화했을 것이다.
이 atlas는 일차적으로 미래의 내가 자기 시간 배분을 정직하게 들여다보기 위한
거울이고, 부차적으로는 협력자들이 "지금 어디에 무게가 실려 있는지"를
빠르게 읽도록 돕는 도구다.

---

## What it shows

Four pages, each a different lens on the same dataset (2,226 commits across 134 repos as of 2026-07):

| Page | Lens | Key visualization |
|------|------|-------------------|
| **Overview** | Temporal | Multi-org calendar heatmap + topic stream graph |
| **Network** | Structural | Cytoscape force-directed graph + Org→Topic Sankey |
| **Latent** | Semantic | UMAP scatter of commit messages, zoomable, hover→GitHub link |
| **Pulse** | Narrative | Rule-based weekly delta — what changed, what's new |

Topics come from BERTopic on multilingual (Korean + English) commit
messages, projected into 2D with UMAP. Color palette is
[Okabe-Ito color-blind safe](https://jfly.uni-koeln.de/color/) extended with
SNU Blue (`#003380`).

### Private working-memory companion

`scripts/workmem.py` adds a local-only "이거 워킹 메모리로" workflow: park an
important task outside biological working memory, then resurface it when git,
calendar, time-of-day, and fuzzy urgency signals suggest a humane re-entry
window. Private items live under
`~/.local/share/activity-atlas/working-memory/` and are not published to GitHub
Pages. See [`docs/working-memory.md`](./docs/working-memory.md).

## Stack

- **Data**: Python (`gh` CLI + sentence-transformers + BERTopic + UMAP)
- **Site**: [Quarto](https://quarto.org/) with [Observable Plot](https://observablehq.com/plot)
  cells, [D3](https://d3js.org/) for the UMAP, [Cytoscape.js](https://js.cytoscape.org/)
  for the network
- **Hosting**: GitHub Pages, deployed via GitHub Actions
- **Cadence**: Cron every Monday + `workflow_dispatch` manual trigger

## Layout

```
activity-atlas/
├── scripts/
│   ├── aa_paths.py       # Shared path resolution (raw store lives outside the repo)
│   ├── fetch_commits.py  # gh repo walk → local raw store
│   ├── topic_model.py    # BERTopic + UMAP
│   ├── weekly_pulse.py   # Rule-based weekly delta
│   ├── join.py           # Taxonomy join → publishable projection
│   ├── seed_taxonomy.py  # One-shot REPO_MAP.md seeder (not a pipeline stage)
│   └── workmem.py        # Private local working-memory companion
├── data/
│   ├── schema.json       # Locked data contracts
│   ├── taxonomy/         # repos.json (curated) + rules.json (fallback patterns)
│   └── pub/              # Published: commits_slim, topics, embeddings,
│                         #            weekly_pulse, palette, taxonomy_coverage
├── assets/
│   └── tokens.css        # SNU Blue / Okabe-Ito palette
├── docs/
│   └── working-memory.md # Local-only working-memory design
├── *.qmd                 # Quarto pages (Phase 3-7)
├── _quarto.yml
└── .github/workflows/build.yml
```

## Local development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. Fetch latest commits across 3 orgs (requires `gh auth login` with repo scope)
.venv/bin/python scripts/fetch_commits.py

# 2. Run topic pipeline (BERTopic + UMAP; downloads HF model ~440MB on first run)
.venv/bin/python scripts/topic_model.py

# 3. Compute weekly pulse delta
.venv/bin/python scripts/weekly_pulse.py

# 4. Join taxonomy + emit publishable projection
.venv/bin/python scripts/join.py

# 5. Preview site
~/.local/quarto/bin/quarto preview
```

### Two data tiers

`data/raw/commits.json` holds full commit message bodies for repos that are
overwhelmingly private. It is **gitignored and never published** — it stays on
the machine that ran `fetch_commits.py`.

What gets committed and deployed is `data/pub/`: `commits_slim.json` (subject
line only, 80 chars, no message body) plus the derived `topics.json`,
`embeddings.json`, and `weekly_pulse.json`. `_quarto.yml` publishes
`data/pub/**` as an allowlist, and CI refuses to build if raw data or a
`message` field ever appears in the repo.

### Refreshing data

The whole Python pipeline runs locally — CI only renders. `fetch_commits.py`
needs an admin-scope token (unsafe as a workflow secret), and the topic scripts
need message bodies that deliberately never enter the repo.

```bash
.venv/bin/python scripts/fetch_commits.py
.venv/bin/python scripts/topic_model.py
.venv/bin/python scripts/weekly_pulse.py
.venv/bin/python scripts/join.py
git add data/pub/ && git commit -m "chore(data): refresh" && git push
```

## Design decisions

See [`CLAUDE.md`](./CLAUDE.md) for the project onboarding guide aimed at Claude
Code sessions. Key explicit out-of-scope decisions:

- Why **not** Observable Framework (pre-aggregated JSON keeps Quarto + Plot viable)
- Why **not** Neo4j (static publish mismatch; Cytoscape.js gives same viz)
- Why Sankey is 2 layers (`Org → Topic`), not 3
- Why Weekly Pulse is rule-based, not LLM-generated
- Why classification is a join step, not a dict inside the fetcher (relabelling
  must not cost 262 API calls)
- Why CI does **not** run `fetch_commits.py` (cross-org admin-scope token as workflow secret is unsafe)

## Verification

Both passes are required before claiming "it works":

```bash
# Pass 1 — HTML markers (file shipped)
curl -s https://snuconnectome.github.io/activity-atlas/ | grep -oE 'd3@7|kpi-row|cytoscape'

# Pass 2 — JS runtime (browser DOM + console errors)
# Use Playwright (or any browser automation). Confirm:
#   index:   0 errors, 4 KPI tiles, ~196 calendar cells
#   latent:  0 errors, 75 UMAP circles, 6 topic chips
#   network: 0 errors, 3 Cytoscape canvases, Sankey 9+14+9 (rect+path+text)
#   pulse:   0 errors, 10 weeks, latest expanded
```

Pass 1 alone is **not sufficient** — see [`CLAUDE.md`](./CLAUDE.md) "Known gotchas" for two silent JS bugs caught only by Pass 2 on first ship.

## License

MIT — see [LICENSE](./LICENSE).
