"""Extensible settings tabs; numeric edits commit on focus loss or mouse release."""

from typing import cast
from PySide6 import QtCore, QtWidgets
from utils.qt_styles import set_text_style

from ..common.protocol import Json
from . import regions
from .project import Config
from .ui_settings import Ui_SettingsPanel


CHOICES = {
    "dpi_policy": (("cap", "Use native image DPI"), ("target", "Render at target DPI")),
    "mode": (("fixed", "Fixed threshold"), ("sauvola", "Sauvola")),
    "regions.profile": (("text-first", "Text first"), ("balanced", "Balanced"), ("image-first", "Image first")),
    "regions.mode": (("keep", "Keep original colors / grayscale"), ("gray8", "Gray8 - remove color"), ("gray2", "Gray2 - 4 levels"), ("gray4", "Gray4 - 16 levels"), ("color2", "Color2 - 4 colors"), ("color4", "Color4 - 16 colors"), ("color8", "Color8 - 256 colors")),
    "regions.codec": (("jpeg", "JPEG"), ("flate", "Lossless Flate")),
    "regions.dither": (("none", "None"), ("ordered", "Ordered"), ("diffusion", "Error diffusion")),
    "regions.color_text_mode": (("follow", "Follow illustration settings"), ("color4", "Color4 - 16 colors"), ("color8", "Color8 - 256 colors")),
}

NUMBER_RANGES = {
    "dpi": (36, 1200, 1),
    "upscale": (1, 4, 1),
    "threshold": (1, 255, 1),
    "window": (3, 501, 2),
    "k": (0.01, 1, 0.01),
    "black_point": (0, 254, 1),
    "white_point": (1, 255, 1),
    "sharpen_radius": (0.1, 10, 0.1),
    "sharpen_percent": (1, 500, 1),
    "regions.threshold": (0.1, 2, 0.05),
    "regions.quality": (1, 95, 1),
    "regions.contrast": (1, 4, 0.1),
    "regions.white_point": (1, 255, 1),
    "regions.color_text_contrast": (1, 4, 0.1),
    "regions.color_text_white_point": (1, 255, 1),
    "regions.denoise_area": (0.1, 100, 0.5),
    "regions.denoise_distance": (1, 100, 1),
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


class SettingsPanel(QtWidgets.QTabWidget, Ui_SettingsPanel):
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
        self.setupUi(self)
        self.editors: dict[str, Editor] = {
            "dpi": self.dpi_editor,
            "dpi_policy": self.dpi_policy_editor,
            "upscale": self.upscale_editor,
            "mode": self.mode_editor,
            "threshold": self.threshold_editor,
            "window": self.window_editor,
            "k": self.k_editor,
            "levels": self.levels_editor,
            "black_point": self.black_point_editor,
            "white_point": self.white_point_editor,
            "sharpen": self.sharpen_editor,
            "sharpen_radius": self.sharpen_radius_editor,
            "sharpen_percent": self.sharpen_percent_editor,
            "regions.enabled": self.regions_enabled_editor,
            "regions.profile": self.regions_profile_editor,
            "regions.threshold": self.regions_threshold_editor,
            "regions.mode": self.regions_mode_editor,
            "regions.codec": self.regions_codec_editor,
            "regions.quality": self.regions_quality_editor,
            "regions.dither": self.regions_dither_editor,
            "regions.contrast": self.regions_contrast_editor,
            "regions.whiten": self.regions_whiten_editor,
            "regions.white_point": self.regions_white_point_editor,
            "regions.color_text_mode": self.regions_color_text_mode_editor,
            "regions.color_text_contrast": self.regions_color_text_contrast_editor,
            "regions.color_text_whiten": self.regions_color_text_whiten_editor,
            "regions.color_text_white_point": self.regions_color_text_white_point_editor,
            "regions.denoise": self.regions_denoise_editor,
            "regions.denoise_area": self.regions_denoise_area_editor,
            "regions.denoise_distance": self.regions_denoise_distance_editor,
            "regions.clean_background": self.regions_clean_background_editor,
            "vectors": self.vectors_editor,
        }
        self.labels = {
            "dpi": self.dpi_label,
            "dpi_policy": self.dpi_policy_label,
            "upscale": self.upscale_label,
            "mode": self.mode_label,
            "threshold": self.threshold_label,
            "window": self.window_label,
            "k": self.k_label,
            "black_point": self.black_point_label,
            "white_point": self.white_point_label,
            "sharpen_radius": self.sharpen_radius_label,
            "sharpen_percent": self.sharpen_percent_label,
            "regions.profile": self.regions_profile_label,
            "regions.threshold": self.regions_threshold_label,
            "regions.mode": self.regions_mode_label,
            "regions.codec": self.regions_codec_label,
            "regions.quality": self.regions_quality_label,
            "regions.dither": self.regions_dither_label,
            "regions.contrast": self.regions_contrast_label,
            "regions.white_point": self.regions_white_point_label,
            "regions.color_text_mode": self.regions_color_text_mode_label,
            "regions.color_text_contrast": self.regions_color_text_contrast_label,
            "regions.color_text_white_point": self.regions_color_text_white_point_label,
            "regions.denoise_area": self.regions_denoise_area_label,
            "regions.denoise_distance": self.regions_denoise_distance_label,
        }
        self.sliders = {
            "threshold": self.threshold_slider,
            "regions.quality": self.regions_quality_slider,
            "regions.white_point": self.regions_white_point_slider,
            "regions.color_text_white_point": self.regions_color_text_white_point_slider,
        }
        self._keys: dict[QtCore.QObject, str] = {}
        for key, editor in self.editors.items():
            editor.setToolTip(TIPS[key])
            if key in self.labels:
                self.labels[key].setToolTip(TIPS[key])
            if isinstance(editor, QtWidgets.QComboBox):
                for value, label in CHOICES[key]:
                    editor.addItem(label, value)
                # The scroll area measured the empty Designer combo. Refresh Qt's
                # cached minimum size so long choices wrap their form rows correctly.
                QtCore.QCoreApplication.sendEvent(editor, QtCore.QEvent(QtCore.QEvent.Type.StyleChange))
                editor.activated.connect(lambda _, key=key: self._commit(key))
            elif isinstance(editor, QtWidgets.QCheckBox):
                editor.toggled.connect(lambda _, key=key: self._commit(key))
            else:
                low, high, step = NUMBER_RANGES[key]
                if isinstance(editor, QtWidgets.QSpinBox):
                    editor.setRange(int(low), int(high))
                    editor.setSingleStep(int(step))
                else:
                    editor.setDecimals(2)
                    editor.setRange(low, high)
                    editor.setSingleStep(step)
                editor.setKeyboardTracking(False)
                editor.lineEdit().textEdited.connect(self._editing_started)
                editor.editingFinished.connect(lambda key=key: self._commit(key))
                editor.installEventFilter(self)
                self._keys[editor] = key
        for key, slider in self.sliders.items():
            spin = cast(QtWidgets.QSpinBox, self.editors[key])
            slider.setRange(spin.minimum(), spin.maximum())
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            slider.sliderReleased.connect(lambda key=key: self._commit(key))
            slider.sliderPressed.connect(self._editing_started)
            slider.installEventFilter(self)
            self._keys[slider] = key
        set_text_style(self.error, "red")
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
