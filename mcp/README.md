# kyt-entity-registry MCP servers

Two implementations of the same MCP server, both read-only, both
exposing the kyt-entity-registry logo catalogue to Claude Code /
Claude Desktop / any MCP client.

Pick one based on your local tooling; the tool surface is identical.

| | [Python](python/) | [TypeScript](ts/) |
|---|---|---|
| **Runtime**     | Python ≥ 3.10 via `uvx` | Node.js ≥ 18 via `npx` |
| **Setup**       | One JSON block in settings | One JSON block in settings |
| **Install**     | Zero — `uvx` pulls straight from git | Local clone + `npm install && npm run build` |
| **Cold start**  | ~1.2 s (uvx resolve + import) | ~0.3 s |
| **Memory**      | ~35 MB | ~55 MB |
| **Recommended** | ✅ default (simpler install) | Team is Node-first |

## What you get

Five tools — the last two are the ones Claude calls most often:

- `resolve_logo(label, category?, prefer_real=true)` — freeform label →
  best-match CDN URL + metadata. Returns `null` on miss.
- `list_categories()` — every category slug with its entity count.
- `list_entities(category?, limit=50, offset=0)` — paginated catalogue.
- `get_entity(category, slug)` — full record for one entity.
- `search_entities(query, category?, limit=10)` — top-N matches for
  disambiguation.

And two resources: `kyt://lookup` (the whole index as JSON) and
`kyt://categories`.

## How matching works

Same rules as [lookup.js](../lookup.js) in the browser:

1. Tokenize the label (CamelCase-expanded, lowercased, 3+ char
   alphanumeric, stopwords dropped).
2. Score each entry by how many of its pre-extracted keywords
   appear in the token set.
3. Tie-break by importance desc, then by real-vs-placeholder (real
   logos get a 0.5 boost by default).
4. Empty intersection → `null`.

The keyword lists are baked into
[`logos/_lookup.json`](https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/_lookup.json)
by the nightly cron; the MCP server fetches that file once per
process lifetime.

## Keep the three in sync

If you edit matching rules on one side, you must edit all three:

- `scripts/build_lookup.py::_STOPWORDS` + `_keywords()` (keyword
  extraction at build time)
- `lookup.js::labelTokens` (browser / consumer runtime)
- `mcp/python/…/server.py::_STOPWORDS` + `_label_tokens`
- `mcp/ts/src/index.ts::labelTokens`

Drift will cause the same label to resolve differently depending on
which consumer asked — unit tests in
aegis-platform's entity-lookup tests lock the TypeScript twin to a
fixture that mirrors the registry output format.

## See also

- **[docs/MCP.md](../docs/MCP.md)** — tool reference + usage examples.
- **[docs/CONSUMERS.md](../docs/CONSUMERS.md)** — non-MCP consumer
  helpers (canonical `entityLogoUrl`, JS fuzzy resolver).
- **[Python README](python/README.md)**, **[TS README](ts/README.md)**
  for install details.
