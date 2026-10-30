from scripts._base import logo_path_for, manual_path_for, LOGOS_DIR


def test_normal_slugs_resolve_inside_logos():
    assert logo_path_for("exchange", "binance-com") == LOGOS_DIR / "exchanges" / "binance-com.png"
    assert manual_path_for("defi", "aave") == LOGOS_DIR / "_manual" / "defi" / "aave.png"


def test_traversal_slugs_rejected():
    assert logo_path_for("exchange", "../../../../.github/workflows/enrich-logos") is None
    assert logo_path_for("exchange", "..") is None
    assert logo_path_for("exchange", "foo/bar") is None
    assert manual_path_for("defi", "../../etc/passwd") is None


def test_empty_or_bad_input_rejected():
    assert logo_path_for("exchange", "") is None
    assert logo_path_for("nope-not-a-category", "binance-com") is None
    assert logo_path_for("exchange", "UPPER-CASE") is None
    assert logo_path_for("exchange", "-leading-dash") is None
