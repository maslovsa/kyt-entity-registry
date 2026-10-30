# kyt-entity-registry MCP server (TypeScript)

TypeScript twin of the Python MCP server — same tool surface
(`resolve_logo`, `list_categories`, `list_entities`, `get_entity`,
`search_entities`) + resources, over stdio.

Use this when your team already uses Node tooling; otherwise the
Python variant at `../python/` is the recommended default.

## Installing — local build

```bash
git clone https://github.com/maslovsa/kyt-entity-registry
cd kyt-entity-registry/mcp/ts
npm install
npm run build
```

Point your MCP client at the built binary:

```json
{
  "mcpServers": {
    "kyt-entity-registry-ts": {
      "command": "node",
      "args": ["/absolute/path/to/kyt-entity-registry/mcp/ts/dist/index.js"]
    }
  }
}
```

## Installing — directly via `npx` from GitHub

No clone required; npm/npx supports installing from a subdirectory:

```json
{
  "mcpServers": {
    "kyt-entity-registry-ts": {
      "command": "npx",
      "args": [
        "-y",
        "github:maslovsa/kyt-entity-registry#main",
        "--prefix=mcp/ts"
      ]
    }
  }
}
```

(npm >= 10; older versions don't support the `--prefix` trick —
use the local-build approach above.)

## Environment

- `KYT_LOOKUP_URL` — override the default CDN URL. Useful for
  compliance snapshots pinned to a git SHA.

## Verifying

```bash
npx @modelcontextprotocol/inspector node dist/index.js
```

Call `resolve_logo` with `{"label": "Binance Hot Wallet", "category": "exchange"}`
— expect the same JSON response as the Python twin.
