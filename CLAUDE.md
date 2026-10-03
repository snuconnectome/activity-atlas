# Activity Atlas — agent onboarding

Read claudedocs/HANDOFF_2026-07-30.md for the current handoff (updated 2026-10-03; the existing filename is retained), README.md for commands and interpretation, and docs/reviews/2026-10-03/ for review and implementation evidence. Historical snapshots in Git are not the current data contract.

## Architecture

Local gh collection → scope-specific raw snapshot → topic model + pulse → taxonomy/public policy join → data/pub → Quarto → full artifact guard + browser tests → Pages.

Eight pages share the public projection. CI runs regression tests and renders committed JSON; it does not collect GitHub data or run private-message ML. A successful rebuild does not prove fresh data.

## Contracts

- Resolve paths only via scripts/aa_paths.py. ACTIVITY_ATLAS_SCOPE=pi (default) or all applies to every pipeline stage. --all-authors selects all for collection only.
- Raw and derived data stay outside Git in ACTIVITY_ATLAS_DATA_DIR/scopes/<scope>/{raw,derived}. The private taxonomy is ACTIVITY_ATLAS_DATA_DIR/taxonomy/repos.json.
- --full replaces a scope, never merges an old all-author snapshot into PI. Event identity includes org/repo and SHA.
- Join requires a complete matching collection manifest, raw fingerprint, topic/embedding and pulse digests, and unique known embedding references. Equal row counts are insufficient.
- Public named records require PUBLIC visibility. Private and unknown repos become daily group counts without name, SHA, subject, exact timestamp, or coordinates. Any restricted source neutralizes its topic text. New producer fields are excluded by allowlists.
- Public subjects additionally require author consent. Missing consent is restrictive. Public Pulse is rebuilt from counts and approved labels.
- data/lab and _site-lab are private, ignored, never deployed. Keep lab data out of any resource or nested public build. Render/inspect the entire deployable tree.
- Generation replacement uses Linux renameat2 exchange, with no missing-path window. Unsupported platforms fail closed. This does not claim power-loss durability across filesystem faults.
- JSON contracts are data/schema.json. Update producers, consumers, fixtures and schema together. Commit-count shares do not measure effort, budget or productivity. PI-only observations do not establish succession risk. PI repo commits do not establish meetings or review.

## TDD and verification

Create a synthetic failing regression first, make the narrow correction, then run the affected tests. Fixtures need no private source or GitHub token. Do not print raw messages, private names, or student identities into reports. Use data-origin provenance before accepting derived results.

```bash
python3 -m unittest discover -s tests -v
quarto render
python3 scripts/check_public.py --site _site
# Start a bound localhost HTTP server, then:
AA_TEST_URL=http://127.0.0.1:9000 python3 -m unittest discover -s tests -p test_browser_safety.py -v
```

All eight rendered pages need actual DOM/runtime verification before claiming they work. ARM64 DGX Chromium: /home/juke/.cache/ms-playwright/chromium-1217/chrome-linux/chrome; set AA_CHROMIUM when necessary. JS imports are pinned; SVG library text APIs and DOM textContent are preferred. Escape every data substitution in authored HTML templates.

## Local work and delivery

Preserve unrelated user work, especially .serena/, docs/working-memory.md and scripts/workmem.py. Stage only authorized files. This onboarding does not authorize a push, deployment, repository-history rewrite, student messaging, or resource archival. Current-file protection and old-history removal are separate outcomes. Avoid introducing new orchestration/refresh wrappers; the four pipeline commands in README are the contract.
