# TODOS

Deferred work from code reviews and CEO plan reviews.

---

## P3 — Reduced-motion CSS overrides for audit gallery transitions

**What:** Add `@media (prefers-reduced-motion: reduce)` overrides for all CSS transitions
introduced by the 2026-06-19 audit gallery UX overhaul: progress bar fill animation,
copy-slug button opacity fade, and any other new `transition` declarations.

**Why:** Users with vestibular disorders or motion sensitivity may have this preference
set. The transitions are subtle (0.15s–0.3s) but the token-vocabulary approach makes
it easy to respect the preference with a single media query block.

**Effort:** XS (human ~30min / CC ~5min)

**When:** Can land in the same PR as the UX overhaul or as a follow-up.

**Blocked by:** Audit Gallery UX overhaul must ship first.

---

## P3 — DESIGN.md for audit gallery / landing page token vocabulary

**What:** Create `DESIGN.md` documenting the Bitok-inspired design token vocabulary
used by the audit gallery and landing page: Inter + Manrope fonts, Bitok pink `#d64686`,
color variable names, radius scale, shadow style, component vocabulary (`.chip`, `.btn`,
`.badge-status`, etc.).

**Why:** Without DESIGN.md, `/plan-design-review` starts cold every session and cannot
calibrate recommendations against the established system. A single markdown file makes
future design reviews faster and the codebase self-documenting.

**Effort:** S (human ~1h / CC ~15min)

**When:** After the UX overhaul ships.

---

## P3 — Virtual scrolling for gallery (10k+ entities)

**What:** Replace 100/page pagination with virtual scrolling via IntersectionObserver
when entity count approaches 10,000.

**Why:** Current pagination (100/page) is efficient up to ~5,000 entities (~25 pages).
Above that, the page count itself becomes unwieldy for reviewers. Virtual scrolling
renders only visible cards, giving the infinite-scroll feel without the DOM overhead.

**Effort:** L (human ~2 days / CC ~2h)

**When:** Trigger when entity count exceeds 5,000 (currently ~2,159 — ~14 months away
at current +200/month growth).

**Blocked by:** Audit gallery UX overhaul must ship first.
