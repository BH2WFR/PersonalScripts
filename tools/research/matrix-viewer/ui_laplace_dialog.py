# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'laplace_dialog.ui'
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

from utils.qt_widgets import (NoWheelComboBox, NoWheelSpinBox)

class Ui_LaplaceDialog(object):
    def setupUi(self, LaplaceDialog):
        if not LaplaceDialog.objectName():
            LaplaceDialog.setObjectName(u"LaplaceDialog")
        LaplaceDialog.resize(630, 590)
        self.form_layout = QVBoxLayout(LaplaceDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.form_source = QLabel(LaplaceDialog)
        self.form_source.setObjectName(u"form_source")
        self.form_source.setWordWrap(True)

        self.form_layout.addWidget(self.form_source)

        self.settings = QWidget(LaplaceDialog)
        self.settings.setObjectName(u"settings")
        self.form_form = QFormLayout(self.settings)
        self.form_form.setObjectName(u"form_form")
        self.row_label = QLabel(self.settings)
        self.row_label.setObjectName(u"row_label")

        self.form_form.setWidget(0, QFormLayout.LabelRole, self.row_label)

        self.row = NoWheelSpinBox(self.settings)
        self.row.setObjectName(u"row")

        self.form_form.setWidget(0, QFormLayout.FieldRole, self.row)

        self.inverse_sigma_label = QLabel(self.settings)
        self.inverse_sigma_label.setObjectName(u"inverse_sigma_label")

        self.form_form.setWidget(1, QFormLayout.LabelRole, self.inverse_sigma_label)

        self.inverse_sigma = QLineEdit(self.settings)
        self.inverse_sigma.setObjectName(u"inverse_sigma")

        self.form_form.setWidget(1, QFormLayout.FieldRole, self.inverse_sigma)

        self.omega_spacing_label = QLabel(self.settings)
        self.omega_spacing_label.setObjectName(u"omega_spacing_label")

        self.form_form.setWidget(2, QFormLayout.LabelRole, self.omega_spacing_label)

        self.omega_spacing = QLineEdit(self.settings)
        self.omega_spacing.setObjectName(u"omega_spacing")

        self.form_form.setWidget(2, QFormLayout.FieldRole, self.omega_spacing)

        self.output_count_label = QLabel(self.settings)
        self.output_count_label.setObjectName(u"output_count_label")

        self.form_form.setWidget(3, QFormLayout.LabelRole, self.output_count_label)

        self.output_count = NoWheelSpinBox(self.settings)
        self.output_count.setObjectName(u"output_count")

        self.form_form.setWidget(3, QFormLayout.FieldRole, self.output_count)

        self.origin_label = QLabel(self.settings)
        self.origin_label.setObjectName(u"origin_label")

        self.form_form.setWidget(4, QFormLayout.LabelRole, self.origin_label)

        self.origin = QLineEdit(self.settings)
        self.origin.setObjectName(u"origin")

        self.form_form.setWidget(4, QFormLayout.FieldRole, self.origin)

        self.inverse_unit_label = QLabel(self.settings)
        self.inverse_unit_label.setObjectName(u"inverse_unit_label")

        self.form_form.setWidget(5, QFormLayout.LabelRole, self.inverse_unit_label)

        self.inverse_unit = QLineEdit(self.settings)
        self.inverse_unit.setObjectName(u"inverse_unit")

        self.form_form.setWidget(5, QFormLayout.FieldRole, self.inverse_unit)

        self.centered = QCheckBox(self.settings)
        self.centered.setObjectName(u"centered")

        self.form_form.setWidget(6, QFormLayout.SpanningRole, self.centered)

        self.range_selector_label = QLabel(self.settings)
        self.range_selector_label.setObjectName(u"range_selector_label")

        self.form_form.setWidget(7, QFormLayout.LabelRole, self.range_selector_label)

        self.range_selector = NoWheelComboBox(self.settings)
        self.range_selector.setObjectName(u"range_selector")

        self.form_form.setWidget(7, QFormLayout.FieldRole, self.range_selector)

        self.spacing_label = QLabel(self.settings)
        self.spacing_label.setObjectName(u"spacing_label")

        self.form_form.setWidget(8, QFormLayout.LabelRole, self.spacing_label)

        self.spacing = QLineEdit(self.settings)
        self.spacing.setObjectName(u"spacing")

        self.form_form.setWidget(8, QFormLayout.FieldRole, self.spacing)

        self.unit_label = QLabel(self.settings)
        self.unit_label.setObjectName(u"unit_label")

        self.form_form.setWidget(9, QFormLayout.LabelRole, self.unit_label)

        self.unit = QLineEdit(self.settings)
        self.unit.setObjectName(u"unit")

        self.form_form.setWidget(9, QFormLayout.FieldRole, self.unit)

        self.auto_sigma = QCheckBox(self.settings)
        self.auto_sigma.setObjectName(u"auto_sigma")

        self.form_form.setWidget(10, QFormLayout.SpanningRole, self.auto_sigma)

        self.sigma_min_label = QLabel(self.settings)
        self.sigma_min_label.setObjectName(u"sigma_min_label")

        self.form_form.setWidget(11, QFormLayout.LabelRole, self.sigma_min_label)

        self.sigma_min = QLineEdit(self.settings)
        self.sigma_min.setObjectName(u"sigma_min")

        self.form_form.setWidget(11, QFormLayout.FieldRole, self.sigma_min)

        self.sigma_max_label = QLabel(self.settings)
        self.sigma_max_label.setObjectName(u"sigma_max_label")

        self.form_form.setWidget(12, QFormLayout.LabelRole, self.sigma_max_label)

        self.sigma_max = QLineEdit(self.settings)
        self.sigma_max.setObjectName(u"sigma_max")

        self.form_form.setWidget(12, QFormLayout.FieldRole, self.sigma_max)

        self.sigma_count_label = QLabel(self.settings)
        self.sigma_count_label.setObjectName(u"sigma_count_label")

        self.form_form.setWidget(13, QFormLayout.LabelRole, self.sigma_count_label)

        self.sigma_count = NoWheelSpinBox(self.settings)
        self.sigma_count.setObjectName(u"sigma_count")

        self.form_form.setWidget(13, QFormLayout.FieldRole, self.sigma_count)

        self.fft_size_label = QLabel(self.settings)
        self.fft_size_label.setObjectName(u"fft_size_label")

        self.form_form.setWidget(14, QFormLayout.LabelRole, self.fft_size_label)

        self.fft_size = NoWheelSpinBox(self.settings)
        self.fft_size.setObjectName(u"fft_size")

        self.form_form.setWidget(14, QFormLayout.FieldRole, self.fft_size)

        self.component = QCheckBox(self.settings)
        self.component.setObjectName(u"component")

        self.form_form.setWidget(15, QFormLayout.SpanningRole, self.component)

        self.bounds = QCheckBox(self.settings)
        self.bounds.setObjectName(u"bounds")

        self.form_form.setWidget(16, QFormLayout.SpanningRole, self.bounds)

        self.fill_zero = QCheckBox(self.settings)
        self.fill_zero.setObjectName(u"fill_zero")

        self.form_form.setWidget(17, QFormLayout.SpanningRole, self.fill_zero)

        self.single = QCheckBox(self.settings)
        self.single.setObjectName(u"single")

        self.form_form.setWidget(18, QFormLayout.SpanningRole, self.single)

        self.form_result_name_label = QLabel(self.settings)
        self.form_result_name_label.setObjectName(u"form_result_name_label")

        self.form_form.setWidget(19, QFormLayout.LabelRole, self.form_result_name_label)

        self.name = QLineEdit(self.settings)
        self.name.setObjectName(u"name")

        self.form_form.setWidget(19, QFormLayout.FieldRole, self.name)


        self.form_layout.addWidget(self.settings)

        self.note = QLabel(LaplaceDialog)
        self.note.setObjectName(u"note")
        self.note.setWordWrap(True)

        self.form_layout.addWidget(self.note)

        self.estimate = QLabel(LaplaceDialog)
        self.estimate.setObjectName(u"estimate")
        self.estimate.setWordWrap(True)

        self.form_layout.addWidget(self.estimate)

        self.form_persistence = QLabel(LaplaceDialog)
        self.form_persistence.setObjectName(u"form_persistence")
        self.form_persistence.setWordWrap(True)

        self.form_layout.addWidget(self.form_persistence)

        self.buttons = QDialogButtonBox(LaplaceDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.Cancel)

        self.form_layout.addWidget(self.buttons)

#if QT_CONFIG(shortcut)
        self.row_label.setBuddy(self.row)
        self.inverse_sigma_label.setBuddy(self.inverse_sigma)
        self.omega_spacing_label.setBuddy(self.omega_spacing)
        self.output_count_label.setBuddy(self.output_count)
        self.origin_label.setBuddy(self.origin)
        self.inverse_unit_label.setBuddy(self.inverse_unit)
        self.range_selector_label.setBuddy(self.range_selector)
        self.spacing_label.setBuddy(self.spacing)
        self.unit_label.setBuddy(self.unit)
        self.sigma_min_label.setBuddy(self.sigma_min)
        self.sigma_max_label.setBuddy(self.sigma_max)
        self.sigma_count_label.setBuddy(self.sigma_count)
        self.fft_size_label.setBuddy(self.fft_size)
        self.form_result_name_label.setBuddy(self.name)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(LaplaceDialog)

        QMetaObject.connectSlotsByName(LaplaceDialog)
    # setupUi

    def retranslateUi(self, LaplaceDialog):
        self.row_label.setText(QCoreApplication.translate("LaplaceDialog", u"Sigma row (zero-based)", None))
        self.inverse_sigma_label.setText(QCoreApplication.translate("LaplaceDialog", u"Sigma of this row (1 / time unit)", None))
        self.inverse_sigma.setText(QCoreApplication.translate("LaplaceDialog", u"0", None))
        self.omega_spacing_label.setText(QCoreApplication.translate("LaplaceDialog", u"Angular-frequency step (rad / time unit)", None))
        self.omega_spacing.setText(QCoreApplication.translate("LaplaceDialog", u"1", None))
        self.output_count_label.setText(QCoreApplication.translate("LaplaceDialog", u"Original sample count (without padding)", None))
        self.origin_label.setText(QCoreApplication.translate("LaplaceDialog", u"Output coordinate origin", None))
        self.origin.setText(QCoreApplication.translate("LaplaceDialog", u"0", None))
        self.inverse_unit_label.setText(QCoreApplication.translate("LaplaceDialog", u"Output time unit", None))
        self.inverse_unit.setText(QCoreApplication.translate("LaplaceDialog", u"sample", None))
        self.centered.setText(QCoreApplication.translate("LaplaceDialog", u"Frequency columns use centered order (fftshift)", None))
        self.range_selector_label.setText(QCoreApplication.translate("LaplaceDialog", u"Input range", None))
        self.spacing_label.setText(QCoreApplication.translate("LaplaceDialog", u"Sampling interval dt", None))
        self.unit_label.setText(QCoreApplication.translate("LaplaceDialog", u"Time / sample unit", None))
        self.auto_sigma.setText(QCoreApplication.translate("LaplaceDialog", u"Automatic sigma range (\u00b14 / signal duration)", None))
        self.sigma_min_label.setText(QCoreApplication.translate("LaplaceDialog", u"Sigma minimum", None))
        self.sigma_max_label.setText(QCoreApplication.translate("LaplaceDialog", u"Sigma maximum", None))
        self.sigma_count_label.setText(QCoreApplication.translate("LaplaceDialog", u"Sigma rows", None))
        self.fft_size_label.setText(QCoreApplication.translate("LaplaceDialog", u"Frequency columns (optional zero padding)", None))
        self.bounds.setText(QCoreApplication.translate("LaplaceDialog", u"Apply current value bounds before transforming", None))
        self.fill_zero.setText(QCoreApplication.translate("LaplaceDialog", u"Replace NaN / Inf / filtered samples with zero", None))
        self.single.setText(QCoreApplication.translate("LaplaceDialog", u"Single precision (complex64)", None))
        self.form_result_name_label.setText(QCoreApplication.translate("LaplaceDialog", u"Result name", None))
        self.name.setPlaceholderText(QCoreApplication.translate("LaplaceDialog", u"Automatic: source \u00b7 channel \u00b7 Laplace / Inverse Laplace", None))
        self.form_persistence.setText(QCoreApplication.translate("LaplaceDialog", u"NPY / MAT / CSV / TXT exports save values only. After reloading, enter the inverse parameters manually.", None))
        pass
    # retranslateUi

