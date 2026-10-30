import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import prune_manual_duplicates as p  # noqa: E402


def test_orphan_with_another_copy_of_the_image_is_deletable():
    assert p.decide(None, b"x", b"x", 1) == p.ORPHAN
    assert p.decide(None, b"x", None, 2) == p.ORPHAN


def test_orphan_that_is_the_only_copy_is_kept():
    assert p.decide(None, b"x", None, 0) == p.KEEP_SOLE_COPY


def test_unlocked_row_keeps_its_manual_input_even_if_identical():
    assert p.decide(False, b"x", b"x", 1) == p.KEEP_UNLOCKED


def test_locked_row_with_identical_public_file_is_redundant():
    assert p.decide(True, b"x", b"x", 1) == p.REDUNDANT


def test_locked_row_with_different_public_file_keeps_the_original():
    assert p.decide(True, b"orig", b"re-encoded", 0) == p.KEEP_DIFFERS


def test_locked_row_without_public_file_is_never_deleted():
    assert p.decide(True, b"x", None, 0) == p.KEEP_NO_PUBLIC


def test_twin_orphans_never_both_deleted():
    from collections import Counter
    a, b = Path("a.png"), Path("b.png")
    rows = [(a, p.ORPHAN, 10, "H"), (b, p.ORPHAN, 10, "H")]
    out = {path: label for path, label, _ in p.survivors_gate(rows, Counter({"H": 2}))}
    assert sorted(out.values()) == [p.KEEP_SOLE_COPY, p.ORPHAN]


def test_deletion_allowed_while_a_public_copy_survives():
    from collections import Counter
    rows = [(Path("m.png"), p.REDUNDANT, 10, "H")]
    assert p.survivors_gate(rows, Counter({"H": 2}))[0][1] == p.REDUNDANT
