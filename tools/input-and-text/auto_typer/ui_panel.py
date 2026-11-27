# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'panel.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QGridLayout, QLabel,
    QPlainTextEdit, QPushButton, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget)

class Ui_TypingPanel(object):
    def setupUi(self, TypingPanel):
        if not TypingPanel.objectName():
            TypingPanel.setObjectName(u"TypingPanel")
        TypingPanel.resize(480, 230)
        self.main_layout = QVBoxLayout(TypingPanel)
        self.main_layout.setObjectName(u"main_layout")
        self.preview = QPlainTextEdit(TypingPanel)
        self.preview.setObjectName(u"preview")
        self.preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview.setReadOnly(True)

        self.main_layout.addWidget(self.preview)

        self.controls_layout = QGridLayout()
        self.controls_layout.setObjectName(u"controls_layout")
        self.paste = QPushButton(TypingPanel)
        self.paste.setObjectName(u"paste")
        self.paste.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.controls_layout.addWidget(self.paste, 0, 0, 1, 1)

        self.edit = QPushButton(TypingPanel)
        self.edit.setObjectName(u"edit")
        self.edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.controls_layout.addWidget(self.edit, 0, 1, 1, 1)

        self.button_spacing = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.controls_layout.addItem(self.button_spacing, 0, 2, 1, 1)

        self.start = QPushButton(TypingPanel)
        self.start.setObjectName(u"start")
        font = QFont()
        font.setBold(True)
        self.start.setFont(font)
        self.start.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.controls_layout.addWidget(self.start, 0, 3, 1, 1)

        self.stop = QPushButton(TypingPanel)
        self.stop.setObjectName(u"stop")
        self.stop.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stop.setEnabled(False)

        self.controls_layout.addWidget(self.stop, 0, 4, 1, 1)

        self.status = QLabel(TypingPanel)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)

        self.controls_layout.addWidget(self.status, 1, 0, 1, 4)

        self.ascii_only = QCheckBox(TypingPanel)
        self.ascii_only.setObjectName(u"ascii_only")
        self.ascii_only.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.controls_layout.addWidget(self.ascii_only, 1, 4, 1, 1)

        self.controls_layout.setColumnStretch(2, 1)

        self.main_layout.addLayout(self.controls_layout)

        self.ime_notice = QLabel(TypingPanel)
        self.ime_notice.setObjectName(u"ime_notice")
        self.ime_notice.setFont(font)

        self.main_layout.addWidget(self.ime_notice)


        self.retranslateUi(TypingPanel)

        QMetaObject.connectSlotsByName(TypingPanel)
    # setupUi

    def retranslateUi(self, TypingPanel):
        TypingPanel.setWindowTitle(QCoreApplication.translate("TypingPanel", u"Auto Typer", None))
        self.preview.setPlaceholderText(QCoreApplication.translate("TypingPanel", u"Paste from the clipboard or click Edit to enter text.", None))
        self.paste.setText(QCoreApplication.translate("TypingPanel", u"Paste from Clipboard", None))
        self.edit.setText(QCoreApplication.translate("TypingPanel", u"Edit", None))
        self.start.setText(QCoreApplication.translate("TypingPanel", u"Start Typing", None))
        self.stop.setText(QCoreApplication.translate("TypingPanel", u"Stop", None))
        self.ascii_only.setText(QCoreApplication.translate("TypingPanel", u"ASCII Only", None))
        self.ime_notice.setText(QCoreApplication.translate("TypingPanel", u"Please make sure that your IDE is in English mode | \u8bf7\u786e\u4fdd\u8f93\u5165\u6cd5\u4e3a\u82f1\u6587\u6a21\u5f0f ", None))
    # retranslateUi

