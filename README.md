# Activity Atlas

Weekly-evolving visualization of one researcher's GitHub activity across
three organizations — `snuconnectome`, `Transconnectome`, `neurox-org` —
built in the style of digital journalism: clean visuals, interactive
exploration, and rule-based weekly storytelling.

[Live site →](https://snuconnectome.github.io/activity-atlas/) (rebuilds every Monday 08:00 UTC)

---

## Why this exists

<!-- TODO(human): Personal narrative — replace this section with 4–8 lines in your own voice
     answering: What pattern in your work do you most want to see? What would change
     if you noticed it 6 months earlier? Who else (lab members, collaborators, your
     future self) might benefit from seeing this?
     This is the only part of the README that should not be generic. Keep the rest
     of the document factual. -->

(Personal motivation goes here — see TODO above.)

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
