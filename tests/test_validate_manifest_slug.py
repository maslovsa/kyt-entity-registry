import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import validate_manifest  # noqa: E402


def test_accepts_plain_slugs():
    for slug in ("binance-com", "0x", "a1-b2"):
        assert validate_manifest.check_slug_charset({"slug": slug}) == []


def test_rejects_html_and_path_characters():
    for slug in ("<img src=x>", "a/b", "../x", "A", "-a", "a b", ""):
        assert validate_manifest.check_slug_charset({"slug": slug}), slug
