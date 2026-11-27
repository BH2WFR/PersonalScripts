# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'image_mainwindow.ui'
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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QPlainTextEdit, QPushButton,
    QSizePolicy, QSplitter, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from ..common.llm_window import ApiSettingsForm
from ..common.task_buttons import TaskControls
from ..common.viewer import PageViewer
from .exchange_view import ExchangeView
from .formula_preview import FormulaPreviewTab
from .panel import OcrSettingsTabs
from .vision_panel import VisionPanel
from utils.qt_widgets import NoWheelComboBox

class Ui_ImageWindow(object):
    def setupUi(self, ImageWindow):
        if not ImageWindow.objectName():
            ImageWindow.setObjectName(u"ImageWindow")
        ImageWindow.resize(1160, 780)
        self.splitter = QSplitter(ImageWindow)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.left = QWidget(self.splitter)
        self.left.setObjectName(u"left")
        self.controls = QVBoxLayout(self.left)
        self.controls.setObjectName(u"controls")
        self.mode = NoWheelComboBox(self.left)
        self.mode.setObjectName(u"mode")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.mode.sizePolicy().hasHeightForWidth())
        self.mode.setSizePolicy(sizePolicy)

        self.controls.addWidget(self.mode)

        self.delimiter = NoWheelComboBox(self.left)
        self.delimiter.setObjectName(u"delimiter")
        sizePolicy.setHeightForWidth(self.delimiter.sizePolicy().hasHeightForWidth())
        self.delimiter.setSizePolicy(sizePolicy)

        self.controls.addWidget(self.delimiter)

        self.formula_controls = QWidget(self.left)
        self.formula_controls.setObjectName(u"formula_controls")
        self.formula_buttons = QHBoxLayout(self.formula_controls)
        self.formula_buttons.setObjectName(u"formula_buttons")
        self.formula_buttons.setContentsMargins(0, 0, 0, 0)
        self.formula_install = QPushButton(self.formula_controls)
        self.formula_install.setObjectName(u"formula_install")

        self.formula_buttons.addWidget(self.formula_install)

        self.formula_remove = QPushButton(self.formula_controls)
        self.formula_remove.setObjectName(u"formula_remove")

        self.formula_buttons.addWidget(self.formula_remove)


        self.controls.addWidget(self.formula_controls)

        self.formula_hint = QLabel(self.left)
        self.formula_hint.setObjectName(u"formula_hint")
        self.formula_hint.setWordWrap(True)

        self.controls.addWidget(self.formula_hint)

        self.panel = OcrSettingsTabs(self.left)
        self.panel.setObjectName(u"panel")

        self.controls.addWidget(self.panel)

        self.api_tabs = QTabWidget(self.left)
        self.api_tabs.setObjectName(u"api_tabs")
        self.vision_options = VisionPanel()
        self.vision_options.setObjectName(u"vision_options")
        self.api_tabs.addTab(self.vision_options, "")
        self.api_form = ApiSettingsForm()
        self.api_form.setObjectName(u"api_form")
        self.api_tabs.addTab(self.api_form, "")

        self.controls.addWidget(self.api_tabs)

        self.controls.setStretch(4, 1)
        self.controls.setStretch(5, 1)
        self.splitter.addWidget(self.left)
        self.body = QWidget(self.splitter)
        self.body.setObjectName(u"body")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setObjectName(u"body_layout")
        self.input_actions = QHBoxLayout()
        self.input_actions.setObjectName(u"input_actions")
        self.open_button = QPushButton(self.body)
        self.open_button.setObjectName(u"open_button")

        self.input_actions.addWidget(self.open_button)

        self.paste_button = QPushButton(self.body)
        self.paste_button.setObjectName(u"paste_button")

        self.input_actions.addWidget(self.paste_button)

        self.remove_button = QPushButton(self.body)
        self.remove_button.setObjectName(u"remove_button")

        self.input_actions.addWidget(self.remove_button)

        self.current_button = QPushButton(self.body)
        self.current_button.setObjectName(u"current_button")

        self.input_actions.addWidget(self.current_button)

        self.run_button = QPushButton(self.body)
        self.run_button.setObjectName(u"run_button")

        self.input_actions.addWidget(self.run_button)


        self.body_layout.addLayout(self.input_actions)

        self.list = QTreeWidget(self.body)
        self.list.setObjectName(u"list")
        self.list.setRootIsDecorated(False)
        self.list.setAlternatingRowColors(True)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)

        self.body_layout.addWidget(self.list)

        self.tabs = QTabWidget(self.body)
        self.tabs.setObjectName(u"tabs")
        self.text = QPlainTextEdit()
        self.text.setObjectName(u"text")
        self.text.setReadOnly(True)
        self.tabs.addTab(self.text, "")
        self.viewer = PageViewer()
        self.viewer.setObjectName(u"viewer")
        self.tabs.addTab(self.viewer, "")
        self.preview_tab = FormulaPreviewTab()
        self.preview_tab.setObjectName(u"preview_tab")
        self.tabs.addTab(self.preview_tab, "")
        self.api_log = ExchangeView()
        self.api_log.setObjectName(u"api_log")
        self.tabs.addTab(self.api_log, "")

        self.body_layout.addWidget(self.tabs)

        self.output_actions = QHBoxLayout()
        self.output_actions.setObjectName(u"output_actions")
        self.copy = QPushButton(self.body)
        self.copy.setObjectName(u"copy")

        self.output_actions.addWidget(self.copy)

        self.copy_all = QPushButton(self.body)
        self.copy_all.setObjectName(u"copy_all")

        self.output_actions.addWidget(self.copy_all)

        self.save = QPushButton(self.body)
        self.save.setObjectName(u"save")

        self.output_actions.addWidget(self.save)


        self.body_layout.addLayout(self.output_actions)

        self.footer = QHBoxLayout()
        self.footer.setObjectName(u"footer")
        self.status = QLabel(self.body)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)

        self.footer.addWidget(self.status)

        self.tasks = TaskControls(self.body)
        self.tasks.setObjectName(u"tasks")

        self.footer.addWidget(self.tasks)

        self.footer.setStretch(0, 1)

        self.body_layout.addLayout(self.footer)

        self.body_layout.setStretch(1, 1)
        self.body_layout.setStretch(2, 2)
        self.splitter.addWidget(self.body)
        ImageWindow.setCentralWidget(self.splitter)

        self.retranslateUi(ImageWindow)

        QMetaObject.connectSlotsByName(ImageWindow)
    # setupUi

    def retranslateUi(self, ImageWindow):
        ImageWindow.setWindowTitle(QCoreApplication.translate("ImageWindow", u"Image to Text and Formula", None))
        self.formula_install.setText(QCoreApplication.translate("ImageWindow", u"Install model (99 MiB)", None))
        self.formula_remove.setText(QCoreApplication.translate("ImageWindow", u"Uninstall model", None))
        self.formula_hint.setText("")
        self.api_tabs.setTabText(self.api_tabs.indexOf(self.vision_options), QCoreApplication.translate("ImageWindow", u"Recognition", None))
        self.api_tabs.setTabText(self.api_tabs.indexOf(self.api_form), QCoreApplication.translate("ImageWindow", u"API settings", None))
        self.open_button.setText(QCoreApplication.translate("ImageWindow", u"Add images...", None))
        self.paste_button.setText(QCoreApplication.translate("ImageWindow", u"Paste image", None))
        self.remove_button.setText(QCoreApplication.translate("ImageWindow", u"Remove selected", None))
        self.current_button.setText(QCoreApplication.translate("ImageWindow", u"Recognize current", None))
        self.run_button.setText(QCoreApplication.translate("ImageWindow", u"Recognize all", None))
        ___qtreewidgetitem = self.list.headerItem()
        ___qtreewidgetitem.setText(3, QCoreApplication.translate("ImageWindow", u"Status", None));
        ___qtreewidgetitem.setText(2, QCoreApplication.translate("ImageWindow", u"File size", None));
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("ImageWindow", u"Pixels", None));
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("ImageWindow", u"Image", None));
        self.tabs.setTabText(self.tabs.indexOf(self.text), QCoreApplication.translate("ImageWindow", u"Recognized text", None))
        self.tabs.setTabText(self.tabs.indexOf(self.viewer), QCoreApplication.translate("ImageWindow", u"Image preview", None))
        self.tabs.setTabText(self.tabs.indexOf(self.preview_tab), QCoreApplication.translate("ImageWindow", u"Formula preview", None))
        self.tabs.setTabText(self.tabs.indexOf(self.api_log), QCoreApplication.translate("ImageWindow", u"API exchange", None))
        self.copy.setText(QCoreApplication.translate("ImageWindow", u"Copy current", None))
        self.copy_all.setText(QCoreApplication.translate("ImageWindow", u"Copy all", None))
        self.save.setText(QCoreApplication.translate("ImageWindow", u"Save all as TXT...", None))
        self.status.setText(QCoreApplication.translate("ImageWindow", u"Add or drop images, or paste from the clipboard.", None))
    # retranslateUi

