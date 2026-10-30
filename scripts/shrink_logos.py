"""Re-encode heavy logos through the canonical encoder, keeping logo_hash in sync.

jsDelivr stops serving a GitHub repo whose tracked files exceed 50 MB (HTTP 403,
"Package size exceeded the configured limit of 50 MB"). This applies
normalize_png._encode — the same function every enrichment run uses — to the
logos that are already on disk, so that:

  * the bytes on disk equal what the nightly enrichment would produce, and
  * entities.csv `logo_hash` still equals sha256(file). enrich.py trusts that
    equality ("disk is source of truth"); a file that changed without its hash
    would be re-fetched and overwritten at the next run, undoing the shrink.

Only the public logos/<category>/<slug>.png of a CSV row are touched.
logos/_manual/** is the override INPUT tree and is left alone, as are files no
CSV row points at. A re-encode is accepted only if it is at least
QUANTIZE_MIN_GAIN smaller (done inside _encode) and its alpha-composited
difference to the original stays under --max-error (0-255 scale).

Dry-run by default.  Usage:
    python3 scripts/shrink_logos.py                 # report only
    python3 scripts/shrink_logos.py --apply         # write files + logo_hash
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageChops, ImageStat  # noqa: E402

from _base import logo_path_for, read_entities, sha256_hex, write_entities  # noqa: E402
from normalize_png import QUANTIZE_MIN_GAIN, _encode  # noqa: E402

DEFAULT_MAX_ERROR = 8.0


def _flatten(img: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    return Image.alpha_composite(Image.new("RGBA", img.size, bg + (255,)), img).convert("RGB")


def visual_error(a: Image.Image, b: Image.Image) -> float:
    """Mean absolute channel difference (0-255) over white and black backdrops."""
    total = 0.0
    for bg in ((255, 255, 255), (0, 0, 0)):
        diff = ImageChops.difference(_flatten(a, bg), _flatten(b, bg))
        total += sum(ImageStat.Stat(diff).mean) / 3
    return total / 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write files and update logo_hash")
    ap.add_argument("--max-error", type=float, default=DEFAULT_MAX_ERROR)
    args = ap.parse_args()

    rows = read_entities()
    saved = changed = rejected = hash_untouched = 0
    worst = 0.0
    for row in rows:
        path = logo_path_for(row.category_slug, row.slug)
        if path is None or not path.exists():
            continue
        old = path.read_bytes()
        img = Image.open(io.BytesIO(old))
        img.load()
        if img.mode != "RGBA" or img.size != (160, 160):
            continue
        new = _encode(img)
        # Same bar _encode applies to new logos: a few-percent lossless repack is not
        # worth a new hash (and a CDN cache miss) on a public file.
        if len(new) >= len(old) * QUANTIZE_MIN_GAIN:
            continue
        err = visual_error(img, Image.open(io.BytesIO(new)).convert("RGBA"))
        if err > args.max_error:
            rejected += 1
            print(f"reject  {path}  err={err:.2f}")
            continue
        worst = max(worst, err)
        saved += len(old) - len(new)
        changed += 1
        if args.apply:
            in_sync = row.logo_hash == sha256_hex(old)
            path.write_bytes(new)
            if in_sync:
                row.set("logo_hash", sha256_hex(new))
            else:
                # Hash already drifted before this run: leave it alone rather than
                # paper over it — enrich.py treats the mismatch as "refetch me".
                hash_untouched += 1
    if args.apply:
        write_entities(rows)
        # _base.write_entities emits CRLF; the repo stores entities.csv with LF.
        # Put LF back so the diff is the changed logo_hash cells and nothing else.
        csv_path = Path(__file__).resolve().parent.parent / "entities.csv"
        csv_path.write_bytes(csv_path.read_bytes().replace(b"\r\n", b"\n"))
    mode = "applied" if args.apply else "dry-run"
    print(f"{mode}: {changed} files, {saved / 1e6:.2f} MB saved, worst err {worst:.2f}, "
          f"rejected {rejected}, hash left untouched (pre-existing drift) {hash_untouched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
