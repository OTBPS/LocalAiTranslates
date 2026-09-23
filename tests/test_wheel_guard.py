"""The mouse wheel must not change a value it happens to be over.

Scrolling a settings page moves the cursor across a language dropdown
and a port field. With Qt's default behaviour that silently changes the
language you translate into, or the port the host listens on, and the
only evidence is the value being wrong later.
"""

import os

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget

from screen_translator.widgets import ComboBox, SpinBox


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


def wheel(widget, *, steps: int = -1) -> QWheelEvent:
    delta = QPoint(0, 120 * steps)
    centre = QPointF(widget.rect().center())
    return QWheelEvent(
        centre,
        widget.mapToGlobal(centre),
        delta,
        delta,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def combo(items=("英语", "简体中文", "日语", "韩语")):
    control = ComboBox()
    for item in items:
        control.addItem(item)
    return control


@pytest.mark.parametrize("steps", [-1, 1, -3, 3])
def test_scrolling_a_dropdown_does_not_change_the_selection(steps):
    control = combo()
    control.setCurrentIndex(1)

    QApplication.sendEvent(control, wheel(control, steps=steps))

    assert control.currentIndex() == 1
    assert control.currentText() == "简体中文"


@pytest.mark.parametrize("steps", [-1, 1])
def test_scrolling_a_spin_box_does_not_change_its_value(steps):
    control = SpinBox()
    control.setRange(1024, 65535)
    control.setValue(8765)

    QApplication.sendEvent(control, wheel(control, steps=steps))

    assert control.value() == 8765


def test_a_focused_dropdown_is_still_not_scrollable():
    """Focus is not consent. The cursor is over it either way."""
    control = combo()
    control.show()
    control.setFocus()
    control.setCurrentIndex(2)
    try:
        QApplication.sendEvent(control, wheel(control))

        assert control.currentIndex() == 2
    finally:
        control.close()


def test_the_wheel_still_reaches_the_page_underneath():
    """Ignoring the event is not the same as swallowing it.

    A dropdown that eats the wheel would trade a changed value for a
    page that will not scroll, which is the same complaint wearing a
    different hat.
    """
    scroll = QScrollArea()
    content = QWidget()
    column = QVBoxLayout(content)
    control = combo()
    column.addWidget(control)
    for _ in range(40):
        column.addWidget(QWidget())
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.resize(300, 200)
    content.setMinimumHeight(2000)
    scroll.show()
    QApplication.processEvents()
    try:
        assert scroll.verticalScrollBar().maximum() > 0, (
            "the page has to be scrollable for this to mean anything"
        )

        event = wheel(control)
        QApplication.sendEvent(control, event)

        # Declined, so Qt offers it to the ancestors. An accepted event
        # would stop here and the page would not move.
        assert not event.isAccepted()
    finally:
        scroll.close()


def test_clicking_still_opens_the_list():
    control = combo()
    control.show()
    QApplication.processEvents()
    try:
        control.showPopup()
        QApplication.processEvents()

        assert control.view().isVisible()
        control.hidePopup()
    finally:
        control.close()


def test_the_open_list_scrolls_normally():
    """The popup is a separate widget and keeps Qt's behaviour.

    Refusing the wheel there would make a long list unusable, which is
    not what was asked for.
    """
    control = combo(tuple(f"项目 {index}" for index in range(40)))
    control.show()
    control.showPopup()
    QApplication.processEvents()
    try:
        view = control.view()
        assert view.verticalScrollBar().maximum() > 0
        # The view is an ordinary item view: nothing overrides its wheel.
        assert type(view).wheelEvent is not ComboBox.wheelEvent
        control.hidePopup()
    finally:
        control.close()


def test_the_wheel_does_not_steal_focus():
    # WheelFocus would let a scroll move the keyboard focus, so the next
    # keystroke lands somewhere the user did not choose.
    assert combo().focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert SpinBox().focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_keyboard_selection_is_untouched():
    control = combo()
    control.show()
    control.setFocus()
    control.setCurrentIndex(0)
    try:
        QApplication.sendEvent(
            control,
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier),
        )

        # Only the wheel is refused; arrows are how a keyboard user picks.
        assert control.currentIndex() == 1
    finally:
        control.close()
