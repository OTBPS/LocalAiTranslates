"""The application stylesheet, generated from tokens.

Three properties are testable because the sheet is generated rather than
written:

1. Every hex that appears in the output is a value the theme actually
   holds. A stray colour cannot survive review by being one character
   different from the right one.
2. `border-radius: 0` is emitted once from a token rather than repeated
   in a dozen rules.
3. No `:focus` rule changes geometry. The resting state already declares
   the focus border width, so focus alters `border-color` and nothing
   else. The old approach -- thicken the border, subtract a pixel of
   padding to compensate -- broke every time a control was restyled.
"""

from __future__ import annotations

from . import components
from .metrics import Metrics
from .resources import asset_path
from .semantic import Theme
from .typography import Typography


def stylesheet(theme: Theme, metrics: Metrics, fonts: Typography) -> str:
    card = components.card(theme, metrics)
    field = components.text_field(theme, metrics)
    primary = components.primary_button(theme, metrics)
    secondary = components.secondary_button(theme, metrics)
    danger = components.danger_button(theme, metrics)
    radius = metrics.radius_control
    check = asset_path("check-dark.svg" if theme.dark else "check.svg")
    # Inputs declare the focus border at rest, so this is the padding
    # that keeps the text where it was.
    pad = field.padding - (field.border_width - metrics.border)

    return "\n".join(
        part.strip("\n")
        for part in (
            f"""
        QWidget {{
            background: {theme.bg_canvas};
            color: {theme.text_primary};
            font-family: {fonts.family(fonts.size_body)};
            font-size: {fonts.size_body}px;
        }}
        QWidget#scrollContent, QScrollArea, QScrollArea > QWidget > QWidget {{
            background: {theme.bg_canvas};
            border: none;
        }}
        QLabel {{ background: transparent; }}
""",
            f"""
        QFrame#card, QFrame#noticeCard {{
            background: {card.fill};
            border: {card.border_width}px solid {card.border};
            border-radius: {card.radius}px;
        }}
        QFrame#footerBar {{
            background: {card.fill};
            border-top: {metrics.rule}px solid {theme.stroke_separator};
        }}
        QFrame#divider {{
            background: {theme.stroke_separator};
            border: none;
            min-height: {metrics.space_hair}px;
            max-height: {metrics.space_hair}px;
        }}
""",
            f"""
        QFrame#noticeCard[severity="error"] {{ background: {theme.accent_fill}; }}
        QFrame#noticeCard[severity="success"],
        QFrame#noticeCard[severity="warning"] {{ background: {theme.bg_hover}; }}
        /* Id and attribute have to be combined. An id selector outranks a
           bare attribute selector in Qt, so `QLabel[severity="error"]`
           alone loses to `QLabel#helperText`, and the detail line stays
           muted grey on the red fill -- unreadable, and easy to miss
           because the title above it does change. */
        QLabel[severity="error"],
        QLabel#noticeTitle[severity="error"],
        QLabel#helperText[severity="error"] {{ color: {theme.text_on_accent}; }}
""",
            f"""
        QLabel#noticeTitle {{
            font-family: {fonts.family(fonts.size_body)};
            font-size: {fonts.size_body}px;
            font-weight: {fonts.weight_heading};
        }}
        QLabel#heroTitle {{
            color: {theme.text_on_accent};
            font-family: {fonts.family(fonts.size_title)};
            font-size: {fonts.size_title}px;
            font-weight: {fonts.weight_heading};
        }}
        QLabel#heroMark {{
            color: {theme.text_on_accent};
            background: {theme.bg_hover};
            border: {metrics.border}px solid {theme.stroke_control};
            border-radius: {metrics.radius_small}px;
            font-size: 25px;
            font-weight: {fonts.weight_heading};
        }}
        QLabel#sectionTitle {{
            font-family: {fonts.family(fonts.size_section)};
            font-size: {fonts.size_section}px;
            font-weight: {fonts.weight_heading};
            color: {theme.text_primary};
        }}
        QLabel#fieldLabel {{
            font-size: {fonts.size_label}px;
            font-weight: {fonts.weight_label};
            color: {theme.text_secondary};
        }}
        QLabel#pageSubtitle, QLabel#helperText, QLabel#rowSubtitle {{
            color: {theme.text_secondary};
        }}
        QLabel#rowTitle {{
            color: {theme.text_primary};
            font-size: {fonts.size_body}px;
            font-weight: {fonts.weight_label};
        }}
        QLabel#rowSubtitle {{ font-size: {fonts.size_small}px; }}
        QLabel#pairingCode {{
            font-size: {fonts.size_section}px;
            font-weight: {fonts.weight_heading};
            color: {theme.text_primary};
        }}
""",
            f"""
        QLineEdit, QKeySequenceEdit, QComboBox {{
            min-height: {field.height}px;
            padding: 0 {pad}px;
            background: {field.fill};
            color: {field.text};
            border: {field.border_width}px solid {field.border};
            border-radius: {field.radius}px;
            selection-background-color: {field.selection_bg};
            selection-color: {field.selection_text};
        }}
        QLineEdit:hover, QKeySequenceEdit:hover, QComboBox:hover {{
            background: {field.fill_hover};
            border-color: {theme.accent_text};
        }}
        QLineEdit:focus, QKeySequenceEdit:focus, QComboBox:focus {{
            border-color: {field.border_focus};
        }}
        QPlainTextEdit {{
            padding: {metrics.space_tight}px {pad}px;
            background: {field.fill};
            color: {field.text};
            border: {field.border_width}px solid {field.border};
            border-radius: {field.radius}px;
            selection-background-color: {field.selection_bg};
            selection-color: {field.selection_text};
        }}
        QPlainTextEdit:hover {{ border-color: {theme.accent_text}; }}
        QPlainTextEdit:focus {{ border-color: {field.border_focus}; }}
        QPlainTextEdit[readOnly="true"] {{ background: {theme.bg_surface}; }}
""",
            f"""
        QTabWidget::pane {{ background: {theme.bg_canvas}; border: none; top: -{metrics.border}px; }}
        QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
        QTabBar::tab {{
            min-height: {metrics.height_tab}px;
            min-width: 108px;
            padding: 0 18px;
            margin-right: {metrics.space_tight}px;
            background: {theme.bg_surface};
            color: {theme.text_secondary};
            border: {metrics.border}px solid {theme.stroke_control};
            border-radius: {metrics.radius_small}px;
            font-weight: {fonts.weight_label};
        }}
        QTabBar::tab:hover {{ background: {theme.bg_hover}; color: {theme.text_primary}; }}
        QTabBar::tab:selected {{ background: {theme.accent_fill}; color: {theme.text_on_accent}; }}
        QTabBar::tab:focus {{ border-color: {theme.focus}; }}
""",
            f"""
        QComboBox::drop-down {{ border: none; width: 34px; }}
        QComboBox QAbstractItemView {{
            background: {theme.bg_surface};
            color: {theme.text_primary};
            border: {metrics.border}px solid {theme.stroke_control};
            border-radius: {metrics.radius_small}px;
            selection-background-color: {theme.bg_hover};
            selection-color: {theme.text_primary};
            padding: {metrics.space_tight}px;
            outline: 0;
        }}
""",
            f"""
        QPushButton {{
            min-height: {secondary.height}px;
            padding: 0 17px;
            background: {secondary.fill};
            color: {secondary.text};
            border: {metrics.focus_border}px solid {secondary.border};
            border-radius: {secondary.radius}px;
            font-weight: {fonts.weight_label};
        }}
        QPushButton:hover {{ background: {secondary.fill_hover}; }}
        QPushButton:pressed {{ background: {secondary.fill_pressed}; }}
        QPushButton:focus {{ border-color: {theme.focus}; }}
        QPushButton:disabled {{
            color: {theme.text_disabled};
            background: {theme.bg_disabled};
            border-color: {theme.text_disabled};
        }}
        QPushButton#primaryButton {{
            min-height: {primary.height}px;
            background: {primary.fill};
            color: {primary.text};
            border-color: {primary.border};
            border-radius: {primary.radius}px;
            font-size: 15px;
        }}
        QPushButton#primaryButton:hover {{
            background: {primary.fill_hover};
            border-color: {primary.fill_hover};
        }}
        QPushButton#primaryButton:pressed {{
            background: {primary.fill_pressed};
            border-color: {primary.fill_pressed};
        }}
        QPushButton#iconButton {{
            min-width: {metrics.height_icon}px;
            max-width: {metrics.height_icon}px;
            min-height: {metrics.height_icon}px;
            padding: 0;
            background: {theme.bg_hover};
        }}
        QPushButton#dangerButton {{
            color: {danger.text};
            background: {danger.fill};
            border-color: {danger.border};
        }}
        QPushButton#dangerButton:hover {{
            color: {theme.text_on_accent};
            background: {danger.fill_hover};
        }}
""",
            f"""
        QCheckBox {{ spacing: 10px; background: transparent; min-height: {metrics.height_control}px; }}
        QCheckBox::indicator {{
            width: 20px;
            height: 20px;
            border: {metrics.border}px solid {theme.stroke_control};
            border-radius: {metrics.radius_small}px;
            background: {theme.bg_surface_raised};
        }}
        QCheckBox::indicator:hover {{ border-color: {theme.accent_text}; }}
        QCheckBox::indicator:checked {{
            background: {theme.accent_fill};
            border-color: {theme.accent_fill};
            image: url("{check}");
        }}
        QCheckBox::indicator:disabled {{
            background: {theme.bg_disabled};
            border-color: {theme.text_disabled};
        }}
        QCheckBox:focus {{ color: {theme.accent_text}; }}
""",
            f"""
        QProgressBar {{
            min-height: 10px;
            max-height: 10px;
            border: {metrics.border}px solid {theme.stroke_control};
            border-radius: {min(radius, 5)}px;
            background: {theme.bg_surface_raised};
            text-align: center;
            color: transparent;
        }}
        QProgressBar::chunk {{
            background: {theme.accent_fill};
            border-radius: {min(radius, 5)}px;
        }}
""",
            f"""
        QMenu {{
            background: {theme.bg_surface};
            color: {theme.text_primary};
            border: {metrics.border}px solid {theme.stroke_control};
            border-radius: {metrics.radius_small}px;
            padding: {metrics.space_tight}px;
        }}
        QMenu::item {{ min-height: 30px; padding: 7px 28px 7px 12px; border-radius: {metrics.radius_small}px; }}
        QMenu::item:selected {{ background: {theme.bg_hover}; color: {theme.text_primary}; }}
        QMenu::separator {{
            height: {metrics.space_hair}px;
            background: {theme.stroke_separator};
            margin: {metrics.space_tight}px 8px;
        }}
        QToolTip {{
            color: {theme.tooltip_text};
            background: {theme.tooltip_bg};
            border: 1px solid {theme.tooltip_text};
            border-radius: {metrics.radius_small}px;
            padding: 7px;
        }}
""",
            f"""
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: {metrics.space_hair}px; }}
        QScrollBar::handle:vertical {{
            background: {theme.stroke_separator};
            border-radius: {min(radius, 4)}px;
            min-height: 32px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
""",
        )
    )
