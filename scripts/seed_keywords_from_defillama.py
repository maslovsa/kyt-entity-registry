"""Seed `keywords` and `canonical_domain` for dex/defi/bridge/mining rows.

Uses DeFiLlama protocols list as the primary reference:
  1. Fetch https://api.llama.fi/protocols  (~7 400 protocols)
  2. For each target row with empty keywords:
       a. Try normalized-name match → DeFiLlama entry
       b. Fall back to slug-derived keyword (strips domain TLDs + generic suffixes)
  3. Write keywords (+ canonical_domain when currently empty and DeFiLlama has a url)

Rules:
  - NEVER overwrites existing keywords (only fills blanks)
  - NEVER touches logo_status / logo_hash / manual_lock
  - Skips rows in blocklist (generic, ambiguous, internal-tool slugs)
  - After writing: run `python3 scripts/generate_manifest.py` to rebuild manifest

USAGE
  # Preview what would change
  python3 scripts/seed_keywords_from_defillama.py --input entities.csv --dry-run

  # Write changes
  python3 scripts/seed_keywords_from_defillama.py --input entities.csv --output entities.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

# ─── Configuration ────────────────────────────────────────────────────────────

# Categories we seed keywords for.
TARGET_CATEGORIES = {"dex", "defi", "bridge", "mining"}

# Slugs that should never get auto-generated keywords.
# Generic / ambiguous / not real branded entities.
SKIP_SLUGS = {
    "multiple-dexs",
    "multiple-cexs",
    "multiple-bridges",
    "other",
    "unknown",
    "scorechain",   # AML tool, not a DeFi protocol
}

DEFILLAMA_API = "https://api.llama.fi/protocols"

# DeFiLlama category → our category_slug mapping.
CATEGORY_MAP: dict[str, str] = {
    "Dexs": "dex",
    "DEX Aggregator": "dex",
    "Dexes": "dex",
    "Lending": "defi",
    "Yield": "defi",
    "Yield Aggregator": "defi",
    "CDP": "defi",
    "Liquid Staking": "defi",
    "Derivatives": "defi",
    "Farm": "defi",
    "Algo-Stables": "defi",
    "Reserve Currency": "defi",
    "RWA": "defi",
    "Leveraged Farming": "defi",
    "Prediction Market": "defi",
    "Options": "defi",
    "NFT Marketplace": "nft_marketplace",
    "Bridge": "bridge",
    "Cross Chain Bridge": "bridge",
    "Canonical Bridge": "bridge",
    "Mining": "mining",
    "Staking Pool": "mining",
}

# ─── Normalisation helpers ────────────────────────────────────────────────────

_RE_VERSION    = re.compile(r'\s+v\d+(\.\d+)?(\s|$)', re.I)
_RE_PARENS     = re.compile(r'\s*\([^)]+\)')
_RE_GENERICS   = re.compile(
    r'\s+(protocol|finance|network|exchange|dex|aggregator|platform|dao|'
    r'labs?|app|solutions?)\s*$', re.I
)
_RE_DOTS       = re.compile(r'[.,/]')
_RE_SPACES     = re.compile(r'\s+')

def _normalize_name(s: str) -> str:
    s = _RE_VERSION.sub(' ', s)
    s = _RE_PARENS.sub('', s)
    s = _RE_GENERICS.sub('', s)
    s = _RE_DOTS.sub(' ', s)
    return _RE_SPACES.sub(' ', s).lower().strip()


# Only strip real domain TLDs and truly generic word suffixes from slugs.
_RE_SLUG_TLD     = re.compile(r'-(com|io|fi|xyz|org|net|app)$', re.I)
_RE_SLUG_GENERIC = re.compile(r'-(finance|protocol|network|labs?|dao|v\d+)$', re.I)

def _slug_to_keyword(slug: str) -> Optional[str]:
    """Derive a base keyword from an arkham_slug.

    Strips domain TLDs (`.com`, `.fi`, …) and generic word suffixes
    (`-finance`, `-network`, …) iteratively. Returns None when the
    result is too short to be a useful keyword.
    """
    s = slug.lower().strip()
    # TLD pass
    prev = None
    while s != prev:
        prev = s
        s = _RE_SLUG_TLD.sub('', s).strip('-')
    # Generic word pass
    prev = None
    while s != prev:
        prev = s
        s = _RE_SLUG_GENERIC.sub('', s).strip('-')
    # Reject too-short or empty results (except known short brands like "1inch")
    if not s or (len(s) < 3 and not re.match(r'^\d', s)):
        return None
    return s


def _domain_from_url(url: str) -> Optional[str]:
    """Extract bare domain (no www) from a URL string."""
    if not url:
        return None
    try:
        parsed = urlparse(url if url.startswith('http') else 'https://' + url)
        host = parsed.netloc or parsed.path.split('/')[0]
        return host.lstrip('www.').lower().strip() or None
    except Exception:
        return None


# ─── Keyword building ─────────────────────────────────────────────────────────

_RE_KW_VERSION  = re.compile(r'\s+v\d+(\.\d+)?(\s|$)', re.I)
_RE_KW_PARENS   = re.compile(r'\s*\([^)]+\)')
_RE_KW_GENERICS = re.compile(
    # NOTE: 'dex' intentionally excluded — it's often a product differentiator
    # (e.g. "OKX Dex" vs "OKX" exchange).  Same for 'bridge' and 'swap'.
    r'\s+(protocol|finance|network|aggregator|platform|dao|'
    r'labs?|app|solutions?)\s*$', re.I
)

def _name_to_primary_keyword(name: str) -> Optional[str]:
    """Extract primary keyword from entity_name, preserving dots (for 'curve.fi' etc.).

    Strips version suffixes and generic word suffixes, but keeps internal
    punctuation like dots (important for .fi / .io branded names).
    """
    s = name.strip()
    # Split on " - " (e.g. "Kyber.network - Kyberswap") → take the last part
    if ' - ' in s:
        s = s.split(' - ')[-1].strip()
    s = _RE_KW_VERSION.sub(' ', s)
    s = _RE_KW_PARENS.sub('', s)
    s = _RE_KW_GENERICS.sub('', s)
    s = re.sub(r'\s+', ' ', s).lower().strip()
    return s if s and len(s) >= 2 else None


def _build_keywords(row: dict, dl_entry: Optional[dict]) -> list[str]:
    """Return a de-duplicated list of keyword candidates.

    Primary:  entity_name stripped of version/generic (dots preserved)
    Secondary: slug-derived keyword (shorter, no dots)
    DeFiLlama extras: gecko_id
    """
    candidates: list[str] = []

    name = row.get("entity_name", "")
    slug = row.get("arkham_slug", "")

    # 1. Primary: name-derived, dots preserved (e.g. "curve.fi")
    primary = _name_to_primary_keyword(name)
    if primary:
        candidates.append(primary)

    # 2. Slug-derived (shorter, no dots — e.g. "curve" from "curve-fi")
    kw_slug = _slug_to_keyword(slug)
    if kw_slug and kw_slug != primary and kw_slug not in candidates:
        candidates.append(kw_slug)

    # 3. DeFiLlama-enriched extras
    if dl_entry:
        # If DeFiLlama name is shorter / simpler, add it
        dl_base = _normalize_name(dl_entry.get("name", ""))
        if dl_base and len(dl_base) >= 2 and dl_base not in candidates:
            candidates.append(dl_base)
        # gecko_id as an alias (e.g. "sushi" for SushiSwap)
        gecko = (dl_entry.get("gecko_id") or "").strip().lower()
        if gecko and gecko not in candidates and not gecko.startswith("coingecko:"):
            candidates.append(gecko)

    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        c = c.strip()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ─── DeFiLlama fetch + index ──────────────────────────────────────────────────

def _fetch_defillama() -> list[dict]:
    print("Fetching DeFiLlama protocols...", file=sys.stderr)
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True) as client:
        r = client.get(DEFILLAMA_API, headers={"User-Agent": "kyt-registry/1.0"})
        r.raise_for_status()
        data: list[dict] = r.json()
    print(f"  {len(data)} protocols", file=sys.stderr)
    return data


def _build_dl_index(protocols: list[dict]) -> dict[str, dict]:
    """Build {normalized_name: first_matching_protocol} lookup."""
    idx: dict[str, dict] = {}
    for p in protocols:
        key = _normalize_name(p.get("name", ""))
        if key and key not in idx:
            idx[key] = p
        # also index by slug parts (DeFiLlama id)
        id_key = _normalize_name(p.get("id", "").replace("-", " "))
        if id_key and id_key not in idx:
            idx[id_key] = p
    return idx


# ─── CSV helpers ─────────────────────────────────────────────────────────────

def _load_csv(path: Optional[Path]) -> tuple[list[str], list[dict]]:
    if not path:
        raise ValueError("--input FILE required")
    reader = csv.DictReader(path.open(encoding="utf-8"))
    rows = list(reader)
    fieldnames: list[str] = list(reader.fieldnames or [])
    return fieldnames, rows


def _write_csv(fieldnames: list[str], rows: list[dict], path: Optional[Path]) -> None:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({f: row.get(f, "") for f in fieldnames})
    text = out.getvalue()
    if path:
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path} ({len(text):,} bytes, {len(rows)} rows)", file=sys.stderr)
    else:
        sys.stdout.write(text)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--input",  type=Path, required=True, help="Path to entities.csv")
    ap.add_argument("--output", type=Path, default=None,
                    help="Destination (default: stdout; pass same path as --input to patch in-place)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print stats and sample diffs, don't write output")
    ap.add_argument("--category", default=None,
                    help="Restrict to one category (e.g. dex)")
    args = ap.parse_args()

    target_cats = {args.category} if args.category else TARGET_CATEGORIES

    fieldnames, rows = _load_csv(args.input)
    print(f"  {len(rows)} rows loaded", file=sys.stderr)

    protocols   = _fetch_defillama()
    dl_index    = _build_dl_index(protocols)

    # Stats
    patched_kw  = 0
    patched_dom = 0
    skipped     = 0
    already_set = 0
    dl_matched  = 0

    diff_samples: list[str] = []

    for row in rows:
        cat  = row.get("category_slug", "")
        slug = row.get("arkham_slug", "").strip()

        if cat not in target_cats:
            continue
        if slug in SKIP_SLUGS:
            skipped += 1
            continue
        if row.get("keywords", "").strip():
            already_set += 1
            continue

        # DeFiLlama lookup
        name_key = _normalize_name(row.get("entity_name", ""))
        dl_entry = dl_index.get(name_key)
        if not dl_entry:
            # Try slug-normalised lookup
            id_key = _normalize_name(slug.replace("-", " "))
            dl_entry = dl_index.get(id_key)
        if dl_entry:
            dl_matched += 1

        kws = _build_keywords(row, dl_entry)
        if not kws:
            skipped += 1
            continue

        kw_str = ",".join(kws)

        if args.dry_run:
            if len(diff_samples) < 20:
                dl_info = f"  DL={dl_entry['name']}" if dl_entry else ""
                diff_samples.append(
                    f"  {row['entity_name']:40s}  [{cat}]  kw={kw_str!r:40s}{dl_info}"
                )

        row["keywords"] = kw_str
        patched_kw += 1

        # Fill canonical_domain from DeFiLlama url (only if currently blank)
        if dl_entry and not row.get("canonical_domain", "").strip():
            dom = _domain_from_url(dl_entry.get("url", ""))
            if dom:
                row["canonical_domain"] = dom
                patched_dom += 1

    print(f"\n── Results ──────────────────────────────────────────────", file=sys.stderr)
    print(f"  already had keywords : {already_set}", file=sys.stderr)
    print(f"  skipped (blocklist)  : {skipped}", file=sys.stderr)
    print(f"  DeFiLlama matched    : {dl_matched}", file=sys.stderr)
    print(f"  keywords patched     : {patched_kw}", file=sys.stderr)
    print(f"  domains filled       : {patched_dom}", file=sys.stderr)

    if args.dry_run:
        print(f"\nSample patches ({len(diff_samples)} shown):", file=sys.stderr)
        for s in diff_samples:
            print(s, file=sys.stderr)
        print("\nDry-run — no output written", file=sys.stderr)
        return 0

    _write_csv(fieldnames, rows, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
