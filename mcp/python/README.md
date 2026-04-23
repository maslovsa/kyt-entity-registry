# kyt-entity-registry MCP server (Python)

Read-only MCP server that exposes the kyt-entity-registry logo
catalogue to any Claude Code / Claude Desktop client.

Fetches `logos/_lookup.json` from jsDelivr at startup, caches in
memory for the lifetime of the process. Zero credentials required —
nothing leaves the client machine beyond one GET to the CDN.

## Tools

| Tool | Purpose |
|---|---|
| `resolve_logo` | Freeform label → best-match CDN URL + metadata |
| `list_categories` | All category slugs with entity counts |
| `list_entities` | Paginated catalogue, filter by category |
| `get_entity` | Full record for one `(category, slug)` |
| `search_entities` | Top-N fuzzy matches (disambiguation UI) |

Plus two resources: `kyt://lookup` (full index JSON) and
`kyt://categories`.

## Installing

### Option A — claude-code / claude-desktop, run via `uvx` from git (recommended)

No local clone required. Add to `~/.claude/settings.json` (or the
Claude Desktop equivalent):

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

Restart the client. In a new chat, `/mcp` should list
`kyt-entity-registry` with five tools.

### Option B — local clone + venv

```bash
git clone https://github.com/maslovsa/kyt-entity-registry
cd kyt-entity-registry/mcp/python
uv venv
uv sync                # pulls mcp + httpx
uv run kyt-entity-registry-mcp
```

Then point your MCP config at the full executable path.

## Environment

- `KYT_LOOKUP_URL` — override the default CDN URL. Useful when
  pinning to a specific git SHA for compliance snapshots:
  `https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@<sha>/logos/_lookup.json`.

## Verifying

Quick inspector round-trip:

```bash
npx @modelcontextprotocol/inspector \
  uvx --from . kyt-entity-registry-mcp
```

Call `resolve_logo` with `{"label": "Binance Hot Wallet", "category": "exchange"}`
— expect:

```json
{
  "url": "https://cdn.jsdelivr.net/gh/.../logos/exchanges/binance-com.png",
  "slug": "binance-com",
  "name": "Binance.com",
  "category": "exchange",
  "real": true,
  "importance": 100
}
```
