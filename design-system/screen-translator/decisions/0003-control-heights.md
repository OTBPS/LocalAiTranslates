# ADR 0003 — Control heights: 44 for primary, 36 and 40 elsewhere

- **Status:** Accepted
- **Decided:** 2026-09-23

## Context

ADR 0001 set a blanket 44 px minimum on every control. Apple's HIG gives
44 × 44 pt as the minimum hit area, and that is where the number came from.

Applied uniformly on a desktop settings window it costs a great deal of
vertical space: the form does not fit at the 680 × 600 minimum size without
scrolling, and the Liquid-Glass direction calls for *more* padding, not less.
A mouse pointer is also not a fingertip.

## Decision

| Control | Height | Why |
|---|---|---|
| Primary button | **44 px** | Not reduced. This is the one control a user reaches for under time pressure. |
| Text input, combo box | **36 px** | Mouse target, always adjacent to its label, which is also clickable via `setBuddy`. |
| Icon button | **40 × 40 px** | Icon-only, so it keeps more area than a labelled control of the same importance. |

## Standards

- **WCAG 2.5.5 Target Size (Enhanced), AAA** — 44 × 44 CSS px. Met by the
  primary button; not met by inputs or icon buttons.
- **WCAG 2.5.8 Target Size (Minimum), AA** — 24 × 24 CSS px. Met everywhere,
  with margin.

The concession is AAA to AA on two control classes, on a pointer-driven
desktop application, in exchange for a form that fits its own minimum window
size.

## Consequences

- `test_contrast_ratios_meet_wcag_aa` and the structural layout assertions
  cover AA. Nothing claims AAA.
- Every `Field` sets `setBuddy`, so the label is part of the hit area of the
  control it names. This is what makes 36 px acceptable rather than merely
  compliant.
- If this application ever runs on a touch device the decision has to be
  revisited; nothing here assumes it will not.
