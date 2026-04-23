/**
 * kyt-entity-registry — fuzzy logo resolver (vanilla JS / TypeScript-safe).
 *
 * Usage:
 *
 *   import { createLookup } from 'https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/lookup.js'
 *
 *   const lookup = await createLookup()       // fetches _lookup.json once, caches
 *   const hit = lookup.resolve({ category: 'dex', label: 'Uniswap V3 Deposits' })
 *   //  -> { url: '<cdn>/logos/dex/uniswap.png', slug: 'uniswap', name: 'Uniswap', real: true }
 *
 *   // Freeform: no category filter, fall back to best overall match
 *   lookup.resolve({ label: 'Ronin Bridge Hack' })
 *   //  -> hack/ronin-network-rekt
 *
 * Design:
 *   * Index is ~80 KB. Fetch once per session, cache in module scope.
 *   * Matching = keyword-overlap score. Each entry has pre-extracted
 *     lowercase keywords (see scripts/build_lookup.py). Label is
 *     tokenized the same way; score = |label_tokens ∩ entry.kw|.
 *   * Ties broken by `imp` (importance, higher wins) then by `real`
 *     (real logo wins over placeholder-only entries).
 *   * When category is passed we filter the candidate set first;
 *     without it we match across all categories.
 *   * Never throws — misses return null. A falling-back consumer can
 *     then decide whether to render nothing, the fallback glyph, or
 *     some category-specific default.
 */

const DEFAULT_INDEX_URL =
  'https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/_lookup.json';

let _indexPromise = null;

/**
 * Tokenize a freeform label to the same shape `build_lookup.py` uses.
 *
 * Includes CamelCase expansion so compound identifiers like
 * "YearnFinance" and "OnyxProtocol" produce individual keyword tokens
 * ("yearn", "onyx") that match entity entries. Must stay in sync with
 * the TS twin in aml_checker/src/lib/entities/lookup.ts and with the
 * _keywords() function in scripts/build_lookup.py.
 */
export function labelTokens(label) {
  if (!label) return new Set();
  const out = new Set();
  const s = String(label);
  // CamelCase expansion: "YearnFinance" → "Yearn Finance"
  const expanded = s
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2');
  for (const t of expanded.toLowerCase().split(/[^a-z0-9]+/)) {
    if (t.length >= 3 && !/^\d+$/.test(t)) out.add(t);
  }
  // Domain-join: "XT.com" → also emit "xtcom" so short 2-letter
  // abbreviations can match. Must stay in sync with build_lookup.py
  // and lookup.ts.
  if (!s.includes(' ') && s.includes('.')) {
    const joined = s.toLowerCase().replace(/\./g, '');
    if (joined.length >= 4 && /^[a-z0-9]+$/.test(joined)) out.add(joined);
  }
  return out;
}

/**
 * Load the lookup index once per tab and cache it. Pass a custom
 * `url` when pinning to a git SHA for compliance snapshots. The
 * returned helper exposes `resolve` and `has`.
 */
export function createLookup({ url = DEFAULT_INDEX_URL } = {}) {
  if (_indexPromise && _indexPromise._url === url) return _indexPromise;
  _indexPromise = (async () => {
    const r = await fetch(url, { cache: 'default' });
    if (!r.ok) throw new Error(`lookup fetch ${r.status}`);
    const idx = await r.json();
    return makeResolver(idx);
  })();
  _indexPromise._url = url;
  return _indexPromise;
}

/** Build a resolver instance from an already-loaded index object.
 *  Exposed so tests can inject a fixture without hitting the network. */
export function makeResolver(index) {
  const { cdn, fallback, category_to_dir, entries } = index;

  /** Build the absolute logo URL for a given (category, slug). */
  function urlFor(category, slug) {
    const dir = category_to_dir[category];
    if (!dir || !slug) return cdn + fallback;
    return `${cdn}/logos/${dir}/${slug}.png`;
  }

  /** Best-match candidate for a {category, label} pair, or null. */
  function resolve({ category, label, preferReal = true } = {}) {
    const tokens = labelTokens(label);
    if (tokens.size === 0) return null;

    let best = null;
    let bestScore = 0;
    for (const e of entries) {
      if (category && e.cat !== category) continue;
      let score = 0;
      for (const k of e.kw) if (tokens.has(k)) score++;
      if (score === 0) continue;

      // Entries are already sorted by (imp desc, name asc) in the
      // index, so the FIRST entry with a given score wins the
      // importance tiebreaker naturally. `real` beats placeholder
      // even at a slightly lower score when preferReal is on —
      // callers almost always want a real brand mark.
      const realBoost = preferReal && e.real ? 0.5 : 0;
      const effective = score + realBoost;
      if (effective > bestScore) {
        best = e;
        bestScore = effective;
      }
    }
    if (!best) return null;
    return {
      slug: best.slug,
      name: best.name,
      category: best.cat,
      real: best.real,
      importance: best.imp,
      url: urlFor(best.cat, best.slug),
    };
  }

  /** Existence check without constructing the URL. */
  function has({ category, slug }) {
    for (const e of entries) {
      if (e.cat === category && e.slug === slug) return true;
    }
    return false;
  }

  return { resolve, has, urlFor, fallbackUrl: cdn + fallback, entries, cdn };
}
