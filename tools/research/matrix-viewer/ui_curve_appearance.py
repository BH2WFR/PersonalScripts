# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'curve_appearance.ui'
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
from PySide6.QtWidgets import (QApplication, QFormLayout, QLabel, QPushButton,
    QSizePolicy, QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelDoubleSpinBox)

class Ui_CurveAppearance(object):
    def setupUi(self, CurveAppearance):
        if not CurveAppearance.objectName():
            CurveAppearance.setObjectName(u"CurveAppearance")
        self.appearance_form = QFormLayout(CurveAppearance)
        self.appearance_form.setObjectName(u"appearance_form")
        self.style_label = QLabel(CurveAppearance)
        self.style_label.setObjectName(u"style_label")

        self.appearance_form.setWidget(0, QFormLayout.LabelRole, self.style_label)

        self.style_selector = NoWheelComboBox(CurveAppearance)
        self.style_selector.setObjectName(u"style_selector")

        self.appearance_form.setWidget(0, QFormLayout.FieldRole, self.style_selector)

        self.line_style_2_label = QLabel(CurveAppearance)
        self.line_style_2_label.setObjectName(u"line_style_2_label")

        self.appearance_form.setWidget(1, QFormLayout.LabelRole, self.line_style_2_label)

        self.line_style = NoWheelComboBox(CurveAppearance)
        self.line_style.setObjectName(u"line_style")

        self.appearance_form.setWidget(1, QFormLayout.FieldRole, self.line_style)

        self.dash_scale_2_label = QLabel(CurveAppearance)
        self.dash_scale_2_label.setObjectName(u"dash_scale_2_label")

        self.appearance_form.setWidget(2, QFormLayout.LabelRole, self.dash_scale_2_label)

        self.dash_scale = NoWheelDoubleSpinBox(CurveAppearance)
        self.dash_scale.setObjectName(u"dash_scale")

        self.appearance_form.setWidget(2, QFormLayout.FieldRole, self.dash_scale)

        self.point_shape_2_label = QLabel(CurveAppearance)
        self.point_shape_2_label.setObjectName(u"point_shape_2_label")

        self.appearance_form.setWidget(3, QFormLayout.LabelRole, self.point_shape_2_label)

        self.point_shape = NoWheelComboBox(CurveAppearance)
        self.point_shape.setObjectName(u"point_shape")

        self.appearance_form.setWidget(3, QFormLayout.FieldRole, self.point_shape)

        self.line_width_2_label = QLabel(CurveAppearance)
        self.line_width_2_label.setObjectName(u"line_width_2_label")

        self.appearance_form.setWidget(4, QFormLayout.LabelRole, self.line_width_2_label)

        self.line_width = NoWheelDoubleSpinBox(CurveAppearance)
        self.line_width.setObjectName(u"line_width")

        self.appearance_form.setWidget(4, QFormLayout.FieldRole, self.line_width)

        self.point_size_2_label = QLabel(CurveAppearance)
        self.point_size_2_label.setObjectName(u"point_size_2_label")

        self.appearance_form.setWidget(5, QFormLayout.LabelRole, self.point_size_2_label)

        self.point_size = NoWheelDoubleSpinBox(CurveAppearance)
        self.point_size.setObjectName(u"point_size")

        self.appearance_form.setWidget(5, QFormLayout.FieldRole, self.point_size)

        self.color_label = QLabel(CurveAppearance)
        self.color_label.setObjectName(u"color_label")

        self.appearance_form.setWidget(6, QFormLayout.LabelRole, self.color_label)

        self.color_button = QPushButton(CurveAppearance)
        self.color_button.setObjectName(u"color_button")

        self.appearance_form.setWidget(6, QFormLayout.FieldRole, self.color_button)

#if QT_CONFIG(shortcut)
        self.style_label.setBuddy(self.style_selector)
        self.line_style_2_label.setBuddy(self.line_style)
        self.dash_scale_2_label.setBuddy(self.dash_scale)
        self.point_shape_2_label.setBuddy(self.point_shape)
        self.line_width_2_label.setBuddy(self.line_width)
        self.point_size_2_label.setBuddy(self.point_size)
        self.color_label.setBuddy(self.color_button)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(CurveAppearance)

        QMetaObject.connectSlotsByName(CurveAppearance)
    # setupUi

    def retranslateUi(self, CurveAppearance):
        self.style_label.setText(QCoreApplication.translate("CurveAppearance", u"Style", None))
        self.line_style_2_label.setText(QCoreApplication.translate("CurveAppearance", u"Line style", None))
#if QT_CONFIG(tooltip)
        self.line_style.setToolTip(QCoreApplication.translate("CurveAppearance", u"Line pattern for this signal/slice and its derivative.", None))
#endif // QT_CONFIG(tooltip)
        self.dash_scale_2_label.setText(QCoreApplication.translate("CurveAppearance", u"Dash scale", None))
#if QT_CONFIG(tooltip)
        self.dash_scale.setToolTip(QCoreApplication.translate("CurveAppearance", u"Multiply dash and gap lengths for this curve. 1\u00d7 uses the original pattern.", None))
#endif // QT_CONFIG(tooltip)
        self.point_shape_2_label.setText(QCoreApplication.translate("CurveAppearance", u"Point shape", None))
#if QT_CONFIG(tooltip)
        self.point_shape.setToolTip(QCoreApplication.translate("CurveAppearance", u"Sample symbol for Points and Line + points; also applies to the derivative.", None))
#endif // QT_CONFIG(tooltip)
        self.line_width_2_label.setText(QCoreApplication.translate("CurveAppearance", u"Line width", None))
#if QT_CONFIG(tooltip)
        self.line_width.setToolTip(QCoreApplication.translate("CurveAppearance", u"Line width for this signal/slice and its derivative. Applies to Line and Line + points.", None))
#endif // QT_CONFIG(tooltip)
        self.point_size_2_label.setText(QCoreApplication.translate("CurveAppearance", u"Point size", None))
#if QT_CONFIG(tooltip)
        self.point_size.setToolTip(QCoreApplication.translate("CurveAppearance", u"Sample diameter for this signal/slice and its derivative. Select Points or Line + points to see samples.", None))
#endif // QT_CONFIG(tooltip)
        self.color_label.setText(QCoreApplication.translate("CurveAppearance", u"Color", None))
        self.color_button.setText(QCoreApplication.translate("CurveAppearance", u"Line color", None))
        pass
    # retranslateUi

