# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'mainwindow.ui'
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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QSizePolicy,
    QSpacerItem, QVBoxLayout, QWidget)

from unicode_inspector.editor import OriginalEditor
from unicode_inspector.table import CharacterTable

class Ui_UnicodeInspector(object):
    def setupUi(self, UnicodeInspector):
        if not UnicodeInspector.objectName():
            UnicodeInspector.setObjectName(u"UnicodeInspector")
        UnicodeInspector.resize(1100, 720)
        UnicodeInspector.setMinimumSize(QSize(800, 500))
        self.main_layout = QVBoxLayout(UnicodeInspector)
        self.main_layout.setSpacing(0)
        self.main_layout.setObjectName(u"main_layout")
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.header_layout = QHBoxLayout()
        self.header_layout.setSpacing(8)
        self.header_layout.setObjectName(u"header_layout")
        self.source_label = QLabel(UnicodeInspector)
        self.source_label.setObjectName(u"source_label")

        self.header_layout.addWidget(self.source_label)

        self.paste_button = QPushButton(UnicodeInspector)
        self.paste_button.setObjectName(u"paste_button")
        font = QFont()
        font.setBold(True)
        self.paste_button.setFont(font)

        self.header_layout.addWidget(self.paste_button)

        self.clear_button = QPushButton(UnicodeInspector)
        self.clear_button.setObjectName(u"clear_button")

        self.header_layout.addWidget(self.clear_button)

        self.analyze_button = QPushButton(UnicodeInspector)
        self.analyze_button.setObjectName(u"analyze_button")

        self.header_layout.addWidget(self.analyze_button)

        self.header_layout.setStretch(0, 1)

        self.main_layout.addLayout(self.header_layout)

        self.header_spacing = QSpacerItem(0, 6, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.main_layout.addItem(self.header_spacing)

        self.original = OriginalEditor(UnicodeInspector)
        self.original.setObjectName(u"original")
        self.original.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        self.main_layout.addWidget(self.original)

        self.source_spacing = QSpacerItem(0, 12, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.main_layout.addItem(self.source_spacing)

        self.summary_layout = QHBoxLayout()
        self.summary_layout.setSpacing(5)
        self.summary_layout.setObjectName(u"summary_layout")
        self.character_count_label = QLabel(UnicodeInspector)
        self.character_count_label.setObjectName(u"character_count_label")

        self.summary_layout.addWidget(self.character_count_label)

        self.character_count = QLineEdit(UnicodeInspector)
        self.character_count.setObjectName(u"character_count")
        self.character_count.setReadOnly(True)
        self.character_count.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.summary_layout.addWidget(self.character_count)

        self.character_count_spacing = QSpacerItem(9, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.summary_layout.addItem(self.character_count_spacing)

        self.utf8_bytes_label = QLabel(UnicodeInspector)
        self.utf8_bytes_label.setObjectName(u"utf8_bytes_label")

        self.summary_layout.addWidget(self.utf8_bytes_label)

        self.utf8_bytes = QLineEdit(UnicodeInspector)
        self.utf8_bytes.setObjectName(u"utf8_bytes")
        self.utf8_bytes.setReadOnly(True)
        self.utf8_bytes.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.summary_layout.addWidget(self.utf8_bytes)

        self.utf8_bytes_spacing = QSpacerItem(9, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.summary_layout.addItem(self.utf8_bytes_spacing)

        self.utf16_bytes_label = QLabel(UnicodeInspector)
        self.utf16_bytes_label.setObjectName(u"utf16_bytes_label")

        self.summary_layout.addWidget(self.utf16_bytes_label)

        self.utf16_bytes = QLineEdit(UnicodeInspector)
        self.utf16_bytes.setObjectName(u"utf16_bytes")
        self.utf16_bytes.setReadOnly(True)
        self.utf16_bytes.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.summary_layout.addWidget(self.utf16_bytes)

        self.utf16_bytes_spacing = QSpacerItem(9, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.summary_layout.addItem(self.utf16_bytes_spacing)

        self.word_count_label = QLabel(UnicodeInspector)
        self.word_count_label.setObjectName(u"word_count_label")

        self.summary_layout.addWidget(self.word_count_label)

        self.word_count = QLineEdit(UnicodeInspector)
        self.word_count.setObjectName(u"word_count")
        self.word_count.setReadOnly(True)
        self.word_count.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.summary_layout.addWidget(self.word_count)

        self.word_count_spacing = QSpacerItem(9, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.summary_layout.addItem(self.word_count_spacing)

        self.line_count_label = QLabel(UnicodeInspector)
        self.line_count_label.setObjectName(u"line_count_label")

        self.summary_layout.addWidget(self.line_count_label)

        self.line_count = QLineEdit(UnicodeInspector)
        self.line_count.setObjectName(u"line_count")
        self.line_count.setReadOnly(True)
        self.line_count.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.summary_layout.addWidget(self.line_count)

        self.line_count_spacing = QSpacerItem(9, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.summary_layout.addItem(self.line_count_spacing)

        self.summary_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.summary_layout.addItem(self.summary_stretch)


        self.main_layout.addLayout(self.summary_layout)

        self.summary_spacing = QSpacerItem(0, 12, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.main_layout.addItem(self.summary_spacing)

        self.table = CharacterTable(UnicodeInspector)
        self.table.setObjectName(u"table")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setMinimumSectionSize(50)
        self.table.verticalHeader().setVisible(False)

        self.main_layout.addWidget(self.table)

        self.table_spacing = QSpacerItem(0, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.main_layout.addItem(self.table_spacing)

        self.footer_layout = QHBoxLayout()
        self.footer_layout.setSpacing(8)
        self.footer_layout.setObjectName(u"footer_layout")
        self.status = QLabel(UnicodeInspector)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)

        self.footer_layout.addWidget(self.status)

        self.copy_original_button = QPushButton(UnicodeInspector)
        self.copy_original_button.setObjectName(u"copy_original_button")

        self.footer_layout.addWidget(self.copy_original_button)

        self.copy_rows_button = QPushButton(UnicodeInspector)
        self.copy_rows_button.setObjectName(u"copy_rows_button")

        self.footer_layout.addWidget(self.copy_rows_button)

        self.copy_report_button = QPushButton(UnicodeInspector)
        self.copy_report_button.setObjectName(u"copy_report_button")

        self.footer_layout.addWidget(self.copy_report_button)

        self.footer_layout.setStretch(0, 1)

        self.main_layout.addLayout(self.footer_layout)

        self.main_layout.setStretch(6, 1)

        self.retranslateUi(UnicodeInspector)

        QMetaObject.connectSlotsByName(UnicodeInspector)
    # setupUi

    def retranslateUi(self, UnicodeInspector):
        UnicodeInspector.setWindowTitle(QCoreApplication.translate("UnicodeInspector", u"Unicode Inspector", None))
        self.source_label.setText(QCoreApplication.translate("UnicodeInspector", u"Text to inspect", None))
        self.paste_button.setText(QCoreApplication.translate("UnicodeInspector", u"Paste", None))
        self.clear_button.setText(QCoreApplication.translate("UnicodeInspector", u"Clear", None))
        self.analyze_button.setText(QCoreApplication.translate("UnicodeInspector", u"Analyze", None))
#if QT_CONFIG(accessibility)
        self.original.setAccessibleName(QCoreApplication.translate("UnicodeInspector", u"Text to inspect", None))
#endif // QT_CONFIG(accessibility)
        self.character_count_label.setText(QCoreApplication.translate("UnicodeInspector", u"Characters", None))
#if QT_CONFIG(accessibility)
        self.character_count.setAccessibleName(QCoreApplication.translate("UnicodeInspector", u"Characters", None))
#endif // QT_CONFIG(accessibility)
        self.utf8_bytes_label.setText(QCoreApplication.translate("UnicodeInspector", u"UTF-8 bytes", None))
#if QT_CONFIG(accessibility)
        self.utf8_bytes.setAccessibleName(QCoreApplication.translate("UnicodeInspector", u"UTF-8 bytes", None))
#endif // QT_CONFIG(accessibility)
        self.utf16_bytes_label.setText(QCoreApplication.translate("UnicodeInspector", u"UTF-16 bytes", None))
#if QT_CONFIG(accessibility)
        self.utf16_bytes.setAccessibleName(QCoreApplication.translate("UnicodeInspector", u"UTF-16 bytes", None))
#endif // QT_CONFIG(accessibility)
        self.word_count_label.setText(QCoreApplication.translate("UnicodeInspector", u"Words", None))
#if QT_CONFIG(accessibility)
        self.word_count.setAccessibleName(QCoreApplication.translate("UnicodeInspector", u"Words", None))
#endif // QT_CONFIG(accessibility)
        self.line_count_label.setText(QCoreApplication.translate("UnicodeInspector", u"Lines", None))
#if QT_CONFIG(accessibility)
        self.line_count.setAccessibleName(QCoreApplication.translate("UnicodeInspector", u"Lines", None))
#endif // QT_CONFIG(accessibility)
        self.copy_original_button.setText(QCoreApplication.translate("UnicodeInspector", u"Copy Original", None))
        self.copy_rows_button.setText(QCoreApplication.translate("UnicodeInspector", u"Copy Selected Rows", None))
        self.copy_report_button.setText(QCoreApplication.translate("UnicodeInspector", u"Copy Full Report", None))
    # retranslateUi

