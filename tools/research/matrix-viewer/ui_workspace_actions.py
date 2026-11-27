# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'workspace_actions.ui'
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
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QPushButton, QSizePolicy,
    QWidget)

from .qt_widgets import VerticalSeparator

class Ui_WorkspaceActions(object):
    def setupUi(self, WorkspaceActions):
        if not WorkspaceActions.objectName():
            WorkspaceActions.setObjectName(u"WorkspaceActions")
        self.tab_actions_layout = QHBoxLayout(WorkspaceActions)
        self.tab_actions_layout.setSpacing(2)
        self.tab_actions_layout.setObjectName(u"tab_actions_layout")
        self.tab_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.extrema_button = QPushButton(WorkspaceActions)
        self.extrema_button.setObjectName(u"extrema_button")
        font = QFont()
        font.setBold(True)
        self.extrema_button.setFont(font)

        self.tab_actions_layout.addWidget(self.extrema_button)

        self.tab_actions_separator = VerticalSeparator(WorkspaceActions)
        self.tab_actions_separator.setObjectName(u"tab_actions_separator")

        self.tab_actions_layout.addWidget(self.tab_actions_separator)

        self.color_lock_button = QPushButton(WorkspaceActions)
        self.color_lock_button.setObjectName(u"color_lock_button")
        self.color_lock_button.setCheckable(True)

        self.tab_actions_layout.addWidget(self.color_lock_button)

        self.profile_y_lock_button = QPushButton(WorkspaceActions)
        self.profile_y_lock_button.setObjectName(u"profile_y_lock_button")

        self.tab_actions_layout.addWidget(self.profile_y_lock_button)

        self.profile_fit_button = QPushButton(WorkspaceActions)
        self.profile_fit_button.setObjectName(u"profile_fit_button")

        self.tab_actions_layout.addWidget(self.profile_fit_button)

        self.spatial_fit_button = QPushButton(WorkspaceActions)
        self.spatial_fit_button.setObjectName(u"spatial_fit_button")

        self.tab_actions_layout.addWidget(self.spatial_fit_button)

        self.view_settings_button = QPushButton(WorkspaceActions)
        self.view_settings_button.setObjectName(u"view_settings_button")

        self.tab_actions_layout.addWidget(self.view_settings_button)


        self.retranslateUi(WorkspaceActions)

        QMetaObject.connectSlotsByName(WorkspaceActions)
    # setupUi

    def retranslateUi(self, WorkspaceActions):
        self.extrema_button.setText(QCoreApplication.translate("WorkspaceActions", u"Calculate extrema", None))
        self.color_lock_button.setText(QCoreApplication.translate("WorkspaceActions", u"Lock color range", None))
        self.profile_y_lock_button.setText(QCoreApplication.translate("WorkspaceActions", u"Lock Y range", None))
        self.profile_fit_button.setText(QCoreApplication.translate("WorkspaceActions", u"Fit curve", None))
        self.spatial_fit_button.setText(QCoreApplication.translate("WorkspaceActions", u"Fit view", None))
        self.view_settings_button.setText(QCoreApplication.translate("WorkspaceActions", u"View settings\u2026", None))
        pass
    # retranslateUi

