"""OCR controls that commit numeric edits on focus loss or completed keyboard entry."""

from PySide6 import QtCore, QtGui, QtWidgets
from utils.qt_styles import color_swatch_icon
from utils.qt_widgets import NoWheelSpinBox, NoWheelDoubleSpinBox, with_cjk_fallbacks
from .models import inventory
from .model import LANGUAGES, LANGUAGE_LABELS, Settings
from .ui_settings import Ui_SettingsPanel


class OcrSettingsTabs(QtWidgets.QTabWidget, Ui_SettingsPanel):
    """Separate recognition settings from preview-only colors and fonts."""

    recognitionChanged = QtCore.Signal()
    appearanceChanged = QtCore.Signal()
    addPagesRequested = QtCore.Signal()
    addCurrentRequested = QtCore.Signal()
    removePagesRequested = QtCore.Signal()
    clearPagesRequested = QtCore.Signal()
    manageModelsRequested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setupUi(self)

    def configure(self, settings: Settings, *, images: bool = False) -> None:
        """Initialize the form once with the saved settings for this OCR tool."""
        self.color = QtGui.QColor("#dc2020")
        self.preview_font = QtGui.QFont()
        self.preview_font.setPixelSize(40)
        self.controls: dict[str, NoWheelSpinBox | NoWheelDoubleSpinBox] = {}
        self.ignored_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.ignored_list.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.ignored_list.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.ignored_list.setToolTip("Physical pages excluded from OCR. Their original PDF content is retained.")
        for button, signal in ((self.add_pages, self.addPagesRequested), (self.add_current, self.addCurrentRequested),
                               (self.remove_pages, self.removePagesRequested), (self.clear_pages, self.clearPagesRequested)):
            button.clicked.connect(signal)
        if images:
            for row in range(4):
                self.ocr_form.setRowVisible(row, False)
            self.ocr_form.setRowVisible(self.ocr_note, False)
        self.language_list.setAlternatingRowColors(True)
        for language in LANGUAGES:
            item = QtWidgets.QListWidgetItem(LANGUAGE_LABELS[language], self.language_list)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, language)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked if language in settings.languages else QtCore.Qt.CheckState.Unchecked)
        self.language_list.setFixedHeight(self.language_list.sizeHintForRow(0) * min(6, len(LANGUAGES)) + 2 * self.language_list.frameWidth())
        self.language_list.setToolTip("Select only the languages needed for this document. Extension groups need a download from Manage models. Multiple models use more CPU and memory.")
        self.manage_models.clicked.connect(self.manageModelsRequested)
        for control, name, low, high, step, tip in (
            (self.dpi, "dpi", 72, 600, 25, "OCR input resolution; originals are never resampled in the output PDF."),
            (self.side, "side", 320, 4096, 128, "Detector image size in pixels. Increase for small text; higher values use more CPU and memory."),
            (self.threads, "threads", 1, 32, 1, "ONNX inference threads; pages are processed serially."),
            (self.threshold, "threshold", .01, .99, .05, "Lower values retain more possible text pixels."),
            (self.box_threshold, "box_threshold", .01, .99, .05, "Lower values retain more candidate text boxes."),
            (self.unclip, "unclip", 1., 3., .1, "Expansion around detected text; excessively large values merge adjacent lines."),
            (self.score, "score", 0., 1., .05, "Low values retain uncertain text for highlighting anchors."),
        ):
            self._configure_number(control, settings, name, low, high, step, tip)
        if images:
            self.recognition_form.setRowVisible(self.controls['dpi'], False)
        self.angle.setChecked(settings.angle)
        self.angle.setToolTip("Classify text-line orientation; page rotation and geometry are not changed.")
        self.tiling_group.setCheckable(True)
        self.tiling_group.setChecked(settings.tiled)
        self._configure_number(self.tile_size, settings, "tile_size", 512, 4096, 128,
            "Square crops in rendered pixels. Overlap supplies context; tiles run serially. The detector max side still applies to each crop.")
        self._configure_number(self.tile_overlap, settings, "tile_overlap", 10, 50, 5,
            "Shared context between adjacent tiles. Increase if words are cut at seams; higher overlap costs more time.")
        self.english.addItem("Words", False)
        self.english.addItem("Characters", True)
        self.english.setCurrentIndex(int(settings.english_characters))
        self.english.setToolTip("Word or letter coordinates for English/numeric lines. Chinese character coordinates are already enabled.")
        for name, control in (("margin_x", self.margin_x), ("margin_y", self.margin_y)):
            self._configure_number(control, settings, name, -40., 50., 1.,
                "Percentage of the original anchor width/height on each side, along the text axes. Positive expands, negative shrinks. Updates preview/export without rerunning OCR.")
            self.controls[name].setSuffix(" %")
        self.anchors_group.setVisible(not images)
        self.grayscale.setChecked(settings.grayscale)
        for label, key in (("Off", "off"), ("Auto levels", "auto"), ("Local contrast (CLAHE)", "local")):
            self.contrast.addItem(label, key)
        self.contrast.setCurrentIndex(self.contrast.findData(settings.contrast))
        self.contrast.setToolTip("Auto levels stretch the 1st/99th luminance percentiles. Local contrast can help uneven gray backgrounds but may strengthen noise.")
        self._configure_number(self.contrast_clip, settings, "contrast_clip", 1., 8., .5,
            "CLAHE clip limit. Larger values strengthen local contrast and may amplify noise.")
        self.controls["contrast_clip"].setEnabled(settings.contrast == "local")
        for label, key in (("Off", "off"), ("Median 3 × 3", "median"), ("Gentle bilateral", "bilateral")):
            self.denoise.addItem(label, key)
        self.denoise.setCurrentIndex(self.denoise.findData(settings.denoise))
        self.denoise.setToolTip("Median filtering removes specks but can erase thin strokes. Bilateral filtering smooths mild noise while retaining edges.")
        self.color_button.clicked.connect(self._color)
        self.font_button.clicked.connect(self._font)
        if images:
            self.removeTab(self.indexOf(self.appearance))
            self.preprocessing_note.setText("Preprocessing applies to all images before recognition.")

        self.refresh_languages()
        self.language_list.itemChanged.connect(self._language_changed)
        self.angle.toggled.connect(self.recognitionChanged)
        self.tiling_group.toggled.connect(self.recognitionChanged)
        self.english.currentIndexChanged.connect(self.recognitionChanged)
        self.grayscale.toggled.connect(self.recognitionChanged)
        self.contrast.currentIndexChanged.connect(self._contrast_changed)
        self.denoise.currentIndexChanged.connect(self.recognitionChanged)
        self.update_appearance()

    def _configure_number(self, control: NoWheelSpinBox | NoWheelDoubleSpinBox, settings: Settings, name: str,
                          low: int | float, high: int | float, step: int | float, tip: str) -> None:
        """Configure one no-wheel number editor with deferred commit semantics."""
        if isinstance(control, NoWheelSpinBox):
            control.setRange(int(low), int(high))
            control.setSingleStep(int(step))
        else:
            control.setRange(float(low), float(high))
            control.setSingleStep(float(step))
        control.setValue(getattr(settings, name))
        control.setKeyboardTracking(False)
        control.setToolTip(tip)
        control.editingFinished.connect(self.recognitionChanged)
        self.controls[name] = control

    def _contrast_changed(self) -> None:
        self.controls["contrast_clip"].setEnabled(self.contrast.currentData() == "local")
        self.recognitionChanged.emit()

    def refresh_languages(self) -> None:
        """Disable missing extensions and recover a usable selection after deletion."""
        previous = self.selected_languages()
        installed = {row["key"] for row in inventory() if row["size"]}
        with QtCore.QSignalBlocker(self.language_list):
            for index, key in enumerate(LANGUAGES):
                item = self.language_list.item(index)
                enabled = key in ("chinese", "english", "japanese") or key in installed
                flags = item.flags()
                flag = QtCore.Qt.ItemFlag.ItemIsEnabled
                item.setFlags(flags | flag if enabled else flags & ~flag)
                suffix = "" if enabled else " (install separately)"
                item.setText(LANGUAGE_LABELS[key] + suffix)
                item.setToolTip("" if enabled else "Install this language separately in Manage models.")
                if not enabled:
                    item.setCheckState(QtCore.Qt.CheckState.Unchecked)
            if not self.selected_languages():
                for index in (0, 1):
                    self.language_list.item(index).setCheckState(QtCore.Qt.CheckState.Checked)
        if previous != self.selected_languages():
            self.recognitionChanged.emit()

    def selected_languages(self) -> tuple[str, ...]:
        """Return checked languages in stable display order."""
        return tuple(self.language_list.item(index).data(QtCore.Qt.ItemDataRole.UserRole)
                     for index in range(self.language_list.count())
                     if self.language_list.item(index).checkState() == QtCore.Qt.CheckState.Checked)

    def _language_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        """Keep at least one language selected so recognition always has a model."""
        if not self.selected_languages():
            with QtCore.QSignalBlocker(self.language_list):
                item.setCheckState(QtCore.Qt.CheckState.Checked)
            return
        self.recognitionChanged.emit()

    def settings(self) -> Settings:
        """Read the committed form values."""
        return Settings(languages=self.selected_languages(), angle=self.angle.isChecked(),
            dpi=int(self.controls["dpi"].value()), side=int(self.controls["side"].value()),
            threads=int(self.controls["threads"].value()), threshold=float(self.controls["threshold"].value()),
            box_threshold=float(self.controls["box_threshold"].value()), unclip=float(self.controls["unclip"].value()),
            score=float(self.controls["score"].value()), tiled=self.tiling_group.isChecked(),
            tile_size=int(self.controls["tile_size"].value()), tile_overlap=int(self.controls["tile_overlap"].value()),
            english_characters=bool(self.english.currentData()), margin_x=float(self.controls["margin_x"].value()),
            margin_y=float(self.controls["margin_y"].value()), grayscale=self.grayscale.isChecked(),
            contrast=str(self.contrast.currentData()), contrast_clip=float(self.controls["contrast_clip"].value()),
            denoise=str(self.denoise.currentData()))

    def update_appearance(self) -> None:
        """Reflect current preview choices after loading preferences or editing."""
        self.color_button.setText(f"Text color: {self.color.name()}")
        self.color_button.setIcon(color_swatch_icon(self.color))
        self.font_button.setText(f"Text font: {self.preview_font.family()}")

    def _color(self) -> None:
        color = QtWidgets.QColorDialog.getColor(self.color, self, "Preview text color")
        if color.isValid():
            self.color = color
            self.update_appearance()
            self.appearanceChanged.emit()

    def _font(self) -> None:
        accepted, font = QtWidgets.QFontDialog.getFont(self.preview_font, self, "Preview text font")
        if accepted:
            font.setPixelSize(40)
            self.preview_font = font
            self.update_appearance()
            self.appearanceChanged.emit()


class SettingsPanel(OcrSettingsTabs):
    """Construct a standalone panel with an existing recognition profile."""

    def __init__(self, settings: Settings, parent: QtWidgets.QWidget | None = None, *, images: bool = False) -> None:
        super().__init__(parent)
        self.configure(settings, images=images)


def overlay_text(pixmap: QtGui.QPixmap, result: object, font: QtGui.QFont,
                 color: QtGui.QColor) -> QtGui.QPixmap:
    """Draw recognized glyphs into a detached preview, fitted to normalized anchors."""
    from .model import Result

    if not isinstance(result, Result) or not result.tokens:
        return pixmap
    font = with_cjk_fallbacks(font)
    rendered = pixmap.copy()
    painter = QtGui.QPainter(rendered)
    try:
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        painter.setFont(font)
        painter.setPen(color)
        metrics = QtGui.QFontMetricsF(font)
        for token in result.tokens:
            if len(token.quad) != 4 or not token.text.strip():
                continue
            points = [QtCore.QPointF(x * pixmap.width(), y * pixmap.height()) for x, y in token.quad]
            width = metrics.horizontalAdvance(token.text)
            height = metrics.height()
            if width <= 0 or height <= 0:
                continue
            across, down = points[1] - points[0], points[3] - points[0]
            painter.setTransform(QtGui.QTransform(across.x() / width, across.y() / width,
                                                  down.x() / height, down.y() / height,
                                                  points[0].x(), points[0].y()))
            painter.drawText(QtCore.QPointF(0, metrics.ascent()), token.text)
    finally:
        painter.end()
    return rendered
