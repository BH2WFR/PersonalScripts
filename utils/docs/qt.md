# Qt controls

[Utility index](../README.md)

Implementation: [qt_widgets.py](../qt_widgets.py).

## API reference

| Need | Use |
| --- | --- |
| Qt inputs without wheel edits | Explicitly import `NoWheelComboBox`, `NoWheelSpinBox`, `NoWheelDoubleSpinBox`, `install_no_wheel_controls` from `utils.qt_widgets`; subclasses ignore wheel edits even with focus; idempotent `install_no_wheel_controls(application)` also protects native dialog editors without blocking popup-list scrolling |

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
