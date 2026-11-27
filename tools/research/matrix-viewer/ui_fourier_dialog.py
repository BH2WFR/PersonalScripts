# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'fourier_dialog.ui'
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
    QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelSpinBox)

class Ui_FourierDialog(object):
    def setupUi(self, FourierDialog):
        if not FourierDialog.objectName():
            FourierDialog.setObjectName(u"FourierDialog")
        FourierDialog.resize(650, 710)
        self.form_layout = QVBoxLayout(FourierDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.form_source = QLabel(FourierDialog)
        self.form_source.setObjectName(u"form_source")
        self.form_source.setWordWrap(True)

        self.form_layout.addWidget(self.form_source)

        self.settings = QWidget(FourierDialog)
        self.settings.setObjectName(u"settings")
        self.form_form = QFormLayout(self.settings)
        self.form_form.setObjectName(u"form_form")
        self.form_operation_label = QLabel(self.settings)
        self.form_operation_label.setObjectName(u"form_operation_label")

        self.form_form.setWidget(0, QFormLayout.LabelRole, self.form_operation_label)

        self.direction = NoWheelComboBox(self.settings)
        self.direction.setObjectName(u"direction")

        self.form_form.setWidget(0, QFormLayout.FieldRole, self.direction)

        self.form_input_range_label = QLabel(self.settings)
        self.form_input_range_label.setObjectName(u"form_input_range_label")

        self.form_form.setWidget(1, QFormLayout.LabelRole, self.form_input_range_label)

        self.range = NoWheelComboBox(self.settings)
        self.range.setObjectName(u"range")

        self.form_form.setWidget(1, QFormLayout.FieldRole, self.range)

        self.form_numeric_image_channel_label = QLabel(self.settings)
        self.form_numeric_image_channel_label.setObjectName(u"form_numeric_image_channel_label")

        self.form_form.setWidget(2, QFormLayout.LabelRole, self.form_numeric_image_channel_label)

        self.channel = NoWheelComboBox(self.settings)
        self.channel.setObjectName(u"channel")

        self.form_form.setWidget(2, QFormLayout.FieldRole, self.channel)

        self.form_complex_input_label = QLabel(self.settings)
        self.form_complex_input_label.setObjectName(u"form_complex_input_label")

        self.form_form.setWidget(3, QFormLayout.LabelRole, self.form_complex_input_label)

        self.component = NoWheelComboBox(self.settings)
        self.component.setObjectName(u"component")

        self.form_form.setWidget(3, QFormLayout.FieldRole, self.component)

        self.form_transform_axes_label = QLabel(self.settings)
        self.form_transform_axes_label.setObjectName(u"form_transform_axes_label")

        self.form_form.setWidget(4, QFormLayout.LabelRole, self.form_transform_axes_label)

        self.axes = NoWheelComboBox(self.settings)
        self.axes.setObjectName(u"axes")

        self.form_form.setWidget(4, QFormLayout.FieldRole, self.axes)

        self.first_axis_label = QLabel(self.settings)
        self.first_axis_label.setObjectName(u"first_axis_label")

        self.form_form.setWidget(5, QFormLayout.LabelRole, self.first_axis_label)

        self.first_fields = QWidget(self.settings)
        self.first_fields.setObjectName(u"first_fields")
        self.first_axis_layout = QHBoxLayout(self.first_fields)
        self.first_axis_layout.setObjectName(u"first_axis_layout")
        self.first_axis_layout.setContentsMargins(0, 0, 0, 0)
        self.first_spacing_label = QLabel(self.first_fields)
        self.first_spacing_label.setObjectName(u"first_spacing_label")

        self.first_axis_layout.addWidget(self.first_spacing_label)

        self.first_spacing = QLineEdit(self.first_fields)
        self.first_spacing.setObjectName(u"first_spacing")
        self.first_spacing.setMaximumSize(QSize(110, 16777215))

        self.first_axis_layout.addWidget(self.first_spacing)

        self.first_unit_label = QLabel(self.first_fields)
        self.first_unit_label.setObjectName(u"first_unit_label")

        self.first_axis_layout.addWidget(self.first_unit_label)

        self.first_unit = QLineEdit(self.first_fields)
        self.first_unit.setObjectName(u"first_unit")
        self.first_unit.setMaximumSize(QSize(90, 16777215))

        self.first_axis_layout.addWidget(self.first_unit)

        self.first_size_label = QLabel(self.first_fields)
        self.first_size_label.setObjectName(u"first_size_label")

        self.first_axis_layout.addWidget(self.first_size_label)

        self.first_size = NoWheelSpinBox(self.first_fields)
        self.first_size.setObjectName(u"first_size")

        self.first_axis_layout.addWidget(self.first_size)


        self.form_form.setWidget(5, QFormLayout.FieldRole, self.first_fields)

        self.second_axis_label = QLabel(self.settings)
        self.second_axis_label.setObjectName(u"second_axis_label")

        self.form_form.setWidget(6, QFormLayout.LabelRole, self.second_axis_label)

        self.second_fields = QWidget(self.settings)
        self.second_fields.setObjectName(u"second_fields")
        self.second_axis_layout = QHBoxLayout(self.second_fields)
        self.second_axis_layout.setObjectName(u"second_axis_layout")
        self.second_axis_layout.setContentsMargins(0, 0, 0, 0)
        self.second_spacing_label = QLabel(self.second_fields)
        self.second_spacing_label.setObjectName(u"second_spacing_label")

        self.second_axis_layout.addWidget(self.second_spacing_label)

        self.second_spacing = QLineEdit(self.second_fields)
        self.second_spacing.setObjectName(u"second_spacing")
        self.second_spacing.setMaximumSize(QSize(110, 16777215))

        self.second_axis_layout.addWidget(self.second_spacing)

        self.second_unit_label = QLabel(self.second_fields)
        self.second_unit_label.setObjectName(u"second_unit_label")

        self.second_axis_layout.addWidget(self.second_unit_label)

        self.second_unit = QLineEdit(self.second_fields)
        self.second_unit.setObjectName(u"second_unit")
        self.second_unit.setMaximumSize(QSize(90, 16777215))

        self.second_axis_layout.addWidget(self.second_unit)

        self.second_size_label = QLabel(self.second_fields)
        self.second_size_label.setObjectName(u"second_size_label")

        self.second_axis_layout.addWidget(self.second_size_label)

        self.second_size = NoWheelSpinBox(self.second_fields)
        self.second_size.setObjectName(u"second_size")

        self.second_axis_layout.addWidget(self.second_size)


        self.form_form.setWidget(6, QFormLayout.FieldRole, self.second_fields)

        self.form_normalization_label = QLabel(self.settings)
        self.form_normalization_label.setObjectName(u"form_normalization_label")

        self.form_form.setWidget(7, QFormLayout.LabelRole, self.form_normalization_label)

        self.norm = NoWheelComboBox(self.settings)
        self.norm.setObjectName(u"norm")

        self.form_form.setWidget(7, QFormLayout.FieldRole, self.norm)

        self.centered = QCheckBox(self.settings)
        self.centered.setObjectName(u"centered")

        self.form_form.setWidget(8, QFormLayout.SpanningRole, self.centered)

        self.mean = QCheckBox(self.settings)
        self.mean.setObjectName(u"mean")

        self.form_form.setWidget(9, QFormLayout.SpanningRole, self.mean)

        self.form_window_label = QLabel(self.settings)
        self.form_window_label.setObjectName(u"form_window_label")

        self.form_form.setWidget(10, QFormLayout.LabelRole, self.form_window_label)

        self.window_selector = NoWheelComboBox(self.settings)
        self.window_selector.setObjectName(u"window_selector")

        self.form_form.setWidget(10, QFormLayout.FieldRole, self.window_selector)

        self.form_value_bounds_label = QLabel(self.settings)
        self.form_value_bounds_label.setObjectName(u"form_value_bounds_label")

        self.form_form.setWidget(11, QFormLayout.LabelRole, self.form_value_bounds_label)

        self.bounds = QLabel(self.settings)
        self.bounds.setObjectName(u"bounds")
        self.bounds.setWordWrap(True)

        self.form_form.setWidget(11, QFormLayout.FieldRole, self.bounds)

        self.form_treatment_box = QGroupBox(self.settings)
        self.form_treatment_box.setObjectName(u"form_treatment_box")
        self.treatment_form = QFormLayout(self.form_treatment_box)
        self.treatment_form.setObjectName(u"treatment_form")
        self.nan_replacement_label = QLabel(self.form_treatment_box)
        self.nan_replacement_label.setObjectName(u"nan_replacement_label")

        self.treatment_form.setWidget(0, QFormLayout.LabelRole, self.nan_replacement_label)

        self.nan_replacement = NoWheelComboBox(self.form_treatment_box)
        self.nan_replacement.setObjectName(u"nan_replacement")

        self.treatment_form.setWidget(0, QFormLayout.FieldRole, self.nan_replacement)

        self.positive_replacement_label = QLabel(self.form_treatment_box)
        self.positive_replacement_label.setObjectName(u"positive_replacement_label")

        self.treatment_form.setWidget(1, QFormLayout.LabelRole, self.positive_replacement_label)

        self.positive_replacement = NoWheelComboBox(self.form_treatment_box)
        self.positive_replacement.setObjectName(u"positive_replacement")

        self.treatment_form.setWidget(1, QFormLayout.FieldRole, self.positive_replacement)

        self.negative_replacement_label = QLabel(self.form_treatment_box)
        self.negative_replacement_label.setObjectName(u"negative_replacement_label")

        self.treatment_form.setWidget(2, QFormLayout.LabelRole, self.negative_replacement_label)

        self.negative_replacement = NoWheelComboBox(self.form_treatment_box)
        self.negative_replacement.setObjectName(u"negative_replacement")

        self.treatment_form.setWidget(2, QFormLayout.FieldRole, self.negative_replacement)

        self.clipped_replacement_label = QLabel(self.form_treatment_box)
        self.clipped_replacement_label.setObjectName(u"clipped_replacement_label")

        self.treatment_form.setWidget(3, QFormLayout.LabelRole, self.clipped_replacement_label)

        self.clipped_replacement = NoWheelComboBox(self.form_treatment_box)
        self.clipped_replacement.setObjectName(u"clipped_replacement")

        self.treatment_form.setWidget(3, QFormLayout.FieldRole, self.clipped_replacement)

        self.treatment_note = QLabel(self.form_treatment_box)
        self.treatment_note.setObjectName(u"treatment_note")
        self.treatment_note.setWordWrap(True)

        self.treatment_form.setWidget(4, QFormLayout.SpanningRole, self.treatment_note)


        self.form_form.setWidget(12, QFormLayout.SpanningRole, self.form_treatment_box)

        self.single = QCheckBox(self.settings)
        self.single.setObjectName(u"single")

        self.form_form.setWidget(13, QFormLayout.SpanningRole, self.single)

        self.trim = QCheckBox(self.settings)
        self.trim.setObjectName(u"trim")

        self.form_form.setWidget(14, QFormLayout.SpanningRole, self.trim)

        self.form_result_name_label = QLabel(self.settings)
        self.form_result_name_label.setObjectName(u"form_result_name_label")

        self.form_form.setWidget(15, QFormLayout.LabelRole, self.form_result_name_label)

        self.name = QLineEdit(self.settings)
        self.name.setObjectName(u"name")

        self.form_form.setWidget(15, QFormLayout.FieldRole, self.name)


        self.form_layout.addWidget(self.settings)

        self.note = QLabel(FourierDialog)
        self.note.setObjectName(u"note")
        self.note.setWordWrap(True)

        self.form_layout.addWidget(self.note)

        self.estimate = QLabel(FourierDialog)
        self.estimate.setObjectName(u"estimate")
        self.estimate.setWordWrap(True)

        self.form_layout.addWidget(self.estimate)

        self.layout_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.form_layout.addItem(self.layout_spacer)

        self.buttons = QDialogButtonBox(FourierDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.Cancel)

        self.form_layout.addWidget(self.buttons)

#if QT_CONFIG(shortcut)
        self.form_operation_label.setBuddy(self.direction)
        self.form_input_range_label.setBuddy(self.range)
        self.form_numeric_image_channel_label.setBuddy(self.channel)
        self.form_complex_input_label.setBuddy(self.component)
        self.form_transform_axes_label.setBuddy(self.axes)
        self.first_axis_label.setBuddy(self.first_fields)
        self.second_axis_label.setBuddy(self.second_fields)
        self.form_normalization_label.setBuddy(self.norm)
        self.form_window_label.setBuddy(self.window_selector)
        self.form_value_bounds_label.setBuddy(self.bounds)
        self.nan_replacement_label.setBuddy(self.nan_replacement)
        self.positive_replacement_label.setBuddy(self.positive_replacement)
        self.negative_replacement_label.setBuddy(self.negative_replacement)
        self.clipped_replacement_label.setBuddy(self.clipped_replacement)
        self.form_result_name_label.setBuddy(self.name)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(FourierDialog)

        QMetaObject.connectSlotsByName(FourierDialog)
    # setupUi

    def retranslateUi(self, FourierDialog):
        FourierDialog.setWindowTitle(QCoreApplication.translate("FourierDialog", u"Fourier transform", None))
        self.form_operation_label.setText(QCoreApplication.translate("FourierDialog", u"Operation", None))
#if QT_CONFIG(tooltip)
        self.direction.setToolTip(QCoreApplication.translate("FourierDialog", u"IFFT is available only for complex sources and always uses both real and imaginary parts.", None))
#endif // QT_CONFIG(tooltip)
        self.form_input_range_label.setText(QCoreApplication.translate("FourierDialog", u"Input range", None))
#if QT_CONFIG(tooltip)
        self.range.setToolTip(QCoreApplication.translate("FourierDialog", u"Full scopes ignore current X/Y and value bounds. Cropped real-channel inputs use X/Y and Z bounds with the treatment below; full complex and phase inputs use X/Y only.", None))
#endif // QT_CONFIG(tooltip)
        self.form_numeric_image_channel_label.setText(QCoreApplication.translate("FourierDialog", u"Numeric image channel", None))
        self.form_complex_input_label.setText(QCoreApplication.translate("FourierDialog", u"Complex input", None))
        self.form_transform_axes_label.setText(QCoreApplication.translate("FourierDialog", u"Transform axes", None))
        self.first_axis_label.setText(QCoreApplication.translate("FourierDialog", u"Axis 1", None))
        self.first_spacing_label.setText(QCoreApplication.translate("FourierDialog", u"\u0394", None))
        self.first_spacing.setText(QCoreApplication.translate("FourierDialog", u"1", None))
#if QT_CONFIG(tooltip)
        self.first_spacing.setToolTip(QCoreApplication.translate("FourierDialog", u"Distance/time between samples. Scientific notation is accepted.", None))
#endif // QT_CONFIG(tooltip)
        self.first_unit_label.setText(QCoreApplication.translate("FourierDialog", u"Unit", None))
        self.first_unit.setText(QCoreApplication.translate("FourierDialog", u"sample", None))
        self.first_size_label.setText(QCoreApplication.translate("FourierDialog", u"Output N", None))
        self.second_axis_label.setText(QCoreApplication.translate("FourierDialog", u"Axis 2", None))
        self.second_spacing_label.setText(QCoreApplication.translate("FourierDialog", u"\u0394", None))
        self.second_spacing.setText(QCoreApplication.translate("FourierDialog", u"1", None))
#if QT_CONFIG(tooltip)
        self.second_spacing.setToolTip(QCoreApplication.translate("FourierDialog", u"Distance/time between samples. Scientific notation is accepted.", None))
#endif // QT_CONFIG(tooltip)
        self.second_unit_label.setText(QCoreApplication.translate("FourierDialog", u"Unit", None))
        self.second_unit.setText(QCoreApplication.translate("FourierDialog", u"sample", None))
        self.second_size_label.setText(QCoreApplication.translate("FourierDialog", u"Output N", None))
        self.form_normalization_label.setText(QCoreApplication.translate("FourierDialog", u"Normalization", None))
#if QT_CONFIG(tooltip)
        self.norm.setToolTip(QCoreApplication.translate("FourierDialog", u"backward: FFT unscaled, IFFT divided by N. ortho: both divided by sqrt(N). forward: FFT divided by N.", None))
#endif // QT_CONFIG(tooltip)
        self.centered.setText(QCoreApplication.translate("FourierDialog", u"Input spectrum is centered (fftshift)", None))
        self.mean.setText(QCoreApplication.translate("FourierDialog", u"Remove mean before FFT", None))
        self.form_window_label.setText(QCoreApplication.translate("FourierDialog", u"Window", None))
#if QT_CONFIG(tooltip)
        self.window_selector.setToolTip(QCoreApplication.translate("FourierDialog", u"Periodic window, separately on each transformed axis. No amplitude compensation.", None))
#endif // QT_CONFIG(tooltip)
        self.form_value_bounds_label.setText(QCoreApplication.translate("FourierDialog", u"Value bounds", None))
        self.form_treatment_box.setTitle(QCoreApplication.translate("FourierDialog", u"Special values", None))
        self.nan_replacement_label.setText(QCoreApplication.translate("FourierDialog", u"NaN", None))
        self.positive_replacement_label.setText(QCoreApplication.translate("FourierDialog", u"+Inf", None))
        self.negative_replacement_label.setText(QCoreApplication.translate("FourierDialog", u"-Inf", None))
        self.clipped_replacement_label.setText(QCoreApplication.translate("FourierDialog", u"Outside value bounds", None))
        self.single.setText(QCoreApplication.translate("FourierDialog", u"Single precision (complex64); default: complex128", None))
        self.trim.setText(QCoreApplication.translate("FourierDialog", u"After IFFT, remove padding recorded by the paired FFT", None))
        self.form_result_name_label.setText(QCoreApplication.translate("FourierDialog", u"Result name", None))
        self.name.setPlaceholderText(QCoreApplication.translate("FourierDialog", u"Automatic: source \u00b7 channel \u00b7 FFT / IFFT", None))
    # retranslateUi

