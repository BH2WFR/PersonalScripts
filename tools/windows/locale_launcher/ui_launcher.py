# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'launcher.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)

from utils.qt_widgets import NoWheelComboBox

class Ui_Launcher(object):
    def setupUi(self, Launcher):
        if not Launcher.objectName():
            Launcher.setObjectName(u"Launcher")
        Launcher.resize(704, 298)
        self.main_layout = QVBoxLayout(Launcher)
        self.main_layout.setObjectName(u"main_layout")
        self.target_row = QHBoxLayout()
        self.target_row.setObjectName(u"target_row")
        self.path = QLineEdit(Launcher)
        self.path.setObjectName(u"path")

        self.target_row.addWidget(self.path)

        self.open_button = QPushButton(Launcher)
        self.open_button.setObjectName(u"open_button")

        self.target_row.addWidget(self.open_button)

        self.paste_button = QPushButton(Launcher)
        self.paste_button.setObjectName(u"paste_button")

        self.target_row.addWidget(self.paste_button)

        self.target_row.setStretch(0, 1)

        self.main_layout.addLayout(self.target_row)

        self.arguments_row = QHBoxLayout()
        self.arguments_row.setObjectName(u"arguments_row")
        self.arguments_label = QLabel(Launcher)
        self.arguments_label.setObjectName(u"arguments_label")

        self.arguments_row.addWidget(self.arguments_label)

        self.arguments = QLineEdit(Launcher)
        self.arguments.setObjectName(u"arguments")

        self.arguments_row.addWidget(self.arguments)

        self.arguments_row.setStretch(1, 1)

        self.main_layout.addLayout(self.arguments_row)

        self.directory_row = QHBoxLayout()
        self.directory_row.setObjectName(u"directory_row")
        self.directory_label = QLabel(Launcher)
        self.directory_label.setObjectName(u"directory_label")

        self.directory_row.addWidget(self.directory_label)

        self.directory = QLineEdit(Launcher)
        self.directory.setObjectName(u"directory")

        self.directory_row.addWidget(self.directory)

        self.folder_button = QPushButton(Launcher)
        self.folder_button.setObjectName(u"folder_button")

        self.directory_row.addWidget(self.folder_button)

        self.directory_row.setStretch(1, 1)

        self.main_layout.addLayout(self.directory_row)

        self.fields = QGridLayout()
        self.fields.setObjectName(u"fields")
        self.launch_heading = QLabel(Launcher)
        self.launch_heading.setObjectName(u"launch_heading")

        self.fields.addWidget(self.launch_heading, 1, 1, 1, 1)

        self.host_heading = QLabel(Launcher)
        self.host_heading.setObjectName(u"host_heading")

        self.fields.addWidget(self.host_heading, 1, 3, 1, 1)

        self.region_label = QLabel(Launcher)
        self.region_label.setObjectName(u"region_label")

        self.fields.addWidget(self.region_label, 2, 0, 1, 1)

        self.region = NoWheelComboBox(Launcher)
        self.region.setObjectName(u"region")
        self.region.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.region.setMinimumContentsLength(27)

        self.fields.addWidget(self.region, 2, 1, 1, 1)

        self.host_region = QLabel(Launcher)
        self.host_region.setObjectName(u"host_region")
        self.host_region.setWordWrap(True)

        self.fields.addWidget(self.host_region, 2, 3, 1, 1)

        self.page_label = QLabel(Launcher)
        self.page_label.setObjectName(u"page_label")

        self.fields.addWidget(self.page_label, 3, 0, 1, 1)

        self.page = NoWheelComboBox(Launcher)
        self.page.setObjectName(u"page")
        self.page.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.page.setMinimumContentsLength(27)

        self.fields.addWidget(self.page, 3, 1, 1, 1)

        self.host_page = QLabel(Launcher)
        self.host_page.setObjectName(u"host_page")
        self.host_page.setWordWrap(True)

        self.fields.addWidget(self.host_page, 3, 3, 1, 1)

        self.language_label = QLabel(Launcher)
        self.language_label.setObjectName(u"language_label")

        self.fields.addWidget(self.language_label, 4, 0, 1, 1)

        self.language = NoWheelComboBox(Launcher)
        self.language.setObjectName(u"language")
        self.language.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.language.setMinimumContentsLength(27)

        self.fields.addWidget(self.language, 4, 1, 1, 1)

        self.host_language = QLabel(Launcher)
        self.host_language.setObjectName(u"host_language")
        self.host_language.setWordWrap(True)

        self.fields.addWidget(self.host_language, 4, 3, 1, 1)

        self.zone_label = QLabel(Launcher)
        self.zone_label.setObjectName(u"zone_label")

        self.fields.addWidget(self.zone_label, 5, 0, 1, 1)

        self.zone = NoWheelComboBox(Launcher)
        self.zone.setObjectName(u"zone")
        self.zone.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.zone.setMinimumContentsLength(27)

        self.fields.addWidget(self.zone, 5, 1, 1, 1)

        self.host_zone = QLabel(Launcher)
        self.host_zone.setObjectName(u"host_zone")
        self.host_zone.setWordWrap(True)

        self.fields.addWidget(self.host_zone, 5, 3, 1, 1)

        self.divider = QFrame(Launcher)
        self.divider.setObjectName(u"divider")
        self.divider.setFrameShape(QFrame.Shape.VLine)
        self.divider.setFrameShadow(QFrame.Shadow.Sunken)

        self.fields.addWidget(self.divider, 0, 2, 6, 1)

        self.fields.setColumnStretch(1, 3)
        self.fields.setColumnStretch(3, 2)

        self.main_layout.addLayout(self.fields)

        self.button_row = QHBoxLayout()
        self.button_row.setObjectName(u"button_row")
        self.button_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.button_row.addItem(self.button_spacer)

        self.admin_button = QPushButton(Launcher)
        self.admin_button.setObjectName(u"admin_button")

        self.button_row.addWidget(self.admin_button)

        self.run_button = QPushButton(Launcher)
        self.run_button.setObjectName(u"run_button")

        self.button_row.addWidget(self.run_button)


        self.main_layout.addLayout(self.button_row)

#if QT_CONFIG(shortcut)
        self.arguments_label.setBuddy(self.arguments)
        self.directory_label.setBuddy(self.directory)
        self.region_label.setBuddy(self.region)
        self.page_label.setBuddy(self.page)
        self.language_label.setBuddy(self.language)
        self.zone_label.setBuddy(self.zone)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(Launcher)

        QMetaObject.connectSlotsByName(Launcher)
    # setupUi

    def retranslateUi(self, Launcher):
        Launcher.setWindowTitle(QCoreApplication.translate("Launcher", u"Locale Launcher", None))
        self.path.setPlaceholderText(QCoreApplication.translate("Launcher", u"Drop an .exe or .com here", None))
#if QT_CONFIG(accessibility)
        self.path.setAccessibleName(QCoreApplication.translate("Launcher", u"Target executable", None))
#endif // QT_CONFIG(accessibility)
        self.open_button.setText(QCoreApplication.translate("Launcher", u"Open\u2026", None))
        self.paste_button.setText(QCoreApplication.translate("Launcher", u"Paste", None))
        self.arguments_label.setText(QCoreApplication.translate("Launcher", u"Arguments", None))
        self.arguments.setPlaceholderText(QCoreApplication.translate("Launcher", u"Optional command-line arguments", None))
#if QT_CONFIG(accessibility)
        self.arguments.setAccessibleName(QCoreApplication.translate("Launcher", u"Arguments", None))
#endif // QT_CONFIG(accessibility)
        self.directory_label.setText(QCoreApplication.translate("Launcher", u"Start in", None))
#if QT_CONFIG(accessibility)
        self.directory.setAccessibleName(QCoreApplication.translate("Launcher", u"Working directory", None))
#endif // QT_CONFIG(accessibility)
        self.folder_button.setText(QCoreApplication.translate("Launcher", u"Open folder\u2026", None))
        self.launch_heading.setText(QCoreApplication.translate("Launcher", u"Launch settings", None))
        self.host_heading.setText(QCoreApplication.translate("Launcher", u"This computer", None))
        self.region_label.setText(QCoreApplication.translate("Launcher", u"Region", None))
#if QT_CONFIG(accessibility)
        self.region.setAccessibleName(QCoreApplication.translate("Launcher", u"Region", None))
#endif // QT_CONFIG(accessibility)
        self.page_label.setText(QCoreApplication.translate("Launcher", u"Code page", None))
#if QT_CONFIG(accessibility)
        self.page.setAccessibleName(QCoreApplication.translate("Launcher", u"Code page", None))
#endif // QT_CONFIG(accessibility)
        self.language_label.setText(QCoreApplication.translate("Launcher", u"UI language", None))
#if QT_CONFIG(accessibility)
        self.language.setAccessibleName(QCoreApplication.translate("Launcher", u"UI language", None))
#endif // QT_CONFIG(accessibility)
        self.zone_label.setText(QCoreApplication.translate("Launcher", u"Time zone", None))
#if QT_CONFIG(accessibility)
        self.zone.setAccessibleName(QCoreApplication.translate("Launcher", u"Time zone", None))
#endif // QT_CONFIG(accessibility)
        self.admin_button.setText(QCoreApplication.translate("Launcher", u"Run as administrator", None))
        self.run_button.setText(QCoreApplication.translate("Launcher", u"Run", None))
    # retranslateUi

