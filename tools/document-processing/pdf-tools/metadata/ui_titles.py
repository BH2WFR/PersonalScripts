# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'titles.ui'
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
    QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QPushButton, QSizePolicy, QSplitter, QVBoxLayout,
    QWidget)

class Ui_TitleDialog(object):
    def setupUi(self, TitleDialog):
        if not TitleDialog.objectName():
            TitleDialog.setObjectName(u"TitleDialog")
        TitleDialog.resize(680, 410)
        self.main_layout = QVBoxLayout(TitleDialog)
        self.main_layout.setObjectName(u"main_layout")
        self.split = QSplitter(TitleDialog)
        self.split.setObjectName(u"split")
        self.split.setOrientation(Qt.Horizontal)
        self.left = QWidget(self.split)
        self.left.setObjectName(u"left")
        self.left_layout = QVBoxLayout(self.left)
        self.left_layout.setObjectName(u"left_layout")
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.language_label = QLabel(self.left)
        self.language_label.setObjectName(u"language_label")

        self.left_layout.addWidget(self.language_label)

        self.languages = QListWidget(self.left)
        self.languages.setObjectName(u"languages")

        self.left_layout.addWidget(self.languages)

        self.add_language = QPushButton(self.left)
        self.add_language.setObjectName(u"add_language")

        self.left_layout.addWidget(self.add_language)

        self.split.addWidget(self.left)
        self.right = QWidget(self.split)
        self.right.setObjectName(u"right")
        self.right_layout = QVBoxLayout(self.right)
        self.right_layout.setObjectName(u"right_layout")
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self.right)
        self.label.setObjectName(u"label")

        self.right_layout.addWidget(self.label)

        self.editor = QPlainTextEdit(self.right)
        self.editor.setObjectName(u"editor")

        self.right_layout.addWidget(self.editor)

        self.clear_one = QPushButton(self.right)
        self.clear_one.setObjectName(u"clear_one")

        self.right_layout.addWidget(self.clear_one)

        self.split.addWidget(self.right)

        self.main_layout.addWidget(self.split)

        self.buttons = QDialogButtonBox(TitleDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)

        self.main_layout.addWidget(self.buttons)


        self.retranslateUi(TitleDialog)

        QMetaObject.connectSlotsByName(TitleDialog)
    # setupUi

    def retranslateUi(self, TitleDialog):
        TitleDialog.setWindowTitle(QCoreApplication.translate("TitleDialog", u"Multilingual titles", None))
        self.language_label.setText(QCoreApplication.translate("TitleDialog", u"Language", None))
        self.add_language.setText(QCoreApplication.translate("TitleDialog", u"Add language\u2026", None))
        self.label.setText(QCoreApplication.translate("TitleDialog", u"Title", None))
        self.clear_one.setText(QCoreApplication.translate("TitleDialog", u"Clear this language", None))
    # retranslateUi

