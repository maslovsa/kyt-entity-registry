# kyt-entity-registry

**Landing page** → <https://maslovsa.github.io/kyt-entity-registry/>
· **Audit tool** → <https://maslovsa.github.io/kyt-entity-registry/audit.html>

Public registry of crypto entity metadata + logos. Shared source of
truth for [aegis-platform](https://github.com/maslovsa/aegis-platform)
and any future KYT/AML project that needs "the Binance logo" or "the
OFAC seal".

- **entities.csv** — 800+ rows today. Exchanges, DEXes, bridges, DeFi
  protocols, mixers, sanctioning bodies, hack incidents. Ranked by
  importance (0-100). Single source of truth.
- **logos/** — PNG 160×160 per entity, bucketed by category.
- **logos/_lookup.json** — fuzzy-match index (800 entries, ~80 KB)
  with pre-extracted keywords. Powers [lookup.js](lookup.js) + MCP.
- **scripts/** — enrichment pipeline (Arkham → Brandfetch → DefiLlama
  → favicon → placeholder → manual override).
- **mcp/** — MCP stdio servers (Python + TypeScript) so Claude
  agents can `resolve_logo` over freeform labels. See
  [docs/MCP.md](docs/MCP.md).
- **index.html + landing.css + landing.js** — public landing page
  (EN + RU, patchwork quilt, bulk upload).
- **audit.html + gallery.css + gallery.js** — reviewer audit tool.
- **CDN** — served free via jsDelivr.

## Quick URL (consumers)

```
https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/<dir>/<slug>.png
```

Examples:

```
https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/exchanges/binance-com.png
https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/dex/uniswap.png
https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/defi/aave.png
```

`<dir>` ≠ `category_slug` verbatim — one plural rule: `exchange → exchanges`.
Everything else (dex, defi, bridge, wallet, hack, mixer, psp, bot,
gambling, nft_marketplace, sanctioned, mining) maps 1:1.

**Easiest for consumers (recommended): read `entry.logo_path` from
manifest.json (v2, 2026-04-30).** Each manifest entry now ships the
full relative path (e.g. `"logo_path": "logos/exchanges/binance-com.png"`)
so you never need to know the asymmetry.  Just concatenate it onto
the CDN base URL and you're done.  Old v1 fields (`slug`, `category`,
…) remain — v1-aware consumers keep working unchanged.

### Consumer helpers (pick one)

| You have... | Use this | Shipped at |
|---|---|---|
| Canonical `(category_slug, entity_name)` | `entityLogoUrl()` | [docs/CONSUMERS.md](docs/CONSUMERS.md) — copy-paste TS/Python |
| Freeform label like `"Binance Hot Wallet 10"` | `lookup.resolve({category, label})` | [lookup.js](lookup.js) — fetch once per session |
| No category, just a freeform string | `lookup.resolve({label})` across all categories | same |
| A Claude agent (Claude Code / Desktop) | MCP `resolve_logo` tool | [mcp/README.md](mcp/README.md) + [docs/MCP.md](docs/MCP.md) — uvx one-liner |

`lookup.js` matches by keyword-overlap scoring (label tokens ∩ entry
keywords), breaks ties by importance + real-vs-placeholder. Covers
the 500+ entities that `entityLogoUrl()` misses on non-canonical
input. 80 KB index, 1 fetch/session, sub-ms per call.

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

Live at **https://maslovsa.github.io/kyt-entity-registry/** (or open
[index.html](index.html) directly). Every entity renders as a card
with its logo, category, status, and freshness. Category chips,
search, and sort narrow the grid; click **Mark as problem** on cards
whose logo needs rework.

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
(consumed by [`scripts/rework_from_report.py`](scripts/rework_from_report.py)):

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

## Applying a rework report

[`scripts/rework_from_report.py`](scripts/rework_from_report.py)
walks a reviewer-exported CSV and takes one of four per-row
actions. Runs offline; never touches the network.

### One-time setup

```bash
# macOS / modern Linux: the system python3 enforces PEP 668 and
# refuses `pip install` globally. Use a venv.
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` is pinned loosely (Pillow >= 10, httpx >= 0.27)
so CPython 3.8 → 3.13 all resolve. On 3.8 pip picks Pillow 10
(last release supporting that line); on 3.9+ you get Pillow 11.

### Run

```bash
# Dry-run — prints the plan, writes nothing.
.venv/bin/python scripts/rework_from_report.py path/to/kyt-registry-rework-YYYY-MM-DD.csv

# Apply. Writes PNGs to logos/_manual/ + logos/<cat>/, updates entities.csv.
.venv/bin/python scripts/rework_from_report.py path/to/kyt-registry-rework-YYYY-MM-DD.csv --apply

# Commit.
git add entities.csv logos/
git commit -m "rework: apply N suggestions from <report>"
```

Run it from the repo root — the script resolves internal paths
from its own location, and the CSV path can be absolute or
relative.

If you hit `ModuleNotFoundError: No module named 'PIL'` you're
running a Python that doesn't have the deps installed. The script
catches this at import time and prints the fix (use the venv
interpreter shown above).

### Decision table

| Inputs | Action | What happens |
|---|---|---|
| `suggested_logo_data_url` starts with `data:image/…` | **apply** | base64-decode → `normalize_png.normalize()` → write to `logos/_manual/<cat>/<slug>.png` AND `logos/<cat>/<slug>.png`. CSV row flips to `logo_status=manual`, `manual_lock=true`, fresh `logo_hash`/`logo_updated_at`. Nightly enrich will never overwrite it. |
| no data URL, reason ∈ `{wrong_image, low_quality, outdated}` | **retry** | Delete `logos/<cat>/<slug>.png`. CSV row resets to `logo_status=none`. Next nightly enrich re-tries every source from scratch. `_manual/` override (if any) is preserved. |
| no data URL, reason = `missing` | **clear** | Same as retry — delete PNG + reset row. Intent: "this entity should not have a logo". Next enrich will write a placeholder back; a human then either decides that's fine or hand-curates. |
| no data URL, reason ∈ `{manual_needed, other, (empty)}` | **log** | Print the row and move on — nothing to automate. A maintainer picks it up manually. |
| `arkham_slug` not in current `entities.csv` | **skip** | The row refers to an entity that no longer exists (dormant / renamed). Logged, no changes. |
| `manual_lock=true` on the target row and no fresh suggestion | **skip** | Respect the lock; only a new `suggested_logo_data_url` can override a locked row. |

### Handoff flow

Reviewer exports the CSV from the gallery → hands it over (PR under
`reports/`, email attachment, whatever). A maintainer runs the
script locally, reviews the dry-run, re-runs with `--apply`, and
commits. All decisions happen locally — no suggested bytes ever
leave the reviewer's machine until the maintainer pushes.

## GitHub Pages

Already enabled at https://maslovsa.github.io/kyt-entity-registry/.
The `main` branch is the deployed ref. Pages build is automatic on
push (~1 min). CDN cache TTL matches jsDelivr (12-24 h) — for
urgent UI fixes bust with:

```bash
curl https://purge.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/index.html
```

## Contributing

PRs welcome for:
- Logo corrections (drop your PNG into `logos/_manual/<cat>/<slug>.png`)
- New entity rows in `entities.csv` (keep rows sorted by importance DESC)
- Script improvements

Please keep logos ≤ 50 KB (tune compression if needed) and exactly
160×160 RGBA PNG.

## Related docs

- **[docs/CONSUMERS.md](docs/CONSUMERS.md)** — TS + Python helpers
  for consumers: canonical `entityLogoUrl()`, fuzzy `resolve()`,
  existence check via `_index.json`, SHA-pinning for PDFs, cache
  gotchas. Drop the snippets into any new consumer verbatim.
- **[docs/PROVIDERS.md](docs/PROVIDERS.md)** — contract for upstream
  projects (aegis-platform today) shipping fresh CSV exports:
  column ownership, never-do list, PR review checklist.
- **[lookup.js](lookup.js)** — the fuzzy resolver itself (~50 lines,
  ES module). Fetch once per session, resolve freeform labels to
  CDN URLs.
- **[CLAUDE.md](CLAUDE.md)** — agent-facing runbook: constraints,
  source-priority chain, audit-loop rules, never-do list.

## License

- **Code**: MIT.
- **Logos**: Each logo is property of its respective brand owner.
  Inclusion here is fair-use for interoperability / identification.
  If you're a brand owner and want a logo removed or replaced,
  open an issue or PR — will act same-day.
