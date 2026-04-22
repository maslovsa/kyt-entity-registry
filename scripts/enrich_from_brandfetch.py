"""Fetch a logo from Brandfetch's public CDN.

URL shape: https://cdn.brandfetch.io/<domain>?c=<client_id>

The `c=` client ID is the public Brand Link ID baked into every page
that embeds Brandfetch widgets. It IS safe to hard-code. Runtime can
override via BRANDFETCH_CLIENT_ID env var so Actions can rotate it
without a commit.

Observed behavior (2026-04):
  - Returns image/webp ~1-25 KB. Pillow decodes webp, so we pass the
    bytes straight to normalize_png.
  - 1-2 KB responses are Brandfetch's generic 'lettermark' fallback
    (single-letter on coloured square, often wrong brand colour).
    Reject those; let DefiLlama have a shot.
  - Non-square aspect usually means a wordmark, not a brand mark —
    also reject, the normalizer would letterbox it with transparency.
"""

from __future__ import annotations

import io
import os

import httpx
from PIL import Image

_BASE = "https://cdn.brandfetch.io"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Default CID baked in per CLAUDE.md C7 — public value, safe to inline.
# Prefer env var if set (Actions pulls from secrets).
_DEFAULT_CID = "1ax1776856961656bfumLaCV7mtfLC42Xi"

MIN_BYTES = 3 * 1024        # <3 KB is Brandfetch's lettermark fallback
_MAX_ASPECT_RATIO = 1.6     # wordmarks are usually 2:1 or wider


def _client_id() -> str:
    return os.environ.get("BRANDFETCH_CLIENT_ID") or _DEFAULT_CID


def _is_acceptable(data: bytes) -> bool:
    """Heuristic gate: reject lettermarks and wordmarks."""
    if len(data) < MIN_BYTES:
        return False
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            w, h = im.size
    except Exception:
        return False
    if w == 0 or h == 0:
        return False
    ratio = max(w, h) / min(w, h)
    return ratio <= _MAX_ASPECT_RATIO


def fetch(domain: str, client: httpx.Client | None = None) -> bytes | None:
    """Return raw logo bytes (typically webp) or None."""
    if not domain:
        return None
    domain = domain.strip().lower().lstrip("https://").lstrip("http://").strip("/")
    if not domain:
        return None

    url = f"{_BASE}/{domain}?c={_client_id()}"
    owns_client = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        try:
            r = client.get(url)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        ct = r.headers.get("content-type", "")
        if not ct.startswith("image/"):
            return None
        data = r.content
        if not _is_acceptable(data):
            return None
        return data
    finally:
        if owns_client:
            client.close()


if __name__ == "__main__":
    import sys
    for d in sys.argv[1:]:
        data = fetch(d)
        print(d, "->", "hit" if data else "miss",
              f"({len(data)} B)" if data else "")
