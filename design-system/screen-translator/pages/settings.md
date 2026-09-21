# Settings — modern constructivist desktop treatment

This page overrides the global AI-native palette because the product owner
explicitly requested a Soviet constructivist visual direction.

## Visual language

- Use warm paper `#E9DFC8`, ink black `#151515`, revolutionary red `#C51D23`,
  and restrained signal yellow `#E8BC35`.
- Use flat color fields, asymmetric diagonals, circles, rectangles, two-pixel
  black rules, and square corners. Do not use gradients, glass, or soft shadows.
- Use Arial Black for short headings and Microsoft YaHei UI / Arial for body text;
  keep Windows-native rendering and do not download fonts.

## Interaction

- Controls must be at least 44 px high and retain visible keyboard focus.
- Use rectangular mechanical switches with a 120 ms transition; state correctness
  must not depend on animation completion.
- Use SVG outline icons with consistent 1.8 px strokes; no emoji icons.
- Keep one prominent action: **开始截图**. Saving and model maintenance remain
  visually secondary.
- Keep labels visible, helper text near its control, and status expressed with
  both text and color.
- Prefer concise control labels over explanatory copy. Show helper text only for errors,
  progress, or information needed to complete the current action; move optional technical
  details to tooltips.
- Do not repeat values already visible in adjacent controls, status pills, or button labels.

## Desktop adaptation

- Preserve the native Windows title bar, system menu, tab order, file picker,
  and tray behavior.
- Use geometric decoration only in the hero and capture chrome; keep form controls
  aligned and predictable.
- Layout must remain usable down to 680×640 and reflow vertically via scrolling.
