"""Shared PySide6 application setup, font fallback and form controls."""

from functools import lru_cache
import struct
import sys

from PySide6 import QtCore, QtGui, QtWidgets


def show_nonactivating_tool(widget: QtWidgets.QWidget) -> None:
    """Show a no-focus tool window, applying the native Windows style before mapping.

    Callers configure the window flags, including WindowDoesNotAcceptFocus.
    Raises OSError if Windows cannot apply the extended style.
    """
    if sys.platform == "win32" and QtGui.QGuiApplication.platformName() == "windows":
        import ctypes
        from ctypes import wintypes

        hwnd = wintypes.HWND(int(widget.winId()))
        api = ctypes.WinDLL("user32", use_last_error=True)
        api.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        api.GetWindowLongW.restype = wintypes.LONG
        api.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        api.SetWindowLongW.restype = wintypes.LONG
        style = api.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        ctypes.set_last_error(0)
        if not api.SetWindowLongW(hwnd, -20, style | 0x08000000) and ctypes.get_last_error():  # WS_EX_NOACTIVATE
            raise ctypes.WinError(ctypes.get_last_error())
    widget.show()


def show_cursor_tooltip(text: str, *, duration_ms: int, parent: QtWidgets.QWidget | None = None) -> None:
    """Show a Qt tooltip at the current pointer position without taking focus."""
    QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), text, parent, msecShowTime=duration_ms)


_WINDOWS_FAMILIES = {
    "SC": ("Microsoft YaHei UI", "Microsoft YaHei"),
    "TC": ("Microsoft JhengHei UI", "Microsoft JhengHei"),
    "JP": ("Yu Gothic UI", "Meiryo UI", "Yu Gothic", "Meiryo"),
    "KR": ("Malgun Gothic",),
}
_MACOS_FAMILIES = {
    "SC": ("PingFang SC",),
    "TC": ("PingFang TC", "PingFang HK"),
    "JP": ("Hiragino Sans", "Hiragino Kaku Gothic ProN"),
    "KR": ("Apple SD Gothic Neo",),
}
_SARASA_MONO = {"SC": "Sarasa Mono SC", "TC": "Sarasa Mono TC", "JP": "Sarasa Mono J", "KR": "Sarasa Mono K"}
_SOURCE_HAN = {
    "SC": ("Source Han Sans SC", "Source Han Sans CN"),
    "TC": ("Source Han Sans TC", "Source Han Sans TW"),
    "JP": ("Source Han Sans JP", "Source Han Sans"),
    "KR": ("Source Han Sans KR", "Source Han Sans K"),
}
# Qt encodes the fallback face index in one byte. Leave room for private fonts
# and caller-supplied aliases when using the entire installed catalog.
_DIRECT_FALLBACK_FAMILY_LIMIT = 240


@lru_cache(maxsize=1)
def _supplemental_fallback_families(platform: str, installed: tuple[str, ...]) -> tuple[str, ...]:
    """Find installed faces omitted from the Windows or macOS native fallback list."""
    # Retain the platform's usual script fonts ahead of broad third-party faces.
    system_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont)
    samples = [QtGui.QFontDatabase.writingSystemSample(script) for script in QtGui.QFontDatabase.writingSystems()]
    preferred = [system_font.family()]
    # Query emoji separately so a script font with monochrome emoji cannot take priority.
    for sample in ("😀", "⠿ ∑", " ".join(samples)):
        layout = QtGui.QTextLayout(sample, system_font)
        layout.beginLayout()
        layout.createLine()
        layout.endLayout()
        for run in layout.glyphRuns():
            face = run.rawFont()
            if face.isValid() and any(run.glyphIndexes()):
                preferred.append(face.familyName())
    if platform == "cocoa":
        # Core Text's LastResort glyphs are placeholders, including for Tangut.
        installed = tuple(name for name in installed if name.lstrip(".").replace(" ", "").casefold() != "lastresort")
    native = dict.fromkeys(name for name in preferred if name in installed)
    ordered = dict.fromkeys([*native, *installed])
    if len(ordered) <= _DIRECT_FALLBACK_FAMILY_LIMIT:
        return tuple(ordered)
    try:
        from fontTools.ttLib import TTFont, TTLibError
        from fontTools.ttLib.tables._c_m_a_p import table__c_m_a_p
    except ImportError:
        return tuple(ordered)

    covered: set[int] = set()
    seen_tables: set[bytes] = set()
    result = list(native)
    # Only the cmap is needed. Its glyph IDs can be decoded without loading outlines.
    decoder = TTFont()
    decoder.setGlyphOrder([".notdef"])
    for family in ordered:
        raw = QtGui.QRawFont.fromFont(QtGui.QFont(family))
        if not raw.isValid():
            continue
        data = bytes(raw.fontTable("cmap").data())
        if not data or data in seen_tables:
            continue
        seen_tables.add(data)
        cmap = table__c_m_a_p("cmap")
        try:
            cmap.decompile(data, decoder)
            mapping = cmap.getBestCmap()
        except (TTLibError, struct.error, ValueError, IndexError, AssertionError):
            continue
        if mapping and not covered.issuperset(mapping):
            if family not in native:
                result.append(family)
            covered.update(mapping)
    return tuple(result)


def with_cjk_fallbacks(font: QtGui.QFont) -> QtGui.QFont:
    """Copy a UI font with regional CJK preferences and system glyph fallback.

    Existing families and font attributes keep their priority. For overlapping
    glyphs, traditional Chinese, Japanese and Korean locales prefer their own
    regional forms. Fixed-width fonts prefer CJK mono faces.
    Call after creating the GUI application.
    """
    regions = {
        QtCore.QLocale.Script.TraditionalHanScript: ("TC", "SC", "JP", "KR"),
        QtCore.QLocale.Script.JapaneseScript: ("JP", "SC", "TC", "KR"),
        QtCore.QLocale.Script.KoreanScript: ("KR", "SC", "TC", "JP"),
    }.get(QtCore.QLocale().script(), ("SC", "TC", "JP", "KR"))
    native = {"win32": _WINDOWS_FAMILIES, "darwin": _MACOS_FAMILIES}.get(sys.platform, {})
    candidates: list[str] = []
    if font.fixedPitch() or font.styleHint() in (QtGui.QFont.StyleHint.Monospace, QtGui.QFont.StyleHint.TypeWriter):
        for region in regions:
            candidates.extend((_SARASA_MONO[region], f"Noto Sans Mono CJK {region}"))
    for region in regions:
        candidates.extend(native.get(region, ()))
        candidates.extend((f"Noto Sans CJK {region}", f"Noto Sans {region}", *_SOURCE_HAN[region]))
    available = QtGui.QFontDatabase.families()
    installed = set(available)
    result = QtGui.QFont(font)
    strategy = font.styleStrategy()
    if strategy & QtGui.QFont.StyleStrategy.NoFontMerging:
        result.setStyleStrategy(strategy & ~QtGui.QFont.StyleStrategy.NoFontMerging)
    families = font.families() or [QtGui.QFontInfo(font).family()]
    platform = QtGui.QGuiApplication.platformName()
    if platform in ("windows", "cocoa"):
        candidates.extend(_supplemental_fallback_families(platform, tuple(available)))
    fallbacks = [family for family in dict.fromkeys(candidates) if family in installed and family not in families]
    if fallbacks:
        result.setFamilies([*families, *fallbacks])
    return result


def configure_qt_application(application: QtWidgets.QApplication, style: str | QtWidgets.QStyle = "Fusion") -> None:
    """Apply the tool's Fusion style, font fallbacks and wheel guards before constructing widgets."""
    if application.platformName() in ("windows", "cocoa"):
        # Qt reports each rejected OpenType candidate at info level during font matching.
        QtCore.QLoggingCategory.setFilterRules("qt.text.font.db.info=false")
    application.setStyle(style)
    font = application.font()
    configured = with_cjk_fallbacks(font)
    if configured != font:
        application.setFont(configured)
    install_no_wheel_controls(application)


class NoWheelComboBox(QtWidgets.QComboBox):
    """Ignore wheel changes even with focus; retain popup and keyboard selection."""

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Leave the selection unchanged and let the parent handle scrolling."""
        event.ignore()


class NoWheelSpinBox(QtWidgets.QSpinBox):
    """Integer input that leaves wheel scrolling to its containing widget."""

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Ignore the wheel without modifying the integer value."""
        event.ignore()


class NoWheelDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    """Floating-point input that leaves wheel scrolling to its container."""

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Ignore the wheel without modifying the numeric value."""
        event.ignore()


class _NoWheelFilter(QtCore.QObject):
    """Cover native dialogs and editable fields, without blocking popup lists."""

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() != QtCore.QEvent.Type.Wheel:
            return False
        control = watched.parent() if isinstance(watched, QtWidgets.QLineEdit) else watched
        if isinstance(control, (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
            event.ignore()
            return True
        return False


def install_no_wheel_controls(application: QtWidgets.QApplication) -> None:
    """Enforce no-wheel value editing, including controls made by QInputDialog.

    Args:
        application: Existing GUI application; owns the filter until shutdown.
    Returns:
        None. Repeated installation on the same application is harmless.
    Side effects:
        Installs an application event filter. Wheel events over combo/spin
        editors are ignored so ancestor scroll areas can handle them. Does not
        change Qt classes, keyboard/mouse-click behavior or popup-list scrolling.
    """
    if application.findChild(_NoWheelFilter) is None:
        application.installEventFilter(_NoWheelFilter(application))
