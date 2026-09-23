# Settings window

Overrides `../MASTER.md` where the two differ.

## Structure

Three tabs — 截图翻译 / 文本翻译 / 系统设置 — under a large-title header and
above a shared footer. The notice banner sits **outside** the tabs, because
the Save button is in the shared footer: a confirmation placed inside one
page is invisible from the other two, which is exactly the bug that made a
banner necessary.

Each tab is a column of cards. Settings that are a list of labelled rows use
`InsetGroup` rather than a `Card` with a hand-built `QVBoxLayout`; that is
the Apple settings container and it is what makes hairline separation and
corner inheritance consistent.

## Copy

*(Both rules carried over from the constructivist direction — see ADR 0001.
They were its real gain and survive the change of visual language.)*

- Prefer a concise label over explanatory copy. Helper text appears only for
  errors, progress, or something needed to complete the current action;
  optional technical detail goes in a tooltip.
- Never repeat a value already visible in an adjacent control, chip or
  button label.

## Interaction

- One prominent action per page. On 截图翻译 that is **开始截图**; saving and
  model maintenance stay visually secondary.
- Every disabled control carries its reason. `set_enabled_with_reason` sets
  the state and the tooltip in one call so the two cannot separate.
- A message that names a problem also carries a `Destination`, so its button
  lands on the control that fixes it rather than describing where to find
  it.
- Labels are bound to their controls with `setBuddy`, so the label is part
  of the hit area — which is what makes a 36 px input acceptable (ADR 0003).

## Cross-device

- The host is chosen from the Tailscale device list, which already knows the
  name, the system, whether it is online and whether the link is direct.
  "手动填写地址" stays as the first entry: a host Tailscale cannot see, or a
  machine without Tailscale, must still be reachable.
- Pairing is a six-digit code. The manual secret field remains, labelled as
  being for older hosts, because a v0.7.0 host has no pairing route and
  whoever updates one machine first must not be stranded.
- Paired devices are listed by name and address. A secret is never rendered.

## Desktop adaptation

- Keep the native Windows title bar, system menu, tab order, file picker and
  tray behaviour. Mica does not require a custom title bar and does not get
  one.
- Usable down to 680 × 600, reflowing vertically by scrolling. The larger
  Liquid-Glass padding makes this tighter than before, so it is a
  pre-delivery check rather than an assumption.
