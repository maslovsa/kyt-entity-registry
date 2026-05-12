# CONSUMERS — how downstream projects resolve logos

Audience: UIs and reports that render per-entity logos. Today:
aegis-platform (Next.js + React UI and backend report surfaces);
tomorrow: any project that needs "the Binance logo" or "the Tornado
Cash seal".

## The one thing consumers do

Given **(category_slug, entity_name)** from an Aegis verdict or a label
claim, produce a URL that returns a 160×160 PNG.

```
entityLogoUrl('exchange', 'Binance.com')
  → "https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/exchanges/binance-com.png"
```

That's it. No backend call. No SDK. No npm package.

## Resolution rules (exact)

1. **Directory** = category_slug with ONE plural rule:
   `exchange → exchanges`. Everything else 1:1. Unknown category →
   route to `_fallback/unknown.png`.

2. **Filename** = `entity_name.toLowerCase()`, then:
   - strip these suffixes: ` Network`, ` Exchange`, ` Protocol`,
     ` Finance`, ` Labs`, ` Foundation`, ` DAO`, ` Pool`, ` Swap`
   - collapse whitespace and any non-alphanumeric to single `-`
   - strip leading/trailing `-`
   - if empty after normalization → `_fallback/unknown.png`

3. **CDN host**:
   - app UI (live, auto-updating) → `cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main`
   - compliance export / PDF → `cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@<git-sha>`

4. **Error handling**: browser 404 → set `src = _fallback/unknown.png`.

## TypeScript helper (drop-in)

Ship this exact file in every TS consumer. Keeps the normalization
identical across projects — drift is a bug.

```ts
// src/lib/entities/logo-url.ts

export const ENTITY_REGISTRY_CDN =
  'https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main'

/** Category slug as it appears in entities.csv / Aegis verdicts →
 *  the logos/ subdirectory name. Only `exchange → exchanges` differs. */
const CATEGORY_TO_DIR: Record<string, string> = {
  exchange:         'exchanges',
  dex:              'dex',
  bridge:           'bridge',
  defi:             'defi',
  wallet:           'wallet',
  mining:           'mining',
  psp:              'psp',
  bot:              'bot',
  gambling:         'gambling',
  nft_marketplace: 'nft_marketplace',
  mixer:            'mixer',
  hack:             'hack',
  sanctioned:       'sanctioned',
  custodian:        'custodian',
}

const SUFFIX_STRIP = [
  ' network', ' exchange', ' protocol', ' finance',
  ' labs', ' foundation', ' dao', ' pool', ' swap',
] as const

/** Normalize a raw entity_name string into the registry's filename slug.
 *  Pure function; identical output across language implementations. */
export function entitySlug(entityName: string): string {
  let s = (entityName ?? '').toLowerCase().trim()
  for (const suf of SUFFIX_STRIP) {
    if (s.endsWith(suf)) {
      s = s.slice(0, -suf.length).trim()
      break
    }
  }
  s = s.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
  return s
}

/** Resolve (category_slug, entity_name) → absolute CDN URL.
 *  Unknown category OR empty-after-slug → fallback URL. */
export function entityLogoUrl(category: string, entityName: string): string {
  const dir = CATEGORY_TO_DIR[category]
  const slug = entitySlug(entityName)
  if (!dir || !slug) return fallbackLogoUrl()
  return `${ENTITY_REGISTRY_CDN}/logos/${dir}/${slug}.png`
}

export function fallbackLogoUrl(): string {
  return `${ENTITY_REGISTRY_CDN}/logos/_fallback/unknown.png`
}
```

### React usage

```tsx
import Image from 'next/image'
import { entityLogoUrl, fallbackLogoUrl } from '@/lib/entities/logo-url'

export function EntityLogo({
  category, entityName, size = 32,
}: {
  category: string
  entityName: string
  size?: number
}) {
  return (
    <img
      src={entityLogoUrl(category, entityName)}
      alt={entityName}
      width={size} height={size}
      loading="lazy"
      onError={e => {
        const el = e.currentTarget as HTMLImageElement
        if (!el.dataset.fellBack) {
          el.dataset.fellBack = '1'
          el.src = fallbackLogoUrl()
        }
      }}
      className="rounded-full bg-white"
    />
  )
}
```

### Unit test (keep drift-free)

```ts
import { entitySlug, entityLogoUrl } from './logo-url'

describe('entitySlug', () => {
  it('lowercases + slugifies', () => {
    expect(entitySlug('Binance.com')).toBe('binance-com')
    expect(entitySlug('Htx.com - Huobi.com')).toBe('htx-com-huobi-com')
    expect(entitySlug('1inch Network')).toBe('1inch')        // strips " Network"
    expect(entitySlug('Aave')).toBe('aave')
    expect(entitySlug('Tornado Cash')).toBe('tornado-cash')
  })
  it('returns empty for junk', () => {
    expect(entitySlug('')).toBe('')
    expect(entitySlug('   ')).toBe('')
  })
})

describe('entityLogoUrl', () => {
  const CDN = 'https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main'
  it('maps exchange to exchanges', () => {
    expect(entityLogoUrl('exchange', 'Binance.com'))
      .toBe(`${CDN}/logos/exchanges/binance-com.png`)
  })
  it('passes through 1:1 categories', () => {
    expect(entityLogoUrl('dex', 'Uniswap'))
      .toBe(`${CDN}/logos/dex/uniswap.png`)
  })
  it('falls back on unknown category', () => {
    expect(entityLogoUrl('something_new', 'Foo'))
      .toBe(`${CDN}/logos/_fallback/unknown.png`)
  })
})
```

## Python helper (backend renders, PDF exports)

```python
# aegis-platform: api/lib/entity_logo.py

ENTITY_REGISTRY_CDN = (
    "https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main"
)

_CATEGORY_TO_DIR = {
    "exchange":        "exchanges",
    "dex":             "dex",
    "bridge":          "bridge",
    "defi":            "defi",
    "wallet":          "wallet",
    "mining":          "mining",
    "psp":             "psp",
    "bot":             "bot",
    "gambling":        "gambling",
    "nft_marketplace": "nft_marketplace",
    "mixer":           "mixer",
    "hack":            "hack",
    "sanctioned":      "sanctioned",
    "custodian":       "custodian",
}

_STRIP_SUFFIXES = [
    " network", " exchange", " protocol", " finance",
    " labs", " foundation", " dao", " pool", " swap",
]

import re


def entity_slug(entity_name: str) -> str:
    s = (entity_name or "").lower().strip()
    for suf in _STRIP_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
            break
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def entity_logo_url(category: str, entity_name: str,
                    ref: str = "main") -> str:
    """Resolve to the logo CDN URL. Pass ref='<git-sha>' for a pinned
    compliance snapshot URL."""
    cdn = ENTITY_REGISTRY_CDN.replace("@main", f"@{ref}") if ref != "main" \
        else ENTITY_REGISTRY_CDN
    d = _CATEGORY_TO_DIR.get(category)
    slug = entity_slug(entity_name)
    if not d or not slug:
        return f"{cdn}/logos/_fallback/unknown.png"
    return f"{cdn}/logos/{d}/{slug}.png"
```

## Does the file actually exist? — optional existence check

The resolver returns a URL no matter what; jsDelivr responds 404 if
the PNG isn't there, and the browser's `onError` swaps to fallback.
For most UIs that's enough.

If a consumer wants to know *without* a round-trip whether a logo
exists — say, to decide between showing a logo-chip vs a text-only
badge — fetch the registry index once per session:

```ts
// Fetched once per session, cached in memory.
const indexUrl = `${ENTITY_REGISTRY_CDN}/logos/_index.json`
// Shape: { "exchanges/binance-com": true, "dex/uniswap": true, ... }
const logoIndex: Record<string, true> = await (await fetch(indexUrl)).json()

export function hasLogo(category: string, entityName: string): boolean {
  const dir = CATEGORY_TO_DIR[category]
  const slug = entitySlug(entityName)
  return !!logoIndex[`${dir}/${slug}`]
}
```

`_index.json` is regenerated as part of the nightly enrichment cron.
Until it ships, consumers use `<img onError>` — same UX, one wasted
404 per miss, acceptable.

## Fuzzy resolver — matching a freeform label to a logo

`entityLogoUrl(category, entityName)` above assumes the caller
already has a canonical name (`"Binance.com"`, `"Uniswap"`). Real
consumers usually have a **freeform label** from a verdict or
address annotation: `"Binance Hot Wallet 10"`, `"Uniswap V3
Deposits"`, `"Ronin Bridge Hack"`. Those don't hit the canonical
resolver.

`logos/_lookup.json` + `lookup.js` solve this with keyword-overlap
matching: each entity carries a small list of pre-extracted
keywords (lowercase alphanumeric tokens, >= 3 chars, not a
stopword). A freeform label is tokenized the same way; score =
size of the intersection. Ties broken by `imp` (importance) then
by `real` (real logo beats placeholder).

### JS / TS — drop-in

```ts
import { createLookup } from 'https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/lookup.js'

// One fetch per session — the module caches internally.
const lookup = await createLookup()

const hit = lookup.resolve({ category: 'dex', label: 'Uniswap V3 Deposits' })
//  -> { url: 'https://.../logos/dex/uniswap.png',
//       slug: 'uniswap', name: 'Uniswap',
//       category: 'dex', real: true, importance: 100 }

const miss = lookup.resolve({ category: 'dex', label: 'nonsense xyz 42' })
//  -> null
```

`createLookup({ url })` accepts a pinned CDN URL for compliance
snapshots: `…/gh/maslovsa/kyt-entity-registry@<sha>/logos/_lookup.json`.

### React usage (aegis-platform pattern)

```tsx
import { useEffect, useState } from 'react'
import { createLookup } from '…/lookup.js'
// or the TypeScript port at src/lib/entities/lookup.ts

let _lookupPromise: Promise<Awaited<ReturnType<typeof createLookup>>> | null
function getLookup() { return _lookupPromise ??= createLookup() }

export function EntityLogo({ category, label, size = 20 }: {
  category: string; label: string; size?: number
}) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    getLookup().then(l => {
      if (cancelled) return
      const hit = l.resolve({ category, label })
      setUrl(hit?.real ? hit.url : null)  // only show REAL hits
    })
    return () => { cancelled = true }
  }, [category, label])
  if (!url) return null
  return <img src={url} width={size} height={size} alt={label}
              className="rounded-full bg-white" />
}
```

### Python twin (for server-side rendering / PDF exports)

```python
# pip install httpx (already in kyt-entity-registry/requirements.txt)
import functools, re
import httpx

_CDN = "https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main"

@functools.lru_cache(maxsize=1)
def _lookup():
    return httpx.get(f"{_CDN}/logos/_lookup.json", timeout=10).json()

_TOKEN_RE = re.compile(r"[^a-z0-9]+")

def _tokens(label: str) -> set[str]:
    return {t for t in _TOKEN_RE.split((label or "").lower())
            if len(t) >= 3 and not t.isdigit()}

def resolve_entity_logo(category: str | None, label: str,
                        prefer_real: bool = True) -> str | None:
    """Return the CDN URL of the best-matching logo, or None."""
    tokens = _tokens(label)
    if not tokens: return None
    idx = _lookup()
    dirs = idx["category_to_dir"]
    best, best_score = None, 0
    for e in idx["entries"]:
        if category and e["cat"] != category: continue
        score = sum(1 for k in e["kw"] if k in tokens)
        if score == 0: continue
        effective = score + (0.5 if prefer_real and e["real"] else 0)
        if effective > best_score:
            best, best_score = e, effective
    if not best: return None
    return f"{idx['cdn']}/logos/{dirs[best['cat']]}/{best['slug']}.png"
```

### Keyword extraction rules (for reference)

Every entry's `kw` field is built from:

1. Each alphanumeric token of `entity_name`, lowercased, len >= 3,
   non-numeric, not in the stopword set.
2. Each alphanumeric segment of `arkham_slug` under the same
   filters (so `"alphapo-rekt"` contributes `["alphapo"]` — `"rekt"`
   is a stopword).
3. The first segment of `canonical_domain` (`"binance.com"` →
   `"binance"`).

Stopwords (exact-match, lowercased): `network`, `protocol`,
`finance`, `labs`, `foundation`, `dao`, `pool`, `swap`, `exchange`,
`bridge`, `defi`, `dex`, `mixer`, `wallet`, `hack`, `sanctioned`,
`gambling`, `mining`, `bot`, `psp`, `rekt`, `com`, `net`, `org`,
`xyz`, `app`, `fi`, `the`, `and`, `for`, `inc`, `ltd`, `llc`,
`fund`, `group`, `team`.

These are excluded because they match nearly every row in a
category (e.g. `network` appears in most DeFi protocols) and
would dominate the score with false positives.

If you add a consumer in a new language, copy the same list
verbatim — keeping the rules in sync is mandatory, otherwise your
resolver will pick a different "best" entry than the TS / Python
twin.

## Compliance / PDF snapshots — pinning to SHA

When generating a compliance PDF or long-lived archive:

```ts
// Capture once at report-generation time
const pinnedSha = await fetch(
  'https://api.github.com/repos/maslovsa/kyt-entity-registry/commits/main',
).then(r => r.json()).then(r => r.sha)

// Use that SHA for every logo URL in the PDF
const logoUrl = `https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@${pinnedSha}/logos/exchanges/binance-com.png`
```

A year later, opening that PDF still renders the Binance logo from
that exact commit — even if the registry has since updated to a
newer Binance logo.

The Python helper takes a `ref` parameter for this (`entity_logo_url(..., ref=sha)`).

## Gotchas

1. **jsDelivr cache TTL is 12-24 h**. If you manually purged a logo on
   the registry side, give it up to a day before consumer UIs see
   the new asset. For urgent fixes:
   `curl "https://purge.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/exchanges/binance-com.png"`

2. **Category drift**. If you coin a new category_slug in Aegis,
   update `_CATEGORY_TO_DIR` in every consumer AND update the
   registry's allowed-categories list (in `PROVIDERS.md`). Add a
   compat shim: unknown categories route to `_fallback` until the
   registry picks them up.

3. **Importance isn't visible to consumers**. The registry doesn't
   expose "how important is Binance" via CDN — that's editorial
   metadata for the enrichment cron only. Consumers just ask
   `entityLogoUrl(cat, name)` and get a URL.

4. **Name normalization is load-bearing.** The Python + TS helpers
   MUST produce identical slugs on identical input. Keep the unit
   tests in sync. If a consumer needs a different transform (e.g.
   specialized domain-name handling), add a wrapper — don't
   fork `entitySlug`.
