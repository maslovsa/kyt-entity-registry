import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_lookup  # noqa: E402
from _base import Row  # noqa: E402


def _row(name, slug, domain, h, status="arkham", cat="defi"):
    cols = ["entity_name", "category_slug", "importance", "arkham_slug", "canonical_domain",
            "keywords", "logo_status", "logo_hash"]
    vals = [name, cat, "50", slug, domain, slug, status, h]
    return Row(dict(zip(cols, vals)))


def test_same_brand_same_image_share_grp_and_others_do_not():
    rows = [
        _row("Hatom Lending", "hatom-lending", "app.hatom.com", "a" * 64),
        _row("Hatom LST", "hatom-lst", "hatom.com", "a" * 64),        # same root + same image
        _row("Hatom Other", "hatom-other", "hatom.com", "b" * 64),    # same root, different image
        _row("Lone", "lone", "lone.io", "c" * 64),
        _row("Synth", "synth", "hatom.com", "a" * 64, status="synthetic"),  # not a real logo: not listed at all
    ]
    entries = {e["slug"]: e for e in build_lookup.build(rows)["entries"]}
    assert entries["hatom-lending"]["grp"] == entries["hatom-lst"]["grp"]
    assert "grp" not in entries["hatom-other"]
    assert "grp" not in entries["lone"]
    assert "synth" not in entries


def test_lowtrust_categories_drop_generic_name_tokens_but_keep_the_brand():
    """p2p/scam/darknet_market/staking_provider rows are '<word><word>.best' style names:
    their name-split tokens ('best', 'coin', 'cool') must not become lookup keywords."""
    low = build_lookup._keywords(_row("CoolCoin.best", "coolcoin-best", "coolcoin.best", "d" * 64, cat="p2p"))
    assert "coolcoin" in low
    assert not ({"best", "coin", "cool"} & set(low))
    # a normal category keeps its split tokens (behaviour unchanged for 2800+ entities)
    normal = build_lookup._keywords(_row("CoolCoin.best", "coolcoin-best", "coolcoin.best", "d" * 64, cat="exchange"))
    assert {"cool", "coin", "best"} <= set(normal)
