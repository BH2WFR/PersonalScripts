# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'slice_appearance.ui'
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
    QPushButton, QSizePolicy, QStackedWidget, QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox)

class Ui_SliceAppearance(object):
    def setupUi(self, SliceAppearance):
        if not SliceAppearance.objectName():
            SliceAppearance.setObjectName(u"SliceAppearance")
        self.appearance = QFormLayout(SliceAppearance)
        self.appearance.setObjectName(u"appearance")
        self.color_label = QLabel(SliceAppearance)
        self.color_label.setObjectName(u"color_label")

        self.appearance.setWidget(0, QFormLayout.LabelRole, self.color_label)

        self.profile_color_3d_button = QPushButton(SliceAppearance)
        self.profile_color_3d_button.setObjectName(u"profile_color_3d_button")

        self.appearance.setWidget(0, QFormLayout.FieldRole, self.profile_color_3d_button)

        self.style_label = QLabel(SliceAppearance)
        self.style_label.setObjectName(u"style_label")

        self.appearance.setWidget(1, QFormLayout.LabelRole, self.style_label)

        self.profile_style = NoWheelComboBox(SliceAppearance)
        self.profile_style.setObjectName(u"profile_style")

        self.appearance.setWidget(1, QFormLayout.FieldRole, self.profile_style)

        self.profile_style_options = QStackedWidget(SliceAppearance)
        self.profile_style_options.setObjectName(u"profile_style_options")
        self.profile_style_options.setMaximumSize(QSize(165, 16777215))
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.profile_style_options.sizePolicy().hasHeightForWidth())
        self.profile_style_options.setSizePolicy(sizePolicy)
        self.profile_lift = NoWheelDoubleSpinBox()
        self.profile_lift.setObjectName(u"profile_lift")
        self.profile_style_options.addWidget(self.profile_lift)
        self.profile_opacity = NoWheelSpinBox()
        self.profile_opacity.setObjectName(u"profile_opacity")
        self.profile_style_options.addWidget(self.profile_opacity)

        self.appearance.setWidget(2, QFormLayout.SpanningRole, self.profile_style_options)

#if QT_CONFIG(shortcut)
        self.color_label.setBuddy(self.profile_color_3d_button)
        self.style_label.setBuddy(self.profile_style)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(SliceAppearance)

        QMetaObject.connectSlotsByName(SliceAppearance)
    # setupUi

    def retranslateUi(self, SliceAppearance):
        SliceAppearance.setTitle(QCoreApplication.translate("SliceAppearance", u"Slice marker (all matrices)", None))
        self.color_label.setText(QCoreApplication.translate("SliceAppearance", u"Color", None))
        self.profile_color_3d_button.setText(QCoreApplication.translate("SliceAppearance", u"3D color", None))
        self.style_label.setText(QCoreApplication.translate("SliceAppearance", u"Style", None))
#if QT_CONFIG(tooltip)
        self.profile_lift.setToolTip(QCoreApplication.translate("SliceAppearance", u"Raise the 3D curve by this percentage of the visible height range. Source values stay unchanged.", None))
#endif // QT_CONFIG(tooltip)
    # retranslateUi

