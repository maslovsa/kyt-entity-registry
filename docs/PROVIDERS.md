# PROVIDERS — how upstream projects supply fresh entity data

Audience: maintainers of projects that aggregate address labels and
want to propose updates to the canonical entity list. Today that's
**aegis-platform**; tomorrow it may be any KYT-class tool with its
own ingest pipeline.

## Contract

The registry is authoritative for:
- **slug names** (once assigned, never rename — they pin URLs)
- **row membership** (rows never get deleted, they just go dormant
  with `logo_status=none` + `manual_lock=true`)
- **logo files** and their metadata (`logo_status`, `logo_updated_at`,
  `manual_lock`, `logo_hash`)

Providers are authoritative for:
- **discovery** of new entities worth adding
- **importance ranking** (claim_count × trust)
- **networks / sources / severity** columns — purely derivable data

## How aegis-platform ships fresh data

### One-shot (manual)

```bash
# In aegis-platform repo
set -a && source .env && set +a
python scripts/export_entity_registry.py --output /tmp/entities.new.csv

# Review the diff against the live registry
diff <(curl -sL https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/entities.csv) \
     /tmp/entities.new.csv | head -40

# Open PR on kyt-entity-registry with the merged version
# (export script can do this in auto mode — see --pr flag below)
```

### Weekly automation

aegis-platform has `.github/workflows/export-entity-registry.yml`
(target for build-out). Flow:

1. Sunday 12:00 UTC — workflow_dispatch OR cron fires
2. Script queries aegis-platform's `label_claims` → generates a candidate
   CSV (same columns as `entities.csv`)
3. Pulls the LIVE `entities.csv` from
   `cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/entities.csv`
4. Merges:
   - Existing rows: keep `logo_status`, `logo_updated_at`,
     `manual_lock`, `logo_hash` from LIVE; update importance /
     claim_count / max_trust / networks / sources from CANDIDATE
   - New rows: append with `logo_status=none`, blank logo columns
   - Removed rows: NEVER drop. Flip importance to 0, keep slug
     stable, add `_dormant=true` marker column (migration note
     below).
5. Opens a PR against `maslovsa/kyt-entity-registry` titled
   `data: re-export from aegis-platform @ <sha>` with a summary
6. Human (you) reviews: diff should be bounded, no slug renames,
   importance shifts make sense
7. Merge → cron picks up new rows + refreshes stale logos

### Never-do list for providers

- Never PR a deleted row. Rows are immutable.
- Never rename a `entity_name` (and thus the slug) — instead:
  - Add a new row with the new name
  - Add the old slug to the new row's `aliases` column
  - Old row stays with `_dormant=true`
- Never modify `logo_status`, `logo_updated_at`, `manual_lock`,
  `logo_hash` via a provider export. Those are registry-owned
  state. The merge step preserves them.

## The `entities.csv` columns contract

Registry commits to keeping these columns forever (additions OK,
removals require coordinated migration):

| Column | Owner | Description |
|---|---|---|
| `entity_name`      | provider | human-readable name, e.g. "Binance.com" |
| `category_slug`    | provider | one of the 13 canonical slugs |
| `importance`       | provider | 0-100, re-scored each export |
| `claim_count`      | provider | raw count from aegis-platform label_claims |
| `max_trust`        | provider | max trust_weight across contributing sources |
| `severity`         | provider | from risk_categories table |
| `networks`         | provider | `|`-joined network slugs |
| `sources`          | provider | `|`-joined source slugs |
| `arkham_slug`      | provider | lowercase-dash, first enrichment source tries this |
| `canonical_domain` | provider | populated when name looks domain-like |
| `logo_status`      | **registry** | `none` / `arkham` / `brandfetch` / `defillama` / `manual` |
| `logo_updated_at`  | **registry** | ISO date, set by enrichment cron |
| `manual_lock`      | **registry** | `true` → enrichment never overwrites |
| `logo_hash`        | **registry** | sha256 hex; short-circuits unchanged commits |

A future `aliases` column (provider) + `_dormant` column (provider)
will land when we implement rename handling — tracked in
CLAUDE.md task queue.

## Category → directory mapping

When a row carries `category_slug=exchange`, the logo lives at
`logos/exchanges/<slug>.png` (note: plural).

Full map:

| `category_slug` | Directory | Notes |
|---|---|---|
| exchange         | logos/exchanges/ | plural |
| dex              | logos/dex/ | |
| bridge           | logos/bridge/ | |
| defi             | logos/defi/ | |
| wallet           | logos/wallet/ | |
| mining           | logos/mining/ | |
| psp              | logos/psp/ | payment service providers |
| bot              | logos/bot/ | trading bots |
| gambling         | logos/gambling/ | |
| nft_marketplace  | logos/nft_marketplace/ | |
| mixer            | logos/mixer/ | |
| hack             | logos/hack/ | by incident name |
| sanctioned       | logos/sanctioned/ | sanctioning bodies (OFAC, UK OFSI, …) |
| other / unknown  | logos/_fallback/unknown.png | consumer fallback |

Enrichment scripts + consumer resolvers must share this map. It lives
in code as a constant (`scripts/generate_manifest.py` →
`CATEGORY_DIR_MAP`); any change here MUST update that constant in
the same PR — and vice versa.

**Manifest v2 (2026-04-30) makes this asymmetry transparent to
consumers.** Each entry now carries `logo_path` (e.g.
`"logos/exchanges/binance-com.png"`), so badge resolvers don't have
to know the map at all — they just concatenate `<CDN>/<logo_path>`.
The map lives only in the manifest generator.  v1 consumers (no
`logo_path` field) still need this table to build their URLs; that's
the deprecation path off the asymmetry.

## PR review checklist for provider exports

Before merging `data: re-export from ...`:

- [ ] Net new rows look like real new entities (not CSV-parsing noise)
- [ ] No slug renamings (check `git diff entities.csv` for
      `entity_name` mutations — those should manifest as
      *deleted + added* pairs, not inline edits. If inline, block.)
- [ ] Importance shifts have a reason (new hack ingest, new source
      merged into label_claims, etc.)
- [ ] `logo_status` / `logo_updated_at` / `manual_lock` /
      `logo_hash` rows match the LIVE registry values for preserved
      rows (merge step must preserve them)
- [ ] Row count delta is plausible (±20% typical; ±100% warrants
      scrutiny)

## What the provider script looks like (stub)

A working implementation lives in aegis-platform at
`scripts/export_entity_registry.py` once built; shape is:

```python
# pseudocode
candidate_rows = query_supabase_for_entities()       # SQL from docs/kyt_entity_registry_v1 build
live_rows = fetch_csv("https://cdn.jsdelivr.net/gh/maslovsa/kyt-entity-registry@main/entities.csv")
merged = merge_preserving_registry_state(candidate_rows, live_rows)
write_csv("/tmp/entities.new.csv", merged)

if args.pr:
    branch = f"export/{iso_date}"
    # clone kyt-entity-registry, copy CSV, commit, push branch, open PR
    push_to_registry_as_pr(branch, "/tmp/entities.new.csv")
```

Never commit directly to `main` on the registry — always PR. The
registry's `main` is treated as the published CDN state, not a
working branch.
