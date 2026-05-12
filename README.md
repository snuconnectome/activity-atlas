# Activity Atlas

Weekly-evolving visualization of one researcher's GitHub activity across
three organizations — `snuconnectome`, `Transconnectome`, `neurox-org` —
built in the style of digital journalism: clean visuals, interactive
exploration, and rule-based weekly storytelling.

[Live site →](https://snuconnectome.github.io/activity-atlas/) (rebuilds every Monday 08:00 UTC)

---

## Why this exists

<!-- DRAFT by Claude — please refine in your own voice. Original TODO(human) guidance:
     What pattern in your work do you most want to see? What would change if you
     noticed it 6 months earlier? Who else (lab members, collaborators, your
     future self) might benefit from seeing this? -->

지난 8개월간 세 개 organization에 흩어진 ~93건의 commit을 돌아보면,
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

Four pages, each a different lens on the same ~93-commit dataset:

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
├── scripts/              # Python pipeline (Phase 1, 2, 7)
│   ├── fetch_commits.py
│   ├── topic_model.py
│   └── weekly_pulse.py
├── data/                 # JSON outputs (versioned for diffability)
│   ├── schema.json       # Locked data contracts
│   ├── raw/commits.json
│   ├── topics.json
│   ├── embeddings.json
│   └── weekly_pulse.json
├── assets/
│   └── tokens.css        # SNU Blue / Okabe-Ito palette
├── *.qmd                 # Quarto pages (Phase 3-7)
├── _quarto.yml
└── .github/workflows/build.yml
```

## Local development

```bash
# 1. Fetch data
python scripts/fetch_commits.py

# 2. Run topic pipeline
python scripts/topic_model.py

# 3. Compute weekly pulse
python scripts/weekly_pulse.py

# 4. Preview site
quarto preview
```

## Design decisions

See [`/home/juke/.claude/plans/quizzical-munching-muffin.md`](../../.claude/plans/quizzical-munching-muffin.md)
for the full plan, including:

- Why **not** Observable Framework (overkill at N=93)
- Why **not** Neo4j (static publish mismatch)
- Why Sankey is 2 layers, not 3
- Why Weekly Pulse is rule-based, not LLM-generated

## License

MIT — see [LICENSE](./LICENSE).
