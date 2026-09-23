# ADR 0006 — The primary button fills with `#0066DB`, not `#007AFF`

- **Status:** Accepted
- **Decided:** 2026-09-23

## Context

Apple's system blue is `#007AFF`. White text on it measures **4.02:1**,
below the WCAG AA threshold of 4.5:1 for normal text. Apple ships it anyway;
the HIG grants its own system colours an exemption.

This project has a test, `test_contrast_ratios_meet_wcag_aa`, that computes
the ratio and fails the build.

## Options

- **(a)** Use `#007AFF` and add the primary button to an exemption list,
  annotated "Apple system colour". Honest about the source, but it converts
  a hard gate into a list of things that do not have to pass it. The list
  only ever grows.
- **(b)** Fill with `#0066DB`. White text measures **5.35:1** ✓ AA. The two
  blues are practically indistinguishable side by side.
- **(c)** Dark text on a blue fill. Passes, and looks nothing like the
  target direction.

## Decision

**(b).** `#0066DB` for the primary button's fill.

`#007AFF` is kept, and used for text links, selected states and tinted
accents — a blue *glyph* on a white background at 4.02:1 meets AA for large
text and for non-text contrast (3:1), which is what those uses are.

In dark mode `#0A84FF` is used as-is: on `#1C1C1E` it already clears the
threshold.

## Consequences

- The contrast test stays a gate with no exemption list, which is the point.
  It is eight lines, runs in milliseconds, and turns a documented intention
  into something CI enforces.
- The palette carries two blues. `semantic.py` names them by role
  (`accent_fill` and `accent_text`) rather than by shade, so the reason
  travels with the value.
- If Apple revises its system blue, this ADR is where to look first.
