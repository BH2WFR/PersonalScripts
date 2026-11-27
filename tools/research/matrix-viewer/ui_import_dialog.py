# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'import_dialog.ui'
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
    QHeaderView, QLabel, QPushButton, QSizePolicy,
    QSpacerItem, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelSpinBox)

class Ui_ImportDialog(object):
    def setupUi(self, ImportDialog):
        if not ImportDialog.objectName():
            ImportDialog.setObjectName(u"ImportDialog")
        self.form_layout = QVBoxLayout(ImportDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.form_source = QLabel(ImportDialog)
        self.form_source.setObjectName(u"form_source")
        self.form_source.setWordWrap(True)

        self.form_layout.addWidget(self.form_source)

        self.include_file_prefix = QCheckBox(ImportDialog)
        self.include_file_prefix.setObjectName(u"include_file_prefix")

        self.form_layout.addWidget(self.include_file_prefix)

        self.form_bar = QHBoxLayout()
        self.form_bar.setObjectName(u"form_bar")
        self.select_all = QPushButton(ImportDialog)
        self.select_all.setObjectName(u"select_all")

        self.form_bar.addWidget(self.select_all)

        self.select_none = QPushButton(ImportDialog)
        self.select_none.setObjectName(u"select_none")

        self.form_bar.addWidget(self.select_none)

        self.bar_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.form_bar.addItem(self.bar_spacer)


        self.form_layout.addLayout(self.form_bar)

        self.members = QTreeWidget(ImportDialog)
        self.members.setObjectName(u"members")

        self.form_layout.addWidget(self.members)

        self.range_box = QGroupBox(ImportDialog)
        self.range_box.setObjectName(u"range_box")
        self.form = QFormLayout(self.range_box)
        self.form.setObjectName(u"form")
        self.start_row_fields_label = QLabel(self.range_box)
        self.start_row_fields_label.setObjectName(u"start_row_fields_label")

        self.form.setWidget(0, QFormLayout.LabelRole, self.start_row_fields_label)

        self.start_row_fields = QHBoxLayout()
        self.start_row_fields.setObjectName(u"start_row_fields")
        self.start_row = NoWheelSpinBox(self.range_box)
        self.start_row.setObjectName(u"start_row")

        self.start_row_fields.addWidget(self.start_row)

        self.start_row_to = QLabel(self.range_box)
        self.start_row_to.setObjectName(u"start_row_to")

        self.start_row_fields.addWidget(self.start_row_to)

        self.end_row = NoWheelSpinBox(self.range_box)
        self.end_row.setObjectName(u"end_row")

        self.start_row_fields.addWidget(self.end_row)


        self.form.setLayout(0, QFormLayout.FieldRole, self.start_row_fields)

        self.start_column_fields_label = QLabel(self.range_box)
        self.start_column_fields_label.setObjectName(u"start_column_fields_label")

        self.form.setWidget(1, QFormLayout.LabelRole, self.start_column_fields_label)

        self.start_column_fields = QHBoxLayout()
        self.start_column_fields.setObjectName(u"start_column_fields")
        self.start_column = NoWheelSpinBox(self.range_box)
        self.start_column.setObjectName(u"start_column")

        self.start_column_fields.addWidget(self.start_column)

        self.start_column_to = QLabel(self.range_box)
        self.start_column_to.setObjectName(u"start_column_to")

        self.start_column_fields.addWidget(self.start_column_to)

        self.end_column = NoWheelSpinBox(self.range_box)
        self.end_column.setObjectName(u"end_column")

        self.start_column_fields.addWidget(self.end_column)


        self.form.setLayout(1, QFormLayout.FieldRole, self.start_column_fields)

        self.form_header_2_label = QLabel(self.range_box)
        self.form_header_2_label.setObjectName(u"form_header_2_label")

        self.form.setWidget(2, QFormLayout.LabelRole, self.form_header_2_label)

        self.header = NoWheelComboBox(self.range_box)
        self.header.setObjectName(u"header")

        self.form.setWidget(2, QFormLayout.FieldRole, self.header)

        self.form_text_delimiter_label = QLabel(self.range_box)
        self.form_text_delimiter_label.setObjectName(u"form_text_delimiter_label")

        self.form.setWidget(3, QFormLayout.LabelRole, self.form_text_delimiter_label)

        self.delimiter = NoWheelComboBox(self.range_box)
        self.delimiter.setObjectName(u"delimiter")

        self.form.setWidget(3, QFormLayout.FieldRole, self.delimiter)


        self.form_layout.addWidget(self.range_box)

        self.preview_box = QGroupBox(ImportDialog)
        self.preview_box.setObjectName(u"preview_box")
        self.form_preview_layout = QVBoxLayout(self.preview_box)
        self.form_preview_layout.setObjectName(u"form_preview_layout")
        self.preview = QTableWidget(self.preview_box)
        self.preview.setObjectName(u"preview")
        self.preview.setMaximumSize(QSize(16777215, 180))

        self.form_preview_layout.addWidget(self.preview)


        self.form_layout.addWidget(self.preview_box)

        self.note = QLabel(ImportDialog)
        self.note.setObjectName(u"note")
        self.note.setWordWrap(True)

        self.form_layout.addWidget(self.note)

        self.buttons = QDialogButtonBox(ImportDialog)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setStandardButtons(QDialogButtonBox.Open|QDialogButtonBox.Cancel)

        self.form_layout.addWidget(self.buttons)

        self.form_layout.setStretch(3, 1)
#if QT_CONFIG(shortcut)
        self.form_header_2_label.setBuddy(self.header)
        self.form_text_delimiter_label.setBuddy(self.delimiter)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(ImportDialog)

        QMetaObject.connectSlotsByName(ImportDialog)
    # setupUi

    def retranslateUi(self, ImportDialog):
        ImportDialog.setWindowTitle(QCoreApplication.translate("ImportDialog", u"Choose matrices / input range", None))
        self.include_file_prefix.setText(QCoreApplication.translate("ImportDialog", u"Include NPZ filename in matrix names", None))
#if QT_CONFIG(tooltip)
        self.include_file_prefix.setToolTip(QCoreApplication.translate("ImportDialog", u"Checked: archive.npz :: member. Unchecked: member only. Applies to all selected matrices, including split channels. The full source stays in tooltips.", None))
#endif // QT_CONFIG(tooltip)
        self.select_all.setText(QCoreApplication.translate("ImportDialog", u"Select all", None))
        self.select_none.setText(QCoreApplication.translate("ImportDialog", u"Select none", None))
        self.range_box.setTitle(QCoreApplication.translate("ImportDialog", u"Input range for the highlighted table (1-based, inclusive)", None))
        self.start_row_fields_label.setText(QCoreApplication.translate("ImportDialog", u"Rows", None))
        self.start_row_to.setText(QCoreApplication.translate("ImportDialog", u"to", None))
        self.start_column_fields_label.setText(QCoreApplication.translate("ImportDialog", u"Columns", None))
        self.start_column_to.setText(QCoreApplication.translate("ImportDialog", u"to", None))
        self.form_header_2_label.setText(QCoreApplication.translate("ImportDialog", u"Header", None))
        self.form_text_delimiter_label.setText(QCoreApplication.translate("ImportDialog", u"Text delimiter", None))
        self.preview_box.setTitle(QCoreApplication.translate("ImportDialog", u"Original top-left cells (preview only)", None))
    # retranslateUi

