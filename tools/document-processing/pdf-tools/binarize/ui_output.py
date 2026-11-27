# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'output.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QSpacerItem,
    QVBoxLayout, QWidget)

from utils.qt_widgets import NoWheelSpinBox

class Ui_OutputTab(object):
    def setupUi(self, OutputTab):
        if not OutputTab.objectName():
            OutputTab.setObjectName(u"OutputTab")
        OutputTab.setWidgetResizable(True)
        self.output_page = QWidget()
        self.output_page.setObjectName(u"output_page")
        self.output_layout = QVBoxLayout(self.output_page)
        self.output_layout.setObjectName(u"output_layout")
        self.export_group = QGroupBox(self.output_page)
        self.export_group.setObjectName(u"export_group")
        self.export_form = QFormLayout(self.export_group)
        self.export_form.setObjectName(u"export_form")
        self.workers_label = QLabel(self.export_group)
        self.workers_label.setObjectName(u"workers_label")

        self.export_form.setWidget(0, QFormLayout.LabelRole, self.workers_label)

        self.workers = NoWheelSpinBox(self.export_group)
        self.workers.setObjectName(u"workers")

        self.export_form.setWidget(0, QFormLayout.FieldRole, self.workers)

        self.open_saved_preview = QCheckBox(self.export_group)
        self.open_saved_preview.setObjectName(u"open_saved_preview")

        self.export_form.setWidget(1, QFormLayout.SpanningRole, self.open_saved_preview)


        self.output_layout.addWidget(self.export_group)

        self.separator = QFrame(self.output_page)
        self.separator.setObjectName(u"separator")
        self.separator.setFrameShape(QFrame.HLine)

        self.output_layout.addWidget(self.separator)

        self.review_group = QGroupBox(self.output_page)
        self.review_group.setObjectName(u"review_group")
        self.review_form = QFormLayout(self.review_group)
        self.review_form.setObjectName(u"review_form")
        self.save_regions = QCheckBox(self.review_group)
        self.save_regions.setObjectName(u"save_regions")

        self.review_form.setWidget(0, QFormLayout.SpanningRole, self.save_regions)

        self.save_annotations = QCheckBox(self.review_group)
        self.save_annotations.setObjectName(u"save_annotations")

        self.review_form.setWidget(1, QFormLayout.SpanningRole, self.save_annotations)

        self.region_path_label = QLabel(self.review_group)
        self.region_path_label.setObjectName(u"region_path_label")

        self.review_form.setWidget(2, QFormLayout.LabelRole, self.region_path_label)

        self.region_path = QLineEdit(self.review_group)
        self.region_path.setObjectName(u"region_path")

        self.review_form.setWidget(2, QFormLayout.FieldRole, self.region_path)

        self.region_actions = QHBoxLayout()
        self.region_actions.setObjectName(u"region_actions")
        self.browse_regions = QPushButton(self.review_group)
        self.browse_regions.setObjectName(u"browse_regions")

        self.region_actions.addWidget(self.browse_regions)

        self.clear_regions = QPushButton(self.review_group)
        self.clear_regions.setObjectName(u"clear_regions")

        self.region_actions.addWidget(self.clear_regions)


        self.review_form.setLayout(3, QFormLayout.SpanningRole, self.region_actions)


        self.output_layout.addWidget(self.review_group)

        self.output_note = QLabel(self.output_page)
        self.output_note.setObjectName(u"output_note")
        self.output_note.setWordWrap(True)

        self.output_layout.addWidget(self.output_note)

        self.output_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.output_layout.addItem(self.output_stretch)

        OutputTab.setWidget(self.output_page)
#if QT_CONFIG(shortcut)
        self.workers_label.setBuddy(self.workers)
        self.region_path_label.setBuddy(self.region_path)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(OutputTab)

        QMetaObject.connectSlotsByName(OutputTab)
    # setupUi

    def retranslateUi(self, OutputTab):
        self.export_group.setTitle(QCoreApplication.translate("OutputTab", u"Export", None))
        self.workers_label.setText(QCoreApplication.translate("OutputTab", u"Image encoders", None))
        self.open_saved_preview.setText(QCoreApplication.translate("OutputTab", u"Open saved page in external viewer", None))
        self.review_group.setTitle(QCoreApplication.translate("OutputTab", u"Optional region review files", None))
        self.save_regions.setText(QCoreApplication.translate("OutputTab", u"Export region JSON", None))
        self.save_annotations.setText(QCoreApplication.translate("OutputTab", u"Export box annotation PNGs", None))
        self.region_path_label.setText(QCoreApplication.translate("OutputTab", u"Region input", None))
        self.browse_regions.setText(QCoreApplication.translate("OutputTab", u"Browse regions...", None))
        self.clear_regions.setText(QCoreApplication.translate("OutputTab", u"Clear", None))
        self.output_note.setText(QCoreApplication.translate("OutputTab", u"These settings apply to the whole project.\n"
"Export defaults to the source PDF folder.\n"
"Existing outputs require overwrite confirmation; the source is protected.", None))
        pass
    # retranslateUi

