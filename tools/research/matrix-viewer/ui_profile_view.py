# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'profile_view.ui'
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
from PySide6.QtWidgets import (QApplication, QSizePolicy, QTabWidget, QVBoxLayout,
    QWidget)

class Ui_ProfileView(object):
    def setupUi(self, ProfileView):
        if not ProfileView.objectName():
            ProfileView.setObjectName(u"ProfileView")
        self.form_layout = QVBoxLayout(ProfileView)
        self.form_layout.setObjectName(u"form_layout")
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget(ProfileView)
        self.tabs.setObjectName(u"tabs")
        self.signal_page = QWidget()
        self.signal_page.setObjectName(u"signal_page")
        self.signal_layout = QVBoxLayout(self.signal_page)
        self.signal_layout.setObjectName(u"signal_layout")
        self.signal_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs.addTab(self.signal_page, "")
        self.form_page = QWidget()
        self.form_page.setObjectName(u"form_page")
        self.form_derivative_layout = QVBoxLayout(self.form_page)
        self.form_derivative_layout.setObjectName(u"form_derivative_layout")
        self.form_derivative_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs.addTab(self.form_page, "")

        self.form_layout.addWidget(self.tabs)


        self.retranslateUi(ProfileView)

        QMetaObject.connectSlotsByName(ProfileView)
    # setupUi

    def retranslateUi(self, ProfileView):
        self.tabs.setTabText(self.tabs.indexOf(self.signal_page), QCoreApplication.translate("ProfileView", u"Signal", None))
        self.tabs.setTabText(self.tabs.indexOf(self.form_page), QCoreApplication.translate("ProfileView", u"Derivative", None))
        pass
    # retranslateUi

