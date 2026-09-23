"""Button factories.

Functions returning `QPushButton`, not subclasses. Several tests assert
over `findChildren(QPushButton)`, and a subclass would keep working
there but would also let a future button quietly stop being one. A
factory sets an object name and returns the plain type.

`icon_button` takes `accessible_name` as a required argument, so an
unlabelled icon button is a `TypeError` rather than something a reviewer
has to notice.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QPushButton, QWidget

from ..design import metrics
from .icons import themed_icon


def button(
    label: str, parent: QWidget | None = None, *, icon: str = "", role: str = "default"
) -> QPushButton:
    control = QPushButton(label, parent)
    if icon:
        control.setIcon(themed_icon(icon, role))
        control.setIconSize(QSize(18, 18))
    return control


def primary_button(label: str, parent: QWidget | None = None, *, icon: str = "") -> QPushButton:
    control = QPushButton(label, parent)
    control.setObjectName("primaryButton")
    if icon:
        # White, because the button is filled with the accent.
        control.setIcon(themed_icon(icon, "on_accent"))
        control.setIconSize(QSize(18, 18))
    return control


def danger_button(label: str, parent: QWidget | None = None, *, icon: str = "") -> QPushButton:
    control = QPushButton(label, parent)
    control.setObjectName("dangerButton")
    if icon:
        control.setIcon(themed_icon(icon, "critical"))
        control.setIconSize(QSize(18, 18))
    return control


def icon_button(
    icon: str,
    accessible_name: str,
    *,
    tooltip: str = "",
    role: str = "default",
    parent: QWidget | None = None,
    sizes=None,
) -> QPushButton:
    """An icon-only button. The name is mandatory, not optional."""
    sizes = sizes or metrics.ACTIVE
    control = QPushButton(parent)
    control.setObjectName("iconButton")
    control.setIcon(themed_icon(icon, role))
    control.setIconSize(QSize(sizes.height_icon // 2, sizes.height_icon // 2))
    control.setAccessibleName(accessible_name)
    # An icon-only control has to be reachable by pointer and by screen
    # reader; the tooltip defaults to the name rather than to nothing.
    control.setToolTip(tooltip or accessible_name)
    control.setFixedSize(sizes.height_icon, sizes.height_icon)
    return control
