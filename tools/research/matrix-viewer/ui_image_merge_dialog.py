# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'image_merge_dialog.ui'
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
    QDialogButtonBox, QFormLayout, QGridLayout, QLabel,
    QLineEdit, QSizePolicy, QVBoxLayout, QWidget)

from .image_preview import ImagePreview
from utils.qt_widgets import NoWheelComboBox

class Ui_ImageMergeDialog(object):
    def setupUi(self, ImageMergeDialog):
        if not ImageMergeDialog.objectName():
            ImageMergeDialog.setObjectName(u"ImageMergeDialog")
        ImageMergeDialog.resize(1000, 720)
        self.form_layout = QVBoxLayout(ImageMergeDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.settings = QWidget(ImageMergeDialog)
        self.settings.setObjectName(u"settings")
        self.form_fields = QVBoxLayout(self.settings)
        self.form_fields.setObjectName(u"form_fields")
        self.form_top = QFormLayout()
        self.form_top.setObjectName(u"form_top")
        self.form_output_8_bit_per_channel_label = QLabel(self.settings)
        self.form_output_8_bit_per_channel_label.setObjectName(u"form_output_8_bit_per_channel_label")

        self.form_top.setWidget(0, QFormLayout.LabelRole, self.form_output_8_bit_per_channel_label)

        self.mode = NoWheelComboBox(self.settings)
        self.mode.setObjectName(u"mode")

        self.form_top.setWidget(0, QFormLayout.FieldRole, self.mode)

        self.form_result_name_2_label = QLabel(self.settings)
        self.form_result_name_2_label.setObjectName(u"form_result_name_2_label")

        self.form_top.setWidget(1, QFormLayout.LabelRole, self.form_result_name_2_label)

        self.result_name = QLineEdit(self.settings)
        self.result_name.setObjectName(u"result_name")

        self.form_top.setWidget(1, QFormLayout.FieldRole, self.result_name)

        self.link_ranges = QCheckBox(self.settings)
        self.link_ranges.setObjectName(u"link_ranges")

        self.form_top.setWidget(2, QFormLayout.SpanningRole, self.link_ranges)


        self.form_fields.addLayout(self.form_top)

        self.grid = QGridLayout()
        self.grid.setObjectName(u"grid")

        self.form_fields.addLayout(self.grid)


        self.form_layout.addWidget(self.settings)

        self.form_note = QLabel(ImageMergeDialog)
        self.form_note.setObjectName(u"form_note")
        self.form_note.setWordWrap(True)

        self.form_layout.addWidget(self.form_note)

        self.preview = ImagePreview(ImageMergeDialog)
        self.preview.setObjectName(u"preview")

        self.form_layout.addWidget(self.preview)

        self.status = QLabel(ImageMergeDialog)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)

        self.form_layout.addWidget(self.status)

        self.buttons = QDialogButtonBox(ImageMergeDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.Cancel)

        self.form_layout.addWidget(self.buttons)

        self.form_layout.setStretch(2, 1)
#if QT_CONFIG(shortcut)
        self.form_output_8_bit_per_channel_label.setBuddy(self.mode)
        self.form_result_name_2_label.setBuddy(self.result_name)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(ImageMergeDialog)

        QMetaObject.connectSlotsByName(ImageMergeDialog)
    # setupUi

    def retranslateUi(self, ImageMergeDialog):
        ImageMergeDialog.setWindowTitle(QCoreApplication.translate("ImageMergeDialog", u"Image merge \u2014 selected matrices / channels", None))
        self.form_output_8_bit_per_channel_label.setText(QCoreApplication.translate("ImageMergeDialog", u"Output (8-bit per channel)", None))
        self.form_result_name_2_label.setText(QCoreApplication.translate("ImageMergeDialog", u"Result name", None))
        self.result_name.setPlaceholderText(QCoreApplication.translate("ImageMergeDialog", u"Automatic: Image merge \u00b7 RGB / RGBA / Monochrome + alpha", None))
        self.link_ranges.setText(QCoreApplication.translate("ImageMergeDialog", u"Link input ranges", None))
#if QT_CONFIG(tooltip)
        self.link_ranges.setToolTip(QCoreApplication.translate("ImageMergeDialog", u"Use the first row's range mode and limits for all output channels.\n"
"Current-channel auto uses the first row's source; shared auto uses all assigned sources.\n"
"Source assignments and gains remain independent.", None))
#endif // QT_CONFIG(tooltip)
        self.form_note.setText(QCoreApplication.translate("ImageMergeDialog", u"Full-size channels \u2192 range \u2192 gain \u2192 8-bit image. Hover for details.", None))
#if QT_CONFIG(tooltip)
        self.form_note.setToolTip(QCoreApplication.translate("ImageMergeDialog", u"Crop, value bounds and overlay alignment are ignored. All shapes must match. RGB/M gains adjust brightness / white balance; A gain adjusts opacity. NaN / -Inf become 0, +Inf becomes 255. Constant auto-range channels become 0. Alpha is stored separately, without multiplying the color channels.", None))
#endif // QT_CONFIG(tooltip)
        self.status.setText(QCoreApplication.translate("ImageMergeDialog", u"Preparing selected sources\u2026", None))
    # retranslateUi

