# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'complex_merge_dialog.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QDialog,
    QDialogButtonBox, QFormLayout, QGroupBox, QLabel,
    QLineEdit, QSizePolicy, QVBoxLayout, QWidget)

from utils.qt_widgets import NoWheelComboBox

class Ui_ComplexMergeDialog(object):
    def setupUi(self, ComplexMergeDialog):
        if not ComplexMergeDialog.objectName():
            ComplexMergeDialog.setObjectName(u"ComplexMergeDialog")
        ComplexMergeDialog.resize(720, 470)
        self.form_layout = QVBoxLayout(ComplexMergeDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.settings = QWidget(ComplexMergeDialog)
        self.settings.setObjectName(u"settings")
        self.form_settings_layout = QVBoxLayout(self.settings)
        self.form_settings_layout.setObjectName(u"form_settings_layout")
        self.form_form = QFormLayout()
        self.form_form.setObjectName(u"form_form")
        self.form_combine_label = QLabel(self.settings)
        self.form_combine_label.setObjectName(u"form_combine_label")

        self.form_form.setWidget(0, QFormLayout.LabelRole, self.form_combine_label)

        self.mode_selector = NoWheelComboBox(self.settings)
        self.mode_selector.setObjectName(u"mode_selector")

        self.form_form.setWidget(0, QFormLayout.FieldRole, self.mode_selector)


        self.form_settings_layout.addLayout(self.form_form)

        self.first_input = QGroupBox(self.settings)
        self.first_input.setObjectName(u"first_input")
        self.first_form = QFormLayout(self.first_input)
        self.first_form.setObjectName(u"first_form")
        self.first_matrix_label = QLabel(self.first_input)
        self.first_matrix_label.setObjectName(u"first_matrix_label")

        self.first_form.setWidget(0, QFormLayout.LabelRole, self.first_matrix_label)

        self.first_matrix = NoWheelComboBox(self.first_input)
        self.first_matrix.setObjectName(u"first_matrix")
        self.first_matrix.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.first_matrix.setMinimumContentsLength(28)

        self.first_form.setWidget(0, QFormLayout.FieldRole, self.first_matrix)

        self.first_channel_label = QLabel(self.first_input)
        self.first_channel_label.setObjectName(u"first_channel_label")

        self.first_form.setWidget(1, QFormLayout.LabelRole, self.first_channel_label)

        self.first_channel = NoWheelComboBox(self.first_input)
        self.first_channel.setObjectName(u"first_channel")
        self.first_channel.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.first_channel.setMinimumContentsLength(28)

        self.first_form.setWidget(1, QFormLayout.FieldRole, self.first_channel)

        self.first_detail = QLabel(self.first_input)
        self.first_detail.setObjectName(u"first_detail")
        self.first_detail.setWordWrap(True)

        self.first_form.setWidget(2, QFormLayout.SpanningRole, self.first_detail)


        self.form_settings_layout.addWidget(self.first_input)

        self.second_input = QGroupBox(self.settings)
        self.second_input.setObjectName(u"second_input")
        self.second_form = QFormLayout(self.second_input)
        self.second_form.setObjectName(u"second_form")
        self.second_matrix_label = QLabel(self.second_input)
        self.second_matrix_label.setObjectName(u"second_matrix_label")

        self.second_form.setWidget(0, QFormLayout.LabelRole, self.second_matrix_label)

        self.second_matrix = NoWheelComboBox(self.second_input)
        self.second_matrix.setObjectName(u"second_matrix")
        self.second_matrix.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.second_matrix.setMinimumContentsLength(28)

        self.second_form.setWidget(0, QFormLayout.FieldRole, self.second_matrix)

        self.second_channel_label = QLabel(self.second_input)
        self.second_channel_label.setObjectName(u"second_channel_label")

        self.second_form.setWidget(1, QFormLayout.LabelRole, self.second_channel_label)

        self.second_channel = NoWheelComboBox(self.second_input)
        self.second_channel.setObjectName(u"second_channel")
        self.second_channel.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.second_channel.setMinimumContentsLength(28)

        self.second_form.setWidget(1, QFormLayout.FieldRole, self.second_channel)

        self.second_detail = QLabel(self.second_input)
        self.second_detail.setObjectName(u"second_detail")
        self.second_detail.setWordWrap(True)

        self.second_form.setWidget(2, QFormLayout.SpanningRole, self.second_detail)


        self.form_settings_layout.addWidget(self.second_input)

        self.form_bottom = QFormLayout()
        self.form_bottom.setObjectName(u"form_bottom")
        self.form_phase_unit_polar_mode_label = QLabel(self.settings)
        self.form_phase_unit_polar_mode_label.setObjectName(u"form_phase_unit_polar_mode_label")

        self.form_bottom.setWidget(0, QFormLayout.LabelRole, self.form_phase_unit_polar_mode_label)

        self.phase_unit = NoWheelComboBox(self.settings)
        self.phase_unit.setObjectName(u"phase_unit")

        self.form_bottom.setWidget(0, QFormLayout.FieldRole, self.phase_unit)

        self.form_result_name_2_label = QLabel(self.settings)
        self.form_result_name_2_label.setObjectName(u"form_result_name_2_label")

        self.form_bottom.setWidget(1, QFormLayout.LabelRole, self.form_result_name_2_label)

        self.result_name = QLineEdit(self.settings)
        self.result_name.setObjectName(u"result_name")

        self.form_bottom.setWidget(1, QFormLayout.FieldRole, self.result_name)


        self.form_settings_layout.addLayout(self.form_bottom)


        self.form_layout.addWidget(self.settings)

        self.note = QLabel(ComplexMergeDialog)
        self.note.setObjectName(u"note")
        self.note.setWordWrap(True)

        self.form_layout.addWidget(self.note)

        self.buttons = QDialogButtonBox(ComplexMergeDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.Cancel)

        self.form_layout.addWidget(self.buttons)

#if QT_CONFIG(shortcut)
        self.form_combine_label.setBuddy(self.mode_selector)
        self.first_matrix_label.setBuddy(self.first_matrix)
        self.first_channel_label.setBuddy(self.first_channel)
        self.second_matrix_label.setBuddy(self.second_matrix)
        self.second_channel_label.setBuddy(self.second_channel)
        self.form_phase_unit_polar_mode_label.setBuddy(self.phase_unit)
        self.form_result_name_2_label.setBuddy(self.result_name)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(ComplexMergeDialog)

        QMetaObject.connectSlotsByName(ComplexMergeDialog)
    # setupUi

    def retranslateUi(self, ComplexMergeDialog):
        ComplexMergeDialog.setWindowTitle(QCoreApplication.translate("ComplexMergeDialog", u"Complex matrix merge", None))
        self.form_combine_label.setText(QCoreApplication.translate("ComplexMergeDialog", u"Combine", None))
        self.first_input.setTitle(QCoreApplication.translate("ComplexMergeDialog", u"First input", None))
        self.first_matrix_label.setText(QCoreApplication.translate("ComplexMergeDialog", u"Matrix", None))
        self.first_channel_label.setText(QCoreApplication.translate("ComplexMergeDialog", u"Channel", None))
        self.second_input.setTitle(QCoreApplication.translate("ComplexMergeDialog", u"Second input", None))
        self.second_matrix_label.setText(QCoreApplication.translate("ComplexMergeDialog", u"Matrix", None))
        self.second_channel_label.setText(QCoreApplication.translate("ComplexMergeDialog", u"Channel", None))
        self.form_phase_unit_polar_mode_label.setText(QCoreApplication.translate("ComplexMergeDialog", u"Phase unit (polar mode)", None))
        self.form_result_name_2_label.setText(QCoreApplication.translate("ComplexMergeDialog", u"Result name", None))
        self.result_name.setPlaceholderText(QCoreApplication.translate("ComplexMergeDialog", u"Automatic: Complex merge \u00b7 first source + second source", None))
        self.note.setText(QCoreApplication.translate("ComplexMergeDialog", u"Uses complete numeric channels before display crop, value bounds or overlay alignment. Shapes and sample coordinates must match; no broadcasting or resampling. XY signals require the same unique, uniform X grid. Color composites use their numeric grayscale fusion channels. Polar magnitude must be linear and nonnegative. NaN / Inf remain gaps. The result is a new complex matrix; source arrays are unchanged.", None))
    # retranslateUi

