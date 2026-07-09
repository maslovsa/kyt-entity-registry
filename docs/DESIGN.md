# DESIGN.md — kyt-entity-registry design system

Token vocabulary for `gallery.css`, `landing.css`, and `gallery.js`.
Keep this in sync when changing tokens — `/plan-design-review` uses it
as the reference so future sessions don't start cold.

---

## Inspiration

Bitok-inspired theme. Tokens mirror `src/app/globals.css` in
`aml_checker` / `aegis-platform`. Pink accent, dark-surface dark mode,
Inter + Manrope type pair.

---

## Colour tokens

### Light mode (`:root` default)

| Token | Value | Role |
|---|---|---|
| `--background` | `#f7f7fa` | Page background |
| `--foreground` | `#232325` | Default text |
| `--card` | `#ffffff` | Card / toolbar surface |
| `--card-foreground` | `#232325` | Text on card |
| `--brand` | `#d64686` | Bitok pink — primary accent |
| `--brand-soft` | `#fde9f1` | Pink tint for backgrounds |
| `--brand-foreground` | `#ffffff` | Text on brand surface |
| `--primary` | `#d64686` | Alias of brand |
| `--primary-foreground` | `#ffffff` | |
| `--secondary` | `#f3f3f6` | Secondary surface |
| `--secondary-foreground` | `#353535` | |
| `--muted` | `#f3f3f6` | Subtle background |
| `--muted-foreground` | `#626368` | Subdued text |
| `--accent` | `#fde9f1` | Accent tint (= brand-soft) |
| `--accent-foreground` | `#d64686` | Text on accent |
| `--destructive` | `#ef4444` | Error / missing logo red |
| `--destructive-soft` | `#fee2e2` | Error background tint |
| `--border` | `#e9e9ee` | Borders and dividers |
| `--input` | `#e9e9ee` | Input borders |
| `--ring` | `#d64686` | Focus ring colour |
| `--shadow` | `0 1px 3px rgba(35,35,37,0.06), 0 1px 2px rgba(35,35,37,0.04)` | Card lift |

### Dark mode

Triggered by `@media (prefers-color-scheme: dark) :root:not(.light)` and `:root.dark`.

| Token | Value |
|---|---|
| `--background` | `#18181c` |
| `--foreground` | `#f5f5f7` |
| `--card` | `#232328` |
| `--brand` | `#ec5b9d` | (brighter for dark contrast) |
| `--brand-soft` | `#3a1e2d` |
| `--muted` | `#2a2a30` |
| `--muted-foreground` | `#9e9ea7` |
| `--border` | `#2e2e36` |
| `--shadow` | `0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3)` |

Theme toggle class: `.light` forces light, `.dark` forces dark on `:root`.

### Badge status colours

Status badges on cards use hardcoded semantic colours (not CSS vars) because
they need to stay legible across both themes independently:

| Status | Light bg / text | Dark bg / text |
|---|---|---|
| `arkham` | `#dbeafe` / `#1e40af` | `#1e3a5f` / `#93c5fd` |
| `defillama` | `#fef3c7` / `#92400e` | `#3f2e10` / `#fcd34d` |
| `favicon` | `#fef3c7` / `#92400e` | `#3d2e10` / `#fcd34d` |
| `manual` | `#d1fae5` / `#065f46` | `#1a3a2a` / `#6ee7a4` |
| `brandfetch` | `#ede9fe` / `#5b21b6` | `#2e1f4a` / `#c4b5fd` |
| `placeholder` | `--muted` / `--muted-foreground` | same |
| `none` | `--destructive-soft` / `--destructive` | same |

Status chip `::before` dots mirror the same palette.

---

## Typography

| Token | Value |
|---|---|
| `--font-sans` | `'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif` |
| `--font-heading` | `'Manrope', var(--font-sans)` |

Loaded via `<link>` in `index.html` / `audit.html` from Google Fonts
(`Inter:wght@400;500;600;700` + `Manrope:wght@600;700;800`).

OpenType features on `<body>`: `"ss01", "cv11"` (Inter alternate digits + slashed zero).
`-webkit-font-smoothing: antialiased`.

Base size: `14px`. Headings: `font-family: var(--font-heading); letter-spacing: -0.01em; font-weight: 700`.

---

## Radius scale

| Token | Value | Used on |
|---|---|---|
| `--radius` | `0.75rem` | Cards, modals |
| `--radius-md` | `calc(var(--radius) * 0.8)` ≈ 0.6rem | Inputs, buttons, logo area |
| `--radius-sm` | `calc(var(--radius) * 0.6)` ≈ 0.45rem | Badges |
| Chips | `999px` | Pill shape, hardcoded |

---

## Component vocabulary

### `.card`

Grid cell for one entity. `background: var(--card)`, `border: 1px solid var(--border)`,
`border-radius: var(--radius)`, `box-shadow: var(--shadow)`. 14px padding, flex column, 10px gap.

States:
- Hover: `border-color: var(--muted-foreground)`
- Flagged: `border-color: var(--destructive)`, `background: var(--destructive-soft)`
- Missing logo: `::after { content: "?" }` in 48px bold red inside `.card-logo`

### `.badge`

10px, `border-radius: var(--radius-sm)`, `background: var(--muted)`, `text-transform: lowercase`.
`.badge-status` variants override bg/color per source (see table above).

### `.chip`

Pill filter button. `border-radius: 999px`, 12px text, `background: var(--card)`.
Selected state: `border-bottom: 2px solid var(--brand)`, `font-weight: 600` — underline
indicator, no fill. Unselected chips dim to `opacity: 0.5` when any chip is selected
(`.chips-has-selection` on parent).

### `.btn`

`padding: 9px 16px`, `border-radius: var(--radius-md)`, 13px, `font-weight: 500`.

Variants:
- `.btn-primary` — brand pink fill
- `.btn-subtle` — transparent, destructive red on hover
- `.btn-sm` — `padding: 5px 10px`, 12px

### `#search`

`flex: 1 1 240px`, same border/radius as buttons, 14px. Focus ring:
`box-shadow: 0 0 0 3px color-mix(in srgb, var(--ring) 25%, transparent)`.

### `#progress-bar` / `#progress-fill`

3px track below the stats bar. Fill animates `width 0.3s ease` on load progress.

### `.toolbar`

`position: sticky; top: 0; z-index: 10`. Frosted glass:
`background: color-mix(in srgb, var(--background) 92%, transparent)` +
`backdrop-filter: saturate(1.4) blur(8px)`.

### `.grid`

`display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px`.
`max-width: 1400px`, `padding: 16px 24px 56px`.

---

## Motion

All transitions are `120ms` (UI interactions) or `0.3s ease` (progress bar fill).
`@media (prefers-reduced-motion: reduce)` blanket override in both CSS files:
`*, *::before, *::after { transition: none !important; animation: none !important; }`.

---

## Dark mode toggle

`gallery.js` manages `.light` / `.dark` class on `:root` and persists to
`localStorage['theme']`. System preference is the fallback. The `data-theme`
attribute approach used by Artifacts is **not** used here — class toggle only.
