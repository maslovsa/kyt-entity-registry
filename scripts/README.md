# scripts/

Build and validation tooling for the published artefacts.

| Script | Does |
|---|---|
| `generate_manifest.py` | `entities.csv` (+ `designations.json`) → `manifest.json` |
| `build_lookup.py` | `entities.csv` → `logos/_lookup.json` |
| `validate_manifest.py` | static checks on `manifest.json` (optional semantic tier with `--snapshot`) |
| `normalize_png.py` | any image → canonical 160×160 RGBA PNG |
| `shrink_logos.py` | re-encode heavy PNGs, updates `logo_hash` in `entities.csv` |
| `prune_manual_duplicates.py` | drop unreachable copies in `logos/_manual/` |
| `check_repo_size.py` | tracked tree must stay under jsDelivr's 50 MB package limit (CI cap 48 MB) |
| `build_og_preview.py` | `og-preview.png` for the landing page |
| `_base.py` | shared paths, CSV schema, slug rules |

`entities.csv` is written with `_base.write_entities()` (LF line endings,
column order = `_base.COLUMNS`).
