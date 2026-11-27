# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'edit_dialog.ui'
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
    QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget)

class Ui_EditDialog(object):
    def setupUi(self, EditDialog):
        if not EditDialog.objectName():
            EditDialog.setObjectName(u"EditDialog")
        EditDialog.resize(480, 230)
        self.main_layout = QVBoxLayout(EditDialog)
        self.main_layout.setObjectName(u"main_layout")
        self.editor = QPlainTextEdit(EditDialog)
        self.editor.setObjectName(u"editor")

        self.main_layout.addWidget(self.editor)

        self.buttons = QDialogButtonBox(EditDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)

        self.main_layout.addWidget(self.buttons)


        self.retranslateUi(EditDialog)

        QMetaObject.connectSlotsByName(EditDialog)
    # setupUi

    def retranslateUi(self, EditDialog):
        EditDialog.setWindowTitle(QCoreApplication.translate("EditDialog", u"Edit text", None))
    # retranslateUi

