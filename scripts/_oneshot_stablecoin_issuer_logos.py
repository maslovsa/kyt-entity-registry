"""One-shot: fetch DeFiLlama pegged-icon logos for stablecoin_issuer entities.

Background: aegis-platform's `apps/data/scripts/ingest_defillama_stablecoin_issuers.py`
seeds `vasp_entities` (category=stablecoin_issuer, `registry_slug=gecko_id`) but
never fetches a logo -- deferred intentionally. This script closes that gap:

  1. Read the target list (vasp_entities rows, registry_category=stablecoin_issuer,
     dumped to JSON by the caller -- see --input).
  2. For each row with a `registry_slug` (gecko_id), fetch
     https://icons.llamao.fi/icons/pegged/<gecko_id>?w=160&h=160
  3. Normalize via normalize_png.normalize() (160x160 RGBA, <=50KB).
  4. Write logos/stablecoin_issuer/<gecko_id>.png
  5. Append a row to entities.csv (category_slug=stablecoin_issuer), unless an
     arkham_slug collision already exists (skip + report -- never overwrite an
     existing row from a one-shot).

Idempotent: re-running skips slugs already in entities.csv or already on disk.

Usage:
    python3 scripts/_oneshot_stablecoin_issuer_logos.py --input <path-to-json>
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _base import (  # noqa: E402
    CSV_PATH, LOGOS_DIR, COLUMNS, entity_slug, sha256_hex,
)
from normalize_png import normalize, NormalizeError  # noqa: E402

ICON_URL = "https://icons.llamao.fi/icons/pegged/{slug}?w=160&h=160"
TODAY = dt.date.today().isoformat()


def load_existing_slugs() -> set[str]:
    slugs = set()
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            s = (row.get("arkham_slug") or "").strip()
            if s:
                slugs.add(s)
    return slugs


def fetch_icon(slug: str, client: httpx.Client) -> bytes | None:
    url = ICON_URL.format(slug=slug)
    try:
        r = client.get(url, timeout=15, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or not r.content:
        return None
    ctype = r.headers.get("content-type", "")
    if "image" not in ctype:
        return None
    return r.content


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="JSON dump of vasp_entities rows")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = json.loads(Path(args.input).read_text())
    existing = load_existing_slugs()

    out_dir = LOGOS_DIR / "stablecoin_issuer"
    out_dir.mkdir(parents=True, exist_ok=True)

    new_csv_rows: list[dict] = []
    stats = {"no_slug": 0, "already_in_csv": 0, "fetch_ok": 0, "fetch_failed": 0, "normalize_failed": 0}

    with httpx.Client(headers={"User-Agent": "kyt-entity-registry/1.0 stablecoin-logo-oneshot"}) as client:
        for row in rows:
            slug = (row.get("registry_slug") or "").strip()
            name = (row.get("display_name") or "").strip()
            if not slug:
                stats["no_slug"] += 1
                continue
            if slug in existing:
                stats["already_in_csv"] += 1
                continue

            raw = fetch_icon(slug, client)
            if raw is None:
                stats["fetch_failed"] += 1
                continue

            try:
                png = normalize(raw)
            except NormalizeError:
                stats["normalize_failed"] += 1
                continue

            if not args.dry_run:
                (out_dir / f"{slug}.png").write_bytes(png)

            new_csv_rows.append({
                "entity_name": name,
                "category_slug": "stablecoin_issuer",
                "importance": "65",
                "claim_count": "0",
                "max_trust": "0",
                "severity": "10",
                "networks": "",
                "sources": "defillama-adapters",
                "arkham_slug": slug,
                "canonical_domain": "",
                "keywords": name.lower(),
                "product_aliases": "",
                "logo_status": "defillama",
                "logo_updated_at": TODAY,
                "manual_lock": "false",
                "logo_hash": sha256_hex(png),
            })
            existing.add(slug)
            stats["fetch_ok"] += 1
            time.sleep(0.1)  # polite pacing

    if new_csv_rows and not args.dry_run:
        with open(CSV_PATH, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            for r in new_csv_rows:
                w.writerow(r)

    print(json.dumps({**stats, "total_input": len(rows), "csv_rows_written": len(new_csv_rows) if not args.dry_run else 0,
                       "csv_rows_would_write": len(new_csv_rows) if args.dry_run else 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
