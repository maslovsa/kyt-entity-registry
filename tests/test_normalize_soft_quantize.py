import io
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from PIL import Image  # noqa: E402

import normalize_png  # noqa: E402


def _many_colours() -> Image.Image:
    """Flat shapes plus faint per-pixel noise (like a JPEG-sourced logo): the noise defeats
    lossless deflate, while a 256-colour palette folds it back into the flat colours."""
    random.seed(11)
    base = [(220, 40, 40), (30, 90, 200), (250, 250, 250), (20, 20, 20)]
    img = Image.new("RGBA", (160, 160))
    px = []
    for y in range(160):
        for x in range(160):
            r, g, b = base[(x // 40 + y // 40) % 4]
            n = lambda c: max(0, min(255, c + random.randint(-4, 4)))  # noqa: E731
            px.append((n(r), n(g), n(b), 255 if (x - 80) ** 2 + (y - 80) ** 2 < 75 ** 2 else 0))
    img.putdata(px)
    return img


def test_small_logo_stays_lossless():
    img = Image.new("RGBA", (160, 160), (10, 20, 30, 255))
    out = normalize_png._encode(img)
    assert Image.open(io.BytesIO(out)).convert("RGBA").tobytes() == img.tobytes()


def test_heavy_logo_between_soft_and_hard_cap_is_quantized_and_stays_rgba_160(monkeypatch):
    img = _many_colours()
    lossless = io.BytesIO()
    img.save(lossless, format="PNG", optimize=True)
    # Make the lossless form count as "heavy" regardless of how well the sandbox's
    # zlib happens to compress this synthetic image.
    monkeypatch.setattr(normalize_png, "SOFT_QUANTIZE_BYTES", len(lossless.getvalue()) - 1)
    monkeypatch.setattr(normalize_png, "MAX_BYTES", len(lossless.getvalue()) + 10_000)
    out = normalize_png._encode(img)
    got = Image.open(io.BytesIO(out))
    assert got.mode == "RGBA" and got.size == (160, 160)
    assert len(out) < len(lossless.getvalue()) * normalize_png.QUANTIZE_MIN_GAIN


def test_marginal_quantization_gain_keeps_lossless_bytes(monkeypatch):
    img = Image.new("RGBA", (160, 160), (200, 10, 10, 255))
    lossless = io.BytesIO()
    img.save(lossless, format="PNG", optimize=True)
    monkeypatch.setattr(normalize_png, "SOFT_QUANTIZE_BYTES", 1)  # force the comparison
    out = normalize_png._encode(img)
    assert out == lossless.getvalue()
