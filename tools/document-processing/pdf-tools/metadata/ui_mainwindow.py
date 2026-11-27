# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'mainwindow.ui'
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
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QSizePolicy, QSpacerItem, QTabWidget,
    QVBoxLayout, QWidget)

from .panels import (OutputOptions, Properties)

class Ui_MetadataWindow(object):
    def setupUi(self, MetadataWindow):
        if not MetadataWindow.objectName():
            MetadataWindow.setObjectName(u"MetadataWindow")
        MetadataWindow.resize(760, 600)
        self.main_layout = QVBoxLayout(MetadataWindow)
        self.main_layout.setObjectName(u"main_layout")
        self.open_button = QPushButton(MetadataWindow)
        self.open_button.setObjectName(u"open_button")

        self.main_layout.addWidget(self.open_button, 0, Qt.AlignLeft)

        self.info = QLabel(MetadataWindow)
        self.info.setObjectName(u"info")
        self.info.setWordWrap(True)

        self.main_layout.addWidget(self.info)

        self.tabs = QTabWidget(MetadataWindow)
        self.tabs.setObjectName(u"tabs")
        self.properties = Properties()
        self.properties.setObjectName(u"properties")
        self.tabs.addTab(self.properties, "")
        self.xml = QPlainTextEdit()
        self.xml.setObjectName(u"xml")
        self.tabs.addTab(self.xml, "")
        self.options = OutputOptions()
        self.options.setObjectName(u"options")
        self.tabs.addTab(self.options, "")

        self.main_layout.addWidget(self.tabs)

        self.status = QLabel(MetadataWindow)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)

        self.main_layout.addWidget(self.status)

        self.footer = QHBoxLayout()
        self.footer.setObjectName(u"footer")
        self.footer_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.footer.addItem(self.footer_stretch)

        self.task_slot = QHBoxLayout()
        self.task_slot.setObjectName(u"task_slot")

        self.footer.addLayout(self.task_slot)

        self.save = QPushButton(MetadataWindow)
        self.save.setObjectName(u"save")

        self.footer.addWidget(self.save)


        self.main_layout.addLayout(self.footer)


        self.retranslateUi(MetadataWindow)

        QMetaObject.connectSlotsByName(MetadataWindow)
    # setupUi

    def retranslateUi(self, MetadataWindow):
        MetadataWindow.setWindowTitle(QCoreApplication.translate("MetadataWindow", u"PDF Metadata Editor", None))
        self.open_button.setText(QCoreApplication.translate("MetadataWindow", u"Open PDF\u2026", None))
        self.info.setText(QCoreApplication.translate("MetadataWindow", u"Open a PDF to edit its document properties.", None))
        self.tabs.setTabText(self.tabs.indexOf(self.properties), QCoreApplication.translate("MetadataWindow", u"Document properties", None))
        self.tabs.setTabText(self.tabs.indexOf(self.xml), QCoreApplication.translate("MetadataWindow", u"XMP (XML)", None))
        self.tabs.setTabText(self.tabs.indexOf(self.options), QCoreApplication.translate("MetadataWindow", u"Output settings", None))
        self.save.setText(QCoreApplication.translate("MetadataWindow", u"Save as\u2026", None))
    # retranslateUi

