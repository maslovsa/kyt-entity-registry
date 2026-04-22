"""Fetch a logo from DefiLlama's icon CDN.

URL shape:
    https://icons.llamao.fi/icons/protocols/<slug>?w=128&h=128

Primarily useful for DeFi protocols. Returns webp at ~1-15 KB,
upstream-rendered at the requested size. We ask for 128 and let the
normalizer upscale to 160 via Lanczos.

DefiLlama uses the same protocol slug as its main site — identical
format to our `arkham_slug`, so we try that directly first.
"""

from __future__ import annotations

import httpx

_BASE = "https://icons.llamao.fi/icons/protocols"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MIN_BYTES = 500   # reject accidental 1-pixel or empty fallbacks


def fetch(slug: str, client: httpx.Client | None = None) -> bytes | None:
    """Return raw logo bytes or None."""
    if not slug:
        return None

    url = f"{_BASE}/{slug}?w=128&h=128"
    owns_client = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        try:
            r = client.get(url)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        if not r.headers.get("content-type", "").startswith("image/"):
            return None
        data = r.content
        if len(data) < _MIN_BYTES:
            return None
        return data
    finally:
        if owns_client:
            client.close()


if __name__ == "__main__":
    import sys
    for s in sys.argv[1:]:
        data = fetch(s)
        print(s, "->", "hit" if data else "miss",
              f"({len(data)} B)" if data else "")
