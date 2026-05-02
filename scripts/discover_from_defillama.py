"""Discover new DeFi/DEX/Bridge/Mining protocols from DeFiLlama not yet in entities.csv.

Uses DeFiLlama /protocols list as source:
  1. Fetch all ~7 400 protocols
  2. Filter to supported categories (dex, defi, bridge, mining) + TVL >= MIN_TVL_USD
  3. Skip any protocol whose normalized name or slug already exists in entities.csv
  4. Build a new CSV row for each novel protocol (entity_name, category_slug,
     importance tier, networks, keywords, canonical_domain)

TVL → importance tiers:
  >= 1 000 000 000  →  95
  >= 100 000 000    →  85
  >=  10 000 000    →  75
  >=   1 000 000    →  65   (MIN_TVL_USD default)

USAGE
  # Preview what would be added (no file write)
  python3 scripts/discover_from_defillama.py --input entities.csv --dry-run

  # Append new rows to CSV
  python3 scripts/discover_from_defillama.py --input entities.csv --output entities.csv

  # Lower TVL bar to find niche-but-known protocols
  python3 scripts/discover_from_defillama.py --input entities.csv --min-tvl 100000 --dry-run

  # After adding rows: run generate_manifest.py to rebuild manifest
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

DEFILLAMA_API = "https://api.llama.fi/protocols"

MIN_TVL_USD = 1_000_000   # default: $1M TVL floor

# DeFiLlama category → our category_slug
CATEGORY_MAP: dict[str, str] = {
    "Dexs":              "dex",
    "DEX Aggregator":    "dex",
    "Dexes":             "dex",
    "Lending":           "defi",
    "Yield":             "defi",
    "Yield Aggregator":  "defi",
    "CDP":               "defi",
    "Liquid Staking":    "defi",
    "Derivatives":       "defi",
    "Farm":              "defi",
    "Algo-Stables":      "defi",
    "Reserve Currency":  "defi",
    "RWA":               "defi",
    "Leveraged Farming": "defi",
    "Prediction Market": "defi",
    "Options":           "defi",
    "Bridge":            "bridge",
    "Cross Chain Bridge":"bridge",
    "Canonical Bridge":  "bridge",
    "Mining":            "mining",
    "Staking Pool":      "mining",
}

# DeFiLlama chain name → our network token
CHAIN_MAP: dict[str, str] = {
    "Ethereum":   "ETH",
    "BSC":        "BSC",
    "Binance":    "BSC",
    "Polygon":    "POLYGON",
    "Tron":       "TRON",
    "Solana":     "SOL",
    "Arbitrum":   "ARBITRUM",
    "Optimism":   "OPTIMISM",
    "Avalanche":  "AVALANCHE",
    "Base":       "BASE",
    "Fantom":     "FANTOM",
    "Bitcoin":    "BTC",
}

# DeFiLlama protocol IDs or normalized names to never add.
SKIP_IDS: set[str] = {
    "multiple-dexs",
    "multiple-cexs",
    "multiple-bridges",
    "other",
    "unknown",
}

# ─── Normalization helpers ────────────────────────────────────────────────────

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


def _name_to_slug(name: str) -> str:
    """Convert entity name to arkham_slug style (lowercase, hyphens)."""
    s = _normalize_name(name)
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s


_RE_KW_VERSION  = re.compile(r'\s+v\d+(\.\d+)?(\s|$)', re.I)
_RE_KW_PARENS   = re.compile(r'\s*\([^)]+\)')
_RE_KW_GENERICS = re.compile(
    r'\s+(protocol|finance|network|aggregator|platform|dao|labs?|app|solutions?)\s*$',
    re.I
)


def _name_to_keyword(name: str) -> Optional[str]:
    """Primary keyword from entity_name (dots preserved, generics stripped)."""
    s = name.strip()
    if ' - ' in s:
        s = s.split(' - ')[-1].strip()
    s = _RE_KW_VERSION.sub(' ', s)
    s = _RE_KW_PARENS.sub('', s)
    s = _RE_KW_GENERICS.sub('', s)
    s = re.sub(r'\s+', ' ', s).lower().strip()
    return s if s and len(s) >= 2 else None


_RE_SLUG_TLD     = re.compile(r'-(com|io|fi|xyz|org|net|app)$', re.I)
_RE_SLUG_GENERIC = re.compile(r'-(finance|protocol|network|labs?|dao|v\d+)$', re.I)


def _slug_to_keyword(slug: str) -> Optional[str]:
    s = slug.lower().strip()
    prev = None
    while s != prev:
        prev = s
        s = _RE_SLUG_TLD.sub('', s).strip('-')
    prev = None
    while s != prev:
        prev = s
        s = _RE_SLUG_GENERIC.sub('', s).strip('-')
    if not s or (len(s) < 3 and not re.match(r'^\d', s)):
        return None
    return s


def _domain_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    try:
        parsed = urlparse(url if url.startswith('http') else 'https://' + url)
        host = parsed.netloc or parsed.path.split('/')[0]
        return host.lstrip('www.').lower().strip() or None
    except Exception:
        return None


def _tvl_to_importance(tvl: float) -> int:
    if tvl >= 1_000_000_000:
        return 95
    if tvl >= 100_000_000:
        return 85
    if tvl >= 10_000_000:
        return 75
    return 65


def _chains_to_networks(chains: list[str]) -> str:
    """Map DeFiLlama chain list to pipe-separated network tokens."""
    seen: set[str] = set()
    out: list[str] = []
    for c in chains:
        net = CHAIN_MAP.get(c)
        if net and net not in seen:
            seen.add(net)
            out.append(net)
    return '|'.join(out)


# ─── DeFiLlama fetch ──────────────────────────────────────────────────────────

def _fetch_defillama() -> list[dict]:
    print("Fetching DeFiLlama protocols...", file=sys.stderr)
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True) as client:
        r = client.get(DEFILLAMA_API, headers={"User-Agent": "kyt-registry/1.0"})
        r.raise_for_status()
        data: list[dict] = r.json()
    print(f"  {len(data)} protocols fetched", file=sys.stderr)
    return data


# ─── CSV helpers ─────────────────────────────────────────────────────────────

def _load_csv(path: Path) -> tuple[list[str], list[dict]]:
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
    ap.add_argument("--input",   type=Path, required=True, help="Path to entities.csv")
    ap.add_argument("--output",  type=Path, default=None,
                    help="Destination (default: stdout; pass same path as --input to append in-place)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be added, don't write output")
    ap.add_argument("--min-tvl", type=float, default=MIN_TVL_USD,
                    help=f"Minimum TVL in USD (default: {MIN_TVL_USD:,.0f})")
    ap.add_argument("--category", default=None,
                    help="Restrict to one category_slug (e.g. dex)")
    ap.add_argument("--limit",   type=int,   default=None,
                    help="Cap number of new rows added (useful for review batches)")
    args = ap.parse_args()

    fieldnames, rows = _load_csv(args.input)
    print(f"  {len(rows)} existing rows loaded", file=sys.stderr)

    # Build lookup sets from existing entries (normalized name + slug)
    existing_names: set[str] = set()
    existing_slugs: set[str] = set()
    for r in rows:
        existing_names.add(_normalize_name(r.get("entity_name", "")))
        existing_slugs.add(r.get("arkham_slug", "").strip().lower())

    protocols = _fetch_defillama()

    # Sort by TVL descending so highest-value protocols are processed first
    protocols.sort(key=lambda p: p.get("tvl") or 0, reverse=True)

    new_rows: list[dict] = []
    skipped_existing = 0
    skipped_tvl      = 0
    skipped_category = 0
    skipped_blocklist = 0

    target_cat = {args.category} if args.category else set(CATEGORY_MAP.values())

    for p in protocols:
        dl_name     = (p.get("name") or "").strip()
        dl_id       = (p.get("id")   or "").strip().lower()
        dl_category = (p.get("category") or "").strip()
        dl_tvl      = p.get("tvl") or 0
        dl_chains   = p.get("chains") or []
        dl_url      = p.get("url") or ""
        dl_gecko    = (p.get("gecko_id") or "").strip().lower()

        if not dl_name:
            continue

        # Category filter
        cat_slug = CATEGORY_MAP.get(dl_category)
        if not cat_slug:
            skipped_category += 1
            continue
        if cat_slug not in target_cat:
            skipped_category += 1
            continue

        # TVL filter
        if dl_tvl < args.min_tvl:
            skipped_tvl += 1
            continue

        # Blocklist
        if dl_id in SKIP_IDS:
            skipped_blocklist += 1
            continue

        # Already exists check (by normalized name or by generated slug)
        norm_name    = _normalize_name(dl_name)
        gen_slug     = _name_to_slug(dl_name)
        id_norm      = _normalize_name(dl_id.replace("-", " "))

        if (norm_name in existing_names
                or id_norm in existing_names
                or gen_slug in existing_slugs
                or dl_id in existing_slugs):
            skipped_existing += 1
            continue

        # Build keywords
        kw_primary = _name_to_keyword(dl_name)
        kw_slug    = _slug_to_keyword(gen_slug)
        keywords_parts: list[str] = []
        if kw_primary:
            keywords_parts.append(kw_primary)
        if kw_slug and kw_slug != kw_primary:
            keywords_parts.append(kw_slug)
        if dl_gecko and dl_gecko not in keywords_parts and not dl_gecko.startswith("coingecko:"):
            keywords_parts.append(dl_gecko)

        keywords = ",".join(dict.fromkeys(keywords_parts))  # deduplicate, preserve order

        # Networks
        networks = _chains_to_networks(dl_chains)

        # Canonical domain
        canonical_domain = _domain_from_url(dl_url) or ""

        # Importance from TVL
        importance = _tvl_to_importance(dl_tvl)

        new_row: dict = {
            "entity_name":      dl_name,
            "category_slug":    cat_slug,
            "importance":       str(importance),
            "claim_count":      "0",
            "max_trust":        "0",
            "severity":         "10",
            "networks":         networks,
            "sources":          "",
            "arkham_slug":      gen_slug,
            "canonical_domain": canonical_domain,
            "keywords":         keywords,
            "product_aliases":  "",
            "logo_status":      "",
            "logo_updated_at":  "",
            "manual_lock":      "false",
            "logo_hash":        "",
        }
        new_rows.append(new_row)

        # Add to lookups so duplicates within the batch are also caught
        existing_names.add(norm_name)
        existing_slugs.add(gen_slug)

        if args.limit and len(new_rows) >= args.limit:
            break

    # Print stats
    print(f"\n── Results ──────────────────────────────────────────────", file=sys.stderr)
    print(f"  already in registry  : {skipped_existing}", file=sys.stderr)
    print(f"  skipped (blocklist)  : {skipped_blocklist}", file=sys.stderr)
    print(f"  skipped (category)   : {skipped_category}", file=sys.stderr)
    print(f"  skipped (TVL < {args.min_tvl:,.0f}): {skipped_tvl}", file=sys.stderr)
    print(f"  new rows to add      : {len(new_rows)}", file=sys.stderr)

    if args.dry_run:
        print(f"\nSample (up to 30 rows):", file=sys.stderr)
        for row in new_rows[:30]:
            tvl_str = ""
            print(
                f"  {row['entity_name']:40s}  [{row['category_slug']:8s}]  "
                f"imp={row['importance']}  kw={row['keywords']!r}",
                file=sys.stderr,
            )
        print("\nDry-run — no output written", file=sys.stderr)
        return 0

    combined = rows + new_rows
    _write_csv(fieldnames, combined, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
