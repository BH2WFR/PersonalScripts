# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'properties.ui'
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
from PySide6.QtWidgets import (QApplication, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QSizePolicy,
    QSpacerItem, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget)

class Ui_Properties(object):
    def setupUi(self, Properties):
        if not Properties.objectName():
            Properties.setObjectName(u"Properties")
        self.main_layout = QVBoxLayout(Properties)
        self.main_layout.setObjectName(u"main_layout")
        self.fields_form = QFormLayout()
        self.fields_form.setObjectName(u"fields_form")
        self.title_row_label = QLabel(Properties)
        self.title_row_label.setObjectName(u"title_row_label")

        self.fields_form.setWidget(0, QFormLayout.LabelRole, self.title_row_label)

        self.title_row = QHBoxLayout()
        self.title_row.setObjectName(u"title_row")
        self.title_field = QLineEdit(Properties)
        self.title_field.setObjectName(u"title_field")

        self.title_row.addWidget(self.title_field)

        self.edit_titles = QPushButton(Properties)
        self.edit_titles.setObjectName(u"edit_titles")

        self.title_row.addWidget(self.edit_titles)


        self.fields_form.setLayout(0, QFormLayout.FieldRole, self.title_row)

        self.author_field_label = QLabel(Properties)
        self.author_field_label.setObjectName(u"author_field_label")

        self.fields_form.setWidget(1, QFormLayout.LabelRole, self.author_field_label)

        self.author_field = QLineEdit(Properties)
        self.author_field.setObjectName(u"author_field")

        self.fields_form.setWidget(1, QFormLayout.FieldRole, self.author_field)

        self.subject_field_label = QLabel(Properties)
        self.subject_field_label.setObjectName(u"subject_field_label")

        self.fields_form.setWidget(2, QFormLayout.LabelRole, self.subject_field_label)

        self.subject_field = QLineEdit(Properties)
        self.subject_field.setObjectName(u"subject_field")

        self.fields_form.setWidget(2, QFormLayout.FieldRole, self.subject_field)

        self.keywords_field_label = QLabel(Properties)
        self.keywords_field_label.setObjectName(u"keywords_field_label")

        self.fields_form.setWidget(3, QFormLayout.LabelRole, self.keywords_field_label)

        self.keywords_field = QLineEdit(Properties)
        self.keywords_field.setObjectName(u"keywords_field")

        self.fields_form.setWidget(3, QFormLayout.FieldRole, self.keywords_field)

        self.creator_field_label = QLabel(Properties)
        self.creator_field_label.setObjectName(u"creator_field_label")

        self.fields_form.setWidget(4, QFormLayout.LabelRole, self.creator_field_label)

        self.creator_field = QLineEdit(Properties)
        self.creator_field.setObjectName(u"creator_field")

        self.fields_form.setWidget(4, QFormLayout.FieldRole, self.creator_field)

        self.producer_field_label = QLabel(Properties)
        self.producer_field_label.setObjectName(u"producer_field_label")

        self.fields_form.setWidget(5, QFormLayout.LabelRole, self.producer_field_label)

        self.producer_field = QLineEdit(Properties)
        self.producer_field.setObjectName(u"producer_field")

        self.fields_form.setWidget(5, QFormLayout.FieldRole, self.producer_field)


        self.main_layout.addLayout(self.fields_form)

        self.extra_actions = QHBoxLayout()
        self.extra_actions.setObjectName(u"extra_actions")
        self.extra_label = QLabel(Properties)
        self.extra_label.setObjectName(u"extra_label")

        self.extra_actions.addWidget(self.extra_label)

        self.actions_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.extra_actions.addItem(self.actions_stretch)

        self.add = QPushButton(Properties)
        self.add.setObjectName(u"add")

        self.extra_actions.addWidget(self.add)

        self.remove = QPushButton(Properties)
        self.remove.setObjectName(u"remove")

        self.extra_actions.addWidget(self.remove)


        self.main_layout.addLayout(self.extra_actions)

        self.table = QTableWidget(Properties)
        if (self.table.columnCount() < 3):
            self.table.setColumnCount(3)
        __qtablewidgetitem = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        self.table.setObjectName(u"table")

        self.main_layout.addWidget(self.table)

#if QT_CONFIG(shortcut)
        self.author_field_label.setBuddy(self.author_field)
        self.subject_field_label.setBuddy(self.subject_field)
        self.keywords_field_label.setBuddy(self.keywords_field)
        self.creator_field_label.setBuddy(self.creator_field)
        self.producer_field_label.setBuddy(self.producer_field)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(Properties)

        QMetaObject.connectSlotsByName(Properties)
    # setupUi

    def retranslateUi(self, Properties):
        self.title_row_label.setText(QCoreApplication.translate("Properties", u"Title", None))
        self.edit_titles.setText(QCoreApplication.translate("Properties", u"Multilingual\u2026", None))
        self.author_field_label.setText(QCoreApplication.translate("Properties", u"Author", None))
        self.subject_field_label.setText(QCoreApplication.translate("Properties", u"Subject", None))
        self.keywords_field_label.setText(QCoreApplication.translate("Properties", u"Keywords", None))
        self.creator_field_label.setText(QCoreApplication.translate("Properties", u"Creator", None))
        self.producer_field_label.setText(QCoreApplication.translate("Properties", u"Producer", None))
        self.extra_label.setText(QCoreApplication.translate("Properties", u"Additional document properties", None))
        self.add.setText(QCoreApplication.translate("Properties", u"Add property", None))
        self.remove.setText(QCoreApplication.translate("Properties", u"Remove", None))
        ___qtablewidgetitem = self.table.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("Properties", u"Property", None));
        ___qtablewidgetitem1 = self.table.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("Properties", u"Format", None));
        ___qtablewidgetitem2 = self.table.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("Properties", u"Value", None));
        pass
    # retranslateUi

