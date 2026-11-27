# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'value_markers.ui'
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
    QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QWidget)

from utils.qt_widgets import NoWheelDoubleSpinBox

class Ui_ValueMarkers(object):
    def setupUi(self, ValueMarkers):
        if not ValueMarkers.objectName():
            ValueMarkers.setObjectName(u"ValueMarkers")
        self.markers = QFormLayout(ValueMarkers)
        self.markers.setObjectName(u"markers")
        self.highlight_row = QHBoxLayout()
        self.highlight_row.setObjectName(u"highlight_row")
        self.highlight_clipped = QCheckBox(ValueMarkers)
        self.highlight_clipped.setObjectName(u"highlight_clipped")

        self.highlight_row.addWidget(self.highlight_clipped)

        self.clip_color_button = QPushButton(ValueMarkers)
        self.clip_color_button.setObjectName(u"clip_color_button")

        self.highlight_row.addWidget(self.clip_color_button)


        self.markers.setLayout(0, QFormLayout.SpanningRole, self.highlight_row)

        self.show_nonfinite = QCheckBox(ValueMarkers)
        self.show_nonfinite.setObjectName(u"show_nonfinite")

        self.markers.setWidget(1, QFormLayout.SpanningRole, self.show_nonfinite)

        self.nonfinite_color_row = QWidget(ValueMarkers)
        self.nonfinite_color_row.setObjectName(u"nonfinite_color_row")
        self.nonfinite_colors = QHBoxLayout(self.nonfinite_color_row)
        self.nonfinite_colors.setObjectName(u"nonfinite_colors")
        self.nonfinite_colors.setContentsMargins(0, 0, 0, 0)

        self.markers.setWidget(2, QFormLayout.SpanningRole, self.nonfinite_color_row)

        self.field_1d_nonfinite_marker_size_label = QLabel(ValueMarkers)
        self.field_1d_nonfinite_marker_size_label.setObjectName(u"field_1d_nonfinite_marker_size_label")

        self.markers.setWidget(3, QFormLayout.LabelRole, self.field_1d_nonfinite_marker_size_label)

        self.nonfinite_size = NoWheelDoubleSpinBox(ValueMarkers)
        self.nonfinite_size.setObjectName(u"nonfinite_size")

        self.markers.setWidget(3, QFormLayout.FieldRole, self.nonfinite_size)

        self.marker_hint = QLabel(ValueMarkers)
        self.marker_hint.setObjectName(u"marker_hint")
        self.marker_hint.setWordWrap(True)

        self.markers.setWidget(4, QFormLayout.SpanningRole, self.marker_hint)

#if QT_CONFIG(shortcut)
        self.field_1d_nonfinite_marker_size_label.setBuddy(self.nonfinite_size)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(ValueMarkers)

        QMetaObject.connectSlotsByName(ValueMarkers)
    # setupUi

    def retranslateUi(self, ValueMarkers):
        ValueMarkers.setTitle(QCoreApplication.translate("ValueMarkers", u"Value markers", None))
        self.highlight_clipped.setText(QCoreApplication.translate("ValueMarkers", u"Highlight clipped values", None))
#if QT_CONFIG(tooltip)
        self.highlight_clipped.setToolTip(QCoreApplication.translate("ValueMarkers", u"Emphasize clamped samples in 1D, 2D and 3D. Turning this off keeps value clamping active.", None))
#endif // QT_CONFIG(tooltip)
        self.clip_color_button.setText(QCoreApplication.translate("ValueMarkers", u"Clipping color", None))
        self.show_nonfinite.setText(QCoreApplication.translate("ValueMarkers", u"Show Inf / -Inf / NaN markers (1D / 2D)", None))
#if QT_CONFIG(tooltip)
        self.show_nonfinite.setToolTip(QCoreApplication.translate("ValueMarkers", u"1D: Inf at the visible finite maximum, -Inf at the minimum, NaN at zero. No finite samples: use zero. 2D: color the original pixel. Source values and derivatives are unchanged.", None))
#endif // QT_CONFIG(tooltip)
        self.field_1d_nonfinite_marker_size_label.setText(QCoreApplication.translate("ValueMarkers", u"1D nonfinite marker size", None))
#if QT_CONFIG(tooltip)
        self.nonfinite_size.setToolTip(QCoreApplication.translate("ValueMarkers", u"Inf / -Inf / NaN dot diameter in 1D plots, including slices. 2D retains whole-pixel coloring.", None))
#endif // QT_CONFIG(tooltip)
        self.marker_hint.setText(QCoreApplication.translate("ValueMarkers", u"1D: Inf at the finite maximum, -Inf at the minimum, NaN at zero. 2D: color the original pixel. Derivatives exclude these samples.", None))
    # retranslateUi

