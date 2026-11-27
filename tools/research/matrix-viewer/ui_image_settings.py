# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'image_settings.ui'
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
    QSizePolicy, QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelDoubleSpinBox)

class Ui_ImageSettings(object):
    def setupUi(self, ImageSettings):
        if not ImageSettings.objectName():
            ImageSettings.setObjectName(u"ImageSettings")
        self.image_form = QFormLayout(ImageSettings)
        self.image_form.setObjectName(u"image_form")
        self.style_label = QLabel(ImageSettings)
        self.style_label.setObjectName(u"style_label")

        self.image_form.setWidget(0, QFormLayout.LabelRole, self.style_label)

        self.image_style = NoWheelComboBox(ImageSettings)
        self.image_style.setObjectName(u"image_style")

        self.image_form.setWidget(0, QFormLayout.FieldRole, self.image_style)

        self.point_size_2_label = QLabel(ImageSettings)
        self.point_size_2_label.setObjectName(u"point_size_2_label")

        self.image_form.setWidget(1, QFormLayout.LabelRole, self.point_size_2_label)

        self.image_point_size = NoWheelDoubleSpinBox(ImageSettings)
        self.image_point_size.setObjectName(u"image_point_size")

        self.image_form.setWidget(1, QFormLayout.FieldRole, self.image_point_size)

#if QT_CONFIG(shortcut)
        self.style_label.setBuddy(self.image_style)
        self.point_size_2_label.setBuddy(self.image_point_size)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(ImageSettings)

        QMetaObject.connectSlotsByName(ImageSettings)
    # setupUi

    def retranslateUi(self, ImageSettings):
        ImageSettings.setTitle(QCoreApplication.translate("ImageSettings", u"2D rendering", None))
        self.style_label.setText(QCoreApplication.translate("ImageSettings", u"Style", None))
        self.point_size_2_label.setText(QCoreApplication.translate("ImageSettings", u"Point size", None))
    # retranslateUi

