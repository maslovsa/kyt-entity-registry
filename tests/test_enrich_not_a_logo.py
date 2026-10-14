import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import enrich  # noqa: E402
from _base import sha256_hex  # noqa: E402
from normalize_png import normalize  # noqa: E402
from PIL import Image  # noqa: E402


def _png(color):
    buf = io.BytesIO()
    Image.new("RGBA", (300, 300), color).save(buf, "PNG")
    return buf.getvalue()


def test_blocklisted_image_is_rejected(monkeypatch):
    """Regression (2026-10-14): Arkham's grey default-avatar silhouette was
    stored as a real logo for KaoyaSwap / Moola Market / Sigma Money."""
    raw = _png((100, 110, 130, 255))
    monkeypatch.setattr(enrich, "_NOT_A_LOGO_HASHES",
                        frozenset({sha256_hex(normalize(raw))}))
    assert enrich._is_not_a_logo(raw)


def test_ordinary_image_is_accepted():
    assert not enrich._is_not_a_logo(_png((200, 30, 30, 255)))


def test_real_guard_hash_is_well_formed():
    assert enrich._NOT_A_LOGO_HASHES
    assert all(len(h) == 64 for h in enrich._NOT_A_LOGO_HASHES)
