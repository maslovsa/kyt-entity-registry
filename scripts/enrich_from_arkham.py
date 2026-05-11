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


def _candidates(arkham_slug: str) -> Iterable[str]:
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
    #    stores "betterbank-io"). This is the big coverage win.
    for tail in _DOMAIN_TAILS:
        add(base + tail)

    # 3. Last-resort leading segment — covers "poly-network" ->
    #    "poly", "htx-com-huobi-com" -> "htx".
    head = re.split(r"-", arkham_slug, maxsplit=1)[0]
    add(head)

    return candidates


def fetch(arkham_slug: str, client: httpx.Client | None = None) -> bytes | None:
    """Return raw PNG bytes or None. Never raises on 404/403/timeout."""
    if not arkham_slug:
        return None

    owns_client = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        for slug in _candidates(arkham_slug):
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
