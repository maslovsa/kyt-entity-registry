# kyt-entity-registry

Public registry of crypto entity metadata + logos. Shared source of
truth for [sdn_api](https://github.com/maslovsa/sdn-api),
[aml_checker](https://github.com/maslovsa/aml_checker), and any future
KYT/AML project that needs "the Binance logo" or "the OFAC seal".

- **entities.csv** — 800+ rows today. Exchanges, DEXes, bridges, DeFi
  protocols, mixers, sanctioning bodies, hack incidents. Ranked by
  importance (0-100). Single source of truth.
- **logos/** — PNG 160×160 per entity, bucketed by category.
- **scripts/** — enrichment pipeline (Arkham → Brandfetch → DefiLlama
  icons → manual override).
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
| `logo_status` | `none` / `arkham` / `brandfetch` / `defillama` / `manual` |
| `logo_updated_at` | ISO date of last successful fetch |
| `manual_lock` | `true` → automated enrichment NEVER touches this row |
| `logo_hash` | sha256 of the current PNG. Skip commit if unchanged. |

Nightly cron (see `.github/workflows/enrich-logos.yml`) walks entities
by importance DESC and:

1. **Skips** rows where `manual_lock=true`.
2. **Skips** rows where `logo_status != 'none'` AND
   `logo_updated_at > now() - REFRESH_DAYS` (default 30 days).
3. For the rest, tries sources in order: Arkham → Brandfetch →
   DefiLlama → fallback.
4. If the fetched PNG's sha256 matches `logo_hash`, commits nothing.
5. Otherwise normalizes to 160×160 transparent PNG, updates
   `entities.csv`, writes logo file.

## Manual overrides

Drop a hand-curated PNG into `logos/_manual/<category>/<slug>.png`.
Enrichment will see it, copy into the main path, flip the CSV row's
`manual_lock=true` + `logo_status=manual`. After that, no auto-refresh
will overwrite it.

## Contributing

PRs welcome for:
- Logo corrections (drop your PNG into `logos/_manual/<cat>/<slug>.png`)
- New entity rows in `entities.csv` (keep rows sorted by importance DESC)
- Script improvements

Please keep logos ≤ 50 KB (tune compression if needed) and exactly
160×160 RGBA PNG.

## License

- **Code**: MIT.
- **Logos**: Each logo is property of its respective brand owner.
  Inclusion here is fair-use for interoperability / identification.
  If you're a brand owner and want a logo removed or replaced,
  open an issue or PR — will act same-day.
