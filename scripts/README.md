# scripts/ — enrichment pipeline

**Not yet implemented.** See `../CLAUDE.md` section "Tasks ready for you" for
the build-out order (T1 → T8).

## Intended interface

```
# CLI
python scripts/enrich.py [--max N] [--category exchanges] [--dry-run]

# Called by .github/workflows/enrich-logos.yml nightly
```

## Envelope

- Reads `../entities.csv`
- Writes `../entities.csv` (in place, same column order)
- Writes `../logos/<category>/<slug>.png`
- Never writes logs outside the repo; all stdout/stderr goes to the
  GitHub Actions log

## Source order (from CLAUDE.md C4)

1. `enrich_from_arkham.py` — static.arkhamintelligence.com/entities/{slug}.png
2. `enrich_from_brandfetch.py` — cdn.brandfetch.io/{domain}?c={CLIENT_ID}
3. `enrich_from_defillama.py` — icons.llamao.fi/icons/protocols/{slug}?w=128&h=128
4. `logos/_manual/<cat>/<slug>.png` — highest authority; copied in + lock

Each source returns either `bytes` (raw image) or `None`. Orchestrator
feeds bytes into `normalize_png.py` which produces canonical 160×160
RGBA PNG.

## When Claude comes to work here

Read `../CLAUDE.md` top-to-bottom. Do not add a 5th source without
updating the RFC. Do not change `entities.csv` schema without
coordinating with the sdn_api export job.
