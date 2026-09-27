"""Fetch a logo from Arkham's static bucket.

URL shape: https://static.arkhamintelligence.com/entities/<slug>.png

Observed patterns (2026-04):
  * Exchange slugs are usually stored both as `<brand>-com` and
    `<brand>` (binance-com vs binance). We try both.
  * Hack entities drop the -rekt suffix (alphapo-rekt -> alphapo).
  * Many DeFi protocols are keyed by their DOMAIN with dots
    replaced by dashes (betterbank.io -> betterbank-io,
    deltaprime.io -> deltaprime-io, friend.tech -> friend-tech).
    The upstream CSV often has `arkham_slug=betterbank` (the bare
    brand) but the real file is `betterbank-io`, so we try both
    the literal slug AND the slug with common TLD tails appended.

Strategy: build a small ordered candidate list per row, GET each
until a byte-plausible PNG comes back. First 200 wins. ~10-15
candidates per row caps the cost.

Safety note (2026-09-27): steps 2 and 3 below both *construct* a
candidate slug instead of using the arkham_slug verbatim, and either
can land on a string that happens to be a totally different,
independently-tracked entity's OWN real slug:
  * step 3 (leading segment): "kraken-darknet-market" -> "kraken" ->
    the real Kraken exchange's logo.
  * step 2 (append domain tail): "stake" (Stake DAO's bare slug) ->
    "stake-com" -> the real Stake.com casino's logo. Confirmed live in
    entities.csv: the "Stake DAO" and "Stake.com" rows carry the
    identical logo_hash today because of exactly this.
`fetch()` cannot tell a genuine match from a false one itself -- it
just returns the first 200.

Both steps are also the module's biggest source of real coverage:
most of the time a shared word IS the same brand family under a
different taxonomy tag or domain suffix (Balancer -> "Balancer V2",
"betterbank" -> "betterbank-io"), so unconditionally refusing every
collision would trade a confirmed rare false-positive for a routine,
large false-negative. `known_slugs`, when passed, suppresses a step 2
or step 3 candidate only when it collides with one of the given slugs
-- callers are expected to build that set from real evidence that a
shared word does NOT mean "same brand family" for this specific row
(see enrich.py's HIGH_RISK_CATEGORIES and the canonical_domain-root
mismatch check), not pass it for every row in the registry.
"""

from __future__ import annotations

import re
import time
from typing import Iterable

import httpx

_BASE = "https://static.arkhamintelligence.com/entities"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_RATE_DELAY = 0.12   # ~8 req/sec polite cap on the static bucket

# Suffixes that typically come from "<brand>.tld" becoming
# "<brand>-tld" upstream — strip to recover the bare brand AND also
# try appending them when the arkham_slug looks bare.
_DOMAIN_TAILS = (
    "-com", "-io", "-xyz", "-finance", "-fi", "-network",
    "-protocol", "-app", "-org", "-net", "-exchange",
)
# Descriptor tails applied at upstream — strip only, we never append.
_DESCRIPTOR_TAILS = ("-rekt", "-bridge", "-rekt-2", "-labs")


def _candidates(
    arkham_slug: str, known_slugs: frozenset[str] | None = None,
) -> Iterable[str]:
    seen: set[str] = set()
    candidates: list[str] = []

    def add(s: str) -> None:
        s = s.strip("-")
        if s and s not in seen:
            seen.add(s)
            candidates.append(s)

    add(arkham_slug)

    # 1. If the slug ends with a known tail, strip it. This recovers
    #    "alphapo" from "alphapo-rekt", "binance" from "binance-com".
    base = arkham_slug
    for tail in _DOMAIN_TAILS + _DESCRIPTOR_TAILS:
        if arkham_slug.endswith(tail):
            base = arkham_slug[: -len(tail)]
            add(base)
            break

    # 2. Append each common domain-TLD tail to the *bare brand*
    #    (user's observation: upstream ships "betterbank" but Arkham
    #    stores "betterbank-io"). This is the big coverage win — and,
    #    per the module docstring, also how "stake" (Stake DAO) landed
    #    on "stake-com" (Stake.com)'s real logo. Same guard as step 3.
    for tail in _DOMAIN_TAILS:
        cand = base + tail
        if known_slugs is None or cand not in known_slugs:
            add(cand)

    # 3. Last-resort leading segment — covers "poly-network" ->
    #    "poly", "htx-com-huobi-com" -> "htx". Most of the time this is
    #    the SAME brand under a different taxonomy tag, so it stays
    #    unconditional unless the caller explicitly scoped known_slugs
    #    down to the (rare) rows where that assumption doesn't hold —
    #    e.g. "kraken-darknet-market" -> "kraken" silently returned the
    #    real Kraken exchange's logo, 2026-09-27, because the darknet
    #    market is not a "product line" of the exchange, just a
    #    coincidental name collision.
    head = re.split(r"-", arkham_slug, maxsplit=1)[0]
    if known_slugs is None or head not in known_slugs:
        add(head)

    return candidates


def fetch(
    arkham_slug: str,
    client: httpx.Client | None = None,
    known_slugs: frozenset[str] | None = None,
) -> bytes | None:
    """Return raw PNG bytes or None. Never raises on 404/403/timeout.

    `known_slugs`: the specific OTHER slugs this row must not guess
    into (see the module docstring). Passing it suppresses a step 2
    (append-tail) or step 3 (leading-segment) candidate whenever it
    collides with one of them. Omitting it keeps the old, unguarded
    behavior for one-off/manual callers.
    """
    if not arkham_slug:
        return None

    owns_client = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        for slug in _candidates(arkham_slug, known_slugs=known_slugs):
            url = f"{_BASE}/{slug}.png"
            try:
                r = client.get(url)
            except httpx.HTTPError:
                time.sleep(_RATE_DELAY)
                continue

            time.sleep(_RATE_DELAY)
            if r.status_code != 200:
                continue
            if not r.headers.get("content-type", "").startswith("image/"):
                continue
            data = r.content
            # Arkham sometimes serves a stub 127-byte XML "not found"
            # as 200 at the CDN edge — guard against tiny payloads.
            if len(data) < 200:
                continue
            return data
        return None
    finally:
        if owns_client:
            client.close()


if __name__ == "__main__":
    # Manual probe: python scripts/enrich_from_arkham.py binance-com uniswap
    import sys
    for s in sys.argv[1:]:
        data = fetch(s)
        print(s, "->", "hit" if data else "miss",
              f"({len(data)} B)" if data else "")
