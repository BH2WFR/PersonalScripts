# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'scaling_dialog.ui'
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
    QDialogButtonBox, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget)

class Ui_ScalingDialog(object):
    def setupUi(self, ScalingDialog):
        if not ScalingDialog.objectName():
            ScalingDialog.setObjectName(u"ScalingDialog")
        ScalingDialog.resize(600, 320)
        self.form_layout = QVBoxLayout(ScalingDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.form_note = QLabel(ScalingDialog)
        self.form_note.setObjectName(u"form_note")
        self.form_note.setWordWrap(True)

        self.form_layout.addWidget(self.form_note)

        self.form_auto = QPushButton(ScalingDialog)
        self.form_auto.setObjectName(u"form_auto")

        self.form_layout.addWidget(self.form_auto)

        self.endpoint_ticks = QCheckBox(ScalingDialog)
        self.endpoint_ticks.setObjectName(u"endpoint_ticks")

        self.form_layout.addWidget(self.endpoint_ticks)

        self.y_lock = QCheckBox(ScalingDialog)
        self.y_lock.setObjectName(u"y_lock")

        self.form_layout.addWidget(self.y_lock)

        self.form_grid = QGridLayout()
        self.form_grid.setObjectName(u"form_grid")

        self.form_layout.addLayout(self.form_grid)

        self.form_apply = QPushButton(ScalingDialog)
        self.form_apply.setObjectName(u"form_apply")

        self.form_layout.addWidget(self.form_apply)

        self.form_presets = QHBoxLayout()
        self.form_presets.setObjectName(u"form_presets")

        self.form_layout.addLayout(self.form_presets)

        self.equal_lock = QCheckBox(ScalingDialog)
        self.equal_lock.setObjectName(u"equal_lock")

        self.form_layout.addWidget(self.equal_lock)

        self.geometry_box = QGroupBox(ScalingDialog)
        self.geometry_box.setObjectName(u"geometry_box")
        self.form_geometry_layout = QGridLayout(self.geometry_box)
        self.form_geometry_layout.setObjectName(u"form_geometry_layout")
        self.apply_geometry = QPushButton(self.geometry_box)
        self.apply_geometry.setObjectName(u"apply_geometry")

        self.form_geometry_layout.addWidget(self.apply_geometry, 1, 0, 1, 2)

        self.auto_geometry = QPushButton(self.geometry_box)
        self.auto_geometry.setObjectName(u"auto_geometry")

        self.form_geometry_layout.addWidget(self.auto_geometry, 1, 2, 1, 2)

        self.form_geometry_note = QLabel(self.geometry_box)
        self.form_geometry_note.setObjectName(u"form_geometry_note")
        self.form_geometry_note.setWordWrap(True)

        self.form_geometry_layout.addWidget(self.form_geometry_note, 2, 0, 1, 4)

        self.z_lock = QCheckBox(self.geometry_box)
        self.z_lock.setObjectName(u"z_lock")

        self.form_geometry_layout.addWidget(self.z_lock, 4, 0, 1, 4)


        self.form_layout.addWidget(self.geometry_box)

        self.color_box = QGroupBox(ScalingDialog)
        self.color_box.setObjectName(u"color_box")
        self.form_color_layout = QGridLayout(self.color_box)
        self.form_color_layout.setObjectName(u"form_color_layout")
        self.apply_colors = QPushButton(self.color_box)
        self.apply_colors.setObjectName(u"apply_colors")

        self.form_color_layout.addWidget(self.apply_colors, 1, 0, 1, 2)

        self.auto_colors = QPushButton(self.color_box)
        self.auto_colors.setObjectName(u"auto_colors")

        self.form_color_layout.addWidget(self.auto_colors, 1, 2, 1, 2)

        self.form_color_note = QLabel(self.color_box)
        self.form_color_note.setObjectName(u"form_color_note")
        self.form_color_note.setWordWrap(True)

        self.form_color_layout.addWidget(self.form_color_note, 2, 0, 1, 4)

        self.color_lock = QCheckBox(self.color_box)
        self.color_lock.setObjectName(u"color_lock")

        self.form_color_layout.addWidget(self.color_lock, 4, 0, 1, 4)


        self.form_layout.addWidget(self.color_box)

        self.form_buttons = QDialogButtonBox(ScalingDialog)
        self.form_buttons.setObjectName(u"form_buttons")
        self.form_buttons.setStandardButtons(QDialogButtonBox.Close)

        self.form_layout.addWidget(self.form_buttons)


        self.retranslateUi(ScalingDialog)

        QMetaObject.connectSlotsByName(ScalingDialog)
    # setupUi

    def retranslateUi(self, ScalingDialog):
        self.form_auto.setText(QCoreApplication.translate("ScalingDialog", u"Apply auto scaling", None))
#if QT_CONFIG(tooltip)
        self.form_auto.setToolTip(QCoreApplication.translate("ScalingDialog", u"Fit once. In 3D, restore automatic Z bounds and matrix-height balance without changing camera direction.", None))
#endif // QT_CONFIG(tooltip)
        self.endpoint_ticks.setText(QCoreApplication.translate("ScalingDialog", u"Show range endpoints on value axes / color bars (all views)", None))
#if QT_CONFIG(tooltip)
        self.endpoint_ticks.setToolTip(QCoreApplication.translate("ScalingDialog", u"Off: automatic ticks. On: include minimum/maximum on 1D Y, 3D Z and 2D/3D color scales. Does not change manual ranges.", None))
#endif // QT_CONFIG(tooltip)
        self.y_lock.setText(QCoreApplication.translate("ScalingDialog", u"Lock Y range (expand only, across slices and matrices)", None))
#if QT_CONFIG(tooltip)
        self.y_lock.setToolTip(QCoreApplication.translate("ScalingDialog", u"Signal and derivative accumulate separate ranges. Turn off/on to start again. While locked, Y fitting and manual edits can only expand the range.", None))
#endif // QT_CONFIG(tooltip)
        self.equal_lock.setText(QCoreApplication.translate("ScalingDialog", u"Lock X:Y = 1:1 (data units)", None))
        self.geometry_box.setTitle(QCoreApplication.translate("ScalingDialog", u"Geometry Z range (all visible layers)", None))
        self.apply_geometry.setText(QCoreApplication.translate("ScalingDialog", u"Apply Z range", None))
        self.auto_geometry.setText(QCoreApplication.translate("ScalingDialog", u"Auto Z range", None))
        self.form_geometry_note.setText(QCoreApplication.translate("ScalingDialog", u"Display only: geometry outside this interval is hidden. Use full Z coordinates after height/alignment, before scene multipliers (not the abbreviated scientific ticks). Color bounds and source data are unchanged. Applies across matrix switches.", None))
        self.z_lock.setText(QCoreApplication.translate("ScalingDialog", u"Lock Z range (expand only)", None))
#if QT_CONFIG(tooltip)
        self.z_lock.setToolTip(QCoreApplication.translate("ScalingDialog", u"Independent of the shared 2D/3D color lock. Keeps geometry bounds across matrices, overlays and height changes. Turn off/on to restart.", None))
#endif // QT_CONFIG(tooltip)
        self.color_box.setTitle(QCoreApplication.translate("ScalingDialog", u"Color scale (shared by 2D and 3D)", None))
        self.apply_colors.setText(QCoreApplication.translate("ScalingDialog", u"Apply color range", None))
        self.auto_colors.setText(QCoreApplication.translate("ScalingDialog", u"Auto color range", None))
        self.form_color_note.setText(QCoreApplication.translate("ScalingDialog", u"Stored for the active channel. Use the same bounds for comparable figures. Unavailable for original image colors or solid-color overlays.", None))
        self.color_lock.setText(QCoreApplication.translate("ScalingDialog", u"Lock color range (expand only, shared by 2D / 3D)", None))
        pass
    # retranslateUi

