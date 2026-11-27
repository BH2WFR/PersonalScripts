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
from PySide6.QtWidgets import (QApplication, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QProgressBar, QPushButton,
    QSizePolicy, QSpacerItem, QSplitter, QToolBar,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from ..common.navigation import NavigationPane
from ..common.page_toolbar import (PageToolbar, PreviewOptionsToolbar, PreviewPane)
from ..common.viewer import PageViewer
from .panel import SettingsPanel
from .profile_tree import ProfileTree

class Ui_BinarizeWindow(object):
    def setupUi(self, BinarizeWindow):
        if not BinarizeWindow.objectName():
            BinarizeWindow.setObjectName(u"BinarizeWindow")
        BinarizeWindow.resize(1440, 900)
        BinarizeWindow.setMinimumSize(QSize(980, 600))
        self.splitter = QSplitter(BinarizeWindow)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.left = QWidget(self.splitter)
        self.left.setObjectName(u"left")
        self.left.setMinimumSize(QSize(330, 0))
        self.left_layout = QVBoxLayout(self.left)
        self.left_layout.setSpacing(4)
        self.left_layout.setObjectName(u"left_layout")
        self.left_layout.setContentsMargins(6, 6, 6, 6)
        self.file_toolbar = QToolBar(self.left)
        self.file_toolbar.setObjectName(u"file_toolbar")

        self.left_layout.addWidget(self.file_toolbar)

        self.profiles_box = QGroupBox(self.left)
        self.profiles_box.setObjectName(u"profiles_box")
        self.profiles_layout = QVBoxLayout(self.profiles_box)
        self.profiles_layout.setSpacing(4)
        self.profiles_layout.setObjectName(u"profiles_layout")
        self.profiles_layout.setContentsMargins(6, 6, 6, 6)
        self.profile_actions = QHBoxLayout()
        self.profile_actions.setObjectName(u"profile_actions")
        self.add_profile_button = QPushButton(self.profiles_box)
        self.add_profile_button.setObjectName(u"add_profile_button")

        self.profile_actions.addWidget(self.add_profile_button)

        self.apply_profile_button = QPushButton(self.profiles_box)
        self.apply_profile_button.setObjectName(u"apply_profile_button")

        self.profile_actions.addWidget(self.apply_profile_button)

        self.profile_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.profile_actions.addItem(self.profile_stretch)


        self.profiles_layout.addLayout(self.profile_actions)

        self.profile_list = ProfileTree(self.profiles_box)
        self.profile_list.setObjectName(u"profile_list")
        self.profile_list.setRootIsDecorated(False)
        self.profile_list.setUniformRowHeights(True)

        self.profiles_layout.addWidget(self.profile_list)


        self.left_layout.addWidget(self.profiles_box)

        self.settings = SettingsPanel(self.left)
        self.settings.setObjectName(u"settings")

        self.left_layout.addWidget(self.settings)

        self.left_layout.setStretch(2, 1)
        self.splitter.addWidget(self.left)
        self.right_column = QWidget(self.splitter)
        self.right_column.setObjectName(u"right_column")
        self.right_layout = QVBoxLayout(self.right_column)
        self.right_layout.setObjectName(u"right_layout")
        self.right_layout.setContentsMargins(4, 6, 6, 6)
        self.preview_pane = PreviewPane(self.right_column)
        self.preview_pane.setObjectName(u"preview_pane")
        self.preview_body = QWidget(self.preview_pane)
        self.preview_body.setObjectName(u"preview_body")
        self.preview_layout = QVBoxLayout(self.preview_body)
        self.preview_layout.setSpacing(4)
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

        self.progress_bar = QProgressBar(self.preview_body)
        self.progress_bar.setObjectName(u"progress_bar")
        self.progress_bar.setMinimumSize(QSize(120, 0))
        self.progress_bar.setMaximumSize(QSize(120, 16777215))

        self.footer.addWidget(self.progress_bar)

        self.task_slot = QHBoxLayout()
        self.task_slot.setObjectName(u"task_slot")

        self.footer.addLayout(self.task_slot)

        self.preview_export_button = QPushButton(self.preview_body)
        self.preview_export_button.setObjectName(u"preview_export_button")

        self.footer.addWidget(self.preview_export_button)

        self.export_button = QPushButton(self.preview_body)
        self.export_button.setObjectName(u"export_button")

        self.footer.addWidget(self.export_button)

        self.footer.setStretch(0, 1)

        self.preview_layout.addLayout(self.footer)

        self.preview_layout.setStretch(0, 1)
        self.preview_pane.setCentralWidget(self.preview_body)
        self.view_toolbar = PageToolbar(self.preview_pane)
        self.view_toolbar.setObjectName(u"view_toolbar")
        self.view_toolbar.setMovable(False)
        self.preview_pane.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.view_toolbar)
        self.tool_toolbar = PreviewOptionsToolbar(self.preview_pane)
        self.tool_toolbar.setObjectName(u"tool_toolbar")
        self.tool_toolbar.setMovable(False)
        self.preview_pane.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.tool_toolbar)

        self.right_layout.addWidget(self.preview_pane)

        self.splitter.addWidget(self.right_column)
        BinarizeWindow.setCentralWidget(self.splitter)

        self.retranslateUi(BinarizeWindow)

        QMetaObject.connectSlotsByName(BinarizeWindow)
    # setupUi

    def retranslateUi(self, BinarizeWindow):
        BinarizeWindow.setWindowTitle(QCoreApplication.translate("BinarizeWindow", u"PDF Binarizer", None))
        self.profiles_box.setTitle(QCoreApplication.translate("BinarizeWindow", u"Profiles", None))
        self.add_profile_button.setText(QCoreApplication.translate("BinarizeWindow", u"Add copy", None))
        self.apply_profile_button.setText(QCoreApplication.translate("BinarizeWindow", u"Apply to pages\u2026", None))
        ___qtreewidgetitem = self.profile_list.headerItem()
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("BinarizeWindow", u"Pages", None));
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("BinarizeWindow", u"Profile", None));
        self.status.setText(QCoreApplication.translate("BinarizeWindow", u"Ready. No PDF loaded.", None))
        self.preview_export_button.setText(QCoreApplication.translate("BinarizeWindow", u"Save shown page", None))
        self.export_button.setText(QCoreApplication.translate("BinarizeWindow", u"Export PDF", None))
        self.view_toolbar.setWindowTitle("")
        self.tool_toolbar.setWindowTitle(QCoreApplication.translate("BinarizeWindow", u"Preview options", None))
    # retranslateUi

