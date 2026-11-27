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
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QVBoxLayout, QWidget)

from ..common.navigation import NavigationPane
from ..common.page_toolbar import (PageToolbar, PreviewOptionsToolbar, PreviewPane)
from .panel import SplitPanel
from .viewer import SplitViewer

class Ui_SplitWindow(object):
    def setupUi(self, SplitWindow):
        if not SplitWindow.objectName():
            SplitWindow.setObjectName(u"SplitWindow")
        SplitWindow.resize(1420, 900)
        self.splitter = QSplitter(SplitWindow)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.left = QWidget(self.splitter)
        self.left.setObjectName(u"left")
        self.left.setMinimumSize(QSize(340, 0))
        self.left_layout = QVBoxLayout(self.left)
        self.left_layout.setObjectName(u"left_layout")
        self.left_layout.setContentsMargins(6, 6, 3, 6)
        self.file_actions = QHBoxLayout()
        self.file_actions.setObjectName(u"file_actions")
        self.open_button = QPushButton(self.left)
        self.open_button.setObjectName(u"open_button")

        self.file_actions.addWidget(self.open_button)

        self.close_button = QPushButton(self.left)
        self.close_button.setObjectName(u"close_button")

        self.file_actions.addWidget(self.close_button)


        self.left_layout.addLayout(self.file_actions)

        self.page_info = QLabel(self.left)
        self.page_info.setObjectName(u"page_info")
        self.page_info.setWordWrap(True)

        self.left_layout.addWidget(self.page_info)

        self.settings_scroll = QScrollArea(self.left)
        self.settings_scroll.setObjectName(u"settings_scroll")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.NoFrame)
        self.panel = SplitPanel()
        self.panel.setObjectName(u"panel")
        self.settings_scroll.setWidget(self.panel)

        self.left_layout.addWidget(self.settings_scroll)

        self.left_layout.setStretch(2, 1)
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
        self.viewer = SplitViewer(self.content)
        self.viewer.setObjectName(u"viewer")
        self.content.addWidget(self.viewer)
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

        self.task_slot = QHBoxLayout()
        self.task_slot.setObjectName(u"task_slot")

        self.footer.addLayout(self.task_slot)

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
        SplitWindow.setCentralWidget(self.splitter)

        self.retranslateUi(SplitWindow)

        QMetaObject.connectSlotsByName(SplitWindow)
    # setupUi

    def retranslateUi(self, SplitWindow):
        SplitWindow.setWindowTitle(QCoreApplication.translate("SplitWindow", u"PDF Page Splitter", None))
        self.open_button.setText(QCoreApplication.translate("SplitWindow", u"Open PDF", None))
        self.close_button.setText(QCoreApplication.translate("SplitWindow", u"Close", None))
        self.page_info.setText(QCoreApplication.translate("SplitWindow", u"Page: \u2014\n"
"Size: \u2014", None))
        self.status.setText(QCoreApplication.translate("SplitWindow", u"Open or drop a PDF to begin.", None))
        self.export_button.setText(QCoreApplication.translate("SplitWindow", u"Export PDF", None))
        self.toolbar.setWindowTitle("")
        self.tool_toolbar.setWindowTitle(QCoreApplication.translate("SplitWindow", u"Preview options", None))
    # retranslateUi

