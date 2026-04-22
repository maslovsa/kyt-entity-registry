"""Fetch a logo from Arkham's static bucket.

URL shape: https://static.arkhamintelligence.com/entities/<slug>.png

Observed quirks (2026-04):
  - Exchange slugs drop TLD suffixes: binance-com -> binance,
    bybit-com -> bybit, htx-com-huobi-com -> ... harder, usually misses
  - Hack entities drop the -rekt suffix: alphapo-rekt -> alphapo

Strategy: try a short ordered list of candidate slugs per row. First
HTTP 200 wins. Abort after ~3 candidates to stay polite.
"""

from __future__ import annotations

import re
import time
from typing import Iterable

import httpx

_BASE = "https://static.arkhamintelligence.com/entities"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_RATE_DELAY = 0.2  # 5 req/sec polite cap on the static bucket

# Suffix families to try stripping, in order. Kept short to stay polite.
_STRIP_TAILS = ("-com", "-io", "-net", "-org", "-rekt", "-bridge")


def _candidates(arkham_slug: str) -> Iterable[str]:
    seen: set[str] = set()
    candidates: list[str] = []

    def add(s: str) -> None:
        s = s.strip("-")
        if s and s not in seen:
            seen.add(s)
            candidates.append(s)

    add(arkham_slug)
    for tail in _STRIP_TAILS:
        if arkham_slug.endswith(tail):
            add(arkham_slug[: -len(tail)])
    # Also try the leading segment before the first '-' when the slug
    # looks like "poly-network" or "htx-com-huobi-com" — one more shot.
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
