# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'overlay_colors.ui'
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
from PySide6.QtWidgets import (QApplication, QFormLayout, QGroupBox, QLabel,
    QPushButton, QSizePolicy, QWidget)

from utils.qt_widgets import NoWheelDoubleSpinBox

class Ui_OverlayColors(object):
    def setupUi(self, OverlayColors):
        if not OverlayColors.objectName():
            OverlayColors.setObjectName(u"OverlayColors")
        self.colors = QFormLayout(OverlayColors)
        self.colors.setObjectName(u"colors")
        self.color_label = QLabel(OverlayColors)
        self.color_label.setObjectName(u"color_label")

        self.colors.setWidget(0, QFormLayout.LabelRole, self.color_label)

        self.layer_color = QPushButton(OverlayColors)
        self.layer_color.setObjectName(u"layer_color")

        self.colors.setWidget(0, QFormLayout.FieldRole, self.layer_color)

        self.field_2d_3d_opacity_label = QLabel(OverlayColors)
        self.field_2d_3d_opacity_label.setObjectName(u"field_2d_3d_opacity_label")

        self.colors.setWidget(1, QFormLayout.LabelRole, self.field_2d_3d_opacity_label)

        self.layer_opacity = NoWheelDoubleSpinBox(OverlayColors)
        self.layer_opacity.setObjectName(u"layer_opacity")

        self.colors.setWidget(1, QFormLayout.FieldRole, self.layer_opacity)

        self.color_note = QLabel(OverlayColors)
        self.color_note.setObjectName(u"color_note")
        self.color_note.setWordWrap(True)

        self.colors.setWidget(2, QFormLayout.SpanningRole, self.color_note)

#if QT_CONFIG(shortcut)
        self.color_label.setBuddy(self.layer_color)
        self.field_2d_3d_opacity_label.setBuddy(self.layer_opacity)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(OverlayColors)

        QMetaObject.connectSlotsByName(OverlayColors)
    # setupUi

    def retranslateUi(self, OverlayColors):
        OverlayColors.setTitle(QCoreApplication.translate("OverlayColors", u"Overlay colors (active channel)", None))
        self.color_label.setText(QCoreApplication.translate("OverlayColors", u"Color", None))
        self.layer_color.setText(QCoreApplication.translate("OverlayColors", u"Solid color\u2026", None))
        self.field_2d_3d_opacity_label.setText(QCoreApplication.translate("OverlayColors", u"2D / 3D opacity", None))
        self.color_note.setText(QCoreApplication.translate("OverlayColors", u"Overlays use one solid color per channel. In 2D, values also control opacity.", None))
    # retranslateUi

