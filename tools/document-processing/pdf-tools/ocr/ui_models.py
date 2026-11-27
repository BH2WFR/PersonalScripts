# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'models.ui'
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
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QHeaderView,
    QLabel, QPlainTextEdit, QPushButton, QSizePolicy,
    QSpacerItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget)

from ..common.task_buttons import TaskControls

class Ui_ModelDialog(object):
    def setupUi(self, ModelDialog):
        if not ModelDialog.objectName():
            ModelDialog.setObjectName(u"ModelDialog")
        ModelDialog.resize(830, 570)
        self.main_layout = QVBoxLayout(ModelDialog)
        self.main_layout.setObjectName(u"main_layout")
        self.note = QLabel(ModelDialog)
        self.note.setObjectName(u"note")
        self.note.setWordWrap(True)

        self.main_layout.addWidget(self.note)

        self.tree = QTreeWidget(ModelDialog)
        self.tree.setObjectName(u"tree")
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)

        self.main_layout.addWidget(self.tree)

        self.details = QPlainTextEdit(ModelDialog)
        self.details.setObjectName(u"details")
        self.details.setMaximumSize(QSize(16777215, 110))

        self.main_layout.addWidget(self.details)

        self.summary = QLabel(ModelDialog)
        self.summary.setObjectName(u"summary")
        self.summary.setWordWrap(True)

        self.main_layout.addWidget(self.summary)

        self.actions = QHBoxLayout()
        self.actions.setObjectName(u"actions")
        self.download_button = QPushButton(ModelDialog)
        self.download_button.setObjectName(u"download_button")

        self.actions.addWidget(self.download_button)

        self.verify_button = QPushButton(ModelDialog)
        self.verify_button.setObjectName(u"verify_button")

        self.actions.addWidget(self.verify_button)

        self.delete_button = QPushButton(ModelDialog)
        self.delete_button.setObjectName(u"delete_button")

        self.actions.addWidget(self.delete_button)

        self.refresh_button = QPushButton(ModelDialog)
        self.refresh_button.setObjectName(u"refresh_button")

        self.actions.addWidget(self.refresh_button)

        self.folder_button = QPushButton(ModelDialog)
        self.folder_button.setObjectName(u"folder_button")

        self.actions.addWidget(self.folder_button)


        self.main_layout.addLayout(self.actions)

        self.status = QLabel(ModelDialog)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)

        self.main_layout.addWidget(self.status)

        self.footer = QHBoxLayout()
        self.footer.setObjectName(u"footer")
        self.controls = TaskControls(ModelDialog)
        self.controls.setObjectName(u"controls")

        self.footer.addWidget(self.controls)

        self.footer_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.footer.addItem(self.footer_stretch)

        self.close_button = QPushButton(ModelDialog)
        self.close_button.setObjectName(u"close_button")

        self.footer.addWidget(self.close_button)


        self.main_layout.addLayout(self.footer)

        self.main_layout.setStretch(1, 1)

        self.retranslateUi(ModelDialog)

        QMetaObject.connectSlotsByName(ModelDialog)
    # setupUi

    def retranslateUi(self, ModelDialog):
        ModelDialog.setWindowTitle(QCoreApplication.translate("ModelDialog", u"OCR models", None))
        self.note.setText(QCoreApplication.translate("ModelDialog", u"Download only the languages you need. Bundled models are read-only.\n"
"Downloads use RapidOCR's official registry and are checked with SHA-256. Select a language in OCR settings to use its model.", None))
        ___qtreewidgetitem = self.tree.headerItem()
        ___qtreewidgetitem.setText(3, QCoreApplication.translate("ModelDialog", u"Local size", None));
        ___qtreewidgetitem.setText(2, QCoreApplication.translate("ModelDialog", u"Status", None));
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("ModelDialog", u"Version", None));
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("ModelDialog", u"Model / languages", None));
        self.download_button.setText(QCoreApplication.translate("ModelDialog", u"Download / Repair", None))
        self.verify_button.setText(QCoreApplication.translate("ModelDialog", u"Verify", None))
        self.delete_button.setText(QCoreApplication.translate("ModelDialog", u"Delete", None))
        self.refresh_button.setText(QCoreApplication.translate("ModelDialog", u"Refresh", None))
        self.folder_button.setText(QCoreApplication.translate("ModelDialog", u"Open folder", None))
        self.status.setText(QCoreApplication.translate("ModelDialog", u"Reading local models...", None))
        self.close_button.setText(QCoreApplication.translate("ModelDialog", u"Close", None))
    # retranslateUi

