"""Generate og-preview.png — the 1200x630 image linked from the
landing page's <meta property="og:image">.

Composition: a 10-column strip of real logos forming the top band,
with a dark gradient over the bottom half and a title + tagline on
top. Pure Pillow, no external deps beyond the existing Pillow pin.

Usage:
    python scripts/build_og_preview.py

Writes ../og-preview.png (repo root) — that's the file referenced
from index.html's OpenGraph tags. Commit it alongside the landing
changes. Regenerate whenever the landing copy or logo coverage
changes meaningfully; not part of the nightly cron (would churn
every commit).
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-not-found]

from _base import LOGOS_DIR, REPO_ROOT  # type: ignore[import-not-found]

OUT = REPO_ROOT / "og-preview.png"
W, H = 1200, 630
TILE = 80                   # 80-px thumbnails sit nicely at this canvas size
COLS = W // TILE            # 15 tiles per row
ROWS = H // TILE            # 7 rows
MARGIN = 0                  # quilt fills the whole canvas

BG = (247, 247, 250, 255)   # --background light
FG = (35, 35, 37, 255)      # --foreground
BRAND = (214, 70, 134, 255) # --brand
MUTED = (98, 99, 104, 255)  # --muted-foreground


def _load_font(size: int, weight: str = "Regular") -> ImageFont.ImageFont:
    """Try Helvetica/Manrope/Inter from common system paths, fall
    back to Pillow's bundled default so the script works offline."""
    candidates = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _pick_logos() -> list[Path]:
    """Real-only logo paths from _lookup.json, shuffled deterministically."""
    idx_path = LOGOS_DIR / "_lookup.json"
    if not idx_path.exists():
        return []
    idx = json.loads(idx_path.read_text())
    entries = [e for e in idx["entries"] if e["real"]]
    # Deterministic shuffle for reproducible builds — same input = same png.
    rnd = random.Random(42)
    rnd.shuffle(entries)
    dirs = idx["category_to_dir"]
    paths: list[Path] = []
    for e in entries:
        p = LOGOS_DIR / dirs[e["cat"]] / f"{e['slug']}.png"
        if p.exists():
            paths.append(p)
        if len(paths) >= COLS * ROWS:
            break
    return paths


def _compose_quilt(canvas: Image.Image, logos: list[Path]) -> None:
    for i, logo_path in enumerate(logos):
        col, row = i % COLS, i // COLS
        x, y = col * TILE, row * TILE
        try:
            with Image.open(logo_path) as im:
                im = im.convert("RGBA")
                # Keep 10-px padding inside each tile so the logo
                # breathes and we don't overwhelm the composition.
                scale = (TILE - 12) / max(im.width, im.height)
                w, h = round(im.width * scale), round(im.height * scale)
                im = im.resize((w, h), Image.Resampling.LANCZOS)
                canvas.paste(im, (x + (TILE - w) // 2, y + (TILE - h) // 2), im)
        except Exception:
            continue


def _compose_overlay(canvas: Image.Image) -> None:
    # Dark gradient fading from transparent at the top to 85% bottom so
    # the text area is readable whatever logos land there.
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov = ImageDraw.Draw(overlay)
    for yy in range(H):
        alpha = int(max(0, min(225, (yy - H * 0.35) * 1.5)))
        ov.line([(0, yy), (W, yy)], fill=(15, 15, 18, alpha))
    canvas.alpha_composite(overlay)


def _compose_text(canvas: Image.Image) -> None:
    d = ImageDraw.Draw(canvas)
    # Eyebrow
    eyebrow_font = _load_font(22)
    d.text((70, H - 240), "KYT-ENTITY-REGISTRY",
           font=eyebrow_font, fill=BRAND)

    # Title
    title_font = _load_font(64)
    title = "Open logo registry\nfor every crypto entity"
    d.multiline_text((70, H - 200), title, font=title_font,
                     fill=(255, 255, 255, 255), spacing=6)

    # Subtitle
    sub_font = _load_font(22)
    sub = "800+ exchanges · DEX · bridges · mixers · hacks   ·   free via jsDelivr + MCP"
    d.text((70, H - 60), sub,
           font=sub_font, fill=(220, 220, 225, 255))


def main() -> int:
    canvas = Image.new("RGBA", (W, H), BG)
    logos = _pick_logos()
    if logos:
        _compose_quilt(canvas, logos)
    _compose_overlay(canvas)
    _compose_text(canvas)
    canvas.convert("RGB").save(OUT, format="PNG", optimize=True)
    print(f"wrote {OUT.relative_to(REPO_ROOT)} ({OUT.stat().st_size} B, "
          f"{len(logos)} logos used)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
