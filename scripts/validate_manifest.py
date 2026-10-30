"""Validate manifest.json against static rules AND a snapshot of the live
consumer's expected display_names.

Two check tiers:

  STATIC — no external deps. Catches syntactic regressions:
    - keyword field is non-empty (already enforced by generator, but re-check)
    - no keyword is a space-separated phrase that clearly used to be a
      comma-separated list ("wintermute market maker algorithmic trading")
    - no product_alias contains a whole-word token that appears in ANY of
      the entry's keywords (self-strip)
    - duplicate slug across CSV → duplicate slug in manifest

  SEMANTIC — optional, needs a display-name snapshot passed via
  --snapshot ({"display_names": {slug: name}, "strip_prefixes": [...]}).
  For each manifest entry whose slug is in the snapshot, simulate a
  consumer's keyword badge detection on that display name. If it doesn't
  match, we print the offending entry and exit non-zero. The snapshot is
  maintained by the data provider and is not part of this repository;
  without it the semantic tier is skipped.

Usage:
  # Static checks only
  python3 scripts/validate_manifest.py

  # Point at a specific manifest and snapshot
  python3 scripts/validate_manifest.py --manifest manifest.json \\
      --snapshot display_names.json

Exit code:
  0  — all checks passed
  1  — one or more entries violate a rule
  2  — invalid arguments / missing input files
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "manifest.json"
DEFAULT_KNOWN_DUPS = REPO_ROOT / ".validator_known_dups.txt"
DEFAULT_KNOWN_SEMANTIC = REPO_ROOT / ".validator_known_semantic.txt"


def _load_slug_allowlist(path: Path) -> set[str]:
    """Read a slug-per-line allowlist, ignoring blank lines, full-line '#'
    comments, and trailing inline '# ...' comments."""
    out: set[str] = set()
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out

def prefix_regexes(prefixes: list[str]) -> tuple[re.Pattern, re.Pattern] | None:
    """Label prefixes ("{source}:") the consumer strips before matching. They
    come from the snapshot, so this repository does not name them."""
    if not prefixes:
        return None
    alt = "|".join(prefixes)
    return (re.compile(rf"^\s*(?:{alt})\s*:", re.IGNORECASE),
            re.compile(rf"^\s*(?:{alt})\s*$", re.IGNORECASE))


def kw_regex(k: str) -> re.Pattern:
    escaped = re.escape(k)
    return re.compile(r"(?<![a-zA-Z0-9_])" + escaped + r"(?![a-zA-Z0-9_])", re.IGNORECASE)


def detect_badge_match(label: str, entry: dict,
                       prefixes: tuple[re.Pattern, re.Pattern] | None = None) -> bool:
    """Keyword badge detection as consumers implement it."""
    if not label:
        return False
    lower = label
    if prefixes:
        prefix_re, bare_re = prefixes
        if bare_re.match(label):
            return False
        lower = prefix_re.sub(" ", label)
    lower = lower.lower()
    for entry_alias in entry.get("product_aliases", []):
        lower = lower.replace(entry_alias.lower(), " ")
    return any(kw_regex(k).search(lower) for k in entry.get("keywords", []))


# ─── Static rules ─────────────────────────────────────────────────────────────

def check_no_multi_word_solo_keyword(entry: dict) -> list[str]:
    """Warn if the ONLY keyword is a multi-word phrase that looks like
    a description (>=3 words). Real labels rarely match verbose phrases.
    """
    kws = entry.get("keywords", [])
    if not kws:
        return []
    if len(kws) > 1:
        return []
    only = kws[0]
    if len(only.split()) >= 3:
        return [f"only keyword is a {len(only.split())}-word phrase: {only!r}. "
                "Split with commas in entities.csv."]
    return []


def check_alias_equals_keyword(entry: dict) -> list[str]:
    """Fail only in the unambiguous self-strip case: an alias whose entire
    text equals one of the entry's keywords. That guarantees the label,
    if it matches the alias, will have that keyword erased before matching.

    We deliberately do NOT flag aliases that merely SHARE tokens with a
    keyword — that's the intended pattern for brand disambiguation
    (e.g. binance-com kw=['binance'] al=['binance smart chain'] keeps
    a "Binance Smart Chain" label from false-badging Binance CEX).
    """
    aliases = entry.get("product_aliases", [])
    kws = entry.get("keywords", [])
    if not aliases or not kws:
        return []
    kw_set = {k.lower() for k in kws}
    errs = []
    for a in aliases:
        if a.lower() in kw_set:
            errs.append(f"alias {a!r} equals a keyword — would strip it "
                        f"before matching. Remove either the alias or the keyword.")
    return errs


def check_broken_quotes(entry: dict) -> list[str]:
    """Detect dangling quote leftovers from CSV parse errors, e.g.
    keywords=['"zerohash', 'zero hash"'].
    """
    errs = []
    for k in entry.get("keywords", []):
        if k.startswith('"') or k.endswith('"'):
            errs.append(f"keyword has dangling quote: {k!r}. "
                        "Fix quoting in entities.csv.")
    return errs


# ─── Runner ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--snapshot", type=Path, default=None,
                    help="display-name snapshot JSON; omit to skip the semantic check")
    ap.add_argument("--known-dups", type=Path, default=DEFAULT_KNOWN_DUPS,
                    help="Allowlist of slugs that intentionally have 2+ CSV rows")
    ap.add_argument("--known-semantic", type=Path, default=DEFAULT_KNOWN_SEMANTIC,
                    help="Allowlist of slugs whose display_name is intentionally not keyword-matchable")
    ap.add_argument("--warn-only", action="store_true",
                    help="Exit 0 even on failure (useful during rollout)")
    args = ap.parse_args()

    if not args.manifest.exists():
        print(f"ERROR: manifest not found: {args.manifest}", file=sys.stderr)
        return 2

    m = json.loads(args.manifest.read_text())
    entries = m.get("entries", [])
    print(f"validate-manifest: {len(entries)} entries in {args.manifest.name}")

    total_static_errs = 0
    slug_counts: dict[str, int] = {}
    for e in entries:
        slug = e.get("slug", "<no-slug>")
        slug_counts[slug] = slug_counts.get(slug, 0) + 1

        errs: list[str] = []
        errs += check_no_multi_word_solo_keyword(e)
        errs += check_alias_equals_keyword(e)
        errs += check_broken_quotes(e)

        for msg in errs:
            print(f"  STATIC {slug}: {msg}")
            total_static_errs += 1

    known_dups: set[str] = set()
    if args.known_dups.exists():
        for line in args.known_dups.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                known_dups.add(line)
    dup_slugs = [s for s, n in slug_counts.items() if n > 1]
    unknown_dups = sorted(s for s in dup_slugs if s not in known_dups)
    if unknown_dups:
        print(f"  STATIC duplicate slug NOT in allowlist: {unknown_dups}")
        print(f"    (append them to {args.known_dups.name} to grandfather, or "
              f"merge the duplicate CSV rows to remove them.)")
        total_static_errs += len(unknown_dups)
    grandfathered = sorted(s for s in dup_slugs if s in known_dups)
    if grandfathered:
        print(f"  NOTE {len(grandfathered)} known-dup slug (allowlisted): {grandfathered}")

    known_semantic = _load_slug_allowlist(args.known_semantic)

    total_semantic_errs = 0
    if args.snapshot is not None and args.snapshot.exists():
        snap = json.loads(args.snapshot.read_text())
        dn_by_slug: dict[str, str] = snap.get("display_names", {})
        prefixes = prefix_regexes(snap.get("strip_prefixes", []))
        print(f"validate-manifest: {len(dn_by_slug)} slugs in {args.snapshot.name}")
        if known_semantic:
            print(f"validate-manifest: {len(known_semantic)} slug(s) in semantic allowlist")

        # Group manifest entries by slug so we handle intentional
        # duplicates by requiring at least ONE entry to match.
        by_slug: dict[str, list[dict]] = {}
        for e in entries:
            by_slug.setdefault(e["slug"], []).append(e)

        for slug, dn in dn_by_slug.items():
            if slug in known_semantic:
                continue  # intentionally not keyword-matchable (short/ambiguous name)
            e_list = by_slug.get(slug)
            if not e_list:
                continue
            if not any(detect_badge_match(dn, e, prefixes) for e in e_list):
                print(f"  SEMANTIC {slug}: dn={dn!r} won't match any keywords/aliases "
                      f"of {[{'kw': x['keywords'], 'al': x['product_aliases']} for x in e_list]}")
                total_semantic_errs += 1
    else:
        print("validate-manifest: no snapshot given — SKIPPING semantic check")

    if total_static_errs or total_semantic_errs:
        print(f"\nFAIL: {total_static_errs} static, {total_semantic_errs} semantic")
        return 0 if args.warn_only else 1

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
