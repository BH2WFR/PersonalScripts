# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'key_picker.ui'
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
from PySide6.QtWidgets import (QApplication, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget)

from utils.qt_widgets import NoWheelComboBox

class Ui_KeyPicker(object):
    def setupUi(self, KeyPicker):
        if not KeyPicker.objectName():
            KeyPicker.setObjectName(u"KeyPicker")
        self.picker_layout = QVBoxLayout(KeyPicker)
        self.picker_layout.setObjectName(u"picker_layout")
        self.picker_layout.setContentsMargins(0, 0, 0, 0)
        self.combo = NoWheelComboBox(KeyPicker)
        self.combo.setObjectName(u"combo")
        self.combo.setMinimumSize(QSize(420, 0))
        self.combo.setEditable(True)

        self.picker_layout.addWidget(self.combo)

        self.capture_button = QPushButton(KeyPicker)
        self.capture_button.setObjectName(u"capture_button")

        self.picker_layout.addWidget(self.capture_button)


        self.retranslateUi(KeyPicker)

        QMetaObject.connectSlotsByName(KeyPicker)
    # setupUi

    def retranslateUi(self, KeyPicker):
        self.capture_button.setText(QCoreApplication.translate("KeyPicker", u"Capture key...", None))
        pass
    # retranslateUi

