"""Refresh dn_snapshot.json — the cached vasp_entities.display_name map.

Fetches the current list from the aegis-platform Supabase project via the
Management API SQL endpoint. Runs weekly (GHA workflow_dispatch or cron) to
keep the semantic validator's expectations in sync with what the UI actually
resolves at runtime.

The snapshot is committed BACK into the registry repo so PR checks work
without any live DB access — they compare the manifest against whatever
the last refresh saw.

Required env vars (set as GHA repository secrets in kyt-entity-registry):
  SUPABASE_ACCESS_TOKEN — Personal Access Token with sql:execute scope
  SUPABASE_PROJECT_REF  — project ref (e.g. ykvgssjonwlddvfsxjrk)

Usage:
  python3 scripts/refresh_dn_snapshot.py                   # write dn_snapshot.json
  python3 scripts/refresh_dn_snapshot.py --output /tmp/x   # custom path
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

QUERY = (
    "SELECT registry_slug, display_name FROM vasp_entities "
    "WHERE registry_slug IS NOT NULL AND is_archived = false"
)


def fetch() -> list[dict]:
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    ref = os.environ.get("SUPABASE_PROJECT_REF")
    if not token or not ref:
        print("ERROR: SUPABASE_ACCESS_TOKEN or SUPABASE_PROJECT_REF unset", file=sys.stderr)
        sys.exit(2)
    url = f"https://api.supabase.com/v1/projects/{ref}/database/query"
    r = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": QUERY},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "dn_snapshot.json",
    )
    args = ap.parse_args()

    rows = fetch()
    dn_by_slug = {r["registry_slug"]: r["display_name"] for r in rows}
    snap = {
        "schema_version": 1,
        "source": "aegis-platform Supabase vasp_entities",
        "row_count": len(dn_by_slug),
        "display_names": dict(sorted(dn_by_slug.items())),
    }
    args.output.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.output} — {len(dn_by_slug)} display_names")
    return 0


if __name__ == "__main__":
    sys.exit(main())
