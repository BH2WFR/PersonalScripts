# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'surface_settings.ui'
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
    QLabel, QSizePolicy, QSlider, QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelDoubleSpinBox)

class Ui_SurfaceSettings(object):
    def setupUi(self, SurfaceSettings):
        if not SurfaceSettings.objectName():
            SurfaceSettings.setObjectName(u"SurfaceSettings")
        self.surface = QFormLayout(SurfaceSettings)
        self.surface.setObjectName(u"surface")
        self.style_label = QLabel(SurfaceSettings)
        self.style_label.setObjectName(u"style_label")

        self.surface.setWidget(0, QFormLayout.LabelRole, self.style_label)

        self.surface_style = NoWheelComboBox(SurfaceSettings)
        self.surface_style.setObjectName(u"surface_style")

        self.surface.setWidget(0, QFormLayout.FieldRole, self.surface_style)

        self.point_size_2_label = QLabel(SurfaceSettings)
        self.point_size_2_label.setObjectName(u"point_size_2_label")

        self.surface.setWidget(1, QFormLayout.LabelRole, self.point_size_2_label)

        self.point_size = NoWheelDoubleSpinBox(SurfaceSettings)
        self.point_size.setObjectName(u"point_size")

        self.surface.setWidget(1, QFormLayout.FieldRole, self.point_size)

        self.auto_height = QCheckBox(SurfaceSettings)
        self.auto_height.setObjectName(u"auto_height")

        self.surface.setWidget(2, QFormLayout.SpanningRole, self.auto_height)

        self.matrix_height_multiplier_label = QLabel(SurfaceSettings)
        self.matrix_height_multiplier_label.setObjectName(u"matrix_height_multiplier_label")

        self.surface.setWidget(3, QFormLayout.LabelRole, self.matrix_height_multiplier_label)

        self.height_scale = NoWheelDoubleSpinBox(SurfaceSettings)
        self.height_scale.setObjectName(u"height_scale")

        self.surface.setWidget(3, QFormLayout.FieldRole, self.height_scale)

        self.height_slider = QSlider(SurfaceSettings)
        self.height_slider.setObjectName(u"height_slider")
        self.height_slider.setOrientation(Qt.Horizontal)

        self.surface.setWidget(4, QFormLayout.SpanningRole, self.height_slider)

        self.parallel = QCheckBox(SurfaceSettings)
        self.parallel.setObjectName(u"parallel")

        self.surface.setWidget(5, QFormLayout.SpanningRole, self.parallel)

#if QT_CONFIG(shortcut)
        self.style_label.setBuddy(self.surface_style)
        self.point_size_2_label.setBuddy(self.point_size)
        self.matrix_height_multiplier_label.setBuddy(self.height_scale)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(SurfaceSettings)

        QMetaObject.connectSlotsByName(SurfaceSettings)
    # setupUi

    def retranslateUi(self, SurfaceSettings):
        SurfaceSettings.setTitle(QCoreApplication.translate("SurfaceSettings", u"3D rendering", None))
        self.style_label.setText(QCoreApplication.translate("SurfaceSettings", u"Style", None))
        self.point_size_2_label.setText(QCoreApplication.translate("SurfaceSettings", u"Point size", None))
        self.auto_height.setText(QCoreApplication.translate("SurfaceSettings", u"Auto matrix height (continuous)", None))
#if QT_CONFIG(tooltip)
        self.auto_height.setToolTip(QCoreApplication.translate("SurfaceSettings", u"Recalculate this matrix's height after data changes. Scaling > Apply auto scaling fits all visible matrices once instead.", None))
#endif // QT_CONFIG(tooltip)
        self.matrix_height_multiplier_label.setText(QCoreApplication.translate("SurfaceSettings", u"Matrix height multiplier", None))
#if QT_CONFIG(tooltip)
        self.height_scale.setToolTip(QCoreApplication.translate("SurfaceSettings", u"Per-matrix height, applied before the shared X/Y/Z scene multipliers in Scaling.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.height_slider.setToolTip(QCoreApplication.translate("SurfaceSettings", u"Logarithmic height multiplier, synchronized with the numeric value.", None))
#endif // QT_CONFIG(tooltip)
        self.parallel.setText(QCoreApplication.translate("SurfaceSettings", u"Orthographic projection", None))
    # retranslateUi

