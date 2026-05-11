"""One-shot cleanup, follow-up to PR #4.

Three orthogonal passes, applied in order:

  Pass 1 — RECAT: per-row reclassification of obvious mis-categorized
    rows. PR #4 used a blanket `hack→defi` heuristic; this pass moves
    the obviously-not-defi rows to their correct category.

      a) Name contains the word "Bridge"  →  category=bridge
      b) Name matches the curated CEX list  →  category=exchange

    Curated CEX list is conservative — only well-known centralized
    exchanges where the brand is unambiguous. Ambiguous ones (THORChain,
    Saga, IoTeX, Hedera, Shibarium, Tornado Cash Governance, Wintermute,
    market makers, …) are LEFT under `defi` for operator review.

  Pass 2 — DEDUPE: merge (slug, category) duplicates after PR #4 + the
    pass 1 recats. For each duplicate group, keep the single "best"
    row, merge in non-empty fields (`sources`, `networks`, `keywords`,
    `product_aliases`, `canonical_domain`, `arkham_slug`, `claim_count`,
    `importance`, `max_trust`) from the dropped rows.

    Best-row selection: highest logo_status quality (manual > arkham >
    brandfetch > favicon > placeholder > none), then `manual_lock=true`,
    then higher `claim_count`, then higher `importance`, then first-
    seen as tiebreaker.

  Pass 3 — SEVERITY: drop the hack-era `severity=95` left on re-cat'd
    rows to the per-category default from
    `apps/data/scripts/export_entity_registry.py:SEVERITY_DEFAULTS`.
    Only touches rows where `severity=95` and category NOT IN
    {hack, sanctioned, mixer, gambling}.

Logo files are moved (`git mv`) when a row is reclassified to a
different category; orphan logos from dedupe-dropped rows are
`git rm`'d.

Usage:
    python3 scripts/_oneshot_post_pr4_cleanup.py             # dry-run
    python3 scripts/_oneshot_post_pr4_cleanup.py --apply     # write
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _base import COLUMNS, LOGOS_DIR, CATEGORY_TO_DIR, entity_slug  # noqa: E402

CSV_PATH = REPO_ROOT / "entities.csv"

# ── Pass 1 inputs ────────────────────────────────────────────────────

BRIDGE_NAME_RX = re.compile(r"\bBridge\b", re.I)

# Curated CEX list: only well-known centralized exchanges where the
# brand is unambiguous. Match by normalized name (lowercase, strip
# common "- REKT" suffix variants).
CEX_BRANDS = {
    "alphapo", "ascendex", "bigone", "bingx", "bitmart", "btcturk",
    "bybit", "coindcx", "coinex", "crypto.com", "deribit", "indodax",
    "infini", "kucoin", "lcx", "m2 exchange", "okex", "okx",
    "phemex", "poloniex", "remitano", "wazirx", "woo x", "woox",
    "huobi", "htx", "htx-huobi",
}

# ── Pass 3 inputs ────────────────────────────────────────────────────

SEVERITY_DEFAULTS = {
    "hack": 95, "sanctioned": 95, "mixer": 95,
    "gambling": 50,
    "dex": 10, "nft_marketplace": 10,
    "exchange": 5, "bridge": 5, "defi": 5, "wallet": 5,
    "mining": 5, "psp": 5, "bot": 5,
}
# Categories whose severity=95 we leave alone (true high-risk).
KEEP_HIGH_SEVERITY = {"hack", "sanctioned", "mixer", "gambling"}

# Logo status quality, higher = better.
LOGO_QUALITY = {
    "manual": 5, "arkham": 4, "brandfetch": 3,
    "favicon": 2, "placeholder": 1, "none": 0, "": 0,
}

# Fields where we want to merge non-empty values from the loser rows.
MERGE_FIELDS_TEXT = ("canonical_domain", "arkham_slug")
MERGE_FIELDS_PIPED = ("networks", "sources", "keywords", "product_aliases")
MERGE_FIELDS_NUMERIC_MAX = ("claim_count", "importance", "max_trust")


def slug_for(row: dict) -> str:
    return row.get("arkham_slug") or entity_slug(row.get("entity_name", ""))


def logo_path(category: str, slug: str) -> Path | None:
    d = CATEGORY_TO_DIR.get(category)
    if not d or not slug:
        return None
    return LOGOS_DIR / d / f"{slug}.png"


def norm_brand(name: str) -> str:
    n = name.lower().strip()
    for sfx in (" - rekt 2", " - rekt", " - r3kt", " rekt 2", " rekt",
                "-rekt-2", "-rekt", " 2"):
        if n.endswith(sfx):
            n = n[: -len(sfx)].strip()
    return n


def merge_into(keep: dict, loser: dict) -> None:
    """Merge non-empty fields from `loser` into `keep` in place."""
    for f in MERGE_FIELDS_TEXT:
        if not keep.get(f) and loser.get(f):
            keep[f] = loser[f]
    for f in MERGE_FIELDS_PIPED:
        existing = set(filter(None, (keep.get(f) or "").split("|")))
        incoming = set(filter(None, (loser.get(f) or "").split("|")))
        merged = existing | incoming
        if merged:
            keep[f] = "|".join(sorted(merged))
    for f in MERGE_FIELDS_NUMERIC_MAX:
        try:
            kv = int(keep.get(f) or "0")
        except ValueError:
            kv = 0
        try:
            lv = int(loser.get(f) or "0")
        except ValueError:
            lv = 0
        keep[f] = str(max(kv, lv))


def row_quality(r: dict) -> tuple:
    return (
        LOGO_QUALITY.get(r.get("logo_status", ""), 0),
        1 if (r.get("manual_lock") or "").lower() == "true" else 0,
        int(r.get("claim_count") or 0) if (r.get("claim_count") or "0").isdigit() else 0,
        int(r.get("importance") or 0) if (r.get("importance") or "0").isdigit() else 0,
    )


def git_mv(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "mv", str(src.relative_to(REPO_ROOT)), str(dst.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT, check=True,
    )


def git_rm(path: Path) -> None:
    subprocess.run(
        ["git", "rm", str(path.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT, check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with open(CSV_PATH, newline="") as f:
        rows = [{k: r.get(k, "") for k in COLUMNS} for r in csv.DictReader(f)]

    # ── Pass 1: per-row recat ────────────────────────────────────────
    recat_bridge: list[str] = []
    recat_exchange: list[str] = []
    for r in rows:
        if r["category_slug"] != "defi":
            continue
        name = r["entity_name"]
        if BRIDGE_NAME_RX.search(name):
            r["category_slug"] = "bridge"
            recat_bridge.append(name)
        elif norm_brand(name) in CEX_BRANDS:
            r["category_slug"] = "exchange"
            recat_exchange.append(name)

    # ── Pass 2: dedupe by (slug, category) ───────────────────────────
    groups: dict[tuple[str, str], list[int]] = {}
    for idx, r in enumerate(rows):
        key = (slug_for(r), r["category_slug"])
        groups.setdefault(key, []).append(idx)

    drop_indices: set[int] = set()
    dedupe_summary: list[str] = []
    for (slug, cat), idxs in groups.items():
        if len(idxs) <= 1:
            continue
        # Pick best
        ranked = sorted(idxs, key=lambda i: row_quality(rows[i]), reverse=True)
        keep = ranked[0]
        losers = ranked[1:]
        keep_name = rows[keep]["entity_name"]
        loser_names = [rows[i]["entity_name"] for i in losers]
        for li in losers:
            merge_into(rows[keep], rows[li])
            drop_indices.add(li)
        dedupe_summary.append(
            f"  {cat}/{slug}: keep '{keep_name}' (logo={rows[keep].get('logo_status','none')}), "
            f"drop {loser_names}"
        )

    # ── Pass 3: severity normalization ──────────────────────────────
    sev_changes = 0
    for idx, r in enumerate(rows):
        if idx in drop_indices:
            continue
        if (r.get("severity") or "") != "95":
            continue
        cat = r["category_slug"]
        if cat in KEEP_HIGH_SEVERITY:
            continue
        new_sev = SEVERITY_DEFAULTS.get(cat)
        if new_sev is None:
            continue
        r["severity"] = str(new_sev)
        sev_changes += 1

    # ── Compute logo ops ────────────────────────────────────────────
    # `rows` already has updated categories. To know the OLD category,
    # we re-read the original CSV.
    with open(CSV_PATH, newline="") as f:
        orig_rows = [{k: r.get(k, "") for k in COLUMNS} for r in csv.DictReader(f)]

    logo_moves: dict[Path, Path] = {}
    logo_deletes: set[Path] = set()

    # Recat moves: for surviving rows with new category != original.
    for idx, r in enumerate(rows):
        if idx in drop_indices:
            continue
        old_cat = orig_rows[idx]["category_slug"]
        new_cat = r["category_slug"]
        if old_cat == new_cat:
            continue
        slug = slug_for(r)
        src = logo_path(old_cat, slug)
        dst = logo_path(new_cat, slug)
        if src and src.exists() and dst is not None and src not in logo_moves:
            if dst.exists():
                logo_deletes.add(src)
            else:
                logo_moves[src] = dst

    # Dedupe drops: orphan logo of loser row, only if no keep-row sibling
    # in the same category has the same slug + a logo file already
    # accounted for.
    for li in drop_indices:
        old_cat = orig_rows[li]["category_slug"]
        slug = slug_for(orig_rows[li])
        src = logo_path(old_cat, slug)
        if not (src and src.exists()):
            continue
        # If this src is the keep-row's logo (which it is for same-cat
        # dedupes since slug+cat match), skip — don't delete what we
        # want to keep.
        keep_uses_this_file = False
        for idx, r in enumerate(rows):
            if idx in drop_indices:
                continue
            if slug_for(r) == slug and r["category_slug"] == old_cat:
                # keep row in same dir → its logo is the same file.
                keep_uses_this_file = True
                break
        if not keep_uses_this_file and src not in logo_moves:
            logo_deletes.add(src)

    survivors = [r for i, r in enumerate(rows) if i not in drop_indices]

    print("=" * 70)
    print("PASS 1 — recat")
    print("=" * 70)
    print(f"defi → bridge: {len(recat_bridge)}")
    for n in recat_bridge:
        print(f"  → bridge: {n}")
    print(f"defi → exchange: {len(recat_exchange)}")
    for n in recat_exchange:
        print(f"  → exchange: {n}")
    print()
    print("=" * 70)
    print("PASS 2 — dedupe")
    print("=" * 70)
    print(f"Duplicate groups: {sum(1 for v in groups.values() if len(v) > 1)}, dropping {len(drop_indices)} rows")
    for line in dedupe_summary:
        print(line)
    print()
    print("=" * 70)
    print("PASS 3 — severity")
    print("=" * 70)
    print(f"Rows lowered from 95 to category default: {sev_changes}")
    print()
    print("=" * 70)
    print("RESULT")
    print("=" * 70)
    print(f"Input rows: {len(rows)} → output rows: {len(survivors)} (Δ={len(survivors)-len(rows)})")
    print(f"Logo files to git mv: {len(logo_moves)}")
    print(f"Logo files to git rm: {len(logo_deletes)}")

    if not args.apply:
        print("\n(dry-run; pass --apply to write)")
        return 0

    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in survivors:
            w.writerow({k: r.get(k, "") for k in COLUMNS})

    for src, dst in logo_moves.items():
        git_mv(src, dst)
    for p in sorted(logo_deletes):
        git_rm(p)

    print("\napplied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
