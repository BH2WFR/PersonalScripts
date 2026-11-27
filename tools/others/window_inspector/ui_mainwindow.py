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
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QSpacerItem,
    QSplitter, QTabWidget, QToolBar, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelSpinBox)
from window_inspector.picker import Finder
from window_inspector.table import ValueTable

class Ui_Inspector(object):
    def setupUi(self, Inspector):
        if not Inspector.objectName():
            Inspector.setObjectName(u"Inspector")
        Inspector.resize(1080, 720)
        Inspector.setMinimumSize(QSize(0, 400))
        self.action_properties = QAction(Inspector)
        self.action_properties.setObjectName(u"action_properties")
        self.action_show_file = QAction(Inspector)
        self.action_show_file.setObjectName(u"action_show_file")
        self.action_restart = QAction(Inspector)
        self.action_restart.setObjectName(u"action_restart")
        self.action_terminate = QAction(Inspector)
        self.action_terminate.setObjectName(u"action_terminate")
        self.action_activate = QAction(Inspector)
        self.action_activate.setObjectName(u"action_activate")
        self.action_center = QAction(Inspector)
        self.action_center.setObjectName(u"action_center")
        self.action_reset_size = QAction(Inspector)
        self.action_reset_size.setObjectName(u"action_reset_size")
        self.action_highlight = QAction(Inspector)
        self.action_highlight.setObjectName(u"action_highlight")
        self.action_minimize = QAction(Inspector)
        self.action_minimize.setObjectName(u"action_minimize")
        self.action_close_window = QAction(Inspector)
        self.action_close_window.setObjectName(u"action_close_window")
        self.action_always_on_top = QAction(Inspector)
        self.action_always_on_top.setObjectName(u"action_always_on_top")
        self.action_always_on_top.setCheckable(True)
        self.action_opacity = QAction(Inspector)
        self.action_opacity.setObjectName(u"action_opacity")
        self.action_click_through = QAction(Inspector)
        self.action_click_through.setObjectName(u"action_click_through")
        self.action_click_through.setCheckable(True)
        self.action_enable_controls = QAction(Inspector)
        self.action_enable_controls.setObjectName(u"action_enable_controls")
        self.action_show_controls = QAction(Inspector)
        self.action_show_controls.setObjectName(u"action_show_controls")
        self.action_enable_menus = QAction(Inspector)
        self.action_enable_menus.setObjectName(u"action_enable_menus")
        self.main_layout = QVBoxLayout(Inspector)
        self.main_layout.setSpacing(6)
        self.main_layout.setObjectName(u"main_layout")
        self.main_layout.setContentsMargins(8, 4, 8, 8)
        self.header_layout = QHBoxLayout()
        self.header_layout.setSpacing(6)
        self.header_layout.setObjectName(u"header_layout")
        self.finder = Finder(Inspector)
        self.finder.setObjectName(u"finder")
        self.finder.setMinimumSize(QSize(34, 30))
        self.finder.setMaximumSize(QSize(34, 16777215))
        self.finder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.header_layout.addWidget(self.finder)

        self.selector = NoWheelComboBox(Inspector)
        self.selector.setObjectName(u"selector")
        self.selector.setEditable(True)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.selector.sizePolicy().hasHeightForWidth())
        self.selector.setSizePolicy(sizePolicy)

        self.header_layout.addWidget(self.selector)

        self.list_button = QPushButton(Inspector)
        self.list_button.setObjectName(u"list_button")

        self.header_layout.addWidget(self.list_button)

        self.find_button = QPushButton(Inspector)
        self.find_button.setObjectName(u"find_button")

        self.header_layout.addWidget(self.find_button)

        self.header_layout.setStretch(1, 1)

        self.main_layout.addLayout(self.header_layout)

        self.options_layout = QHBoxLayout()
        self.options_layout.setSpacing(6)
        self.options_layout.setObjectName(u"options_layout")
        self.finder_hint = QLabel(Inspector)
        self.finder_hint.setObjectName(u"finder_hint")

        self.options_layout.addWidget(self.finder_hint)

        self.options_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.options_layout.addItem(self.options_stretch)

        self.hidden_windows = QCheckBox(Inspector)
        self.hidden_windows.setObjectName(u"hidden_windows")

        self.options_layout.addWidget(self.hidden_windows)

        self.pin = QCheckBox(Inspector)
        self.pin.setObjectName(u"pin")

        self.options_layout.addWidget(self.pin)

        self.options_separator = QFrame(Inspector)
        self.options_separator.setObjectName(u"options_separator")
        self.options_separator.setFrameShape(QFrame.Shape.VLine)
        self.options_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.options_layout.addWidget(self.options_separator)

        self.refresh_button = QPushButton(Inspector)
        self.refresh_button.setObjectName(u"refresh_button")

        self.options_layout.addWidget(self.refresh_button)

        self.read_button = QPushButton(Inspector)
        self.read_button.setObjectName(u"read_button")

        self.options_layout.addWidget(self.read_button)


        self.main_layout.addLayout(self.options_layout)

        self.actions_group = QGroupBox(Inspector)
        self.actions_group.setObjectName(u"actions_group")
        self.action_layout = QGridLayout(self.actions_group)
        self.action_layout.setObjectName(u"action_layout")
        self.action_layout.setVerticalSpacing(0)
        self.action_layout.setContentsMargins(6, 0, 6, 0)
        self.process_label = QLabel(self.actions_group)
        self.process_label.setObjectName(u"process_label")
        font = QFont()
        font.setBold(True)
        self.process_label.setFont(font)

        self.action_layout.addWidget(self.process_label, 0, 0, 1, 1)

        self.process_row = QHBoxLayout()
        self.process_row.setSpacing(6)
        self.process_row.setObjectName(u"process_row")
        self.process_bar = QToolBar(self.actions_group)
        self.process_bar.setObjectName(u"process_bar")
        self.process_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        self.process_row.addWidget(self.process_bar)

        self.priority_separator = QFrame(self.actions_group)
        self.priority_separator.setObjectName(u"priority_separator")
        self.priority_separator.setFrameShape(QFrame.Shape.VLine)
        self.priority_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.process_row.addWidget(self.priority_separator)

        self.priority_label = QLabel(self.actions_group)
        self.priority_label.setObjectName(u"priority_label")
        self.priority_label.setFont(font)

        self.process_row.addWidget(self.priority_label)

        self.windows_priority = NoWheelComboBox(self.actions_group)
        self.windows_priority.setObjectName(u"windows_priority")

        self.process_row.addWidget(self.windows_priority)

        self.nice_priority = NoWheelSpinBox(self.actions_group)
        self.nice_priority.setObjectName(u"nice_priority")

        self.process_row.addWidget(self.nice_priority)

        self.process_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.process_row.addItem(self.process_stretch)


        self.action_layout.addLayout(self.process_row, 0, 1, 1, 1)

        self.window_label = QLabel(self.actions_group)
        self.window_label.setObjectName(u"window_label")
        self.window_label.setFont(font)

        self.action_layout.addWidget(self.window_label, 1, 0, 1, 1)

        self.window_row = QHBoxLayout()
        self.window_row.setSpacing(6)
        self.window_row.setObjectName(u"window_row")
        self.window_bar = QToolBar(self.actions_group)
        self.window_bar.setObjectName(u"window_bar")
        self.window_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        self.window_row.addWidget(self.window_bar)

        self.window_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.window_row.addItem(self.window_stretch)


        self.action_layout.addLayout(self.window_row, 1, 1, 1, 1)

        self.action_layout.setColumnStretch(1, 1)

        self.main_layout.addWidget(self.actions_group)

        self.details_group = QGroupBox(Inspector)
        self.details_group.setObjectName(u"details_group")
        self.details_layout = QVBoxLayout(self.details_group)
        self.details_layout.setObjectName(u"details_layout")
        self.details_layout.setContentsMargins(-1, -1, -1, 2)
        self.field_grid = QGridLayout()
        self.field_grid.setObjectName(u"field_grid")
        self.field_grid.setHorizontalSpacing(6)
        self.field_grid.setVerticalSpacing(2)
        self.title_field_label = QLabel(self.details_group)
        self.title_field_label.setObjectName(u"title_field_label")

        self.field_grid.addWidget(self.title_field_label, 0, 0, 1, 1)

        self.title_field = QLineEdit(self.details_group)
        self.title_field.setObjectName(u"title_field")
        self.title_field.setReadOnly(True)

        self.field_grid.addWidget(self.title_field, 0, 1, 1, 1)

        self.process_field_label = QLabel(self.details_group)
        self.process_field_label.setObjectName(u"process_field_label")

        self.field_grid.addWidget(self.process_field_label, 1, 0, 1, 1)

        self.process_field = QLineEdit(self.details_group)
        self.process_field.setObjectName(u"process_field")
        self.process_field.setReadOnly(True)

        self.field_grid.addWidget(self.process_field, 1, 1, 1, 1)

        self.path_field_label = QLabel(self.details_group)
        self.path_field_label.setObjectName(u"path_field_label")

        self.field_grid.addWidget(self.path_field_label, 2, 0, 1, 1)

        self.path_layout = QHBoxLayout()
        self.path_layout.setSpacing(6)
        self.path_layout.setObjectName(u"path_layout")
        self.paths = NoWheelComboBox(self.details_group)
        self.paths.setObjectName(u"paths")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.paths.sizePolicy().hasHeightForWidth())
        self.paths.setSizePolicy(sizePolicy1)

        self.path_layout.addWidget(self.paths)

        self.path_field = QLineEdit(self.details_group)
        self.path_field.setObjectName(u"path_field")
        self.path_field.setReadOnly(True)

        self.path_layout.addWidget(self.path_field)

        self.path_layout.setStretch(1, 1)

        self.field_grid.addLayout(self.path_layout, 2, 1, 1, 1)

        self.command_field_label = QLabel(self.details_group)
        self.command_field_label.setObjectName(u"command_field_label")

        self.field_grid.addWidget(self.command_field_label, 3, 0, 1, 1)

        self.command_field = QLineEdit(self.details_group)
        self.command_field.setObjectName(u"command_field")
        self.command_field.setReadOnly(True)

        self.field_grid.addWidget(self.command_field, 3, 1, 1, 1)

        self.field_grid.setColumnStretch(1, 1)

        self.details_layout.addLayout(self.field_grid)

        self.splitter = QSplitter(self.details_group)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.info = ValueTable(self.splitter)
        self.info.setObjectName(u"info")
        self.info.setIndentation(16)
        self.info.setRootIsDecorated(True)
        self.info.setUniformRowHeights(True)
        self.splitter.addWidget(self.info)
        self.info.header().setStretchLastSection(False)
        self.tabs = QTabWidget(self.splitter)
        self.tabs.setObjectName(u"tabs")
        self.controls = QTreeWidget()
        self.controls.setObjectName(u"controls")
        self.controls.setRootIsDecorated(False)
        self.controls.setUniformRowHeights(True)
        self.tabs.addTab(self.controls, "")
        self.controls.header().setStretchLastSection(False)
        self.arguments = ValueTable()
        self.arguments.setObjectName(u"arguments")
        self.arguments.setRootIsDecorated(False)
        self.arguments.setUniformRowHeights(True)
        self.tabs.addTab(self.arguments, "")
        self.arguments.header().setStretchLastSection(False)
        self.splitter.addWidget(self.tabs)

        self.details_layout.addWidget(self.splitter)

        self.details_layout.setStretch(1, 1)

        self.main_layout.addWidget(self.details_group)

        self.footer_layout = QHBoxLayout()
        self.footer_layout.setSpacing(6)
        self.footer_layout.setObjectName(u"footer_layout")
        self.status = QLabel(Inspector)
        self.status.setObjectName(u"status")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.status.sizePolicy().hasHeightForWidth())
        self.status.setSizePolicy(sizePolicy2)

        self.footer_layout.addWidget(self.status)

        self.copy_hint = QLabel(Inspector)
        self.copy_hint.setObjectName(u"copy_hint")

        self.footer_layout.addWidget(self.copy_hint)

        self.copy_button = QPushButton(Inspector)
        self.copy_button.setObjectName(u"copy_button")

        self.footer_layout.addWidget(self.copy_button)

        self.footer_layout.setStretch(0, 1)

        self.main_layout.addLayout(self.footer_layout)

        self.main_layout.setStretch(3, 1)

        self.process_bar.addAction(self.action_properties)
        self.process_bar.addAction(self.action_show_file)
        self.process_bar.addSeparator()
        self.process_bar.addAction(self.action_restart)
        self.process_bar.addAction(self.action_terminate)
        self.window_bar.addAction(self.action_activate)
        self.window_bar.addAction(self.action_center)
        self.window_bar.addAction(self.action_reset_size)
        self.window_bar.addAction(self.action_highlight)
        self.window_bar.addSeparator()
        self.window_bar.addAction(self.action_minimize)
        self.window_bar.addAction(self.action_close_window)
        self.window_bar.addSeparator()
        self.window_bar.addAction(self.action_always_on_top)
        self.window_bar.addAction(self.action_opacity)
        self.window_bar.addAction(self.action_click_through)
        self.window_bar.addSeparator()
        self.window_bar.addAction(self.action_enable_controls)
        self.window_bar.addAction(self.action_show_controls)
        self.window_bar.addAction(self.action_enable_menus)

        self.retranslateUi(Inspector)

        QMetaObject.connectSlotsByName(Inspector)
    # setupUi

    def retranslateUi(self, Inspector):
        Inspector.setWindowTitle(QCoreApplication.translate("Inspector", u"Window Inspector", None))
        self.action_properties.setText(QCoreApplication.translate("Inspector", u"Properties", None))
#if QT_CONFIG(tooltip)
        self.action_properties.setToolTip(QCoreApplication.translate("Inspector", u"Show properties for the selected path.", None))
#endif // QT_CONFIG(tooltip)
        self.action_show_file.setText(QCoreApplication.translate("Inspector", u"Show File", None))
#if QT_CONFIG(tooltip)
        self.action_show_file.setToolTip(QCoreApplication.translate("Inspector", u"Reveal the selected path in its containing folder.", None))
#endif // QT_CONFIG(tooltip)
        self.action_restart.setText(QCoreApplication.translate("Inspector", u"Restart", None))
#if QT_CONFIG(tooltip)
        self.action_restart.setToolTip(QCoreApplication.translate("Inspector", u"End the process and relaunch it with its original arguments.", None))
#endif // QT_CONFIG(tooltip)
        self.action_terminate.setText(QCoreApplication.translate("Inspector", u"Terminate", None))
#if QT_CONFIG(tooltip)
        self.action_terminate.setToolTip(QCoreApplication.translate("Inspector", u"Force the process to quit, including all of its windows.", None))
#endif // QT_CONFIG(tooltip)
        self.action_activate.setText(QCoreApplication.translate("Inspector", u"Activate", None))
#if QT_CONFIG(tooltip)
        self.action_activate.setToolTip(QCoreApplication.translate("Inspector", u"Bring the window to the front for three seconds.", None))
#endif // QT_CONFIG(tooltip)
        self.action_center.setText(QCoreApplication.translate("Inspector", u"Center", None))
#if QT_CONFIG(tooltip)
        self.action_center.setToolTip(QCoreApplication.translate("Inspector", u"Bring the window forward, center it, and highlight it for three seconds.", None))
#endif // QT_CONFIG(tooltip)
        self.action_reset_size.setText(QCoreApplication.translate("Inspector", u"Reset Size", None))
#if QT_CONFIG(tooltip)
        self.action_reset_size.setToolTip(QCoreApplication.translate("Inspector", u"Bring the window forward, restore its default size, center it, and highlight it for three seconds.", None))
#endif // QT_CONFIG(tooltip)
        self.action_highlight.setText(QCoreApplication.translate("Inspector", u"Highlight", None))
#if QT_CONFIG(tooltip)
        self.action_highlight.setToolTip(QCoreApplication.translate("Inspector", u"Outline the window on screen for three seconds.", None))
#endif // QT_CONFIG(tooltip)
        self.action_minimize.setText(QCoreApplication.translate("Inspector", u"Minimize", None))
#if QT_CONFIG(tooltip)
        self.action_minimize.setToolTip(QCoreApplication.translate("Inspector", u"Minimize the selected window.", None))
#endif // QT_CONFIG(tooltip)
        self.action_close_window.setText(QCoreApplication.translate("Inspector", u"Close Window", None))
#if QT_CONFIG(tooltip)
        self.action_close_window.setToolTip(QCoreApplication.translate("Inspector", u"Ask the selected window to close.", None))
#endif // QT_CONFIG(tooltip)
        self.action_always_on_top.setText(QCoreApplication.translate("Inspector", u"Always on Top", None))
#if QT_CONFIG(tooltip)
        self.action_always_on_top.setToolTip(QCoreApplication.translate("Inspector", u"Keep the selected window above other windows.", None))
#endif // QT_CONFIG(tooltip)
        self.action_opacity.setText(QCoreApplication.translate("Inspector", u"Opacity", None))
#if QT_CONFIG(tooltip)
        self.action_opacity.setToolTip(QCoreApplication.translate("Inspector", u"Adjust the opacity of the selected window.", None))
#endif // QT_CONFIG(tooltip)
        self.action_click_through.setText(QCoreApplication.translate("Inspector", u"Click-through", None))
#if QT_CONFIG(tooltip)
        self.action_click_through.setToolTip(QCoreApplication.translate("Inspector", u"Let mouse clicks pass through the selected window.", None))
#endif // QT_CONFIG(tooltip)
        self.action_enable_controls.setText(QCoreApplication.translate("Inspector", u"Enable Controls", None))
#if QT_CONFIG(tooltip)
        self.action_enable_controls.setToolTip(QCoreApplication.translate("Inspector", u"Enable disabled controls in the selected window.", None))
#endif // QT_CONFIG(tooltip)
        self.action_show_controls.setText(QCoreApplication.translate("Inspector", u"Show Controls", None))
#if QT_CONFIG(tooltip)
        self.action_show_controls.setToolTip(QCoreApplication.translate("Inspector", u"Show hidden controls in the selected window.", None))
#endif // QT_CONFIG(tooltip)
        self.action_enable_menus.setText(QCoreApplication.translate("Inspector", u"Enable Menus", None))
#if QT_CONFIG(tooltip)
        self.action_enable_menus.setToolTip(QCoreApplication.translate("Inspector", u"Enable disabled menu items in the selected window.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.finder.setToolTip(QCoreApplication.translate("Inspector", u"Drag the finder onto a window. Release to inspect it, or press Esc to cancel.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.finder.setAccessibleName(QCoreApplication.translate("Inspector", u"Window finder", None))
#endif // QT_CONFIG(accessibility)
#if QT_CONFIG(tooltip)
        self.selector.setToolTip(QCoreApplication.translate("Inspector", u"Search by window title, process name, window ID, or PID (for example, PID:1234).", None))
#endif // QT_CONFIG(tooltip)
        self.list_button.setText(QCoreApplication.translate("Inspector", u"Refresh List", None))
#if QT_CONFIG(tooltip)
        self.list_button.setToolTip(QCoreApplication.translate("Inspector", u"Load the current list of windows.", None))
#endif // QT_CONFIG(tooltip)
        self.find_button.setText(QCoreApplication.translate("Inspector", u"Find", None))
#if QT_CONFIG(tooltip)
        self.find_button.setToolTip(QCoreApplication.translate("Inspector", u"Inspect the first window matching your search.", None))
#endif // QT_CONFIG(tooltip)
        self.finder_hint.setText(QCoreApplication.translate("Inspector", u"\u2b06\ufe0f Drag the finder onto a window", None))
        self.hidden_windows.setText(QCoreApplication.translate("Inspector", u"Include hidden windows", None))
#if QT_CONFIG(tooltip)
        self.hidden_windows.setToolTip(QCoreApplication.translate("Inspector", u"Include hidden windows when listing or searching.", None))
#endif // QT_CONFIG(tooltip)
        self.pin.setText(QCoreApplication.translate("Inspector", u"Keep inspector on top", None))
#if QT_CONFIG(tooltip)
        self.pin.setToolTip(QCoreApplication.translate("Inspector", u"Keep Window Inspector above other windows.", None))
#endif // QT_CONFIG(tooltip)
        self.refresh_button.setText(QCoreApplication.translate("Inspector", u"Refresh Info", None))
#if QT_CONFIG(tooltip)
        self.refresh_button.setToolTip(QCoreApplication.translate("Inspector", u"Read the selected window and process details again.", None))
#endif // QT_CONFIG(tooltip)
        self.read_button.setText(QCoreApplication.translate("Inspector", u"Read Controls", None))
#if QT_CONFIG(tooltip)
        self.read_button.setToolTip(QCoreApplication.translate("Inspector", u"List the controls exposed by the selected window.", None))
#endif // QT_CONFIG(tooltip)
        self.actions_group.setTitle(QCoreApplication.translate("Inspector", u"Actions", None))
        self.process_label.setText(QCoreApplication.translate("Inspector", u"Process:", None))
        self.process_bar.setWindowTitle(QCoreApplication.translate("Inspector", u"Process", None))
#if QT_CONFIG(accessibility)
        self.process_bar.setAccessibleName(QCoreApplication.translate("Inspector", u"Process", None))
#endif // QT_CONFIG(accessibility)
        self.process_bar.setStyleSheet(QCoreApplication.translate("Inspector", u"QToolBar { border: 0; padding: 0; }", None))
        self.priority_label.setText(QCoreApplication.translate("Inspector", u"Priority:", None))
#if QT_CONFIG(tooltip)
        self.windows_priority.setToolTip(QCoreApplication.translate("Inspector", u"Choose the scheduling priority for the selected process.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.nice_priority.setToolTip(QCoreApplication.translate("Inspector", u"Select a nice value from \u221220 to 19. Lower values give the process higher priority.", None))
#endif // QT_CONFIG(tooltip)
        self.window_label.setText(QCoreApplication.translate("Inspector", u"Window:", None))
        self.window_bar.setWindowTitle(QCoreApplication.translate("Inspector", u"Window", None))
#if QT_CONFIG(accessibility)
        self.window_bar.setAccessibleName(QCoreApplication.translate("Inspector", u"Window", None))
#endif // QT_CONFIG(accessibility)
        self.window_bar.setStyleSheet(QCoreApplication.translate("Inspector", u"QToolBar { border: 0; padding: 0; }", None))
        self.details_group.setTitle(QCoreApplication.translate("Inspector", u"Window details", None))
        self.title_field_label.setText(QCoreApplication.translate("Inspector", u"Title", None))
        self.title_field.setStyleSheet(QCoreApplication.translate("Inspector", u"max-height: 1.2em;", None))
        self.process_field_label.setText(QCoreApplication.translate("Inspector", u"Process", None))
        self.process_field.setStyleSheet(QCoreApplication.translate("Inspector", u"max-height: 1.2em;", None))
        self.path_field_label.setText(QCoreApplication.translate("Inspector", u"Path", None))
#if QT_CONFIG(tooltip)
        self.paths.setToolTip(QCoreApplication.translate("Inspector", u"Choose the executable, application bundle or window document.", None))
#endif // QT_CONFIG(tooltip)
        self.path_field.setStyleSheet(QCoreApplication.translate("Inspector", u"max-height: 1.2em;", None))
        self.command_field_label.setText(QCoreApplication.translate("Inspector", u"Command line", None))
        self.command_field.setStyleSheet(QCoreApplication.translate("Inspector", u"max-height: 1.2em;", None))
        ___qtreewidgetitem = self.info.headerItem()
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("Inspector", u"Value", None));
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("Inspector", u"Property", None));
        ___qtreewidgetitem1 = self.controls.headerItem()
        ___qtreewidgetitem1.setText(5, QCoreApplication.translate("Inspector", u"Position and size", None));
        ___qtreewidgetitem1.setText(4, QCoreApplication.translate("Inspector", u"Class", None));
        ___qtreewidgetitem1.setText(3, QCoreApplication.translate("Inspector", u"Text", None));
        ___qtreewidgetitem1.setText(2, QCoreApplication.translate("Inspector", u"ClassNN", None));
        ___qtreewidgetitem1.setText(1, QCoreApplication.translate("Inspector", u"HWND", None));
        ___qtreewidgetitem1.setText(0, QCoreApplication.translate("Inspector", u"#", None));
        self.tabs.setTabText(self.tabs.indexOf(self.controls), QCoreApplication.translate("Inspector", u"Controls", None))
        ___qtreewidgetitem2 = self.arguments.headerItem()
        ___qtreewidgetitem2.setText(1, QCoreApplication.translate("Inspector", u"Argument", None));
        ___qtreewidgetitem2.setText(0, QCoreApplication.translate("Inspector", u"#", None));
        self.tabs.setTabText(self.tabs.indexOf(self.arguments), QCoreApplication.translate("Inspector", u"Arguments", None))
        self.copy_hint.setText(QCoreApplication.translate("Inspector", u"Double-click a row to copy its contents.", None))
        self.copy_button.setText(QCoreApplication.translate("Inspector", u"Copy All", None))
#if QT_CONFIG(tooltip)
        self.copy_button.setToolTip(QCoreApplication.translate("Inspector", u"Copy the displayed details, controls and arguments.", None))
#endif // QT_CONFIG(tooltip)
    # retranslateUi

