# ADR 0007 — Redraw the application icon

- **Status:** Accepted
- **Decided:** 2026-09-23
- **Relates to:** [0002](0002-liquid-glass-direction.md)

## Context

ADR 0002 listed the icon as an unresolved cost: a red, black and yellow
constructivist mark sitting above a blue-and-white interface looks like it
belongs to a different program. The work was deliberately left unscheduled,
because it reaches further than it appears to — the generation script, nine
ICO size assertions, `installer.iss`, `installer.common.iss`,
`installer.update.iss`, both PyInstaller specs, and the Windows icon cache.

There was also a defect independent of the direction. The old mark carried
five ideas at once: a red field, a black diagonal, a yellow disc, four crop
brackets and the 译 glyph. At 128 px that is dense. At 16 px, which is what
the notification area and the Alt-Tab list actually show, it is a smudge.

## Decision

One idea: the 译 glyph, white, on a rounded tile with a vertical blue
gradient. The diagonal, the disc and the brackets are gone.

**The glyph stays.** It is what the product is named after and the only part
of the old mark that was ever recognisable at a glance. Changing the shape
and the colour while keeping the character is the right amount of change;
replacing it as well would discard the one piece of continuity worth having.

**Every size is rendered at its own scale, not downsampled from one master.**
译 has thirteen strokes. Reducing a 1024 px render to 16 px turns them into
grey. The generator therefore draws all nine sizes, each supersampled 8× and
reduced with Lanczos, and small tiles give the character proportionally more
of the square — 80% below 24 px against 62% at 256. Pillow's ICO writer uses
a supplied image whose size matches exactly and only downsamples when one is
missing, so supplying all nine means none of them are guesses. This is the
same optical-sizing idea as the Display and Text cuts of the interface font.

The specular edge stroke appears only at 48 px and above, because below that
it is thinner than a pixel and reads as a dirty edge rather than a highlight.

**Colours are imported from `design.primitives`.** The previous icon
hard-coded its four, which is how it outlived the direction it was drawn
for by two releases. A test asserts the generator contains no colour
literal.

## Consequences

- `app-icon.svg` is rewritten as the editable reference. It matches the
  large sizes; the small ones are deliberately different, and the file says
  so.
- Nothing in the packaging changes. Every reference is to the path
  `screen_translator/assets/app-icon.ico`, and the file keeps its name. The
  incremental updater delivers the assets directory by wildcard, so a patch
  carries the new icon without touching `installer.update.iss` — which
  matters, because `tests/test_installer_boundaries.py` pins that file's
  source list exactly.
- `tests/test_app_icon.py` covers the nine sizes, glyph legibility and
  centring at each, transparent corners, the palette, and the two ways the
  artwork could go stale.
- **Windows caches icons aggressively.** Replacing the ICO in place is not
  enough: the taskbar, Explorer and existing shortcuts keep drawing the old
  artwork until something invalidates the cache, which otherwise means a
  sign-out. The v0.5.1 release notes claim the installer already notifies
  Explorer — it did not; no script contained the call. `installer.shell.iss`
  adds it, shared by the full, client and incremental scripts, and a test
  asserts both top-level scripts include it and call it at `ssPostInstall`.
  The claim went unnoticed for three releases because nothing about the
  icon had changed since it was written.
