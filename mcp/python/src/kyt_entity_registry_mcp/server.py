"""MCP stdio server for kyt-entity-registry.

Reads the pre-built lookup index from the jsDelivr CDN at startup,
caches it in memory for the lifetime of the process. Re-fetches on
`refresh_index` (not yet a tool — rely on the hosting MCP client to
restart the process for a fresh index; the landing-page cron updates
the CDN nightly).

Tool surface (kept identical to lookup.js + the TS MCP twin):

  * resolve_logo(label, category?, prefer_real=True)
  * list_categories()
  * list_entities(category?, limit=50, offset=0)
  * get_entity(category, slug)
  * search_entities(query, category?, limit=10)

Resources:

  * kyt://lookup          → full lookup JSON
  * kyt://categories      → list of categories w/ counts

Transport: stdio. Run via `uvx --from git+…` or `kyt-entity-registry-mcp`
once installed in a venv."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
    Resource,
)
from pydantic import AnyUrl

LOOKUP_URL = os.environ.get(
    "KYT_LOOKUP_URL",
    "https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/_lookup.json",
)
_HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

logger = logging.getLogger("kyt-entity-registry-mcp")


# ── stopwords + tokenizer mirror scripts/build_lookup.py + lookup.js ──
# Kept in sync MANUALLY with
#   kyt-entity-registry/scripts/build_lookup.py::_STOPWORDS
#   kyt-entity-registry/lookup.js::labelTokens
# If you change one side, change all three.
_STOPWORDS = frozenset({
    "network", "protocol", "finance", "labs", "foundation", "dao",
    "pool", "swap", "exchange",
    "bridge", "defi", "dex", "mixer", "wallet", "hack",
    "sanctioned", "gambling", "mining", "bot", "psp", "rekt",
    "com", "net", "org", "xyz", "app", "fi",
    "the", "and", "for", "inc", "ltd", "llc", "fund", "group", "team",
})


def _label_tokens(label: str) -> set[str]:
    """Tokenize a freeform label. Mirrors labelTokens() in lookup.js —
    CamelCase expansion + domain-join."""
    if not label:
        return set()
    s = str(label)
    # CamelCase expansion
    expanded = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", s)
    expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", expanded)
    tokens: set[str] = set()
    for t in re.split(r"[^a-z0-9]+", expanded.lower()):
        if len(t) >= 3 and not t.isdigit():
            tokens.add(t)
    # Domain-join: "XT.com" -> also "xtcom"
    if " " not in s and "." in s:
        joined = re.sub(r"\.", "", s.lower())
        if len(joined) >= 4 and re.fullmatch(r"[a-z0-9]+", joined):
            tokens.add(joined)
    return tokens


@dataclass
class Index:
    version: int
    generated_at: str
    cdn: str
    fallback: str
    category_to_dir: dict[str, str]
    entries: list[dict[str, Any]]

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Index":
        return cls(
            version=int(raw.get("version", 1)),
            generated_at=str(raw.get("generated_at", "")),
            cdn=str(raw["cdn"]).rstrip("/"),
            fallback=str(raw["fallback"]),
            category_to_dir=dict(raw["category_to_dir"]),
            entries=list(raw["entries"]),
        )

    def url_for(self, category: str, slug: str) -> str:
        d = self.category_to_dir.get(category)
        if not d or not slug:
            return f"{self.cdn}{self.fallback}"
        return f"{self.cdn}/logos/{d}/{slug}.png"


class RegistryClient:
    """Lazy-fetched, process-wide cached index. One HTTP GET per MCP
    server lifetime; re-invoke by restarting the child process."""

    def __init__(self, url: str = LOOKUP_URL) -> None:
        self._url = url
        self._index: Index | None = None
        self._lock = asyncio.Lock()

    async def index(self) -> Index:
        if self._index is not None:
            return self._index
        async with self._lock:
            if self._index is not None:
                return self._index
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT,
                                        follow_redirects=True) as c:
                r = await c.get(self._url)
                r.raise_for_status()
                self._index = Index.from_json(r.json())
                logger.info(
                    "loaded lookup from %s (%d entries, generated %s)",
                    self._url, len(self._index.entries),
                    self._index.generated_at,
                )
            return self._index


# ── resolve logic (mirrors lookup.js::resolve) ──────────────────────
def _resolve(index: Index, label: str, category: str | None,
             prefer_real: bool) -> dict[str, Any] | None:
    tokens = _label_tokens(label)
    if not tokens:
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    for e in index.entries:
        if category and e["cat"] != category:
            continue
        score = sum(1 for k in e["kw"] if k in tokens)
        if score == 0:
            continue
        real_boost = 0.5 if prefer_real and e["real"] else 0.0
        eff = score + real_boost
        if eff > best_score:
            best = e
            best_score = eff
    if best is None:
        return None
    return {
        "url": index.url_for(best["cat"], best["slug"]),
        "slug": best["slug"],
        "name": best["name"],
        "category": best["cat"],
        "real": bool(best["real"]),
        "importance": int(best["imp"]),
    }


# ── MCP server wiring ──────────────────────────────────────────────
server: Server = Server("kyt-entity-registry")
registry = RegistryClient()


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="resolve_logo",
            description=(
                "Resolve a freeform entity label (e.g. 'Binance Hot Wallet 10' "
                "or 'Ronin Bridge Hack') to a logo URL on the jsDelivr CDN. "
                "Uses keyword-overlap scoring; returns null on no match. "
                "Pass `category` to restrict matching to one of exchange, "
                "dex, defi, bridge, wallet, mining, psp, bot, gambling, "
                "nft_marketplace, mixer, hack, sanctioned."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "category": {"type": "string",
                                 "description": "optional category_slug filter"},
                    "prefer_real": {
                        "type": "boolean", "default": True,
                        "description": "Rank entries with a real brand logo "
                                       "above ones still on placeholder glyph.",
                    },
                },
                "required": ["label"],
            },
        ),
        Tool(
            name="list_categories",
            description="Return every category_slug with its entity count and "
                        "the corresponding logos/ directory name.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_entities",
            description="Paginated catalogue of entities. Omit `category` to "
                        "iterate all. Ordered by importance desc, then name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "limit": {"type": "integer", "default": 50,
                              "minimum": 1, "maximum": 500},
                    "offset": {"type": "integer", "default": 0, "minimum": 0},
                },
            },
        ),
        Tool(
            name="get_entity",
            description="Full record for one entity by (category, slug). "
                        "Returns null if the key is unknown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "slug": {"type": "string"},
                },
                "required": ["category", "slug"],
            },
        ),
        Tool(
            name="search_entities",
            description="Top-N fuzzy matches for a query across all (or one) "
                        "category. Unlike resolve_logo, returns the whole "
                        "top-N list so the caller can disambiguate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "category": {"type": "string"},
                    "limit": {"type": "integer", "default": 10,
                              "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
            },
        ),
    ]


def _as_text(payload: Any) -> list[TextContent]:
    """MCP tool results are wire-level text; JSON-encode for the
    client. Claude unpacks this back into a dict automatically."""
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    idx = await registry.index()

    if name == "resolve_logo":
        label = str(arguments.get("label", ""))
        category = arguments.get("category")
        prefer_real = bool(arguments.get("prefer_real", True))
        return _as_text(_resolve(idx, label, category, prefer_real))

    if name == "list_categories":
        counts: dict[str, int] = {}
        for e in idx.entries:
            counts[e["cat"]] = counts.get(e["cat"], 0) + 1
        payload = [
            {"slug": c, "dir": idx.category_to_dir.get(c, c), "count": n}
            for c, n in sorted(counts.items(), key=lambda kv: -kv[1])
        ]
        return _as_text(payload)

    if name == "list_entities":
        category = arguments.get("category")
        limit = int(arguments.get("limit", 50))
        offset = int(arguments.get("offset", 0))
        rows = [e for e in idx.entries
                if (not category or e["cat"] == category)]
        page = rows[offset:offset + limit]
        payload = [
            {
                "slug": e["slug"], "name": e["name"], "category": e["cat"],
                "importance": e["imp"], "real": bool(e["real"]),
                "url": idx.url_for(e["cat"], e["slug"]),
            }
            for e in page
        ]
        return _as_text({"total": len(rows), "offset": offset,
                         "limit": limit, "entries": payload})

    if name == "get_entity":
        category = str(arguments.get("category", ""))
        slug = str(arguments.get("slug", ""))
        for e in idx.entries:
            if e["cat"] == category and e["slug"] == slug:
                return _as_text({
                    "slug": e["slug"], "name": e["name"], "category": e["cat"],
                    "keywords": list(e.get("kw", [])),
                    "importance": int(e["imp"]),
                    "real": bool(e["real"]),
                    "url": idx.url_for(e["cat"], e["slug"]),
                })
        return _as_text(None)

    if name == "search_entities":
        query = str(arguments.get("query", ""))
        category = arguments.get("category")
        limit = int(arguments.get("limit", 10))
        tokens = _label_tokens(query)
        scored: list[tuple[float, dict[str, Any]]] = []
        for e in idx.entries:
            if category and e["cat"] != category:
                continue
            score = sum(1 for k in e["kw"] if k in tokens)
            if score == 0:
                continue
            scored.append((score + (0.5 if e["real"] else 0), e))
        scored.sort(key=lambda t: (-t[0], -t[1]["imp"], t[1]["name"].lower()))
        top = scored[:limit]
        payload = [
            {
                "score": s, "slug": e["slug"], "name": e["name"],
                "category": e["cat"], "real": bool(e["real"]),
                "importance": int(e["imp"]),
                "url": idx.url_for(e["cat"], e["slug"]),
            }
            for s, e in top
        ]
        return _as_text(payload)

    raise ValueError(f"unknown tool: {name}")


# ── resources ────────────────────────────────────────────────────────
@server.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri=AnyUrl("kyt://lookup"),
            name="lookup index",
            description="Full kyt-entity-registry lookup.json — pre-extracted "
                        "keywords, importance, real/placeholder flag for "
                        "every entity. JSON; ~80 KB.",
            mimeType="application/json",
        ),
        Resource(
            uri=AnyUrl("kyt://categories"),
            name="categories",
            description="List of categories with entity counts.",
            mimeType="application/json",
        ),
    ]


@server.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    idx = await registry.index()
    if str(uri) == "kyt://lookup":
        return json.dumps({
            "version": idx.version,
            "generated_at": idx.generated_at,
            "cdn": idx.cdn,
            "fallback": idx.fallback,
            "category_to_dir": idx.category_to_dir,
            "entries": idx.entries,
        }, ensure_ascii=False)
    if str(uri) == "kyt://categories":
        counts: dict[str, int] = {}
        for e in idx.entries:
            counts[e["cat"]] = counts.get(e["cat"], 0) + 1
        return json.dumps(
            [{"slug": c, "dir": idx.category_to_dir.get(c, c), "count": n}
             for c, n in sorted(counts.items(), key=lambda kv: -kv[1])],
            ensure_ascii=False,
        )
    raise ValueError(f"unknown resource: {uri}")


async def _run() -> None:
    logging.basicConfig(level=logging.WARNING)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
