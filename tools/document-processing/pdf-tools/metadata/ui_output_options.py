# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'output_options.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QFormLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QSizePolicy,
    QWidget)

from utils.qt_widgets import NoWheelComboBox

class Ui_OutputOptions(object):
    def setupUi(self, OutputOptions):
        if not OutputOptions.objectName():
            OutputOptions.setObjectName(u"OutputOptions")
        self.options_form = QFormLayout(OutputOptions)
        self.options_form.setObjectName(u"options_form")
        self.marker_label = QLabel(OutputOptions)
        self.marker_label.setObjectName(u"marker_label")

        self.options_form.setWidget(0, QFormLayout.LabelRole, self.marker_label)

        self.marker = NoWheelComboBox(OutputOptions)
        self.marker.setObjectName(u"marker")

        self.options_form.setWidget(0, QFormLayout.FieldRole, self.marker)

        self.marker_note = QLabel(OutputOptions)
        self.marker_note.setObjectName(u"marker_note")
        self.marker_note.setWordWrap(True)

        self.options_form.setWidget(1, QFormLayout.SpanningRole, self.marker_note)

        self.mode_label = QLabel(OutputOptions)
        self.mode_label.setObjectName(u"mode_label")

        self.options_form.setWidget(2, QFormLayout.LabelRole, self.mode_label)

        self.mode = NoWheelComboBox(OutputOptions)
        self.mode.setObjectName(u"mode")

        self.options_form.setWidget(2, QFormLayout.FieldRole, self.mode)

        self.owner_label = QLabel(OutputOptions)
        self.owner_label.setObjectName(u"owner_label")

        self.options_form.setWidget(3, QFormLayout.LabelRole, self.owner_label)

        self.owner = QLineEdit(OutputOptions)
        self.owner.setObjectName(u"owner")

        self.options_form.setWidget(3, QFormLayout.FieldRole, self.owner)

        self.user_label = QLabel(OutputOptions)
        self.user_label.setObjectName(u"user_label")

        self.options_form.setWidget(4, QFormLayout.LabelRole, self.user_label)

        self.user = QLineEdit(OutputOptions)
        self.user.setObjectName(u"user")

        self.options_form.setWidget(4, QFormLayout.FieldRole, self.user)

        self.group = QGroupBox(OutputOptions)
        self.group.setObjectName(u"group")
        self.permission_grid = QGridLayout(self.group)
        self.permission_grid.setObjectName(u"permission_grid")
        self.print_pages = QCheckBox(self.group)
        self.print_pages.setObjectName(u"print_pages")

        self.permission_grid.addWidget(self.print_pages, 0, 0, 1, 1)

        self.print_hq = QCheckBox(self.group)
        self.print_hq.setObjectName(u"print_hq")

        self.permission_grid.addWidget(self.print_hq, 0, 1, 1, 1)

        self.copy_content = QCheckBox(self.group)
        self.copy_content.setObjectName(u"copy_content")

        self.permission_grid.addWidget(self.copy_content, 1, 0, 1, 1)

        self.accessible = QCheckBox(self.group)
        self.accessible.setObjectName(u"accessible")

        self.permission_grid.addWidget(self.accessible, 1, 1, 1, 1)

        self.modify = QCheckBox(self.group)
        self.modify.setObjectName(u"modify")

        self.permission_grid.addWidget(self.modify, 2, 0, 1, 1)

        self.annotate = QCheckBox(self.group)
        self.annotate.setObjectName(u"annotate")

        self.permission_grid.addWidget(self.annotate, 2, 1, 1, 1)

        self.fill_forms = QCheckBox(self.group)
        self.fill_forms.setObjectName(u"fill_forms")

        self.permission_grid.addWidget(self.fill_forms, 3, 0, 1, 1)

        self.assemble = QCheckBox(self.group)
        self.assemble.setObjectName(u"assemble")

        self.permission_grid.addWidget(self.assemble, 3, 1, 1, 1)


        self.options_form.setWidget(5, QFormLayout.SpanningRole, self.group)

#if QT_CONFIG(shortcut)
        self.marker_label.setBuddy(self.marker)
        self.mode_label.setBuddy(self.mode)
        self.owner_label.setBuddy(self.owner)
        self.user_label.setBuddy(self.user)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(OutputOptions)

        QMetaObject.connectSlotsByName(OutputOptions)
    # setupUi

    def retranslateUi(self, OutputOptions):
        self.marker_label.setText(QCoreApplication.translate("OutputOptions", u"PDF/A identification", None))
        self.marker_note.setText(QCoreApplication.translate("OutputOptions", u"Writing identification alone does not establish PDF/A conformance.", None))
        self.mode_label.setText(QCoreApplication.translate("OutputOptions", u"Output security", None))
        self.owner_label.setText(QCoreApplication.translate("OutputOptions", u"Owner password", None))
        self.user_label.setText(QCoreApplication.translate("OutputOptions", u"Opening password", None))
        self.group.setTitle(QCoreApplication.translate("OutputOptions", u"Allowed actions", None))
        self.print_pages.setText(QCoreApplication.translate("OutputOptions", u"Print", None))
        self.print_hq.setText(QCoreApplication.translate("OutputOptions", u"High-quality printing", None))
        self.copy_content.setText(QCoreApplication.translate("OutputOptions", u"Copy text and images", None))
        self.accessible.setText(QCoreApplication.translate("OutputOptions", u"Accessibility", None))
        self.modify.setText(QCoreApplication.translate("OutputOptions", u"Modify content", None))
        self.annotate.setText(QCoreApplication.translate("OutputOptions", u"Add annotations", None))
        self.fill_forms.setText(QCoreApplication.translate("OutputOptions", u"Fill forms", None))
        self.assemble.setText(QCoreApplication.translate("OutputOptions", u"Assemble pages", None))
        pass
    # retranslateUi

