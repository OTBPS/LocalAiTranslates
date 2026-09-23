"""Disabling a control and saying why, in one call.

Separated so nothing has to import the whole widget package to use it,
and so the two halves cannot be written apart. Greying a control out and
leaving the user to guess was the most common complaint about the
settings window.
"""

from __future__ import annotations


def set_enabled_with_reason(widget, enabled: bool, reason: str = "") -> None:
    widget.setEnabled(enabled)
    if not enabled:
        # Remember the control's own tooltip once, the first time we
        # replace it, so the explanation can be handed back later.
        if not hasattr(widget, "_enabled_tooltip"):
            widget._enabled_tooltip = widget.toolTip()
        widget.setToolTip(reason)
    elif hasattr(widget, "_enabled_tooltip"):
        # Only restore what we took. Clearing unconditionally would wipe
        # the tooltips of controls that were never disabled.
        widget.setToolTip(widget._enabled_tooltip)
        del widget._enabled_tooltip
