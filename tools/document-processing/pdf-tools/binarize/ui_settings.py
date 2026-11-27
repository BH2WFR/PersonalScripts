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
    QGroupBox, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QSlider, QSpacerItem, QTabWidget,
    QVBoxLayout, QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox)

class Ui_SettingsPanel(object):
    def setupUi(self, SettingsPanel):
        if not SettingsPanel.objectName():
            SettingsPanel.setObjectName(u"SettingsPanel")
        SettingsPanel.resize(384, 609)
        self.text_scroll = QScrollArea()
        self.text_scroll.setObjectName(u"text_scroll")
        self.text_scroll.setWidgetResizable(True)
        self.text_page = QWidget()
        self.text_page.setObjectName(u"text_page")
        self.text_page.setGeometry(QRect(0, 0, 376, 578))
        self.text_layout = QVBoxLayout(self.text_page)
        self.text_layout.setSpacing(5)
        self.text_layout.setObjectName(u"text_layout")
        self.text_layout.setContentsMargins(4, 4, 4, 4)
        self.dpi_group = QGroupBox(self.text_page)
        self.dpi_group.setObjectName(u"dpi_group")
        self.dpi_form = QFormLayout(self.dpi_group)
        self.dpi_form.setObjectName(u"dpi_form")
        self.dpi_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.dpi_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.dpi_form.setContentsMargins(7, 8, 7, 7)
        self.dpi_label = QLabel(self.dpi_group)
        self.dpi_label.setObjectName(u"dpi_label")

        self.dpi_form.setWidget(0, QFormLayout.LabelRole, self.dpi_label)

        self.dpi_editor = NoWheelSpinBox(self.dpi_group)
        self.dpi_editor.setObjectName(u"dpi_editor")

        self.dpi_form.setWidget(0, QFormLayout.FieldRole, self.dpi_editor)

        self.dpi_policy_label = QLabel(self.dpi_group)
        self.dpi_policy_label.setObjectName(u"dpi_policy_label")

        self.dpi_form.setWidget(1, QFormLayout.LabelRole, self.dpi_policy_label)

        self.dpi_policy_editor = NoWheelComboBox(self.dpi_group)
        self.dpi_policy_editor.setObjectName(u"dpi_policy_editor")

        self.dpi_form.setWidget(1, QFormLayout.FieldRole, self.dpi_policy_editor)

        self.upscale_label = QLabel(self.dpi_group)
        self.upscale_label.setObjectName(u"upscale_label")

        self.dpi_form.setWidget(2, QFormLayout.LabelRole, self.upscale_label)

        self.upscale_editor = NoWheelSpinBox(self.dpi_group)
        self.upscale_editor.setObjectName(u"upscale_editor")

        self.dpi_form.setWidget(2, QFormLayout.FieldRole, self.upscale_editor)


        self.text_layout.addWidget(self.dpi_group)

        self.mode_line = QFrame(self.text_page)
        self.mode_line.setObjectName(u"mode_line")
        self.mode_line.setFrameShape(QFrame.Shape.HLine)

        self.text_layout.addWidget(self.mode_line)

        self.mode_group = QGroupBox(self.text_page)
        self.mode_group.setObjectName(u"mode_group")
        self.mode_form = QFormLayout(self.mode_group)
        self.mode_form.setObjectName(u"mode_form")
        self.mode_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.mode_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.mode_form.setContentsMargins(7, 8, 7, 7)
        self.mode_label = QLabel(self.mode_group)
        self.mode_label.setObjectName(u"mode_label")

        self.mode_form.setWidget(0, QFormLayout.LabelRole, self.mode_label)

        self.mode_editor = NoWheelComboBox(self.mode_group)
        self.mode_editor.setObjectName(u"mode_editor")

        self.mode_form.setWidget(0, QFormLayout.FieldRole, self.mode_editor)

        self.threshold_label = QLabel(self.mode_group)
        self.threshold_label.setObjectName(u"threshold_label")

        self.mode_form.setWidget(1, QFormLayout.LabelRole, self.threshold_label)

        self.threshold_row = QWidget(self.mode_group)
        self.threshold_row.setObjectName(u"threshold_row")
        self.threshold_layout = QHBoxLayout(self.threshold_row)
        self.threshold_layout.setObjectName(u"threshold_layout")
        self.threshold_layout.setContentsMargins(0, 0, 0, 0)
        self.threshold_slider = QSlider(self.threshold_row)
        self.threshold_slider.setObjectName(u"threshold_slider")
        self.threshold_slider.setOrientation(Qt.Orientation.Horizontal)

        self.threshold_layout.addWidget(self.threshold_slider)

        self.threshold_editor = NoWheelSpinBox(self.threshold_row)
        self.threshold_editor.setObjectName(u"threshold_editor")

        self.threshold_layout.addWidget(self.threshold_editor)

        self.threshold_layout.setStretch(0, 1)

        self.mode_form.setWidget(1, QFormLayout.FieldRole, self.threshold_row)

        self.window_label = QLabel(self.mode_group)
        self.window_label.setObjectName(u"window_label")

        self.mode_form.setWidget(2, QFormLayout.LabelRole, self.window_label)

        self.window_editor = NoWheelSpinBox(self.mode_group)
        self.window_editor.setObjectName(u"window_editor")

        self.mode_form.setWidget(2, QFormLayout.FieldRole, self.window_editor)

        self.k_label = QLabel(self.mode_group)
        self.k_label.setObjectName(u"k_label")

        self.mode_form.setWidget(3, QFormLayout.LabelRole, self.k_label)

        self.k_editor = NoWheelDoubleSpinBox(self.mode_group)
        self.k_editor.setObjectName(u"k_editor")

        self.mode_form.setWidget(3, QFormLayout.FieldRole, self.k_editor)


        self.text_layout.addWidget(self.mode_group)

        self.levels_line = QFrame(self.text_page)
        self.levels_line.setObjectName(u"levels_line")
        self.levels_line.setFrameShape(QFrame.Shape.HLine)

        self.text_layout.addWidget(self.levels_line)

        self.levels_group = QGroupBox(self.text_page)
        self.levels_group.setObjectName(u"levels_group")
        self.levels_form = QFormLayout(self.levels_group)
        self.levels_form.setObjectName(u"levels_form")
        self.levels_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.levels_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.levels_form.setContentsMargins(7, 8, 7, 7)
        self.levels_editor = QCheckBox(self.levels_group)
        self.levels_editor.setObjectName(u"levels_editor")

        self.levels_form.setWidget(0, QFormLayout.SpanningRole, self.levels_editor)

        self.black_point_label = QLabel(self.levels_group)
        self.black_point_label.setObjectName(u"black_point_label")

        self.levels_form.setWidget(1, QFormLayout.LabelRole, self.black_point_label)

        self.black_point_editor = NoWheelSpinBox(self.levels_group)
        self.black_point_editor.setObjectName(u"black_point_editor")

        self.levels_form.setWidget(1, QFormLayout.FieldRole, self.black_point_editor)

        self.white_point_label = QLabel(self.levels_group)
        self.white_point_label.setObjectName(u"white_point_label")

        self.levels_form.setWidget(2, QFormLayout.LabelRole, self.white_point_label)

        self.white_point_editor = NoWheelSpinBox(self.levels_group)
        self.white_point_editor.setObjectName(u"white_point_editor")

        self.levels_form.setWidget(2, QFormLayout.FieldRole, self.white_point_editor)


        self.text_layout.addWidget(self.levels_group)

        self.sharpen_line = QFrame(self.text_page)
        self.sharpen_line.setObjectName(u"sharpen_line")
        self.sharpen_line.setFrameShape(QFrame.Shape.HLine)

        self.text_layout.addWidget(self.sharpen_line)

        self.sharpen_group = QGroupBox(self.text_page)
        self.sharpen_group.setObjectName(u"sharpen_group")
        self.sharpen_form = QFormLayout(self.sharpen_group)
        self.sharpen_form.setObjectName(u"sharpen_form")
        self.sharpen_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.sharpen_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.sharpen_form.setContentsMargins(7, 8, 7, 7)
        self.sharpen_editor = QCheckBox(self.sharpen_group)
        self.sharpen_editor.setObjectName(u"sharpen_editor")

        self.sharpen_form.setWidget(0, QFormLayout.SpanningRole, self.sharpen_editor)

        self.sharpen_radius_label = QLabel(self.sharpen_group)
        self.sharpen_radius_label.setObjectName(u"sharpen_radius_label")

        self.sharpen_form.setWidget(1, QFormLayout.LabelRole, self.sharpen_radius_label)

        self.sharpen_radius_editor = NoWheelDoubleSpinBox(self.sharpen_group)
        self.sharpen_radius_editor.setObjectName(u"sharpen_radius_editor")

        self.sharpen_form.setWidget(1, QFormLayout.FieldRole, self.sharpen_radius_editor)

        self.sharpen_percent_label = QLabel(self.sharpen_group)
        self.sharpen_percent_label.setObjectName(u"sharpen_percent_label")

        self.sharpen_form.setWidget(2, QFormLayout.LabelRole, self.sharpen_percent_label)

        self.sharpen_percent_editor = NoWheelSpinBox(self.sharpen_group)
        self.sharpen_percent_editor.setObjectName(u"sharpen_percent_editor")

        self.sharpen_form.setWidget(2, QFormLayout.FieldRole, self.sharpen_percent_editor)


        self.text_layout.addWidget(self.sharpen_group)

        self.text_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.text_layout.addItem(self.text_stretch)

        self.text_scroll.setWidget(self.text_page)
        SettingsPanel.addTab(self.text_scroll, "")
        self.images_scroll = QScrollArea()
        self.images_scroll.setObjectName(u"images_scroll")
        self.images_scroll.setWidgetResizable(True)
        self.images_page = QWidget()
        self.images_page.setObjectName(u"images_page")
        self.images_page.setGeometry(QRect(0, -121, 359, 699))
        self.images_layout = QVBoxLayout(self.images_page)
        self.images_layout.setSpacing(5)
        self.images_layout.setObjectName(u"images_layout")
        self.images_layout.setContentsMargins(4, 4, 4, 4)
        self.regions_enabled_group = QGroupBox(self.images_page)
        self.regions_enabled_group.setObjectName(u"regions_enabled_group")
        self.regions_enabled_form = QFormLayout(self.regions_enabled_group)
        self.regions_enabled_form.setObjectName(u"regions_enabled_form")
        self.regions_enabled_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.regions_enabled_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.regions_enabled_form.setContentsMargins(7, 8, 7, 7)
        self.regions_enabled_editor = QCheckBox(self.regions_enabled_group)
        self.regions_enabled_editor.setObjectName(u"regions_enabled_editor")

        self.regions_enabled_form.setWidget(0, QFormLayout.SpanningRole, self.regions_enabled_editor)

        self.regions_profile_label = QLabel(self.regions_enabled_group)
        self.regions_profile_label.setObjectName(u"regions_profile_label")

        self.regions_enabled_form.setWidget(1, QFormLayout.LabelRole, self.regions_profile_label)

        self.regions_profile_editor = NoWheelComboBox(self.regions_enabled_group)
        self.regions_profile_editor.setObjectName(u"regions_profile_editor")

        self.regions_enabled_form.setWidget(1, QFormLayout.FieldRole, self.regions_profile_editor)

        self.regions_threshold_label = QLabel(self.regions_enabled_group)
        self.regions_threshold_label.setObjectName(u"regions_threshold_label")

        self.regions_enabled_form.setWidget(2, QFormLayout.LabelRole, self.regions_threshold_label)

        self.regions_threshold_editor = NoWheelDoubleSpinBox(self.regions_enabled_group)
        self.regions_threshold_editor.setObjectName(u"regions_threshold_editor")

        self.regions_enabled_form.setWidget(2, QFormLayout.FieldRole, self.regions_threshold_editor)


        self.images_layout.addWidget(self.regions_enabled_group)

        self.regions_mode_line = QFrame(self.images_page)
        self.regions_mode_line.setObjectName(u"regions_mode_line")
        self.regions_mode_line.setFrameShape(QFrame.Shape.HLine)

        self.images_layout.addWidget(self.regions_mode_line)

        self.regions_mode_group = QGroupBox(self.images_page)
        self.regions_mode_group.setObjectName(u"regions_mode_group")
        self.regions_mode_form = QFormLayout(self.regions_mode_group)
        self.regions_mode_form.setObjectName(u"regions_mode_form")
        self.regions_mode_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.regions_mode_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.regions_mode_form.setContentsMargins(7, 8, 7, 7)
        self.regions_mode_label = QLabel(self.regions_mode_group)
        self.regions_mode_label.setObjectName(u"regions_mode_label")

        self.regions_mode_form.setWidget(0, QFormLayout.LabelRole, self.regions_mode_label)

        self.regions_mode_editor = NoWheelComboBox(self.regions_mode_group)
        self.regions_mode_editor.setObjectName(u"regions_mode_editor")

        self.regions_mode_form.setWidget(0, QFormLayout.FieldRole, self.regions_mode_editor)


        self.images_layout.addWidget(self.regions_mode_group)

        self.regions_codec_line = QFrame(self.images_page)
        self.regions_codec_line.setObjectName(u"regions_codec_line")
        self.regions_codec_line.setFrameShape(QFrame.Shape.HLine)

        self.images_layout.addWidget(self.regions_codec_line)

        self.regions_codec_group = QGroupBox(self.images_page)
        self.regions_codec_group.setObjectName(u"regions_codec_group")
        self.regions_codec_form = QFormLayout(self.regions_codec_group)
        self.regions_codec_form.setObjectName(u"regions_codec_form")
        self.regions_codec_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.regions_codec_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.regions_codec_form.setContentsMargins(7, 8, 7, 7)
        self.regions_codec_label = QLabel(self.regions_codec_group)
        self.regions_codec_label.setObjectName(u"regions_codec_label")

        self.regions_codec_form.setWidget(0, QFormLayout.LabelRole, self.regions_codec_label)

        self.regions_codec_editor = NoWheelComboBox(self.regions_codec_group)
        self.regions_codec_editor.setObjectName(u"regions_codec_editor")

        self.regions_codec_form.setWidget(0, QFormLayout.FieldRole, self.regions_codec_editor)

        self.regions_quality_label = QLabel(self.regions_codec_group)
        self.regions_quality_label.setObjectName(u"regions_quality_label")

        self.regions_codec_form.setWidget(1, QFormLayout.LabelRole, self.regions_quality_label)

        self.regions_quality_row = QWidget(self.regions_codec_group)
        self.regions_quality_row.setObjectName(u"regions_quality_row")
        self.regions_quality_layout = QHBoxLayout(self.regions_quality_row)
        self.regions_quality_layout.setObjectName(u"regions_quality_layout")
        self.regions_quality_layout.setContentsMargins(0, 0, 0, 0)
        self.regions_quality_slider = QSlider(self.regions_quality_row)
        self.regions_quality_slider.setObjectName(u"regions_quality_slider")
        self.regions_quality_slider.setOrientation(Qt.Orientation.Horizontal)

        self.regions_quality_layout.addWidget(self.regions_quality_slider)

        self.regions_quality_editor = NoWheelSpinBox(self.regions_quality_row)
        self.regions_quality_editor.setObjectName(u"regions_quality_editor")

        self.regions_quality_layout.addWidget(self.regions_quality_editor)

        self.regions_quality_layout.setStretch(0, 1)

        self.regions_codec_form.setWidget(1, QFormLayout.FieldRole, self.regions_quality_row)


        self.images_layout.addWidget(self.regions_codec_group)

        self.regions_dither_line = QFrame(self.images_page)
        self.regions_dither_line.setObjectName(u"regions_dither_line")
        self.regions_dither_line.setFrameShape(QFrame.Shape.HLine)

        self.images_layout.addWidget(self.regions_dither_line)

        self.regions_dither_group = QGroupBox(self.images_page)
        self.regions_dither_group.setObjectName(u"regions_dither_group")
        self.regions_dither_form = QFormLayout(self.regions_dither_group)
        self.regions_dither_form.setObjectName(u"regions_dither_form")
        self.regions_dither_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.regions_dither_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.regions_dither_form.setContentsMargins(7, 8, 7, 7)
        self.regions_dither_label = QLabel(self.regions_dither_group)
        self.regions_dither_label.setObjectName(u"regions_dither_label")

        self.regions_dither_form.setWidget(0, QFormLayout.LabelRole, self.regions_dither_label)

        self.regions_dither_editor = NoWheelComboBox(self.regions_dither_group)
        self.regions_dither_editor.setObjectName(u"regions_dither_editor")

        self.regions_dither_form.setWidget(0, QFormLayout.FieldRole, self.regions_dither_editor)

        self.regions_contrast_label = QLabel(self.regions_dither_group)
        self.regions_contrast_label.setObjectName(u"regions_contrast_label")

        self.regions_dither_form.setWidget(1, QFormLayout.LabelRole, self.regions_contrast_label)

        self.regions_contrast_editor = NoWheelDoubleSpinBox(self.regions_dither_group)
        self.regions_contrast_editor.setObjectName(u"regions_contrast_editor")

        self.regions_dither_form.setWidget(1, QFormLayout.FieldRole, self.regions_contrast_editor)


        self.images_layout.addWidget(self.regions_dither_group)

        self.regions_whiten_line = QFrame(self.images_page)
        self.regions_whiten_line.setObjectName(u"regions_whiten_line")
        self.regions_whiten_line.setFrameShape(QFrame.Shape.HLine)

        self.images_layout.addWidget(self.regions_whiten_line)

        self.regions_whiten_group = QGroupBox(self.images_page)
        self.regions_whiten_group.setObjectName(u"regions_whiten_group")
        self.regions_whiten_form = QFormLayout(self.regions_whiten_group)
        self.regions_whiten_form.setObjectName(u"regions_whiten_form")
        self.regions_whiten_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.regions_whiten_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.regions_whiten_form.setContentsMargins(7, 8, 7, 7)
        self.regions_whiten_editor = QCheckBox(self.regions_whiten_group)
        self.regions_whiten_editor.setObjectName(u"regions_whiten_editor")

        self.regions_whiten_form.setWidget(0, QFormLayout.SpanningRole, self.regions_whiten_editor)

        self.regions_white_point_label = QLabel(self.regions_whiten_group)
        self.regions_white_point_label.setObjectName(u"regions_white_point_label")

        self.regions_whiten_form.setWidget(1, QFormLayout.LabelRole, self.regions_white_point_label)

        self.regions_white_point_row = QWidget(self.regions_whiten_group)
        self.regions_white_point_row.setObjectName(u"regions_white_point_row")
        self.regions_white_point_layout = QHBoxLayout(self.regions_white_point_row)
        self.regions_white_point_layout.setObjectName(u"regions_white_point_layout")
        self.regions_white_point_layout.setContentsMargins(0, 0, 0, 0)
        self.regions_white_point_slider = QSlider(self.regions_white_point_row)
        self.regions_white_point_slider.setObjectName(u"regions_white_point_slider")
        self.regions_white_point_slider.setOrientation(Qt.Orientation.Horizontal)

        self.regions_white_point_layout.addWidget(self.regions_white_point_slider)

        self.regions_white_point_editor = NoWheelSpinBox(self.regions_white_point_row)
        self.regions_white_point_editor.setObjectName(u"regions_white_point_editor")

        self.regions_white_point_layout.addWidget(self.regions_white_point_editor)

        self.regions_white_point_layout.setStretch(0, 1)

        self.regions_whiten_form.setWidget(1, QFormLayout.FieldRole, self.regions_white_point_row)


        self.images_layout.addWidget(self.regions_whiten_group)

        self.regions_color_text_mode_line = QFrame(self.images_page)
        self.regions_color_text_mode_line.setObjectName(u"regions_color_text_mode_line")
        self.regions_color_text_mode_line.setFrameShape(QFrame.Shape.HLine)

        self.images_layout.addWidget(self.regions_color_text_mode_line)

        self.regions_color_text_mode_group = QGroupBox(self.images_page)
        self.regions_color_text_mode_group.setObjectName(u"regions_color_text_mode_group")
        self.regions_color_text_mode_form = QFormLayout(self.regions_color_text_mode_group)
        self.regions_color_text_mode_form.setObjectName(u"regions_color_text_mode_form")
        self.regions_color_text_mode_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.regions_color_text_mode_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.regions_color_text_mode_form.setContentsMargins(7, 8, 7, 7)
        self.regions_color_text_mode_label = QLabel(self.regions_color_text_mode_group)
        self.regions_color_text_mode_label.setObjectName(u"regions_color_text_mode_label")

        self.regions_color_text_mode_form.setWidget(0, QFormLayout.LabelRole, self.regions_color_text_mode_label)

        self.regions_color_text_mode_editor = NoWheelComboBox(self.regions_color_text_mode_group)
        self.regions_color_text_mode_editor.setObjectName(u"regions_color_text_mode_editor")

        self.regions_color_text_mode_form.setWidget(0, QFormLayout.FieldRole, self.regions_color_text_mode_editor)

        self.regions_color_text_contrast_label = QLabel(self.regions_color_text_mode_group)
        self.regions_color_text_contrast_label.setObjectName(u"regions_color_text_contrast_label")

        self.regions_color_text_mode_form.setWidget(1, QFormLayout.LabelRole, self.regions_color_text_contrast_label)

        self.regions_color_text_contrast_editor = NoWheelDoubleSpinBox(self.regions_color_text_mode_group)
        self.regions_color_text_contrast_editor.setObjectName(u"regions_color_text_contrast_editor")

        self.regions_color_text_mode_form.setWidget(1, QFormLayout.FieldRole, self.regions_color_text_contrast_editor)

        self.regions_color_text_whiten_editor = QCheckBox(self.regions_color_text_mode_group)
        self.regions_color_text_whiten_editor.setObjectName(u"regions_color_text_whiten_editor")

        self.regions_color_text_mode_form.setWidget(2, QFormLayout.SpanningRole, self.regions_color_text_whiten_editor)

        self.regions_color_text_white_point_label = QLabel(self.regions_color_text_mode_group)
        self.regions_color_text_white_point_label.setObjectName(u"regions_color_text_white_point_label")

        self.regions_color_text_mode_form.setWidget(3, QFormLayout.LabelRole, self.regions_color_text_white_point_label)

        self.regions_color_text_white_point_row = QWidget(self.regions_color_text_mode_group)
        self.regions_color_text_white_point_row.setObjectName(u"regions_color_text_white_point_row")
        self.regions_color_text_white_point_layout = QHBoxLayout(self.regions_color_text_white_point_row)
        self.regions_color_text_white_point_layout.setObjectName(u"regions_color_text_white_point_layout")
        self.regions_color_text_white_point_layout.setContentsMargins(0, 0, 0, 0)
        self.regions_color_text_white_point_slider = QSlider(self.regions_color_text_white_point_row)
        self.regions_color_text_white_point_slider.setObjectName(u"regions_color_text_white_point_slider")
        self.regions_color_text_white_point_slider.setOrientation(Qt.Orientation.Horizontal)

        self.regions_color_text_white_point_layout.addWidget(self.regions_color_text_white_point_slider)

        self.regions_color_text_white_point_editor = NoWheelSpinBox(self.regions_color_text_white_point_row)
        self.regions_color_text_white_point_editor.setObjectName(u"regions_color_text_white_point_editor")

        self.regions_color_text_white_point_layout.addWidget(self.regions_color_text_white_point_editor)

        self.regions_color_text_white_point_layout.setStretch(0, 1)

        self.regions_color_text_mode_form.setWidget(3, QFormLayout.FieldRole, self.regions_color_text_white_point_row)

        self.image_hint = QLabel(self.regions_color_text_mode_group)
        self.image_hint.setObjectName(u"image_hint")
        self.image_hint.setWordWrap(True)

        self.regions_color_text_mode_form.setWidget(4, QFormLayout.SpanningRole, self.image_hint)


        self.images_layout.addWidget(self.regions_color_text_mode_group)

        self.images_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.images_layout.addItem(self.images_stretch)

        self.images_scroll.setWidget(self.images_page)
        SettingsPanel.addTab(self.images_scroll, "")
        self.cleanup_scroll = QScrollArea()
        self.cleanup_scroll.setObjectName(u"cleanup_scroll")
        self.cleanup_scroll.setWidgetResizable(True)
        self.cleanup_page = QWidget()
        self.cleanup_page.setObjectName(u"cleanup_page")
        self.cleanup_page.setGeometry(QRect(0, 0, 376, 578))
        self.cleanup_layout = QVBoxLayout(self.cleanup_page)
        self.cleanup_layout.setSpacing(5)
        self.cleanup_layout.setObjectName(u"cleanup_layout")
        self.cleanup_layout.setContentsMargins(4, 4, 4, 4)
        self.regions_denoise_group = QGroupBox(self.cleanup_page)
        self.regions_denoise_group.setObjectName(u"regions_denoise_group")
        self.regions_denoise_form = QFormLayout(self.regions_denoise_group)
        self.regions_denoise_form.setObjectName(u"regions_denoise_form")
        self.regions_denoise_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.regions_denoise_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.regions_denoise_form.setContentsMargins(7, 8, 7, 7)
        self.regions_denoise_editor = QCheckBox(self.regions_denoise_group)
        self.regions_denoise_editor.setObjectName(u"regions_denoise_editor")

        self.regions_denoise_form.setWidget(0, QFormLayout.SpanningRole, self.regions_denoise_editor)

        self.regions_denoise_area_label = QLabel(self.regions_denoise_group)
        self.regions_denoise_area_label.setObjectName(u"regions_denoise_area_label")

        self.regions_denoise_form.setWidget(1, QFormLayout.LabelRole, self.regions_denoise_area_label)

        self.regions_denoise_area_editor = NoWheelSpinBox(self.regions_denoise_group)
        self.regions_denoise_area_editor.setObjectName(u"regions_denoise_area_editor")

        self.regions_denoise_form.setWidget(1, QFormLayout.FieldRole, self.regions_denoise_area_editor)

        self.regions_denoise_distance_label = QLabel(self.regions_denoise_group)
        self.regions_denoise_distance_label.setObjectName(u"regions_denoise_distance_label")

        self.regions_denoise_form.setWidget(2, QFormLayout.LabelRole, self.regions_denoise_distance_label)

        self.regions_denoise_distance_editor = NoWheelSpinBox(self.regions_denoise_group)
        self.regions_denoise_distance_editor.setObjectName(u"regions_denoise_distance_editor")

        self.regions_denoise_form.setWidget(2, QFormLayout.FieldRole, self.regions_denoise_distance_editor)


        self.cleanup_layout.addWidget(self.regions_denoise_group)

        self.regions_clean_background_line = QFrame(self.cleanup_page)
        self.regions_clean_background_line.setObjectName(u"regions_clean_background_line")
        self.regions_clean_background_line.setFrameShape(QFrame.Shape.HLine)

        self.cleanup_layout.addWidget(self.regions_clean_background_line)

        self.regions_clean_background_group = QGroupBox(self.cleanup_page)
        self.regions_clean_background_group.setObjectName(u"regions_clean_background_group")
        self.regions_clean_background_form = QFormLayout(self.regions_clean_background_group)
        self.regions_clean_background_form.setObjectName(u"regions_clean_background_form")
        self.regions_clean_background_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.regions_clean_background_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.regions_clean_background_form.setContentsMargins(7, 8, 7, 7)
        self.regions_clean_background_editor = QCheckBox(self.regions_clean_background_group)
        self.regions_clean_background_editor.setObjectName(u"regions_clean_background_editor")

        self.regions_clean_background_form.setWidget(0, QFormLayout.SpanningRole, self.regions_clean_background_editor)


        self.cleanup_layout.addWidget(self.regions_clean_background_group)

        self.vectors_line = QFrame(self.cleanup_page)
        self.vectors_line.setObjectName(u"vectors_line")
        self.vectors_line.setFrameShape(QFrame.Shape.HLine)

        self.cleanup_layout.addWidget(self.vectors_line)

        self.vectors_group = QGroupBox(self.cleanup_page)
        self.vectors_group.setObjectName(u"vectors_group")
        self.vectors_form = QFormLayout(self.vectors_group)
        self.vectors_form.setObjectName(u"vectors_form")
        self.vectors_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.vectors_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.vectors_form.setContentsMargins(7, 8, 7, 7)
        self.vectors_editor = QCheckBox(self.vectors_group)
        self.vectors_editor.setObjectName(u"vectors_editor")

        self.vectors_form.setWidget(0, QFormLayout.SpanningRole, self.vectors_editor)

        self.error = QLabel(self.vectors_group)
        self.error.setObjectName(u"error")
        self.error.setWordWrap(True)

        self.vectors_form.setWidget(1, QFormLayout.SpanningRole, self.error)


        self.cleanup_layout.addWidget(self.vectors_group)

        self.cleanup_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.cleanup_layout.addItem(self.cleanup_stretch)

        self.cleanup_scroll.setWidget(self.cleanup_page)
        SettingsPanel.addTab(self.cleanup_scroll, "")

        self.retranslateUi(SettingsPanel)

        SettingsPanel.setCurrentIndex(1)


        QMetaObject.connectSlotsByName(SettingsPanel)
    # setupUi

    def retranslateUi(self, SettingsPanel):
        self.dpi_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Resolution", None))
        self.dpi_label.setText(QCoreApplication.translate("SettingsPanel", u"Sampling target (DPI)", None))
        self.dpi_policy_label.setText(QCoreApplication.translate("SettingsPanel", u"Below-target image sampling", None))
        self.upscale_label.setText(QCoreApplication.translate("SettingsPanel", u"Lanczos text enlargement", None))
        self.mode_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Binarization", None))
        self.mode_label.setText(QCoreApplication.translate("SettingsPanel", u"Method", None))
        self.threshold_label.setText(QCoreApplication.translate("SettingsPanel", u"Threshold", None))
        self.window_label.setText(QCoreApplication.translate("SettingsPanel", u"Sauvola window (odd)", None))
        self.k_label.setText(QCoreApplication.translate("SettingsPanel", u"Sauvola k", None))
        self.levels_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Black / white points", None))
        self.levels_editor.setText(QCoreApplication.translate("SettingsPanel", u"Adjust black/white points", None))
        self.black_point_label.setText(QCoreApplication.translate("SettingsPanel", u"Black point", None))
        self.white_point_label.setText(QCoreApplication.translate("SettingsPanel", u"White point", None))
        self.sharpen_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Sharpening", None))
        self.sharpen_editor.setText(QCoreApplication.translate("SettingsPanel", u"Unsharp mask", None))
        self.sharpen_radius_label.setText(QCoreApplication.translate("SettingsPanel", u"Sharpen radius", None))
        self.sharpen_percent_label.setText(QCoreApplication.translate("SettingsPanel", u"Sharpen amount (%)", None))
        SettingsPanel.setTabText(SettingsPanel.indexOf(self.text_scroll), QCoreApplication.translate("SettingsPanel", u"Text", None))
        self.regions_enabled_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Region detection", None))
        self.regions_enabled_editor.setText(QCoreApplication.translate("SettingsPanel", u"Protect illustrations automatically", None))
        self.regions_profile_label.setText(QCoreApplication.translate("SettingsPanel", u"Detection preset", None))
        self.regions_threshold_label.setText(QCoreApplication.translate("SettingsPanel", u"Detection threshold", None))
        self.regions_mode_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Protected image appearance", None))
        self.regions_mode_label.setText(QCoreApplication.translate("SettingsPanel", u"Protected image mode", None))
        self.regions_codec_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Compression", None))
        self.regions_codec_label.setText(QCoreApplication.translate("SettingsPanel", u"Crop compression", None))
        self.regions_quality_label.setText(QCoreApplication.translate("SettingsPanel", u"JPEG quality", None))
        self.regions_dither_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Tone reproduction", None))
        self.regions_dither_label.setText(QCoreApplication.translate("SettingsPanel", u"Dithering", None))
        self.regions_contrast_label.setText(QCoreApplication.translate("SettingsPanel", u"Crop contrast (1 = off)", None))
        self.regions_whiten_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Image background", None))
        self.regions_whiten_editor.setText(QCoreApplication.translate("SettingsPanel", u"Whiten image crop background", None))
        self.regions_white_point_label.setText(QCoreApplication.translate("SettingsPanel", u"Image crop white point", None))
        self.regions_color_text_mode_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Colored text", None))
        self.regions_color_text_mode_label.setText(QCoreApplication.translate("SettingsPanel", u"Colored text mode", None))
        self.regions_color_text_contrast_label.setText(QCoreApplication.translate("SettingsPanel", u"Text crop contrast (1 = off)", None))
        self.regions_color_text_whiten_editor.setText(QCoreApplication.translate("SettingsPanel", u"Whiten text crop background", None))
        self.regions_color_text_white_point_label.setText(QCoreApplication.translate("SettingsPanel", u"Text crop white point", None))
        self.image_hint.setText(QCoreApplication.translate("SettingsPanel", u"Text backgrounds always use lossless CCITT Group 4.\n"
"Low-depth crops use lossless Flate.", None))
        SettingsPanel.setTabText(SettingsPanel.indexOf(self.images_scroll), QCoreApplication.translate("SettingsPanel", u"Images", None))
        self.regions_denoise_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Binary speck removal", None))
        self.regions_denoise_editor.setText(QCoreApplication.translate("SettingsPanel", u"Remove isolated binary specks", None))
        self.regions_denoise_area_label.setText(QCoreApplication.translate("SettingsPanel", u"Maximum speck area at 240 DPI", None))
        self.regions_denoise_distance_label.setText(QCoreApplication.translate("SettingsPanel", u"Distance from other ink", None))
        self.regions_clean_background_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Shaded text", None))
        self.regions_clean_background_editor.setText(QCoreApplication.translate("SettingsPanel", u"Clean shaded text (Sauvola)", None))
        self.vectors_group.setTitle(QCoreApplication.translate("SettingsPanel", u"Vector graphics", None))
        self.vectors_editor.setText(QCoreApplication.translate("SettingsPanel", u"Vector colors: non-white to black", None))
        SettingsPanel.setTabText(SettingsPanel.indexOf(self.cleanup_scroll), QCoreApplication.translate("SettingsPanel", u"Cleanup", None))
        pass
    # retranslateUi

