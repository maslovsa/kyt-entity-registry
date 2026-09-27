import sys
from pathlib import Path

from scripts.enrich_from_arkham import _candidates

# enrich.py imports sibling modules as `from _base import ...` (it's
# normally run as a script, not a package) — importing it as
# scripts.enrich would break that. Mirror what enrich.py itself does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def test_leading_segment_suppressed_when_head_collides_with_known_slug():
    """Regression (2026-09-27): "kraken-darknet-market" -> "kraken" as a
    last-resort guess returned the real Kraken exchange's own logo. If
    "kraken" is in the caller-supplied known_slugs set, the guess must
    not be offered as a candidate at all."""
    known = frozenset({"kraken", "kraken-com"})
    candidates = list(_candidates("kraken-darknet-market", known_slugs=known))
    assert "kraken" not in candidates


def test_leading_segment_still_offered_without_collision():
    """Same shape of slug, but nothing in the given set claims the bare
    head — the last-resort guess is still worth trying."""
    candidates = list(_candidates("htx-com-huobi-com", known_slugs=frozenset()))
    assert "htx" in candidates


def test_leading_segment_offered_when_known_slugs_omitted():
    """Callers that don't pass known_slugs (manual probes, older
    scripts) keep the old, unguarded behavior."""
    candidates = list(_candidates("kraken-darknet-market"))
    assert "kraken" in candidates


def test_other_candidates_unaffected_by_collision():
    """The guard only suppresses the step-3 bare-head guess — literal,
    suffix-stripped, and domain-tail candidates are untouched."""
    known = frozenset({"kraken"})
    candidates = list(_candidates("kraken-darknet-market", known_slugs=known))
    assert "kraken-darknet-market" in candidates


def test_append_tail_suppressed_when_it_collides_with_known_slug():
    """Regression (2026-09-27): "stake" (Stake DAO's bare arkham_slug)
    appends "-com" at step 2 and lands on "stake-com" — Stake.com the
    casino's own registered slug. Confirmed live: both rows carry the
    identical logo_hash today. The step-2 append loop must respect
    known_slugs exactly like step 3."""
    known = frozenset({"stake-com"})
    candidates = list(_candidates("stake", known_slugs=known))
    assert "stake-com" not in candidates
    # every other domain-tail variant is still offered
    assert "stake-io" in candidates


def test_append_tail_offered_without_collision():
    candidates = list(_candidates("betterbank", known_slugs=frozenset()))
    assert "betterbank-io" in candidates


def test_deny_slugs_for_arms_guard_for_high_risk_category():
    """A row in HIGH_RISK_CATEGORIES (sanctioned/mixer/hack) gets every
    non-risky-category slug denied outright — that's the guard that
    catches "kraken-darknet-market" -> "kraken"."""
    import enrich

    class Sanctioned:
        arkham_slug = "kraken-darknet-market"
        category_slug = "sanctioned"
        canonical_domain = ""

    class Kraken:
        arkham_slug = "kraken"
        category_slug = "exchange"
        canonical_domain = ""

    rows = [Sanctioned(), Kraken()]
    deny_slugs_for = enrich._build_deny_slugs_fn(rows)
    assert "kraken" in deny_slugs_for(Sanctioned())


def test_deny_slugs_for_arms_guard_on_domain_root_mismatch():
    """Regression (2026-09-27): Stake DAO (canonical_domain=stakedao.org,
    category=defi — NOT in HIGH_RISK_CATEGORIES) must still have
    "stake-com" denied, because Stake.com's own canonical_domain
    (stake.com) has a different root ("stake" != "stakedao"). Neither
    row is high-risk-category, so this can only come from the
    domain-root check."""
    import enrich

    class StakeDAO:
        arkham_slug = "stake"
        category_slug = "defi"
        canonical_domain = "stakedao.org"

    class StakeCom:
        arkham_slug = "stake-com"
        category_slug = "gambling"
        canonical_domain = "stake.com"

    class BalancerV2:
        """Control: no canonical_domain of its own, and not high-risk
        — must NOT get an armed guard at all (empty deny set)."""
        arkham_slug = "balancer-v2"
        category_slug = "defi"
        canonical_domain = ""

    rows = [StakeDAO(), StakeCom(), BalancerV2()]
    deny_slugs_for = enrich._build_deny_slugs_fn(rows)

    assert "stake-com" in deny_slugs_for(StakeDAO())
    assert deny_slugs_for(BalancerV2()) == frozenset()


def test_domain_root_extraction():
    import enrich

    assert enrich._domain_root("stakedao.org") == "stakedao"
    assert enrich._domain_root("portal.arbitrum.io") == "arbitrum"
    assert enrich._domain_root("") is None
    assert enrich._domain_root(None) is None
