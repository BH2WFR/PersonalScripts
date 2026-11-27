# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'matrix_export_dialog.ui'
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
    QLabel, QSizePolicy, QVBoxLayout, QWidget)

class Ui_MatrixExportDialog(object):
    def setupUi(self, MatrixExportDialog):
        if not MatrixExportDialog.objectName():
            MatrixExportDialog.setObjectName(u"MatrixExportDialog")
        MatrixExportDialog.resize(570, 460)
        self.form_layout = QVBoxLayout(MatrixExportDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.source_info = QLabel(MatrixExportDialog)
        self.source_info.setObjectName(u"source_info")
        self.source_info.setWordWrap(True)

        self.form_layout.addWidget(self.source_info)

        self.status = QLabel(MatrixExportDialog)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)

        self.form_layout.addWidget(self.status)

        self.form_buttons = QDialogButtonBox(MatrixExportDialog)
        self.form_buttons.setObjectName(u"form_buttons")
        self.form_buttons.setStandardButtons(QDialogButtonBox.Close)

        self.form_layout.addWidget(self.form_buttons)


        self.retranslateUi(MatrixExportDialog)

        QMetaObject.connectSlotsByName(MatrixExportDialog)
    # setupUi

    def retranslateUi(self, MatrixExportDialog):
        MatrixExportDialog.setWindowTitle(QCoreApplication.translate("MatrixExportDialog", u"Export matrix", None))
    # retranslateUi

