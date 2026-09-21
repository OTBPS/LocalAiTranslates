"""Text translation workspace.

The page is a view: it collects a string and a language pair, hands them to
``ManualTranslationController`` and renders whatever that controller reports.
It performs no segmentation, no inference and no process management, and it
never writes user content anywhere except the clipboard the user asked for.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .core import LANGUAGE_NAMES, SOURCE_LANGUAGES, TARGET_LANGUAGES, swap_language_pair
from .models import get_translation_model
from .theme import asset_path
from .ui_components import make_card, make_language_row

READY_STATUS = "就绪"
TRANSLATING_STATUS = "正在翻译…"
CANCELLED_STATUS = "已取消"
PREEMPTED_STATUS = "已被截图翻译取消"
COPIED_STATUS = "译文已复制"


class TextTranslationPage(QWidget):
    """Input, output and actions for manually entered text."""

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.c = controller
        self._request_id = -1
        self._running = False
        self._message = READY_STATUS

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        text_card, text_layout = make_card("文本翻译")
        grid, self.source_language, self.swap_button, self.target_language = make_language_row(
            SOURCE_LANGUAGES, TARGET_LANGUAGES, LANGUAGE_NAMES, asset_path("swap.svg")
        )
        self.swap_button.clicked.connect(self.swap_languages)
        self.source_language.currentIndexChanged.connect(self.language_selection_changed)
        self.target_language.currentIndexChanged.connect(self.language_selection_changed)
        text_layout.addLayout(grid)

        source_label = QLabel("原文")
        source_label.setObjectName("fieldLabel")
        text_layout.addWidget(source_label)
        self.source_text = QPlainTextEdit()
        self.source_text.setAccessibleName("原文输入框")
        self.source_text.setPlaceholderText("输入或粘贴要翻译的文本")
        self.source_text.setTabChangesFocus(True)
        self.source_text.setMinimumHeight(104)
        # Ignore the editor's own tall hint so the action row stays above the fold.
        self.source_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.source_text.textChanged.connect(self.input_changed)
        text_layout.addWidget(self.source_text, 1)

        target_label = QLabel("译文")
        target_label.setObjectName("fieldLabel")
        text_layout.addWidget(target_label)
        self.target_text = QPlainTextEdit()
        self.target_text.setAccessibleName("译文输出框")
        self.target_text.setReadOnly(True)
        self.target_text.setTabChangesFocus(True)
        self.target_text.setMinimumHeight(104)
        self.target_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        text_layout.addWidget(self.target_text, 1)

        self.status = QLabel()
        self.status.setObjectName("helperText")
        self.status.setWordWrap(True)
        text_layout.addWidget(self.status)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.translate_button = QPushButton("翻译")
        self.translate_button.setObjectName("primaryButton")
        self.translate_button.setToolTip("翻译（Ctrl+Enter）")
        self.translate_button.clicked.connect(self.start_translation)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.cancel_translation)
        self.copy_button = QPushButton("复制译文")
        self.copy_button.clicked.connect(self.copy_translation)
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self.clear)
        actions.addWidget(self.translate_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        actions.addWidget(self.copy_button)
        actions.addWidget(self.clear_button)
        text_layout.addLayout(actions)
        layout.addWidget(text_card, 1)

        self.setTabOrder(self.source_language, self.swap_button)
        self.setTabOrder(self.swap_button, self.target_language)
        self.setTabOrder(self.target_language, self.source_text)
        self.setTabOrder(self.source_text, self.target_text)
        self.setTabOrder(self.target_text, self.translate_button)

        self._shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut.activated.connect(self.start_translation)

        manual = getattr(controller, "manual", None)
        if manual is not None:
            manual.started.connect(self.translation_started)
            manual.progress.connect(self.translation_progress)
            manual.finished.connect(self.translation_finished)
            manual.failed.connect(self.translation_failed)
            manual.cancelled.connect(self.translation_cancelled)

        self.load_config()
        self.refresh()

    # ----- state -----------------------------------------------------------

    def set_combo(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def load_config(self):
        self.source_language.blockSignals(True)
        self.target_language.blockSignals(True)
        try:
            self.set_combo(self.source_language, self.c.config.source_language)
            self.set_combo(self.target_language, self.c.config.target_language)
        finally:
            self.source_language.blockSignals(False)
            self.target_language.blockSignals(False)

    def model_status(self) -> str:
        try:
            name = get_translation_model(self.c.config.translation_model).display_name
        except ValueError:
            name = self.c.config.translation_model
        return f"{name} · {self.c.translator.mode}"

    def refresh(self):
        capture_busy = bool(self.c.busy) or bool(self.c.download_token)
        has_input = bool(self.source_text.toPlainText().strip())
        self.source_language.setEnabled(not capture_busy and not self._running)
        self.target_language.setEnabled(not capture_busy and not self._running)
        pair = swap_language_pair(
            self.source_language.currentData(),
            self.target_language.currentData(),
            self.c.detected_source_language,
        )
        self.swap_button.setEnabled(bool(pair) and not capture_busy and not self._running)
        self.source_text.setReadOnly(self._running)
        self.translate_button.setEnabled(has_input and not capture_busy and not self._running)
        self.cancel_button.setEnabled(self._running)
        self.copy_button.setEnabled(bool(self.target_text.toPlainText()))
        self.clear_button.setEnabled(not self._running and bool(has_input or self.target_text.toPlainText()))
        self.status.setText(f"{self.model_status()} · {self._message}")

    def set_message(self, message: str) -> None:
        self._message = message
        self.refresh()

    # ----- actions ---------------------------------------------------------

    def input_changed(self):
        self.refresh()

    def language_selection_changed(self):
        if self.c.busy or self.c.download_token:
            self.load_config()
            return
        self.c.set_language_pair(
            self.source_language.currentData(),
            self.target_language.currentData(),
        )
        self.refresh()

    def swap_languages(self):
        pair = swap_language_pair(
            self.source_language.currentData(),
            self.target_language.currentData(),
            self.c.detected_source_language,
        )
        if not pair:
            return
        self.source_language.blockSignals(True)
        self.target_language.blockSignals(True)
        try:
            self.set_combo(self.source_language, pair[0])
            self.set_combo(self.target_language, pair[1])
        finally:
            self.source_language.blockSignals(False)
            self.target_language.blockSignals(False)
        self.c.set_language_pair(*pair)
        self.refresh()

    def start_translation(self):
        if not self.translate_button.isEnabled():
            return
        self._request_id = self.c.manual.translate(
            self.source_text.toPlainText(),
            self.source_language.currentData(),
            self.target_language.currentData(),
        )

    def cancel_translation(self):
        if self._running:
            self.c.manual.cancel()

    def copy_translation(self):
        text = self.target_text.toPlainText()
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self.set_message(COPIED_STATUS)

    def clear(self):
        if self._running:
            return
        self.source_text.clear()
        self.target_text.clear()
        self.set_message(READY_STATUS)

    # ----- manual controller signals ---------------------------------------

    def _is_current(self, request_id: int) -> bool:
        return request_id == self._request_id

    def translation_started(self, request_id: int):
        self._request_id = request_id
        self._running = True
        self.target_text.clear()
        self.set_message(TRANSLATING_STATUS)

    def translation_progress(self, request_id: int, message: str):
        if self._is_current(request_id):
            self.set_message(message)

    def translation_finished(self, request_id: int, text: str):
        if not self._is_current(request_id):
            return
        self._running = False
        self.target_text.setPlainText(text)
        if self._message == TRANSLATING_STATUS:
            self._message = READY_STATUS
        self.refresh()

    def translation_failed(self, request_id: int, message: str):
        if not self._is_current(request_id):
            return
        self._running = False
        self.set_message(message)

    def translation_cancelled(self, request_id: int):
        if not self._is_current(request_id):
            return
        self._running = False
        preempted = bool(getattr(self.c, "busy", False)) or self.c.inference.capture_active
        self.set_message(PREEMPTED_STATUS if preempted else CANCELLED_STATUS)
