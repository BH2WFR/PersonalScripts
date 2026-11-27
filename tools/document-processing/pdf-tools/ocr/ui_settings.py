# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'settings.ui'
##
## Created by: Qt User Interface Compiler version 6.8.3
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHeaderView, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QSizePolicy, QSpacerItem, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox)

class Ui_SettingsPanel(object):
    def setupUi(self, SettingsPanel):
        if not SettingsPanel.objectName():
            SettingsPanel.setObjectName(u"SettingsPanel")
        self.ocr_scroll = QScrollArea()
        self.ocr_scroll.setObjectName(u"ocr_scroll")
        self.ocr_scroll.setWidgetResizable(True)
        self.ocr_scroll.setFrameShape(QFrame.NoFrame)
        self.ocr_page = QWidget()
        self.ocr_page.setObjectName(u"ocr_page")
        self.ocr_layout = QVBoxLayout(self.ocr_page)
        self.ocr_layout.setObjectName(u"ocr_layout")
        self.ocr_form = QFormLayout()
        self.ocr_form.setObjectName(u"ocr_form")
        self.ocr_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.ocr_form.setFormAlignment(Qt.AlignTop)
        self.ocr_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.ignore_heading = QLabel(self.ocr_page)
        self.ignore_heading.setObjectName(u"ignore_heading")

        self.ocr_form.setWidget(0, QFormLayout.SpanningRole, self.ignore_heading)

        self.ignored_list = QTreeWidget(self.ocr_page)
        self.ignored_list.setObjectName(u"ignored_list")
        self.ignored_list.setMinimumSize(QSize(0, 90))
        self.ignored_list.setMaximumSize(QSize(16777215, 150))
        self.ignored_list.setRootIsDecorated(False)
        self.ignored_list.setAlternatingRowColors(True)

        self.ocr_form.setWidget(1, QFormLayout.SpanningRole, self.ignored_list)

        self.page_actions = QGridLayout()
        self.page_actions.setObjectName(u"page_actions")
        self.add_pages = QPushButton(self.ocr_page)
        self.add_pages.setObjectName(u"add_pages")

        self.page_actions.addWidget(self.add_pages, 0, 0, 1, 1)

        self.add_current = QPushButton(self.ocr_page)
        self.add_current.setObjectName(u"add_current")

        self.page_actions.addWidget(self.add_current, 0, 1, 1, 1)

        self.remove_pages = QPushButton(self.ocr_page)
        self.remove_pages.setObjectName(u"remove_pages")

        self.page_actions.addWidget(self.remove_pages, 1, 0, 1, 1)

        self.clear_pages = QPushButton(self.ocr_page)
        self.clear_pages.setObjectName(u"clear_pages")

        self.page_actions.addWidget(self.clear_pages, 1, 1, 1, 1)


        self.ocr_form.setLayout(2, QFormLayout.SpanningRole, self.page_actions)

        self.separator = QFrame(self.ocr_page)
        self.separator.setObjectName(u"separator")
        self.separator.setFrameShape(QFrame.HLine)
        self.separator.setFrameShadow(QFrame.Sunken)

        self.ocr_form.setWidget(3, QFormLayout.SpanningRole, self.separator)

        self.language_list_label = QLabel(self.ocr_page)
        self.language_list_label.setObjectName(u"language_list_label")

        self.ocr_form.setWidget(4, QFormLayout.LabelRole, self.language_list_label)

        self.language_list = QListWidget(self.ocr_page)
        self.language_list.setObjectName(u"language_list")

        self.ocr_form.setWidget(4, QFormLayout.FieldRole, self.language_list)

        self.manage_models = QPushButton(self.ocr_page)
        self.manage_models.setObjectName(u"manage_models")

        self.ocr_form.setWidget(5, QFormLayout.SpanningRole, self.manage_models)

        self.recognition_group = QGroupBox(self.ocr_page)
        self.recognition_group.setObjectName(u"recognition_group")
        self.recognition_form = QFormLayout(self.recognition_group)
        self.recognition_form.setObjectName(u"recognition_form")
        self.recognition_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.dpi_label = QLabel(self.recognition_group)
        self.dpi_label.setObjectName(u"dpi_label")

        self.recognition_form.setWidget(0, QFormLayout.LabelRole, self.dpi_label)

        self.dpi = NoWheelSpinBox(self.recognition_group)
        self.dpi.setObjectName(u"dpi")

        self.recognition_form.setWidget(0, QFormLayout.FieldRole, self.dpi)

        self.side_label = QLabel(self.recognition_group)
        self.side_label.setObjectName(u"side_label")

        self.recognition_form.setWidget(1, QFormLayout.LabelRole, self.side_label)

        self.side = NoWheelSpinBox(self.recognition_group)
        self.side.setObjectName(u"side")

        self.recognition_form.setWidget(1, QFormLayout.FieldRole, self.side)

        self.threads_label = QLabel(self.recognition_group)
        self.threads_label.setObjectName(u"threads_label")

        self.recognition_form.setWidget(2, QFormLayout.LabelRole, self.threads_label)

        self.threads = NoWheelSpinBox(self.recognition_group)
        self.threads.setObjectName(u"threads")

        self.recognition_form.setWidget(2, QFormLayout.FieldRole, self.threads)

        self.threshold_label = QLabel(self.recognition_group)
        self.threshold_label.setObjectName(u"threshold_label")

        self.recognition_form.setWidget(3, QFormLayout.LabelRole, self.threshold_label)

        self.threshold = NoWheelDoubleSpinBox(self.recognition_group)
        self.threshold.setObjectName(u"threshold")

        self.recognition_form.setWidget(3, QFormLayout.FieldRole, self.threshold)

        self.box_threshold_label = QLabel(self.recognition_group)
        self.box_threshold_label.setObjectName(u"box_threshold_label")

        self.recognition_form.setWidget(4, QFormLayout.LabelRole, self.box_threshold_label)

        self.box_threshold = NoWheelDoubleSpinBox(self.recognition_group)
        self.box_threshold.setObjectName(u"box_threshold")

        self.recognition_form.setWidget(4, QFormLayout.FieldRole, self.box_threshold)

        self.unclip_label = QLabel(self.recognition_group)
        self.unclip_label.setObjectName(u"unclip_label")

        self.recognition_form.setWidget(5, QFormLayout.LabelRole, self.unclip_label)

        self.unclip = NoWheelDoubleSpinBox(self.recognition_group)
        self.unclip.setObjectName(u"unclip")

        self.recognition_form.setWidget(5, QFormLayout.FieldRole, self.unclip)

        self.score_label = QLabel(self.recognition_group)
        self.score_label.setObjectName(u"score_label")

        self.recognition_form.setWidget(6, QFormLayout.LabelRole, self.score_label)

        self.score = NoWheelDoubleSpinBox(self.recognition_group)
        self.score.setObjectName(u"score")

        self.recognition_form.setWidget(6, QFormLayout.FieldRole, self.score)

        self.angle = QCheckBox(self.recognition_group)
        self.angle.setObjectName(u"angle")

        self.recognition_form.setWidget(7, QFormLayout.SpanningRole, self.angle)


        self.ocr_form.setWidget(6, QFormLayout.SpanningRole, self.recognition_group)

        self.ocr_note = QLabel(self.ocr_page)
        self.ocr_note.setObjectName(u"ocr_note")
        self.ocr_note.setWordWrap(True)

        self.ocr_form.setWidget(7, QFormLayout.SpanningRole, self.ocr_note)


        self.ocr_layout.addLayout(self.ocr_form)

        self.ocr_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.ocr_layout.addItem(self.ocr_stretch)

        self.ocr_layout.setStretch(1, 1)
        self.ocr_scroll.setWidget(self.ocr_page)
        SettingsPanel.addTab(self.ocr_scroll, "")
        self.layout_scroll = QScrollArea()
        self.layout_scroll.setObjectName(u"layout_scroll")
        self.layout_scroll.setWidgetResizable(True)
        self.layout_scroll.setFrameShape(QFrame.NoFrame)
        self.layout_page = QWidget()
        self.layout_page.setObjectName(u"layout_page")
        self.layout_layout = QVBoxLayout(self.layout_page)
        self.layout_layout.setObjectName(u"layout_layout")
        self.tiling_group = QGroupBox(self.layout_page)
        self.tiling_group.setObjectName(u"tiling_group")
        self.tiling_group.setCheckable(True)
        self.tiling_form = QFormLayout(self.tiling_group)
        self.tiling_form.setObjectName(u"tiling_form")
        self.tiling_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.tile_size_label = QLabel(self.tiling_group)
        self.tile_size_label.setObjectName(u"tile_size_label")

        self.tiling_form.setWidget(0, QFormLayout.LabelRole, self.tile_size_label)

        self.tile_size = NoWheelSpinBox(self.tiling_group)
        self.tile_size.setObjectName(u"tile_size")

        self.tiling_form.setWidget(0, QFormLayout.FieldRole, self.tile_size)

        self.tile_overlap_label = QLabel(self.tiling_group)
        self.tile_overlap_label.setObjectName(u"tile_overlap_label")

        self.tiling_form.setWidget(1, QFormLayout.LabelRole, self.tile_overlap_label)

        self.tile_overlap = NoWheelSpinBox(self.tiling_group)
        self.tile_overlap.setObjectName(u"tile_overlap")

        self.tiling_form.setWidget(1, QFormLayout.FieldRole, self.tile_overlap)

        self.tile_note = QLabel(self.tiling_group)
        self.tile_note.setObjectName(u"tile_note")
        self.tile_note.setWordWrap(True)

        self.tiling_form.setWidget(2, QFormLayout.SpanningRole, self.tile_note)


        self.layout_layout.addWidget(self.tiling_group)

        self.anchors_group = QGroupBox(self.layout_page)
        self.anchors_group.setObjectName(u"anchors_group")
        self.anchors_form = QFormLayout(self.anchors_group)
        self.anchors_form.setObjectName(u"anchors_form")
        self.anchors_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.english_label = QLabel(self.anchors_group)
        self.english_label.setObjectName(u"english_label")

        self.anchors_form.setWidget(0, QFormLayout.LabelRole, self.english_label)

        self.english = NoWheelComboBox(self.anchors_group)
        self.english.setObjectName(u"english")

        self.anchors_form.setWidget(0, QFormLayout.FieldRole, self.english)

        self.margin_x_label = QLabel(self.anchors_group)
        self.margin_x_label.setObjectName(u"margin_x_label")

        self.anchors_form.setWidget(1, QFormLayout.LabelRole, self.margin_x_label)

        self.margin_x = NoWheelDoubleSpinBox(self.anchors_group)
        self.margin_x.setObjectName(u"margin_x")

        self.anchors_form.setWidget(1, QFormLayout.FieldRole, self.margin_x)

        self.margin_y_label = QLabel(self.anchors_group)
        self.margin_y_label.setObjectName(u"margin_y_label")

        self.anchors_form.setWidget(2, QFormLayout.LabelRole, self.margin_y_label)

        self.margin_y = NoWheelDoubleSpinBox(self.anchors_group)
        self.margin_y.setObjectName(u"margin_y")

        self.anchors_form.setWidget(2, QFormLayout.FieldRole, self.margin_y)


        self.layout_layout.addWidget(self.anchors_group)

        self.layout_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.layout_layout.addItem(self.layout_stretch)

        self.layout_scroll.setWidget(self.layout_page)
        SettingsPanel.addTab(self.layout_scroll, "")
        self.preprocess_scroll = QScrollArea()
        self.preprocess_scroll.setObjectName(u"preprocess_scroll")
        self.preprocess_scroll.setWidgetResizable(True)
        self.preprocess_scroll.setFrameShape(QFrame.NoFrame)
        self.preprocess_page = QWidget()
        self.preprocess_page.setObjectName(u"preprocess_page")
        self.preprocess_layout = QVBoxLayout(self.preprocess_page)
        self.preprocess_layout.setObjectName(u"preprocess_layout")
        self.color_group = QGroupBox(self.preprocess_page)
        self.color_group.setObjectName(u"color_group")
        self.color_form = QFormLayout(self.color_group)
        self.color_form.setObjectName(u"color_form")
        self.color_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.grayscale = QCheckBox(self.color_group)
        self.grayscale.setObjectName(u"grayscale")

        self.color_form.setWidget(0, QFormLayout.SpanningRole, self.grayscale)

        self.contrast_label = QLabel(self.color_group)
        self.contrast_label.setObjectName(u"contrast_label")

        self.color_form.setWidget(1, QFormLayout.LabelRole, self.contrast_label)

        self.contrast = NoWheelComboBox(self.color_group)
        self.contrast.setObjectName(u"contrast")

        self.color_form.setWidget(1, QFormLayout.FieldRole, self.contrast)

        self.contrast_clip_label = QLabel(self.color_group)
        self.contrast_clip_label.setObjectName(u"contrast_clip_label")

        self.color_form.setWidget(2, QFormLayout.LabelRole, self.contrast_clip_label)

        self.contrast_clip = NoWheelDoubleSpinBox(self.color_group)
        self.contrast_clip.setObjectName(u"contrast_clip")

        self.color_form.setWidget(2, QFormLayout.FieldRole, self.contrast_clip)


        self.preprocess_layout.addWidget(self.color_group)

        self.noise_group = QGroupBox(self.preprocess_page)
        self.noise_group.setObjectName(u"noise_group")
        self.noise_form = QFormLayout(self.noise_group)
        self.noise_form.setObjectName(u"noise_form")
        self.denoise_label = QLabel(self.noise_group)
        self.denoise_label.setObjectName(u"denoise_label")

        self.noise_form.setWidget(0, QFormLayout.LabelRole, self.denoise_label)

        self.denoise = NoWheelComboBox(self.noise_group)
        self.denoise.setObjectName(u"denoise")

        self.noise_form.setWidget(0, QFormLayout.FieldRole, self.denoise)


        self.preprocess_layout.addWidget(self.noise_group)

        self.preprocessing_note = QLabel(self.preprocess_page)
        self.preprocessing_note.setObjectName(u"preprocessing_note")
        self.preprocessing_note.setWordWrap(True)

        self.preprocess_layout.addWidget(self.preprocessing_note)

        self.preprocess_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.preprocess_layout.addItem(self.preprocess_stretch)

        self.preprocess_scroll.setWidget(self.preprocess_page)
        SettingsPanel.addTab(self.preprocess_scroll, "")
        self.appearance = QWidget()
        self.appearance.setObjectName(u"appearance")
        self.display = QVBoxLayout(self.appearance)
        self.display.setObjectName(u"display")
        self.color_button = QPushButton(self.appearance)
        self.color_button.setObjectName(u"color_button")

        self.display.addWidget(self.color_button)

        self.font_button = QPushButton(self.appearance)
        self.font_button.setObjectName(u"font_button")

        self.display.addWidget(self.font_button)

        self.preview_note = QLabel(self.appearance)
        self.preview_note.setObjectName(u"preview_note")
        self.preview_note.setWordWrap(True)

        self.display.addWidget(self.preview_note)

        self.preview_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.display.addItem(self.preview_stretch)

        SettingsPanel.addTab(self.appearance, "")
#if QT_CONFIG(shortcut)
        self.language_list_label.setBuddy(self.language_list)
        self.dpi_label.setBuddy(self.dpi)
        self.side_label.setBuddy(self.side)
        self.threads_label.setBuddy(self.threads)
        self.threshold_label.setBuddy(self.threshold)
        self.box_threshold_label.setBuddy(self.box_threshold)
        self.unclip_label.setBuddy(self.unclip)
        self.score_label.setBuddy(self.score)
        self.tile_size_label.setBuddy(self.tile_size)
        self.tile_overlap_label.setBuddy(self.tile_overlap)
        self.english_label.setBuddy(self.english)
        self.margin_x_label.setBuddy(self.margin_x)
        self.margin_y_label.setBuddy(self.margin_y)
        self.contrast_label.setBuddy(self.contrast)
        self.contrast_clip_label.setBuddy(self.contrast_clip)
        self.denoise_label.setBuddy(self.denoise)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(SettingsPanel)

        QMetaObject.connectSlotsByName(SettingsPanel)
    # setupUi

    def retranslateUi(self, SettingsPanel):
        self.ignore_heading.setText(QCoreApplication.translate("SettingsPanel", u"Ignore pages", None))
        ___qtreewidgetitem = self.ignored_list.headerItem()
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("SettingsPanel", u"Title", None));
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("SettingsPanel", u"Page", None));
        self.add_pages.setText(QCoreApplication.translate("SettingsPanel", u"Add pages", None))
        self.add_current.setText(QCoreApplication.translate("SettingsPanel", u"Add current", None))
        self.remove_pages.setText(QCoreApplication.translate("SettingsPanel", u"Remove", None))
        self.clear_pages.setText(QCoreApplication.translate("SettingsPanel", u"Clear", None))
        self.language_list_label.setText(QCoreApplication.translate("SettingsPanel", u"Languages", None))
        self.manage_models.setText(QCoreApplication.translate("SettingsPanel", u"Manage models...", None))
        self.recognition_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Recognition", None))
        self.dpi_label.setText(QCoreApplication.translate("SettingsPanel", u"Render DPI", None))
        self.side_label.setText(QCoreApplication.translate("SettingsPanel", u"Detector max side", None))
        self.threads_label.setText(QCoreApplication.translate("SettingsPanel", u"CPU threads", None))
        self.threshold_label.setText(QCoreApplication.translate("SettingsPanel", u"Pixel threshold", None))
        self.box_threshold_label.setText(QCoreApplication.translate("SettingsPanel", u"Box threshold", None))
        self.unclip_label.setText(QCoreApplication.translate("SettingsPanel", u"Box expansion", None))
        self.score_label.setText(QCoreApplication.translate("SettingsPanel", u"Minimum text score", None))
        self.angle.setText(QCoreApplication.translate("SettingsPanel", u"Text angle classification", None))
        self.ocr_note.setText(QCoreApplication.translate("SettingsPanel", u"Existing text is retained. OCR adds invisible text only.\n"
"Recognition and preprocessing changes clear results; anchor margins and preview appearance do not.", None))
        SettingsPanel.setTabText(SettingsPanel.indexOf(self.ocr_scroll), QCoreApplication.translate("SettingsPanel", u"OCR", None))
        self.tiling_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Tiled recognition", None))
        self.tile_size_label.setText(QCoreApplication.translate("SettingsPanel", u"Tile side (px)", None))
        self.tile_overlap_label.setText(QCoreApplication.translate("SettingsPanel", u"Overlap (%)", None))
        self.tile_note.setText(QCoreApplication.translate("SettingsPanel", u"Useful for large pages and small text. Seam duplicates are removed; long words may need more overlap.", None))
        self.anchors_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Text anchors", None))
        self.english_label.setText(QCoreApplication.translate("SettingsPanel", u"English positions", None))
        self.margin_x_label.setText(QCoreApplication.translate("SettingsPanel", u"Horizontal margin", None))
        self.margin_y_label.setText(QCoreApplication.translate("SettingsPanel", u"Vertical margin", None))
        SettingsPanel.setTabText(SettingsPanel.indexOf(self.layout_scroll), QCoreApplication.translate("SettingsPanel", u"Layout", None))
        self.color_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Color and contrast", None))
        self.grayscale.setText(QCoreApplication.translate("SettingsPanel", u"Convert input to grayscale", None))
        self.contrast_label.setText(QCoreApplication.translate("SettingsPanel", u"Contrast", None))
        self.contrast_clip_label.setText(QCoreApplication.translate("SettingsPanel", u"Local contrast limit", None))
        self.noise_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Noise reduction", None))
        self.denoise_label.setText(QCoreApplication.translate("SettingsPanel", u"Filter", None))
        self.preprocessing_note.setText(QCoreApplication.translate("SettingsPanel", u"Applied only to OCR input, before splitting into tiles. Original PDF images and colored overlay backgrounds remain unchanged. All preprocessing is off by default.", None))
        SettingsPanel.setTabText(SettingsPanel.indexOf(self.preprocess_scroll), QCoreApplication.translate("SettingsPanel", u"Preprocess", None))
        self.color_button.setText("")
        self.font_button.setText("")
        self.preview_note.setText(QCoreApplication.translate("SettingsPanel", u"These settings affect colored text in the preview only. The exported text layer is always invisible.", None))
        SettingsPanel.setTabText(SettingsPanel.indexOf(self.appearance), QCoreApplication.translate("SettingsPanel", u"Preview", None))
        pass
    # retranslateUi

