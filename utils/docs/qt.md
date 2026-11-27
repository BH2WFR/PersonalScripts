# Qt controls and images

[Utility index](../README.md)

Implementations: [qt_widgets.py](../qt_widgets.py) and [qt_images.py](../qt_images.py).

## API reference

| Need | Use |
| --- | --- |
| Show an interactive tool window | `show_foreground_tool(widget)` shows or restores the window and requests keyboard focus. On macOS it makes a one-time activation request 100 ms after showing the window. Capture any source window or selection before calling it. |
| Show a no-focus tool window | `show_nonactivating_tool(widget)` shows a configured tool window and preserves the typing target. It applies the native Windows nonactivation style before display and raises the panel on macOS. |
| Raise a native Cocoa window | `utils.macos_windows.order_window_front(window, activate=...)` restores a minimized NSWindow and raises it. Use `True` for interactive windows and `False` for nonactivating panels. Both Qt helpers load PyObjC on demand on Cocoa. If it is unavailable, they use Qt to raise the window. |
| Start a standalone macOS Qt overlay | Enter `utils.macos_windows.nonactivating_qt_session()` before creating QApplication and keep the context through the event loop so Qt startup also preserves the source application's focus. |
| Show feedback near the mouse | `show_cursor_tooltip(text, duration_ms=..., parent=None)` displays a timed Qt tooltip at the current global cursor position and preserves keyboard focus. Import it from `utils.qt_widgets` and call it on the GUI thread. |
| Set up a PySide6 tool | `configure_qt_application(application, style="Fusion")` applies the style, CJK fallback families and wheel guards. Pass a Fusion-based proxy style when the tool supplies one. |
| Customize an editor or label font | `with_cjk_fallbacks(font) -> QFont` returns a copy with installed Chinese, Japanese and Korean fallbacks appended to the requested families. Size, weight and style hint are preserved. |
| Use a monospaced UI font | `monospace_ui_font() -> QFont` uses the configured application size on macOS and the system fixed-font size on Windows and Linux. It prefers Consolas, then the platform fixed family, Menlo and DejaVu Sans Mono, with the shared regional glyph fallbacks. |
| Qt inputs without wheel edits | Explicitly import `NoWheelComboBox`, `NoWheelSpinBox`, `NoWheelDoubleSpinBox`, `install_no_wheel_controls` from `utils.qt_widgets`; subclasses ignore wheel edits even with focus; idempotent `install_no_wheel_controls(application)` also protects native dialog editors without blocking popup-list scrolling |

## Theme colors

Import Qt styling helpers from [qt_styles.py](../qt_styles.py). After creating
the application, `is_dark_theme(widget)` prefers the Qt system scheme and uses
its top-level window's active `QPalette.Window` background when the scheme is
unknown. Omitting the widget uses the application palette for that fallback.
For a manual preview, `set_window_theme_palette(widget, palette)` makes that window
use its explicit palette for both native and semantic colors. All controls in a window use the same mode. A view's `Base` brush only supplies
the background for tinted status cells. Scheme signals and palette changes are
coalesced until Qt has updated its palette; moving controls between windows
also refreshes their styles. The theme observer keeps its last colors on the Qt
object so callbacks retain their state when PySide recreates a Python wrapper.

| Use | API |
| --- | --- |
| Semantic widget text | `set_text_style(widget, color, bold=False)` accepts red, brown, blue, cyan, green, magenta, orange or gray. Pass `None` to restore the default. |
| Emphasized push or tool button | `set_button_style(button, color)` supports blue, red, green, orange and magenta. Reserve colored fills for actions that produce or copy a result. Ordinary emphasis uses `set_bold(widget)` from `utils.qt_widgets` and inherits native colors. Accent buttons have bold white text, a brighter hover fill and a darker checked or pressed fill. The focus border is navy in light mode and pale blue in dark mode. Checked or pressed buttons use pale blue against their darker fill in both modes. Disabled buttons use Qt's native disabled appearance and keep their bold caption. |
| Custom QSS | `text_stylesheet(color, bold=False)` and `button_stylesheet(color)` return a stylesheet for the current theme. The live setters above own the widget's local stylesheet and refresh it on light/dark transitions. |
| Model or delegate colors | `theme_text_color(color)` returns a QColor. `theme_tint(color, selected=False)` provides a matching background. Use `on_theme_change(view, bound_method)` to update stored brushes in an open view. |
| User-selected document or plot color | `color_swatch_icon(color)` displays the selected QColor on a button whose caption inherits the theme. |

Native tools can import [gui_colors.py](../gui_colors.py) without loading Qt.
`text_hex(color, dark=...)` and `button_fills(color, dark=...)` share the Qt color
choices. Windows Tk tools can call `windows_apps_use_dark_theme()`; Cocoa views
use their effective appearance. Each toolkit owns its rendering and theme updates.

Run `conda run -n base python test/qt-style-preview.py` from the repository root
to compare all eight text colors, five accent buttons and inherited or monospaced
fonts. The preview starts in the system theme. Use its switch to compare modes
in place and compare accent styles with the Default and Bold button samples.

## Clipboard file paths

Import `read_clipboard_paths()` from [qt_clipboard.py](../qt_clipboard.py) and
call it on the Qt GUI thread to get the original text and extracted paths together.
When only file objects are available, the source text contains the native Finder
filename list or fully encoded file URL strings from Qt, one per line. `clipboard_file_paths()` returns
only the paths. Both helpers read copied files and folders in clipboard
order. Windows Explorer file selections use Qt's local file URLs and produce
native backslashes, including UNC prefixes. On macOS, PyObjC enables direct
access to Finder's filename list or its per-item property lists. Qt local file
URLs also work without PyObjC. Absolute paths copied as text and textual
`file://` URLs use the shared path decoders. Pass `preserve_text_separators=True`
to `read_clipboard_paths()` to retain the slash spelling of path text after removing
paired quotes and decoding file URLs. An empty list means no usable paths.
Pass `parse_text_paths=False` to extract native file selections while preserving
ordinary clipboard text, including quoted paths and file URLs, as the source.

Linux file managers can supply a standard `text/uri-list`, a GNOME
`x-special/gnome-copied-files` payload, or older Nautilus text starting with
`x-special/nautilus-clipboard`. The standard list wins when both are present.
KDE file managers can also supply `application/x-kde4-urilist` as a fallback.
KDE cut flags and the GNOME `copy` or `cut` line are metadata. Only local file URLs contribute
paths. Reading the list leaves the clipboard and files untouched.

For file-manager drops, pass the event's `mimeData().urls()` to
`local_file_paths(urls)`. It preserves the order of local file URLs and uses
the same native path decoding as the clipboard reader without accessing the clipboard.

For verbatim text inspection, `original_mime_text(mime)` returns plain text or
`None` for non-text content. On the Windows Qt platform it reads external
clipboard Unicode text directly to preserve CRLF. Drag data and application-owned
MIME data use the supplied Qt payload.

## Image operations

Import these functions explicitly from `utils.qt_images`.

| Need | Use |
| --- | --- |
| Convert Pillow pixels for Qt | `qimage_from_pillow(image)` accepts RGB and RGBA, preserves alpha and returns a detached QImage. The caller chooses frame, orientation and color conversion before calling. |
| Copy an image | `copy_image_to_clipboard(image)` copies a QImage to the system clipboard on the GUI thread. |
| Save a PNG | `save_png(image, path)` accepts a QImage and a string or Path destination. It commits the encoded PNG atomically and raises `OSError` on failure, preserving an existing file. |

The calling tool chooses the image or crop, prompts for a path, remembers the
directory and presents errors. Formula typesetting belongs to the formula preview.

## GUI conventions

Simple GUI tools may use Tkinter; reserve PySide6 for complex interfaces.
The following conventions apply only to PySide6 tools.

Call `configure_qt_application(application)` before creating any widgets, including
when reusing an application. Controls and dialogs inherit the application font.
For bold labels, derive a QFont from the widget and use `setBold(True)` to retain
the family list. Use `monospace_ui_font()` for fixed-width controls. Both
font roles use `with_cjk_fallbacks` to select the regional fallback order.

Traditional Chinese, Japanese and Korean Qt locales prioritize their regional
fallback families. Other locales prioritize simplified Chinese. Shared ideographs
use the first font in the list that contains the glyph.
Windows candidates include Microsoft YaHei UI, Microsoft JhengHei UI, Microsoft
JhengHei, Yu Gothic UI and Malgun Gothic. macOS candidates include PingFang SC,
PingFang TC/HK, Hiragino Sans and Apple SD Gothic Neo.
All platforms also check installed Noto and Source Han families. Monospaced UI
fonts prefer available Sarasa Mono and Noto Sans Mono CJK faces.

Both helpers enable Qt font merging for characters outside those families.
On Windows and macOS, Qt can omit an installed font for a rare script. For
example, the macOS fallback list can miss an installed font containing Tangut.
The helper asks Qt to lay out sample text to identify native emoji, symbol and
script faces, then adds other installed families. Rare-script fallback uses
glyph coverage regardless of the family's name. On macOS it skips the LastResort
placeholder font when building this list. Linux continues to use Qt's native fallback.
For large font collections the helper uses the project's `fonttools` package
to discard redundant character maps. The result is cached for the installed
family list. Display requires a font containing the glyph. PDF document font
selection and embedded web content have their own rendering paths.

On the Windows and Cocoa backends, application setup disables informational messages from
`qt.text.font.db` for the process. Qt emits these when it tries a candidate
font that lacks OpenType support for the requested script. Font matching and
warning-level diagnostics continue normally.

Use `NoWheelSpinBox`, `NoWheelDoubleSpinBox` and `NoWheelComboBox` for form
controls. Application setup calls `install_no_wheel_controls(application)`,
which also covers Qt-generated dialog editors. In a scrollable container,
rolling over a closed combo box or any spin box should scroll the container
and preserve the control's value, even when the control has focus. Keyboard
and button input still work, and an open combo-box list scrolls normally.
Import these APIs explicitly from `utils.qt_widgets`; keep the ordinary utils
facade Qt-free. Checks: `test/test_qt_widgets.py`.

Use Qt 6's native high-DPI support and logical widget coordinates. Do not multiply
ordinary widget dimensions by the device pixel ratio. Custom raster buffers and
cached previews must track the current window's device pixel ratio and refresh
when it changes. Check startup and moves between differently scaled monitors;
fonts, controls and images must remain readable without clipping or state loss.
See https://doc.qt.io/qt-6/highdpi.html.
