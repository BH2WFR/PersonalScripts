"""Theme-aware Qt widget styles and color swatches."""

from collections.abc import Callable
from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets

from .gui_colors import ButtonColor, TextColor, button_fills, text_hex
from .qt_widgets import set_bold


_WINDOW_THEME_PROPERTY = "useWindowThemePalette"


def set_window_theme_palette(widget: QtWidgets.QWidget, palette: QtGui.QPalette) -> None:
    """Explicitly preview a palette in this window, including its semantic colors."""
    window = widget.window()
    window.setProperty(_WINDOW_THEME_PROPERTY, True)
    window.setPalette(palette)


def is_dark_theme(widget: QtWidgets.QWidget | None = None) -> bool:
    """Use Qt's system scheme, falling back to the top-level window background."""
    window = widget.window() if widget is not None else None
    if window is None or not window.property(_WINDOW_THEME_PROPERTY):
        scheme = QtGui.QGuiApplication.styleHints().colorScheme()
        if scheme != QtCore.Qt.ColorScheme.Unknown:
            return scheme == QtCore.Qt.ColorScheme.Dark
    palette = window.palette() if window is not None else QtGui.QGuiApplication.palette()
    background = palette.color(QtGui.QPalette.ColorGroup.Active, QtGui.QPalette.ColorRole.Window)
    return QtGui.qGray(background.rgb()) < 128


def theme_text_color(color: TextColor, widget: QtWidgets.QWidget | None = None) -> QtGui.QColor:
    """Resolve a semantic text color for model items or custom painting."""
    return QtGui.QColor(text_hex(color, dark=is_dark_theme(widget)))


def theme_tint(color: TextColor, widget: QtWidgets.QWidget | None = None, *, selected: bool = False) -> QtGui.QColor:
    """Blend a semantic foreground into the view background for status badges."""
    palette = widget.palette() if widget is not None else QtGui.QGuiApplication.palette()
    base = palette.color(QtGui.QPalette.ColorRole.Base)
    ink = theme_text_color(color, widget)
    amount = 0.22 if selected else 0.10
    return QtGui.QColor.fromRgbF(
        base.redF() + amount * (ink.redF() - base.redF()),
        base.greenF() + amount * (ink.greenF() - base.greenF()),
        base.blueF() + amount * (ink.blueF() - base.blueF()),
    )


def text_stylesheet(color: TextColor, widget: QtWidgets.QWidget | None = None, *, bold: bool = False) -> str:
    """Return enabled text styling, leaving disabled text to the Qt palette."""
    weight = " font-weight: bold;" if bold else ""
    return f"*:enabled {{ color: {theme_text_color(color, widget).name()};{weight} }}"


def button_stylesheet(color: ButtonColor, widget: QtWidgets.QWidget | None = None) -> str:
    """Return emphasis styling for push/tool buttons, including focus and checked states."""
    dark = is_dark_theme(widget)
    normal, hover, pressed = button_fills(color, dark=dark)
    pale_blue = "#a6cfff"
    focus_border = pale_blue if dark else "#071a37"
    return (
        "QAbstractButton { font-weight: bold; }"
        f"QAbstractButton:enabled {{ background-color: {normal}; color: white;"
        " border: 2px solid transparent; border-radius: 3px; padding: 0.2em 0.6em; }"
        f"QAbstractButton:enabled:hover {{ background-color: {hover}; }}"
        f"QAbstractButton:enabled:checked {{ background-color: {pressed}; }}"
        f"QAbstractButton:enabled:pressed {{ background-color: {pressed}; }}"
        f"QAbstractButton:enabled:focus {{ border-color: {focus_border}; outline: none; }}"
        "QAbstractButton:enabled:focus:checked, QAbstractButton:enabled:focus:pressed"
        f" {{ border-color: {pale_blue}; }}"
    )


class _ThemeChanges(QtCore.QObject):
    """Coalesce scheme, palette and reparent events after Qt has applied its palette."""

    def __init__(self, app: QtGui.QGuiApplication) -> None:
        super().__init__(app)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        app.styleHints().colorSchemeChanged.connect(self.schedule)
        app.installEventFilter(self)

    @QtCore.Slot()
    def schedule(self) -> None:
        if not self.timer.isActive():
            self.timer.start(0)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() in (QtCore.QEvent.Type.ApplicationPaletteChange, QtCore.QEvent.Type.PaletteChange,
                            QtCore.QEvent.Type.ParentChange):
            self.schedule()
        elif event.type() == QtCore.QEvent.Type.DynamicPropertyChange:
            change = cast(QtCore.QDynamicPropertyChangeEvent, event)
            if change.propertyName() == _WINDOW_THEME_PROPERTY.encode():
                self.schedule()
        return False


class _WidgetTheme(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, widget: QtWidgets.QWidget) -> None:
        super().__init__(widget)
        # Designer forms can release a Python wrapper before Qt destroys its children.
        self.setProperty("themeColors", self._colors(widget))

    @staticmethod
    def _colors(widget: QtWidgets.QWidget) -> tuple[bool, int]:
        return is_dark_theme(widget), widget.palette().color(QtGui.QPalette.ColorRole.Base).rgba()

    @QtCore.Slot()
    def update(self) -> None:
        colors = self._colors(cast(QtWidgets.QWidget, self.parent()))
        if colors != self.property("themeColors"):
            self.setProperty("themeColors", colors)
            self.changed.emit()


def on_theme_change(widget: QtWidgets.QWidget, callback: Callable[[], None]) -> None:
    """Refresh a bound method when the window mode or the view's Base brush changes."""
    app = cast(QtGui.QGuiApplication, QtGui.QGuiApplication.instance())
    monitor = app.findChild(_ThemeChanges, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly)
    if monitor is None:
        monitor = _ThemeChanges(app)
    theme = widget.findChild(_WidgetTheme, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly)
    if theme is None:
        theme = _WidgetTheme(widget)
        monitor.timer.timeout.connect(theme.update)
    theme.changed.connect(callback)


class _WidgetStyle(QtCore.QObject):
    def __init__(self, widget: QtWidgets.QWidget) -> None:
        super().__init__(widget)
        self.text: TextColor | None = None
        self.button: ButtonColor | None = None
        self.original_font: QtGui.QFont | None = None
        self.bold = False
        widget.installEventFilter(self)
        on_theme_change(widget, self.refresh)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if self.button is not None and event.type() == QtCore.QEvent.Type.EnabledChange:
            self.refresh()
        return False

    @QtCore.Slot()
    def refresh(self) -> None:
        widget = cast(QtWidgets.QWidget, self.parent())
        if self.button is not None:
            # Native painting also inherits a custom window's disabled palette on theme changes.
            sheet = button_stylesheet(self.button, widget) if widget.isEnabled() else ""
        elif self.text is not None:
            sheet = text_stylesheet(self.text, widget, bold=self.bold)
        else:
            sheet = ""
        if widget.styleSheet() != sheet:
            widget.setStyleSheet(sheet)


def _binding(widget: QtWidgets.QWidget) -> _WidgetStyle:
    return widget.findChild(_WidgetStyle, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly) or _WidgetStyle(widget)


def set_text_style(widget: QtWidgets.QWidget, color: TextColor | None, *, bold: bool = False) -> None:
    """Apply a live semantic foreground. Pass None to restore the widget default."""
    binding = _binding(widget)
    if binding.original_font is not None:
        widget.setStyleSheet("")
        widget.setFont(binding.original_font)
        binding.original_font = None
    binding.text, binding.bold, binding.button = color, bold, None
    binding.refresh()


def set_button_style(button: QtWidgets.QAbstractButton, color: ButtonColor) -> None:
    """Apply a theme-aware accent fill and bold white caption to a result action."""
    binding = _binding(button)
    if binding.button is None:
        button.setStyleSheet("")
        binding.original_font = button.font()
        set_bold(button)
    binding.button = color
    binding.refresh()


def color_swatch_icon(color: QtGui.QColor) -> QtGui.QIcon:
    """Show the exact selected data color while leaving the button label readable."""
    swatch = QtGui.QPixmap(16, 16)
    swatch.fill(color)
    return QtGui.QIcon(swatch)
