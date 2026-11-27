# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'raw_data_view.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QSizePolicy, QSlider,
    QTableView, QVBoxLayout, QWidget)

from .qt_widgets import VerticalSeparator
from utils.qt_widgets import (NoWheelComboBox, NoWheelSpinBox)

class Ui_RawDataView(object):
    def setupUi(self, RawDataView):
        if not RawDataView.objectName():
            RawDataView.setObjectName(u"RawDataView")
        self.form_layout = QVBoxLayout(RawDataView)
        self.form_layout.setObjectName(u"form_layout")
        self.form_heading = QHBoxLayout()
        self.form_heading.setObjectName(u"form_heading")
        self.note = QLabel(RawDataView)
        self.note.setObjectName(u"note")
        self.note.setWordWrap(True)

        self.form_heading.addWidget(self.note)

        self.hex_checkbox = QCheckBox(RawDataView)
        self.hex_checkbox.setObjectName(u"hex_checkbox")

        self.form_heading.addWidget(self.hex_checkbox)

        self.form_matrix_inline = QLabel(RawDataView)
        self.form_matrix_inline.setObjectName(u"form_matrix_inline")

        self.form_heading.addWidget(self.form_matrix_inline)

        self.matrix_combo = NoWheelComboBox(RawDataView)
        self.matrix_combo.setObjectName(u"matrix_combo")

        self.form_heading.addWidget(self.matrix_combo)

        self.form_heading.setStretch(0, 1)

        self.form_layout.addLayout(self.form_heading)

        self.table = QTableView(RawDataView)
        self.table.setObjectName(u"table")
        self.table.setWordWrap(False)

        self.form_layout.addWidget(self.table)

        self.form_bar = QHBoxLayout()
        self.form_bar.setObjectName(u"form_bar")
        self.row_label = QLabel(RawDataView)
        self.row_label.setObjectName(u"row_label")

        self.form_bar.addWidget(self.row_label)

        self.row = NoWheelSpinBox(RawDataView)
        self.row.setObjectName(u"row")

        self.form_bar.addWidget(self.row)

        self.column_label = QLabel(RawDataView)
        self.column_label.setObjectName(u"column_label")

        self.form_bar.addWidget(self.column_label)

        self.column = NoWheelSpinBox(RawDataView)
        self.column.setObjectName(u"column")

        self.form_bar.addWidget(self.column)

        self.form_go = QPushButton(RawDataView)
        self.form_go.setObjectName(u"form_go")

        self.form_bar.addWidget(self.form_go)

        self.form_copy = QPushButton(RawDataView)
        self.form_copy.setObjectName(u"form_copy")

        self.form_bar.addWidget(self.form_copy)

        self.form_verticalseparator_inline = VerticalSeparator(RawDataView)
        self.form_verticalseparator_inline.setObjectName(u"form_verticalseparator_inline")

        self.form_bar.addWidget(self.form_verticalseparator_inline)

        self.form_column_width_2_inline = QLabel(RawDataView)
        self.form_column_width_2_inline.setObjectName(u"form_column_width_2_inline")

        self.form_bar.addWidget(self.form_column_width_2_inline)

        self.column_width = NoWheelSpinBox(RawDataView)
        self.column_width.setObjectName(u"column_width")

        self.form_bar.addWidget(self.column_width)

        self.width_slider = QSlider(RawDataView)
        self.width_slider.setObjectName(u"width_slider")
        self.width_slider.setOrientation(Qt.Horizontal)

        self.form_bar.addWidget(self.width_slider)

        self.form_bar.setStretch(9, 1)

        self.form_layout.addLayout(self.form_bar)


        self.retranslateUi(RawDataView)

        QMetaObject.connectSlotsByName(RawDataView)
    # setupUi

    def retranslateUi(self, RawDataView):
        self.note.setText(QCoreApplication.translate("RawDataView", u"No data loaded", None))
        self.hex_checkbox.setText(QCoreApplication.translate("RawDataView", u"Hexadecimal", None))
        self.form_matrix_inline.setText(QCoreApplication.translate("RawDataView", u"Matrix", None))
        self.matrix_combo.setPlaceholderText(QCoreApplication.translate("RawDataView", u"No matrices", None))
        self.row_label.setText(QCoreApplication.translate("RawDataView", u"Row", None))
        self.column_label.setText(QCoreApplication.translate("RawDataView", u"Column", None))
        self.form_go.setText(QCoreApplication.translate("RawDataView", u"Go to cell", None))
        self.form_copy.setText(QCoreApplication.translate("RawDataView", u"Copy selection", None))
        self.form_column_width_2_inline.setText(QCoreApplication.translate("RawDataView", u"Column width", None))
        pass
    # retranslateUi

