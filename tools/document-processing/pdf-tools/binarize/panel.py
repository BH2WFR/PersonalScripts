"""Extensible settings tabs; numeric edits commit on focus loss or mouse release."""

from dataclasses import dataclass
from typing import cast
from PySide6 import QtCore, QtGui, QtWidgets

from ..common.protocol import Json
from . import regions
from .project import Config


@dataclass(frozen=True)
class Field:
    """Presentation metadata; validation remains in the canonical engine settings."""

    key: str
    label: str
    tab: str
    minimum: float = 0
    maximum: float = 1
    step: float = 1
    choices: tuple[tuple[str, str], ...] = ()
    slider: bool = False


FIELDS: tuple[Field, ...] = (
    Field("dpi", "Base DPI", "Text", 36, 1200),
    Field("mode", "Method", "Text", choices=(("fixed", "Fixed threshold"), ("sauvola", "Sauvola"))),
    Field("threshold", "Threshold", "Text", 1, 255, slider=True),
    Field("window", "Sauvola window (odd)", "Text", 3, 501, 2),
    Field("k", "Sauvola k", "Text", .01, 1, .01),
    Field("levels", "Adjust black/white points", "Text"),
    Field("black_point", "Black point", "Text", 0, 254),
    Field("white_point", "White point", "Text", 1, 255),
    Field("upscale", "Upscale factor", "Text", 1, 4),
    Field("sharpen", "Unsharp mask", "Text"),
    Field("sharpen_radius", "Sharpen radius", "Text", .1, 10, .1),
    Field("sharpen_percent", "Sharpen amount (%)", "Text", 1, 500),
    Field("regions.enabled", "Protect illustrations automatically", "Images"),
    Field("regions.profile", "Detection preset", "Images", choices=(
        ("text-first", "Text first"), ("balanced", "Balanced"), ("image-first", "Image first"))),
    Field("regions.threshold", "Detection threshold", "Images", .1, 2, .05),
    Field("regions.mode", "Protected image mode", "Images", choices=(
        ("keep", "Keep original colors / grayscale"), ("gray8", "Gray8 - remove color"),
        ("gray2", "Gray2 - 4 levels"), ("gray4", "Gray4 - 16 levels"),
        ("color2", "Color2 - 4 colors"), ("color4", "Color4 - 16 colors"))),
    Field("regions.codec", "Crop compression", "Images", choices=(("jpeg", "JPEG"), ("flate", "Lossless Flate"))),
    Field("regions.quality", "JPEG quality", "Images", 1, 95, slider=True),
    Field("regions.dither", "Dithering", "Images", choices=(
        ("none", "None"), ("ordered", "Ordered"), ("diffusion", "Error diffusion"))),
    Field("regions.contrast", "Crop contrast (1 = off)", "Images", 1, 4, .1),
    Field("regions.denoise", "Remove isolated binary specks", "Cleanup"),
    Field("regions.denoise_area", "Maximum speck area at 240 DPI", "Cleanup", .1, 100, .5),
    Field("regions.denoise_distance", "Distance from other ink", "Cleanup", 1, 100),
    Field("regions.clean_background", "Clean shaded text (Sauvola)", "Cleanup"),
    Field("vectors", "Vector colors: non-white to black", "Cleanup"),
)

type Editor = QtWidgets.QCheckBox | QtWidgets.QComboBox | QtWidgets.QSpinBox | QtWidgets.QDoubleSpinBox


class SettingsPanel(QtWidgets.QTabWidget):
    """Edit a complete profile through grouped, dependency-aware controls.

    Signals:
        configChanged: A valid immutable Config after a committed edit.
        validityChanged: Whether displayed edits are valid for preview/export.
    """

    configChanged = QtCore.Signal(object)
    validityChanged = QtCore.Signal(bool)
    interactionFinished = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = Config()
        self.valid = True
        self.imported_regions = False
        self._loading = False
        self.editing = False
        self.editors: dict[str, Editor] = {}
        self.sliders: dict[str, QtWidgets.QSlider] = {}
        self._keys: dict[QtCore.QObject, str] = {}
        self._forms: dict[str, QtWidgets.QFormLayout] = {}
        values = self.config.values()
        for name in ("Text", "Images", "Cleanup"):
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            body = QtWidgets.QWidget()
            form = QtWidgets.QFormLayout(body)
            form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
            scroll.setWidget(body)
            self.addTab(scroll, name)
            self._forms[name] = form
        # ── create editors from the same field table ──
        for spec in FIELDS:
            original = values[spec.key]
            editor: Editor
            if spec.choices:
                combo = QtWidgets.QComboBox()
                for value, label in spec.choices:
                    combo.addItem(label, value)
                combo.activated.connect(lambda _, key=spec.key: self._commit(key))
                editor = combo
            elif type(original) is bool:
                check = QtWidgets.QCheckBox(spec.label)
                check.toggled.connect(lambda _, key=spec.key: self._commit(key))
                editor = check
            else:
                if type(original) is float or original is None:
                    spin = QtWidgets.QDoubleSpinBox()
                    spin.setDecimals(2)
                    spin.setRange(spec.minimum, spec.maximum)
                    spin.setSingleStep(spec.step)
                else:
                    spin = QtWidgets.QSpinBox()
                    spin.setRange(int(spec.minimum), int(spec.maximum))
                    spin.setSingleStep(int(spec.step))
                spin.setKeyboardTracking(False)
                spin.lineEdit().textEdited.connect(self._editing_started)
                spin.editingFinished.connect(lambda key=spec.key: self._commit(key))
                spin.installEventFilter(self)
                self._keys[spin] = spec.key
                editor = spin
            self.editors[spec.key] = editor
            form = self._forms[spec.tab]
            if isinstance(editor, QtWidgets.QCheckBox):
                form.addRow(editor)
            elif spec.slider:
                row = QtWidgets.QWidget()
                layout = QtWidgets.QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
                slider.setRange(int(spec.minimum), int(spec.maximum))
                spin = cast(QtWidgets.QSpinBox, editor)
                slider.valueChanged.connect(spin.setValue)
                spin.valueChanged.connect(slider.setValue)
                slider.sliderReleased.connect(lambda key=spec.key: self._commit(key))
                slider.sliderPressed.connect(self._editing_started)
                slider.installEventFilter(self)
                self._keys[slider] = spec.key
                self.sliders[spec.key] = slider
                layout.addWidget(slider, 1)
                layout.addWidget(spin)
                form.addRow(spec.label, row)
            else:
                form.addRow(spec.label, editor)
        hint = QtWidgets.QLabel("Text backgrounds always use lossless CCITT Group 4.\nLow-depth crops use lossless Flate.")
        hint.setWordWrap(True)
        self._forms["Images"].addRow(hint)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c43b32;")
        self._forms["Cleanup"].addRow(self.error)
        self.set_config(self.config)

    def set_config(self, config: Config) -> None:
        """Populate controls without generating edits or page assignments."""
        self._loading = True
        try:
            self.config = config
            values = config.values()
            values["regions.threshold"] = config.processing.regions.cutoff
            for key, editor in self.editors.items():
                value = values[key]
                blocker = QtCore.QSignalBlocker(editor)
                if isinstance(editor, QtWidgets.QCheckBox):
                    editor.setChecked(bool(value))
                elif isinstance(editor, QtWidgets.QComboBox):
                    editor.setCurrentIndex(editor.findData(value))
                elif isinstance(editor, QtWidgets.QDoubleSpinBox):
                    editor.setValue(float(cast(float, value)))
                else:
                    editor.setValue(int(cast(int, value)))
                del blocker
                if key in self.sliders:
                    self.sliders[key].setValue(int(cast(int, value)))
            self.valid = True
            self.editing = False
            self.error.clear()
            self._availability()
        finally:
            self._loading = False
        self.validityChanged.emit(True)

    def _values(self) -> dict[str, Json]:
        result: dict[str, Json] = {}
        for key, editor in self.editors.items():
            if isinstance(editor, QtWidgets.QCheckBox):
                result[key] = editor.isChecked()
            elif isinstance(editor, QtWidgets.QComboBox):
                result[key] = str(editor.currentData())
            else:
                result[key] = editor.value()
        return result

    def _editing_started(self, *args: object) -> None:
        if not self._loading:
            self.editing = True

    def commit_pending(self) -> bool:
        """Finish numeric edits before navigation or export snapshots are created."""
        for editor in self.editors.values():
            if isinstance(editor, QtWidgets.QAbstractSpinBox):
                editor.interpretText()
        self._commit("")
        return self.valid

    def has_active_edit(self) -> bool:
        """Defer only a currently focused text edit or a slider still being dragged.

        A stale textEdited flag must never block original/profile changes after
        the editor loses focus or becomes disabled.
        """
        if any(slider.isSliderDown() for slider in self.sliders.values()):
            return True
        focus = QtWidgets.QApplication.focusWidget()
        if focus is None or not self.editing:
            return False
        return any(editor.isEnabled() and isinstance(editor, QtWidgets.QAbstractSpinBox)
                   and (focus is editor or editor.isAncestorOf(focus)) for editor in self.editors.values())

    def _commit(self, key: str) -> None:
        if self._loading:
            return
        values = self._values()
        if (key != "regions.profile" and self.config.processing.regions.threshold is None
                and values["regions.threshold"] == self.config.processing.regions.cutoff):
            values["regions.threshold"] = None
        if key == "regions.profile":
            values["regions.threshold"] = regions._PROFILE_THRESHOLDS[regions._Profile(str(values[key]))]
        if key == "regions.clean_background" and values[key]:
            values["mode"] = "sauvola"
        elif key == "mode" and values[key] == "fixed":
            values["regions.clean_background"] = False
        try:
            config = Config.from_values(values)
        except ValueError as exc:
            self.valid = False
            self.error.setText(str(exc))
            self.setToolTip(str(exc))
            self.validityChanged.emit(False)
            return
        changed = config != self.config
        self.set_config(config)
        self.setToolTip("")
        if changed:
            self.configChanged.emit(config)
        self.interactionFinished.emit()

    def _availability(self) -> None:
        settings = self.config.processing
        image = settings.regions
        active = image.enabled or image.clean_background or self.imported_regions
        enabled = {
            "threshold": settings.mode.value == "fixed", "window": settings.mode.value == "sauvola",
            "k": settings.mode.value == "sauvola", "black_point": settings.levels, "white_point": settings.levels,
            "sharpen_radius": settings.sharpen, "sharpen_percent": settings.sharpen,
            "regions.profile": image.enabled, "regions.threshold": image.enabled,
            "regions.mode": active, "regions.contrast": active,
            "regions.codec": active and image.mode in (regions._Mode.KEEP, regions._Mode.GRAY8),
            "regions.quality": active and image.mode in (regions._Mode.KEEP, regions._Mode.GRAY8) and image.codec == regions._Codec.JPEG,
            "regions.dither": active and image.mode not in (regions._Mode.KEEP, regions._Mode.GRAY8),
            "regions.denoise_area": image.denoise, "regions.denoise_distance": image.denoise,
        }
        for key, state in enabled.items():
            self.editors[key].setEnabled(state)
            if key in self.sliders:
                self.sliders[key].setEnabled(state)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """Commit spin-button and slider keyboard edits only when interaction ends."""
        if watched in self._keys and event.type() in (
                QtCore.QEvent.Type.MouseButtonRelease, QtCore.QEvent.Type.KeyRelease, QtCore.QEvent.Type.FocusOut):
            if event.type() != QtCore.QEvent.Type.KeyRelease or isinstance(watched, QtWidgets.QSlider):
                key = self._keys[watched]
                QtCore.QTimer.singleShot(0, lambda: self._commit(key))
        return super().eventFilter(watched, event)
