"""One-shot cleanup: re-categorize `hack` victim rows to `defi`.

Background: ~431 rows under `category_slug=hack` represent DeFi PROTOCOLS
that were hack VICTIMS, not attacker entities. Same heuristic the
promoter side now applies (aegis-platform PR #48 + migration 00123),
backfilled here for the live CSV.

Heuristic (mirror of `apps/data/scripts/export_entity_registry.py`
`_ATTACKER_RX`):

    re.compile(r"(exploit|attacker|hacker|drain|thief)", re.I)

Rules per hack row:
  1. entity_name matches ATTACKER_RX -> KEEP as hack (true attacker brand).
  2. Same entity_name has a non-hack row in CSV -> DELETE the hack row
     (canonical category-row exists elsewhere).
  3. Otherwise -> RE-CATEGORIZE to defi.

For re-categorized rows, the logo (if any) is moved
`logos/hack/<slug>.png -> logos/defi/<slug>.png` via `git mv`. For
deleted hack rows, the orphan logo is `git rm`'d.

`severity` is intentionally NOT touched — left for operator review.

Usage:
    python3 scripts/_oneshot_recat_hack_victims.py             # dry-run
    python3 scripts/_oneshot_recat_hack_victims.py --apply     # write
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from _base import COLUMNS, LOGOS_DIR, CATEGORY_TO_DIR, entity_slug  # noqa: E402

CSV_PATH = REPO_ROOT / "entities.csv"
ATTACKER_RX = re.compile(r"(exploit|attacker|hacker|drain|thief)", re.I)


def slug_for(row: dict) -> str:
    return row.get("arkham_slug") or entity_slug(row.get("entity_name", ""))


def logo_path(category: str, slug: str) -> Path | None:
    d = CATEGORY_TO_DIR.get(category)
    if not d or not slug:
        return None
    return LOGOS_DIR / d / f"{slug}.png"


def git_mv(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "mv", str(src.relative_to(REPO_ROOT)), str(dst.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT,
        check=True,
    )


def git_rm(path: Path) -> None:
    subprocess.run(
        ["git", "rm", str(path.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    rows: list[dict] = []
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: r.get(k, "") for k in COLUMNS})

    # Map entity_name -> set of non-hack categories where it also appears.
    twins: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r["category_slug"] != "hack":
            twins[r["entity_name"]].add(r["category_slug"])

    out: list[dict] = []
    keep_attackers: list[str] = []
    deleted_twins: list[tuple[str, str]] = []  # (name, where_else)
    recat: list[tuple[str, str]] = []  # (name, slug)
    # Dedupe by source path: case-only duplicates (e.g. "Bybit" + "ByBit"
    # collapse to the same slug `bybit`) would otherwise try to git-mv
    # the same file twice and fail on the second pass.
    logo_moves: dict[Path, Path] = {}  # src -> dst
    logo_deletes: set[Path] = set()

    for r in rows:
        if r["category_slug"] != "hack":
            out.append(r)
            continue

        name = r["entity_name"]
        slug = slug_for(r)

        if ATTACKER_RX.search(name):
            keep_attackers.append(name)
            out.append(r)
            continue

        non_hack_twins = twins.get(name, set())
        if non_hack_twins:
            deleted_twins.append((name, ",".join(sorted(non_hack_twins))))
            src_logo = logo_path("hack", slug)
            if src_logo and src_logo.exists():
                logo_deletes.add(src_logo)
            # Skip appending → effectively deletes this row.
            continue

        # Re-categorize to defi.
        new_row = dict(r)
        new_row["category_slug"] = "defi"
        recat.append((name, slug))
        src_logo = logo_path("hack", slug)
        dst_logo = logo_path("defi", slug)
        if src_logo and src_logo.exists() and dst_logo is not None:
            if dst_logo.exists():
                # Pre-existing curated defi logo — drop the hack copy.
                logo_deletes.add(src_logo)
            elif src_logo not in logo_moves:
                logo_moves[src_logo] = dst_logo
        out.append(new_row)

    print(f"Input rows: {len(rows)}")
    print(f"Output rows: {len(out)}")
    print(f"Deleted (hack→twin in non-hack cat exists elsewhere): {len(deleted_twins)}")
    for name, where in deleted_twins:
        print(f"  - {name} (canonical: {where})")
    print(f"Attackers kept as hack: {len(keep_attackers)}")
    for n in keep_attackers:
        print(f"  = {n}")
    print(f"Re-categorized hack→defi: {len(recat)}")
    print(f"Logo files to git mv (hack→defi): {len(logo_moves)}")
    print(f"Logo files to git rm (orphan/dup): {len(logo_deletes)}")

    if not args.apply:
        print("\n(dry-run; pass --apply to write)")
        return 0

    # Write CSV.
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in out:
            w.writerow({k: r.get(k, "") for k in COLUMNS})

    # Move logos (git mv).
    for src, dst in logo_moves.items():
        git_mv(src, dst)

    # Delete orphan logos (git rm).
    for p in sorted(logo_deletes):
        git_rm(p)

    print("\napplied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
