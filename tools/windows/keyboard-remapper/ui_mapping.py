# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'mapping.ui'
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
    QGridLayout, QLabel, QSizePolicy, QVBoxLayout,
    QWidget)

from personal_keyboard_remap.widgets import (SourceKeyPicker, TargetKeyPicker)

class Ui_MappingDialog(object):
    def setupUi(self, MappingDialog):
        if not MappingDialog.objectName():
            MappingDialog.setObjectName(u"MappingDialog")
        MappingDialog.resize(930, 280)
        self.main_layout = QVBoxLayout(MappingDialog)
        self.main_layout.setObjectName(u"main_layout")
        self.key_grid = QGridLayout()
        self.key_grid.setObjectName(u"key_grid")
        self.source_label = QLabel(MappingDialog)
        self.source_label.setObjectName(u"source_label")

        self.key_grid.addWidget(self.source_label, 0, 0, 1, 1)

        self.target_label = QLabel(MappingDialog)
        self.target_label.setObjectName(u"target_label")

        self.key_grid.addWidget(self.target_label, 0, 1, 1, 1)

        self.source = SourceKeyPicker(MappingDialog)
        self.source.setObjectName(u"source")

        self.key_grid.addWidget(self.source, 1, 0, 1, 1)

        self.target = TargetKeyPicker(MappingDialog)
        self.target.setObjectName(u"target")

        self.key_grid.addWidget(self.target, 1, 1, 1, 1)


        self.main_layout.addLayout(self.key_grid)

        self.notice = QLabel(MappingDialog)
        self.notice.setObjectName(u"notice")
        self.notice.setWordWrap(True)

        self.main_layout.addWidget(self.notice)

        self.buttons = QDialogButtonBox(MappingDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)

        self.main_layout.addWidget(self.buttons)


        self.retranslateUi(MappingDialog)

        QMetaObject.connectSlotsByName(MappingDialog)
    # setupUi

    def retranslateUi(self, MappingDialog):
        MappingDialog.setWindowTitle(QCoreApplication.translate("MappingDialog", u"Add mapping", None))
        self.source_label.setText(QCoreApplication.translate("MappingDialog", u"FROM - original physical key", None))
        self.target_label.setText(QCoreApplication.translate("MappingDialog", u"TO - replacement key", None))
        self.notice.setText(QCoreApplication.translate("MappingDialog", u"Scan codes, not characters or shortcuts. US labels describe base positions; ISO/JIS/Korean aliases may share codes.\n"
"Unknown words are preserved but are not guaranteed to work. Capture cannot recover a key that Windows has already disabled or remapped.", None))
    # retranslateUi

