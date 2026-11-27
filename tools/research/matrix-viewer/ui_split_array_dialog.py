# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'split_array_dialog.ui'
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
    QDialogButtonBox, QLabel, QSizePolicy, QVBoxLayout,
    QWidget)

from utils.qt_widgets import NoWheelComboBox

class Ui_SplitArrayDialog(object):
    def setupUi(self, SplitArrayDialog):
        if not SplitArrayDialog.objectName():
            SplitArrayDialog.setObjectName(u"SplitArrayDialog")
        self.form_layout = QVBoxLayout(SplitArrayDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.form_label = QLabel(SplitArrayDialog)
        self.form_label.setObjectName(u"form_label")
        self.form_label.setWordWrap(True)

        self.form_layout.addWidget(self.form_label)

        self.form_choose_a_channel_axis_to_split_i_inline = QLabel(SplitArrayDialog)
        self.form_choose_a_channel_axis_to_split_i_inline.setObjectName(u"form_choose_a_channel_axis_to_split_i_inline")

        self.form_layout.addWidget(self.form_choose_a_channel_axis_to_split_i_inline)

        self.channel_axis = NoWheelComboBox(SplitArrayDialog)
        self.channel_axis.setObjectName(u"channel_axis")

        self.form_layout.addWidget(self.channel_axis)

        self.form_note = QLabel(SplitArrayDialog)
        self.form_note.setObjectName(u"form_note")
        self.form_note.setWordWrap(True)

        self.form_layout.addWidget(self.form_note)

        self.apply_matching = QCheckBox(SplitArrayDialog)
        self.apply_matching.setObjectName(u"apply_matching")

        self.form_layout.addWidget(self.apply_matching)

        self.match_description = QLabel(SplitArrayDialog)
        self.match_description.setObjectName(u"match_description")
        self.match_description.setWordWrap(True)

        self.form_layout.addWidget(self.match_description)

        self.form_buttons = QDialogButtonBox(SplitArrayDialog)
        self.form_buttons.setObjectName(u"form_buttons")

        self.form_layout.addWidget(self.form_buttons)


        self.retranslateUi(SplitArrayDialog)

        QMetaObject.connectSlotsByName(SplitArrayDialog)
    # setupUi

    def retranslateUi(self, SplitArrayDialog):
        SplitArrayDialog.setWindowTitle(QCoreApplication.translate("SplitArrayDialog", u"Open 3D array", None))
        self.form_choose_a_channel_axis_to_split_i_inline.setText(QCoreApplication.translate("SplitArrayDialog", u"Choose a channel axis to split into separate 2D matrices.", None))
        self.form_note.setText(QCoreApplication.translate("SplitArrayDialog", u"All channels on this axis will be opened. Original values and dtype are preserved. Axis and channel indices start at 0. Don't open skips this array; check the option below to also skip later matching arrays.", None))
        self.apply_matching.setText(QCoreApplication.translate("SplitArrayDialog", u"Apply to matching arrays in this import", None))
#if QT_CONFIG(tooltip)
        self.apply_matching.setToolTip(QCoreApplication.translate("SplitArrayDialog", u"Remember Split and open or Don't open for later 3D arrays with the same length on the selected axis. Other dimensions may differ. Escape/window close skips only this array. A new import resets this choice.", None))
#endif // QT_CONFIG(tooltip)
    # retranslateUi

