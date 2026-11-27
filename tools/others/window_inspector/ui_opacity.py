# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'opacity.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDialog, QDialogButtonBox,
    QSizePolicy, QVBoxLayout, QWidget)

from utils.qt_widgets import NoWheelSpinBox

class Ui_OpacityDialog(object):
    def setupUi(self, OpacityDialog):
        if not OpacityDialog.objectName():
            OpacityDialog.setObjectName(u"OpacityDialog")
        self.main_layout = QVBoxLayout(OpacityDialog)
        self.main_layout.setObjectName(u"main_layout")
        self.spin = NoWheelSpinBox(OpacityDialog)
        self.spin.setObjectName(u"spin")

        self.main_layout.addWidget(self.spin)

        self.buttons = QDialogButtonBox(OpacityDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Reset)

        self.main_layout.addWidget(self.buttons)


        self.retranslateUi(OpacityDialog)

        QMetaObject.connectSlotsByName(OpacityDialog)
    # setupUi

    def retranslateUi(self, OpacityDialog):
        OpacityDialog.setWindowTitle(QCoreApplication.translate("OpacityDialog", u"Window opacity", None))
#if QT_CONFIG(accessibility)
        self.spin.setAccessibleName(QCoreApplication.translate("OpacityDialog", u"Window opacity", None))
#endif // QT_CONFIG(accessibility)
        self.spin.setSuffix(QCoreApplication.translate("OpacityDialog", u"%", None))
    # retranslateUi

