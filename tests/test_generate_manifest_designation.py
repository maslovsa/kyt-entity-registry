"""Optional `designation` on manifest entries, `sanctioned` untouched."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_manifest as gm  # noqa: E402

ROWS = [
    {"slug": "grinex", "category_slug": "sanctioned", "keywords": "grinex",
     "logo_status": "manual"},
    {"slug": "binance-com", "category_slug": "exchange", "keywords": "binance",
     "logo_status": "manual"},
]


def test_designation_added_only_for_listed_slugs_and_sanctioned_stays():
    m = gm.build_manifest(ROWS, {"grinex": {"list": "ofac_sdn", "id": "OFAC-55045", "date": None}})
    by = {e["slug"]: e for e in m["entries"]}
    assert by["grinex"]["designation"] == {"list": "ofac_sdn", "id": "OFAC-55045", "date": None}
    assert by["grinex"]["sanctioned"] is True
    assert "designation" not in by["binance-com"]
    assert by["binance-com"]["sanctioned"] is False


def test_no_designations_means_manifest_shape_unchanged():
    m = gm.build_manifest(ROWS)
    assert all("designation" not in e for e in m["entries"])


def test_load_designations_drops_malformed_and_missing_file(tmp_path):
    assert gm.load_designations(tmp_path / "nope.json") == {}
    p = tmp_path / "d.json"
    p.write_text(json.dumps({
        "ok": {"list": "uk_hmt", "id": "RUS1", "date": "2025-01-01"},
        "bad": {"list": "uk_hmt"}, "worse": "x",
    }))
    assert gm.load_designations(p) == {"ok": {"list": "uk_hmt", "id": "RUS1", "date": "2025-01-01"}}
