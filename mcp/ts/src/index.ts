#!/usr/bin/env node
/**
 * kyt-entity-registry MCP server (TypeScript twin of mcp/python).
 *
 * Read-only. Fetches logos/_lookup.json from jsDelivr at startup,
 * caches for process lifetime. Exposes 5 tools + 2 resources over
 * stdio MCP transport.
 *
 * Tool + tokenizer logic is a direct mirror of:
 *   - kyt-entity-registry/lookup.js (browser twin)
 *   - kyt-entity-registry/mcp/python/src/kyt_entity_registry_mcp/server.py
 *
 * Keep the three in sync: stopwords list + labelTokens() + resolve
 * scoring MUST produce identical answers for identical inputs. Tests
 * live in aegis-platform (which already exercises the resolver rules
 * against the registry format).
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import {
  CallToolRequestSchema,
  ListResourcesRequestSchema,
  ListToolsRequestSchema,
  ReadResourceRequestSchema,
} from '@modelcontextprotocol/sdk/types.js'

const LOOKUP_URL =
  process.env.KYT_LOOKUP_URL ??
  'https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/logos/_lookup.json'

// ── types ──────────────────────────────────────────────────────────
interface Entry {
  cat: string
  slug: string
  name: string
  kw: string[]
  imp: number
  real: boolean
}
interface Index {
  version: number
  generated_at: string
  cdn: string
  fallback: string
  category_to_dir: Record<string, string>
  entries: Entry[]
}

// ── tokenizer (mirrors lookup.js::labelTokens) ────────────────────
function labelTokens(label: string): Set<string> {
  if (!label) return new Set()
  const out = new Set<string>()
  const s = String(label)
  const expanded = s
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
  for (const t of expanded.toLowerCase().split(/[^a-z0-9]+/)) {
    if (t.length >= 3 && !/^\d+$/.test(t)) out.add(t)
  }
  if (!s.includes(' ') && s.includes('.')) {
    const joined = s.toLowerCase().replace(/\./g, '')
    if (joined.length >= 4 && /^[a-z0-9]+$/.test(joined)) out.add(joined)
  }
  return out
}

// ── cached fetch ──────────────────────────────────────────────────
let _index: Index | null = null
let _indexPromise: Promise<Index> | null = null
async function getIndex(): Promise<Index> {
  if (_index) return _index
  if (_indexPromise) return _indexPromise
  _indexPromise = (async () => {
    const r = await fetch(LOOKUP_URL)
    if (!r.ok) throw new Error(`lookup fetch ${r.status}`)
    _index = (await r.json()) as Index
    _index.cdn = _index.cdn.replace(/\/+$/, '')
    return _index
  })()
  return _indexPromise
}

function urlFor(idx: Index, cat: string, slug: string): string {
  const dir = idx.category_to_dir[cat]
  if (!dir || !slug) return idx.cdn + idx.fallback
  return `${idx.cdn}/logos/${dir}/${slug}.png`
}

// ── resolver (mirrors lookup.js::resolve) ─────────────────────────
interface ResolveHit {
  url: string
  slug: string
  name: string
  category: string
  real: boolean
  importance: number
}
function resolve(
  idx: Index,
  label: string,
  category?: string,
  preferReal = true,
): ResolveHit | null {
  const tokens = labelTokens(label)
  if (tokens.size === 0) return null
  let best: Entry | null = null
  let bestScore = 0
  for (const e of idx.entries) {
    if (category && e.cat !== category) continue
    let score = 0
    for (const k of e.kw) if (tokens.has(k)) score++
    if (score === 0) continue
    const eff = score + (preferReal && e.real ? 0.5 : 0)
    if (eff > bestScore) {
      best = e
      bestScore = eff
    }
  }
  if (!best) return null
  return {
    url: urlFor(idx, best.cat, best.slug),
    slug: best.slug,
    name: best.name,
    category: best.cat,
    real: best.real,
    importance: best.imp,
  }
}

// ── MCP server ────────────────────────────────────────────────────
const server = new Server(
  { name: 'kyt-entity-registry', version: '0.1.0' },
  { capabilities: { tools: {}, resources: {} } },
)

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'resolve_logo',
      description:
        "Resolve a freeform entity label (e.g. 'Binance Hot Wallet 10' " +
        "or 'Ronin Bridge Hack') to a logo URL on the jsDelivr CDN. " +
        'Uses keyword-overlap scoring; returns null on no match. ' +
        'Pass `category` to restrict matching to one of exchange, ' +
        'dex, defi, bridge, wallet, mining, psp, bot, gambling, ' +
        'nft_marketplace, mixer, hack, sanctioned.',
      inputSchema: {
        type: 'object',
        properties: {
          label: { type: 'string' },
          category: { type: 'string' },
          prefer_real: { type: 'boolean', default: true },
        },
        required: ['label'],
      },
    },
    {
      name: 'list_categories',
      description:
        'Return every category_slug with its entity count and the ' +
        'corresponding logos/ directory name.',
      inputSchema: { type: 'object', properties: {} },
    },
    {
      name: 'list_entities',
      description:
        'Paginated catalogue of entities. Omit `category` to iterate ' +
        'all. Ordered by importance desc, then name.',
      inputSchema: {
        type: 'object',
        properties: {
          category: { type: 'string' },
          limit: { type: 'integer', default: 50 },
          offset: { type: 'integer', default: 0 },
        },
      },
    },
    {
      name: 'get_entity',
      description:
        'Full record for one entity by (category, slug). Returns null ' +
        'if the key is unknown.',
      inputSchema: {
        type: 'object',
        properties: {
          category: { type: 'string' },
          slug: { type: 'string' },
        },
        required: ['category', 'slug'],
      },
    },
    {
      name: 'search_entities',
      description:
        'Top-N fuzzy matches for a query across all (or one) category. ' +
        'Unlike resolve_logo, returns the whole top-N list so the caller ' +
        'can disambiguate.',
      inputSchema: {
        type: 'object',
        properties: {
          query: { type: 'string' },
          category: { type: 'string' },
          limit: { type: 'integer', default: 10 },
        },
        required: ['query'],
      },
    },
  ],
}))

function asText(payload: unknown) {
  return {
    content: [{ type: 'text' as const, text: JSON.stringify(payload) }],
  }
}

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const idx = await getIndex()
  const name = req.params.name
  const args = (req.params.arguments ?? {}) as Record<string, unknown>

  if (name === 'resolve_logo') {
    return asText(
      resolve(
        idx,
        String(args.label ?? ''),
        typeof args.category === 'string' ? args.category : undefined,
        args.prefer_real !== false,
      ),
    )
  }

  if (name === 'list_categories') {
    const counts: Record<string, number> = {}
    for (const e of idx.entries) counts[e.cat] = (counts[e.cat] ?? 0) + 1
    const rows = Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([slug, count]) => ({
        slug, dir: idx.category_to_dir[slug] ?? slug, count,
      }))
    return asText(rows)
  }

  if (name === 'list_entities') {
    const category = typeof args.category === 'string' ? args.category : undefined
    const limit = Math.max(1, Math.min(500, Number(args.limit ?? 50)))
    const offset = Math.max(0, Number(args.offset ?? 0))
    const rows = idx.entries.filter(e => !category || e.cat === category)
    const page = rows.slice(offset, offset + limit).map(e => ({
      slug: e.slug, name: e.name, category: e.cat,
      importance: e.imp, real: e.real,
      url: urlFor(idx, e.cat, e.slug),
    }))
    return asText({ total: rows.length, offset, limit, entries: page })
  }

  if (name === 'get_entity') {
    const category = String(args.category ?? '')
    const slug = String(args.slug ?? '')
    const hit = idx.entries.find(e => e.cat === category && e.slug === slug)
    if (!hit) return asText(null)
    return asText({
      slug: hit.slug, name: hit.name, category: hit.cat,
      keywords: hit.kw, importance: hit.imp, real: hit.real,
      url: urlFor(idx, hit.cat, hit.slug),
    })
  }

  if (name === 'search_entities') {
    const query = String(args.query ?? '')
    const category = typeof args.category === 'string' ? args.category : undefined
    const limit = Math.max(1, Math.min(50, Number(args.limit ?? 10)))
    const tokens = labelTokens(query)
    const scored: Array<{ score: number; entry: Entry }> = []
    for (const e of idx.entries) {
      if (category && e.cat !== category) continue
      let score = 0
      for (const k of e.kw) if (tokens.has(k)) score++
      if (score === 0) continue
      scored.push({ score: score + (e.real ? 0.5 : 0), entry: e })
    }
    scored.sort((a, b) =>
      b.score - a.score || b.entry.imp - a.entry.imp ||
      a.entry.name.localeCompare(b.entry.name),
    )
    return asText(
      scored.slice(0, limit).map(({ score, entry }) => ({
        score, slug: entry.slug, name: entry.name, category: entry.cat,
        real: entry.real, importance: entry.imp,
        url: urlFor(idx, entry.cat, entry.slug),
      })),
    )
  }

  throw new Error(`unknown tool: ${name}`)
})

// ── resources ─────────────────────────────────────────────────────
server.setRequestHandler(ListResourcesRequestSchema, async () => ({
  resources: [
    {
      uri: 'kyt://lookup',
      name: 'lookup index',
      description:
        'Full kyt-entity-registry lookup.json — pre-extracted keywords, ' +
        'importance, real/placeholder flag for every entity. ~80 KB.',
      mimeType: 'application/json',
    },
    {
      uri: 'kyt://categories',
      name: 'categories',
      description: 'List of categories with entity counts.',
      mimeType: 'application/json',
    },
  ],
}))

server.setRequestHandler(ReadResourceRequestSchema, async (req) => {
  const idx = await getIndex()
  const uri = req.params.uri
  if (uri === 'kyt://lookup') {
    return {
      contents: [{
        uri, mimeType: 'application/json', text: JSON.stringify(idx),
      }],
    }
  }
  if (uri === 'kyt://categories') {
    const counts: Record<string, number> = {}
    for (const e of idx.entries) counts[e.cat] = (counts[e.cat] ?? 0) + 1
    const payload = Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([slug, count]) => ({
        slug, dir: idx.category_to_dir[slug] ?? slug, count,
      }))
    return {
      contents: [{
        uri, mimeType: 'application/json', text: JSON.stringify(payload),
      }],
    }
  }
  throw new Error(`unknown resource: ${uri}`)
})

// ── boot ──────────────────────────────────────────────────────────
async function main() {
  const transport = new StdioServerTransport()
  await server.connect(transport)
}

main().catch((err) => {
  // stderr so stdio MCP transport isn't polluted
  console.error('fatal:', err)
  process.exit(1)
})
