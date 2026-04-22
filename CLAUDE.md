# CLAUDE.md — kyt-entity-registry

Read this first if you open this repo as a Claude Code session.
Short. Actionable. Covers the boundaries of what you're expected to
touch and what you MUST leave alone.

## What this repo is

A public, jsDelivr-fronted GitHub repo of crypto entity metadata +
logos. Consumed by sdn_api + aml_checker for UI rendering. It is
**not** a source of truth for risk verdicts — those live in
sdn_api's `label_claims` / Aegis consensus.

Everything in this repo MUST be safe to make public on GitHub: no
API keys, no private network addresses, no PII.

## Mission

Every entity row in `entities.csv` should eventually have a
correctly-attributed 160×160 PNG logo at
`logos/<category>/<slug>.png`, refreshable nightly, manually
overridable.

## Directory map

```
entities.csv               ← authoritative row list (sorted importance DESC)
logos/
  exchanges/               ← Binance, Bybit, Kraken, …
  dex/                     ← Uniswap, Curve, 1inch, …
  bridge/                  ← Stargate, Wormhole, Synapse, …
  defi/                    ← Aave, Compound, Lido, MakerDAO, …
  wallet/                  ← MetaMask, Coinbase Wallet, …
  mining/                  ← F2Pool, AntPool, …
  psp/                     ← Ramp, MoonPay (payment service providers)
  bot/                     ← Banana Gun, Maestro (trading bots)
  gambling/                ← bet365, Stake, …
  nft_marketplace/         ← OpenSea, Blur, …
  mixer/                   ← Tornado Cash, Railgun
  hack/                    ← labelled by incident name (Ronin Bridge, …)
  sanctioned/              ← OFAC SDN, UK OFSI, Chainalysis Sanctions
  _manual/<category>/...   ← hand-curated overrides
  _fallback/unknown.png    ← rendered when CDN 404s

scripts/
  _base.py                 ← shared helpers (CSV read/write, sha256)
  enrich_from_arkham.py    ← PRIMARY source (static.arkhamintelligence.com)
  enrich_from_brandfetch.py ← fallback (cdn.brandfetch.io + client-ID)
  enrich_from_defillama.py ← DeFi-specific fallback (icons.llamao.fi)
  normalize_png.py         ← 160×160 RGBA, optimize, strip EXIF
  enrich.py                ← orchestrator — reads CSV, dispatches sources

.github/workflows/
  enrich-logos.yml         ← nightly cron
```

## Constraints — read before changing anything

### C1. entities.csv rows are additive

- Never delete existing rows. Entities fade (exchange shuts down) —
  the row stays, `logo_status=none`, `manual_lock=true` prevents
  future overwrites. A consumer looking at a year-old report still
  gets a stable lookup.
- Never rename an entity's `slug` — that breaks every pinned URL
  in consumer code. If a brand rebrands, add a NEW row with
  `aliases` pointing at the old slug.
- `importance` may be re-scored when the source sdn_api CSV is
  re-exported. That's fine. The row set stays stable.

### C2. Logo replacement policy

- `manual_lock=true` → enrichment MUST skip. Never automated writes.
- `logo_status in (arkham, brandfetch, defillama)` →
  auto-refreshable every `REFRESH_DAYS` (default 30).
- sha256 check is the gate — if new bytes == old bytes, make NO
  commit. Otherwise ≥20 commits/night from jitter.

### C3. PNG canonical shape

- 160×160 RGBA, optimized (pngquant/oxipng-grade).
- transparent background (no solid white fill).
- ≤ 50 KB.
- No EXIF / metadata.
- `normalize_png.py` enforces this; enrichment scripts MUST pipe
  everything through it, no direct file writes.

### C4. Source priority + quotas

Order (first-found wins):
1. **Arkham** — `https://static.arkhamintelligence.com/entities/<slug>.png`
   Free, static bucket, no rate limit known. Use the `arkham_slug`
   column from entities.csv (lowercase-dash). Covers most crypto
   brands.
2. **Brandfetch CDN** —
   `https://cdn.brandfetch.io/<domain>?c=<client_id>`
   Free, no auth burn. Use `canonical_domain` column. Good for
   non-crypto entities (payment processors, exchanges with rare
   Arkham coverage). Returns PNG/webp — feed webp into normalize_png
   (Pillow handles it).
3. **DefiLlama icons** —
   `https://icons.llamao.fi/icons/protocols/<slug>?w=128&h=128`
   Primarily DeFi protocols. Free CDN, `defillama-protocols` source
   in sdn_api already knows the slug format — reuse it.
4. **Manual override** — `logos/_manual/<category>/<slug>.png`
   Highest authority. Enrichment copies this into the main path
   and sets `manual_lock=true`.

Do NOT add a new source without updating the RFC (sdn_api docs/
RFC_entity_registry.md).

Do NOT commit any source that requires an API key (no Chainalysis,
Elliptic logos — those brands are paid-only and we have no license
to redistribute). Only freely-licensed or fair-use-for-identification
brand assets.

### C5. Commit hygiene

- Nightly cron commits as `github-actions[bot]`, format:
  `enrich: +N new, +M updated, K missed (YYYY-MM-DD)`.
- Manual PRs use clear prefixes: `add: <entity>`, `fix: <entity>
  logo corruption`, `override: <entity>` (+ add to `_manual/`).
- CSV changes that touch many rows at once (re-export from sdn_api)
  should land in their own PR titled `data: re-export N entities
  from sdn_api @ <sdn-api-sha>`. Reviewable diff.

### C6. CDN cache invalidation

jsDelivr caches aggressively (12-24h). If a consumer reports a
corrupted/wrong logo:
1. Fix the PNG, commit.
2. Bust the cache:
   `curl https://purge.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/<cat>/<slug>.png`
3. Tell the consumer cache will clear within minutes.

### C7. Never push secrets

- No `.env` files.
- `BRANDFETCH_CLIENT_ID` is a PUBLIC CDN client ID (baked into every
  webpage that embeds Brandfetch's Brand Link) — it IS safe in the
  repo. Double-check in RFC before inlining any other value.
- GitHub Actions secrets used by the workflow:
  `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_AUDIT` only; no source-API
  keys are needed because all 3 sources are anonymous.

## Tasks ready for you (in order)

When you first open this repo, these are the work items:

### T1. Seed `scripts/_base.py` + `normalize_png.py`
Helpers every ingest will use. See constraint C3 for shape.

### T2. Implement `enrich_from_arkham.py`
Per entity with `logo_status=none` OR stale, HTTP HEAD
`static.arkhamintelligence.com/entities/<arkham_slug>.png`, on 200
fetch + normalize + write. On 404 / 403, mark `last_fetch_failed`
and try next source.

Rate: 5 req/sec polite, no backoff needed (static bucket).

### T3. Implement `enrich_from_brandfetch.py`
For entities that Arkham 404'd. Use the existing
`BRANDFETCH_CLIENT_ID` from sdn_api/.env. Reject any response with
Content-Type `image/webp` UNLESS it's clearly a brand logo (size
≥ 3 KB and aspect 1:1 after decode — webp lettermark fallbacks are
usually 1-2 KB). When in doubt, reject and move to DefiLlama.

### T4. Implement `enrich_from_defillama.py`
For defi-category entities Arkham + Brandfetch both missed.
`icons.llamao.fi/icons/protocols/<slug>?w=128&h=128` — upscale to
160 via Pillow.

### T5. Implement `scripts/enrich.py` orchestrator
Reads `entities.csv`, sorts by importance DESC, walks the source
chain per row, writes updated CSV + logo at the end. Idempotent.
CLI flags `--max N`, `--category <slug>`, `--dry-run`.

### T6. Write `.github/workflows/enrich-logos.yml`
Cron 02:00 UTC daily. Budget 500 rows/night. Commits as
github-actions[bot] with summary message. Telegram notify on
failure. Cache `pip` install.

### T7. First production run
`gh workflow run enrich-logos.yml --ref main`. Expect ~300 tier-1
PNGs on run 1.

### T8. Update sdn_api + aml_checker consumers
- `sdn_api/public/logos/` → delete, point readers at jsDelivr
- `aml_checker/public/logos/exchanges/` → delete, same
- Add `entityLogoUrl()` helper in both projects — EXACT TS + Python
  source lives in [docs/CONSUMERS.md](docs/CONSUMERS.md). Do NOT
  re-invent the normalization; copy verbatim.
- Add unit tests from CONSUMERS.md — they catch drift if anyone
  edits `SUFFIX_STRIP` / `CATEGORY_TO_DIR` in one project but not
  the other.

### T9. Build + publish `logos/_index.json` as part of enrichment
- Simple addition to `scripts/enrich.py`: after the run, walk `logos/`
  and emit `{"exchanges/binance-com": true, ...}`
- Consumers who want to avoid 404-flash use it via `hasLogo()`
  helper in CONSUMERS.md

### T10. Implement sdn_api side — `scripts/export_entity_registry.py`
- See PROVIDERS.md pseudocode. Gens candidate CSV, fetches live
  registry CSV, merges preserving registry-owned columns, opens PR.
- CLI: `--output FILE`, `--pr` (opens GitHub PR), `--dry-run`.
- Workflow: sdn_api `.github/workflows/export-entity-registry.yml`
  fires Sunday 12:00 UTC.

## What you SHOULD NOT do without asking

- Restructure `logos/<category>/` — consumers' URLs will break.
- Delete rows from `entities.csv` — see C1.
- Add a 5th logo source — update RFC first.
- Commit a logo > 50 KB — run normalize.
- Force-push `main`.
- Introduce a backend / API / database — the whole point is static
  files on GitHub CDN. No server.

## Related docs — MUST read before non-trivial changes

- **[docs/PROVIDERS.md](docs/PROVIDERS.md)** — how upstream projects
  propose fresh CSVs. Column ownership split (who owns what), PR
  review checklist, never-do list (no slug renames, no row
  deletions, no manual touching of logo_* columns).
- **[docs/CONSUMERS.md](docs/CONSUMERS.md)** — the resolver
  contract. If you touch `category_slug` semantics or the name→slug
  normalization, BOTH consumer helpers (TS + Python) must update in
  lockstep OR logos start 404'ing in production.
- RFC: [sdn_api/docs/RFC_entity_registry.md](https://github.com/maslovsa/sdn-api/blob/master/docs/RFC_entity_registry.md)
- Source CSV build: [sdn_api/docs/kyt_entity_registry_v1.csv](https://github.com/maslovsa/sdn-api/blob/master/docs/kyt_entity_registry_v1.csv)
- Sibling projects: sdn_api (provider), aml_checker (consumer)
