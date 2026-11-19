# Qt controls and images

[Utility index](../README.md)

Implementations: [qt_widgets.py](../qt_widgets.py) and [qt_images.py](../qt_images.py).

## API reference

| Need | Use |
| --- | --- |
| Qt inputs without wheel edits | Explicitly import `NoWheelComboBox`, `NoWheelSpinBox`, `NoWheelDoubleSpinBox`, `install_no_wheel_controls` from `utils.qt_widgets`; subclasses ignore wheel edits even with focus; idempotent `install_no_wheel_controls(application)` also protects native dialog editors without blocking popup-list scrolling |

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

Use Fusion. After creating or obtaining a QApplication, call
`application.setStyle("Fusion")` before creating widgets, including when reusing
an application instance.

Use `NoWheelSpinBox`, `NoWheelDoubleSpinBox` and `NoWheelComboBox` for form
controls and install `install_no_wheel_controls(application)` at startup for
Qt-generated dialog editors. Wheel events must not change values even when a
control is focused; keyboard/buttons and open combo-popup scrolling still work.
Import these APIs explicitly from `utils.qt_widgets`; keep the ordinary utils
facade Qt-free. Checks: `test/test_qt_widgets.py`.

Use Qt 6's native high-DPI support and logical widget coordinates. Do not multiply
ordinary widget dimensions by the device pixel ratio. Custom raster buffers and
cached previews must track the current window's device pixel ratio and refresh
when it changes. Check startup and moves between differently scaled monitors;
fonts, controls and images must remain readable without clipping or state loss.
See https://doc.qt.io/qt-6/highdpi.html.
