# Screen Translator Design System

> Page-specific rules in `pages/*.md` override this file.
> Decisions and their reasoning live in `decisions/`.
> The retired constructivist direction is archived verbatim in
> `archive/v0.4.7-constructivist/`.

**Version:** 0.8.0
**Style:** Liquid-Glass-informed (see [ADR 0002](decisions/0002-liquid-glass-direction.md))
**Design dials:** Variance 3/10 | Motion 2/10 | Density 5/10

## Principles

- Content is the layer; controls float above it. Depth comes from material
  and hairlines, never from shadow.
- Geometry is concentric: a radius inside another radius is the outer one
  minus the padding between them.
- Colour carries meaning, never meaning alone. Every state is also words.
- Say what a control does, not what it is. A disabled control says why.
- The interface is quiet. Motion explains a change and then stops.

## Constraints

Why the design is shaped the way it is. These are properties of Qt and of
Windows, not preferences, and knowing them prevents a great deal of wasted
effort:

- **QSS has no background filter.** There is no `backdrop-filter` and no
  equivalent. Element-level translucency that samples what is behind it
  cannot be built. `QGraphicsBlurEffect` blurs what a widget has already
  painted, not what is behind it.
- **QSS has no `box-shadow`.** The only mechanism is
  `QGraphicsDropShadowEffect`, which is per widget and forces software
  compositing. See [ADR 0004](decisions/0004-no-shadows.md).
- **Qt corners are circular, not continuous.** There is no squircle. At the
  radii used here the difference is not visible; drawing every control by
  hand to get one would not be worth it.
- **CJK fonts have no 800 or 900 weight.** Microsoft YaHei ships Light,
  Regular and Bold. Asking for 900 makes Qt synthesise the weight by
  stroking outward, which at 96 dpi renders as mush. The weight whitelist
  is 400 / 500 / 600 / 700.
- **QSS cannot recolour `image: url(...)`.** An SVG referenced from a
  stylesheet renders with whatever colour is inside the file. Dark mode
  therefore needs a second file, not a token.
- **SF Pro cannot be redistributed.** Its licence covers macOS. A sizeable
  part of the Apple feel comes from SF's tight tracking and optical sizes,
  and that part is simply not available.

## Tokens

Values are generated from `screen_translator/design/`; `tokens.md` in this
directory is produced by a script and checked by a test, so the table cannot
drift from the code. **`design/primitives.py` is the only file in the
repository permitted to contain a colour literal.** A test enforces it.

| Role | Light | Dark |
|---|---|---|
| `bg_canvas` | `#F2F2F7` | `#000000` |
| `bg_surface` | `#FFFFFF` | `#1C1C1E` |
| `bg_surface_raised` | `#FFFFFF` | `#2C2C2E` |
| `text_primary` | `#000000` | `#FFFFFF` |
| `text_secondary` | `#6C6C70` | `#98989F` |
| `stroke_separator` | `#C6C6C8` | `#38383A` |
| `accent_fill` | `#0066DB` | `#0A84FF` |
| `accent_text` | `#007AFF` | `#0A84FF` |
| `critical` | `#D70015` | `#FF453A` |
| `success` | `#248A3D` | `#30D158` |
| `caution` | `#8F5A00` | `#FFD60A` |

`accent_fill` is not Apple's `#007AFF`; see
[ADR 0006](decisions/0006-primary-button-blue.md).

**Radii** follow the concentric rule. Outer card 16, inset group row 10,
button and input 10, small control 8, switch and progress bar pill.
`metrics.concentric(outer, padding)` computes the inner value; it is a
function rather than a table because getting this wrong by hand is the
single easiest way to make the geometry look wrong.

**Spacing** is on a 4 px base, biased large: card padding 20, card gap 16,
page margin 24.

**Materials** are three layers. L0 content, opaque. L1 card, opaque fill
with a 1 px hairline. L2 glass, which exists in exactly two places: the
window background (Windows 11 Mica) and the capture overlay's status bar
(a real blur of a frozen screenshot; see
[ADR 0005](decisions/0005-glass-only-on-the-overlay.md)).

## Typography

- Display (≥ 20 px): `Segoe UI Variable Display`
- Text (< 20 px): `Segoe UI Variable Text`
- Fallbacks: `Segoe UI`, then `Microsoft YaHei UI`

Latin families come **first** so CJK falls through to YaHei naturally. The
old stack led with Arial, which is the wrong way round.

Weights 400 / 500 / 600 / 700 only — see Constraints.

Visible field labels are never replaced by placeholder text.

## Components

- **Card** — `bg_surface`, radius 16, 1 px hairline, no shadow.
- **InsetGroup** — the main container for settings: rows inside one rounded
  card, separated by 1 px hairlines, first and last rows inheriting the
  outer corners.
- **Field** — a label bound to its control with `setBuddy`, and an
  accessible name set from the label. Accessibility is the default, not
  something each call site remembers.
- **Primary button** — `accent_fill`, white label, radius 10, height 44.
- **Secondary button** — `bg_surface` fill, hairline border, `accent_text`
  label.
- **Danger button** — `critical` label; `critical` fill with white label on
  hover. Red now means danger and nothing else.
- **Icon button** — 40 × 40, requires an `accessible_name`; the factory
  takes it as a mandatory argument, so omitting it is a `TypeError`.
- **ToggleSwitch** — pill track, circular knob. Animation and
  reduced-motion behaviour are unchanged from the previous direction.
- **StatusChip** — colour plus text, never colour alone.
- **AppHeader** — a large title with a secondary line. No colour-block
  banner; Liquid Glass does not use them.
- **Progress** — pill track, `accent_fill`.

Control heights are in [ADR 0003](decisions/0003-control-heights.md).

## Motion

- Motion explains a state change; nothing moves for decoration.
- Toggle 120 ms; everything else immediate or under 150 ms.
- Animations stay interruptible and honour the system's reduced-motion
  setting.
- Layout dimensions are never animated and neighbouring controls never
  shift.

## Accessibility and interaction

- Normal text 4.5:1, control boundaries and focus 3:1. Enforced by
  `test_contrast_ratios_meet_wcag_aa` in both themes, with no exemption
  list.
- **Focus rings never change geometry.** The resting state declares a 2 px
  border; `:focus` changes only `border-color`. A test asserts that no
  `:focus` rule body contains `padding`, `margin` or `border-width`. The
  old approach — thickening the border and subtracting a pixel of padding
  to compensate — was the most fragile code in the stylesheet.
- Keyboard order follows visual order; every action is reachable without a
  mouse.
- Icon-only buttons require accessible names and tooltips.
- Disabled controls are muted **and** carry the reason in their tooltip.
  `set_enabled_with_reason` does both in one call so they cannot drift.
- Long-running OCR and translation work stays off the UI thread.

## Scope

- **The capture overlay uses its own pinned sub-palette.** It paints on an
  unknown screenshot: whether the application theme is light or dark says
  nothing about whether the region the user grabbed is light or dark, so
  following the theme would be wrong. `design/overlay.py` derives its
  constants from the primitives and then fixes them.
- **`graphics.py` is outside the token system entirely.** Its two colours
  are chosen per image from the measured background luminance, and
  `FONT_FAMILIES` maps a language to a system font — it is not a brand
  stack. Putting either under a theme would let changing the application's
  appearance change the pixels of a translated image.
  `test_graphics_never_imports_the_design_package` keeps that separation
  from being tidied away.

## Forbidden patterns

- Colour literals outside `design/primitives.py`.
- Layout numbers (`setContentsMargins`, `setSpacing`, `setIconSize`) written
  as literals rather than token references. Zero is allowed.
- Drop shadows of any kind.
- Font weights 800 and 900.
- Emoji as structural icons; use the bundled SVG family.
- Hover effects that shift layout or hide keyboard focus.
- Explanatory copy that repeats its own label. *(Carried over from ADR
  0001 — this rule was the real gain of the previous change of direction.)*
- Values repeated from an adjacent control, chip or button label.
  *(Likewise.)*

## Pre-delivery checklist

- Run the full suite, `ruff`, and the UI scenario renders.
- Colour census: the dominant colours of every rendered scene must be a
  subset of the theme.
- Inspect the settings window at 680 × 600 and confirm it scrolls rather
  than clipping.
- Check visible keyboard focus, labels, disabled reasons and contrast.
- Check the capture overlay's selecting, adjusting, processing, failed and
  result states.
- 150% DPI has to be a subprocess (`QT_SCALE_FACTOR` is process-wide), so it
  is checked here rather than in `pytest`.
- Mica and the overlay's real glass need a by-eye check on real hardware;
  offscreen rendering does not go through DWM.
- Confirm model paths, selected model, language pair and configuration
  survive an incremental update.
