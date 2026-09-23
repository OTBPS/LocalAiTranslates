# ADR 0005 — Real glass exists only on the capture overlay's status bar

- **Status:** Accepted
- **Decided:** 2026-09-23

## Context

ADR 0002 establishes that element-level refraction is unreachable in Qt,
because nothing in QSS or `QGraphicsEffect` can sample what is behind a
widget.

There is exactly one surface where that is not a problem.

## Decision

The capture overlay's status bar gets genuine glass. Everything else does
not.

The overlay paints onto `ScreenShot.image` — a `QImage` captured once, at
the moment the hotkey was pressed. It does not scroll, it does not animate,
and nothing behind it can change while the overlay is on screen. So the
region the status bar covers can be blurred once and composited, which is
real refraction rather than a picture of one.

`graphics.blurred_region` does the blur by scaling the strip down and
back up with smooth filtering — a cheap Gaussian approximation that needs
no extra dependency and no numpy round trip. `ScreenShot.backdrop(region)`
caches the result per region.

**The cache is the whole point.** `paintEvent` runs ten times a second
while the model works; a blur there would make the overlay unusable. The
cache lives on `ScreenShot` because that is the object whose lifetime
matches the frozen image — one entry per capture, per screen, per bar
size. This is written here and in a comment at the call site, because
moving a pure function into the paint path looks like a tidy-up.

The cost is one blur of roughly 820 × 58 pixels per capture.

Composited on top: a translucent white fill so the blur shows through, a
1 px top stroke as the static stand-in for a specular highlight, and a
hairline border. The highlight cannot respond to the background, for the
reason in ADR 0002.

## What does not get glass

- **The selection rectangle and its handles.** They move, so the region
  behind them changes continuously, and they need high contrast against an
  unknown screenshot rather than translucency.
- **Every window surface.** Mica (ADR 0002) is the closest available, and it
  is window-level, applied by the compositor.

## Consequences

- `graphics.ScreenShot` gains a cached field. It is computed in
  `CaptureController.begin`, alongside the grab it belongs to.
- The effect cannot be verified by offscreen rendering in the same way the
  rest of the chrome can — it depends on real screen content. It is a
  by-eye item in `VERIFICATION.md`.
