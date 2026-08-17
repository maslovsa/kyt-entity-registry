"""Generate simple text/initials placeholder logos for VASPs that have no
real logo (logo_status in {placeholder, none}) after every source in the
C4 chain (arkham/brandfetch/defillama/favicon) has been tried and missed.

This is a MANUAL curation action, not a new automated C4 source: it does
not touch the enrichment pipeline or require an RFC update. It writes a
one-off batch of hand-picked initials images the same way a reviewer's
gallery-exported "suggested_logo_data_url" would via rework_from_report.py
-- to logos/_manual/<category>/<slug>.png AND the public logos/<category>/
<slug>.png path, then flips the CSV row to logo_status=manual,
manual_lock=true.

Text selection, per entity_name:
  - Split into words on whitespace/-/_/./:/,/()/&, drop non-Latin tokens
    (handles "OFAC SDN: Wang Yunhe 王 云禾" style rows), drop a short
    stopword list (ofac/sdn/ofsi/uk/the/stolen/from/sanctioned) and
    generic TLD-ish tokens (com/io/pro/net/org/cc/www), and drop
    version-like tokens (v2, 21, ...) EXCEPT when they're the only/first
    token.
  - One remaining word, <=8 chars -> spell it out in full (uppercased).
    This is the "few letters -> just write them" case.
  - One remaining word, >6 chars -> try splitting it on internal
    capitalization (camelCase / PascalCase compounds like
    "MixedSwapRouter") into sub-words, then apply the two-word rule
    below; otherwise truncate to 6 chars.
  - Two or more remaining words -> initials of the first two words.

Rendering: bold black text on an opaque white 160x160 canvas, matching
the existing generic logos/404.png placeholder's own black-on-white
convention (this is the one case in the registry where a solid white
fill is the established look -- see logos/404.png -- rather than C3's
default transparent-background rule for real per-entity logos).

Usage:
    .venv/bin/python scripts/generate_initials_logos.py            # dry-run
    .venv/bin/python scripts/generate_initials_logos.py --apply    # writes
    .venv/bin/python scripts/generate_initials_logos.py --preview-dir DIR
        # also dumps every candidate PNG into DIR for a visual sanity pass
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _base import (  # type: ignore[import-not-found]
    COLUMNS,
    CSV_PATH,
    LOGOS_DIR,
    Row,
    logo_path_for,
    manual_path_for,
    read_entities,
    sha256_hex,
)
from normalize_png import normalize  # type: ignore[import-not-found]
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
SUPERSAMPLE = 4
CANVAS = 160

# Entity names that are really just raw hex addresses / "unverified
# contract" labels from hack-attribution rows, not real VASP brands --
# an initials monogram would be meaningless for these.
_JUNK_NAME_RE = re.compile(r"0x[0-9a-f]{4,}|^unverified|^[0-9a-f]{4,8}$", re.IGNORECASE)

_STOP = {
    "ofac", "sdn", "ofsi", "uk", "the", "stolen", "from", "sanctioned",
    "com", "io", "pro", "net", "org", "cc", "www",
}
_VERSION_RE = re.compile(r"^v?\d+$", re.IGNORECASE)
_SPLIT_RE = re.compile(r"[\s\-_./:,()&]+")


def _camel_split(word: str) -> list[str]:
    parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)", word)
    return parts if len(parts) > 1 else [word]


def logo_text(entity_name: str) -> str:
    raw_words = [w for w in _SPLIT_RE.split(entity_name) if w]
    latin_words = [w for w in raw_words if re.fullmatch(r"[A-Za-z0-9]+", w)]
    words = [w for w in latin_words if w.lower() not in _STOP] or latin_words or raw_words
    if len(words) > 1:
        filtered = [words[0]] + [w for w in words[1:] if not _VERSION_RE.fullmatch(w)]
        if filtered:
            words = filtered
    if len(words) == 1 and len(words[0]) > 6:
        sub = _camel_split(words[0])
        if len(sub) > 1:
            words = sub
    if not words:
        words = ["?"]
    if len(words) == 1:
        w = words[0]
        return w.upper() if len(w) <= 8 else w[:6].upper()
    return (words[0][0] + words[1][0]).upper()


def is_junk_label(entity_name: str) -> bool:
    return bool(_JUNK_NAME_RE.search(entity_name))


def render_png(text: str) -> bytes:
    """Bold black text, centered, on an opaque white 160x160 canvas.
    Renders at 4x and downsamples for anti-aliasing, auto-shrinking the
    font until the text fits within ~82% of the canvas."""
    big = CANVAS * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Width is the binding constraint for spelled-out words, height for
    # 2-letter initials -- separate caps so both use the canvas fully
    # instead of short strings blowing up while long ones stay small.
    max_w = big * 0.94
    max_h = big * 0.70
    size = big  # start large, shrink to fit
    while size > 4:
        font = ImageFont.truetype(FONT_PATH, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if w <= max_w and h <= max_h:
            break
        size -= max(1, size // 60)
    else:
        font = ImageFont.truetype(FONT_PATH, 4)
        bbox = draw.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]

    x = (big - w) / 2 - bbox[0]
    y = (big - h) / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=(0, 0, 0, 255))

    small = img.resize((CANVAS, CANVAS), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return normalize(buf.getvalue())


def _rewrite_lines(indices_and_rows: list[tuple[int, Row]]) -> None:
    """Surgically replace only the changed data lines in entities.csv,
    byte-identical everywhere else -- unlike _base.write_entities(),
    which rewrites the whole file and would otherwise turn this into a
    ~2900-line diff for a ~180-row change. newline="" on read/write
    disables Python's universal-newline translation, and the file's
    own line ending (found by sniffing the header line) is reused for
    the replaced lines, so this works whether the file is currently
    bare-LF or CRLF (entities.csv has drifted between the two --
    _base.write_entities() emits CRLF, and it's periodically
    renormalized back to LF by hand) without silently flipping every
    untouched line's ending as a side effect."""
    text = CSV_PATH.read_text(encoding="utf-8", newline="")
    eol = "\r\n" if text[: text.index("\n")].endswith("\r") else "\n"
    lines = text.split(eol)
    for idx, row in indices_and_rows:
        buf = io.StringIO()
        w = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="")
        w.writerow([row.raw.get(c, "") for c in COLUMNS])
        lines[idx + 1] = buf.getvalue()  # +1 to skip header
    CSV_PATH.write_text(eol.join(lines), encoding="utf-8", newline="")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write files + update entities.csv")
    ap.add_argument("--preview-dir", type=Path, default=None,
                     help="also dump every candidate PNG here for a visual check")
    ap.add_argument("--limit", type=int, default=None, help="cap number of rows processed")
    args = ap.parse_args()

    rows = read_entities()
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()

    candidates: list[tuple[int, Row, str]] = []
    skipped_junk = 0
    skipped_locked = 0
    for i, row in enumerate(rows):
        if row.logo_status not in ("placeholder", "none"):
            continue
        if row.manual_lock:
            skipped_locked += 1
            continue
        if is_junk_label(row.entity_name):
            skipped_junk += 1
            continue
        candidates.append((i, row, logo_text(row.entity_name)))

    if args.limit:
        candidates = candidates[: args.limit]

    print(f"candidates: {len(candidates)}  "
          f"(skipped manual_lock={skipped_locked}, skipped junk-label={skipped_junk})",
          file=sys.stderr)

    if args.preview_dir:
        args.preview_dir.mkdir(parents=True, exist_ok=True)

    applied: list[tuple[int, Row]] = []
    for i, row, text in candidates:
        manual = manual_path_for(row.category_slug, row.slug)
        public = logo_path_for(row.category_slug, row.slug)
        if manual is None or public is None:
            print(f"  REJECT {row.entity_name!r}: no dir mapping for "
                  f"category={row.category_slug!r} / bad slug {row.slug!r}",
                  file=sys.stderr)
            continue

        png = render_png(text)
        new_hash = sha256_hex(png)

        if args.preview_dir:
            (args.preview_dir / f"{row.category_slug}__{row.slug}__{text}.png").write_bytes(png)

        print(f"  {row.entity_name!r:45s} -> {text:8s} -> {public.relative_to(LOGOS_DIR.parent)} "
              f"({len(png)} B)")

        if args.apply:
            manual.parent.mkdir(parents=True, exist_ok=True)
            manual.write_bytes(png)
            public.parent.mkdir(parents=True, exist_ok=True)
            public.write_bytes(png)
            row.set("logo_status", "manual")
            row.set("logo_updated_at", today)
            row.set("logo_hash", new_hash)
            row.set("manual_lock", "true")
            applied.append((i, row))

    if args.apply and applied:
        _rewrite_lines(applied)
        print(f"\napplied {len(applied)} rows to entities.csv", file=sys.stderr)
    elif not args.apply:
        print(f"\nDRY RUN -- {len(candidates)} would be applied. Pass --apply to write.",
              file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
