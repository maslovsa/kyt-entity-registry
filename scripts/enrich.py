"""Orchestrator — walk entities.csv, fill in missing/stale logos.

Pipeline per row:
    1. skip if manual_lock=true
    2. skip if fresh (logo_updated_at within REFRESH_DAYS, status != 'none')
    3. if logos/_manual/<cat>/<slug>.png exists → copy over, set manual
    4. else: Arkham -> Brandfetch -> DefiLlama; first hit wins
    5. normalize -> 160x160 RGBA PNG
    6. sha256 check: write + update CSV only if bytes changed

After the walk, rewrite logos/_index.json for consumers that want
existence checks without a 404 round-trip.

CLI:
    python scripts/enrich.py [--max N] [--category <slug>] [--dry-run]
                             [--force] [--verbose]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Callable

import httpx

# Allow "python scripts/enrich.py" to import sibling modules
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _base import (  # type: ignore[import-not-found]
    CSV_PATH,
    FALLBACK_PNG,
    LOGOS_DIR,
    CATEGORY_TO_DIR,
    Row,
    logo_path_for,
    manual_path_for,
    read_entities,
    sha256_hex,
    write_entities,
    write_bool,
)
import enrich_from_arkham      # type: ignore[import-not-found]
import enrich_from_brandfetch  # type: ignore[import-not-found]
import enrich_from_defillama   # type: ignore[import-not-found]
from normalize_png import NormalizeError, normalize  # type: ignore[import-not-found]

REFRESH_DAYS = 30

STATUS_NONE = "none"
STATUS_ARKHAM = "arkham"
STATUS_BRANDFETCH = "brandfetch"
STATUS_DEFILLAMA = "defillama"
STATUS_MANUAL = "manual"


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def _is_fresh(row: Row) -> bool:
    if row.logo_status == STATUS_NONE:
        return False
    updated = row.get("logo_updated_at")
    if not updated:
        return False
    try:
        d = dt.date.fromisoformat(updated)
    except ValueError:
        return False
    return (dt.date.today() - d).days < REFRESH_DAYS


def _try_manual(row: Row) -> bytes | None:
    mp = manual_path_for(row.category_slug, row.slug)
    if mp and mp.exists():
        return mp.read_bytes()
    return None


def _try_auto(row: Row, client: httpx.Client) -> tuple[str, bytes] | None:
    """Return (source_label, bytes) or None. First hit wins."""
    if row.arkham_slug:
        data = enrich_from_arkham.fetch(row.arkham_slug, client=client)
        if data:
            return STATUS_ARKHAM, data

    if row.canonical_domain:
        data = enrich_from_brandfetch.fetch(row.canonical_domain, client=client)
        if data:
            return STATUS_BRANDFETCH, data

    # DefiLlama: only try for DeFi-category entities to stay polite;
    # their CDN has no strong rate limit but this is what the RFC asks.
    if row.category_slug == "defi" and row.arkham_slug:
        data = enrich_from_defillama.fetch(row.arkham_slug, client=client)
        if data:
            return STATUS_DEFILLAMA, data

    return None


def _write_logo(row: Row, png: bytes, dry_run: bool) -> Path | None:
    path = logo_path_for(row.category_slug, row.slug)
    if path is None:
        return None
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
    return path


def _emit_index(dry_run: bool) -> int:
    """Build logos/_index.json from filesystem state. Returns entry count."""
    index: dict[str, bool] = {}
    for category_dir in LOGOS_DIR.iterdir():
        if not category_dir.is_dir():
            continue
        if category_dir.name.startswith("_"):
            continue
        if category_dir.name not in CATEGORY_TO_DIR.values():
            continue
        for png in sorted(category_dir.glob("*.png")):
            index[f"{category_dir.name}/{png.stem}"] = True

    out = LOGOS_DIR / "_index.json"
    payload = json.dumps(index, separators=(",", ":"), sort_keys=True) + "\n"
    if not dry_run:
        out.write_text(payload, encoding="utf-8")
    return len(index)


def _ensure_fallback(dry_run: bool) -> None:
    """Generate a neutral grey `?` PNG if missing — consumers need it."""
    if FALLBACK_PNG.exists():
        return
    if dry_run:
        return
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 152, 152), fill=(210, 210, 215, 255))
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Helvetica.ttc", 88)
    except Exception:
        font = ImageFont.load_default()
    text = "?"
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    d.text(((160 - tw) / 2 - bbox[0], (160 - th) / 2 - bbox[1] - 4),
           text, font=font, fill=(255, 255, 255, 255))
    FALLBACK_PNG.parent.mkdir(parents=True, exist_ok=True)
    img.save(FALLBACK_PNG, format="PNG", optimize=True)


def run(
    max_rows: int | None,
    category: str | None,
    dry_run: bool,
    force: bool,
    verbose: bool,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    rows = read_entities()
    rows.sort(key=lambda r: r.importance, reverse=True)

    counters = {
        "scanned": 0, "skipped_lock": 0, "skipped_fresh": 0,
        "hit_manual": 0, "hit_arkham": 0, "hit_brandfetch": 0,
        "hit_defillama": 0, "miss": 0, "unchanged": 0,
        "written": 0, "normalize_fail": 0,
    }

    _ensure_fallback(dry_run)

    budget = max_rows if max_rows is not None else len(rows)
    processed = 0

    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0),
                      follow_redirects=True) as client:
        for row in rows:
            if category and row.category_slug != category:
                continue
            if processed >= budget:
                break
            processed += 1
            counters["scanned"] += 1

            if row.manual_lock:
                counters["skipped_lock"] += 1
                if verbose:
                    log(f"lock    {row.entity_name}")
                continue
            if not force and _is_fresh(row):
                counters["skipped_fresh"] += 1
                if verbose:
                    log(f"fresh   {row.entity_name}")
                continue

            raw: bytes | None = None
            source: str | None = None

            manual = _try_manual(row)
            if manual is not None:
                raw = manual
                source = STATUS_MANUAL
            else:
                result = _try_auto(row, client)
                if result is not None:
                    source, raw = result

            if raw is None:
                counters["miss"] += 1
                if verbose:
                    log(f"miss    {row.entity_name}")
                continue

            try:
                png = normalize(raw)
            except NormalizeError as e:
                counters["normalize_fail"] += 1
                log(f"badpng  {row.entity_name}: {e}")
                continue

            new_hash = sha256_hex(png)
            if new_hash == row.logo_hash and not force:
                counters["unchanged"] += 1
                if verbose:
                    log(f"same    {row.entity_name}")
                continue

            path = _write_logo(row, png, dry_run)
            if path is None:
                counters["miss"] += 1
                continue
            counters[f"hit_{source}"] += 1
            counters["written"] += 1

            row.set("logo_status", source)
            row.set("logo_updated_at", _today())
            row.set("logo_hash", new_hash)
            if source == STATUS_MANUAL:
                row.set("manual_lock", write_bool(True))

            log(f"+ {source:<10} {row.entity_name}  ({len(png)} B)")
            # polite pacing — no tight loop against any one host
            time.sleep(0.05)

    if not dry_run:
        write_entities(rows)

    idx = _emit_index(dry_run)
    log(f"index: {idx} entries  ({'dry-run' if dry_run else 'written'})")

    return counters


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=None,
                    help="Max rows to process (default: all)")
    ap.add_argument("--category", default=None,
                    help="Restrict to one category_slug")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write files or CSV")
    ap.add_argument("--force", action="store_true",
                    help="Ignore freshness + hash checks")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    c = run(
        max_rows=args.max,
        category=args.category,
        dry_run=args.dry_run,
        force=args.force,
        verbose=args.verbose,
    )

    print("---")
    print(f"scanned:        {c['scanned']}")
    print(f"skipped (lock): {c['skipped_lock']}")
    print(f"skipped (fresh):{c['skipped_fresh']}")
    print(f"manual hits:    {c['hit_manual']}")
    print(f"arkham hits:    {c['hit_arkham']}")
    print(f"brandfetch:     {c['hit_brandfetch']}")
    print(f"defillama:      {c['hit_defillama']}")
    print(f"unchanged:      {c['unchanged']}")
    print(f"written:        {c['written']}")
    print(f"normalize fail: {c['normalize_fail']}")
    print(f"miss:           {c['miss']}")
    print(f"CSV:            {'(dry-run)' if args.dry_run else CSV_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
