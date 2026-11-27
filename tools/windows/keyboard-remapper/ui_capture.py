# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'capture.ui'
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
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget)

class Ui_CaptureDialog(object):
    def setupUi(self, CaptureDialog):
        if not CaptureDialog.objectName():
            CaptureDialog.setObjectName(u"CaptureDialog")
        CaptureDialog.setMinimumSize(QSize(590, 0))
        self.main_layout = QVBoxLayout(CaptureDialog)
        self.main_layout.setObjectName(u"main_layout")
        self.explanation = QLabel(CaptureDialog)
        self.explanation.setObjectName(u"explanation")
        self.explanation.setWordWrap(True)

        self.main_layout.addWidget(self.explanation)

        self.status = QLabel(CaptureDialog)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)
        self.status.setMinimumSize(QSize(0, 80))

        self.main_layout.addWidget(self.status)

        self.button_row = QHBoxLayout()
        self.button_row.setObjectName(u"button_row")
        self.retry_button = QPushButton(CaptureDialog)
        self.retry_button.setObjectName(u"retry_button")
        self.retry_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.retry_button.setAutoDefault(False)

        self.button_row.addWidget(self.retry_button)

        self.use_button = QPushButton(CaptureDialog)
        self.use_button.setObjectName(u"use_button")
        self.use_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.use_button.setAutoDefault(False)

        self.button_row.addWidget(self.use_button)

        self.cancel_button = QPushButton(CaptureDialog)
        self.cancel_button.setObjectName(u"cancel_button")
        self.cancel_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cancel_button.setAutoDefault(False)

        self.button_row.addWidget(self.cancel_button)


        self.main_layout.addLayout(self.button_row)


        self.retranslateUi(CaptureDialog)

        QMetaObject.connectSlotsByName(CaptureDialog)
    # setupUi

    def retranslateUi(self, CaptureDialog):
        CaptureDialog.setWindowTitle(QCoreApplication.translate("CaptureDialog", u"Capture a key", None))
        self.explanation.setText(QCoreApplication.translate("CaptureDialog", u"Keep this window focused and press ONE key, including a modifier.\n"
"Capture stops after one key or 20 seconds. Use the mouse to confirm/cancel.\n"
"\n"
"Already remapped keys may report their destination. Select the original\n"
"key from the list instead. Disabled keys, Fn and system-reserved keys\n"
"may not reach this window. System shortcuts are not blocked.", None))
        self.retry_button.setText(QCoreApplication.translate("CaptureDialog", u"Listen again", None))
        self.use_button.setText(QCoreApplication.translate("CaptureDialog", u"Use this key", None))
        self.cancel_button.setText(QCoreApplication.translate("CaptureDialog", u"Cancel", None))
    # retranslateUi

