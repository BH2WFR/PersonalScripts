# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'export_controls.ui'
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

class Ui_ExportControls(object):
    def setupUi(self, ExportControls):
        if not ExportControls.objectName():
            ExportControls.setObjectName(u"ExportControls")
        self.export_form = QFormLayout(ExportControls)
        self.export_form.setObjectName(u"export_form")
        self.data_label = QLabel(ExportControls)
        self.data_label.setObjectName(u"data_label")

        self.export_form.setWidget(0, QFormLayout.LabelRole, self.data_label)

        self.export_target = NoWheelComboBox(ExportControls)
        self.export_target.setObjectName(u"export_target")

        self.export_form.setWidget(0, QFormLayout.FieldRole, self.export_target)

        self.export_xy = QCheckBox(ExportControls)
        self.export_xy.setObjectName(u"export_xy")

        self.export_form.setWidget(1, QFormLayout.SpanningRole, self.export_xy)

        self.export_z = QCheckBox(ExportControls)
        self.export_z.setObjectName(u"export_z")

        self.export_form.setWidget(2, QFormLayout.SpanningRole, self.export_z)

        self.export_complex = QCheckBox(ExportControls)
        self.export_complex.setObjectName(u"export_complex")

        self.export_form.setWidget(3, QFormLayout.SpanningRole, self.export_complex)

        self.layout_label = QLabel(ExportControls)
        self.layout_label.setObjectName(u"layout_label")

        self.export_form.setWidget(4, QFormLayout.LabelRole, self.layout_label)

        self.export_layout = NoWheelComboBox(ExportControls)
        self.export_layout.setObjectName(u"export_layout")

        self.export_form.setWidget(4, QFormLayout.FieldRole, self.export_layout)

        self.format_label = QLabel(ExportControls)
        self.format_label.setObjectName(u"format_label")

        self.export_form.setWidget(5, QFormLayout.LabelRole, self.format_label)

        self.export_format = NoWheelComboBox(ExportControls)
        self.export_format.setObjectName(u"export_format")

        self.export_form.setWidget(5, QFormLayout.FieldRole, self.export_format)

        self.export_hint = QLabel(ExportControls)
        self.export_hint.setObjectName(u"export_hint")
        self.export_hint.setWordWrap(True)

        self.export_form.setWidget(6, QFormLayout.SpanningRole, self.export_hint)

        self.export_save = QPushButton(ExportControls)
        self.export_save.setObjectName(u"export_save")

        self.export_form.setWidget(7, QFormLayout.SpanningRole, self.export_save)

#if QT_CONFIG(shortcut)
        self.data_label.setBuddy(self.export_target)
        self.layout_label.setBuddy(self.export_layout)
        self.format_label.setBuddy(self.export_format)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(ExportControls)

        QMetaObject.connectSlotsByName(ExportControls)
    # setupUi

    def retranslateUi(self, ExportControls):
        ExportControls.setTitle(QCoreApplication.translate("ExportControls", u"Export", None))
        self.data_label.setText(QCoreApplication.translate("ExportControls", u"Data", None))
        self.export_xy.setText(QCoreApplication.translate("ExportControls", u"Apply X / Y crop", None))
        self.export_z.setText(QCoreApplication.translate("ExportControls", u"Apply value bounds (Z / signal Y)", None))
        self.export_complex.setText(QCoreApplication.translate("ExportControls", u"Export complex matrix (real + imaginary)", None))
#if QT_CONFIG(tooltip)
        self.export_complex.setToolTip(QCoreApplication.translate("ExportControls", u"Checked: preserve both source components, with optional XY crop/slice. Unchecked: export only the displayed component. Ordered value bounds require a real display component.", None))
#endif // QT_CONFIG(tooltip)
        self.layout_label.setText(QCoreApplication.translate("ExportControls", u"Layout", None))
        self.format_label.setText(QCoreApplication.translate("ExportControls", u"Format", None))
        self.export_save.setText(QCoreApplication.translate("ExportControls", u"Export\u2026", None))
    # retranslateUi

