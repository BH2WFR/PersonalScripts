# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'regex_dialog.ui'
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
    QSizePolicy, QWidget)

class Ui_RegexDialog(object):
    def setupUi(self, RegexDialog):
        if not RegexDialog.objectName():
            RegexDialog.setObjectName(u"RegexDialog")
        self.form_layout = QFormLayout(RegexDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.pattern_label = QLabel(RegexDialog)
        self.pattern_label.setObjectName(u"pattern_label")

        self.form_layout.setWidget(0, QFormLayout.LabelRole, self.pattern_label)

        self.pattern = QLineEdit(RegexDialog)
        self.pattern.setObjectName(u"pattern")

        self.form_layout.setWidget(0, QFormLayout.FieldRole, self.pattern)

        self.replacement_label = QLabel(RegexDialog)
        self.replacement_label.setObjectName(u"replacement_label")

        self.form_layout.setWidget(1, QFormLayout.LabelRole, self.replacement_label)

        self.replacement = QLineEdit(RegexDialog)
        self.replacement.setObjectName(u"replacement")

        self.form_layout.setWidget(1, QFormLayout.FieldRole, self.replacement)

        self.capture_hint = QLabel(RegexDialog)
        self.capture_hint.setObjectName(u"capture_hint")

        self.form_layout.setWidget(2, QFormLayout.SpanningRole, self.capture_hint)

        self.match_case = QCheckBox(RegexDialog)
        self.match_case.setObjectName(u"match_case")
        self.match_case.setChecked(True)

        self.form_layout.setWidget(3, QFormLayout.SpanningRole, self.match_case)

        self.error = QLabel(RegexDialog)
        self.error.setObjectName(u"error")
        self.error.setWordWrap(True)

        self.form_layout.setWidget(4, QFormLayout.SpanningRole, self.error)

        self.buttons = QDialogButtonBox(RegexDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)

        self.form_layout.setWidget(5, QFormLayout.SpanningRole, self.buttons)


        self.retranslateUi(RegexDialog)

        QMetaObject.connectSlotsByName(RegexDialog)
    # setupUi

    def retranslateUi(self, RegexDialog):
        RegexDialog.setWindowTitle(QCoreApplication.translate("RegexDialog", u"Regular expression replacement", None))
        self.pattern_label.setText(QCoreApplication.translate("RegexDialog", u"Pattern", None))
        self.pattern.setPlaceholderText(QCoreApplication.translate("RegexDialog", u"(\\w+),\\s*(\\w+)", None))
        self.replacement_label.setText(QCoreApplication.translate("RegexDialog", u"Replacement", None))
        self.replacement.setPlaceholderText(QCoreApplication.translate("RegexDialog", u"\\2 \\1", None))
        self.capture_hint.setText(QCoreApplication.translate("RegexDialog", u"Use \\1 or \\g<name> for a captured group.", None))
        self.match_case.setText(QCoreApplication.translate("RegexDialog", u"Match case", None))
    # retranslateUi

