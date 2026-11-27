# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'color_settings.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QFormLayout, QGroupBox,
    QLabel, QPushButton, QSizePolicy, QWidget)

from utils.qt_widgets import NoWheelComboBox

class Ui_ColorSettings(object):
    def setupUi(self, ColorSettings):
        if not ColorSettings.objectName():
            ColorSettings.setObjectName(u"ColorSettings")
        self.display = QFormLayout(ColorSettings)
        self.display.setObjectName(u"display")
        self.colormap_2_label = QLabel(ColorSettings)
        self.colormap_2_label.setObjectName(u"colormap_2_label")

        self.display.setWidget(0, QFormLayout.LabelRole, self.colormap_2_label)

        self.colormap = NoWheelComboBox(ColorSettings)
        self.colormap.setObjectName(u"colormap")

        self.display.setWidget(0, QFormLayout.FieldRole, self.colormap)

        self.color_range_lock = QCheckBox(ColorSettings)
        self.color_range_lock.setObjectName(u"color_range_lock")

        self.display.setWidget(1, QFormLayout.SpanningRole, self.color_range_lock)

        self.reset_limits = QPushButton(ColorSettings)
        self.reset_limits.setObjectName(u"reset_limits")

        self.display.setWidget(2, QFormLayout.SpanningRole, self.reset_limits)

#if QT_CONFIG(shortcut)
        self.colormap_2_label.setBuddy(self.colormap)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(ColorSettings)

        QMetaObject.connectSlotsByName(ColorSettings)
    # setupUi

    def retranslateUi(self, ColorSettings):
        ColorSettings.setTitle(QCoreApplication.translate("ColorSettings", u"Scalar colors (2D / 3D)", None))
        self.colormap_2_label.setText(QCoreApplication.translate("ColorSettings", u"Colormap", None))
        self.color_range_lock.setText(QCoreApplication.translate("ColorSettings", u"Lock color range (2D / 3D, expand only)", None))
#if QT_CONFIG(tooltip)
        self.color_range_lock.setToolTip(QCoreApplication.translate("ColorSettings", u"Shared by 2D/3D across matrix/channel switches. Minimum can only decrease; maximum can only increase. Turn off to restore each channel's own bounds; turn on again to start a new range. Original image colors and solid-color overlays do not contribute.", None))
#endif // QT_CONFIG(tooltip)
        self.reset_limits.setText(QCoreApplication.translate("ColorSettings", u"Reset color limits", None))
    # retranslateUi

