# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'curve_header.ui'
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
    QWidget)

from .profile_legend import ProfileLegend

class Ui_CurveHeader(object):
    def setupUi(self, CurveHeader):
        if not CurveHeader.objectName():
            CurveHeader.setObjectName(u"CurveHeader")
        self.bar = QHBoxLayout(CurveHeader)
        self.bar.setObjectName(u"bar")
        self.bar.setContentsMargins(2, 0, 2, 0)
        self.title = QLabel(CurveHeader)
        self.title.setObjectName(u"title")
        self.title.setMinimumSize(QSize(55, 0))
        self.title.setMaximumSize(QSize(170, 16777215))
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.title.sizePolicy().hasHeightForWidth())
        self.title.setSizePolicy(sizePolicy)
        font = QFont()
        font.setBold(True)
        self.title.setFont(font)

        self.bar.addWidget(self.title)

        self.legend_bar = ProfileLegend(CurveHeader)
        self.legend_bar.setObjectName(u"legend_bar")

        self.bar.addWidget(self.legend_bar)

        self.readout = QLabel(CurveHeader)
        self.readout.setObjectName(u"readout")
        self.readout.setAlignment(Qt.AlignRight|Qt.AlignVCenter)
        self.readout.setMinimumSize(QSize(120, 0))
        self.readout.setWordWrap(False)
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.readout.sizePolicy().hasHeightForWidth())
        self.readout.setSizePolicy(sizePolicy1)

        self.bar.addWidget(self.readout)

        self.bar.setStretch(1, 1)
        self.bar.setStretch(2, 1)

        self.retranslateUi(CurveHeader)

        QMetaObject.connectSlotsByName(CurveHeader)
    # setupUi

    def retranslateUi(self, CurveHeader):
        self.title.setText(QCoreApplication.translate("CurveHeader", u"Signal / profile", None))
        self.readout.setText(QCoreApplication.translate("CurveHeader", u"Move over the curve to inspect a sample", None))
        pass
    # retranslateUi

