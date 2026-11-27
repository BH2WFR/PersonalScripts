# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'data_conversion_dialog.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QDialog,
    QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QSizePolicy, QVBoxLayout, QWidget)

from utils.qt_widgets import NoWheelComboBox

class Ui_DataConversionDialog(object):
    def setupUi(self, DataConversionDialog):
        if not DataConversionDialog.objectName():
            DataConversionDialog.setObjectName(u"DataConversionDialog")
        DataConversionDialog.resize(650, 530)
        self.form_layout = QVBoxLayout(DataConversionDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.form_source = QLabel(DataConversionDialog)
        self.form_source.setObjectName(u"form_source")
        self.form_source.setWordWrap(True)

        self.form_layout.addWidget(self.form_source)

        self.settings = QWidget(DataConversionDialog)
        self.settings.setObjectName(u"settings")
        self.form = QFormLayout(self.settings)
        self.form.setObjectName(u"form")
        self.form_operation_2_label = QLabel(self.settings)
        self.form_operation_2_label.setObjectName(u"form_operation_2_label")

        self.form.setWidget(0, QFormLayout.LabelRole, self.form_operation_2_label)

        self.operation = NoWheelComboBox(self.settings)
        self.operation.setObjectName(u"operation")

        self.form.setWidget(0, QFormLayout.FieldRole, self.operation)

        self.form_input_range_label = QLabel(self.settings)
        self.form_input_range_label.setObjectName(u"form_input_range_label")

        self.form.setWidget(1, QFormLayout.LabelRole, self.form_input_range_label)

        self.range_selector = NoWheelComboBox(self.settings)
        self.range_selector.setObjectName(u"range_selector")

        self.form.setWidget(1, QFormLayout.FieldRole, self.range_selector)

        self.full_complex = QCheckBox(self.settings)
        self.full_complex.setObjectName(u"full_complex")

        self.form.setWidget(2, QFormLayout.SpanningRole, self.full_complex)

        self.bounds = QCheckBox(self.settings)
        self.bounds.setObjectName(u"bounds")

        self.form.setWidget(3, QFormLayout.SpanningRole, self.bounds)

        self.form_db_reference_label = QLabel(self.settings)
        self.form_db_reference_label.setObjectName(u"form_db_reference_label")

        self.form.setWidget(4, QFormLayout.LabelRole, self.form_db_reference_label)

        self.reference_mode = NoWheelComboBox(self.settings)
        self.reference_mode.setObjectName(u"reference_mode")

        self.form.setWidget(4, QFormLayout.FieldRole, self.reference_mode)

        self.form_reference_value_label = QLabel(self.settings)
        self.form_reference_value_label.setObjectName(u"form_reference_value_label")

        self.form.setWidget(5, QFormLayout.LabelRole, self.form_reference_value_label)

        self.reference = QLineEdit(self.settings)
        self.reference.setObjectName(u"reference")

        self.form.setWidget(5, QFormLayout.FieldRole, self.reference)

        self.use_floor = QCheckBox(self.settings)
        self.use_floor.setObjectName(u"use_floor")

        self.form.setWidget(6, QFormLayout.SpanningRole, self.use_floor)

        self.form_db_floor_label = QLabel(self.settings)
        self.form_db_floor_label.setObjectName(u"form_db_floor_label")

        self.form.setWidget(7, QFormLayout.LabelRole, self.form_db_floor_label)

        self.floor = QLineEdit(self.settings)
        self.floor.setObjectName(u"floor")

        self.form.setWidget(7, QFormLayout.FieldRole, self.floor)

        self.form_scale_label = QLabel(self.settings)
        self.form_scale_label.setObjectName(u"form_scale_label")

        self.form.setWidget(8, QFormLayout.LabelRole, self.form_scale_label)

        self.gain = QLineEdit(self.settings)
        self.gain.setObjectName(u"gain")

        self.form.setWidget(8, QFormLayout.FieldRole, self.gain)

        self.form_offset_2_label = QLabel(self.settings)
        self.form_offset_2_label.setObjectName(u"form_offset_2_label")

        self.form.setWidget(9, QFormLayout.LabelRole, self.form_offset_2_label)

        self.offset = QLineEdit(self.settings)
        self.offset.setObjectName(u"offset")

        self.form.setWidget(9, QFormLayout.FieldRole, self.offset)

        self.form_result_name_2_label = QLabel(self.settings)
        self.form_result_name_2_label.setObjectName(u"form_result_name_2_label")

        self.form.setWidget(10, QFormLayout.LabelRole, self.form_result_name_2_label)

        self.result_name = QLineEdit(self.settings)
        self.result_name.setObjectName(u"result_name")

        self.form.setWidget(10, QFormLayout.FieldRole, self.result_name)


        self.form_layout.addWidget(self.settings)

        self.formula = QLabel(DataConversionDialog)
        self.formula.setObjectName(u"formula")
        self.formula.setWordWrap(True)

        self.form_layout.addWidget(self.formula)

        self.form_note = QLabel(DataConversionDialog)
        self.form_note.setObjectName(u"form_note")
        self.form_note.setWordWrap(True)

        self.form_layout.addWidget(self.form_note)

        self.buttons = QDialogButtonBox(DataConversionDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.Cancel)

        self.form_layout.addWidget(self.buttons)

#if QT_CONFIG(shortcut)
        self.form_operation_2_label.setBuddy(self.operation)
        self.form_input_range_label.setBuddy(self.range_selector)
        self.form_db_reference_label.setBuddy(self.reference_mode)
        self.form_reference_value_label.setBuddy(self.reference)
        self.form_db_floor_label.setBuddy(self.floor)
        self.form_scale_label.setBuddy(self.gain)
        self.form_offset_2_label.setBuddy(self.offset)
        self.form_result_name_2_label.setBuddy(self.result_name)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(DataConversionDialog)

        QMetaObject.connectSlotsByName(DataConversionDialog)
    # setupUi

    def retranslateUi(self, DataConversionDialog):
        DataConversionDialog.setWindowTitle(QCoreApplication.translate("DataConversionDialog", u"Data conversion", None))
        self.form_operation_2_label.setText(QCoreApplication.translate("DataConversionDialog", u"Operation", None))
        self.form_input_range_label.setText(QCoreApplication.translate("DataConversionDialog", u"Input range", None))
        self.full_complex.setText(QCoreApplication.translate("DataConversionDialog", u"Use full complex values (instead of selected component)", None))
#if QT_CONFIG(tooltip)
        self.full_complex.setToolTip(QCoreApplication.translate("DataConversionDialog", u"Full complex input offers amplitude dB, magnitude and scale/offset. Uncheck to convert the displayed real channel.", None))
#endif // QT_CONFIG(tooltip)
        self.bounds.setText(QCoreApplication.translate("DataConversionDialog", u"Apply current value bounds before conversion", None))
        self.form_db_reference_label.setText(QCoreApplication.translate("DataConversionDialog", u"dB reference", None))
        self.form_reference_value_label.setText(QCoreApplication.translate("DataConversionDialog", u"Reference value", None))
        self.reference.setText(QCoreApplication.translate("DataConversionDialog", u"1", None))
#if QT_CONFIG(tooltip)
        self.reference.setToolTip(QCoreApplication.translate("DataConversionDialog", u"Reference amplitude or power in the same units as the input; must be positive.", None))
#endif // QT_CONFIG(tooltip)
        self.use_floor.setText(QCoreApplication.translate("DataConversionDialog", u"Clamp dB output below this floor", None))
        self.form_db_floor_label.setText(QCoreApplication.translate("DataConversionDialog", u"dB floor", None))
        self.form_scale_label.setText(QCoreApplication.translate("DataConversionDialog", u"Scale", None))
        self.gain.setText(QCoreApplication.translate("DataConversionDialog", u"1", None))
        self.form_offset_2_label.setText(QCoreApplication.translate("DataConversionDialog", u"Offset", None))
        self.offset.setText(QCoreApplication.translate("DataConversionDialog", u"0", None))
        self.form_result_name_2_label.setText(QCoreApplication.translate("DataConversionDialog", u"Result name", None))
        self.result_name.setPlaceholderText(QCoreApplication.translate("DataConversionDialog", u"Automatic: source \u00b7 channel \u00b7 operation", None))
        self.form_note.setText(QCoreApplication.translate("DataConversionDialog", u"Creates a new matrix. Original arrays are unchanged. XY converts Y only; point clouds convert Z only. Source coordinates, repeated X values and record order are preserved. Color composites use grayscale height. NaN / Inf and undefined results remain gaps. Peak dB uses the selected range after optional value bounds; all-zero input uses reference 1. Transformed values can be exported through the Export group.", None))
    # retranslateUi

