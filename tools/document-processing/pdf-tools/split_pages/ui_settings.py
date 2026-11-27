# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'settings.ui'
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
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)

from utils.qt_widgets import (NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox)

class Ui_SplitPanel(object):
    def setupUi(self, SplitPanel):
        if not SplitPanel.objectName():
            SplitPanel.setObjectName(u"SplitPanel")
        self.main_layout = QVBoxLayout(SplitPanel)
        self.main_layout.setObjectName(u"main_layout")
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.general = QGroupBox(SplitPanel)
        self.general.setObjectName(u"general")
        self.general_form = QFormLayout(self.general)
        self.general_form.setObjectName(u"general_form")
        self.count_label = QLabel(self.general)
        self.count_label.setObjectName(u"count_label")

        self.general_form.setWidget(0, QFormLayout.LabelRole, self.count_label)

        self.count = NoWheelSpinBox(self.general)
        self.count.setObjectName(u"count")

        self.general_form.setWidget(0, QFormLayout.FieldRole, self.count)

        self.axis_label = QLabel(self.general)
        self.axis_label.setObjectName(u"axis_label")

        self.general_form.setWidget(1, QFormLayout.LabelRole, self.axis_label)

        self.axis = NoWheelComboBox(self.general)
        self.axis.setObjectName(u"axis")

        self.general_form.setWidget(1, QFormLayout.FieldRole, self.axis)

        self.order_label = QLabel(self.general)
        self.order_label.setObjectName(u"order_label")

        self.general_form.setWidget(2, QFormLayout.LabelRole, self.order_label)

        self.order = QLineEdit(self.general)
        self.order.setObjectName(u"order")

        self.general_form.setWidget(2, QFormLayout.FieldRole, self.order)

        self.reverse = QCheckBox(self.general)
        self.reverse.setObjectName(u"reverse")

        self.general_form.setWidget(3, QFormLayout.SpanningRole, self.reverse)

        self.start_label = QLabel(self.general)
        self.start_label.setObjectName(u"start_label")

        self.general_form.setWidget(4, QFormLayout.LabelRole, self.start_label)

        self.start = NoWheelSpinBox(self.general)
        self.start.setObjectName(u"start")

        self.general_form.setWidget(4, QFormLayout.FieldRole, self.start)

        self.end_label = QLabel(self.general)
        self.end_label.setObjectName(u"end_label")

        self.general_form.setWidget(5, QFormLayout.LabelRole, self.end_label)

        self.end = NoWheelSpinBox(self.general)
        self.end.setObjectName(u"end")

        self.general_form.setWidget(5, QFormLayout.FieldRole, self.end)

        self.range_note = QLabel(self.general)
        self.range_note.setObjectName(u"range_note")
        self.range_note.setWordWrap(True)

        self.general_form.setWidget(6, QFormLayout.SpanningRole, self.range_note)


        self.main_layout.addWidget(self.general)

        self.current = QGroupBox(SplitPanel)
        self.current.setObjectName(u"current")
        self.current_layout = QVBoxLayout(self.current)
        self.current_layout.setObjectName(u"current_layout")
        self.keep = QCheckBox(self.current)
        self.keep.setObjectName(u"keep")

        self.current_layout.addWidget(self.keep)

        self.reset = QPushButton(self.current)
        self.reset.setObjectName(u"reset")

        self.current_layout.addWidget(self.reset)

        self.geometry_controls = QWidget(self.current)
        self.geometry_controls.setObjectName(u"geometry_controls")
        self.crop_form = QFormLayout(self.geometry_controls)
        self.crop_form.setObjectName(u"crop_form")
        self.crop_form.setContentsMargins(0, 0, 0, 0)
        self.selection_label = QLabel(self.geometry_controls)
        self.selection_label.setObjectName(u"selection_label")

        self.crop_form.setWidget(0, QFormLayout.LabelRole, self.selection_label)

        self.selection = NoWheelComboBox(self.geometry_controls)
        self.selection.setObjectName(u"selection")

        self.crop_form.setWidget(0, QFormLayout.FieldRole, self.selection)

        self.crop_x_row_label = QLabel(self.geometry_controls)
        self.crop_x_row_label.setObjectName(u"crop_x_row_label")

        self.crop_form.setWidget(1, QFormLayout.LabelRole, self.crop_x_row_label)

        self.crop_x_row = QHBoxLayout()
        self.crop_x_row.setObjectName(u"crop_x_row")
        self.crop_x_row.setContentsMargins(0, 0, 0, 0)
        self.crop_x = NoWheelDoubleSpinBox(self.geometry_controls)
        self.crop_x.setObjectName(u"crop_x")
        self.crop_x.setMinimumSize(QSize(70, 0))

        self.crop_x_row.addWidget(self.crop_x)

        self.crop_x_minus = QPushButton(self.geometry_controls)
        self.crop_x_minus.setObjectName(u"crop_x_minus")
        self.crop_x_minus.setMinimumSize(QSize(40, 0))
        self.crop_x_minus.setMaximumSize(QSize(40, 16777215))

        self.crop_x_row.addWidget(self.crop_x_minus)

        self.crop_x_plus = QPushButton(self.geometry_controls)
        self.crop_x_plus.setObjectName(u"crop_x_plus")
        self.crop_x_plus.setMinimumSize(QSize(40, 0))
        self.crop_x_plus.setMaximumSize(QSize(40, 16777215))

        self.crop_x_row.addWidget(self.crop_x_plus)

        self.crop_x_row.setStretch(0, 1)

        self.crop_form.setLayout(1, QFormLayout.FieldRole, self.crop_x_row)

        self.crop_y_row_label = QLabel(self.geometry_controls)
        self.crop_y_row_label.setObjectName(u"crop_y_row_label")

        self.crop_form.setWidget(2, QFormLayout.LabelRole, self.crop_y_row_label)

        self.crop_y_row = QHBoxLayout()
        self.crop_y_row.setObjectName(u"crop_y_row")
        self.crop_y_row.setContentsMargins(0, 0, 0, 0)
        self.crop_y = NoWheelDoubleSpinBox(self.geometry_controls)
        self.crop_y.setObjectName(u"crop_y")
        self.crop_y.setMinimumSize(QSize(70, 0))

        self.crop_y_row.addWidget(self.crop_y)

        self.crop_y_minus = QPushButton(self.geometry_controls)
        self.crop_y_minus.setObjectName(u"crop_y_minus")
        self.crop_y_minus.setMinimumSize(QSize(40, 0))
        self.crop_y_minus.setMaximumSize(QSize(40, 16777215))

        self.crop_y_row.addWidget(self.crop_y_minus)

        self.crop_y_plus = QPushButton(self.geometry_controls)
        self.crop_y_plus.setObjectName(u"crop_y_plus")
        self.crop_y_plus.setMinimumSize(QSize(40, 0))
        self.crop_y_plus.setMaximumSize(QSize(40, 16777215))

        self.crop_y_row.addWidget(self.crop_y_plus)

        self.crop_y_row.setStretch(0, 1)

        self.crop_form.setLayout(2, QFormLayout.FieldRole, self.crop_y_row)

        self.crop_width_row_label = QLabel(self.geometry_controls)
        self.crop_width_row_label.setObjectName(u"crop_width_row_label")

        self.crop_form.setWidget(3, QFormLayout.LabelRole, self.crop_width_row_label)

        self.crop_width_row = QHBoxLayout()
        self.crop_width_row.setObjectName(u"crop_width_row")
        self.crop_width_row.setContentsMargins(0, 0, 0, 0)
        self.crop_width = NoWheelDoubleSpinBox(self.geometry_controls)
        self.crop_width.setObjectName(u"crop_width")
        self.crop_width.setMinimumSize(QSize(70, 0))

        self.crop_width_row.addWidget(self.crop_width)

        self.crop_width_minus = QPushButton(self.geometry_controls)
        self.crop_width_minus.setObjectName(u"crop_width_minus")
        self.crop_width_minus.setMinimumSize(QSize(40, 0))
        self.crop_width_minus.setMaximumSize(QSize(40, 16777215))

        self.crop_width_row.addWidget(self.crop_width_minus)

        self.crop_width_plus = QPushButton(self.geometry_controls)
        self.crop_width_plus.setObjectName(u"crop_width_plus")
        self.crop_width_plus.setMinimumSize(QSize(40, 0))
        self.crop_width_plus.setMaximumSize(QSize(40, 16777215))

        self.crop_width_row.addWidget(self.crop_width_plus)

        self.crop_width_row.setStretch(0, 1)

        self.crop_form.setLayout(3, QFormLayout.FieldRole, self.crop_width_row)

        self.crop_height_row_label = QLabel(self.geometry_controls)
        self.crop_height_row_label.setObjectName(u"crop_height_row_label")

        self.crop_form.setWidget(4, QFormLayout.LabelRole, self.crop_height_row_label)

        self.crop_height_row = QHBoxLayout()
        self.crop_height_row.setObjectName(u"crop_height_row")
        self.crop_height_row.setContentsMargins(0, 0, 0, 0)
        self.crop_height = NoWheelDoubleSpinBox(self.geometry_controls)
        self.crop_height.setObjectName(u"crop_height")
        self.crop_height.setMinimumSize(QSize(70, 0))

        self.crop_height_row.addWidget(self.crop_height)

        self.crop_height_minus = QPushButton(self.geometry_controls)
        self.crop_height_minus.setObjectName(u"crop_height_minus")
        self.crop_height_minus.setMinimumSize(QSize(40, 0))
        self.crop_height_minus.setMaximumSize(QSize(40, 16777215))

        self.crop_height_row.addWidget(self.crop_height_minus)

        self.crop_height_plus = QPushButton(self.geometry_controls)
        self.crop_height_plus.setObjectName(u"crop_height_plus")
        self.crop_height_plus.setMinimumSize(QSize(40, 0))
        self.crop_height_plus.setMaximumSize(QSize(40, 16777215))

        self.crop_height_row.addWidget(self.crop_height_plus)

        self.crop_height_row.setStretch(0, 1)

        self.crop_form.setLayout(4, QFormLayout.FieldRole, self.crop_height_row)

        self.divider_label = QLabel(self.geometry_controls)
        self.divider_label.setObjectName(u"divider_label")

        self.crop_form.setWidget(5, QFormLayout.LabelRole, self.divider_label)

        self.divider = NoWheelComboBox(self.geometry_controls)
        self.divider.setObjectName(u"divider")

        self.crop_form.setWidget(5, QFormLayout.FieldRole, self.divider)

        self.position_row_label = QLabel(self.geometry_controls)
        self.position_row_label.setObjectName(u"position_row_label")

        self.crop_form.setWidget(6, QFormLayout.LabelRole, self.position_row_label)

        self.position_row = QHBoxLayout()
        self.position_row.setObjectName(u"position_row")
        self.position = NoWheelDoubleSpinBox(self.geometry_controls)
        self.position.setObjectName(u"position")
        self.position.setMinimumSize(QSize(70, 0))

        self.position_row.addWidget(self.position)

        self.position_minus = QPushButton(self.geometry_controls)
        self.position_minus.setObjectName(u"position_minus")
        self.position_minus.setMinimumSize(QSize(40, 0))
        self.position_minus.setMaximumSize(QSize(40, 16777215))

        self.position_row.addWidget(self.position_minus)

        self.position_plus = QPushButton(self.geometry_controls)
        self.position_plus.setObjectName(u"position_plus")
        self.position_plus.setMinimumSize(QSize(40, 0))
        self.position_plus.setMaximumSize(QSize(40, 16777215))

        self.position_row.addWidget(self.position_plus)

        self.position_row.setStretch(0, 1)

        self.crop_form.setLayout(6, QFormLayout.FieldRole, self.position_row)

        self.crop_note = QLabel(self.geometry_controls)
        self.crop_note.setObjectName(u"crop_note")
        self.crop_note.setWordWrap(True)

        self.crop_form.setWidget(7, QFormLayout.SpanningRole, self.crop_note)


        self.current_layout.addWidget(self.geometry_controls)


        self.main_layout.addWidget(self.current)

        self.panel_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.main_layout.addItem(self.panel_stretch)

        self.main_layout.setStretch(2, 1)
#if QT_CONFIG(shortcut)
        self.count_label.setBuddy(self.count)
        self.axis_label.setBuddy(self.axis)
        self.order_label.setBuddy(self.order)
        self.start_label.setBuddy(self.start)
        self.end_label.setBuddy(self.end)
        self.selection_label.setBuddy(self.selection)
        self.divider_label.setBuddy(self.divider)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(SplitPanel)

        QMetaObject.connectSlotsByName(SplitPanel)
    # setupUi

    def retranslateUi(self, SplitPanel):
        self.general.setTitle(QCoreApplication.translate("SplitPanel", u"General", None))
        self.count_label.setText(QCoreApplication.translate("SplitPanel", u"Pieces per page", None))
        self.axis_label.setText(QCoreApplication.translate("SplitPanel", u"Arrangement", None))
        self.order_label.setText(QCoreApplication.translate("SplitPanel", u"Output order", None))
        self.reverse.setText(QCoreApplication.translate("SplitPanel", u"Reverse order", None))
        self.start_label.setText(QCoreApplication.translate("SplitPanel", u"First split page", None))
        self.end_label.setText(QCoreApplication.translate("SplitPanel", u"Last split page", None))
        self.range_note.setText(QCoreApplication.translate("SplitPanel", u"Outside this range: keep whole.\n"
"Custom pages retain their own crops and order.", None))
        self.current.setTitle(QCoreApplication.translate("SplitPanel", u"Current page", None))
        self.keep.setText(QCoreApplication.translate("SplitPanel", u"No processing (keep whole)", None))
        self.reset.setText(QCoreApplication.translate("SplitPanel", u"Reset to general settings", None))
        self.selection_label.setText(QCoreApplication.translate("SplitPanel", u"Crop", None))
        self.crop_x_row_label.setText(QCoreApplication.translate("SplitPanel", u"X", None))
        self.crop_x_minus.setText(QCoreApplication.translate("SplitPanel", u"-10", None))
        self.crop_x_plus.setText(QCoreApplication.translate("SplitPanel", u"+10", None))
        self.crop_y_row_label.setText(QCoreApplication.translate("SplitPanel", u"Y", None))
        self.crop_y_minus.setText(QCoreApplication.translate("SplitPanel", u"-10", None))
        self.crop_y_plus.setText(QCoreApplication.translate("SplitPanel", u"+10", None))
        self.crop_width_row_label.setText(QCoreApplication.translate("SplitPanel", u"Width", None))
        self.crop_width_minus.setText(QCoreApplication.translate("SplitPanel", u"-10", None))
        self.crop_width_plus.setText(QCoreApplication.translate("SplitPanel", u"+10", None))
        self.crop_height_row_label.setText(QCoreApplication.translate("SplitPanel", u"Height", None))
        self.crop_height_minus.setText(QCoreApplication.translate("SplitPanel", u"-10", None))
        self.crop_height_plus.setText(QCoreApplication.translate("SplitPanel", u"+10", None))
        self.divider_label.setText(QCoreApplication.translate("SplitPanel", u"Shared divider", None))
        self.position_row_label.setText(QCoreApplication.translate("SplitPanel", u"Divider position", None))
        self.position_minus.setText(QCoreApplication.translate("SplitPanel", u"-10", None))
        self.position_plus.setText(QCoreApplication.translate("SplitPanel", u"+10", None))
        self.crop_note.setText(QCoreApplication.translate("SplitPanel", u"Coordinates: top-left origin, in pt (1/72 inch).\n"
"Outside the source: blank. Smaller crops: centered on the same paper size.", None))
        pass
    # retranslateUi

