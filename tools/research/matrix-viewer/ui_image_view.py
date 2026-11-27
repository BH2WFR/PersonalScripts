# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'image_view.ui'
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
    QVBoxLayout, QWidget)

class Ui_ImageView(object):
    def setupUi(self, ImageView):
        if not ImageView.objectName():
            ImageView.setObjectName(u"ImageView")
        self.form_layout = QVBoxLayout(ImageView)
        self.form_layout.setObjectName(u"form_layout")
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_header = QHBoxLayout()
        self.form_header.setObjectName(u"form_header")
        self.readout = QLabel(ImageView)
        self.readout.setObjectName(u"readout")
        self.readout.setAlignment(Qt.AlignRight)
        self.readout.setWordWrap(True)

        self.form_header.addWidget(self.readout)

        self.form_header.setStretch(0, 1)

        self.form_layout.addLayout(self.form_header)


        self.retranslateUi(ImageView)

        QMetaObject.connectSlotsByName(ImageView)
    # setupUi

    def retranslateUi(self, ImageView):
        self.readout.setText(QCoreApplication.translate("ImageView", u"Move over the image to inspect a pixel", None))
        pass
    # retranslateUi

