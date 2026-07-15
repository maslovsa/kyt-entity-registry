"""Generate manifest.json for kyt-entity-registry from entities.csv.

manifest.json is the lightweight runtime file that aegis-platform (and any
other consumer) fetches to power badge detection without maintaining a
hard-coded entity list.

INPUTS
  entities.csv — the canonical registry file (from CDN or local copy)
  Must contain columns: slug (arkham_slug), category_slug, keywords,
  product_aliases, logo_status.

OUTPUT
  manifest.json — filtered subset: only logo-ready entries that have
  at least one keyword defined.  Shape (version 2):

    {
      "version": 2,
      "generated_at": "<ISO-8601>",
      "entries": [
        {
          "slug": "binance-com",
          "category": "exchange",
          "logo_path": "logos/exchanges/binance-com.png",
          "keywords": ["binance"],
          "product_aliases": ["binance smart chain", "trust wallet"],
          "sanctioned": false
        },
        ...
      ]
    }

  v2 added `logo_path` so consumers don't have to re-implement the
  `category_slug → directory` asymmetry (only `exchange` is pluralised
  to `exchanges/` on disk; see docs/PROVIDERS.md).  Old v1 fields
  (`slug`, `category`, `keywords`, `product_aliases`, `sanctioned`)
  are unchanged — v1-aware consumers keep working.

TYPICAL USAGE
  # Generate from local CSV (after pulling from CDN or editing locally):
  python3 generate_manifest.py --input entities.csv --output manifest.json

  # Pull the live CSV from CDN, generate, write to stdout:
  python3 generate_manifest.py --from-cdn

  # CI: pull + generate + check diff vs committed manifest:
  python3 generate_manifest.py --from-cdn --check

INTEGRATION
  Run this script after every edit to entities.csv (keywords or logo_status
  columns change).  Commit the updated manifest.json alongside entities.csv
  so jsDelivr serves the fresh version.

  In kyt-entity-registry, wire it as a GitHub Actions step:
    - name: Regenerate manifest
      run: python3 scripts/generate_manifest.py --input entities.csv --output manifest.json
    - name: Commit if changed
      uses: stefanzweifel/git-auto-commit-action@v5
      with:
        commit_message: 'chore: regenerate manifest.json'
        file_pattern: manifest.json
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

# httpx is only needed for --from-cdn; imported lazily inside load_csv() so
# a minimal CI environment (offline validate.yml) doesn't have to install it.

REGISTRY_CSV_URL = (
    "https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/entities.csv"
)

# logo_status values that indicate a real PNG exists on the CDN.
#
# `defillama` added 2026-05-12 — DefiLlama-enriched entries have PNGs
# materialised on disk (logos/<category>/<slug>.png) by the DefiLlama
# enrichment pipeline.  Widening LOGO_READY lifts ~173 DeFi entries
# into the runtime manifest (637 → 810 at time of change) without any
# logo-curation work.  6 pre-existing missing-PNG entries (Iranian /
# Cambodian sanctioned exchanges using Iran-flag override) were
# already in the manifest before this change.
LOGO_READY = {"manual", "arkham", "brandfetch", "defillama"}

# Categories treated as sanctioned for the manifest `sanctioned` flag.
SANCTIONED_CATEGORIES = {"sanctioned"}

# 2026-07-15 — designated entities reclassified OUT of category_slug=sanctioned
# into a business-type bucket (e.g. 'bank') so registry_category reflects what
# the entity IS, not just that it's designated (mirrors aegis-platform's
# risk_metadata.subcategory=sanctioned, a cross-cutting tag independent of
# type). The `sanctioned` manifest flag must still surface for these, since
# aegis-platform consumers (kyt-client.tsx, exchange-badge-styles.ts) key off
# it directly to show a red "(sanctioned)" indicator regardless of category.
SANCTIONED_SLUG_OVERRIDES = {
    "ofac-sdn-cheil-credit-bank",  # OFAC SDN
    "promsvyazbank-ru",            # UK OFSI
    "capital-bank-of-central-asia-kg",  # UK OFSI
    "esb-kg",                      # UK OFSI
}

# Map category_slug → on-disk directory name under logos/.  Mirrors
# docs/PROVIDERS.md "Category → directory mapping" table.  Only
# `exchange` is pluralised (historical reasons); the rest match the
# slug 1:1.  Any change here MUST update docs/PROVIDERS.md in the
# same PR — consumers rely on the `logo_path` field below to avoid
# ever needing this map directly, but enrichment scripts still do.
CATEGORY_DIR_MAP = {
    "exchange": "exchanges",
    "dex": "dex",
    "defi": "defi",
    "bridge": "bridge",
    "wallet": "wallet",
    "mining": "mining",
    "psp": "psp",
    "bot": "bot",
    "gambling": "gambling",
    "nft_marketplace": "nft_marketplace",
    "mixer": "mixer",
    "hack": "hack",
    "bank": "bank",
    "sanctioned": "sanctioned",
}


def _logo_path(category: str, slug: str) -> str:
    """Build the on-disk relative path for a logo PNG.

    Falls back to the bare category name if it's not in the map — keeps
    new categories working before the map is updated (URL will 404 if the
    dir doesn't exist, which is the correct loud-failure mode).
    """
    directory = CATEGORY_DIR_MAP.get(category, category)
    return f"logos/{directory}/{slug}.png"


def _parse_list(raw: str) -> List[str]:
    """'foo,bar, baz' → ['foo', 'bar', 'baz']. Empty string → []."""
    if not raw or not raw.strip():
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def load_csv(path: Optional[Path] = None, from_cdn: bool = False) -> List[dict]:
    if from_cdn:
        import httpx  # lazy — only when --from-cdn is used
        print("Fetching live entities.csv from CDN...", file=sys.stderr)
        r = httpx.get(REGISTRY_CSV_URL, timeout=30, follow_redirects=True)
        r.raise_for_status()
        reader = csv.DictReader(io.StringIO(r.text))
    elif path:
        reader = csv.DictReader(path.open(encoding="utf-8"))
    else:
        raise ValueError("Provide --input FILE or --from-cdn")
    return list(reader)


def build_manifest(rows: List[dict]) -> dict:
    entries = []
    skipped_no_logo = 0
    skipped_no_keywords = 0

    for row in rows:
        logo_status = (row.get("logo_status") or "").strip().lower()
        keywords_raw = row.get("keywords") or ""
        keywords = _parse_list(keywords_raw)

        # Only include entries that are logo-ready AND have keywords.
        if logo_status not in LOGO_READY:
            skipped_no_logo += 1
            continue
        if not keywords:
            skipped_no_keywords += 1
            continue

        slug = (row.get("arkham_slug") or row.get("slug") or "").strip()
        category = (row.get("category_slug") or "").strip()
        product_aliases = _parse_list(row.get("product_aliases") or "")
        sanctioned = category in SANCTIONED_CATEGORIES or slug in SANCTIONED_SLUG_OVERRIDES

        if not slug or not category:
            continue

        entries.append({
            "slug": slug,
            "category": category,
            "logo_path": _logo_path(category, slug),
            "keywords": keywords,
            "product_aliases": product_aliases,
            "sanctioned": sanctioned,
        })

    print(
        f"  {len(entries)} entries in manifest "
        f"(skipped: {skipped_no_logo} no-logo, {skipped_no_keywords} no-keywords)",
        file=sys.stderr,
    )
    return {
        "version": 2,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "entries": entries,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, help="Path to local entities.csv")
    ap.add_argument("--from-cdn", action="store_true", help="Fetch entities.csv live from jsDelivr")
    ap.add_argument("--output", type=Path, default=None,
                    help="Where to write manifest.json (default: stdout)")
    ap.add_argument("--check", action="store_true",
                    help="Exit with code 1 if generated manifest differs from --output")
    args = ap.parse_args()

    rows = load_csv(args.input, from_cdn=args.from_cdn)
    print(f"  {len(rows)} rows in entities.csv", file=sys.stderr)

    manifest = build_manifest(rows)
    new_json = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"

    if args.check and args.output and args.output.exists():
        existing = args.output.read_text(encoding="utf-8")
        # Ignore generated_at for diff — compare entries only
        m_new = json.loads(new_json)
        m_old = json.loads(existing)
        if m_new["entries"] != m_old["entries"]:
            print("DIFF: manifest.json is stale — re-run without --check to update", file=sys.stderr)
            return 1
        print("OK: manifest.json is up-to-date", file=sys.stderr)
        return 0

    if args.output:
        args.output.write_text(new_json, encoding="utf-8")
        print(f"Wrote {args.output} ({len(new_json)} bytes)", file=sys.stderr)
    else:
        sys.stdout.write(new_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
