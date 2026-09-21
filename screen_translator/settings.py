"""Settings window for language, runtime, and model preferences."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .core import (
    CURRENT_CONFIG_VERSION,
    LANGUAGE_NAMES,
    SOURCE_LANGUAGES,
    TARGET_LANGUAGES,
    CancellationToken,
    Cancelled,
    swap_language_pair,
)
from .models import (
    TRANSLATION_MODELS,
    get_translation_model,
    install_models,
    isolate_model_for_redownload,
    models_ready,
)
from .native import set_startup
from .theme import UI_COLORS, asset_path
from .ui_components import ConstructivistHero, ToggleRow


class Settings(QWidget):
    exit_requested = Signal()

    def __init__(self, controller):
        super().__init__()
        self.c = controller
        self.setWindowTitle("屏译")
        self.setMinimumSize(680, 600)
        self.resize(760, 720)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("scrollContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(26, 22, 26, 28)
        layout.setSpacing(14)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        hero = ConstructivistHero()
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 16, 20, 16)
        hero_layout.setSpacing(16)
        mark = QLabel("译")
        mark.setObjectName("heroMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(48, 48)
        hero_layout.addWidget(mark)
        title = QLabel("屏译")
        title.setObjectName("heroTitle")
        hero_layout.addWidget(title)
        hero_layout.addStretch()
        layout.addWidget(hero)

        language_card, language_layout = self.make_card("语言")
        self.language_card = language_card
        language_grid = QGridLayout()
        language_grid.setHorizontalSpacing(12)
        language_grid.setVerticalSpacing(7)
        source_label = QLabel("输入语言")
        source_label.setObjectName("fieldLabel")
        target_label = QLabel("输出语言")
        target_label.setObjectName("fieldLabel")
        language_grid.addWidget(source_label, 0, 0)
        language_grid.addWidget(target_label, 0, 2)
        self.hotkey = QKeySequenceEdit(controller.config.hotkey)
        self.source_language = QComboBox()
        self.source_language.setAccessibleName("输入语言")
        for code in SOURCE_LANGUAGES:
            self.source_language.addItem(LANGUAGE_NAMES[code], code)
        self.swap_button = QPushButton()
        self.swap_button.setObjectName("iconButton")
        self.swap_button.setIcon(QIcon(asset_path("swap.svg")))
        self.swap_button.setIconSize(QSize(22, 22))
        self.swap_button.setAccessibleName("对调输入和输出语言")
        self.swap_button.setToolTip("对调输入和输出语言")
        self.swap_button.setFixedSize(44, 44)
        self.swap_button.clicked.connect(self.swap_languages)
        self.target_language = QComboBox()
        self.target_language.setAccessibleName("输出语言")
        for code in TARGET_LANGUAGES:
            self.target_language.addItem(LANGUAGE_NAMES[code], code)
        self.source_language.currentIndexChanged.connect(self.language_selection_changed)
        self.target_language.currentIndexChanged.connect(self.language_selection_changed)
        language_grid.addWidget(self.source_language, 1, 0)
        language_grid.addWidget(self.swap_button, 1, 1)
        language_grid.addWidget(self.target_language, 1, 2)
        language_grid.setColumnStretch(0, 1)
        language_grid.setColumnStretch(2, 1)
        language_layout.addLayout(language_grid)
        layout.addWidget(language_card)

        preferences_card, preferences_layout = self.make_card("偏好")
        shortcut_label = QLabel("全局截图快捷键")
        shortcut_label.setObjectName("fieldLabel")
        preferences_layout.addWidget(shortcut_label)
        self.hotkey.setMaximumSequenceLength(1)
        self.hotkey.setAccessibleName("全局截图快捷键")
        preferences_layout.addWidget(self.hotkey)
        startup_row = ToggleRow(
            "随 Windows 启动",
            "",
            "随 Windows 启动",
        )
        self.startup = startup_row.switch
        self.startup.setToolTip("登录后静默启动")
        self.startup.setChecked(controller.config.startup)
        preferences_layout.addWidget(startup_row)
        preferences_layout.addWidget(self.make_divider())
        cpu_row = ToggleRow(
            "CPU 兼容模式",
            "",
            "允许 CPU 兼容模式",
        )
        self.cpu = cpu_row.switch
        self.cpu.setToolTip("CUDA 不可用时使用，速度较慢")
        self.cpu.setChecked(controller.config.allow_cpu)
        preferences_layout.addWidget(cpu_row)
        layout.addWidget(preferences_card)

        model_card, model_layout = self.make_card("模型")
        model_label = QLabel("翻译模型")
        model_label.setObjectName("fieldLabel")
        model_layout.addWidget(model_label)
        self.translation_model = QComboBox()
        self.translation_model.setAccessibleName("翻译模型")
        for model_id, model in TRANSLATION_MODELS.items():
            self.translation_model.addItem(model.display_name, model_id)
        self.translation_model.currentIndexChanged.connect(self.model_selection_changed)
        model_layout.addWidget(self.translation_model)
        self.directory_label = QLabel("模型目录")
        self.directory_label.setObjectName("fieldLabel")
        model_layout.addWidget(self.directory_label)
        directory_row = QHBoxLayout()
        directory_row.setSpacing(8)
        self.directory = QLineEdit(controller.config.model_dir)
        self.directory.setAccessibleName("模型保存目录")
        browse = QPushButton("浏览")
        browse.setIcon(QIcon(asset_path("folder.svg")))
        browse.setIconSize(QSize(20, 20))
        browse.clicked.connect(self.browse)
        directory_row.addWidget(self.directory, 1)
        directory_row.addWidget(browse)
        model_layout.addLayout(directory_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.model_status = QLabel()
        self.ocr_status = QLabel()
        self.qwen_status = QLabel()
        for chip in (self.model_status, self.ocr_status, self.qwen_status):
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_row.addWidget(chip, 1)
        model_layout.addLayout(status_row)
        self.status = QLabel()
        self.status.setObjectName("helperText")
        self.status.setWordWrap(True)
        self.status.hide()
        model_layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()
        model_layout.addWidget(self.bar)
        actions = QHBoxLayout()
        self.download_button = QPushButton("下载模型")
        self.download_button.setIcon(QIcon(asset_path("download.svg")))
        self.download_button.setIconSize(QSize(19, 19))
        self.download_button.clicked.connect(self.download_models)
        self.cancel_button = QPushButton("取消下载")
        self.cancel_button.clicked.connect(
            lambda: self.c.download_token.cancel() if self.c.download_token else None
        )
        self.cancel_button.hide()
        actions.addWidget(self.download_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        self.cleanup_button = QPushButton("重新下载")
        self.cleanup_button.setObjectName("dangerButton")
        self.cleanup_button.setIcon(QIcon(asset_path("trash.svg")))
        self.cleanup_button.setIconSize(QSize(18, 18))
        self.cleanup_button.clicked.connect(self.reset_models)
        actions.addWidget(self.cleanup_button)
        model_layout.addLayout(actions)
        layout.addWidget(model_card)

        footer_bar = QFrame()
        footer_bar.setObjectName("footerBar")
        footer = QHBoxLayout(footer_bar)
        footer.setContentsMargins(26, 12, 26, 14)
        footer.setSpacing(10)
        self.exit_button = QPushButton("退出")
        self.exit_button.setObjectName("dangerButton")
        self.exit_button.clicked.connect(self.confirm_exit)
        self.save = QPushButton("保存")
        self.save.clicked.connect(self.apply)
        self.capture_button = QPushButton()
        self.capture_button.setObjectName("primaryButton")
        self.capture_button.setIcon(QIcon(asset_path("camera.svg")))
        self.capture_button.setIconSize(QSize(21, 21))
        self.capture_button.clicked.connect(self.c.toggle)
        footer.addWidget(self.exit_button)
        footer.addStretch()
        footer.addWidget(self.save)
        footer.addWidget(self.capture_button)
        outer.addWidget(footer_bar)

        self.load_config()
        self.refresh()

    def focus_language_controls(self):
        self.scroll.ensureWidgetVisible(self.language_card, 0, 16)
        self.source_language.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def confirm_exit(self):
        if (
            QMessageBox.question(
                self,
                "退出",
                "退出屏译？正在进行的任务会被取消。",
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.exit_requested.emit()

    def make_card(self, title, subtitle=None):
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        card_layout.addWidget(heading)
        if subtitle:
            hint = QLabel(subtitle)
            hint.setObjectName("helperText")
            hint.setWordWrap(True)
            card_layout.addWidget(hint)
        return card, card_layout

    def make_divider(self):
        divider = QFrame()
        divider.setObjectName("divider")
        return divider

    def set_status_chip(self, label, text, tone="neutral"):
        palette = {
            "success": ("#E8BC35", "#151515", UI_COLORS["text"]),
            "warning": ("#C51D23", "#151515", "#FFFFFF"),
            "neutral": ("#F3E9D2", "#151515", UI_COLORS["text_muted"]),
        }
        background, border, foreground = palette[tone]
        label.setText(text)
        label.setStyleSheet(
            f"background:{background};color:{foreground};border:1px solid {border};"
            "border-radius:0;padding:8px 9px;font-size:12px;font-weight:700;"
        )

    def set_combo(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def load_config(self):
        self.source_language.blockSignals(True)
        self.target_language.blockSignals(True)
        self.translation_model.blockSignals(True)
        try:
            self.hotkey.setKeySequence(self.c.config.hotkey)
            self.directory.setText(self.c.config.model_dir)
            self.startup.setChecked(self.c.config.startup)
            self.cpu.setChecked(self.c.config.allow_cpu)
            self.set_combo(self.source_language, self.c.config.source_language)
            self.set_combo(self.target_language, self.c.config.target_language)
            self.set_combo(self.translation_model, self.c.config.translation_model)
            self.capture_button.setText("开始截图")
        finally:
            self.source_language.blockSignals(False)
            self.target_language.blockSignals(False)
            self.translation_model.blockSignals(False)

    def model_selection_changed(self):
        model = get_translation_model(self.translation_model.currentData())
        self.translation_model.setToolTip(self.model_tooltip(model))
        self.refresh()

    def model_tooltip(self, model):
        fallback = ""
        if model.model_id != "qwen3-14b-q5-k-m":
            routed = "、".join(
                {"ja": "日文", "ko": "韩文"}[language]
                for language in model.fallback_languages
            )
            fallback = f"；{routed}可回退到 14B"
        return f"约 {model.approximate_size_gb:.1f} GB{fallback}"

    def language_selection_changed(self):
        if self.c.busy or self.c.download_token:
            self.load_config()
            return
        self.c.set_language_pair(
            self.source_language.currentData(),
            self.target_language.currentData(),
        )

    def swap_languages(self):
        pair = swap_language_pair(
            self.source_language.currentData(),
            self.target_language.currentData(),
            self.c.detected_source_language,
        )
        if pair:
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

    def refresh(self):
        selected_model = self.translation_model.currentData() or self.c.config.translation_model
        model = get_translation_model(selected_model)
        self.translation_model.setToolTip(self.model_tooltip(model))
        ready = models_ready(self.directory.text(), selected_model)
        self.set_status_chip(
            self.model_status,
            "模型就绪" if ready else "模型未下载",
            "success" if ready else "warning",
        )
        for label, name, mode in (
            (self.ocr_status, "OCR", self.c.ocr.mode),
            (self.qwen_status, "Qwen", self.c.translator.mode),
        ):
            if mode == "CUDA":
                self.set_status_chip(label, f"{name} CUDA", "success")
            elif mode.startswith("CPU"):
                self.set_status_chip(label, f"{name} CPU", "warning")
            else:
                self.set_status_chip(label, f"{name} 未加载")
        pair = swap_language_pair(
            self.source_language.currentData(),
            self.target_language.currentData(),
            self.c.detected_source_language,
        )
        editable = not self.c.busy and not self.c.download_token
        self.source_language.setEnabled(editable)
        self.target_language.setEnabled(editable)
        self.swap_button.setEnabled(bool(pair) and editable)
        self.hotkey.setEnabled(editable)
        self.directory.setEnabled(editable)
        self.translation_model.setEnabled(editable)
        self.startup.setEnabled(editable)
        self.cpu.setEnabled(editable)
        self.save.setEnabled(editable)
        self.download_button.setEnabled(editable)
        self.cleanup_button.setEnabled(editable and ready)
        self.capture_button.setEnabled(editable and ready)
        self.capture_button.setText("开始截图" if ready else "模型未就绪")

    def set_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def browse(self):
        directory = QFileDialog.getExistingDirectory(self, "选择模型目录", self.directory.text())
        if directory:
            self.directory.setText(directory)

    def apply(self):
        if self.c.busy or self.c.download_token:
            QMessageBox.information(self, "正在处理", "请先完成或取消当前任务")
            return False
        previous = self.c.config.hotkey
        try:
            sequence = self.hotkey.keySequence().toString()
            self.c.hotkey.register(sequence)
            path = Path(self.directory.text()).expanduser()
            if not path.is_absolute():
                raise ValueError("模型目录必须是绝对路径")
            source_language = self.source_language.currentData()
            target_language = self.target_language.currentData()
            translation_model = self.translation_model.currentData()
            if source_language not in SOURCE_LANGUAGES or target_language not in TARGET_LANGUAGES:
                raise ValueError("请选择有效的输入和输出语言")
            if translation_model not in TRANSLATION_MODELS:
                raise ValueError("请选择有效的翻译模型")
            set_startup(self.startup.isChecked())
            config = replace(
                self.c.config,
                version=CURRENT_CONFIG_VERSION,
                hotkey=sequence,
                model_dir=str(path),
                startup=self.startup.isChecked(),
                allow_cpu=self.cpu.isChecked(),
                translation_model=translation_model,
                source_language=source_language,
                target_language=target_language,
            )
            config.save()
            runtime_changed = (
                config.model_dir != self.c.config.model_dir
                or config.allow_cpu != self.c.config.allow_cpu
                or config.translation_model != self.c.config.translation_model
            )
            source_changed = config.source_language != self.c.config.source_language
            self.c.config = config
            if source_changed:
                self.c.detected_source_language = None
            if runtime_changed:
                self.c.replace_engines()
            self.c.refresh_language_actions()
            self.set_status("已保存")
            self.refresh()
            return True
        except Exception as error:
            self.c.hotkey.register(previous)
            QMessageBox.warning(self, "设置未保存", str(error))
            return False

    def download_models(self):
        if not self.apply():
            return
        self.c.download_token = CancellationToken()
        token = self.c.download_token
        self.download_button.setEnabled(False)
        self.cancel_button.show()
        self.bar.setValue(0)
        self.bar.show()
        self.set_status("正在连接…")
        self.refresh()

        def run():
            try:
                install_models(
                    self.c.config.model_dir,
                    token,
                    self.c.events.download.emit,
                    self.c.config.translation_model,
                )
                message = "模型下载和校验完成，可离线使用"
            except Cancelled:
                message = "下载已取消，下次可继续"
            except Exception as error:
                message = f"下载失败：{type(error).__name__}，请检查网络后重试"
            self.c.events.downloaded.emit(message)

        self.c.tasks.start(run, name="model-download")

    def reset_models(self):
        if self.c.busy or self.c.download_token:
            return
        root = Path(self.c.config.model_dir).resolve()
        if (
            QMessageBox.question(
                self, "重新下载", "重新下载当前模型？旧文件会保留在恢复目录。"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.c.translator.stop()
        backup = isolate_model_for_redownload(root, self.c.config.translation_model)
        if backup:
            self.set_status(f"当前模型已隔离至 {backup.relative_to(root)}")
        self.download_models()
