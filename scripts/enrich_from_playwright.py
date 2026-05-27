"""Extended logo enrichment: DefiLlama fuzzy + Google favicon + Playwright favicon.

Three sources in priority order (first hit wins):

  1. DefiLlama fuzzy    — fetch /protocols JSON, match entity_name by normalized
     substring (strips version numbers, "-rekt" suffixes), download from
     icons.llama.fi. Covers defi/dex/bridge without a known domain.

  2. Google favicon     — https://t0.gstatic.com/faviconV2?...&size=256
     Free, no auth. Needs canonical_domain. Works for exchanges/PSPs/gambling.

  3. Playwright favicon — navigate canonical_domain with headless Chromium (handles
     CloudFlare / JS-heavy sites), extract og:image / apple-touch-icon / largest
     header <img>.

Note: Clearbit and Brandfetch CDN are no longer available (410/DNS-fail as of 2026).

Only processes logo_status in (placeholder, none, ""). Skips manual_lock=true.

Usage:
  python3 scripts/enrich_from_playwright.py --dry-run
  python3 scripts/enrich_from_playwright.py --max 40
  python3 scripts/enrich_from_playwright.py --category exchange
  python3 scripts/enrich_from_playwright.py --source defillama  # only one source
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import date
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from _base import Row, logo_path_for, read_entities, sha256_hex, write_entities
from normalize_png import NormalizeError, normalize

REFRESHABLE = {"placeholder", "none", ""}

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── shared HTTP client ─────────────────────────────────────────────────────────

def _get(client: httpx.Client, url: str, timeout: int = 12) -> bytes | None:
    try:
        r = client.get(url, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 800:
            return r.content
    except Exception:
        pass
    return None


def _try_normalize(data: bytes | None) -> bytes | None:
    if not data:
        return None
    try:
        return normalize(data)
    except NormalizeError:
        return None


# ── source 1: DefiLlama fuzzy ────────────────────────────────────────────────

_STRIP = re.compile(
    r"\s+(protocol|finance|network|exchange|dex|aggregator|platform|dao|"
    r"labs?|app|solutions?)\s*$",
    re.I,
)
_RE_REKT    = re.compile(r"\s*[-–]\s*rekt.*$", re.I)
_RE_EXTRA   = re.compile(r"\s*\([^)]*\)")
_RE_VERSION = re.compile(r"\s+v?\d+(\.\d+)?\s*$", re.I)
_RE_NUM_SFX = re.compile(r"\s+\d+\s*$")


def _norm(s: str) -> str:
    s = _RE_REKT.sub("", s)
    s = _RE_EXTRA.sub("", s)
    s = _RE_VERSION.sub("", s)
    s = _RE_NUM_SFX.sub("", s)
    s = _STRIP.sub("", s)
    return re.sub(r"\s+", " ", s).lower().strip()


def _load_defillama() -> list[dict]:
    print("fetching DefiLlama protocols…", file=sys.stderr)
    with httpx.Client(timeout=60, headers={"User-Agent": "kyt-registry/1.0"}) as c:
        r = c.get("https://api.llama.fi/protocols")
        r.raise_for_status()
        data = r.json()
    print(f"  {len(data)} protocols", file=sys.stderr)
    return data


def _build_defillama_index(protocols: list[dict]) -> dict[str, str]:
    """normalized_name → logo_url"""
    idx: dict[str, str] = {}
    for p in protocols:
        name = (p.get("name") or "").strip()
        logo = (p.get("logo") or "").strip()
        if name and logo:
            idx[_norm(name)] = logo
    return idx


def defillama_fuzzy(
    client: httpx.Client,
    entity_name: str,
    slug: str,
    index: dict[str, str],
) -> bytes | None:
    key = _norm(entity_name)
    # exact normalized match first
    logo_url = index.get(key)
    if not logo_url:
        # substring scan — entity key contained in a protocol name
        for k, url in index.items():
            if key and key in k:
                logo_url = url
                break
    if not logo_url:
        # slug scan
        slug_key = slug.replace("-", " ").lower()
        for k, url in index.items():
            if slug_key and slug_key in k:
                logo_url = url
                break
    if not logo_url:
        return None
    return _try_normalize(_get(client, logo_url))


# ── source 2: Google favicon ──────────────────────────────────────────────────

_GFAV = (
    "https://t0.gstatic.com/faviconV2"
    "?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL"
    "&url=https://{domain}&size=256"
)
_GFAV_MIN = 1_200  # Google returns a tiny grey placeholder when unknown


def google_favicon(client: httpx.Client, domain: str) -> bytes | None:
    if not domain:
        return None
    url = _GFAV.format(domain=domain)
    data = _get(client, url)
    if data and len(data) >= _GFAV_MIN:
        return _try_normalize(data)
    return None


# ── source 3: Playwright favicon ──────────────────────────────────────────────

def _pw_logo(page: Page, client: httpx.Client, domain: str) -> bytes | None:
    if not domain:
        return None
    base = f"https://{domain}"
    try:
        page.goto(base, timeout=20_000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
    except Exception:
        return None

    # og:image
    for sel in [
        'meta[property="og:image"]',
        'meta[name="twitter:image"]',
        'link[rel="apple-touch-icon"]',
        'link[rel="icon"][sizes]',
    ]:
        el = page.query_selector(sel)
        if not el:
            continue
        url = el.get_attribute("content") or el.get_attribute("href") or ""
        if url and not url.endswith(".svg") and not url.endswith(".ico"):
            if not url.startswith("http"):
                url = base.rstrip("/") + "/" + url.lstrip("/")
            data = _try_normalize(_get(client, url))
            if data:
                return data

    # largest <img> in the header / nav
    for img in page.query_selector_all("header img, nav img, [class*='logo'] img")[:6]:
        url = img.get_attribute("src") or ""
        if url and not url.endswith(".svg"):
            if not url.startswith("http"):
                url = base.rstrip("/") + "/" + url.lstrip("/")
            data = _try_normalize(_get(client, url))
            if data:
                return data
    return None


# ── main ───────────────────────────────────────────────────────────────────────

SOURCES = ("defillama", "google", "playwright")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int)
    ap.add_argument("--category")
    ap.add_argument("--source", choices=SOURCES)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    rows = read_entities()
    candidates = [
        r for r in rows
        if r.logo_status in REFRESHABLE
        and not r.manual_lock
        and r.slug
        and (args.category is None or r.category_slug == args.category)
    ]
    candidates.sort(key=lambda r: -r.importance)
    if args.max:
        candidates = candidates[: args.max]

    print(f"candidates: {len(candidates)}", file=sys.stderr)

    # pre-load DefiLlama index once
    dl_index: dict[str, str] = {}
    if args.source in (None, "defillama"):
        dl_index = _build_defillama_index(_load_defillama())

    stats: dict[str, int] = {s: 0 for s in SOURCES}
    stats.update({"miss": 0, "written": 0, "unchanged": 0})

    with httpx.Client(
        timeout=15,
        follow_redirects=True,
        headers={"User-Agent": UA},
    ) as http_client, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        pw_page  = browser.new_page(user_agent=UA, viewport={"width": 1280, "height": 800})

        for row in candidates:
            slug   = row.slug
            cat    = row.category_slug
            domain = row.canonical_domain
            name   = row.entity_name

            dest = logo_path_for(cat, slug)
            if dest is None:
                continue

            png: bytes | None = None
            source = ""

            if png is None and args.source in (None, "defillama") and dl_index:
                png = defillama_fuzzy(http_client, name, slug, dl_index)
                if png:
                    source = "defillama"
                    stats["defillama"] += 1

            if png is None and args.source in (None, "google") and domain:
                png = google_favicon(http_client, domain)
                if png:
                    source = "google"
                    stats["google"] += 1

            if png is None and args.source in (None, "playwright") and domain:
                png = _pw_logo(pw_page, http_client, domain)
                if png:
                    source = "playwright"
                    stats["playwright"] += 1

            if png is None:
                stats["miss"] += 1
                if args.verbose:
                    print(f"miss     {name}", file=sys.stderr)
                continue

            new_hash = sha256_hex(png)
            if dest.exists() and sha256_hex(dest.read_bytes()) == new_hash:
                stats["unchanged"] += 1
                if args.verbose:
                    print(f"same     {name}", file=sys.stderr)
                continue

            print(f"+ {source:12s}  {name}  ({len(png)} B)", file=sys.stderr)

            if not args.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(png)
                row.set("logo_status", source)
                row.set("logo_updated_at", str(date.today()))
                row.set("logo_hash", new_hash)
                stats["written"] += 1

        browser.close()

    print("\n---", file=sys.stderr)
    for k, v in stats.items():
        print(f"  {k:12s}: {v}", file=sys.stderr)

    if not args.dry_run and stats["written"] > 0:
        write_entities(rows)
        print("CSV: entities.csv", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
