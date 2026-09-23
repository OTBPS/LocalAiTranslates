> **ARCHIVED.** This is a verbatim copy of the v0.4.7 constructivist
> direction, kept because ADR 0002 supersedes it and a superseded decision
> is only useful if you can still read what it said. Nothing here applies
> to the current interface. See `../../MASTER.md`.

# Screen Translator Design System

> Page-specific rules in `pages/*.md` override this file.

**Version:** 0.4.7
**Style:** Modern constructivism
**Design dials:** Variance 8/10 | Motion 2/10 | Density 7/10

## Principles

- Function remains obvious: expressive geometry frames the interface but never replaces labels.
- Use asymmetric red, black, and yellow shapes only in the hero and capture chrome.
- Forms stay predictable, keyboard accessible, and easy to scan.
- Use flat color, hard edges, strong rules, and deliberate negative space.
- Do not use gradients, glass, blur, soft shadows, pills, or decorative rounded corners.

## Tokens

| Role | Value |
|---|---|
| Background | `#E9DFC8` |
| Surface | `#F8F1E2` |
| Raised surface | `#FFFDFC` |
| Ink / border | `#151515` |
| Muted text | `#514B40` |
| Primary red | `#C51D23` |
| Primary hover | `#AA171C` |
| Primary pressed | `#821116` |
| Accent yellow | `#E8BC35` |
| Focus | `#C51D23`, 3 px |

Spacing uses a 4/8 px rhythm. Main controls are at least 44 px high. Cards use a
2 px black border; structural separators use 2–3 px black rules. Corner radius is
zero unless a native Windows dialog cannot be styled safely.

## Typography

- Headings: `Arial Black`, then `Microsoft YaHei UI`.
- Body and controls: `Arial`, `Microsoft YaHei UI`, then `Segoe UI`.
- Headings are heavy and compact; body copy stays normal-width and readable.
- Visible field labels must not be replaced by placeholders.

## Components

- **Primary button:** red fill, white label, black 2 px border, 48 px minimum height.
- **Secondary button:** paper fill, black label and border; yellow hover.
- **Danger button:** paper by default, red label; red fill and white label on hover.
- **Icon button:** 44 × 44 px minimum, yellow fill, black 2 px outline SVG.
- **Card:** paper fill, black 2 px border, no shadow, no radius.
- **Input:** white/paper fill, black 2 px border, red 3 px focus ring.
- **Toggle:** rectangular mechanical track and square knob; red selected state.
- **Status:** combine text with color; yellow for ready, red for warning, paper for neutral.
- **Progress:** black outlined track with red fill.
- **Application icon:** red field, black diagonal structure, yellow disc, cream crop brackets,
  and the `译` glyph. Use the checked-in multi-resolution ICO for Windows surfaces and the SVG
  as the canonical editable master; do not create alternate tray or installer marks.

## Motion

- Use motion only to explain state changes.
- Toggle movement: 120 ms; all other feedback should be immediate or under 150 ms.
- Animations must remain interruptible and honor the operating system's reduced-motion setting.
- Never animate layout dimensions or move neighboring controls.

## Accessibility and interaction

- Normal text contrast must meet 4.5:1; control boundaries and focus states 3:1.
- Keyboard order follows visual order and all actions remain reachable without a mouse.
- Icon-only buttons require accessible names and tooltips.
- Disabled controls are visibly muted and non-interactive.
- Do not encode state with color alone; pair it with text or a recognizable shape.
- Keep long-running OCR and translation work off the UI thread.

## Forbidden patterns

- Gradients, glassmorphism, blur, soft shadows, and floating translucent cards.
- Apple-blue accents, pill controls, soft iOS-style radii, and spring decoration.
- Emoji as structural icons; use the bundled 2 px SVG icon family.
- Hover effects that shift layout or hide keyboard focus.
- Decorative copy that repeats labels or explains self-evident controls.

## Pre-delivery checklist

- Run UI rendering tests and the complete automated suite.
- Inspect the settings window at its minimum supported size and with scrolling.
- Verify visible keyboard focus, labels, disabled states, and readable contrast.
- Verify screenshot selection, processing, error, and result overlay states.
- Confirm model paths, selected model, language pair, and user configuration survive an incremental update.
