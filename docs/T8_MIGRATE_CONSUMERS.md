# T8 — Migrate aegis-platform consumers to jsDelivr CDN

Self-contained prompt for a Claude Code session in the aegis-platform
repo. Copy-paste this as a first message or drop it into CLAUDE.md
task queue.

---

## Context

Entity logos used to live as local SVG copies inside aegis-platform
(`apps/ui/public/logos/exchanges/*.svg`). They have been superseded
by the **kyt-entity-registry** — a public GitHub repo served via
jsDelivr CDN with 1200+ normalised 160×160 PNG logos, a manifest-
driven badge detector, and a fuzzy keyword resolver.

The CDN integration is **already wired up** — `entity-registry.ts`
fetches the manifest, `exchange-logos.ts` delegates to
`entryLogoUrl()`, and CSP allows `img-src https:`. What remains is
cleanup: removing local SVG fallback files that are now redundant,
fixing one stale cross-reference, and verifying nothing regresses.

## What to do

### Phase 1 — Remove local exchange SVGs (safe, no UX change)

The 23 SVGs in `apps/ui/public/logos/exchanges/` are only reached
when the CDN returns 404 (offline or brand not in the registry). All
23 brands now have real PNG logos in kyt-entity-registry, so the
fallback never fires in production.

1. **Delete the files** (keep the README.md if useful, otherwise
   delete too):

   ```
   apps/ui/public/logos/exchanges/abcex.svg
   apps/ui/public/logos/exchanges/binance.svg
   apps/ui/public/logos/exchanges/bingx.svg
   apps/ui/public/logos/exchanges/bitfinex.svg
   apps/ui/public/logos/exchanges/bitget.svg
   apps/ui/public/logos/exchanges/bitstamp.svg
   apps/ui/public/logos/exchanges/bybit.svg
   apps/ui/public/logos/exchanges/coinbase.svg
   apps/ui/public/logos/exchanges/cryptocom.svg
   apps/ui/public/logos/exchanges/garantex.svg
   apps/ui/public/logos/exchanges/gate.svg
   apps/ui/public/logos/exchanges/gemini.svg
   apps/ui/public/logos/exchanges/grinex.svg
   apps/ui/public/logos/exchanges/htx.svg
   apps/ui/public/logos/exchanges/keysecure.svg
   apps/ui/public/logos/exchanges/kraken.svg
   apps/ui/public/logos/exchanges/kucoin.svg
   apps/ui/public/logos/exchanges/lbank.svg
   apps/ui/public/logos/exchanges/mexc.svg
   apps/ui/public/logos/exchanges/moscaex.svg
   apps/ui/public/logos/exchanges/okx.svg
   apps/ui/public/logos/exchanges/rapira.svg
   apps/ui/public/logos/exchanges/whitebit.svg
   ```

2. **Update `exchangeLogoLocalFallback()`** in
   `apps/ui/src/lib/graph/exchange-logos.ts:140-142`:

   The function currently returns `/logos/exchanges/${cfg.slug}.svg`.
   Since the files are gone, either:
   - (a) Return the CDN fallback URL instead:
     ```ts
     export function exchangeLogoLocalFallback(cfg: { slug: string }): string {
       return `${ENTITY_REGISTRY_CDN}/logos/_fallback/unknown.png`
     }
     ```
   - (b) Or delete the function entirely and update call sites to use
     `fallbackLogoUrl()` from `logo-url.ts`. Grep for
     `exchangeLogoLocalFallback` to find all callers.

   Option (a) is simpler. Option (b) is cleaner long-term.

3. **Check `vasp-dashboard-client.tsx:153`** — comment mentions
   "local /public/logos/exchanges/<slug>.svg (CIS legacy fallback)".
   The 3-tier fallback there should still work if step 2a was chosen
   (CDN URL instead of local path). Verify the component renders.

### Phase 2 — Fix stale cross-reference

In `apps/ui/src/lib/entities/logo-url.ts:10`, the docstring says:

```
keep it drift-free with the Python twin in `sdn_api/api/lib/entity_logo.py`
```

Replace with:

```
keep it drift-free with the Python twin in kyt-entity-registry/docs/CONSUMERS.md
```

The Python helper source of truth is now in the registry's
CONSUMERS.md, not in the old sdn_api repo.

### Phase 3 — AML provider logos (keep local, no migration)

These logos in `apps/ui/public/logos/` are NOT entity logos — they
are vendor brand marks for the AML provider selector UI:

```
bitok.png        — BitOK provider badge
scorechain.svg   — ScoreChain provider badge
scorechain.png   — (duplicate, can delete if unused)
crystal.svg      — Crystal provider badge
elliptic.png     — Elliptic provider badge
ofac.png         — OFAC SDN historical badge
aegis.svg        — Aegis brand (used by sidebar/header)
aegis-color.svg  — Aegis brand (colour variant)
```

These are **NOT** part of kyt-entity-registry (which covers crypto
entities, not AML tool vendors). Leave them as local assets.

The `providerLogo()` function in `apps/ui/src/lib/provider-logo.ts`
references these — no changes needed there.

## Files to touch (complete list)

| File | Action |
|------|--------|
| `apps/ui/public/logos/exchanges/*.svg` (23 files) | Delete |
| `apps/ui/public/logos/exchanges/README.md` | Delete or keep |
| `apps/ui/src/lib/graph/exchange-logos.ts` | Update `exchangeLogoLocalFallback()` |
| `apps/ui/src/lib/entities/logo-url.ts` | Fix docstring (sdn_api → registry) |
| `apps/ui/src/components/admin/vasp-dashboard-client.tsx` | Verify fallback still renders |

## Files NOT to touch

| File | Why |
|------|-----|
| `apps/ui/src/lib/graph/entity-registry.ts` | Already correct — fetches manifest from CDN |
| `apps/ui/src/lib/graph/exchange-logos.ts` (rest) | `exchangeLogoUrl()` already delegates to CDN |
| `apps/ui/src/lib/provider-logo.ts` | AML vendor logos, not entity logos |
| `apps/ui/public/logos/bitok.png` etc. | AML vendor assets, stay local |
| `apps/ui/src/lib/graph/exchange-badge-styles.ts` | Style config only, no URL logic |

## Verification

1. Run existing tests:
   ```bash
   npx vitest run tests/unit/exchange-logos.test.ts
   npx vitest run tests/unit/entity-logo-url.test.ts
   npx vitest run tests/unit/entity-logo-badge.test.ts
   npx vitest run tests/unit/exchange-logos-batch-2026-04-29.test.ts
   ```

2. Start the dev server and check:
   - Graph view: entity badges render with CDN logos
   - KYT page: exchange logos appear next to labels
   - VASP dashboard: exchange logos in the list render
   - AML policy page: BitOK / ScoreChain logos still appear
   - Admin API settings: provider logos render correctly

3. Verify the CDN fallback works by temporarily blocking
   `cdn.jsdelivr.net` in DevTools Network tab — badges should
   degrade gracefully (no broken image icons).

## Commit message

```
cleanup: remove local exchange SVGs, point fallback at CDN

All 23 exchange logos now live in kyt-entity-registry and are served
via jsDelivr CDN. The local SVG fallback in /public/logos/exchanges/
is no longer needed — exchangeLogoLocalFallback() now returns the
CDN fallback glyph. AML provider logos (BitOK, ScoreChain, etc.)
remain as local assets — they are not entity logos.
```
