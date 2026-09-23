# ADR 0002 — A Liquid-Glass-informed direction

- **Status:** Accepted
- **Supersedes:** [0001](0001-constructivist-direction.md)
- **Decided:** 2026-09-23

## Context

The product owner asked for the interface to be rebuilt in Apple's current
design language. Apple's current language is **Liquid Glass**, introduced at
WWDC 2025 and adopted across iOS, iPadOS and macOS 26: a translucent
material that refracts and reflects what is behind it, with specular edge
highlights, controls floating above content as a distinct functional layer,
and larger, concentric corner radii.

Three things have to be stated plainly before anything else.

**This is the project's third direction.** iOS 18 (v0.4.5–0.4.6) →
constructivism (v0.4.7) → Liquid Glass (now). Each change cost a full pass
over every screen. A fourth would be a pattern, not a decision.

**The target is Apple's language today, not this project's own 2024
interface.** `artifacts/ui/settings-ios18.png` exists in the repository and
is *not* the reference. Reverting to it would be going backwards through
the same list.

**The material itself cannot be reproduced in Qt.** This is a capability
gap, not a version problem:

- QSS has no background-filter primitive. There is no `backdrop-filter`.
- `QGraphicsBlurEffect` operates on what a widget has already painted. It
  cannot sample what is behind the widget. Faking it means grabbing the
  screen, blurring, and compositing by hand — which breaks the instant
  anything scrolls or the window moves.
- Specular highlights have to be computed from the background's luminance,
  which needs the same unavailable sample.
- SF Pro is bundled with macOS and its licence does not permit
  redistribution.

## Decision

Adopt a **Liquid-Glass-informed** direction. Not Liquid Glass; informed by
it. What is reachable and what is not:

| Liquid Glass characteristic | Here | How |
|---|---|---|
| Concentric radii, larger curvature | ✅ full | Pure geometry, expressible in QSS |
| Controls layered above content | ✅ full | Floating cards plus inset grouped lists |
| Capsule controls | ✅ close | Qt has circular corners only; at large radii the difference is not visible |
| System colours, tinted accents | ✅ full | Token layer |
| Window-level translucent material | ⚠️ approximate | Windows 11 **Mica** via `DwmSetWindowAttribute` — window level, not element level |
| Element-level real-time refraction | ❌ unreachable | No API |
| Specular edge highlight | ⚠️ static | A 1 px top highlight stroke that does not respond to the background |
| SF Pro | ❌ unreachable | Segoe UI Variable is the closest Windows equivalent |

**One place gets real glass.** The capture overlay's status bar sits on a
frozen `QImage` — the screenshot. It does not scroll and does not change, so
the region behind the bar can be blurred once per capture and composited.
That is genuine refraction rather than a texture. It is the only surface in
the application where this is possible; see ADR 0005.

**Mica is now in scope**, reversing an earlier "not doing" entry. It is a few
dozen lines of `ctypes`, adds no dependency, and silently falls back to an
opaque background on Windows 10 and older Windows 11. The native title bar
stays; Mica does not require drawing our own.

**The two content rules from ADR 0001 carry over verbatim**: prefer concise
labels over explanatory copy, and never repeat a value already visible in an
adjacent control. Changing visual language is not a reason to discard the
editorial discipline that the last change bought.

## Consequences

- **Distinctiveness drops.** A blue-accented Apple-style desktop application
  looks like many other applications. That is the trade the owner asked for.
- **No gradual path.** The visual flip is a single commit by design (P4 in
  the plan), because a half-converted interface — rounded buttons inside
  square cards — is worse than either end state. `git revert` on that commit
  restores constructivism completely.
- The regression test that pinned the old direction is inverted rather than
  deleted: `test_theme_contract_follows_the_apple_direction` now asserts
  that system blue is present and constructivist red is absent from chrome.
  It still permits red in the application icon.
- Red no longer has to be both accent and danger. System blue is the accent;
  red means danger only.
- Before/after screenshots are checked in under `artifacts/ui/`; the
  constructivist set is the visual evidence for this ADR.
