# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'figure_export_dialog.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QDialog,
    QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QSizePolicy, QVBoxLayout, QWidget)

from .image_preview import ImagePreview
from utils.qt_widgets import (NoWheelComboBox, NoWheelSpinBox)

class Ui_FigureExportDialog(object):
    def setupUi(self, FigureExportDialog):
        if not FigureExportDialog.objectName():
            FigureExportDialog.setObjectName(u"FigureExportDialog")
        FigureExportDialog.resize(1020, 680)
        self.form_root = QVBoxLayout(FigureExportDialog)
        self.form_root.setObjectName(u"form_root")
        self.form_body = QHBoxLayout()
        self.form_body.setObjectName(u"form_body")
        self.form_settings = QWidget(FigureExportDialog)
        self.form_settings.setObjectName(u"form_settings")
        self.form_settings.setMaximumSize(QSize(350, 16777215))
        self.form_form = QFormLayout(self.form_settings)
        self.form_form.setObjectName(u"form_form")
        self.form_view_label = QLabel(self.form_settings)
        self.form_view_label.setObjectName(u"form_view_label")

        self.form_form.setWidget(0, QFormLayout.LabelRole, self.form_view_label)

        self.view_selector = NoWheelComboBox(self.form_settings)
        self.view_selector.setObjectName(u"view_selector")

        self.form_form.setWidget(0, QFormLayout.FieldRole, self.view_selector)

        self.form_format_label = QLabel(self.form_settings)
        self.form_format_label.setObjectName(u"form_format_label")

        self.form_form.setWidget(1, QFormLayout.LabelRole, self.form_format_label)

        self.format_selector = NoWheelComboBox(self.form_settings)
        self.format_selector.setObjectName(u"format_selector")

        self.form_form.setWidget(1, QFormLayout.FieldRole, self.format_selector)

        self.form_image_width_label = QLabel(self.form_settings)
        self.form_image_width_label.setObjectName(u"form_image_width_label")

        self.form_form.setWidget(2, QFormLayout.LabelRole, self.form_image_width_label)

        self.pixel_width = NoWheelSpinBox(self.form_settings)
        self.pixel_width.setObjectName(u"pixel_width")

        self.form_form.setWidget(2, QFormLayout.FieldRole, self.pixel_width)

        self.form_image_height_label = QLabel(self.form_settings)
        self.form_image_height_label.setObjectName(u"form_image_height_label")

        self.form_form.setWidget(3, QFormLayout.LabelRole, self.form_image_height_label)

        self.pixel_height = NoWheelSpinBox(self.form_settings)
        self.pixel_height.setObjectName(u"pixel_height")

        self.form_form.setWidget(3, QFormLayout.FieldRole, self.pixel_height)

        self.lock_aspect = QCheckBox(self.form_settings)
        self.lock_aspect.setObjectName(u"lock_aspect")

        self.form_form.setWidget(4, QFormLayout.SpanningRole, self.lock_aspect)

        self.form_dpi_2_label = QLabel(self.form_settings)
        self.form_dpi_2_label.setObjectName(u"form_dpi_2_label")

        self.form_form.setWidget(5, QFormLayout.LabelRole, self.form_dpi_2_label)

        self.dpi = NoWheelSpinBox(self.form_settings)
        self.dpi.setObjectName(u"dpi")

        self.form_form.setWidget(5, QFormLayout.FieldRole, self.dpi)

        self.transparent = QCheckBox(self.form_settings)
        self.transparent.setObjectName(u"transparent")

        self.form_form.setWidget(6, QFormLayout.SpanningRole, self.transparent)

        self.form_title_2_label = QLabel(self.form_settings)
        self.form_title_2_label.setObjectName(u"form_title_2_label")

        self.form_form.setWidget(7, QFormLayout.LabelRole, self.form_title_2_label)

        self.title = QLineEdit(self.form_settings)
        self.title.setObjectName(u"title")

        self.form_form.setWidget(7, QFormLayout.FieldRole, self.title)

        self.legend = QCheckBox(self.form_settings)
        self.legend.setObjectName(u"legend")

        self.form_form.setWidget(8, QFormLayout.SpanningRole, self.legend)

        self.form_title_legend_size_label = QLabel(self.form_settings)
        self.form_title_legend_size_label.setObjectName(u"form_title_legend_size_label")

        self.form_form.setWidget(9, QFormLayout.LabelRole, self.form_title_legend_size_label)

        self.annotation_size = NoWheelSpinBox(self.form_settings)
        self.annotation_size.setObjectName(u"annotation_size")

        self.form_form.setWidget(9, QFormLayout.FieldRole, self.annotation_size)

        self.dimensions = QLabel(self.form_settings)
        self.dimensions.setObjectName(u"dimensions")
        self.dimensions.setWordWrap(True)

        self.form_form.setWidget(10, QFormLayout.SpanningRole, self.dimensions)

        self.form_note = QLabel(self.form_settings)
        self.form_note.setObjectName(u"form_note")
        self.form_note.setWordWrap(True)

        self.form_form.setWidget(11, QFormLayout.SpanningRole, self.form_note)

        self.source_note = QLabel(self.form_settings)
        self.source_note.setObjectName(u"source_note")
        self.source_note.setWordWrap(True)

        self.form_form.setWidget(12, QFormLayout.SpanningRole, self.source_note)


        self.form_body.addWidget(self.form_settings)

        self.preview = ImagePreview(FigureExportDialog)
        self.preview.setObjectName(u"preview")
        self.preview.setMinimumSize(QSize(380, 260))

        self.form_body.addWidget(self.preview)

        self.form_body.setStretch(1, 1)

        self.form_root.addLayout(self.form_body)

        self.status = QLabel(FigureExportDialog)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)

        self.form_root.addWidget(self.status)

        self.form_buttons = QDialogButtonBox(FigureExportDialog)
        self.form_buttons.setObjectName(u"form_buttons")
        self.form_buttons.setStandardButtons(QDialogButtonBox.Close)

        self.form_root.addWidget(self.form_buttons)

        self.form_root.setStretch(0, 1)
#if QT_CONFIG(shortcut)
        self.form_view_label.setBuddy(self.view_selector)
        self.form_format_label.setBuddy(self.format_selector)
        self.form_image_width_label.setBuddy(self.pixel_width)
        self.form_image_height_label.setBuddy(self.pixel_height)
        self.form_dpi_2_label.setBuddy(self.dpi)
        self.form_title_2_label.setBuddy(self.title)
        self.form_title_legend_size_label.setBuddy(self.annotation_size)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(FigureExportDialog)

        QMetaObject.connectSlotsByName(FigureExportDialog)
    # setupUi

    def retranslateUi(self, FigureExportDialog):
        FigureExportDialog.setWindowTitle(QCoreApplication.translate("FigureExportDialog", u"Export figure", None))
        self.form_view_label.setText(QCoreApplication.translate("FigureExportDialog", u"View", None))
        self.form_format_label.setText(QCoreApplication.translate("FigureExportDialog", u"Format", None))
        self.form_image_width_label.setText(QCoreApplication.translate("FigureExportDialog", u"Image width", None))
        self.form_image_height_label.setText(QCoreApplication.translate("FigureExportDialog", u"Image height", None))
        self.lock_aspect.setText(QCoreApplication.translate("FigureExportDialog", u"Lock original plot aspect ratio", None))
#if QT_CONFIG(tooltip)
        self.lock_aspect.setToolTip(QCoreApplication.translate("FigureExportDialog", u"Uncheck to set width and height independently. Both dimensions include the title and legend.", None))
#endif // QT_CONFIG(tooltip)
        self.form_dpi_2_label.setText(QCoreApplication.translate("FigureExportDialog", u"DPI", None))
        self.transparent.setText(QCoreApplication.translate("FigureExportDialog", u"Transparent background", None))
        self.form_title_2_label.setText(QCoreApplication.translate("FigureExportDialog", u"Title", None))
        self.title.setPlaceholderText(QCoreApplication.translate("FigureExportDialog", u"Optional title; leave empty to omit", None))
        self.legend.setText(QCoreApplication.translate("FigureExportDialog", u"Include channel / matrix legend", None))
        self.form_title_legend_size_label.setText(QCoreApplication.translate("FigureExportDialog", u"Title / legend size", None))
        self.form_note.setText(QCoreApplication.translate("FigureExportDialog", u"Unlock the aspect ratio to set width and height independently. Dimensions include the title and wrapped legend. Plots reflow to fit; a locked X:Y unit ratio is preserved by expanding the visible range. 3D renders into the new viewport. DPI sets print size.\n"
"\n"
"Axes and lines scale with the plot. Viewer controls and hover cursors are excluded. Image pixels and curves use full source detail; 2D points and 3D use the current grid sampling. Background and text colors follow the viewer theme. SVG keeps Qt plot text/curves as vectors and embeds 2D image pixels.", None))
        self.status.setText(QCoreApplication.translate("FigureExportDialog", u"Preparing preview\u2026", None))
    # retranslateUi

