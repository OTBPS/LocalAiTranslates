# ADR 0001 — Modern constructivism as the visual direction

- **Status:** Superseded by [0002](0002-liquid-glass-direction.md)
- **Decided:** v0.4.7 (2026)
- **Recorded:** 2026-09-23, retroactively

## Context

v0.4.5 and v0.4.6 shipped an iOS-18-flavoured interface: system blue, 6 px
radii, soft cards, explanatory subtitles under most controls. It was
competent and entirely anonymous — nothing about it said which application
you were looking at.

## Decision

Adopt modern constructivism: flat warm paper, ink black, a single
revolutionary red, restrained signal yellow, square corners, 2 px rules,
`Arial Black` headings, asymmetric geometry confined to the hero and the
capture chrome.

`pages/settings.md` recorded the origin as "the product owner explicitly
requested a Soviet constructivist visual direction". That sentence is the
whole provenance; it is formalised here so the reason is not buried in a
page-level override.

## Consequences

Two lasting benefits, one of which outlived the direction itself:

1. **Distinctiveness.** The application became recognisable at a glance.
2. **Copy and density discipline.** The switch was used as the occasion to
   delete explanatory subtitles that repeated their own labels, and a blue
   banner reading "英语 → 简体中文" sitting directly below two dropdowns
   already showing exactly that. The two rules written at the time —
   *prefer concise labels over explanatory copy*, and *do not repeat a
   value already visible in an adjacent control* — are content discipline,
   not style, and they carry forward into ADR 0002 unchanged.

Costs: red served as both the accent and the danger colour, distinguished
only by fill versus outline. That works in a constructivist vocabulary and
does not survive translation to any other one — see ADR 0002.

The full text of the direction is archived verbatim at
`../archive/v0.4.7-constructivist/`.
