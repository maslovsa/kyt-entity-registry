# kyt-entity-registry

**Landing page** → <https://maslovsa.github.io/kyt-entity-registry/>

Public registry of crypto entity logos for KYT/AML tools: "the Binance
logo", "the OFAC seal", the Uniswap icon — one URL per entity.

- **entities.csv** — one row per entity: slug, display name, category,
  importance, domain, match keywords and logo status.
- **logos/** — PNG 160×160 per entity, bucketed by category.
- **manifest.json** — runtime file for badge detection: every entity
  with a logo, its `logo_path`, keywords and sanctions designation.
- **logos/_lookup.json** — fuzzy-match index with pre-extracted
  keywords. Powers [lookup.js](lookup.js) + MCP.
- **mcp/** — MCP stdio servers (Python + TypeScript) so Claude
  agents can `resolve_logo` over freeform labels. See
  [docs/MCP.md](docs/MCP.md).
- **index.html + landing.css + landing.js** — public landing page
  (EN + RU, patchwork quilt, bulk upload).
- **scripts/** — build + validation (manifest, lookup index, PNG
  normalisation, repo-size guard).
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
Everything else maps 1:1.

**Easiest for consumers (recommended): read `entry.logo_path` from
manifest.json.** Each manifest entry now ships the
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

## entities.csv columns

| Column | Meaning |
|---|---|
| `slug` | filename stem of the logo, `logos/<dir>/<slug>.png` |
| `entity_name` | display name |
| `category_slug` | `exchange`, `dex`, `bridge`, `defi`, `wallet`, … (see `category_to_dir` in `logos/_lookup.json`) |
| `importance` | ranking weight, higher first |
| `canonical_domain` | the entity's main website |
| `keywords` / `product_aliases` | comma-separated match terms / phrases that must NOT match the entity |
| `logo_status` | `manual` / `fetched` / `synthetic` / `favicon` / `placeholder` / `none` / `deprecated` |
| `logo_updated_at` | ISO date of the last logo change |
| `manual_lock` | `true` → automated refresh never touches this row |
| `logo_hash` | sha256 of the current PNG |

`logos/_index.json` lists only rows with a **real** logo (excludes
`placeholder` + `none`). Use it client-side to tell a genuine logo from
the generic fallback glyph.

## Manual overrides

Drop a hand-curated PNG into `logos/_manual/<category>/<slug>.png` in a PR.
It is copied into the main path and the row is set to
`manual_lock=true` + `logo_status=manual`; no automated refresh will
overwrite it after that.

## After editing entities.csv

```bash
python3 scripts/generate_manifest.py --input entities.csv --output manifest.json
python3 scripts/build_lookup.py
python3 scripts/validate_manifest.py
python3 scripts/check_repo_size.py
python -m pytest -q tests
```

CI (`validate.yml`) regenerates the manifest and fails if the committed
one differs.

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

## Contributing

PRs welcome for:
- Logo corrections (drop your PNG into `logos/_manual/<cat>/<slug>.png`)
- New entity rows in `entities.csv`

Please keep logos exactly 160×160 RGBA PNG (`scripts/normalize_png.py`)
and the whole tree under jsDelivr's 50 MB package limit
(`scripts/check_repo_size.py`, enforced in CI at 48 MB).

## Related docs

- **[docs/CONSUMERS.md](docs/CONSUMERS.md)** — TS + Python helpers
  for consumers: canonical `entityLogoUrl()`, fuzzy `resolve()`,
  existence check via `_index.json`, SHA-pinning for PDFs, cache
  gotchas.
- **[docs/MCP.md](docs/MCP.md)** — MCP server reference.
- **[lookup.js](lookup.js)** — the fuzzy resolver itself (ES module).

## License

- **Code**: MIT.
- **Logos**: Each logo is property of its respective brand owner.
  Inclusion here is fair-use for interoperability / identification.
  If you're a brand owner and want a logo removed or replaced,
  open an issue or PR — will act same-day.
