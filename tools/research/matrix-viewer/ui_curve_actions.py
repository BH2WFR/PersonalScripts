# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'curve_actions.ui'
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

class Ui_CurveActions(object):
    def setupUi(self, CurveActions):
        if not CurveActions.objectName():
            CurveActions.setObjectName(u"CurveActions")
        self.actions_layout = QHBoxLayout(CurveActions)
        self.actions_layout.setSpacing(2)
        self.actions_layout.setObjectName(u"actions_layout")
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.extrema_button = QPushButton(CurveActions)
        self.extrema_button.setObjectName(u"extrema_button")
        font = QFont()
        font.setBold(True)
        self.extrema_button.setFont(font)

        self.actions_layout.addWidget(self.extrema_button)

        self.verticalseparator_inline = VerticalSeparator(CurveActions)
        self.verticalseparator_inline.setObjectName(u"verticalseparator_inline")

        self.actions_layout.addWidget(self.verticalseparator_inline)

        self.y_lock_button = QPushButton(CurveActions)
        self.y_lock_button.setObjectName(u"y_lock_button")

        self.actions_layout.addWidget(self.y_lock_button)

        self.fit = QPushButton(CurveActions)
        self.fit.setObjectName(u"fit")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.fit.sizePolicy().hasHeightForWidth())
        self.fit.setSizePolicy(sizePolicy)

        self.actions_layout.addWidget(self.fit)

        self.settings_button = QPushButton(CurveActions)
        self.settings_button.setObjectName(u"settings_button")
        sizePolicy.setHeightForWidth(self.settings_button.sizePolicy().hasHeightForWidth())
        self.settings_button.setSizePolicy(sizePolicy)

        self.actions_layout.addWidget(self.settings_button)


        self.retranslateUi(CurveActions)

        QMetaObject.connectSlotsByName(CurveActions)
    # setupUi

    def retranslateUi(self, CurveActions):
        self.extrema_button.setText(QCoreApplication.translate("CurveActions", u"Calculate extrema", None))
        self.y_lock_button.setText(QCoreApplication.translate("CurveActions", u"Lock Y range", None))
        self.fit.setText(QCoreApplication.translate("CurveActions", u"Fit curve", None))
        self.settings_button.setText(QCoreApplication.translate("CurveActions", u"View settings\u2026", None))
#if QT_CONFIG(tooltip)
        self.settings_button.setToolTip(QCoreApplication.translate("CurveActions", u"Signal / derivative style, colors and value markers.", None))
#endif // QT_CONFIG(tooltip)
        pass
    # retranslateUi

