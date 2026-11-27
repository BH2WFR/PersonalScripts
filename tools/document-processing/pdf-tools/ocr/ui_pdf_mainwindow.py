# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'pdf_mainwindow.ui'
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
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
    QPlainTextEdit, QPushButton, QSizePolicy, QSplitter,
    QTabWidget, QVBoxLayout, QWidget)

from ..common.navigation import NavigationPane
from ..common.page_toolbar import (PageToolbar, PreviewOptionsToolbar, PreviewPane)
from ..common.task_buttons import TaskControls
from ..common.viewer import PageViewer
from .panel import OcrSettingsTabs
from utils.qt_widgets import NoWheelComboBox

class Ui_OcrWindow(object):
    def setupUi(self, OcrWindow):
        if not OcrWindow.objectName():
            OcrWindow.setObjectName(u"OcrWindow")
        OcrWindow.resize(1420, 900)
        self.splitter = QSplitter(OcrWindow)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.left = QWidget(self.splitter)
        self.left.setObjectName(u"left")
        self.left.setMinimumSize(QSize(340, 0))
        self.left_layout = QVBoxLayout(self.left)
        self.left_layout.setObjectName(u"left_layout")
        self.file_actions = QHBoxLayout()
        self.file_actions.setObjectName(u"file_actions")
        self.open_button = QPushButton(self.left)
        self.open_button.setObjectName(u"open_button")

        self.file_actions.addWidget(self.open_button)

        self.close_button = QPushButton(self.left)
        self.close_button.setObjectName(u"close_button")

        self.file_actions.addWidget(self.close_button)


        self.left_layout.addLayout(self.file_actions)

        self.panel = OcrSettingsTabs(self.left)
        self.panel.setObjectName(u"panel")

        self.left_layout.addWidget(self.panel)

        self.scan_button = QPushButton(self.left)
        self.scan_button.setObjectName(u"scan_button")

        self.left_layout.addWidget(self.scan_button)

        self.left_layout.setStretch(1, 1)
        self.splitter.addWidget(self.left)
        self.right_column = QWidget(self.splitter)
        self.right_column.setObjectName(u"right_column")
        self.right_layout = QVBoxLayout(self.right_column)
        self.right_layout.setObjectName(u"right_layout")
        self.right_layout.setContentsMargins(3, 6, 6, 6)
        self.preview_pane = PreviewPane(self.right_column)
        self.preview_pane.setObjectName(u"preview_pane")
        self.preview_body = QWidget(self.preview_pane)
        self.preview_body.setObjectName(u"preview_body")
        self.preview_layout = QVBoxLayout(self.preview_body)
        self.preview_layout.setObjectName(u"preview_layout")
        self.preview_layout.setContentsMargins(0, 0, 0, 0)
        self.content = QSplitter(self.preview_body)
        self.content.setObjectName(u"content")
        self.content.setOrientation(Qt.Horizontal)
        self.tabs = QTabWidget(self.content)
        self.tabs.setObjectName(u"tabs")
        self.viewer = PageViewer()
        self.viewer.setObjectName(u"viewer")
        self.tabs.addTab(self.viewer, "")
        self.text_tab = QWidget()
        self.text_tab.setObjectName(u"text_tab")
        self.text_layout = QVBoxLayout(self.text_tab)
        self.text_layout.setObjectName(u"text_layout")
        self.text_scope = NoWheelComboBox(self.text_tab)
        self.text_scope.setObjectName(u"text_scope")

        self.text_layout.addWidget(self.text_scope)

        self.text = QPlainTextEdit(self.text_tab)
        self.text.setObjectName(u"text")

        self.text_layout.addWidget(self.text)

        self.tabs.addTab(self.text_tab, "")
        self.content.addWidget(self.tabs)
        self.navigation = NavigationPane(self.content)
        self.navigation.setObjectName(u"navigation")
        self.content.addWidget(self.navigation)

        self.preview_layout.addWidget(self.content)

        self.footer = QHBoxLayout()
        self.footer.setObjectName(u"footer")
        self.status = QLabel(self.preview_body)
        self.status.setObjectName(u"status")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.status.sizePolicy().hasHeightForWidth())
        self.status.setSizePolicy(sizePolicy)

        self.footer.addWidget(self.status)

        self.task_buttons = TaskControls(self.preview_body)
        self.task_buttons.setObjectName(u"task_buttons")

        self.footer.addWidget(self.task_buttons)

        self.export_button = QPushButton(self.preview_body)
        self.export_button.setObjectName(u"export_button")

        self.footer.addWidget(self.export_button)

        self.footer.setStretch(0, 1)

        self.preview_layout.addLayout(self.footer)

        self.preview_layout.setStretch(0, 1)
        self.preview_pane.setCentralWidget(self.preview_body)
        self.toolbar = PageToolbar(self.preview_pane)
        self.toolbar.setObjectName(u"toolbar")
        self.toolbar.setMovable(False)
        self.preview_pane.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)
        self.tool_toolbar = PreviewOptionsToolbar(self.preview_pane)
        self.tool_toolbar.setObjectName(u"tool_toolbar")
        self.tool_toolbar.setMovable(False)
        self.preview_pane.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.tool_toolbar)

        self.right_layout.addWidget(self.preview_pane)

        self.splitter.addWidget(self.right_column)
        OcrWindow.setCentralWidget(self.splitter)

        self.retranslateUi(OcrWindow)

        QMetaObject.connectSlotsByName(OcrWindow)
    # setupUi

    def retranslateUi(self, OcrWindow):
        OcrWindow.setWindowTitle(QCoreApplication.translate("OcrWindow", u"PDF OCR", None))
        self.open_button.setText(QCoreApplication.translate("OcrWindow", u"Open PDF", None))
        self.close_button.setText(QCoreApplication.translate("OcrWindow", u"Close", None))
        self.scan_button.setText(QCoreApplication.translate("OcrWindow", u"Try OCR on this page", None))
        self.tabs.setTabText(self.tabs.indexOf(self.viewer), QCoreApplication.translate("OcrWindow", u"Page preview", None))
        self.tabs.setTabText(self.tabs.indexOf(self.text_tab), QCoreApplication.translate("OcrWindow", u"Recognized text", None))
        self.status.setText(QCoreApplication.translate("OcrWindow", u"Open or drop a PDF. OCR runs only when requested.", None))
        self.export_button.setText(QCoreApplication.translate("OcrWindow", u"Run all / Export PDF", None))
        self.toolbar.setWindowTitle("")
        self.tool_toolbar.setWindowTitle(QCoreApplication.translate("OcrWindow", u"Preview options", None))
    # retranslateUi

