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


def test_same_image_groups_by_first_word_when_there_is_no_domain():
    """Rows with no canonical_domain (incident '- REKT' rows, version rows) join their brand's
    group through the first word of the name — but only when the image is identical."""
    rows = [
        _row("Balancer", "balancer", "", "a" * 64),
        _row("Balancer - REKT", "balancer-rekt", "", "a" * 64, cat="hack"),
        _row("BalancerV2", "balancerv2", "", "a" * 64),
        _row("Balancer Labs Clone", "balancer-clone", "", "b" * 64),   # same word, different image
        _row("Bal", "bal", "", "a" * 64),                               # first word < 4 chars: never grouped
    ]
    entries = {e["slug"]: e for e in build_lookup.build(rows)["entries"]}
    assert entries["balancer"]["grp"] == entries["balancer-rekt"]["grp"] == entries["balancerv2"]["grp"]
    assert "grp" not in entries["balancer-clone"]
    assert "grp" not in entries["bal"]


def test_lowtrust_entries_list_generic_keywords_and_keep_all_tokens():
    """Long-tail p2p/scam/... entries keep every name-split keyword (the brand's own label must
    still match) and list the plain-word ones in "gen"; resolvers refuse a one-generic-word match."""
    rows = [
        _row("CoolCoin.best", "coolcoin-best", "coolcoin.best", "d" * 64, cat="p2p"),
        _row("Forsage", "forsage", "forsage.io", "f" * 64, cat="scam"),
        _row("CoolCoin Exchange", "coolcoin-ex", "coolcoin.ex", "e" * 64, cat="exchange"),
    ]
    entries = {e["slug"]: e for e in build_lookup.build(rows)["entries"]}
    assert {"cool", "coin", "best"} <= set(entries["coolcoin-best"]["kw"])
    assert {"best", "coin", "cool"} <= set(entries["coolcoin-best"]["gen"])
    assert "gen" not in entries["forsage"]            # distinctive brand: nothing generic to guard
    assert "gen" not in entries["coolcoin-ex"]        # normal categories unchanged
