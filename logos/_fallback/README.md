# _fallback/

Place `unknown.png` here — rendered by consumers when the main CDN
lookup 404s.

Spec:
- 160×160 RGBA
- Neutral grey silhouette or "?" glyph
- Works on both light + dark UI backgrounds

Can be manually designed or generated. Must exist before any consumer
UI goes live, otherwise consumers will render a broken-image icon on
missing entities.
