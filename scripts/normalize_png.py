"""Canonicalize a raw logo to the registry's storage shape.

Shape (from CLAUDE.md C3):
- 160x160 RGBA
- transparent background preserved (no white fill)
- optimized, <= 50 KB
- EXIF / metadata stripped

Accepts PNG / JPEG / WEBP / GIF bytes (whatever Pillow can decode).
SVG is not supported — reject upstream.

Usage:
    from normalize_png import normalize
    png_bytes = normalize(source_bytes)
"""

from __future__ import annotations

import io
from typing import Final

from PIL import Image

CANVAS_SIZE: Final[int] = 160
MAX_BYTES: Final[int] = 50 * 1024


class NormalizeError(ValueError):
    """Raised when the input can't be coerced into the canonical shape."""


def _trim_transparent(img: Image.Image) -> Image.Image:
    """Trim fully-transparent padding before fitting, so the logo fills
    the canvas. No-op if the image has no alpha or no transparent edges."""
    if img.mode != "RGBA":
        return img
    alpha = img.getchannel("A")
    bbox = alpha.getbbox()
    if bbox and bbox != (0, 0, img.width, img.height):
        return img.crop(bbox)
    return img


def normalize(data: bytes) -> bytes:
    """Decode, resize-to-fit 160x160 on transparent canvas, re-encode."""
    if not data:
        raise NormalizeError("empty input")

    try:
        with Image.open(io.BytesIO(data)) as src:
            src.load()
            img = src.convert("RGBA")
    except Exception as e:  # Pillow raises many subclasses; treat uniformly
        raise NormalizeError(f"decode failed: {e}") from e

    img = _trim_transparent(img)

    if img.width == 0 or img.height == 0:
        raise NormalizeError("zero-size image after trim")

    # resize longest edge to CANVAS_SIZE, preserve aspect, then center
    scale = CANVAS_SIZE / max(img.width, img.height)
    new_w = max(1, round(img.width * scale))
    new_h = max(1, round(img.height * scale))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    ox = (CANVAS_SIZE - new_w) // 2
    oy = (CANVAS_SIZE - new_h) // 2
    canvas.paste(resized, (ox, oy), resized)

    out = _encode(canvas)

    if len(out) > MAX_BYTES:
        raise NormalizeError(
            f"output {len(out)} B exceeds {MAX_BYTES} B cap after optimize"
        )
    return out


def _encode(img: Image.Image) -> bytes:
    """Encode PNG with optimize=True. Try palette quantization first
    (smaller) and fall back to full RGBA if quality suffers."""
    # Full RGBA first — Pillow's optimize is a reasonable default. Trying
    # palette quantization can butcher anti-aliased edges on logos with
    # many colors, so only fall back to it if full-RGBA exceeds the cap.
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    raw = buf.getvalue()
    if len(raw) <= MAX_BYTES:
        return raw

    # Quantize preserving alpha (PIL keeps transparency in P mode when
    # the source is RGBA).
    q = img.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    buf = io.BytesIO()
    q.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
