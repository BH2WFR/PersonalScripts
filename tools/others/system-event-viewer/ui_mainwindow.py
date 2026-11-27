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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDateTimeEdit, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QPlainTextEdit, QProgressBar, QPushButton,
    QSizePolicy, QSpacerItem, QSplitter, QTabWidget,
    QTableView, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget)

from utils.qt_widgets import NoWheelComboBox

class Ui_PowerEventsWindow(object):
    def setupUi(self, PowerEventsWindow):
        if not PowerEventsWindow.objectName():
            PowerEventsWindow.setObjectName(u"PowerEventsWindow")
        PowerEventsWindow.resize(1200, 800)
        self.central_widget = QWidget(PowerEventsWindow)
        self.central_widget.setObjectName(u"central_widget")
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setSpacing(4)
        self.main_layout.setObjectName(u"main_layout")
        self.main_layout.setContentsMargins(6, 6, 6, 4)
        self.query_layout = QHBoxLayout()
        self.query_layout.setSpacing(4)
        self.query_layout.setObjectName(u"query_layout")
        self.range_label = QLabel(self.central_widget)
        self.range_label.setObjectName(u"range_label")
        self.range_label.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)

        self.query_layout.addWidget(self.range_label)

        self.range_box = NoWheelComboBox(self.central_widget)
        self.range_box.setObjectName(u"range_box")

        self.query_layout.addWidget(self.range_box)

        self.start_label = QLabel(self.central_widget)
        self.start_label.setObjectName(u"start_label")
        self.start_label.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)

        self.query_layout.addWidget(self.start_label)

        self.start_edit = QDateTimeEdit(self.central_widget)
        self.start_edit.setObjectName(u"start_edit")
        self.start_edit.setMinimumSize(QSize(180, 0))
        self.start_edit.setCalendarPopup(True)

        self.query_layout.addWidget(self.start_edit)

        self.end_label = QLabel(self.central_widget)
        self.end_label.setObjectName(u"end_label")
        self.end_label.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)

        self.query_layout.addWidget(self.end_label)

        self.end_edit = QDateTimeEdit(self.central_widget)
        self.end_edit.setObjectName(u"end_edit")
        self.end_edit.setMinimumSize(QSize(180, 0))
        self.end_edit.setCalendarPopup(True)

        self.query_layout.addWidget(self.end_edit)

        self.before_divider = QSpacerItem(8, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.query_layout.addItem(self.before_divider)

        self.query_divider = QFrame(self.central_widget)
        self.query_divider.setObjectName(u"query_divider")
        self.query_divider.setFrameShape(QFrame.Shape.VLine)
        self.query_divider.setFrameShadow(QFrame.Shadow.Sunken)

        self.query_layout.addWidget(self.query_divider)

        self.after_divider = QSpacerItem(8, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.query_layout.addItem(self.after_divider)

        self.query_button = QPushButton(self.central_widget)
        self.query_button.setObjectName(u"query_button")

        self.query_layout.addWidget(self.query_button)

        self.cancel_button = QPushButton(self.central_widget)
        self.cancel_button.setObjectName(u"cancel_button")
        self.cancel_button.setEnabled(False)

        self.query_layout.addWidget(self.cancel_button)


        self.main_layout.addLayout(self.query_layout)

        self.filter_actions = QHBoxLayout()
        self.filter_actions.setSpacing(3)
        self.filter_actions.setObjectName(u"filter_actions")
        self.filter_title = QLabel(self.central_widget)
        self.filter_title.setObjectName(u"filter_title")

        self.filter_actions.addWidget(self.filter_title)

        self.select_all_button = QToolButton(self.central_widget)
        self.select_all_button.setObjectName(u"select_all_button")

        self.filter_actions.addWidget(self.select_all_button)

        self.select_none_button = QToolButton(self.central_widget)
        self.select_none_button.setObjectName(u"select_none_button")

        self.filter_actions.addWidget(self.select_none_button)

        self.reset_types_button = QToolButton(self.central_widget)
        self.reset_types_button.setObjectName(u"reset_types_button")

        self.filter_actions.addWidget(self.reset_types_button)

        self.filter_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.filter_actions.addItem(self.filter_stretch)


        self.main_layout.addLayout(self.filter_actions)

        self.filter_panel = QWidget(self.central_widget)
        self.filter_panel.setObjectName(u"filter_panel")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.filter_panel.sizePolicy().hasHeightForWidth())
        self.filter_panel.setSizePolicy(sizePolicy)
        self.filter_grid = QGridLayout(self.filter_panel)
        self.filter_grid.setObjectName(u"filter_grid")
        self.filter_grid.setHorizontalSpacing(6)
        self.filter_grid.setVerticalSpacing(1)
        self.filter_grid.setContentsMargins(2, 0, 2, 0)

        self.main_layout.addWidget(self.filter_panel)

        self.splitter = QSplitter(self.central_widget)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Vertical)
        self.table = QTableView(self.splitter)
        self.table.setObjectName(u"table")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.splitter.addWidget(self.table)
        self.table.verticalHeader().setVisible(False)
        self.tabs = QTabWidget(self.splitter)
        self.tabs.setObjectName(u"tabs")
        self.detail = QPlainTextEdit()
        self.detail.setObjectName(u"detail")
        self.detail.setReadOnly(True)
        self.tabs.addTab(self.detail, "")
        self.structured_page = QWidget()
        self.structured_page.setObjectName(u"structured_page")
        self.structured_layout = QVBoxLayout(self.structured_page)
        self.structured_layout.setObjectName(u"structured_layout")
        self.structured_layout.setContentsMargins(0, 0, 0, 0)
        self.structured_notice = QLabel(self.structured_page)
        self.structured_notice.setObjectName(u"structured_notice")
        self.structured_notice.setTextFormat(Qt.TextFormat.PlainText)
        self.structured_notice.setWordWrap(True)

        self.structured_layout.addWidget(self.structured_notice)

        self.structured_tree = QTreeWidget(self.structured_page)
        self.structured_tree.setObjectName(u"structured_tree")
        self.structured_tree.setAlternatingRowColors(True)
        self.structured_tree.setUniformRowHeights(True)
        self.structured_tree.header().setStretchLastSection(False)

        self.structured_layout.addWidget(self.structured_tree)

        self.structured_layout.setStretch(1, 1)
        self.tabs.addTab(self.structured_page, "")
        self.sources = QPlainTextEdit()
        self.sources.setObjectName(u"sources")
        self.sources.setReadOnly(True)
        self.tabs.addTab(self.sources, "")
        self.splitter.addWidget(self.tabs)

        self.main_layout.addWidget(self.splitter)

        self.footer = QHBoxLayout()
        self.footer.setObjectName(u"footer")
        self.summary = QLabel(self.central_widget)
        self.summary.setObjectName(u"summary")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.summary.sizePolicy().hasHeightForWidth())
        self.summary.setSizePolicy(sizePolicy1)

        self.footer.addWidget(self.summary)

        self.progress_bar = QProgressBar(self.central_widget)
        self.progress_bar.setObjectName(u"progress_bar")
        self.progress_bar.setMinimumSize(QSize(140, 0))
        self.progress_bar.setMaximumSize(QSize(140, 16777215))
        self.progress_bar.setTextVisible(False)

        self.footer.addWidget(self.progress_bar)

        self.export_button = QPushButton(self.central_widget)
        self.export_button.setObjectName(u"export_button")
        self.export_button.setEnabled(False)

        self.footer.addWidget(self.export_button)

        self.export_json_button = QPushButton(self.central_widget)
        self.export_json_button.setObjectName(u"export_json_button")
        self.export_json_button.setEnabled(False)

        self.footer.addWidget(self.export_json_button)

        self.footer.setStretch(0, 1)

        self.main_layout.addLayout(self.footer)

        self.main_layout.setStretch(3, 1)
        PowerEventsWindow.setCentralWidget(self.central_widget)

        self.retranslateUi(PowerEventsWindow)

        QMetaObject.connectSlotsByName(PowerEventsWindow)
    # setupUi

    def retranslateUi(self, PowerEventsWindow):
        PowerEventsWindow.setWindowTitle(QCoreApplication.translate("PowerEventsWindow", u"System Event Viewer", None))
        self.range_label.setText(QCoreApplication.translate("PowerEventsWindow", u"Range", None))
        self.start_label.setText(QCoreApplication.translate("PowerEventsWindow", u"From", None))
#if QT_CONFIG(tooltip)
        self.start_edit.setToolTip(QCoreApplication.translate("PowerEventsWindow", u"Local time; inclusive start.", None))
#endif // QT_CONFIG(tooltip)
        self.start_edit.setDisplayFormat(QCoreApplication.translate("PowerEventsWindow", u"yyyy-MM-dd HH:mm:ss", None))
        self.end_label.setText(QCoreApplication.translate("PowerEventsWindow", u"Until", None))
#if QT_CONFIG(tooltip)
        self.end_edit.setToolTip(QCoreApplication.translate("PowerEventsWindow", u"Local time; exclusive end.", None))
#endif // QT_CONFIG(tooltip)
        self.end_edit.setDisplayFormat(QCoreApplication.translate("PowerEventsWindow", u"yyyy-MM-dd HH:mm:ss", None))
        self.query_button.setText(QCoreApplication.translate("PowerEventsWindow", u"Query / Refresh", None))
#if QT_CONFIG(tooltip)
        self.query_button.setToolTip(QCoreApplication.translate("PowerEventsWindow", u"Query / Refresh (F5)", None))
#endif // QT_CONFIG(tooltip)
        self.cancel_button.setText(QCoreApplication.translate("PowerEventsWindow", u"Cancel", None))
        self.filter_title.setText(QCoreApplication.translate("PowerEventsWindow", u"Show events", None))
#if QT_CONFIG(tooltip)
        self.filter_title.setToolTip(QCoreApplication.translate("PowerEventsWindow", u"Changing event selections refreshes history automatically.", None))
#endif // QT_CONFIG(tooltip)
        self.select_all_button.setText(QCoreApplication.translate("PowerEventsWindow", u"All", None))
        self.select_none_button.setText(QCoreApplication.translate("PowerEventsWindow", u"None", None))
        self.reset_types_button.setText(QCoreApplication.translate("PowerEventsWindow", u"Reset", None))
#if QT_CONFIG(tooltip)
        self.reset_types_button.setToolTip(QCoreApplication.translate("PowerEventsWindow", u"Restore default event filters; retain dates and layout.", None))
#endif // QT_CONFIG(tooltip)
        self.detail.setPlaceholderText(QCoreApplication.translate("PowerEventsWindow", u"Select an event to inspect its original evidence.", None))
        self.tabs.setTabText(self.tabs.indexOf(self.detail), QCoreApplication.translate("PowerEventsWindow", u"Event details", None))
        self.structured_notice.setText(QCoreApplication.translate("PowerEventsWindow", u"Select an event to inspect its XML or JSON.", None))
        ___qtreewidgetitem = self.structured_tree.headerItem()
        ___qtreewidgetitem.setText(2, QCoreApplication.translate("PowerEventsWindow", u"Attributes / Type", None));
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("PowerEventsWindow", u"Value", None));
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("PowerEventsWindow", u"Node", None));
        self.tabs.setTabText(self.tabs.indexOf(self.structured_page), QCoreApplication.translate("PowerEventsWindow", u"Structured view", None))
        self.tabs.setTabText(self.tabs.indexOf(self.sources), QCoreApplication.translate("PowerEventsWindow", u"Sources and coverage", None))
        self.summary.setText(QCoreApplication.translate("PowerEventsWindow", u"Ready", None))
#if QT_CONFIG(accessibility)
        self.progress_bar.setAccessibleName(QCoreApplication.translate("PowerEventsWindow", u"Query progress", None))
#endif // QT_CONFIG(accessibility)
        self.export_button.setText(QCoreApplication.translate("PowerEventsWindow", u"Export CSV...", None))
        self.export_json_button.setText(QCoreApplication.translate("PowerEventsWindow", u"Export JSON...", None))
    # retranslateUi

