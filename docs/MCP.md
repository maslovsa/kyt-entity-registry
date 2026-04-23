# MCP reference

This doc is the tool-by-tool reference for the kyt-entity-registry
MCP server. Both the Python and TypeScript implementations expose
the same surface; install instructions live in each subdirectory's
README.

## Configure

Claude Code (`~/.claude/settings.json`) or Claude Desktop
(`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kyt-entity-registry": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/maslovsa/kyt-entity-registry.git#subdirectory=mcp/python",
        "kyt-entity-registry-mcp"
      ]
    }
  }
}
```

Restart the client. `/mcp` in a new chat should list
`kyt-entity-registry` with five tools and two resources.

Pin to a specific git SHA for compliance snapshots:

```json
"env": {
  "KYT_LOOKUP_URL": "https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@<sha>/logos/_lookup.json"
}
```

## Tools

### `resolve_logo`

Freeform label → best-match CDN URL. The workhorse.

| Param | Type | Required | Notes |
|---|---|---|---|
| `label` | string | yes | Any human-readable name — `"Binance Hot Wallet 10"`, `"Uniswap V3 Deposits"`, `"Ronin Bridge Hack"`. |
| `category` | string | no | One of `exchange, dex, bridge, defi, wallet, mining, psp, bot, gambling, nft_marketplace, mixer, hack, sanctioned`. Omit to search across all. |
| `prefer_real` | bool | no (default `true`) | Rank real brand logos above placeholder-only entries. |

Returns:

```json
{
  "url": "https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/exchanges/binance-com.png",
  "slug": "binance-com",
  "name": "Binance.com",
  "category": "exchange",
  "real": true,
  "importance": 100
}
```

Or `null` on no match.

### `list_categories`

No arguments. Returns every category with its logos/ directory
mapping and count:

```json
[
  {"slug": "exchange", "dir": "exchanges", "count": 279},
  {"slug": "hack",     "dir": "hack",      "count": 189},
  {"slug": "dex",      "dir": "dex",       "count": 142},
  …
]
```

### `list_entities`

Paginated catalogue.

| Param | Type | Default | Notes |
|---|---|---|---|
| `category` | string | — | Filter; omit for all. |
| `limit` | int | 50 | 1 to 500. |
| `offset` | int | 0 | |

Returns `{total, offset, limit, entries: [...]}` where each entry
has `{slug, name, category, importance, real, url}`.

### `get_entity`

Full record for one `(category, slug)`. Includes the pre-extracted
keyword list — useful if your agent wants to know how it would
match.

| Param | Type | Required |
|---|---|---|
| `category` | string | yes |
| `slug` | string | yes |

### `search_entities`

Like `resolve_logo` but returns the whole top-N list for
disambiguation UIs.

| Param | Type | Default |
|---|---|---|
| `query` | string | — |
| `category` | string | — |
| `limit` | int | 10 (1-50) |

Each result carries its score, so a human-facing UI can render
confidence indicators.

## Resources

- **`kyt://lookup`** — the entire lookup.json (schema described in
  [CONSUMERS.md](CONSUMERS.md)). Useful when the client wants an
  offline cache or to expose the catalogue in a table.
- **`kyt://categories`** — the same shape as `list_categories()`.

## Example usage in Claude Code

```
User: Render the logo for "Binance Hot Wallet 14" in my report.

Claude: [calls resolve_logo with {label: "Binance Hot Wallet 14"}]
        → https://cdn.jsdelivr.net/gh/.../logos/exchanges/binance-com.png
        ![Binance.com](<that URL>)
```

```
User: What's the closest match for "Aave v3"?

Claude: [calls search_entities with {query: "Aave v3", limit: 5}]
        top match: defi/aave  (Aave, importance=95, score=1.5)
        also: defi/aave-arc   (score=1.5), …
```

## Keep in sync

If you edit matching rules on one side, update all three:

- [`scripts/build_lookup.py`](../scripts/build_lookup.py) — build-time
  keyword extraction.
- [`lookup.js`](../lookup.js) — browser runtime.
- [`mcp/python/…/server.py`](../mcp/python/src/kyt_entity_registry_mcp/server.py)
  + [`mcp/ts/src/index.ts`](../mcp/ts/src/index.ts) — MCP twin runtimes.

The stopword list is duplicated across all four; the tokenizer is
duplicated across the three runtime files. Drift here means the
same label resolves to different entries depending on which consumer
asks.
