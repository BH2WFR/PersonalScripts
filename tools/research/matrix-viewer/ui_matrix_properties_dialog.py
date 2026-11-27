# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'matrix_properties_dialog.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDialog, QDialogButtonBox,
    QHeaderView, QLabel, QPushButton, QSizePolicy,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget)

class Ui_MatrixPropertiesDialog(object):
    def setupUi(self, MatrixPropertiesDialog):
        if not MatrixPropertiesDialog.objectName():
            MatrixPropertiesDialog.setObjectName(u"MatrixPropertiesDialog")
        MatrixPropertiesDialog.resize(880, 640)
        self.form_layout = QVBoxLayout(MatrixPropertiesDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.form_identity = QLabel(MatrixPropertiesDialog)
        self.form_identity.setObjectName(u"form_identity")
        self.form_identity.setWordWrap(True)

        self.form_layout.addWidget(self.form_identity)

        self.tabs = QTabWidget(MatrixPropertiesDialog)
        self.tabs.setObjectName(u"tabs")
        self.metadata = QTreeWidget()
        self.metadata.setObjectName(u"metadata")
        self.metadata.setWordWrap(True)
        self.tabs.addTab(self.metadata, "")
        self.form_page = QWidget()
        self.form_page.setObjectName(u"form_page")
        self.form_stats_layout = QVBoxLayout(self.form_page)
        self.form_stats_layout.setObjectName(u"form_stats_layout")
        self.form_help_text = QLabel(self.form_page)
        self.form_help_text.setObjectName(u"form_help_text")
        self.form_help_text.setWordWrap(True)

        self.form_stats_layout.addWidget(self.form_help_text)

        self.calculate = QPushButton(self.form_page)
        self.calculate.setObjectName(u"calculate")

        self.form_stats_layout.addWidget(self.calculate)

        self.status = QLabel(self.form_page)
        self.status.setObjectName(u"status")

        self.form_stats_layout.addWidget(self.status)

        self.statistics = QTreeWidget(self.form_page)
        self.statistics.setObjectName(u"statistics")

        self.form_stats_layout.addWidget(self.statistics)

        self.form_stats_layout.setStretch(3, 1)
        self.tabs.addTab(self.form_page, "")

        self.form_layout.addWidget(self.tabs)

        self.form_close = QDialogButtonBox(MatrixPropertiesDialog)
        self.form_close.setObjectName(u"form_close")
        self.form_close.setStandardButtons(QDialogButtonBox.Close)

        self.form_layout.addWidget(self.form_close)

        self.form_layout.setStretch(1, 1)

        self.retranslateUi(MatrixPropertiesDialog)

        QMetaObject.connectSlotsByName(MatrixPropertiesDialog)
    # setupUi

    def retranslateUi(self, MatrixPropertiesDialog):
        MatrixPropertiesDialog.setWindowTitle(QCoreApplication.translate("MatrixPropertiesDialog", u"Matrix properties", None))
        self.tabs.setTabText(self.tabs.indexOf(self.metadata), QCoreApplication.translate("MatrixPropertiesDialog", u"Metadata / display", None))
        self.form_help_text.setText(QCoreApplication.translate("MatrixPropertiesDialog", u"Click Calculate statistics to scan samples. Statistics use finite values only; variance / standard deviation use ddof=0.\n"
"NaN is excluded from extrema. inf (90000) means an infinite extreme with finite extreme 90000.\n"
"Original matrix and current channel/crop are separate populations; value bounds do not alter these statistics.\n"
"Exact quartiles use linear interpolation and require a temporary copy of finite values, one population at a time.", None))
        self.calculate.setText(QCoreApplication.translate("MatrixPropertiesDialog", u"Calculate statistics", None))
        self.tabs.setTabText(self.tabs.indexOf(self.form_page), QCoreApplication.translate("MatrixPropertiesDialog", u"Statistics", None))
    # retranslateUi

