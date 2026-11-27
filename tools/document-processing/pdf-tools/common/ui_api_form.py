# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'api_form.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy,
    QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox)

class Ui_ApiForm(object):
    def setupUi(self, ApiForm):
        if not ApiForm.objectName():
            ApiForm.setObjectName(u"ApiForm")
        self.settings_form = QFormLayout(ApiForm)
        self.settings_form.setObjectName(u"settings_form")
        self.settings_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.preferences_row = QHBoxLayout()
        self.preferences_row.setObjectName(u"preferences_row")
        self.save_api_button = QPushButton(ApiForm)
        self.save_api_button.setObjectName(u"save_api_button")

        self.preferences_row.addWidget(self.save_api_button)

        self.load_api_button = QPushButton(ApiForm)
        self.load_api_button.setObjectName(u"load_api_button")

        self.preferences_row.addWidget(self.load_api_button)


        self.settings_form.setLayout(0, QFormLayout.SpanningRole, self.preferences_row)

        self.api_config_status = QLabel(ApiForm)
        self.api_config_status.setObjectName(u"api_config_status")
        self.api_config_status.setWordWrap(True)

        self.settings_form.setWidget(1, QFormLayout.SpanningRole, self.api_config_status)

        self.api_url_label = QLabel(ApiForm)
        self.api_url_label.setObjectName(u"api_url_label")

        self.settings_form.setWidget(2, QFormLayout.LabelRole, self.api_url_label)

        self.api_url = NoWheelComboBox(ApiForm)
        self.api_url.setObjectName(u"api_url")

        self.settings_form.setWidget(2, QFormLayout.FieldRole, self.api_url)

        self.model_row_label = QLabel(ApiForm)
        self.model_row_label.setObjectName(u"model_row_label")

        self.settings_form.setWidget(3, QFormLayout.LabelRole, self.model_row_label)

        self.model_row = QHBoxLayout()
        self.model_row.setObjectName(u"model_row")
        self.api_model = NoWheelComboBox(ApiForm)
        self.api_model.setObjectName(u"api_model")

        self.model_row.addWidget(self.api_model)

        self.fetch_button = QPushButton(ApiForm)
        self.fetch_button.setObjectName(u"fetch_button")

        self.model_row.addWidget(self.fetch_button)

        self.model_row.setStretch(0, 1)

        self.settings_form.setLayout(3, QFormLayout.FieldRole, self.model_row)

        self.vision_models_only = QCheckBox(ApiForm)
        self.vision_models_only.setObjectName(u"vision_models_only")

        self.settings_form.setWidget(4, QFormLayout.SpanningRole, self.vision_models_only)

        self.models_status = QLabel(ApiForm)
        self.models_status.setObjectName(u"models_status")
        self.models_status.setWordWrap(True)

        self.settings_form.setWidget(5, QFormLayout.SpanningRole, self.models_status)

        self.api_key_label = QLabel(ApiForm)
        self.api_key_label.setObjectName(u"api_key_label")

        self.settings_form.setWidget(6, QFormLayout.LabelRole, self.api_key_label)

        self.api_key = QLineEdit(ApiForm)
        self.api_key.setObjectName(u"api_key")

        self.settings_form.setWidget(6, QFormLayout.FieldRole, self.api_key)

        self.temperature_label = QLabel(ApiForm)
        self.temperature_label.setObjectName(u"temperature_label")

        self.settings_form.setWidget(7, QFormLayout.LabelRole, self.temperature_label)

        self.temperature = NoWheelDoubleSpinBox(ApiForm)
        self.temperature.setObjectName(u"temperature")

        self.settings_form.setWidget(7, QFormLayout.FieldRole, self.temperature)

        self.max_tokens_label = QLabel(ApiForm)
        self.max_tokens_label.setObjectName(u"max_tokens_label")

        self.settings_form.setWidget(8, QFormLayout.LabelRole, self.max_tokens_label)

        self.max_tokens = NoWheelSpinBox(ApiForm)
        self.max_tokens.setObjectName(u"max_tokens")

        self.settings_form.setWidget(8, QFormLayout.FieldRole, self.max_tokens)

        self.timeout_label = QLabel(ApiForm)
        self.timeout_label.setObjectName(u"timeout_label")

        self.settings_form.setWidget(9, QFormLayout.LabelRole, self.timeout_label)

        self.timeout = NoWheelSpinBox(ApiForm)
        self.timeout.setObjectName(u"timeout")

        self.settings_form.setWidget(9, QFormLayout.FieldRole, self.timeout)

        self.context_images_label = QLabel(ApiForm)
        self.context_images_label.setObjectName(u"context_images_label")

        self.settings_form.setWidget(10, QFormLayout.LabelRole, self.context_images_label)

        self.context_images = NoWheelSpinBox(ApiForm)
        self.context_images.setObjectName(u"context_images")

        self.settings_form.setWidget(10, QFormLayout.FieldRole, self.context_images)

        self.reasoning_effort_label = QLabel(ApiForm)
        self.reasoning_effort_label.setObjectName(u"reasoning_effort_label")

        self.settings_form.setWidget(11, QFormLayout.LabelRole, self.reasoning_effort_label)

        self.reasoning_effort = NoWheelComboBox(ApiForm)
        self.reasoning_effort.setObjectName(u"reasoning_effort")

        self.settings_form.setWidget(11, QFormLayout.FieldRole, self.reasoning_effort)

        self.reset_api_parameters_button = QPushButton(ApiForm)
        self.reset_api_parameters_button.setObjectName(u"reset_api_parameters_button")

        self.settings_form.setWidget(12, QFormLayout.SpanningRole, self.reset_api_parameters_button)

        self.skip_certificate_verification = QCheckBox(ApiForm)
        self.skip_certificate_verification.setObjectName(u"skip_certificate_verification")

        self.settings_form.setWidget(13, QFormLayout.SpanningRole, self.skip_certificate_verification)

        self.balance_key_label = QLabel(ApiForm)
        self.balance_key_label.setObjectName(u"balance_key_label")

        self.settings_form.setWidget(14, QFormLayout.LabelRole, self.balance_key_label)

        self.balance_key = QLineEdit(ApiForm)
        self.balance_key.setObjectName(u"balance_key")

        self.settings_form.setWidget(14, QFormLayout.FieldRole, self.balance_key)

        self.balance_button = QPushButton(ApiForm)
        self.balance_button.setObjectName(u"balance_button")

        self.settings_form.setWidget(15, QFormLayout.SpanningRole, self.balance_button)

        self.balance_status = QLabel(ApiForm)
        self.balance_status.setObjectName(u"balance_status")
        self.balance_status.setWordWrap(True)

        self.settings_form.setWidget(16, QFormLayout.SpanningRole, self.balance_status)

        self.usage = QLabel(ApiForm)
        self.usage.setObjectName(u"usage")
        self.usage.setWordWrap(True)

        self.settings_form.setWidget(17, QFormLayout.SpanningRole, self.usage)

        self.test_button = QPushButton(ApiForm)
        self.test_button.setObjectName(u"test_button")

        self.settings_form.setWidget(18, QFormLayout.SpanningRole, self.test_button)

        self.test_status = QLabel(ApiForm)
        self.test_status.setObjectName(u"test_status")
        self.test_status.setWordWrap(True)

        self.settings_form.setWidget(19, QFormLayout.SpanningRole, self.test_status)

        self.copy_prompt = QPushButton(ApiForm)
        self.copy_prompt.setObjectName(u"copy_prompt")

        self.settings_form.setWidget(20, QFormLayout.SpanningRole, self.copy_prompt)

#if QT_CONFIG(shortcut)
        self.api_url_label.setBuddy(self.api_url)
        self.api_key_label.setBuddy(self.api_key)
        self.temperature_label.setBuddy(self.temperature)
        self.max_tokens_label.setBuddy(self.max_tokens)
        self.timeout_label.setBuddy(self.timeout)
        self.context_images_label.setBuddy(self.context_images)
        self.reasoning_effort_label.setBuddy(self.reasoning_effort)
        self.balance_key_label.setBuddy(self.balance_key)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(ApiForm)

        QMetaObject.connectSlotsByName(ApiForm)
    # setupUi

    def retranslateUi(self, ApiForm):
        self.save_api_button.setText(QCoreApplication.translate("ApiForm", u"Save", None))
        self.load_api_button.setText(QCoreApplication.translate("ApiForm", u"Load", None))
        self.api_config_status.setText(QCoreApplication.translate("ApiForm", u"API settings are loaded at startup; Save or close this window to write changes.", None))
        self.api_url_label.setText(QCoreApplication.translate("ApiForm", u"API preset / URL", None))
        self.model_row_label.setText(QCoreApplication.translate("ApiForm", u"Model", None))
        self.fetch_button.setText(QCoreApplication.translate("ApiForm", u"Get models", None))
        self.vision_models_only.setText(QCoreApplication.translate("ApiForm", u"Vision models only (strict)", None))
        self.models_status.setText(QCoreApplication.translate("ApiForm", u"Get models or enter a vision model name. Local servers may leave API key empty.", None))
        self.api_key_label.setText(QCoreApplication.translate("ApiForm", u"API key", None))
        self.temperature_label.setText(QCoreApplication.translate("ApiForm", u"Temperature", None))
        self.max_tokens_label.setText(QCoreApplication.translate("ApiForm", u"Max output tokens", None))
        self.timeout_label.setText(QCoreApplication.translate("ApiForm", u"Timeout (seconds)", None))
        self.context_images_label.setText(QCoreApplication.translate("ApiForm", u"Context images", None))
        self.reasoning_effort_label.setText(QCoreApplication.translate("ApiForm", u"Reasoning effort", None))
        self.reset_api_parameters_button.setText(QCoreApplication.translate("ApiForm", u"Reset parameters", None))
        self.skip_certificate_verification.setText(QCoreApplication.translate("ApiForm", u"Skip certificate verification", None))
        self.balance_key_label.setText(QCoreApplication.translate("ApiForm", u"Balance key", None))
        self.balance_button.setText(QCoreApplication.translate("ApiForm", u"Refresh API balance", None))
        self.balance_status.setText(QCoreApplication.translate("ApiForm", u"Enter an API key to display the account balance.", None))
        self.usage.setText(QCoreApplication.translate("ApiForm", u"Context: no request yet", None))
        self.test_button.setText(QCoreApplication.translate("ApiForm", u"Test API (small image)", None))
        self.test_status.setText(QCoreApplication.translate("ApiForm", u"API not tested", None))
        self.copy_prompt.setText(QCoreApplication.translate("ApiForm", u"Copy system prompt", None))
        pass
    # retranslateUi

