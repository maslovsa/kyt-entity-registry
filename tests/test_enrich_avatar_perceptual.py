import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from PIL import Image, ImageDraw  # noqa: E402

import enrich  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _avatar(bg, fg, shift=0):
    """A grey 'person' avatar: head + shoulders blob on a flat background."""
    im = Image.new("RGBA", (160, 160), bg)
    d = ImageDraw.Draw(im)
    d.ellipse((52 + shift, 22, 108 + shift, 90), fill=fg)
    d.ellipse((20, 100, 140, 230), fill=fg)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def test_default_avatar_is_rejected_whatever_its_colours(monkeypatch):
    """Arkham serves its default avatar in several colourings; the exact bytes differ so a
    sha256 list kept missing it (dark grey, then light blue, 2026-10-14)."""
    ref = enrich._ahash(enrich.normalize(_avatar((205, 215, 222, 255), (102, 119, 136, 255))))
    monkeypatch.setattr(enrich, "_AVATAR_AHASH", ref)
    assert enrich._is_not_a_logo(_avatar((205, 215, 222, 255), (102, 119, 136, 255)))
    # another colouring of the same avatar (silhouette stays darker than its background)
    assert enrich._is_not_a_logo(_avatar((170, 170, 176, 255), (80, 80, 86, 255)))


def test_real_registry_logos_are_not_flagged():
    """Margin check: none of these genuine logos may look like the avatar."""
    for rel in ("logos/defi/aurora-plus.png", "logos/defi/lido-fi.png", "logos/defi/zunami.png",
                "logos/exchanges/binance-com.png"):
        p = ROOT / rel
        if p.exists():
            assert not enrich._is_not_a_logo(p.read_bytes()), rel
