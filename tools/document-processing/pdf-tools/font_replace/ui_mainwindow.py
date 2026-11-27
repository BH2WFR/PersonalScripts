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
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QPushButton, QSizePolicy, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..common.navigation import NavigationPane
from ..common.page_toolbar import (PageToolbar, PreviewOptionsToolbar, PreviewPane)
from ..common.viewer import PageViewer
from .panel import RulePanel

class Ui_FontReplaceWindow(object):
    def setupUi(self, FontReplaceWindow):
        if not FontReplaceWindow.objectName():
            FontReplaceWindow.setObjectName(u"FontReplaceWindow")
        FontReplaceWindow.resize(1420, 900)
        self.splitter = QSplitter(FontReplaceWindow)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.left = QWidget(self.splitter)
        self.left.setObjectName(u"left")
        self.left.setMinimumSize(QSize(350, 0))
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

        self.rules_heading = QLabel(self.left)
        self.rules_heading.setObjectName(u"rules_heading")

        self.left_layout.addWidget(self.rules_heading)

        self.rule_list = QTreeWidget(self.left)
        self.rule_list.setObjectName(u"rule_list")
        self.rule_list.setMinimumSize(QSize(0, 100))
        self.rule_list.setMaximumSize(QSize(16777215, 260))
        self.rule_list.setRootIsDecorated(False)
        self.rule_list.setAlternatingRowColors(True)

        self.left_layout.addWidget(self.rule_list)

        self.rule_actions = QHBoxLayout()
        self.rule_actions.setObjectName(u"rule_actions")
        self.delete_button = QPushButton(self.left)
        self.delete_button.setObjectName(u"delete_button")

        self.rule_actions.addWidget(self.delete_button)

        self.clear_button = QPushButton(self.left)
        self.clear_button.setObjectName(u"clear_button")

        self.rule_actions.addWidget(self.clear_button)

        self.up_button = QPushButton(self.left)
        self.up_button.setObjectName(u"up_button")

        self.rule_actions.addWidget(self.up_button)

        self.down_button = QPushButton(self.left)
        self.down_button.setObjectName(u"down_button")

        self.rule_actions.addWidget(self.down_button)


        self.left_layout.addLayout(self.rule_actions)

        self.panel = RulePanel(self.left)
        self.panel.setObjectName(u"panel")

        self.left_layout.addWidget(self.panel)

        self.left_layout.setStretch(2, 1)
        self.left_layout.setStretch(4, 3)
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
        self.viewer = PageViewer(self.content)
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
        FontReplaceWindow.setCentralWidget(self.splitter)

        self.retranslateUi(FontReplaceWindow)

        QMetaObject.connectSlotsByName(FontReplaceWindow)
    # setupUi

    def retranslateUi(self, FontReplaceWindow):
        FontReplaceWindow.setWindowTitle(QCoreApplication.translate("FontReplaceWindow", u"PDF Font Replacer", None))
        self.open_button.setText(QCoreApplication.translate("FontReplaceWindow", u"Open PDF", None))
        self.close_button.setText(QCoreApplication.translate("FontReplaceWindow", u"Close", None))
        self.rules_heading.setText(QCoreApplication.translate("FontReplaceWindow", u"Replacement rules \u2014 first match wins", None))
        ___qtreewidgetitem = self.rule_list.headerItem()
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("FontReplaceWindow", u"Replace with", None));
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("FontReplaceWindow", u"Replace from", None));
        self.delete_button.setText(QCoreApplication.translate("FontReplaceWindow", u"Delete", None))
        self.clear_button.setText(QCoreApplication.translate("FontReplaceWindow", u"Clear", None))
        self.up_button.setText(QCoreApplication.translate("FontReplaceWindow", u"\u2191", None))
        self.down_button.setText(QCoreApplication.translate("FontReplaceWindow", u"\u2193", None))
        self.status.setText(QCoreApplication.translate("FontReplaceWindow", u"Open or drop a PDF to begin.", None))
        self.export_button.setText(QCoreApplication.translate("FontReplaceWindow", u"Export PDF", None))
        self.toolbar.setWindowTitle("")
        self.tool_toolbar.setWindowTitle(QCoreApplication.translate("FontReplaceWindow", u"Preview options", None))
    # retranslateUi

