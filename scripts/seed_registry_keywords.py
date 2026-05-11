"""Seed `keywords` and `product_aliases` columns in kyt-entity-registry/entities.csv.

One-time bootstrap: takes the authoritative keyword mapping that previously
lived in aegis-platform/apps/ui/src/lib/graph/exchange-logos.ts and writes it
into the registry CSV so the manifest-driven architecture works.

After this seed, `keywords` and `product_aliases` are REGISTRY_OWNED — the
weekly export from aegis-platform/Supabase never overwrites them (see
export_entity_registry.py REGISTRY_OWNED set).

USAGE
  # Dry-run: show a diff of what would change
  python3 seed_registry_keywords.py --input entities.csv --dry-run

  # Write patched CSV to a file for review / PR
  python3 seed_registry_keywords.py --input entities.csv --output entities_seeded.csv

  # Pull live CSV + patch + write (for direct use in kyt-entity-registry)
  python3 seed_registry_keywords.py --from-cdn --output entities.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

REGISTRY_CSV_URL = (
    "https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/entities.csv"
)

# ─── Keyword seed data ─────────────────────────────────────────────────────────
# Source of truth: the old EXCHANGE_LOGOS constant in exchange-logos.ts.
# Key = arkham_slug (matches entities.csv `arkham_slug` column).
# Value = (keywords_csv, product_aliases_csv)

SEED: Dict[str, Tuple[str, str]] = {
    # ── Tier 1 ────────────────────────────────────────────────────────────────
    "binance-com":        ("binance", "binance smart chain,binance chain,bnb chain,trust wallet"),
    "bybit-com":          ("bybit", ""),
    "okx-com":            ("okx,okex", "okx wallet"),
    "coinbase-com":       ("coinbase", "coinbase wallet,coinbase custody"),
    "kraken-com":         ("kraken", ""),
    # ── Tier 2 ────────────────────────────────────────────────────────────────
    "kucoin-com":         ("kucoin", ""),
    "bitget-com":         ("bitget", "bitget wallet"),
    "gate-io":            ("gate.io,gateio,gate io", ""),
    "htx-com-huobi-com":  ("htx,huobi", ""),
    "mexc-com":           ("mexc", ""),
    "pionex-com":         ("pionex", ""),
    "crypto-com":         ("crypto.com,cryptocom,crypto com", ""),
    "bitfinex-com":       ("bitfinex", ""),
    "coinex-com":         ("coinex", ""),
    "changenow":          ("changenow,changenow.io,changenow.com", ""),
    "revolut-com":        ("revolut", ""),
    "coinspot":           ("coinspot", ""),
    "coinpayments-net":   ("coinpayments", ""),
    "swapster-fi":        ("swapster.fi,swapster", ""),
    "wallet-tg":          (
        "wallet.tg,@wallet,walletbot,wallet bot",
        "trust wallet,coinbase wallet,bitget wallet,okx wallet,binance wallet,"
        "metamask wallet,tonkeeper wallet,safepal wallet",
    ),
    "triple-a-io":        ("triple-a.io,triple-a", ""),
    # ── Tier 3 ────────────────────────────────────────────────────────────────
    "whitebit-com":       ("whitebit", ""),
    "bingx-com":          ("bingx", ""),
    "hitbtc-com":         ("hitbtc.com,hitbtc", ""),
    "n-exchange":         ("n.exchange,nexchange", ""),
    "cryptomus-com":      ("cryptomus", ""),
    "cryptobot":          ("cryptobot,@cryptobot", ""),
    "bridgers-xyz":       ("bridgers.xyz,bridgers", ""),
    "blofin-com":         ("blofin", ""),
    "weex-com":           ("weex", ""),
    "bitcoinvn-io":       ("bitcoinvn.io,bitcoinvn", ""),
    "roqqu-com":          ("roqqu.com,roqqu", ""),
    "sunswap-com":        ("sunswap", ""),
    "chainup-com":        ("chainup.com,chainup", ""),
    "tronify-io":         ("tronify", ""),
    "feesaver-com":       ("feesaver", ""),
    # ── RU / CIS ──────────────────────────────────────────────────────────────
    "garantex":           ("garantex", ""),
    "grinex":             ("grinex", ""),
    "abcex":              ("abcex", ""),
    "rapira":             ("rapira", ""),
    "moscaex":            ("moscaex", ""),
    "bitstamp":           ("bitstamp", ""),
    "keysecure":          ("keysecure", ""),
}


def load_csv(path: Optional[Path], from_cdn: bool) -> Tuple[List[str], List[dict]]:
    if from_cdn:
        print("Fetching live entities.csv from CDN...", file=sys.stderr)
        r = httpx.get(REGISTRY_CSV_URL, timeout=30, follow_redirects=True)
        r.raise_for_status()
        reader = csv.DictReader(io.StringIO(r.text))
    elif path:
        reader = csv.DictReader(path.open(encoding="utf-8"))
    else:
        raise ValueError("Provide --input FILE or --from-cdn")
    rows = list(reader)
    fieldnames: List[str] = list(reader.fieldnames or [])
    return fieldnames, rows


def patch(fieldnames: List[str], rows: List[dict]) -> Tuple[List[str], List[dict], int]:
    """Add keywords + product_aliases columns and fill from SEED."""
    for col in ("keywords", "product_aliases"):
        if col not in fieldnames:
            # Insert before logo_status so registry-owned columns stay grouped.
            try:
                idx = fieldnames.index("logo_status")
                fieldnames.insert(idx, col)
            except ValueError:
                fieldnames.append(col)

    patched = 0
    for row in rows:
        slug = (row.get("arkham_slug") or row.get("slug") or "").strip()
        if slug not in SEED:
            # Ensure the new columns exist even for un-seeded rows.
            row.setdefault("keywords", "")
            row.setdefault("product_aliases", "")
            continue

        kw, pa = SEED[slug]
        # Only overwrite if currently blank — don't stomp manual edits.
        if not row.get("keywords"):
            row["keywords"] = kw
            patched += 1
        if not row.get("product_aliases") and pa:
            row["product_aliases"] = pa

    return fieldnames, rows, patched


def write_csv(fieldnames: List[str], rows: List[dict], path: Optional[Path]) -> None:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({f: row.get(f, "") for f in fieldnames})
    text = out.getvalue()
    if path:
        path.write_text(text, encoding="utf-8")
        print(f"Wrote {path} ({len(text)} bytes, {len(rows)} rows)", file=sys.stderr)
    else:
        sys.stdout.write(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, help="Path to local entities.csv")
    ap.add_argument("--from-cdn", action="store_true", help="Fetch entities.csv live from jsDelivr")
    ap.add_argument("--output", type=Path, default=None,
                    help="Where to write the patched CSV (default: stdout)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print how many rows would be patched, don't write")
    args = ap.parse_args()

    fieldnames, rows = load_csv(args.input, from_cdn=args.from_cdn)
    print(f"  {len(rows)} rows loaded", file=sys.stderr)

    fieldnames, rows, patched = patch(fieldnames, rows)
    print(f"  {patched} rows patched with keywords", file=sys.stderr)

    if args.dry_run:
        print("Dry-run — no output written", file=sys.stderr)
        return 0

    write_csv(fieldnames, rows, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
