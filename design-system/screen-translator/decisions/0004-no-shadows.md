# ADR 0004 — No drop shadows

- **Status:** Accepted
- **Decided:** 2026-09-23

## Context

Depth in most contemporary interfaces comes from shadow. Liquid Glass does
not work that way — it establishes layering through material and specular
highlight, with shadow playing a minor role at best. That is convenient,
because Qt makes shadows expensive.

## Decision

The interface uses no drop shadows. Layering comes from:

- **Material**: opaque content layer, opaque card layer, glass only in the
  two places it is achievable (see ADR 0002 and ADR 0005).
- **1 px hairline separators** in `stroke_separator`, which is how macOS and
  iOS divide inset grouped lists.
- **A 1 px top highlight stroke** on raised surfaces, the static stand-in
  for a specular edge.

## Why not shadows

- QSS has no `box-shadow`. The only mechanism is
  `QGraphicsDropShadowEffect`.
- That effect is per widget, not per stylesheet rule, so the card style
  stops being expressible in one place.
- It forces software compositing for the widget it is applied to. In a
  `QScrollArea` containing several shadowed cards the frame rate drops
  visibly while scrolling.
- Windows 11's own settings surfaces are flat with hairline separators.
  Shadows would look less native here, not more.

## Consequences

- `design/` exports no shadow token, and `QGraphicsDropShadowEffect` appears
  nowhere in the application.
- Any future request for depth has to be answered with material, stroke or
  spacing. If shadow genuinely becomes necessary, this ADR is what has to be
  argued against — the point is that the absence is a decision, not an
  oversight.
