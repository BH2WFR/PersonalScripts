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
    Field("dpi", "Sampling target (DPI)", "Text", 36, 1200),
    Field("dpi_policy", "Below-target image sampling", "Text", choices=(
        ("cap", "Use native image DPI"), ("target", "Render at target DPI"))),
    Field("upscale", "Lanczos text enlargement", "Text", 1, 4),
    Field("mode", "Method", "Text", choices=(("fixed", "Fixed threshold"), ("sauvola", "Sauvola"))),
    Field("threshold", "Threshold", "Text", 1, 255, slider=True),
    Field("window", "Sauvola window (odd)", "Text", 3, 501, 2),
    Field("k", "Sauvola k", "Text", .01, 1, .01),
    Field("levels", "Adjust black/white points", "Text"),
    Field("black_point", "Black point", "Text", 0, 254),
    Field("white_point", "White point", "Text", 1, 255),
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
        ("color2", "Color2 - 4 colors"), ("color4", "Color4 - 16 colors"),
        ("color8", "Color8 - 256 colors"))),
    Field("regions.codec", "Crop compression", "Images", choices=(("jpeg", "JPEG"), ("flate", "Lossless Flate"))),
    Field("regions.quality", "JPEG quality", "Images", 1, 95, slider=True),
    Field("regions.dither", "Dithering", "Images", choices=(
        ("none", "None"), ("ordered", "Ordered"), ("diffusion", "Error diffusion"))),
    Field("regions.contrast", "Crop contrast (1 = off)", "Images", 1, 4, .1),
    Field("regions.whiten", "Whiten image crop background", "Images"),
    Field("regions.white_point", "Image crop white point", "Images", 1, 255, slider=True),
    Field("regions.color_text_mode", "Colored text mode", "Images", choices=(
        ("follow", "Follow illustration settings"), ("color4", "Color4 - 16 colors"),
        ("color8", "Color8 - 256 colors"))),
    Field("regions.color_text_contrast", "Text crop contrast (1 = off)", "Images", 1, 4, .1),
    Field("regions.color_text_whiten", "Whiten text crop background", "Images"),
    Field("regions.color_text_white_point", "Text crop white point", "Images", 1, 255, slider=True),
    Field("regions.denoise", "Remove isolated binary specks", "Cleanup"),
    Field("regions.denoise_area", "Maximum speck area at 240 DPI", "Cleanup", .1, 100, .5),
    Field("regions.denoise_distance", "Distance from other ink", "Cleanup", 1, 100),
    Field("regions.clean_background", "Clean shaded text (Sauvola)", "Cleanup"),
    Field("vectors", "Vector colors: non-white to black", "Cleanup"),
)

GROUP_STARTS = {
    "dpi": "Resolution", "mode": "Binarization", "levels": "Black / white points",
    "sharpen": "Sharpening", "regions.enabled": "Region detection",
    "regions.mode": "Protected image appearance", "regions.codec": "Compression",
    "regions.dither": "Tone reproduction", "regions.denoise": "Binary speck removal",
    "regions.color_text_mode": "Colored text",
    "regions.whiten": "Image background",
    "regions.clean_background": "Shaded text", "vectors": "Vector graphics",
}

TIPS = {
    "dpi": "Target sampling resolution of embedded images, based on their size on the PDF page. Higher values retain small strokes but increase time and size. Start at 300; try 200–240 for larger text. Text/vector objects are retained separately.",
    "dpi_policy": "Use native image DPI (default) caps sampling below the target for low-resolution images. Render at target DPI asks the PDF renderer to enlarge them, which may keep visible pixel steps. The Images tab shows each image's effective DPI. For smooth one-bit text, use native DPI and then the Lanczos enlargement below.",
    "upscale": "After sampling, enlarge grayscale with Lanczos before binarization. A 96-DPI image at 3x produces roughly 288-DPI one-bit text. On low-resolution text, try 2x for smaller files or 3x for smoother zoomed edges. Pixel count grows by the factor squared; use a separate profile for high-resolution pages.",
    "mode": "Fixed threshold suits evenly lit scans. Sauvola computes a local threshold and usually handles uneven gray backgrounds better. Compare a difficult page before exporting.",
    "threshold": "Pixels darker than this value become black (0=black, 255=white). Increase to retain faint strokes; decrease to remove gray noise. Start near 180 and check thin strokes and punctuation.",
    "window": "Size of the local Sauvola neighborhood in base-rendered pixels; must be odd. Larger windows include more surrounding background; very small windows may break strokes. Start at 31 and compare 21–61.",
    "k": "Sauvola sensitivity. Smaller values generally retain more black and faint strokes; larger values suppress more background but may erase weak text. Start at 0.20 and change by 0.02–0.05.",
    "levels": "Stretch grayscale between the black and white points before thresholding. Helps faded scans; start off. Illustration detection uses the source image before this adjustment.",
    "black_point": "Values at or below this become black. Raising it darkens faint text but may turn shaded backgrounds black. Start at 0 and increase gradually; it must stay below the white point.",
    "white_point": "Values at or above this become white. Lowering it removes light paper shading but can erase pale strokes. Start at 255 and lower gradually; check the lightest text.",
    "sharpen": "Unsharp Mask emphasizes edges before binarization. Start off; enable only for soft scans. Excessive sharpening creates halos and specks.",
    "sharpen_radius": "Width of the sharpening neighborhood in base pixels. Larger values affect broader edges and create wider halos. Start at 1 pixel.",
    "sharpen_percent": "Strength of edge enhancement. Higher values sharpen more but amplify noise. Start at 100%; reduce if outlines or specks appear.",
    "regions.enabled": "Detect gray/color illustrations before text thresholding. Detected areas become separate image elements; text outside them uses 1-bit CCITT compression. Enable for diagrams or shaded panels; use Red boxes to inspect detection.",
    "regions.profile": "Text first protects fewer regions for smaller files; Image first protects more detail. Balanced is a starting point. Fine-tune the detection threshold after checking Red boxes.",
    "regions.threshold": "Evidence required to protect an illustration. Higher values produce fewer boxes and smaller files; lower values protect more gray content. Lower it if pictures disappear; raise it if plain text is boxed.",
    "regions.mode": "Keep preserves source colors/tones before the chosen compression. Gray8 only removes color. Gray2/Gray4 use 4/16 gray levels; Color2/Color4/Color8 use 4/16/256 palette colors. Start with Keep; try Gray4 for compact readable diagrams.",
    "regions.codec": "JPEG trades detail for size; Flate is lossless and often suits flat graphics. Low-bit-depth modes always use Flate. Text outside protected crops always uses lossless CCITT Group 4.",
    "regions.quality": "JPEG quality for protected crops only; CCITT text is unaffected. Lower values save space but may damage small text inside diagrams. Start at 30 and increase if labels become unclear.",
    "regions.dither": "Simulate intermediate tones in 2/4-bit images. None gives clean flat areas; Ordered is predictable; Error diffusion keeps gradients but can increase size and grain. Start with None for diagrams.",
    "regions.contrast": "Contrast of protected crops; 1 leaves it unchanged. Increase to strengthen faded images, but highlights/shadows may lose detail. Start at 1 and test small increases.",
    "regions.whiten": "Turn near-white pixels in automatically protected illustrations and uncertain shaded panels into white before contrast and quantization. Colored text has its own whitening controls. Imported regions retain their explicit settings. The selected codec is retained: JPEG may reintroduce near-white values; Flate keeps cleaned pixels exactly white.",
    "regions.white_point": "A source pixel becomes white when all three RGB channels reach this value, before grayscale conversion or contrast. Start at 235; lower values remove more background but may erase pale details inside illustrations. 255 leaves the source unchanged.",
    "regions.color_text_mode": "Automatic detection can recognize small colored strokes as text-like, without OCR. Follow uses the ordinary crop settings. Color4/Color8 instead use 16/256 indexed colors, separate contrast and lossless Flate without dithering. Small monochrome icons may also qualify. Imported regions keep their explicit settings; lettering inside a larger illustration follows that illustration.",
    "regions.color_text_contrast": "Contrast applied only to automatically detected text-like colored crops when Color4/Color8 is selected above. Start at 1.5 to strengthen pale lettering and simplify its background. Use 1 for no enhancement; higher values can clip colors and thin strokes.",
    "regions.color_text_whiten": "Turn near-white pixels in detected colored text crops into pure white before contrast and quantization. Works with Follow, Color4 and Color8. These crops use Flate and reserve pure white in their palette so compression cannot gray the cleaned pixels. Ordinary illustrations are unaffected.",
    "regions.color_text_white_point": "A source pixel becomes white only when all three RGB channels reach this value. Start at 235; lower values remove more pale background but can erase faint colored strokes. This is separate from the black/white points used for binary text.",
    "regions.denoise": "Remove small isolated black components after binarization, regardless of illustration protection. Start off; enable for dirty scans and inspect punctuation and thin strokes.",
    "regions.denoise_area": "Maximum black-component area eligible for removal, normalized to 240 DPI. Higher values remove larger specks but may erase punctuation. Start with the default and increase cautiously.",
    "regions.denoise_distance": "Required separation from other ink, scaled with DPI. Larger distances are more conservative and preserve dots near characters. Reduce only if isolated noise remains.",
    "regions.clean_background": "Detect shaded text panels and handle dark-on-light versus light-on-dark lettering locally. Uses Sauvola automatically. Enable when gray boxes produce black patches; inspect white lettering carefully.",
    "vectors": "Change non-white vector paint to black for e-ink; white stays white. Text, OCR, links and annotations are retained. Start off for colored charts where colors carry meaning.",
}

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
        self.labels: dict[str, QtWidgets.QLabel] = {}
        self._keys: dict[QtCore.QObject, str] = {}
        self._forms: dict[str, QtWidgets.QFormLayout] = {}
        values = self.config.values()
        bodies: dict[str, QtWidgets.QVBoxLayout] = {}
        for name in ("Text", "Images", "Cleanup"):
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            body = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(body)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(5)
            bodies[name] = layout
            scroll.setWidget(body)
            self.addTab(scroll, name)
        # ── create editors from the same field table ──
        for spec in FIELDS:
            if spec.key in GROUP_STARTS:
                layout = bodies[spec.tab]
                if layout.count():
                    line = QtWidgets.QFrame()
                    line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
                    layout.addWidget(line)
                group = QtWidgets.QGroupBox(GROUP_STARTS[spec.key])
                form = QtWidgets.QFormLayout(group)
                form.setContentsMargins(7, 8, 7, 7)
                form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
                form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
                layout.addWidget(group)
                self._forms[spec.tab] = form
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
            editor.setToolTip(TIPS[spec.key])
            label = QtWidgets.QLabel(spec.label)
            label.setToolTip(TIPS[spec.key])
            self.labels[spec.key] = label
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
                form.addRow(label, row)
            else:
                form.addRow(label, editor)
        hint = QtWidgets.QLabel("Text backgrounds always use lossless CCITT Group 4.\nLow-depth crops use lossless Flate.")
        hint.setWordWrap(True)
        self._forms["Images"].addRow(hint)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c43b32;")
        self._forms["Cleanup"].addRow(self.error)
        for layout in bodies.values():
            layout.addStretch()
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
            "regions.color_text_mode": image.enabled,
            "regions.color_text_contrast": image.enabled and image.color_text_mode is not regions._ColorTextMode.FOLLOW,
            "regions.color_text_whiten": image.enabled,
            "regions.color_text_white_point": image.enabled and image.color_text_whiten,
            "regions.mode": active, "regions.contrast": active,
            "regions.whiten": image.enabled or image.clean_background,
            "regions.white_point": (image.enabled or image.clean_background) and image.whiten,
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
