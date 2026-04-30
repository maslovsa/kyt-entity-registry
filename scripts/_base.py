"""Shared helpers for the enrichment pipeline.

Scope: file paths, CSV read/write, hashing, slug normalization, and
category -> directory mapping. Every enrich_from_*.py imports from here
so the contract stays in one place.

If you edit the category map or slug rules, you MUST update
docs/CONSUMERS.md + its TS/Python helpers in lockstep, otherwise logos
will 404 in production.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "entities.csv"
LOGOS_DIR = REPO_ROOT / "logos"
MANUAL_DIR = LOGOS_DIR / "_manual"
FALLBACK_PNG = LOGOS_DIR / "_fallback" / "unknown.png"

# Full column set the registry owns. Older CSVs may lack `logo_hash`
# or `aliases` — read_entities() fills missing keys with "".
#
# 2026-04-30: added `keywords` + `product_aliases` (between
# canonical_domain and logo_status, matching entities.csv header).
# Earlier commit `7ee38cb` (vasp-gap-audit v3 Group H + keywords
# backfill) introduced these columns to the CSV, but `enrich.py`
# wrote with the old COLUMNS list and `extrasaction="ignore"` —
# silently stripping them every nightly run.  See commit `b7a906b`
# for an example of the regression.  Without this fix consumers of
# the manifest (Aegis UI, lookup.js) lose all keyword-driven badge
# detection on every cron run.
COLUMNS = [
    "entity_name",
    "category_slug",
    "importance",
    "claim_count",
    "max_trust",
    "severity",
    "networks",
    "sources",
    "arkham_slug",
    "canonical_domain",
    "keywords",
    "product_aliases",
    "logo_status",
    "logo_updated_at",
    "manual_lock",
    "logo_hash",
]

# category_slug -> logos/<dir>/ name. Mirrors docs/CONSUMERS.md exactly.
CATEGORY_TO_DIR: dict[str, str] = {
    "exchange": "exchanges",
    "dex": "dex",
    "bridge": "bridge",
    "defi": "defi",
    "wallet": "wallet",
    "mining": "mining",
    "psp": "psp",
    "bot": "bot",
    "gambling": "gambling",
    "nft_marketplace": "nft_marketplace",
    "mixer": "mixer",
    "hack": "hack",
    "sanctioned": "sanctioned",
}

_STRIP_SUFFIXES = [
    " network", " exchange", " protocol", " finance",
    " labs", " foundation", " dao", " pool", " swap",
]


def entity_slug(entity_name: str) -> str:
    """Normalize entity_name -> filesystem slug. Mirrors CONSUMERS.md."""
    s = (entity_name or "").lower().strip()
    for suf in _STRIP_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
            break
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def logo_dir_for(category_slug: str) -> Path | None:
    d = CATEGORY_TO_DIR.get(category_slug)
    return LOGOS_DIR / d if d else None


def logo_path_for(category_slug: str, slug: str) -> Path | None:
    d = logo_dir_for(category_slug)
    if d is None or not slug:
        return None
    return d / f"{slug}.png"


def manual_path_for(category_slug: str, slug: str) -> Path | None:
    d = CATEGORY_TO_DIR.get(category_slug)
    if not d or not slug:
        return None
    return MANUAL_DIR / d / f"{slug}.png"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bool(v: str | bool | None) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in {"true", "1", "yes"}


def write_bool(b: bool) -> str:
    return "true" if b else "false"


@dataclass
class Row:
    raw: dict[str, str] = field(default_factory=dict)

    def get(self, k: str, default: str = "") -> str:
        return self.raw.get(k, default) or default

    @property
    def entity_name(self) -> str: return self.get("entity_name")

    @property
    def category_slug(self) -> str: return self.get("category_slug")

    @property
    def arkham_slug(self) -> str: return self.get("arkham_slug")

    @property
    def canonical_domain(self) -> str: return self.get("canonical_domain")

    @property
    def logo_status(self) -> str: return self.get("logo_status", "none")

    @property
    def logo_hash(self) -> str: return self.get("logo_hash", "")

    @property
    def manual_lock(self) -> bool: return read_bool(self.get("manual_lock"))

    @property
    def importance(self) -> int:
        try:
            return int(self.get("importance") or "0")
        except ValueError:
            return 0

    @property
    def slug(self) -> str:
        """Canonical filesystem slug. Prefer arkham_slug if present
        (already pre-normalized upstream), else re-derive from name."""
        return self.arkham_slug or entity_slug(self.entity_name)

    def set(self, k: str, v: str) -> None:
        self.raw[k] = v


def read_entities(path: Path = CSV_PATH) -> list[Row]:
    rows: list[Row] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # fill in columns added later so downstream callers can rely
            # on them being present
            for c in COLUMNS:
                r.setdefault(c, "")
            rows.append(Row(raw=r))
    return rows


def write_entities(rows: Iterable[Row], path: Path = CSV_PATH) -> None:
    """Atomic write: temp file + rename. Preserves column order."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = {c: row.raw.get(c, "") for c in COLUMNS}
            writer.writerow(out)
    tmp.replace(path)
