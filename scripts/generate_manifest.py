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
  at least one keyword defined.  Shape:

    {
      "version": 1,
      "generated_at": "<ISO-8601>",
      "entries": [
        {
          "slug": "binance-com",
          "category": "exchange",
          "keywords": ["binance"],
          "product_aliases": ["binance smart chain", "trust wallet"],
          "sanctioned": false
        },
        ...
      ]
    }

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

import httpx  # already in apps/data requirements

REGISTRY_CSV_URL = (
    "https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/entities.csv"
)

# logo_status values that indicate a real PNG exists on the CDN.
LOGO_READY = {"manual", "arkham", "brandfetch"}

# Categories treated as sanctioned for the manifest `sanctioned` flag.
SANCTIONED_CATEGORIES = {"sanctioned"}


def _parse_list(raw: str) -> List[str]:
    """'foo,bar, baz' → ['foo', 'bar', 'baz']. Empty string → []."""
    if not raw or not raw.strip():
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def load_csv(path: Optional[Path] = None, from_cdn: bool = False) -> List[dict]:
    if from_cdn:
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
        sanctioned = category in SANCTIONED_CATEGORIES

        if not slug or not category:
            continue

        entries.append({
            "slug": slug,
            "category": category,
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
        "version": 1,
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
