"""Fetch a logo from a site's favicon / apple-touch-icon.

Strategy (ordered):
  1. GET https://<domain>/ with a real-browser UA, parse every
     <link rel="icon|apple-touch-icon"> tag, pick the largest
     (apple-touch-icon wins ties — those are usually brand marks,
     not letter-on-square placeholders).
  2. If HTML fetch is blocked (Cloudflare 202/403/503) or no link
     tags found, probe a short list of static paths directly.
  3. Decode with Pillow; reject SVG (we don't rasterise) and
     anything smaller than 32×32 after decode — upscaled to 160
     those look worse than our placeholder.

The normalizer handles the final resize-to-160 + transparent canvas.
"""

from __future__ import annotations

import io
import ipaddress
import logging
import re
import socket
from functools import lru_cache
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15"
)
_HEADERS = {"User-Agent": _UA, "Accept": "text/html,*/*;q=0.9"}

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MIN_SIDE = 32         # reject decoded images with max(w,h) < this
_PREFERRED_SIDE = 64   # prefer candidates at or above this
_MAX_CANDIDATES = 6    # stop probing after this many

# SSRF guard — only allow globally-routable public IPs. Blocks
# loopback (127/8, ::1), RFC1918 (10/8, 172.16/12, 192.168/16),
# link-local (169.254/16 including AWS/GCP metadata endpoints,
# fe80::/10), CGNAT (100.64/10), multicast, reserved, etc.
#
# Defence in depth: the nightly cron runs in GitHub Actions where
# internal addresses don't resolve to anything useful, but any
# consumer running this module locally gets the check for free.
#
# NOT protected: DNS rebinding (a hostname that resolves to a
# public IP at check time and a private one at connect time). For
# the threat model — attacker influences entities.csv via a
# reviewed PR — we accept this gap.
#
# Known domain-parking / registrar-monetization CIDRs. These serve
# template landing pages for expired/dead domains and are sometimes
# re-sold to phishing operators. Legitimate favicons never live here,
# so we refuse to fetch regardless of routability.
# 2026-07-09: added after enrich_from_favicon followed
# protocolmonsters.com to 162.255.119.99 (Namecheap parking),
# triggering a network-egress alert.
_PARKING_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "162.255.116.0/22",  # Namecheap NCNET-5 parking
        "199.59.242.0/23",  # Bodis LLC parking
        "199.188.200.0/22",  # Bluehost/HostGator parking
        "185.53.176.0/22",  # Team Internet / above.com parking
        "204.11.56.0/21",  # DomainMarket / HugeDomains
        "208.100.0.0/16",  # Sedo parking (partial)
    )
)


def _is_public_host(host: str) -> bool:
    """True iff `host` resolves exclusively to globally-routable IPs
    that are not known domain-parking networks. Empty host, resolution
    failure, or any non-global/parking answer → False."""
    if not host:
        return False
    try:
        # getaddrinfo handles both IPv4 and IPv6 + honours /etc/hosts.
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return False
    if not infos:
        return False
    for fam, _type, _proto, _cn, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        # is_global is True only for publicly-routable addresses.
        # Excludes loopback, link-local, private, multicast, reserved.
        if not ip.is_global:
            return False
        # Unwrap IPv4-mapped IPv6 (::ffff:a.b.c.d) before the CIDR
        # comparison below — an IPv6Address never matches an
        # IPv4Network via `in` (silently False, no exception), so
        # without this a parked host answering with an IPv4-mapped
        # AAAA record would sail past _PARKING_NETWORKS undetected.
        check_ip = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) else ip
        if check_ip is not None:
            for net in _PARKING_NETWORKS:
                if check_ip.version == net.version and check_ip in net:
                    logger.warning(
                        "refusing fetch: host %s resolves to %s in known "
                        "parking network %s — entity is likely dead/parked",
                        host, ip, net,
                    )
                    return False
    return True


@lru_cache(maxsize=256)
def _host_allowed(host: str) -> bool:
    """Cached wrapper so repeated candidate URLs on the same host
    only hit DNS once per process. Cleared implicitly when the
    LRU fills, which is fine for a short-lived cron."""
    return _is_public_host(host)


def _url_host_allowed(url: str) -> bool:
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    return _host_allowed((host or "").lower())


def _same_origin(base_url: str, link_url: str) -> bool:
    """True iff `link_url`'s hostname is the same entity as `base_url`'s
    (ignoring a "www." prefix on either side).

    HTML-declared icons can point anywhere — a compromised or parked
    page could serve `<link rel="icon" href="https://attacker.tld/x">`
    and we'd otherwise fetch and ship it as the entity's logo. Confine
    to the domain we were actually told to enrich."""
    try:
        b = urlparse(base_url).hostname or ""
        l = urlparse(link_url).hostname or ""
    except ValueError:
        return False
    if not b or not l:
        return False
    b = b[4:] if b.startswith("www.") else b
    l = l[4:] if l.startswith("www.") else l
    return b == l


# Static fallbacks tried when HTML doesn't expose any <link rel="icon">.
# Order matches real-world quality: apple-touch wins, then favicon PNG,
# then the ICO (which normalize_png handles via Pillow's multi-frame
# decode — we pick the largest frame below).
_STATIC_PATHS = [
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
    "/apple-touch-icon-180x180.png",
    "/apple-touch-icon-152x152.png",
    "/favicon-192x192.png",
    "/favicon-180x180.png",
    "/favicon-96x96.png",
    "/favicon.png",
    "/favicon.ico",
]


def _parse_link_icons(html: str, base_url: str) -> list[tuple[int, bool, str]]:
    """Return list of (declared_size, is_apple_touch, absolute_url).

    `declared_size` is the numeric part of `sizes="192x192"`; 0 when
    missing or "any" (SVG). Callers sort by this and by apple-touch
    priority."""
    icons: list[tuple[int, bool, str]] = []
    for m in re.finditer(r"<link\b[^>]*>", html, re.IGNORECASE):
        tag = m.group(0)
        rel_m = re.search(r'rel\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if not rel_m:
            continue
        rel = rel_m.group(1).lower()
        if "icon" not in rel and "apple-touch-icon" not in rel:
            continue
        href_m = re.search(r'href\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if not href_m:
            continue
        href = href_m.group(1).strip()
        if not href or href.startswith("data:"):
            continue
        size = 0
        size_m = re.search(r'sizes\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if size_m:
            s = size_m.group(1).lower().split()[0]  # "192x192 128x128" -> "192x192"
            if "x" in s:
                try:
                    size = int(s.split("x")[0])
                except ValueError:
                    size = 0
        url = urljoin(base_url, href)
        if url.lower().endswith(".svg"):
            # Pillow can't rasterise SVG. Skip rather than ship a
            # partial implementation.
            continue
        icons.append((size, "apple-touch-icon" in rel, url))
    return icons


def _candidates(domain: str, client: httpx.Client) -> Iterable[str]:
    """Yield candidate icon URLs for this domain, best-quality first.
    Every yielded URL has already passed the SSRF guard — its host
    resolves to a globally-routable IP."""
    # Primary host must be public; skip the whole row otherwise.
    if not _host_allowed(domain):
        return

    base = f"https://{domain}/"
    seen: set[str] = set()

    html_icons: list[tuple[int, bool, str]] = []
    try:
        r = client.get(base, headers=_HEADERS)
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            html_icons = _parse_link_icons(r.text, str(r.url))
    except httpx.HTTPError:
        pass

    # Sort: apple-touch wins ties; then larger declared size wins.
    html_icons.sort(key=lambda t: (not t[1], -t[0]))
    for _, _, url in html_icons:
        if url in seen:
            continue
        # HTML-declared icons can point anywhere — a malicious site
        # could <link rel="icon" href="http://169.254.169.254/">.
        # Check each host before we yield.
        if not _url_host_allowed(url):
            continue
        # ...or off-domain entirely, e.g. a parked page's tracker pixel
        # disguised as a favicon link. Only trust same-origin icons.
        if not _same_origin(base, url):
            continue
        seen.add(url)
        yield url

    for path in _STATIC_PATHS:
        url = f"https://{domain}{path}"
        if url not in seen:
            seen.add(url)
            yield url


def _pick_best_ico_frame(data: bytes) -> bytes:
    """ICO files carry multiple sizes; pick the largest frame and
    re-encode it as PNG bytes (Pillow's default save). If not an ICO
    or decode fails, return the original bytes unchanged."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "ICO":
                return data
            # Pillow exposes ICO sizes via .ico.sizes()
            sizes = sorted(im.ico.sizes(), key=lambda wh: wh[0] * wh[1])
            if not sizes:
                return data
            im.size = sizes[-1]
            im.load()
            out = io.BytesIO()
            im.convert("RGBA").save(out, format="PNG")
            return out.getvalue()
    except Exception:
        return data


def fetch(domain: str, client: httpx.Client | None = None) -> bytes | None:
    """Return raw PNG/JPEG/ICO bytes of the best favicon found, or None."""
    if not domain:
        return None
    # Normalize: strip scheme, trailing slashes, lowercase.
    parsed = urlparse(domain if "://" in domain else f"https://{domain}")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return None

    owns_client = client is None
    client = client or httpx.Client(
        timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS,
    )

    best: tuple[int, bytes] | None = None  # (max_side, bytes)
    try:
        for i, url in enumerate(_candidates(host, client)):
            if i >= _MAX_CANDIDATES:
                break
            try:
                r = client.get(url)
            except httpx.HTTPError:
                continue
            if r.status_code != 200:
                continue
            # Guard against mid-request redirects to a private host.
            # `r.url` is the final URL after any 3xx hops; the pre-
            # fetch check only covered the initial URL.
            if not _url_host_allowed(str(r.url)):
                continue
            ct = r.headers.get("content-type", "")
            if "svg" in ct:
                continue
            raw = r.content
            if len(raw) < 128:
                continue
            if url.lower().endswith(".ico") or "image/x-icon" in ct or "image/vnd.microsoft.icon" in ct:
                raw = _pick_best_ico_frame(raw)
            try:
                with Image.open(io.BytesIO(raw)) as im:
                    im.load()
                    w, h = im.size
            except Exception:
                continue
            side = max(w, h)
            if side < _MIN_SIDE:
                continue
            if best is None or side > best[0]:
                best = (side, raw)
            if side >= _PREFERRED_SIDE:
                # Good enough — stop probing to stay polite to the
                # origin (many sites rate-limit aggressive crawlers).
                break
        return best[1] if best else None
    finally:
        if owns_client:
            client.close()


if __name__ == "__main__":
    import sys
    for d in sys.argv[1:]:
        data = fetch(d)
        print(d, "->", "hit" if data else "miss",
              f"({len(data)} B)" if data else "")
