"""Apply a gallery-exported rework CSV to the registry.

The gallery (`index.html` + `gallery.js`) lets reviewers flag bad
logos, pick replacements from their computer, and export a CSV
containing:
  - entity coordinates (`category_slug`, `arkham_slug`, `entity_name`)
  - the problem reason + free-text note
  - the current logo state at flag time (for audit)
  - optionally: `suggested_logo_data_url` — a `data:image/png;base64,…`
    URL of a replacement PNG already normalised to 160×160 RGBA on
    the reviewer's machine

This script walks that CSV and takes one of four actions per row:

  1. **apply-suggestion** — row has a valid `suggested_logo_data_url`.
     Decode → normalize_png → write to
     `logos/_manual/<category>/<slug>.png`. Then mirror to the public
     path and flip entities.csv: `logo_status=manual`,
     `manual_lock=true`, fresh `logo_updated_at` + `logo_hash`.
     After this row, the nightly enrichment will never touch it
     again (manual_lock).

  2. **retry-sources** — no data URL, but reason ∈
     {wrong_image, low_quality, outdated}. The current logo is
     flawed; clear it so the next enrich re-tries every source from
     scratch. Removes `logos/<category>/<slug>.png` (including
     placeholders) and resets the row to `logo_status=none` with
     empty hash/updated_at.

  3. **clear-placeholder** — reason=missing. Row should not have a
     logo at all; remove the PNG from disk and set logo_status=none.
     (Effectively the same as retry-sources, but the intent differs:
     we explicitly do NOT want sources to re-invent a wrong logo.
     Next enrich will write a placeholder again; that is acceptable
     until a human manually closes this out.)

  4. **log-only** — reason=manual_needed / other / empty without a
     data URL. Nothing to apply automatically. Print the row for a
     maintainer to hand-curate later.

CLI:

    python scripts/rework_from_report.py <report.csv>           # dry-run
    python scripts/rework_from_report.py <report.csv> --apply   # writes

After `--apply` succeeds, commit the result:

    git add entities.csv logos/
    git commit -m "rework: apply N suggestions from <report.csv>"
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Allow "python scripts/rework_from_report.py" to import siblings
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _base import (  # type: ignore[import-not-found]
    CATEGORY_TO_DIR,
    LOGOS_DIR,
    MANUAL_DIR,
    Row,
    logo_path_for,
    manual_path_for,
    read_entities,
    sha256_hex,
    write_bool,
    write_entities,
)
try:
    from normalize_png import NormalizeError, normalize  # type: ignore[import-not-found]
except ModuleNotFoundError as e:
    # Most common cause on macOS: user ran the script from the system
    # python3 (Homebrew / Apple) which doesn't have Pillow + httpx
    # installed because PEP 668 refuses global pip installs. Point
    # them at the venv setup instead of dumping a raw traceback.
    sys.stderr.write(
        f"error: missing dependency ({e.name}).\n\n"
        "Create a venv and install requirements first:\n\n"
        "    python3 -m venv .venv\n"
        "    .venv/bin/pip install -r requirements.txt\n\n"
        "Then re-run with the venv interpreter:\n\n"
        f"    .venv/bin/python scripts/{Path(__file__).name} <report.csv>\n"
    )
    sys.exit(2)

RETRY_REASONS = {"wrong_image", "low_quality", "outdated"}
CLEAR_REASONS = {"missing"}


@dataclass
class Action:
    row: Row
    kind: str           # "apply" | "retry" | "clear" | "log" | "skip"
    detail: str = ""    # short description printed in dry-run + summary


# ── CSV parsing ─────────────────────────────────────────────────────────

def _decode_data_url(url: str) -> bytes | None:
    """Extract raw bytes from a `data:image/...;base64,...` URL.
    Returns None for anything that isn't a base64 image URL."""
    if not url or not url.startswith("data:image/"):
        return None
    head, _, payload = url.partition(",")
    if not payload or ";base64" not in head:
        return None
    try:
        return base64.b64decode(payload, validate=True)
    except (ValueError, base64.binascii.Error):
        return None


def _read_report(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"category_slug", "arkham_slug", "entity_name",
                    "reason", "suggested_logo_data_url"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(
                f"{path}: CSV missing required columns: {sorted(missing)}")
        return list(reader)


# ── per-action handlers ────────────────────────────────────────────────

def _apply_suggestion(row: Row, png: bytes, dry_run: bool) -> str:
    """Write `png` to logos/_manual/<cat>/<slug>.png AND the public
    path. Flip CSV state to manual + locked. Returns a detail string."""
    manual = manual_path_for(row.category_slug, row.slug)
    public = logo_path_for(row.category_slug, row.slug)
    if manual is None or public is None:
        return f"no directory mapping for category {row.category_slug!r}"

    new_hash = sha256_hex(png)
    if not dry_run:
        manual.parent.mkdir(parents=True, exist_ok=True)
        manual.write_bytes(png)
        public.parent.mkdir(parents=True, exist_ok=True)
        public.write_bytes(png)

    row.set("logo_status", "manual")
    # dt.timezone.utc works on 3.8+; dt.UTC is a 3.11+ alias.
    row.set("logo_updated_at", dt.datetime.now(dt.timezone.utc).date().isoformat())
    row.set("logo_hash", new_hash)
    row.set("manual_lock", write_bool(True))
    rel = public.relative_to(LOGOS_DIR.parent)
    return f"-> {rel} ({len(png)} B, sha256 {new_hash[:8]})"


def _clear_current_logo(row: Row, dry_run: bool, *, reset_reason: str) -> str:
    """Remove logos/<cat>/<slug>.png and reset CSV row so the next
    enrich run re-tries all sources. Does NOT touch _manual/ — a
    previously-placed manual override should still get picked up."""
    public = logo_path_for(row.category_slug, row.slug)
    manual = manual_path_for(row.category_slug, row.slug)
    parts: list[str] = []

    # Refuse to touch manual-locked rows unless the reviewer also
    # dropped a fresh suggestion, which would have routed to apply.
    if row.manual_lock:
        return "row is manual_lock=true; skipped"

    if public and public.exists():
        if not dry_run:
            public.unlink()
        parts.append(f"removed {public.relative_to(LOGOS_DIR.parent)}")
    # If a stale _manual/ override exists for this slug, leave it —
    # enrich.py will pick it up on the next run and re-apply.
    if manual and manual.exists():
        parts.append(f"(kept manual override {manual.relative_to(LOGOS_DIR.parent)})")

    row.set("logo_status", "none")
    row.set("logo_updated_at", "")
    row.set("logo_hash", "")
    parts.append(f"logo_status=none (reason={reset_reason})")
    return "; ".join(parts)


# ── orchestration ──────────────────────────────────────────────────────

def _plan(report: list[dict[str, str]], rows_by_key: dict[tuple[str, str], Row]) -> list[Action]:
    out: list[Action] = []
    for r in report:
        key = (r["category_slug"], r["arkham_slug"])
        row = rows_by_key.get(key)
        if row is None:
            out.append(Action(
                row=Row(raw=r), kind="skip",
                detail=f"{r['category_slug']}/{r['arkham_slug']} not in entities.csv"))
            continue

        png_raw = _decode_data_url(r.get("suggested_logo_data_url", ""))
        reason = (r.get("reason") or "").strip()

        if png_raw is not None:
            try:
                png = normalize(png_raw)
            except NormalizeError as e:
                out.append(Action(row=row, kind="skip",
                                  detail=f"suggested image rejected: {e}"))
                continue
            out.append(Action(
                row=row, kind="apply",
                detail=f"({reason or '—'}) {len(png_raw)} B -> {len(png)} B after normalize",
                # stash the bytes on the action for the apply step
            ))
            out[-1].row.raw["_png"] = png  # piggy-back; _base ignores underscore keys
            continue

        if reason in RETRY_REASONS:
            out.append(Action(row=row, kind="retry",
                              detail=f"reason={reason}; will re-run all sources"))
            continue
        if reason in CLEAR_REASONS:
            out.append(Action(row=row, kind="clear",
                              detail=f"reason={reason}; will drop current PNG"))
            continue

        out.append(Action(row=row, kind="log",
                          detail=f"reason={reason or '(none)'}; no auto-action"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path,
                    help="path to kyt-registry-rework-YYYY-MM-DD.csv")
    ap.add_argument("--apply", action="store_true",
                    help="actually write files + update entities.csv "
                         "(default: dry-run, show what would change)")
    args = ap.parse_args()

    if not args.report.exists():
        raise SystemExit(f"{args.report}: not found")

    report = _read_report(args.report)
    rows = read_entities()
    rows_by_key = {(r.category_slug, r.arkham_slug): r for r in rows}

    actions = _plan(report, rows_by_key)

    counters = {"apply": 0, "retry": 0, "clear": 0, "log": 0, "skip": 0}
    print(f"report: {args.report.name}  ({len(report)} row(s))")
    print(f"mode:   {'APPLY' if args.apply else 'dry-run'}")
    print("---")

    for a in actions:
        counters[a.kind] += 1
        name = a.row.entity_name or f"{a.row.category_slug}/{a.row.arkham_slug}"
        if a.kind == "apply":
            png = a.row.raw.pop("_png", None)
            if png is None:
                print(f"  skip   {name}  (internal: normalised bytes lost)")
                counters["apply"] -= 1
                counters["skip"] += 1
                continue
            detail = _apply_suggestion(a.row, png, dry_run=not args.apply)
            print(f"  apply  {name}  {detail}")
        elif a.kind == "retry":
            detail = _clear_current_logo(
                a.row, dry_run=not args.apply, reset_reason="retry")
            print(f"  retry  {name}  {detail}")
        elif a.kind == "clear":
            detail = _clear_current_logo(
                a.row, dry_run=not args.apply, reset_reason="clear")
            print(f"  clear  {name}  {detail}")
        elif a.kind == "log":
            print(f"  log    {name}  {a.detail}")
        elif a.kind == "skip":
            print(f"  skip   {name}  {a.detail}")

    if args.apply and (counters["apply"] or counters["retry"] or counters["clear"]):
        write_entities(rows)
        print("\nentities.csv: written")

    print("\nsummary:")
    for k in ("apply", "retry", "clear", "log", "skip"):
        print(f"  {k:6s} {counters[k]}")
    if not args.apply:
        print("\n(dry-run) re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
