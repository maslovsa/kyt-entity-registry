"""kyt-entity-registry MCP server — read-only access to the crypto
entity logo index hosted at
https://github.com/maslovsa/kyt-entity-registry.

Exposes 5 tools (resolve_logo, list_categories, list_entities,
get_entity, search_entities) + 2 resources (kyt://lookup,
kyt://categories) over stdio MCP transport. Consumed by
Claude Code / Claude Desktop / any MCP client."""

__version__ = "0.1.0"
