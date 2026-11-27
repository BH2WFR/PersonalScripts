#!/usr/bin/env python3
"""Interactive visual check for the shared Qt styles."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import *  # noqa: E402

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


HELP = """QT STYLE PREVIEW

Compare text, buttons and fonts in light and dark themes on standard Qt controls.

Requirements:
  PySide6 6.5+.

Usage:
  python test/qt-style-preview.py
"""


def build_preview() -> QWidget:
    """Build interactive samples using the same helpers as the project tools."""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import (
        QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
    )
    from utils.gui_colors import BUTTON_COLORS, TEXT_COLORS, ButtonColor
    from utils.qt_styles import (
        is_dark_theme, on_theme_change, set_button_style, set_text_style, set_window_theme_palette,
        theme_text_color, theme_tint,
    )
    from utils.qt_widgets import monospace_ui_font, set_bold

    window = QWidget()
    window.setWindowTitle("Qt Style Preview")
    layout = QVBoxLayout(window)
    toggle = QPushButton()

    def update_toggle() -> None:
        toggle.setText("Switch to light mode" if is_dark_theme(window) else "Switch to dark mode")

    def toggle_theme() -> None:
        dark = not is_dark_theme(window)
        role = QPalette.ColorRole
        palette = QPalette(QColor("#373c44" if dark else "#f0f1f3"), QColor("#272a2f" if dark else "#f6f6f7"))
        palette.setColor(role.Base, QColor("#1d2024" if dark else "#ffffff"))
        palette.setColor(role.AlternateBase, QColor("#30343b" if dark else "#f3f4f7"))
        palette.setColor(role.Highlight, QColor("#305d98" if dark else "#2467ab"))
        palette.setColor(role.HighlightedText, QColor("white"))
        muted = QColor("#9da4af" if dark else "#767b84")
        for text_role in (role.WindowText, role.Text, role.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, text_role, muted)
        set_window_theme_palette(window, palette)
        update_toggle()

    toggle.clicked.connect(toggle_theme)
    layout.addWidget(toggle, alignment=Qt.AlignmentFlag.AlignRight)
    update_toggle()
    on_theme_change(window, update_toggle)
    colors = QHBoxLayout()
    layout.addLayout(colors)

    text_group = QGroupBox("Text colors")
    text_grid = QGridLayout(text_group)
    colors.addWidget(text_group)
    for column, title in enumerate(("Regular", "Bold", "Tinted")):
        text_grid.addWidget(QLabel(title), 0, column)
    badges: list[QLabel] = []
    for row, color in enumerate(TEXT_COLORS, 1):
        for column, bold in enumerate((False, True)):
            label = QLabel(color.title())
            set_text_style(label, color, bold=bold)
            text_grid.addWidget(label, row, column)
        badge = QLabel(color.title())
        badge.setAutoFillBackground(True)
        text_grid.addWidget(badge, row, 2)
        badges.append(badge)

    def update_badges() -> None:
        for badge, color in zip(badges, TEXT_COLORS):
            palette = badge.palette()
            palette.setColor(badge.foregroundRole(), theme_text_color(color, badge))
            palette.setColor(badge.backgroundRole(), theme_tint(color, badge))
            badge.setPalette(palette)

    update_badges()
    on_theme_change(text_group, update_badges)

    button_group = QGroupBox("Result buttons")
    button_grid = QGridLayout(button_group)
    colors.addWidget(button_group)
    for column, title in enumerate(("Enabled", "Checked", "Disabled")):
        button_grid.addWidget(QLabel(title), 0, column)
    samples: list[tuple[str, ButtonColor | None]] = [(accent.title(), accent) for accent in BUTTON_COLORS]
    samples.extend((("Default", None), ("Bold", None)))
    for row, (name, accent) in enumerate(samples, 1):
        for column in range(3):
            button = QPushButton(name)
            if column == 1:
                button.setCheckable(True)
                button.setChecked(True)
            button.setEnabled(column != 2)
            if accent is not None:
                set_button_style(button, accent)
            elif name == "Bold":
                set_bold(button)
            button_grid.addWidget(button, row, column)
    button_grid.setRowStretch(button_grid.rowCount(), 1)

    font_group = QGroupBox("Fonts")
    font_grid = QGridLayout(font_group)
    layout.addWidget(font_group)
    for column, title in enumerate(("Label", "Button", "Text field"), 1):
        font_grid.addWidget(QLabel(title), 0, column)
    sample = "Il1  O0  0123  漢汉한🤣  𓀀  𗀀"

    class SampleField(QLineEdit):
        def sizeHint(self) -> QSize:
            """Allow room for the full sample in the field's current font."""
            size = super().sizeHint()
            metrics = self.fontMetrics()
            margins = self.textMargins()
            width = metrics.horizontalAdvance(sample) + margins.left() + margins.right()
            size.setWidth(max(size.width(), width + 2 * metrics.horizontalAdvance("M")))
            return size

    fixed = monospace_ui_font()
    variants = (("Regular", False, False), ("Bold", False, True),
                ("Monospace", True, False), ("Bold monospace", True, True))
    for row, (name, mono, bold) in enumerate(variants, 1):
        font_grid.addWidget(QLabel(name), row, 0)
        for column, widget in enumerate((QLabel(sample), QPushButton(sample), SampleField(sample)), 1):
            if mono:
                widget.setFont(fixed)
            if bold:
                set_bold(widget)
            font_grid.addWidget(widget, row, column)
    return window


def main() -> int:
    Console.initialize_ansi_output()
    Console.argument_parser(HELP).parse_args()
    try:
        from PySide6.QtWidgets import QApplication
        from utils.qt_widgets import configure_qt_application
    except ImportError as exc:
        Console.print_error_and_exit(f"Cannot open preview: {exc}. Install PySide6.")
        return 1
    if sys.platform == "win32":
        System.enable_dpi_awareness()
    app = cast(QApplication, QApplication.instance() or QApplication(sys.argv))
    configure_qt_application(app)
    window = build_preview()
    window.show()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
