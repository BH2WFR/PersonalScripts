# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'surface_view.ui'
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

class Ui_SurfaceView(object):
    def setupUi(self, SurfaceView):
        if not SurfaceView.objectName():
            SurfaceView.setObjectName(u"SurfaceView")
        self.form_layout = QVBoxLayout(SurfaceView)
        self.form_layout.setObjectName(u"form_layout")
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_header = QHBoxLayout()
        self.form_header.setObjectName(u"form_header")
        self.readout = QLabel(SurfaceView)
        self.readout.setObjectName(u"readout")
        self.readout.setAlignment(Qt.AlignRight)
        self.readout.setWordWrap(True)

        self.form_header.addWidget(self.readout)

        self.form_header.setStretch(0, 1)

        self.form_layout.addLayout(self.form_header)

        self.form_footer = QHBoxLayout()
        self.form_footer.setObjectName(u"form_footer")
        self.resolution = QLabel(SurfaceView)
        self.resolution.setObjectName(u"resolution")
        self.resolution.setWordWrap(True)

        self.form_footer.addWidget(self.resolution)

        self.extrema_label = QLabel(SurfaceView)
        self.extrema_label.setObjectName(u"extrema_label")

        self.form_footer.addWidget(self.extrema_label)

        self.form_footer.setStretch(0, 1)

        self.form_layout.addLayout(self.form_footer)


        self.retranslateUi(SurfaceView)

        QMetaObject.connectSlotsByName(SurfaceView)
    # setupUi

    def retranslateUi(self, SurfaceView):
        self.readout.setText(QCoreApplication.translate("SurfaceView", u"Move over the surface to inspect a source sample", None))
        self.resolution.setText(QCoreApplication.translate("SurfaceView", u"3D preview: no data", None))
        pass
    # retranslateUi

