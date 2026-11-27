# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'view_settings_dialog.ui'
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
    QDialogButtonBox, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSpacerItem, QStackedWidget, QTabWidget, QVBoxLayout,
    QWidget)

class Ui_ViewSettingsDialog(object):
    def setupUi(self, ViewSettingsDialog):
        if not ViewSettingsDialog.objectName():
            ViewSettingsDialog.setObjectName(u"ViewSettingsDialog")
        ViewSettingsDialog.resize(570, 570)
        ViewSettingsDialog.setMinimumSize(QSize(460, 420))
        self.form_layout = QVBoxLayout(ViewSettingsDialog)
        self.form_layout.setObjectName(u"form_layout")
        self.source = QLabel(ViewSettingsDialog)
        self.source.setObjectName(u"source")
        self.source.setWordWrap(True)

        self.form_layout.addWidget(self.source)

        self.form_note = QLabel(ViewSettingsDialog)
        self.form_note.setObjectName(u"form_note")
        self.form_note.setWordWrap(True)

        self.form_layout.addWidget(self.form_note)

        self.tabs = QTabWidget(ViewSettingsDialog)
        self.tabs.setObjectName(u"tabs")
        self.signal_page = QScrollArea()
        self.signal_page.setObjectName(u"signal_page")
        self.signal_page.setWidgetResizable(True)
        self.signal_page.setFrameShape(QFrame.NoFrame)
        self.signal_content = QWidget()
        self.signal_content.setObjectName(u"signal_content")
        self.signal_layout = QVBoxLayout(self.signal_content)
        self.signal_layout.setObjectName(u"signal_layout")
        self.signal_lock_slot = QVBoxLayout()
        self.signal_lock_slot.setObjectName(u"signal_lock_slot")

        self.signal_layout.addLayout(self.signal_lock_slot)

        self.profile_scope = QLabel(self.signal_content)
        self.profile_scope.setObjectName(u"profile_scope")
        self.profile_scope.setWordWrap(True)

        self.signal_layout.addWidget(self.profile_scope)

        self.signal_scaling = QGroupBox(self.signal_content)
        self.signal_scaling.setObjectName(u"signal_scaling")
        self.signal_scaling_layout = QHBoxLayout(self.signal_scaling)
        self.signal_scaling_layout.setObjectName(u"signal_scaling_layout")
        self.signal_scaling_button = QPushButton(self.signal_scaling)
        self.signal_scaling_button.setObjectName(u"signal_scaling_button")

        self.signal_scaling_layout.addWidget(self.signal_scaling_button)

        self.derivative_scaling_button = QPushButton(self.signal_scaling)
        self.derivative_scaling_button.setObjectName(u"derivative_scaling_button")

        self.signal_scaling_layout.addWidget(self.derivative_scaling_button)


        self.signal_layout.addWidget(self.signal_scaling)

        self.profile_stack = QStackedWidget(self.signal_content)
        self.profile_stack.setObjectName(u"profile_stack")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.profile_stack.sizePolicy().hasHeightForWidth())
        self.profile_stack.setSizePolicy(sizePolicy)

        self.signal_layout.addWidget(self.profile_stack)

        self.axes = QGroupBox(self.signal_content)
        self.axes.setObjectName(u"axes")
        self.axes_layout = QVBoxLayout(self.axes)
        self.axes_layout.setObjectName(u"axes_layout")
        self.signal_grid = QCheckBox(self.axes)
        self.signal_grid.setObjectName(u"signal_grid")

        self.axes_layout.addWidget(self.signal_grid)

        self.derivative_grid = QCheckBox(self.axes)
        self.derivative_grid.setObjectName(u"derivative_grid")

        self.axes_layout.addWidget(self.derivative_grid)

        self.y_lock = QCheckBox(self.axes)
        self.y_lock.setObjectName(u"y_lock")

        self.axes_layout.addWidget(self.y_lock)

        self.auto_y = QCheckBox(self.axes)
        self.auto_y.setObjectName(u"auto_y")

        self.axes_layout.addWidget(self.auto_y)


        self.signal_layout.addWidget(self.axes)

        self.signal_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.signal_layout.addItem(self.signal_stretch)

        self.signal_page.setWidget(self.signal_content)
        self.tabs.addTab(self.signal_page, "")
        self.image_page = QScrollArea()
        self.image_page.setObjectName(u"image_page")
        self.image_page.setWidgetResizable(True)
        self.image_page.setFrameShape(QFrame.NoFrame)
        self.image_content = QWidget()
        self.image_content.setObjectName(u"image_content")
        self.image_layout = QVBoxLayout(self.image_content)
        self.image_layout.setObjectName(u"image_layout")
        self.image_lock_slot = QVBoxLayout()
        self.image_lock_slot.setObjectName(u"image_lock_slot")

        self.image_layout.addLayout(self.image_lock_slot)

        self.image_scaling = QGroupBox(self.image_content)
        self.image_scaling.setObjectName(u"image_scaling")
        self.image_scaling_layout = QHBoxLayout(self.image_scaling)
        self.image_scaling_layout.setObjectName(u"image_scaling_layout")
        self.image_scaling_button = QPushButton(self.image_scaling)
        self.image_scaling_button.setObjectName(u"image_scaling_button")

        self.image_scaling_layout.addWidget(self.image_scaling_button)


        self.image_layout.addWidget(self.image_scaling)

        self.image_controls_slot = QVBoxLayout()
        self.image_controls_slot.setObjectName(u"image_controls_slot")

        self.image_layout.addLayout(self.image_controls_slot)

        self.image_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.image_layout.addItem(self.image_stretch)

        self.image_page.setWidget(self.image_content)
        self.tabs.addTab(self.image_page, "")
        self.surface_page = QScrollArea()
        self.surface_page.setObjectName(u"surface_page")
        self.surface_page.setWidgetResizable(True)
        self.surface_page.setFrameShape(QFrame.NoFrame)
        self.surface_content = QWidget()
        self.surface_content.setObjectName(u"surface_content")
        self.surface_layout = QVBoxLayout(self.surface_content)
        self.surface_layout.setObjectName(u"surface_layout")
        self.surface_lock_slot = QVBoxLayout()
        self.surface_lock_slot.setObjectName(u"surface_lock_slot")

        self.surface_layout.addLayout(self.surface_lock_slot)

        self.surface_scaling = QGroupBox(self.surface_content)
        self.surface_scaling.setObjectName(u"surface_scaling")
        self.surface_scaling_layout = QHBoxLayout(self.surface_scaling)
        self.surface_scaling_layout.setObjectName(u"surface_scaling_layout")
        self.surface_scaling_button = QPushButton(self.surface_scaling)
        self.surface_scaling_button.setObjectName(u"surface_scaling_button")

        self.surface_scaling_layout.addWidget(self.surface_scaling_button)


        self.surface_layout.addWidget(self.surface_scaling)

        self.z_lock = QCheckBox(self.surface_content)
        self.z_lock.setObjectName(u"z_lock")

        self.surface_layout.addWidget(self.z_lock)

        self.surface_controls_slot = QVBoxLayout()
        self.surface_controls_slot.setObjectName(u"surface_controls_slot")

        self.surface_layout.addLayout(self.surface_controls_slot)

        self.slice_appearance_slot = QVBoxLayout()
        self.slice_appearance_slot.setObjectName(u"slice_appearance_slot")

        self.surface_layout.addLayout(self.slice_appearance_slot)

        self.surface_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.surface_layout.addItem(self.surface_stretch)

        self.surface_page.setWidget(self.surface_content)
        self.tabs.addTab(self.surface_page, "")
        self.colors_page = QScrollArea()
        self.colors_page.setObjectName(u"colors_page")
        self.colors_page.setWidgetResizable(True)
        self.colors_page.setFrameShape(QFrame.NoFrame)
        self.colors_content = QWidget()
        self.colors_content.setObjectName(u"colors_content")
        self.colors_layout = QVBoxLayout(self.colors_content)
        self.colors_layout.setObjectName(u"colors_layout")
        self.colors_lock_slot = QVBoxLayout()
        self.colors_lock_slot.setObjectName(u"colors_lock_slot")

        self.colors_layout.addLayout(self.colors_lock_slot)

        self.display_box_slot = QVBoxLayout()
        self.display_box_slot.setObjectName(u"display_box_slot")

        self.colors_layout.addLayout(self.display_box_slot)

        self.overlay_appearance_slot = QVBoxLayout()
        self.overlay_appearance_slot.setObjectName(u"overlay_appearance_slot")

        self.colors_layout.addLayout(self.overlay_appearance_slot)

        self.colors_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.colors_layout.addItem(self.colors_stretch)

        self.colors_page.setWidget(self.colors_content)
        self.tabs.addTab(self.colors_page, "")
        self.markers_page = QScrollArea()
        self.markers_page.setObjectName(u"markers_page")
        self.markers_page.setWidgetResizable(True)
        self.markers_page.setFrameShape(QFrame.NoFrame)
        self.markers_content = QWidget()
        self.markers_content.setObjectName(u"markers_content")
        self.markers_layout = QVBoxLayout(self.markers_content)
        self.markers_layout.setObjectName(u"markers_layout")
        self.markers_lock_slot = QVBoxLayout()
        self.markers_lock_slot.setObjectName(u"markers_lock_slot")

        self.markers_layout.addLayout(self.markers_lock_slot)

        self.marker_controls_slot = QVBoxLayout()
        self.marker_controls_slot.setObjectName(u"marker_controls_slot")

        self.markers_layout.addLayout(self.marker_controls_slot)

        self.markers_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.markers_layout.addItem(self.markers_stretch)

        self.markers_page.setWidget(self.markers_content)
        self.tabs.addTab(self.markers_page, "")

        self.form_layout.addWidget(self.tabs)

        self.background_slot = QHBoxLayout()
        self.background_slot.setObjectName(u"background_slot")

        self.form_layout.addLayout(self.background_slot)

        self.form_buttons = QDialogButtonBox(ViewSettingsDialog)
        self.form_buttons.setObjectName(u"form_buttons")
        self.form_buttons.setStandardButtons(QDialogButtonBox.Close)

        self.form_layout.addWidget(self.form_buttons)

        self.form_layout.setStretch(2, 1)

        self.retranslateUi(ViewSettingsDialog)

        QMetaObject.connectSlotsByName(ViewSettingsDialog)
    # setupUi

    def retranslateUi(self, ViewSettingsDialog):
        ViewSettingsDialog.setWindowTitle(QCoreApplication.translate("ViewSettingsDialog", u"View settings", None))
        self.form_note.setText(QCoreApplication.translate("ViewSettingsDialog", u"Unlock appearance to restore each matrix's styles. Colors can be locked in single matrix mode; ranges stay independent. Background, slice markers and axes options are shared.", None))
        self.profile_scope.setText(QCoreApplication.translate("ViewSettingsDialog", u"Multiple matrices: line width and point size apply to all. Rendering, line style, dash scale, point shape and color apply to the active matrix/channel.", None))
        self.signal_scaling.setTitle(QCoreApplication.translate("ViewSettingsDialog", u"Scaling (all visible matrices)", None))
        self.signal_scaling_button.setText(QCoreApplication.translate("ViewSettingsDialog", u"1D plot / slice scaling\u2026", None))
#if QT_CONFIG(tooltip)
        self.signal_scaling_button.setToolTip(QCoreApplication.translate("ViewSettingsDialog", u"Open the corresponding plot first. Adjust ranges, individual axes or equal-unit presets; data values stay unchanged.", None))
#endif // QT_CONFIG(tooltip)
        self.derivative_scaling_button.setText(QCoreApplication.translate("ViewSettingsDialog", u"1D derivative scaling\u2026", None))
#if QT_CONFIG(tooltip)
        self.derivative_scaling_button.setToolTip(QCoreApplication.translate("ViewSettingsDialog", u"Open the corresponding plot first. Adjust ranges, individual axes or equal-unit presets; data values stay unchanged.", None))
#endif // QT_CONFIG(tooltip)
        self.axes.setTitle(QCoreApplication.translate("ViewSettingsDialog", u"Axes", None))
        self.signal_grid.setText(QCoreApplication.translate("ViewSettingsDialog", u"Signal grid", None))
        self.derivative_grid.setText(QCoreApplication.translate("ViewSettingsDialog", u"Derivative grid", None))
        self.y_lock.setText(QCoreApplication.translate("ViewSettingsDialog", u"Lock Y range (expand only)", None))
#if QT_CONFIG(tooltip)
        self.y_lock.setToolTip(QCoreApplication.translate("ViewSettingsDialog", u"Shared across slices and 1D matrices. Signal and derivative have separate histories. Overrides Auto Y until unlocked.", None))
#endif // QT_CONFIG(tooltip)
        self.auto_y.setText(QCoreApplication.translate("ViewSettingsDialog", u"Auto Y on slice change", None))
        self.tabs.setTabText(self.tabs.indexOf(self.signal_page), QCoreApplication.translate("ViewSettingsDialog", u"1D", None))
        self.image_scaling.setTitle(QCoreApplication.translate("ViewSettingsDialog", u"Scaling (all visible matrices)", None))
        self.image_scaling_button.setText(QCoreApplication.translate("ViewSettingsDialog", u"2D image scaling\u2026", None))
#if QT_CONFIG(tooltip)
        self.image_scaling_button.setToolTip(QCoreApplication.translate("ViewSettingsDialog", u"Open the corresponding plot first. Adjust ranges, individual axes or equal-unit presets; data values stay unchanged.", None))
#endif // QT_CONFIG(tooltip)
        self.tabs.setTabText(self.tabs.indexOf(self.image_page), QCoreApplication.translate("ViewSettingsDialog", u"2D", None))
        self.surface_scaling.setTitle(QCoreApplication.translate("ViewSettingsDialog", u"Scaling (all visible matrices)", None))
        self.surface_scaling_button.setText(QCoreApplication.translate("ViewSettingsDialog", u"3D view scaling\u2026", None))
#if QT_CONFIG(tooltip)
        self.surface_scaling_button.setToolTip(QCoreApplication.translate("ViewSettingsDialog", u"Open the corresponding plot first. Adjust ranges, individual axes or equal-unit presets; data values stay unchanged.", None))
#endif // QT_CONFIG(tooltip)
        self.z_lock.setText(QCoreApplication.translate("ViewSettingsDialog", u"Lock Z range (expand only)", None))
#if QT_CONFIG(tooltip)
        self.z_lock.setToolTip(QCoreApplication.translate("ViewSettingsDialog", u"3D geometry only; independent of the shared 2D/3D color range lock.", None))
#endif // QT_CONFIG(tooltip)
        self.tabs.setTabText(self.tabs.indexOf(self.surface_page), QCoreApplication.translate("ViewSettingsDialog", u"3D", None))
        self.tabs.setTabText(self.tabs.indexOf(self.colors_page), QCoreApplication.translate("ViewSettingsDialog", u"Colors", None))
        self.tabs.setTabText(self.tabs.indexOf(self.markers_page), QCoreApplication.translate("ViewSettingsDialog", u"Markers", None))
    # retranslateUi

