"""One-shot targeted logo enrichment for the 18 new ETH-top-10000-holder
vasp_entities rows appended to entities.csv 2026-08-24 -- enrich.py's own
big walker sorts by importance (all tied at 100 here) and stable-sorts
ties by file order, so these newly-appended rows sit at the tail of a
~2000-candidate backlog and never get reached within a sane --max. This
mirrors enrich.py's exact per-row logic (_try_auto waterfall + normalize +
CSV write), just pre-filtered to only these 18 slugs.

    python3 scripts/_oneshot_eth10000_vasp_logos_20260824.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import httpx
from _base import (
    Row, logo_path_for, read_entities, sha256_hex, write_entities, FALLBACK_PNG,
)
import enrich_from_arkham
import enrich_from_brandfetch
import enrich_from_defillama
import enrich_from_favicon
import build_lookup
from normalize_png import NormalizeError, normalize

TARGET_SLUGS = {
    "iconomi-com", "musiconomi-com", "coindash-io", "sparkster-me",
    "digix-global", "savedroid-com", "imbrex-io", "duel-com",
    "joinhighrise-com", "mcdex-io", "blackfort-genesis-knights",
    "singularx-com", "india-covid-crypto-relief-fund", "decentraland-org",
    "cryptopunks-app", "status-im", "santiment-net", "juicebox-money",
    "cvault-finance", "eclipse-xyz",
}

_DEFILLAMA_CATEGORIES = {"defi", "dex", "bridge"}

# See enrich.py's HIGH_RISK_CATEGORIES / _domain_root / _deny_slugs_for
# — same guard, kept in sync here so this one-off walker can't
# reintroduce the 2026-09-27 "kraken-darknet-market" (category guard)
# or "stake" -> "stake-com" / Stake DAO vs Stake.com (domain-root
# guard) false-logo-attribution bugs.
_HIGH_RISK_CATEGORIES = {"sanctioned", "mixer", "hack"}


def _domain_root(domain: str | None) -> str | None:
    domain = (domain or "").strip().lower()
    if not domain:
        return None
    domain = domain.split("://")[-1].split("/")[0]
    labels = [l for l in domain.split(".") if l]
    if not labels:
        return None
    return labels[-2] if len(labels) >= 2 else labels[0]


def _try_auto(row: Row, client: httpx.Client, deny_slugs: frozenset[str]):
    if row.arkham_slug:
        data = enrich_from_arkham.fetch(
            row.arkham_slug, client=client, known_slugs=deny_slugs)
        if data:
            return "arkham", data
    if row.canonical_domain:
        data = enrich_from_brandfetch.fetch(row.canonical_domain, client=client)
        if data:
            return "brandfetch", data
    if row.category_slug in _DEFILLAMA_CATEGORIES and row.arkham_slug:
        data = enrich_from_defillama.fetch(row.arkham_slug, client=client)
        if data:
            return "defillama", data
    if row.canonical_domain:
        data = enrich_from_favicon.fetch(row.canonical_domain)
        if data:
            return "favicon", data
    return None


def main() -> int:
    rows = read_entities()
    targets = [r for r in rows if r.slug in TARGET_SLUGS]
    print(f"[start] {len(targets)}/{len(TARGET_SLUGS)} target rows found in CSV")
    non_risky_slugs = frozenset(
        r.arkham_slug.strip().lower()
        for r in rows
        if r.arkham_slug and r.category_slug not in _HIGH_RISK_CATEGORIES
    )
    slug_domain_root: dict[str, str | None] = {}
    for r in rows:
        s = r.arkham_slug.strip().lower() if r.arkham_slug else ""
        if s and s not in slug_domain_root:
            slug_domain_root[s] = _domain_root(r.canonical_domain)

    def _deny_slugs_for(row: Row) -> frozenset[str]:
        my_slug = row.arkham_slug.strip().lower() if row.arkham_slug else ""
        deny: set[str] = set()
        if row.category_slug in _HIGH_RISK_CATEGORIES:
            deny |= non_risky_slugs
        my_root = _domain_root(row.canonical_domain)
        if my_root is not None:
            for slug, root in slug_domain_root.items():
                if slug != my_slug and root is not None and root != my_root:
                    deny.add(slug)
        deny.discard(my_slug)
        return frozenset(deny)

    default_placeholder = FALLBACK_PNG.read_bytes() if FALLBACK_PNG.exists() else None

    written = 0
    placeholders = 0
    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=True) as client:
        for row in targets:
            result = _try_auto(row, client, _deny_slugs_for(row))
            if result is None:
                path = logo_path_for(row.category_slug, row.slug)
                if path is None:
                    print(f"nopath       {row.entity_name} (category_slug={row.category_slug!r})")
                    continue
                if default_placeholder is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(default_placeholder)
                    row.set("logo_status", "placeholder")
                    row.set("logo_updated_at", __import__("datetime").date.today().isoformat())
                    row.set("logo_hash", sha256_hex(default_placeholder))
                    placeholders += 1
                    print(f"placeholder  {row.entity_name}")
                else:
                    print(f"miss         {row.entity_name}")
                continue

            source, raw = result
            try:
                png = normalize(raw)
            except NormalizeError as e:
                print(f"badpng       {row.entity_name}: {e}")
                continue

            path = logo_path_for(row.category_slug, row.slug)
            if path is None:
                print(f"nopath       {row.entity_name}")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png)

            row.set("logo_status", source)
            row.set("logo_updated_at", __import__("datetime").date.today().isoformat())
            row.set("logo_hash", sha256_hex(png))
            written += 1
            print(f"+ {source:<10} {row.entity_name}  ({len(png)} B)")
            time.sleep(0.1)

    write_entities(rows)
    lkp = build_lookup.emit(rows, dry_run=False)
    print(f"lookup: {lkp} entries (written)")
    print(f"\n[summary] written={written} placeholders={placeholders} of {len(targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
