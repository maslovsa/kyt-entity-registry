"""Fail when the tracked tree is too close to jsDelivr's 50 MB package limit.

jsDelivr refuses to serve a GitHub repo whose files exceed 50 MB in total
(HTTP 403 "Package size exceeded the configured limit of 50 MB"), for every
path, not just the heavy ones. This runs in CI so the limit is hit as a failed
check, with room left to react, instead of as broken logos in production.

Sizes are decimal bytes (50 MB = 50_000_000), the stricter reading of "MB".
The ceiling is deliberately 2 MB below the limit.

    python3 scripts/check_repo_size.py            # CI mode
    python3 scripts/check_repo_size.py --limit 45000000
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

LIMIT_BYTES = 48_000_000      # CI ceiling (jsDelivr's limit is 50_000_000)
WARN_FRACTION = 0.95          # print a warning from 95% of the ceiling


def tracked_sizes(root: Path) -> dict[str, int]:
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    sizes: dict[str, int] = {}
    for rel in out.decode().split("\0"):
        if not rel:
            continue
        p = root / rel
        if p.is_file() and not p.is_symlink():
            sizes[rel] = os.path.getsize(p)
    return sizes


def breakdown(sizes: dict[str, int], depth: int = 2) -> list[tuple[str, int]]:
    by: Counter[str] = Counter()
    for rel, n in sizes.items():
        by["/".join(rel.split("/")[:depth]) if "/" in rel else "(root files)"] += n
    return by.most_common(6)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=LIMIT_BYTES)
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    sizes = tracked_sizes(root)
    total = sum(sizes.values())
    print(f"tracked tree: {total / 1e6:.2f} MB in {len(sizes)} files "
          f"(ceiling {args.limit / 1e6:.0f} MB, jsDelivr limit 50 MB)")
    for name, n in breakdown(sizes):
        print(f"  {n / 1e6:7.2f} MB  {name}")

    if total > args.limit:
        print(f"::error::tracked tree is {total / 1e6:.2f} MB, over the {args.limit / 1e6:.0f} MB "
              "ceiling. jsDelivr returns 403 for the whole repo above 50 MB. Shrink first: "
              "python3 scripts/shrink_logos.py --apply (lower SOFT_QUANTIZE_BYTES in "
              "normalize_png.py if needed).")
        return 1
    if total > args.limit * WARN_FRACTION:
        print(f"::warning::tracked tree is {total / args.limit:.0%} of the ceiling — "
              "headroom is nearly gone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
