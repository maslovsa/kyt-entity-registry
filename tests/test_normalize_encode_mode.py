import io
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from PIL import Image  # noqa: E402

import normalize_png  # noqa: E402


def test_oversize_logo_quantized_but_stays_rgba_160(monkeypatch):
    """The >50 KB fallback used to emit a palette ("P") PNG, violating C3's
    160x160 RGBA shape. It must come back RGBA."""
    random.seed(7)
    img = Image.new("RGBA", (160, 160))
    img.putdata([(random.randrange(256), random.randrange(256), random.randrange(256), 255)
                 for _ in range(160 * 160)])
    monkeypatch.setattr(normalize_png, "MAX_BYTES", 10)  # force the fallback path
    out = normalize_png._encode(img)
    got = Image.open(io.BytesIO(out))
    assert got.mode == "RGBA" and got.size == (160, 160)
