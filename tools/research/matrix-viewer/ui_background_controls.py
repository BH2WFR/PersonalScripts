# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'background_controls.ui'
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
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QSizePolicy,
    QSpacerItem, QWidget)

from utils.qt_widgets import NoWheelComboBox

class Ui_BackgroundControls(object):
    def setupUi(self, BackgroundControls):
        if not BackgroundControls.objectName():
            BackgroundControls.setObjectName(u"BackgroundControls")
        self.background = QHBoxLayout(BackgroundControls)
        self.background.setObjectName(u"background")
        self.background_all_views_inline = QLabel(BackgroundControls)
        self.background_all_views_inline.setObjectName(u"background_all_views_inline")

        self.background.addWidget(self.background_all_views_inline)

        self.theme = NoWheelComboBox(BackgroundControls)
        self.theme.setObjectName(u"theme")

        self.background.addWidget(self.theme)

        self.background_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.background.addItem(self.background_spacer)


        self.retranslateUi(BackgroundControls)

        QMetaObject.connectSlotsByName(BackgroundControls)
    # setupUi

    def retranslateUi(self, BackgroundControls):
        self.background_all_views_inline.setText(QCoreApplication.translate("BackgroundControls", u"Background (all views)", None))
        pass
    # retranslateUi

