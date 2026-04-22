# kyt-entity-registry

[Live Demo](https://maslovsa.github.io/kyt-entity-registry/)

Public registry of crypto entity metadata + logos. Shared source of
truth for [sdn_api](https://github.com/maslovsa/sdn-api),
[aml_checker](https://github.com/maslovsa/aml_checker), and any future
KYT/AML project that needs "the Binance logo" or "the OFAC seal".

- **entities.csv** — 800+ rows today. Exchanges, DEXes, bridges, DeFi
  protocols, mixers, sanctioning bodies, hack incidents. Ranked by
  importance (0-100). Single source of truth.
- **logos/** — PNG 160×160 per entity, bucketed by category.
- **scripts/** — enrichment pipeline (Arkham → Brandfetch → DefiLlama
  → favicon → placeholder → manual override).
- **CDN** — served free via jsDelivr.

## Quick URL (consumers)

```
https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/<category>/<slug>.png
```

Examples:

```
https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/exchanges/binance-com.png
https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/dex/uniswap.png
https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/defi/aave.png
```

### Minimal React helper

```tsx
const CDN = 'https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main'
export const entityLogoUrl = (category: string, slug: string) =>
  `${CDN}/logos/${category}/${slug}.png`

// Usage
<img
  src={entityLogoUrl('exchanges', 'binance-com')}
  onError={e => { e.currentTarget.src = `${CDN}/logos/_fallback/unknown.png` }}
  width={32} height={32}
/>
```

## URL pinning — `@main` vs `@<sha>`

jsDelivr's URL can reference any git ref:

- `@main` — always the latest. Edge cache TTL is 12-24 h. **Use this
  by default** in apps. New logos appear automatically within a day.
- `@<commit-sha>` — permanent snapshot. Never changes, immune to
  future corrections. **Use in compliance exports** — e.g. a PDF
  report saying "Binance address was classified as sanctioned on
  2026-04-22; logo as shown is repo at commit abc1234".

You can also pin to a release tag: `@v1.0.0`. Tags come later.

## Refresh policy

Each entity row has:

| Field | Purpose |
|---|---|
| `logo_status` | `none` / `arkham` / `brandfetch` / `defillama` / `favicon` / `manual` / `placeholder` |
| `logo_updated_at` | ISO date of last successful fetch |
| `manual_lock` | `true` → automated enrichment NEVER touches this row |
| `logo_hash` | sha256 of the current PNG. Skip commit if unchanged. |

Nightly cron (see `.github/workflows/enrich-logos.yml`) walks entities
by importance DESC and:

1. **Skips** rows where `manual_lock=true`.
2. **Skips** rows where `logo_status != 'none'` AND
   `logo_status != 'placeholder'` AND
   `logo_updated_at > now() - REFRESH_DAYS` (default 30 days).
   Placeholders intentionally bypass the freshness gate so we keep
   trying real sources every run.
3. For the rest, tries sources in order: **Arkham → Brandfetch →
   DefiLlama → favicon → placeholder**.
   - `favicon` crawls `https://<canonical_domain>/` for
     `<link rel="icon|apple-touch-icon">` (192×192 wins); falls back
     to static paths like `/apple-touch-icon.png`. Rejects ≤ 32×32.
   - `placeholder` writes `logos/404.png` bytes so consumers always
     get a 200 OK from jsDelivr — no 404-flash, no onError gymnastics.
4. If the fetched PNG's sha256 matches `logo_hash`, commits nothing.
5. Otherwise normalizes to 160×160 transparent PNG, updates
   `entities.csv`, writes logo file.

`logos/_index.json` lists only rows with a **real** source hit
(excludes `placeholder` + `none`). Use it client-side to tell a
genuine logo from the generic fallback glyph.

## Manual overrides

Drop a hand-curated PNG into `logos/_manual/<category>/<slug>.png`.
Enrichment will see it, copy into the main path, flip the CSV row's
`manual_lock=true` + `logo_status=manual`. After that, no auto-refresh
will overwrite it.

## Gallery — browse + audit all logos

Open [index.html](index.html) in a browser (or the GitHub Pages deploy
at https://maslovsa.github.io/kyt-entity-registry/ once enabled) to see
every entity as a card with its logo, category, status, and freshness.
Use the category chips, search, and sort to narrow down, then click
**Mark as problem** on cards whose logo needs rework.

Flags persist in `localStorage`, so you can review across sessions.
Two actions per card:

- **Mark as problem** — pick a reason (`wrong_image` / `low_quality`
  / `outdated` / `missing` / `manual_needed` / `other`) and add a
  free-text note.
- **Use my image** — pick a replacement PNG/JPG/WebP/GIF from your
  computer. The browser decodes it, resizes the longest edge to 160
  on a transparent canvas, and embeds the resulting PNG as a
  `data:image/png;base64,…` URL right in the flag — no external
  upload, no expiring link, no rate limit. Preview appears on the
  card so you can visually confirm before exporting.

**Export flagged CSV** downloads `kyt-registry-rework-YYYY-MM-DD.csv`
(consumed by a future `scripts/rework_from_report.py`):

| Column | Source |
|---|---|
| `category_slug`, `arkham_slug`, `entity_name` | joined from entities.csv |
| `reason` | `wrong_image` / `low_quality` / `outdated` / `missing` / `manual_needed` / `user_provided` / `other` |
| `note` | free-text reviewer comment |
| `current_logo_status`, `current_logo_updated_at`, `current_logo_hash` | registry state at flag time |
| `canonical_domain` | for Brandfetch retry hints |
| `flagged_at` | ISO timestamp |
| `suggested_filename` | original filename reviewer picked (provenance only) |
| `suggested_bytes` | byte length of the normalised PNG |
| `suggested_logo_data_url` | full `data:image/png;base64,…` — empty if no replacement was attached |

### Downstream: applying a report

`scripts/rework_from_report.py` (TODO) will walk the CSV and:

1. Rows with `suggested_logo_data_url` → decode base64, drop into
   `logos/_manual/<category_slug>/<arkham_slug>.png`, next enrich
   run copies it to the public path and sets
   `manual_lock=true`.
2. Rows without a suggestion but with `reason=wrong_image` /
   `outdated` → delete the current logo + set `logo_status=none` so
   the next run retries every source.
3. Rows with `reason=manual_needed` → open a GitHub issue
   summarising what's missing so a human can hand-curate.

The PR flow: reviewer exports the CSV, opens a PR adding it under
`reports/` OR emails / attaches it, and a maintainer runs the script
locally. The registry maintainers decide per-row whether to accept
the suggestion.

### Enabling GitHub Pages

Settings → Pages → Source: **Deploy from a branch**, Branch: `main`,
Folder: `/ (root)`. Save. First build takes ~1 min; CDN edge cache
matches jsDelivr (12-24 h), so bust with
`curl https://purge.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/index.html`
after a meaningful UI change.

## Contributing

PRs welcome for:
- Logo corrections (drop your PNG into `logos/_manual/<cat>/<slug>.png`)
- New entity rows in `entities.csv` (keep rows sorted by importance DESC)
- Script improvements

Please keep logos ≤ 50 KB (tune compression if needed) and exactly
160×160 RGBA PNG.

## Related docs

- **[docs/PROVIDERS.md](docs/PROVIDERS.md)** — contract for upstream
  projects (sdn_api today) shipping fresh CSV exports: column
  ownership, never-do list, PR review checklist.
- **[docs/CONSUMERS.md](docs/CONSUMERS.md)** — canonical resolver
  (TypeScript + Python): category → directory map, name→slug
  normalization, `onError` fallback, SHA-pinning for PDFs, cache
  gotchas. Drop the TS helper into any new consumer verbatim.
- **[CLAUDE.md](CLAUDE.md)** — agent-facing runbook, task queue
  T1-T8.

## License

- **Code**: MIT.
- **Logos**: Each logo is property of its respective brand owner.
  Inclusion here is fair-use for interoperability / identification.
  If you're a brand owner and want a logo removed or replaced,
  open an issue or PR — will act same-day.
