"""Build logos/_lookup.json — a fuzzy-match index for consumers.

Consumers (aegis-platform report surfaces, future projects)
often have a freeform label from a verdict or label claim
("Binance Hot Wallet 10", "Uniswap V3 Deposits", "Ronin Bridge Hack")
plus a category slug. They need a URL to the matching logo.

CONSUMERS.md's `entityLogoUrl(category, name)` only works when the
name is already canonical ("Binance.com"). Freeform labels miss.

This script emits a JSON index that lets a ~40-line client-side
resolver do keyword-overlap matching in O(N) per call (N=800 rows;
cheap enough for sub-ms lookups on a precomputed token set).

Shape (intentionally compact — ~80 KB gzipped on the wire):

    {
      "version": 1,
      "generated_at": "YYYY-MM-DD",
      "cdn":          "https://cdn.jsdelivr.net/gh/.../@main",
      "fallback":     "/logos/404.png",
      "category_to_dir": { "exchange": "exchanges", ... },
      "entries": [
        {
          "cat":  "exchange",        // category_slug
          "slug": "binance-com",     // arkham_slug (= filename stem)
          "name": "Binance.com",     // display name
          "kw":   ["binance"],       // lowercase tokens for fuzzy match
          "imp":  100,               // importance, for tiebreaking
          "real": true               // false when status==placeholder
        },
        ...
      ]
    }

Keyword extraction rules — keep in sync with lookup.js / lookup.ts:
  1. For each word in entity_name, lowercased, >= 3 chars, not a
     stopword, not a pure number: add as kw.
  2. arkham_slug with known TLD tails stripped (binance-com -> binance,
     betterbank-io -> betterbank): add if >= 3 chars + not a stopword.
  3. First segment of canonical_domain (binance.com -> binance):
     add if >= 3 chars + not a stopword.
  Deduplicated per row; sorted for stable diffs.

Stopwords deliberately include category-name echoes ("exchange",
"bridge", "protocol", etc.) — they would otherwise match every row
in a category and blow up false-positive counts.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _base import (  # type: ignore[import-not-found]
    CATEGORY_TO_DIR,
    LOGOS_DIR,
    Row,
    read_entities,
)

CDN_BASE = "https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main"
FALLBACK_URL = "/logos/404.png"
LOOKUP_PATH = LOGOS_DIR / "_lookup.json"

# Tokens too generic to be useful on their own — they would match
# most rows in a category and ruin the keyword-overlap score.
_STOPWORDS = frozenset({
    # brand noise that's also in entity_name suffix_strip
    "network", "protocol", "finance", "labs", "foundation", "dao",
    "pool", "swap", "exchange",
    # category echoes
    "bridge", "defi", "dex", "mixer", "wallet", "hack",
    "sanctioned", "gambling", "mining", "bot", "psp", "rekt",
    # TLDs / URL fragments that sneak into domain parsing
    "com", "net", "org", "xyz", "app", "fi",
    # generic English
    "the", "and", "for", "inc", "ltd", "llc", "fund", "group",
    "labs", "team",
})

def _camel_expand(text: str) -> str:
    """Expand CamelCase: 'YearnFinance' → 'Yearn Finance'.
    Must stay in sync with labelTokens() in lookup.js / lookup.ts."""
    text = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return text


def _keywords(row: Row) -> list[str]:
    kws: set[str] = set()

    def consider(token: str) -> None:
        t = token.lower().strip()
        if len(t) < 3:
            return
        if t in _STOPWORDS:
            return
        if t.isdigit():
            return
        kws.add(t)

    # 1. Each word in the entity_name, with CamelCase expansion so
    #    "YearnFinance" → ["yearn", "finance"] and "OnyxProtocol" →
    #    ["onyx", "protocol"] (protocol is a stopword, so only "onyx"
    #    survives). Must match labelTokens() in lookup.js / lookup.ts.
    expanded_name = _camel_expand(row.entity_name or "")
    for w in re.split(r"[^a-z0-9]+", expanded_name.lower()):
        consider(w)

    # 2. Every alphanumeric segment of arkham_slug, treated as a
    #    separate keyword. "alphapo-rekt" -> ["alphapo", "rekt"];
    #    "rekt" is dropped by the stopword filter. "htx-com-huobi-com"
    #    -> ["htx", "huobi"]. We don't keep the compound slug itself
    #    as a kw — no reviewer label ever contains a dashed slug
    #    verbatim, and compound kws only dilute the score.
    #
    #    Special case: two-letter entity abbreviations like "XT" produce
    #    no usable keywords from segment splitting (len < 3 filter). For
    #    such entries we also emit the domain-concatenated form:
    #    "xt-com" slug + "xt.com" domain → "xtcom" (4 chars, matches
    #    label "XT.com" when the caller strips the dot).
    if row.arkham_slug:
        slug_segments = row.arkham_slug.split("-")
        for seg in slug_segments:
            consider(seg)
        # domain-concatenated fallback for short-abbreviation domains
        if row.canonical_domain:
            joined = re.sub(r"\.", "", row.canonical_domain.lower())  # "xt.com" → "xtcom"
            if len(joined) >= 4 and joined not in _STOPWORDS:
                consider(joined)

    # 3. first segment of canonical_domain
    if row.canonical_domain:
        consider(row.canonical_domain.split(".", 1)[0])

    return sorted(kws)


def build(rows: list[Row]) -> dict:
    real_statuses = {"arkham", "brandfetch", "defillama", "favicon", "manual"}
    entries: list[dict] = []
    for r in rows:
        if r.category_slug not in CATEGORY_TO_DIR:
            continue
        if not r.arkham_slug:
            continue
        entries.append({
            "cat":  r.category_slug,
            "slug": r.arkham_slug,
            "name": r.entity_name,
            "kw":   _keywords(r),
            "imp":  r.importance,
            "real": r.logo_status in real_statuses,
        })
    # Sort by importance desc, then name — same order the enrichment
    # cron uses; keeps the resolver's "pick highest importance on tie"
    # cheap (first hit wins).
    entries.sort(key=lambda e: (-e["imp"], e["name"].lower()))

    return {
        "version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).date().isoformat(),
        "cdn": CDN_BASE,
        "fallback": FALLBACK_URL,
        "category_to_dir": dict(CATEGORY_TO_DIR),
        "entries": entries,
    }


def emit(rows: list[Row], dry_run: bool = False) -> int:
    payload = build(rows)
    if dry_run:
        return len(payload["entries"])
    # Compact format — index is re-fetched per session by clients; save
    # every byte. No trailing newline: browser JSON.parse() accepts both.
    LOOKUP_PATH.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=False),
        encoding="utf-8",
    )
    return len(payload["entries"])


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = read_entities()
    n = emit(rows, dry_run=args.dry_run)
    if args.dry_run:
        print(f"would write {LOOKUP_PATH.relative_to(LOGOS_DIR.parent)} ({n} entries)")
    else:
        print(f"wrote {LOOKUP_PATH.relative_to(LOGOS_DIR.parent)} ({n} entries, "
              f"{LOOKUP_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
