"""Delete logos/_manual/** files that nothing can ever read again.

`logos/_manual/<cat>/<slug>.png` is enrich.py's highest-priority INPUT
(`_try_manual`): it is copied to the public path and the row is locked
(`manual_lock=true`). Two kinds of file in that tree are dead weight, and with the
tracked tree capped at jsDelivr's 50 MB (scripts/check_repo_size.py) they matter:

  * ORPHAN   - no entities.csv row maps to this path (a twin in the wrong
               category dir, or a row that no longer exists). enrich.py only ever
               opens manual_path_for(row.category, row.slug), so it never sees it.
               Deleted ONLY when the same image (sha256) also exists elsewhere in
               logos/ - an orphan that is the sole copy of its picture is kept.
  * REDUNDANT - the owning row is manual_lock=true AND the public logo is
               byte-identical. enrich.py skips locked rows before reaching
               _try_manual, and rework_from_report.py refuses to reset them
               ("row is manual_lock=true; skipped"), so the copy is unreachable
               and the public file already holds exactly these bytes.

Kept: anything owned by an UNLOCKED row (still an input), and locked rows whose
public file differs from the manual one (the manual file is then the original that
the public logo was re-encoded from - dropping it would lose the source).
The deleted bytes stay in git history.

Dry-run by default.   python3 scripts/prune_manual_duplicates.py [--apply]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _base import LOGOS_DIR, MANUAL_DIR, logo_path_for, manual_path_for, read_entities  # noqa: E402

ORPHAN = "orphan"
REDUNDANT = "redundant"
KEEP_UNLOCKED = "keep: owned by an unlocked row (still an input)"
KEEP_DIFFERS = "keep: locked row, public file differs (manual file is the original)"
KEEP_NO_PUBLIC = "keep: locked row, public file missing"
KEEP_SOLE_COPY = "keep: orphan, but the only copy of this image"


def decide(owner_locked: bool | None, manual: bytes, public: bytes | None,
           copies_elsewhere: int) -> str:
    """owner_locked is None when no entities.csv row maps to this manual file.
    copies_elsewhere = how many OTHER files in logos/ hold exactly these bytes."""
    if owner_locked is None:
        return ORPHAN if copies_elsewhere > 0 else KEEP_SOLE_COPY
    if not owner_locked:
        return KEEP_UNLOCKED
    if public is None:
        return KEEP_NO_PUBLIC
    return REDUNDANT if public == manual else KEEP_DIFFERS


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def survivors_gate(rows: list[tuple[Path, str, int, str]],
                   total_copies: Counter) -> list[tuple[Path, str, int]]:
    """Never delete the last copy of an image.

    Twin orphans each see the other as "a copy elsewhere"; deleting both loses the
    picture. Walk the deletions and downgrade any that would leave zero copies."""
    left = Counter(total_copies)  # sha256 -> copies in the WHOLE logos/ tree
    out: list[tuple[Path, str, int]] = []
    for path, label, size, sha in rows:
        if label in (ORPHAN, REDUNDANT):
            if left[sha] > 1:
                left[sha] -= 1
            else:
                label = KEEP_SOLE_COPY
        out.append((path, label, size))
    return out


def plan() -> list[tuple[Path, str, int]]:
    copies = Counter(_sha(Path(d, f)) for d, _, fs in os.walk(LOGOS_DIR) for f in fs if f.endswith(".png"))
    owner: dict[Path, tuple[bool, Path | None]] = {}
    for row in read_entities():
        mp = manual_path_for(row.category_slug, row.slug)
        if mp is not None:
            owner[mp.resolve()] = (row.manual_lock, logo_path_for(row.category_slug, row.slug))
    out: list[tuple[Path, str, int, str]] = []
    for d, _, files in os.walk(MANUAL_DIR):
        for f in sorted(files):
            if not f.endswith(".png"):
                continue
            p = Path(d, f)
            locked, public = owner.get(p.resolve(), (None, None))
            pub_bytes = public.read_bytes() if public is not None and public.exists() else None
            data = p.read_bytes()
            others = copies[hashlib.sha256(data).hexdigest()] - 1
            sha = hashlib.sha256(data).hexdigest()
            out.append((p, decide(locked, data, pub_bytes, others), p.stat().st_size, sha))
    return survivors_gate(out, copies)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="delete the files")
    args = ap.parse_args()

    rows = plan()
    delete = [r for r in rows if r[1] in (ORPHAN, REDUNDANT)]
    for label in (ORPHAN, REDUNDANT, KEEP_SOLE_COPY, KEEP_UNLOCKED, KEEP_DIFFERS, KEEP_NO_PUBLIC):
        sel = [r for r in rows if r[1] == label]
        print(f"{len(sel):4d} files {sum(r[2] for r in sel) / 1e6:6.2f} MB  {label}")
    print(f"-> {'deleting' if args.apply else 'would delete'} {len(delete)} files, "
          f"{sum(r[2] for r in delete) / 1e6:.2f} MB")
    if args.apply:
        for p, _, _ in delete:
            p.unlink()
        # drop directories that are now empty
        for d, _, _ in sorted(os.walk(MANUAL_DIR), reverse=True):
            if d != str(MANUAL_DIR) and not os.listdir(d):
                os.rmdir(d)
    assert LOGOS_DIR.exists()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
