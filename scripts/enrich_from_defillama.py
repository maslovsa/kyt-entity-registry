"""Fetch a logo from DefiLlama's icon CDN.

URL shape:
    https://icons.llamao.fi/icons/protocols/<slug>?w=128&h=128

Primarily useful for DeFi protocols. Returns webp at ~1-15 KB,
upstream-rendered at the requested size. We ask for 128 and let the
normalizer upscale to 160 via Lanczos.

DefiLlama slugs often differ from arkham_slug — e.g. "curve" vs
"curve-finance", "blueberryprotocol" vs "blueberry", "bedrock-defi"
vs "bedrock". We build a small candidate list and try each.
"""

from __future__ import annotations

import re
from typing import Iterable

import httpx

_BASE = "https://icons.llamao.fi/icons/protocols"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MIN_BYTES = 500   # reject accidental 1-pixel or empty fallbacks

_STRIP_TAILS = (
    "-defi", "-finance", "-protocol", "-dex", "-swap",
    "-exchange", "-labs", "-network", "-dao",
)
_APPEND_TAILS = ("-finance", "-protocol", "-dex")

_DESCRIPTOR_TAILS = (
    "-rekt", "-rekt-2", "-hack", "-loit",
    "-flashloan", "-v2", "-v3", "01", "02", "03",
)


def _candidates(arkham_slug: str) -> Iterable[str]:
    seen: set[str] = set()
    out: list[str] = []

    def add(s: str) -> None:
        s = s.strip("-")
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    add(arkham_slug)

    # Strip descriptor tails: "curve-dex" → "curve"
    base = arkham_slug
    for tail in _STRIP_TAILS + _DESCRIPTOR_TAILS:
        if arkham_slug.endswith(tail):
            base = arkham_slug[: -len(tail)]
            add(base)
            break

    # CamelCase → kebab: "BlueberryProtocol" → "blueberry-protocol"
    kebab = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", arkham_slug).lower()
    add(kebab)
    for tail in _STRIP_TAILS:
        if kebab.endswith(tail):
            add(kebab[: -len(tail)])
            break

    # Compound-word split: "blueberryprotocol" → "blueberry" and
    # "blueberry-protocol" (DefiLlama often uses the hyphenated form).
    for suffix in ("protocol", "finance", "defi", "dao", "swap", "dex",
                   "lend", "lending"):
        if arkham_slug.endswith(suffix) and len(arkham_slug) > len(suffix):
            stem = arkham_slug[: -len(suffix)]
            add(stem)
            add(f"{stem}-{suffix}")

    # Append common tails to base: "curve" → "curve-finance"
    for tail in _APPEND_TAILS:
        add(base + tail)

    return out


def fetch(slug: str, client: httpx.Client | None = None) -> bytes | None:
    """Return raw logo bytes or None. Tries multiple slug candidates."""
    if not slug:
        return None

    owns_client = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        for candidate in _candidates(slug):
            url = f"{_BASE}/{candidate}?w=128&h=128"
            try:
                r = client.get(url)
            except httpx.HTTPError:
                continue
            if r.status_code != 200:
                continue
            if not r.headers.get("content-type", "").startswith("image/"):
                continue
            data = r.content
            if len(data) < _MIN_BYTES:
                continue
            return data
        return None
    finally:
        if owns_client:
            client.close()


if __name__ == "__main__":
    import sys
    for s in sys.argv[1:]:
        data = fetch(s)
        print(s, "->", "hit" if data else "miss",
              f"({len(data)} B)" if data else "")
