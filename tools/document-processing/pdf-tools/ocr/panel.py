"""OCR controls that commit numeric edits on focus loss or completed keyboard entry."""

from PySide6 import QtCore, QtGui, QtWidgets
from utils.qt_widgets import NoWheelComboBox, NoWheelSpinBox, NoWheelDoubleSpinBox
from .models import inventory
from .model import LANGUAGES, LANGUAGE_LABELS, Settings


class SettingsPanel(QtWidgets.QTabWidget):
    """Separate recognition settings from preview-only colors and fonts."""

    recognitionChanged = QtCore.Signal()
    appearanceChanged = QtCore.Signal()
    addPagesRequested = QtCore.Signal()
    addCurrentRequested = QtCore.Signal()
    removePagesRequested = QtCore.Signal()
    clearPagesRequested = QtCore.Signal()
    manageModelsRequested = QtCore.Signal()

    def __init__(self, settings: Settings, parent: QtWidgets.QWidget | None = None, *, images: bool = False) -> None:
        super().__init__(parent)
        self.color = QtGui.QColor("#dc2020")
        self.preview_font = QtGui.QFont()
        self.preview_font.setPixelSize(40)
        self.controls: dict[str, NoWheelSpinBox | NoWheelDoubleSpinBox] = {}
        ocr = QtWidgets.QWidget()
        ocr_layout = QtWidgets.QVBoxLayout(ocr)
        form = QtWidgets.QFormLayout()
        ocr_layout.addLayout(form)
        ocr_layout.addStretch(1)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow(QtWidgets.QLabel("Ignore pages"))
        self.ignored_list = QtWidgets.QTreeWidget()
        self.ignored_list.setHeaderLabels(["Page", "Title"])
        self.ignored_list.setRootIsDecorated(False)
        self.ignored_list.setAlternatingRowColors(True)
        self.ignored_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.ignored_list.setMinimumHeight(90)
        self.ignored_list.setMaximumHeight(150)
        self.ignored_list.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.ignored_list.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.ignored_list.setToolTip("Physical pages excluded from OCR. Their original PDF content is retained.")
        form.addRow(self.ignored_list)
        actions = QtWidgets.QGridLayout()
        self.add_pages = QtWidgets.QPushButton("Add pages")
        self.add_current = QtWidgets.QPushButton("Add current")
        self.remove_pages = QtWidgets.QPushButton("Remove")
        self.clear_pages = QtWidgets.QPushButton("Clear")
        for index, (button, signal) in enumerate(((self.add_pages, self.addPagesRequested), (self.add_current, self.addCurrentRequested),
                                                  (self.remove_pages, self.removePagesRequested), (self.clear_pages, self.clearPagesRequested))):
            button.clicked.connect(signal)
            actions.addWidget(button, index // 2, index % 2)
        form.addRow(actions)
        self.separator = QtWidgets.QFrame()
        self.separator.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        form.addRow(self.separator)
        if images:
            for row in range(form.rowCount()):
                form.setRowVisible(row, False)
        self.language_list = QtWidgets.QListWidget()
        self.language_list.setAlternatingRowColors(True)
        for language in LANGUAGES:
            item = QtWidgets.QListWidgetItem(LANGUAGE_LABELS[language], self.language_list)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, language)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked if language in settings.languages else QtCore.Qt.CheckState.Unchecked)
        self.language_list.setFixedHeight(self.language_list.sizeHintForRow(0) * min(6, len(LANGUAGES)) + 2 * self.language_list.frameWidth())
        self.language_list.setToolTip("Select only the languages needed for this document. Extension groups need a download from Manage models. Multiple models use more CPU and memory.")
        form.addRow("Languages", self.language_list)
        self.manage_models = QtWidgets.QPushButton("Manage models...")
        self.manage_models.clicked.connect(self.manageModelsRequested)
        form.addRow(self.manage_models)
        recognition_group = QtWidgets.QGroupBox("Recognition")
        recognition_form = QtWidgets.QFormLayout(recognition_group)
        recognition_form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow(recognition_group)
        for name, title, low, high, step, tip in (
            ("dpi", "Render DPI", 72, 600, 25, "OCR input resolution; originals are never resampled in the output PDF."),
            ("side", "Detector max side", 320, 4096, 128, "Detector image size in pixels. Increase for small text; higher values use more CPU and memory."),
            ("threads", "CPU threads", 1, 32, 1, "ONNX inference threads; pages are processed serially."),
            ("threshold", "Pixel threshold", .01, .99, .05, "Lower values retain more possible text pixels."),
            ("box_threshold", "Box threshold", .01, .99, .05, "Lower values retain more candidate text boxes."),
            ("unclip", "Box expansion", 1., 3., .1, "Expansion around detected text; excessively large values merge adjacent lines."),
            ("score", "Minimum text score", 0., 1., .05, "Low values retain uncertain text for highlighting anchors."),
        ):
            self._add_number(recognition_form, settings, name, title, low, high, step, tip)
        if images:
            recognition_form.setRowVisible(self.controls['dpi'], False)
        self.angle = QtWidgets.QCheckBox("Text angle classification")
        self.angle.setChecked(settings.angle)
        self.angle.setToolTip("Classify text-line orientation; page rotation and geometry are not changed.")
        recognition_form.addRow(self.angle)
        note = QtWidgets.QLabel("Existing text is retained. OCR adds invisible text only.\nRecognition and preprocessing changes clear results; anchor margins and preview appearance do not.")
        note.setWordWrap(True)
        if not images:
            form.addRow(note)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(ocr)
        self.addTab(scroll, "OCR")
        layout_tab = QtWidgets.QWidget()
        layout_settings = QtWidgets.QVBoxLayout(layout_tab)
        self.tiling_group = QtWidgets.QGroupBox("Tiled recognition")
        self.tiling_group.setCheckable(True)
        self.tiling_group.setChecked(settings.tiled)
        tiling = QtWidgets.QFormLayout(self.tiling_group)
        tiling.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        self._add_number(tiling, settings, "tile_size", "Tile side (px)", 512, 4096, 128,
            "Square crops in rendered pixels. Overlap supplies context; tiles run serially. The detector max side still applies to each crop.")
        self._add_number(tiling, settings, "tile_overlap", "Overlap (%)", 10, 50, 5,
            "Shared context between adjacent tiles. Increase if words are cut at seams; higher overlap costs more time.")
        tile_note = QtWidgets.QLabel("Useful for large pages and small text. Seam duplicates are removed; long words may need more overlap.")
        tile_note.setWordWrap(True)
        tiling.addRow(tile_note)
        layout_settings.addWidget(self.tiling_group)
        anchors_group = QtWidgets.QGroupBox("Text anchors")
        anchors = QtWidgets.QFormLayout(anchors_group)
        anchors.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        self.english = NoWheelComboBox()
        self.english.addItem("Words", False)
        self.english.addItem("Characters", True)
        self.english.setCurrentIndex(int(settings.english_characters))
        self.english.setToolTip("Word or letter coordinates for English/numeric lines. Chinese character coordinates are already enabled.")
        anchors.addRow("English positions", self.english)
        for name, title in (("margin_x", "Horizontal margin"), ("margin_y", "Vertical margin")):
            self._add_number(anchors, settings, name, title, -40., 50., 1.,
                "Percentage of the original anchor width/height on each side, along the text axes. Positive expands, negative shrinks. Updates preview/export without rerunning OCR.")
            self.controls[name].setSuffix(" %")
        layout_settings.addWidget(anchors_group)
        anchors_group.setVisible(not images)
        layout_settings.addStretch()
        layout_scroll = QtWidgets.QScrollArea()
        layout_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        layout_scroll.setWidgetResizable(True)
        layout_scroll.setWidget(layout_tab)
        self.addTab(layout_scroll, "Layout")
        preprocessing_tab = QtWidgets.QWidget()
        preprocessing = QtWidgets.QVBoxLayout(preprocessing_tab)
        color_group = QtWidgets.QGroupBox("Color and contrast")
        color_form = QtWidgets.QFormLayout(color_group)
        color_form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        self.grayscale = QtWidgets.QCheckBox("Convert input to grayscale")
        self.grayscale.setChecked(settings.grayscale)
        color_form.addRow(self.grayscale)
        self.contrast = NoWheelComboBox()
        for label, key in (("Off", "off"), ("Auto levels", "auto"), ("Local contrast (CLAHE)", "local")):
            self.contrast.addItem(label, key)
        self.contrast.setCurrentIndex(self.contrast.findData(settings.contrast))
        self.contrast.setToolTip("Auto levels stretch the 1st/99th luminance percentiles. Local contrast can help uneven gray backgrounds but may strengthen noise.")
        color_form.addRow("Contrast", self.contrast)
        self._add_number(color_form, settings, "contrast_clip", "Local contrast limit", 1., 8., .5,
            "CLAHE clip limit. Larger values strengthen local contrast and may amplify noise.")
        self.controls["contrast_clip"].setEnabled(settings.contrast == "local")
        preprocessing.addWidget(color_group)
        noise_group = QtWidgets.QGroupBox("Noise reduction")
        noise_form = QtWidgets.QFormLayout(noise_group)
        self.denoise = NoWheelComboBox()
        for label, key in (("Off", "off"), ("Median 3 × 3", "median"), ("Gentle bilateral", "bilateral")):
            self.denoise.addItem(label, key)
        self.denoise.setCurrentIndex(self.denoise.findData(settings.denoise))
        self.denoise.setToolTip("Median filtering removes specks but can erase thin strokes. Bilateral filtering smooths mild noise while retaining edges.")
        noise_form.addRow("Filter", self.denoise)
        preprocessing.addWidget(noise_group)
        preprocessing_note = QtWidgets.QLabel("Applied only to OCR input, before splitting into tiles. Original PDF images and colored overlay backgrounds remain unchanged. All preprocessing is off by default.")
        preprocessing_note.setWordWrap(True)
        preprocessing.addWidget(preprocessing_note)
        preprocessing.addStretch()
        preprocessing_scroll = QtWidgets.QScrollArea()
        preprocessing_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        preprocessing_scroll.setWidgetResizable(True)
        preprocessing_scroll.setWidget(preprocessing_tab)
        self.addTab(preprocessing_scroll, "Preprocess")
        appearance = QtWidgets.QWidget()
        display = QtWidgets.QVBoxLayout(appearance)
        self.color_button = QtWidgets.QPushButton()
        self.color_button.clicked.connect(self._color)
        self.font_button = QtWidgets.QPushButton()
        self.font_button.clicked.connect(self._font)
        display.addWidget(self.color_button)
        display.addWidget(self.font_button)
        label = QtWidgets.QLabel("These settings affect colored text in the preview only. The exported text layer is always invisible.")
        label.setWordWrap(True)
        display.addWidget(label)
        display.addStretch()
        if images:
            appearance.setParent(self)
            appearance.hide()
            preprocessing_note.setText('Preprocessing applies to all images before recognition.')
        else:
            self.addTab(appearance, "Preview")
        self.refresh_languages()
        self.language_list.itemChanged.connect(self._language_changed)
        self.angle.toggled.connect(self.recognitionChanged)
        self.tiling_group.toggled.connect(self.recognitionChanged)
        self.english.currentIndexChanged.connect(self.recognitionChanged)
        self.grayscale.toggled.connect(self.recognitionChanged)
        self.contrast.currentIndexChanged.connect(self._contrast_changed)
        self.denoise.currentIndexChanged.connect(self.recognitionChanged)
        self.update_appearance()

    def _add_number(self, form: QtWidgets.QFormLayout, settings: Settings, name: str, title: str,
                    low: int | float, high: int | float, step: int | float, tip: str) -> None:
        """Create one no-wheel number editor with deferred commit semantics."""
        control = NoWheelSpinBox() if isinstance(low, int) else NoWheelDoubleSpinBox()
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
        form.addRow(title, control)

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
        self.color_button.setStyleSheet(f"color: {self.color.name()};")
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


def overlay_text(pixmap: QtGui.QPixmap, result: object, font: QtGui.QFont,
                 color: QtGui.QColor) -> QtGui.QPixmap:
    """Draw recognized glyphs into a detached preview, fitted to normalized anchors."""
    from .model import Result

    if not isinstance(result, Result) or not result.tokens:
        return pixmap
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
            across, down = (points[1] - points[0]) / width, (points[3] - points[0]) / height
            painter.setTransform(QtGui.QTransform(across.x(), across.y(), down.x(), down.y(), points[0].x(), points[0].y()))
            painter.drawText(QtCore.QPointF(0, metrics.ascent()), token.text)
    finally:
        painter.end()
    return rendered
