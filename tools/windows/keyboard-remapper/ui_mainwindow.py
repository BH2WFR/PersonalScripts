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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QPlainTextEdit, QPushButton,
    QSizePolicy, QSpacerItem, QTableWidgetItem, QToolButton,
    QVBoxLayout, QWidget)

from personal_keyboard_remap.widgets import MappingTable

class Ui_RemapWindow(object):
    def setupUi(self, RemapWindow):
        if not RemapWindow.objectName():
            RemapWindow.setObjectName(u"RemapWindow")
        RemapWindow.resize(1120, 660)
        RemapWindow.setMinimumSize(QSize(860, 480))
        self.central_widget = QWidget(RemapWindow)
        self.central_widget.setObjectName(u"central_widget")
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setObjectName(u"main_layout")
        self.main_layout.setContentsMargins(20, 18, 20, 18)
        self.title = QLabel(self.central_widget)
        self.title.setObjectName(u"title")
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        self.title.setFont(font)

        self.main_layout.addWidget(self.title)

        self.info = QLabel(self.central_widget)
        self.info.setObjectName(u"info")

        self.main_layout.addWidget(self.info)

        self.status = QLabel(self.central_widget)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)

        self.main_layout.addWidget(self.status)

        self.table = MappingTable(self.central_widget)
        if (self.table.columnCount() < 3):
            self.table.setColumnCount(3)
        __qtablewidgetitem = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        self.table.setObjectName(u"table")
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        self.main_layout.addWidget(self.table)

        self.hex_toggle = QToolButton(self.central_widget)
        self.hex_toggle.setObjectName(u"hex_toggle")
        self.hex_toggle.setCheckable(True)
        self.hex_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.hex_toggle.setArrowType(Qt.ArrowType.RightArrow)

        self.main_layout.addWidget(self.hex_toggle)

        self.hex_panel = QWidget(self.central_widget)
        self.hex_panel.setObjectName(u"hex_panel")
        self.hex_layout = QVBoxLayout(self.hex_panel)
        self.hex_layout.setObjectName(u"hex_layout")
        self.hex_layout.setContentsMargins(0, 0, 0, 0)
        self.hex_text = QPlainTextEdit(self.hex_panel)
        self.hex_text.setObjectName(u"hex_text")
        self.hex_text.setReadOnly(True)
        self.hex_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.hex_text.setMinimumSize(QSize(0, 100))
        self.hex_text.setMaximumSize(QSize(16777215, 180))

        self.hex_layout.addWidget(self.hex_text)

        self.hex_actions = QHBoxLayout()
        self.hex_actions.setObjectName(u"hex_actions")
        self.copy_hex_button = QPushButton(self.hex_panel)
        self.copy_hex_button.setObjectName(u"copy_hex_button")

        self.hex_actions.addWidget(self.copy_hex_button)

        self.hex_actions_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.hex_actions.addItem(self.hex_actions_stretch)


        self.hex_layout.addLayout(self.hex_actions)


        self.main_layout.addWidget(self.hex_panel)

        self.draft_actions = QHBoxLayout()
        self.draft_actions.setObjectName(u"draft_actions")
        self.add_button = QPushButton(self.central_widget)
        self.add_button.setObjectName(u"add_button")

        self.draft_actions.addWidget(self.add_button)

        self.edit_button = QPushButton(self.central_widget)
        self.edit_button.setObjectName(u"edit_button")

        self.draft_actions.addWidget(self.edit_button)

        self.remove_button = QPushButton(self.central_widget)
        self.remove_button.setObjectName(u"remove_button")

        self.draft_actions.addWidget(self.remove_button)

        self.clear_button = QPushButton(self.central_widget)
        self.clear_button.setObjectName(u"clear_button")

        self.draft_actions.addWidget(self.clear_button)

        self.draft_actions_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.draft_actions.addItem(self.draft_actions_stretch)


        self.main_layout.addLayout(self.draft_actions)

        self.storage_actions = QHBoxLayout()
        self.storage_actions.setObjectName(u"storage_actions")
        self.reload_button = QPushButton(self.central_widget)
        self.reload_button.setObjectName(u"reload_button")

        self.storage_actions.addWidget(self.reload_button)

        self.backup_button = QPushButton(self.central_widget)
        self.backup_button.setObjectName(u"backup_button")

        self.storage_actions.addWidget(self.backup_button)

        self.restore_button = QPushButton(self.central_widget)
        self.restore_button.setObjectName(u"restore_button")

        self.storage_actions.addWidget(self.restore_button)

        self.storage_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.storage_actions.addItem(self.storage_stretch)

        self.preview_button = QPushButton(self.central_widget)
        self.preview_button.setObjectName(u"preview_button")

        self.storage_actions.addWidget(self.preview_button)

        self.apply_button = QPushButton(self.central_widget)
        self.apply_button.setObjectName(u"apply_button")

        self.storage_actions.addWidget(self.apply_button)


        self.main_layout.addLayout(self.storage_actions)

        self.notice = QLabel(self.central_widget)
        self.notice.setObjectName(u"notice")
        self.notice.setWordWrap(True)
        font1 = QFont()
        font1.setPointSize(8)
        self.notice.setFont(font1)

        self.main_layout.addWidget(self.notice)

        self.main_layout.setStretch(3, 1)
        RemapWindow.setCentralWidget(self.central_widget)

        self.retranslateUi(RemapWindow)

        QMetaObject.connectSlotsByName(RemapWindow)
    # setupUi

    def retranslateUi(self, RemapWindow):
        RemapWindow.setWindowTitle(QCoreApplication.translate("RemapWindow", u"Keyboard Remapper", None))
        self.title.setText(QCoreApplication.translate("RemapWindow", u"Keyboard Remapper", None))
        self.info.setText(QCoreApplication.translate("RemapWindow", u"Windows registry mappings - all users and keyboards - restart required after writing", None))
        ___qtablewidgetitem = self.table.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("RemapWindow", u"Original key / scan code", None));
        ___qtablewidgetitem1 = self.table.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("RemapWindow", u"Replacement key / scan code", None));
        ___qtablewidgetitem2 = self.table.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("RemapWindow", u"Draft status", None));
#if QT_CONFIG(tooltip)
        self.table.setToolTip(QCoreApplication.translate("RemapWindow", u"Drag a row above or below another row to change the stored order.", None))
#endif // QT_CONFIG(tooltip)
        self.hex_toggle.setText(QCoreApplication.translate("RemapWindow", u"Final hexadecimal view (draft)", None))
        self.copy_hex_button.setText(QCoreApplication.translate("RemapWindow", u"Copy hex bytes", None))
        self.add_button.setText(QCoreApplication.translate("RemapWindow", u"Add...", None))
        self.edit_button.setText(QCoreApplication.translate("RemapWindow", u"Edit...", None))
        self.remove_button.setText(QCoreApplication.translate("RemapWindow", u"Remove", None))
        self.clear_button.setText(QCoreApplication.translate("RemapWindow", u"Clear all mappings", None))
        self.reload_button.setText(QCoreApplication.translate("RemapWindow", u"Reload registry", None))
        self.backup_button.setText(QCoreApplication.translate("RemapWindow", u"Back up saved state...", None))
        self.restore_button.setText(QCoreApplication.translate("RemapWindow", u"Load backup into draft...", None))
        self.preview_button.setText(QCoreApplication.translate("RemapWindow", u"Review changes...", None))
        self.apply_button.setText(QCoreApplication.translate("RemapWindow", u"Write to registry...", None))
        self.notice.setText(QCoreApplication.translate("RemapWindow", u"Only for legitimate keyboard testing, custom hotkeys and authorized automation. Capture listens only in the visible capture window; no background logging. Do not use for covert surveillance, credential collection or unauthorized activity.", None))
    # retranslateUi

