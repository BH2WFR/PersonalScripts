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
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QSlider, QSpacerItem, QSplitter,
    QStackedWidget, QTabWidget, QToolButton, QTreeWidgetItem,
    QVBoxLayout, QWidget)

from .channel_tree import ChannelTree
from .image_view import ImageView
from .overlay_profile import OverlayProfile
from .profile_view import ProfileView
from .qt_widgets import OptionalIndexSpinBox
from .raw_view import RawDataView
from .surface_view import SurfaceView
from utils.qt_widgets import (NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox)

class Ui_ViewerWindow(object):
    def setupUi(self, ViewerWindow):
        if not ViewerWindow.objectName():
            ViewerWindow.setObjectName(u"ViewerWindow")
        ViewerWindow.resize(1400, 930)
        ViewerWindow.setMinimumSize(QSize(980, 680))
        self.central_widget = QWidget(ViewerWindow)
        self.central_widget.setObjectName(u"central_widget")
        self.window_layout = QVBoxLayout(self.central_widget)
        self.window_layout.setObjectName(u"window_layout")
        self.window_layout.setContentsMargins(6, 2, 6, 6)
        self.file_bar = QWidget(self.central_widget)
        self.file_bar.setObjectName(u"file_bar")
        self.file_actions = QHBoxLayout(self.file_bar)
        self.file_actions.setObjectName(u"file_actions")
        self.open_file_button = QPushButton(self.file_bar)
        self.open_file_button.setObjectName(u"open_file_button")

        self.file_actions.addWidget(self.open_file_button)

        self.path_label = QLineEdit(self.file_bar)
        self.path_label.setObjectName(u"path_label")
        self.path_label.setReadOnly(True)

        self.file_actions.addWidget(self.path_label)

        self.archive_label = QLabel(self.file_bar)
        self.archive_label.setObjectName(u"archive_label")

        self.file_actions.addWidget(self.archive_label)

        self.archive_key = NoWheelComboBox(self.file_bar)
        self.archive_key.setObjectName(u"archive_key")
        self.archive_key.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.archive_key.setMinimumContentsLength(12)

        self.file_actions.addWidget(self.archive_key)

        self.display_label = QLabel(self.file_bar)
        self.display_label.setObjectName(u"display_label")

        self.file_actions.addWidget(self.display_label)

        self.display_channel = NoWheelComboBox(self.file_bar)
        self.display_channel.setObjectName(u"display_channel")
        self.display_channel.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.display_channel.setMinimumContentsLength(18)

        self.file_actions.addWidget(self.display_channel)

        self.fit_views_button = QPushButton(self.file_bar)
        self.fit_views_button.setObjectName(u"fit_views_button")

        self.file_actions.addWidget(self.fit_views_button)

        self.file_actions.setStretch(1, 1)

        self.window_layout.addWidget(self.file_bar)

        self.main_split = QSplitter(self.central_widget)
        self.main_split.setObjectName(u"main_split")
        self.main_split.setOrientation(Qt.Horizontal)
        self.workspace_split = QSplitter(self.main_split)
        self.workspace_split.setObjectName(u"workspace_split")
        self.workspace_split.setOrientation(Qt.Vertical)
        self.workspace_split.setChildrenCollapsible(False)
        self.matrix_box = QGroupBox(self.workspace_split)
        self.matrix_box.setObjectName(u"matrix_box")
        self.matrix_panel_layout = QVBoxLayout(self.matrix_box)
        self.matrix_panel_layout.setObjectName(u"matrix_panel_layout")
        self.matrix_panel_bar = QHBoxLayout()
        self.matrix_panel_bar.setObjectName(u"matrix_panel_bar")
        self.add_overlay = QToolButton(self.matrix_box)
        self.add_overlay.setObjectName(u"add_overlay")

        self.matrix_panel_bar.addWidget(self.add_overlay)

        self.fourier_button = QPushButton(self.matrix_box)
        self.fourier_button.setObjectName(u"fourier_button")

        self.matrix_panel_bar.addWidget(self.fourier_button)

        self.single_matrix_mode = QRadioButton(self.matrix_box)
        self.single_matrix_mode.setObjectName(u"single_matrix_mode")

        self.matrix_panel_bar.addWidget(self.single_matrix_mode)

        self.multiple_matrix_mode = QRadioButton(self.matrix_box)
        self.multiple_matrix_mode.setObjectName(u"multiple_matrix_mode")

        self.matrix_panel_bar.addWidget(self.multiple_matrix_mode)

        self.matrix_panel_bar_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.matrix_panel_bar.addItem(self.matrix_panel_bar_spacer)


        self.matrix_panel_layout.addLayout(self.matrix_panel_bar)

        self.matrix_panel_actions = QHBoxLayout()
        self.matrix_panel_actions.setObjectName(u"matrix_panel_actions")
        self.none_visible = QPushButton(self.matrix_box)
        self.none_visible.setObjectName(u"none_visible")

        self.matrix_panel_actions.addWidget(self.none_visible)

        self.remove_matrix = QToolButton(self.matrix_box)
        self.remove_matrix.setObjectName(u"remove_matrix")

        self.matrix_panel_actions.addWidget(self.remove_matrix)


        self.matrix_panel_layout.addLayout(self.matrix_panel_actions)

        self.matrix_list = ChannelTree(self.matrix_box)
        self.matrix_list.setObjectName(u"matrix_list")
        self.matrix_list.setMinimumSize(QSize(0, 90))
        self.matrix_list.setIndentation(14)

        self.matrix_panel_layout.addWidget(self.matrix_list)

        self.workspace_split.addWidget(self.matrix_box)
        self.control_scroll = QScrollArea(self.workspace_split)
        self.control_scroll.setObjectName(u"control_scroll")
        self.control_scroll.setWidgetResizable(True)
        self.control_scroll.setMinimumSize(QSize(360, 0))
        self.control_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.controls = QWidget()
        self.controls.setObjectName(u"controls")
        self.viewer_controls_layout = QVBoxLayout(self.controls)
        self.viewer_controls_layout.setObjectName(u"viewer_controls_layout")
        self.alignment_box = QGroupBox(self.controls)
        self.alignment_box.setObjectName(u"alignment_box")
        self.overlay_alignment_form = QFormLayout(self.alignment_box)
        self.overlay_alignment_form.setObjectName(u"overlay_alignment_form")
        self.overlay_alignment_align_relative_to_label = QLabel(self.alignment_box)
        self.overlay_alignment_align_relative_to_label.setObjectName(u"overlay_alignment_align_relative_to_label")

        self.overlay_alignment_form.setWidget(0, QFormLayout.LabelRole, self.overlay_alignment_align_relative_to_label)

        self.reference = NoWheelComboBox(self.alignment_box)
        self.reference.setObjectName(u"reference")

        self.overlay_alignment_form.setWidget(0, QFormLayout.FieldRole, self.reference)

        self.overlay_alignment_x_alignment_label = QLabel(self.alignment_box)
        self.overlay_alignment_x_alignment_label.setObjectName(u"overlay_alignment_x_alignment_label")

        self.overlay_alignment_form.setWidget(1, QFormLayout.LabelRole, self.overlay_alignment_x_alignment_label)

        self.alignment_x = NoWheelComboBox(self.alignment_box)
        self.alignment_x.setObjectName(u"alignment_x")

        self.overlay_alignment_form.setWidget(1, QFormLayout.FieldRole, self.alignment_x)

        self.overlay_alignment_y_alignment_label = QLabel(self.alignment_box)
        self.overlay_alignment_y_alignment_label.setObjectName(u"overlay_alignment_y_alignment_label")

        self.overlay_alignment_form.setWidget(2, QFormLayout.LabelRole, self.overlay_alignment_y_alignment_label)

        self.alignment_y = NoWheelComboBox(self.alignment_box)
        self.alignment_y.setObjectName(u"alignment_y")

        self.overlay_alignment_form.setWidget(2, QFormLayout.FieldRole, self.alignment_y)

        self.overlay_alignment_z_alignment_3d_label = QLabel(self.alignment_box)
        self.overlay_alignment_z_alignment_3d_label.setObjectName(u"overlay_alignment_z_alignment_3d_label")

        self.overlay_alignment_form.setWidget(3, QFormLayout.LabelRole, self.overlay_alignment_z_alignment_3d_label)

        self.alignment_z = NoWheelComboBox(self.alignment_box)
        self.alignment_z.setObjectName(u"alignment_z")

        self.overlay_alignment_form.setWidget(3, QFormLayout.FieldRole, self.alignment_z)

        self.overlay_alignment_note = QLabel(self.alignment_box)
        self.overlay_alignment_note.setObjectName(u"overlay_alignment_note")
        self.overlay_alignment_note.setWordWrap(True)

        self.overlay_alignment_form.setWidget(4, QFormLayout.SpanningRole, self.overlay_alignment_note)


        self.viewer_controls_layout.addWidget(self.alignment_box)

        self.info = QLabel(self.controls)
        self.info.setObjectName(u"info")
        self.info.setWordWrap(True)

        self.viewer_controls_layout.addWidget(self.info)

        self.viewer_controls_axes_box = QGroupBox(self.controls)
        self.viewer_controls_axes_box.setObjectName(u"viewer_controls_axes_box")
        self.viewer_controls_form = QFormLayout(self.viewer_controls_axes_box)
        self.viewer_controls_form.setObjectName(u"viewer_controls_form")
        self.viewer_controls_view_as_label = QLabel(self.viewer_controls_axes_box)
        self.viewer_controls_view_as_label.setObjectName(u"viewer_controls_view_as_label")

        self.viewer_controls_form.setWidget(0, QFormLayout.LabelRole, self.viewer_controls_view_as_label)

        self.mode = NoWheelComboBox(self.viewer_controls_axes_box)
        self.mode.setObjectName(u"mode")

        self.viewer_controls_form.setWidget(0, QFormLayout.FieldRole, self.mode)

        self.viewer_controls_column_sample_axis_label = QLabel(self.viewer_controls_axes_box)
        self.viewer_controls_column_sample_axis_label.setObjectName(u"viewer_controls_column_sample_axis_label")

        self.viewer_controls_form.setWidget(1, QFormLayout.LabelRole, self.viewer_controls_column_sample_axis_label)

        self.x_axis = NoWheelComboBox(self.viewer_controls_axes_box)
        self.x_axis.setObjectName(u"x_axis")

        self.viewer_controls_form.setWidget(1, QFormLayout.FieldRole, self.x_axis)

        self.viewer_controls_row_axis_label = QLabel(self.viewer_controls_axes_box)
        self.viewer_controls_row_axis_label.setObjectName(u"viewer_controls_row_axis_label")

        self.viewer_controls_form.setWidget(2, QFormLayout.LabelRole, self.viewer_controls_row_axis_label)

        self.y_axis = NoWheelComboBox(self.viewer_controls_axes_box)
        self.y_axis.setObjectName(u"y_axis")

        self.viewer_controls_form.setWidget(2, QFormLayout.FieldRole, self.y_axis)

        self.viewer_controls_channel_axis_2_label = QLabel(self.viewer_controls_axes_box)
        self.viewer_controls_channel_axis_2_label.setObjectName(u"viewer_controls_channel_axis_2_label")

        self.viewer_controls_form.setWidget(3, QFormLayout.LabelRole, self.viewer_controls_channel_axis_2_label)

        self.channel_axis = NoWheelComboBox(self.viewer_controls_axes_box)
        self.channel_axis.setObjectName(u"channel_axis")

        self.viewer_controls_form.setWidget(3, QFormLayout.FieldRole, self.channel_axis)

        self.viewer_controls_channel_index_label = QLabel(self.viewer_controls_axes_box)
        self.viewer_controls_channel_index_label.setObjectName(u"viewer_controls_channel_index_label")

        self.viewer_controls_form.setWidget(4, QFormLayout.LabelRole, self.viewer_controls_channel_index_label)

        self.channel = NoWheelSpinBox(self.viewer_controls_axes_box)
        self.channel.setObjectName(u"channel")

        self.viewer_controls_form.setWidget(4, QFormLayout.FieldRole, self.channel)


        self.viewer_controls_layout.addWidget(self.viewer_controls_axes_box)

        self.slice_box = QGroupBox(self.controls)
        self.slice_box.setObjectName(u"slice_box")
        self.slice_form = QFormLayout(self.slice_box)
        self.slice_form.setObjectName(u"slice_form")

        self.viewer_controls_layout.addWidget(self.slice_box)

        self.coordinate_box = QGroupBox(self.controls)
        self.coordinate_box.setObjectName(u"coordinate_box")
        self.viewer_controls_coordinate_form = QFormLayout(self.coordinate_box)
        self.viewer_controls_coordinate_form.setObjectName(u"viewer_controls_coordinate_form")
        self.viewer_controls_coordinates_stored_in_label = QLabel(self.coordinate_box)
        self.viewer_controls_coordinates_stored_in_label.setObjectName(u"viewer_controls_coordinates_stored_in_label")

        self.viewer_controls_coordinate_form.setWidget(0, QFormLayout.LabelRole, self.viewer_controls_coordinates_stored_in_label)

        self.coordinate_axis = NoWheelComboBox(self.coordinate_box)
        self.coordinate_axis.setObjectName(u"coordinate_axis")

        self.viewer_controls_coordinate_form.setWidget(0, QFormLayout.FieldRole, self.coordinate_axis)

        self.coord_x_label = QLabel(self.coordinate_box)
        self.coord_x_label.setObjectName(u"coord_x_label")

        self.viewer_controls_coordinate_form.setWidget(1, QFormLayout.LabelRole, self.coord_x_label)

        self.coord_x = NoWheelComboBox(self.coordinate_box)
        self.coord_x.setObjectName(u"coord_x")

        self.viewer_controls_coordinate_form.setWidget(1, QFormLayout.FieldRole, self.coord_x)

        self.coord_y_label = QLabel(self.coordinate_box)
        self.coord_y_label.setObjectName(u"coord_y_label")

        self.viewer_controls_coordinate_form.setWidget(2, QFormLayout.LabelRole, self.coord_y_label)

        self.coord_y = NoWheelComboBox(self.coordinate_box)
        self.coord_y.setObjectName(u"coord_y")

        self.viewer_controls_coordinate_form.setWidget(2, QFormLayout.FieldRole, self.coord_y)

        self.coord_z_label = QLabel(self.coordinate_box)
        self.coord_z_label.setObjectName(u"coord_z_label")

        self.viewer_controls_coordinate_form.setWidget(3, QFormLayout.LabelRole, self.coord_z_label)

        self.coord_z = NoWheelComboBox(self.coordinate_box)
        self.coord_z.setObjectName(u"coord_z")

        self.viewer_controls_coordinate_form.setWidget(3, QFormLayout.FieldRole, self.coord_z)

        self.viewer_controls_swap = QPushButton(self.coordinate_box)
        self.viewer_controls_swap.setObjectName(u"viewer_controls_swap")

        self.viewer_controls_coordinate_form.setWidget(4, QFormLayout.SpanningRole, self.viewer_controls_swap)


        self.viewer_controls_layout.addWidget(self.coordinate_box)

        self.crop_box = QGroupBox(self.controls)
        self.crop_box.setObjectName(u"crop_box")
        self.index_crop_form = QFormLayout(self.crop_box)
        self.index_crop_form.setObjectName(u"index_crop_form")
        self.crop_x_fields_label = QLabel(self.crop_box)
        self.crop_x_fields_label.setObjectName(u"crop_x_fields_label")

        self.index_crop_form.setWidget(0, QFormLayout.LabelRole, self.crop_x_fields_label)

        self.crop_x_fields = QHBoxLayout()
        self.crop_x_fields.setObjectName(u"crop_x_fields")
        self.crop_x_start = NoWheelSpinBox(self.crop_box)
        self.crop_x_start.setObjectName(u"crop_x_start")

        self.crop_x_fields.addWidget(self.crop_x_start)

        self.crop_x_to = QLabel(self.crop_box)
        self.crop_x_to.setObjectName(u"crop_x_to")

        self.crop_x_fields.addWidget(self.crop_x_to)

        self.crop_x_end = NoWheelSpinBox(self.crop_box)
        self.crop_x_end.setObjectName(u"crop_x_end")

        self.crop_x_fields.addWidget(self.crop_x_end)


        self.index_crop_form.setLayout(0, QFormLayout.FieldRole, self.crop_x_fields)

        self.crop_y_fields_label = QLabel(self.crop_box)
        self.crop_y_fields_label.setObjectName(u"crop_y_fields_label")

        self.index_crop_form.setWidget(1, QFormLayout.LabelRole, self.crop_y_fields_label)

        self.crop_y_fields = QHBoxLayout()
        self.crop_y_fields.setObjectName(u"crop_y_fields")
        self.crop_y_start = NoWheelSpinBox(self.crop_box)
        self.crop_y_start.setObjectName(u"crop_y_start")

        self.crop_y_fields.addWidget(self.crop_y_start)

        self.crop_y_to = QLabel(self.crop_box)
        self.crop_y_to.setObjectName(u"crop_y_to")

        self.crop_y_fields.addWidget(self.crop_y_to)

        self.crop_y_end = NoWheelSpinBox(self.crop_box)
        self.crop_y_end.setObjectName(u"crop_y_end")

        self.crop_y_fields.addWidget(self.crop_y_end)


        self.index_crop_form.setLayout(1, QFormLayout.FieldRole, self.crop_y_fields)

        self.crop_apply = QPushButton(self.crop_box)
        self.crop_apply.setObjectName(u"crop_apply")

        self.index_crop_form.setWidget(2, QFormLayout.LabelRole, self.crop_apply)

        self.crop_reset = QPushButton(self.crop_box)
        self.crop_reset.setObjectName(u"crop_reset")

        self.index_crop_form.setWidget(2, QFormLayout.FieldRole, self.crop_reset)

        self.crop_info = QLabel(self.crop_box)
        self.crop_info.setObjectName(u"crop_info")
        self.crop_info.setWordWrap(True)

        self.index_crop_form.setWidget(3, QFormLayout.SpanningRole, self.crop_info)


        self.viewer_controls_layout.addWidget(self.crop_box)

        self.viewer_controls_filter_box = QGroupBox(self.controls)
        self.viewer_controls_filter_box.setObjectName(u"viewer_controls_filter_box")
        self.viewer_controls_filters = QFormLayout(self.viewer_controls_filter_box)
        self.viewer_controls_filters.setObjectName(u"viewer_controls_filters")
        self.viewer_controls_bounds_row = QHBoxLayout()
        self.viewer_controls_bounds_row.setObjectName(u"viewer_controls_bounds_row")
        self.viewer_controls_minimum_inline = QLabel(self.viewer_controls_filter_box)
        self.viewer_controls_minimum_inline.setObjectName(u"viewer_controls_minimum_inline")

        self.viewer_controls_bounds_row.addWidget(self.viewer_controls_minimum_inline)

        self.filter_low = QLineEdit(self.viewer_controls_filter_box)
        self.filter_low.setObjectName(u"filter_low")

        self.viewer_controls_bounds_row.addWidget(self.filter_low)

        self.viewer_controls_maximum_inline = QLabel(self.viewer_controls_filter_box)
        self.viewer_controls_maximum_inline.setObjectName(u"viewer_controls_maximum_inline")

        self.viewer_controls_bounds_row.addWidget(self.viewer_controls_maximum_inline)

        self.filter_high = QLineEdit(self.viewer_controls_filter_box)
        self.filter_high.setObjectName(u"filter_high")

        self.viewer_controls_bounds_row.addWidget(self.filter_high)

        self.viewer_controls_bounds_row.setStretch(1, 1)
        self.viewer_controls_bounds_row.setStretch(3, 1)

        self.viewer_controls_filters.setLayout(0, QFormLayout.SpanningRole, self.viewer_controls_bounds_row)

        self.viewer_controls_outside_bounds_label = QLabel(self.viewer_controls_filter_box)
        self.viewer_controls_outside_bounds_label.setObjectName(u"viewer_controls_outside_bounds_label")

        self.viewer_controls_filters.setWidget(1, QFormLayout.LabelRole, self.viewer_controls_outside_bounds_label)

        self.filter_mode = NoWheelComboBox(self.viewer_controls_filter_box)
        self.filter_mode.setObjectName(u"filter_mode")

        self.viewer_controls_filters.setWidget(1, QFormLayout.FieldRole, self.filter_mode)

        self.viewer_controls_filter_hint = QLabel(self.viewer_controls_filter_box)
        self.viewer_controls_filter_hint.setObjectName(u"viewer_controls_filter_hint")
        self.viewer_controls_filter_hint.setWordWrap(True)

        self.viewer_controls_filters.setWidget(2, QFormLayout.SpanningRole, self.viewer_controls_filter_hint)

        self.viewer_controls_bounds_buttons = QHBoxLayout()
        self.viewer_controls_bounds_buttons.setObjectName(u"viewer_controls_bounds_buttons")
        self.viewer_controls_apply_filter = QPushButton(self.viewer_controls_filter_box)
        self.viewer_controls_apply_filter.setObjectName(u"viewer_controls_apply_filter")

        self.viewer_controls_bounds_buttons.addWidget(self.viewer_controls_apply_filter)

        self.revert_value_bounds = QPushButton(self.viewer_controls_filter_box)
        self.revert_value_bounds.setObjectName(u"revert_value_bounds")

        self.viewer_controls_bounds_buttons.addWidget(self.revert_value_bounds)


        self.viewer_controls_filters.setLayout(3, QFormLayout.SpanningRole, self.viewer_controls_bounds_buttons)


        self.viewer_controls_layout.addWidget(self.viewer_controls_filter_box)

        self.magnitude_controls = QGroupBox(self.controls)
        self.magnitude_controls.setObjectName(u"magnitude_controls")
        self.viewer_controls_magnitude = QFormLayout(self.magnitude_controls)
        self.viewer_controls_magnitude.setObjectName(u"viewer_controls_magnitude")
        self.viewer_controls_magnitude_floor_label = QLabel(self.magnitude_controls)
        self.viewer_controls_magnitude_floor_label.setObjectName(u"viewer_controls_magnitude_floor_label")

        self.viewer_controls_magnitude.setWidget(0, QFormLayout.LabelRole, self.viewer_controls_magnitude_floor_label)

        self.db_floor = NoWheelDoubleSpinBox(self.magnitude_controls)
        self.db_floor.setObjectName(u"db_floor")

        self.viewer_controls_magnitude.setWidget(0, QFormLayout.FieldRole, self.db_floor)


        self.viewer_controls_layout.addWidget(self.magnitude_controls)

        self.sampling_controls = QGroupBox(self.controls)
        self.sampling_controls.setObjectName(u"sampling_controls")
        self.viewer_controls_sampling = QFormLayout(self.sampling_controls)
        self.viewer_controls_sampling.setObjectName(u"viewer_controls_sampling")
        self.viewer_controls_maximum_grid_edge_label = QLabel(self.sampling_controls)
        self.viewer_controls_maximum_grid_edge_label.setObjectName(u"viewer_controls_maximum_grid_edge_label")

        self.viewer_controls_sampling.setWidget(0, QFormLayout.LabelRole, self.viewer_controls_maximum_grid_edge_label)

        self.grid_sampling_controls = QWidget(self.sampling_controls)
        self.grid_sampling_controls.setObjectName(u"grid_sampling_controls")
        self.viewer_controls_edge_row = QHBoxLayout(self.grid_sampling_controls)
        self.viewer_controls_edge_row.setSpacing(2)
        self.viewer_controls_edge_row.setObjectName(u"viewer_controls_edge_row")
        self.viewer_controls_edge_row.setContentsMargins(0, 0, 0, 0)
        self.max_edge = NoWheelSpinBox(self.grid_sampling_controls)
        self.max_edge.setObjectName(u"max_edge")

        self.viewer_controls_edge_row.addWidget(self.max_edge)

        self.grid_sampling_presets = QToolButton(self.grid_sampling_controls)
        self.grid_sampling_presets.setObjectName(u"grid_sampling_presets")

        self.viewer_controls_edge_row.addWidget(self.grid_sampling_presets)

        self.viewer_controls_edge_row.setStretch(0, 1)

        self.viewer_controls_sampling.setWidget(0, QFormLayout.FieldRole, self.grid_sampling_controls)

        self.viewer_controls_maximum_cloud_points_label = QLabel(self.sampling_controls)
        self.viewer_controls_maximum_cloud_points_label.setObjectName(u"viewer_controls_maximum_cloud_points_label")

        self.viewer_controls_sampling.setWidget(1, QFormLayout.LabelRole, self.viewer_controls_maximum_cloud_points_label)

        self.max_points = NoWheelSpinBox(self.sampling_controls)
        self.max_points.setObjectName(u"max_points")

        self.viewer_controls_sampling.setWidget(1, QFormLayout.FieldRole, self.max_points)

        self.viewer_controls_hint = QLabel(self.sampling_controls)
        self.viewer_controls_hint.setObjectName(u"viewer_controls_hint")
        self.viewer_controls_hint.setWordWrap(True)

        self.viewer_controls_sampling.setWidget(2, QFormLayout.SpanningRole, self.viewer_controls_hint)


        self.viewer_controls_layout.addWidget(self.sampling_controls)

        self.viewer_controls_layout_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.viewer_controls_layout.addItem(self.viewer_controls_layout_spacer)

        self.control_scroll.setWidget(self.controls)
        self.workspace_split.addWidget(self.control_scroll)
        self.main_split.addWidget(self.workspace_split)
        self.right_panel = QWidget(self.main_split)
        self.right_panel.setObjectName(u"right_panel")
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setObjectName(u"right_layout")
        self.right_layout.setContentsMargins(2, 0, 0, 0)
        self.vertical = QSplitter(self.right_panel)
        self.vertical.setObjectName(u"vertical")
        self.vertical.setOrientation(Qt.Vertical)
        self.vertical.setChildrenCollapsible(False)
        self.tabs = QTabWidget(self.vertical)
        self.tabs.setObjectName(u"tabs")
        self.primary_view = QStackedWidget()
        self.primary_view.setObjectName(u"primary_view")
        self.image_view = ImageView()
        self.image_view.setObjectName(u"image_view")
        self.primary_view.addWidget(self.image_view)
        self.tabs.addTab(self.primary_view, "")
        self.secondary_view = QStackedWidget()
        self.secondary_view.setObjectName(u"secondary_view")
        self.surface_view = SurfaceView()
        self.surface_view.setObjectName(u"surface_view")
        self.secondary_view.addWidget(self.surface_view)
        self.tabs.addTab(self.secondary_view, "")
        self.raw_view = RawDataView()
        self.raw_view.setObjectName(u"raw_view")
        self.tabs.addTab(self.raw_view, "")
        self.vertical.addWidget(self.tabs)
        self.profile_area = QWidget(self.vertical)
        self.profile_area.setObjectName(u"profile_area")
        self.profile_layout = QVBoxLayout(self.profile_area)
        self.profile_layout.setObjectName(u"profile_layout")
        self.profile_layout.setContentsMargins(0, 2, 0, 0)
        self.profile_controls = QWidget(self.profile_area)
        self.profile_controls.setObjectName(u"profile_controls")
        self.profile_selector_layout = QVBoxLayout(self.profile_controls)
        self.profile_selector_layout.setObjectName(u"profile_selector_layout")
        self.profile_selector_layout.setContentsMargins(0, 0, 0, 0)
        self.profile_selector_selector = QHBoxLayout()
        self.profile_selector_selector.setObjectName(u"profile_selector_selector")
        self.profile_selector_profile_inline = QLabel(self.profile_controls)
        self.profile_selector_profile_inline.setObjectName(u"profile_selector_profile_inline")

        self.profile_selector_selector.addWidget(self.profile_selector_profile_inline)

        self.profile_direction = NoWheelComboBox(self.profile_controls)
        self.profile_direction.addItem("")
        self.profile_direction.addItem("")
        self.profile_direction.setObjectName(u"profile_direction")

        self.profile_selector_selector.addWidget(self.profile_direction)

        self.profile_index = OptionalIndexSpinBox(self.profile_controls)
        self.profile_index.setObjectName(u"profile_index")

        self.profile_selector_selector.addWidget(self.profile_index)

        self.profile_slider = QSlider(self.profile_controls)
        self.profile_slider.setObjectName(u"profile_slider")
        self.profile_slider.setOrientation(Qt.Horizontal)

        self.profile_selector_selector.addWidget(self.profile_slider)

        self.profile_toggle = QPushButton(self.profile_controls)
        self.profile_toggle.setObjectName(u"profile_toggle")

        self.profile_selector_selector.addWidget(self.profile_toggle)

        self.profile_selector_selector.setStretch(3, 1)

        self.profile_selector_layout.addLayout(self.profile_selector_selector)


        self.profile_layout.addWidget(self.profile_controls)

        self.profile_view = ProfileView(self.profile_area)
        self.profile_view.setObjectName(u"profile_view")

        self.profile_layout.addWidget(self.profile_view)

        self.overlay_profile = OverlayProfile(self.profile_area)
        self.overlay_profile.setObjectName(u"overlay_profile")

        self.profile_layout.addWidget(self.overlay_profile)

        self.vertical.addWidget(self.profile_area)

        self.right_layout.addWidget(self.vertical)

        self.hint = QLabel(self.right_panel)
        self.hint.setObjectName(u"hint")
        self.hint.setWordWrap(True)

        self.right_layout.addWidget(self.hint)

        self.main_split.addWidget(self.right_panel)

        self.window_layout.addWidget(self.main_split)

        self.window_layout.setStretch(1, 1)
        ViewerWindow.setCentralWidget(self.central_widget)
#if QT_CONFIG(shortcut)
        self.overlay_alignment_align_relative_to_label.setBuddy(self.reference)
        self.overlay_alignment_x_alignment_label.setBuddy(self.alignment_x)
        self.overlay_alignment_y_alignment_label.setBuddy(self.alignment_y)
        self.overlay_alignment_z_alignment_3d_label.setBuddy(self.alignment_z)
        self.viewer_controls_view_as_label.setBuddy(self.mode)
        self.viewer_controls_column_sample_axis_label.setBuddy(self.x_axis)
        self.viewer_controls_row_axis_label.setBuddy(self.y_axis)
        self.viewer_controls_channel_axis_2_label.setBuddy(self.channel_axis)
        self.viewer_controls_channel_index_label.setBuddy(self.channel)
        self.viewer_controls_coordinates_stored_in_label.setBuddy(self.coordinate_axis)
        self.coord_x_label.setBuddy(self.coord_x)
        self.coord_y_label.setBuddy(self.coord_y)
        self.coord_z_label.setBuddy(self.coord_z)
        self.viewer_controls_outside_bounds_label.setBuddy(self.filter_mode)
        self.viewer_controls_magnitude_floor_label.setBuddy(self.db_floor)
        self.viewer_controls_maximum_grid_edge_label.setBuddy(self.grid_sampling_controls)
        self.viewer_controls_maximum_cloud_points_label.setBuddy(self.max_points)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(ViewerWindow)

        QMetaObject.connectSlotsByName(ViewerWindow)
    # setupUi

    def retranslateUi(self, ViewerWindow):
        ViewerWindow.setWindowTitle(QCoreApplication.translate("ViewerWindow", u"Matrix Viewer \u2014 NPY / NPZ / MAT / CSV / TXT / Images", None))
        self.open_file_button.setText(QCoreApplication.translate("ViewerWindow", u"Open file\u2026", None))
        self.path_label.setPlaceholderText(QCoreApplication.translate("ViewerWindow", u"Drop an NPY, NPZ, MAT, CSV, TXT or image file here", None))
        self.archive_label.setText(QCoreApplication.translate("ViewerWindow", u"Array", None))
        self.display_label.setText(QCoreApplication.translate("ViewerWindow", u"Display", None))
        self.fit_views_button.setText(QCoreApplication.translate("ViewerWindow", u"Fit views", None))
        self.matrix_box.setTitle(QCoreApplication.translate("ViewerWindow", u"Matrices / channels", None))
#if QT_CONFIG(tooltip)
        self.add_overlay.setToolTip(QCoreApplication.translate("ViewerWindow", u"Open one or more files, or choose Open and replace from the arrow menu. Files can also be dropped anywhere in the window.", None))
#endif // QT_CONFIG(tooltip)
        self.fourier_button.setText(QCoreApplication.translate("ViewerWindow", u"Transform\u2026", None))
        self.single_matrix_mode.setText(QCoreApplication.translate("ViewerWindow", u"Single matrix", None))
#if QT_CONFIG(tooltip)
        self.single_matrix_mode.setToolTip(QCoreApplication.translate("ViewerWindow", u"Click a channel or single-channel matrix to show it exclusively. Click a multichannel matrix to expand its channels.", None))
#endif // QT_CONFIG(tooltip)
        self.multiple_matrix_mode.setText(QCoreApplication.translate("ViewerWindow", u"Multiple matrices", None))
#if QT_CONFIG(tooltip)
        self.multiple_matrix_mode.setToolTip(QCoreApplication.translate("ViewerWindow", u"Use channel checkboxes to overlay compatible matrices/channels. Row clicks only choose the editing target.", None))
#endif // QT_CONFIG(tooltip)
        self.none_visible.setText(QCoreApplication.translate("ViewerWindow", u"Hide all", None))
#if QT_CONFIG(tooltip)
        self.remove_matrix.setToolTip(QCoreApplication.translate("ViewerWindow", u"Close the selected matrix and its channels. The source file is unchanged.", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(tooltip)
        self.matrix_list.setToolTip(QCoreApplication.translate("ViewerWindow", u"Single matrix: click a channel or single-channel matrix to show it. Multichannel matrices expand without changing visibility. Multiple matrices: click rows to edit and use checkboxes to combine channels. F2 renames the matrix.", None))
#endif // QT_CONFIG(tooltip)
        self.alignment_box.setTitle(QCoreApplication.translate("ViewerWindow", u"Overlay alignment (active channel)", None))
        self.overlay_alignment_align_relative_to_label.setText(QCoreApplication.translate("ViewerWindow", u"Align relative to", None))
#if QT_CONFIG(tooltip)
        self.reference.setToolTip(QCoreApplication.translate("ViewerWindow", u"Shared reference for checked channels. Clicking matrix/channel rows does not change the reference.", None))
#endif // QT_CONFIG(tooltip)
        self.overlay_alignment_x_alignment_label.setText(QCoreApplication.translate("ViewerWindow", u"X alignment", None))
        self.overlay_alignment_y_alignment_label.setText(QCoreApplication.translate("ViewerWindow", u"Y alignment", None))
        self.overlay_alignment_z_alignment_3d_label.setText(QCoreApplication.translate("ViewerWindow", u"Z alignment (3D)", None))
#if QT_CONFIG(tooltip)
        self.alignment_z.setToolTip(QCoreApplication.translate("ViewerWindow", u"Align visible Z ranges to the reference after height scaling. Affects 3D geometry only; images, profiles and numeric exports keep source values.", None))
#endif // QT_CONFIG(tooltip)
        self.overlay_alignment_note.setText(QCoreApplication.translate("ViewerWindow", u"X/Y alignment is included in visible-matrix exports. Z alignment and height scaling affect only 3D geometry. Data and derivatives retain source values. 2D values control opacity.", None))
        self.info.setText(QCoreApplication.translate("ViewerWindow", u"No data loaded", None))
        self.viewer_controls_axes_box.setTitle(QCoreApplication.translate("ViewerWindow", u"Data interpretation", None))
        self.viewer_controls_view_as_label.setText(QCoreApplication.translate("ViewerWindow", u"View as", None))
        self.viewer_controls_column_sample_axis_label.setText(QCoreApplication.translate("ViewerWindow", u"Column / sample axis", None))
        self.viewer_controls_row_axis_label.setText(QCoreApplication.translate("ViewerWindow", u"Row axis", None))
        self.viewer_controls_channel_axis_2_label.setText(QCoreApplication.translate("ViewerWindow", u"Channel axis", None))
        self.viewer_controls_channel_index_label.setText(QCoreApplication.translate("ViewerWindow", u"Channel index", None))
        self.slice_box.setTitle(QCoreApplication.translate("ViewerWindow", u"Other-axis slices", None))
        self.coordinate_box.setTitle(QCoreApplication.translate("ViewerWindow", u"Coordinate layout", None))
        self.viewer_controls_coordinates_stored_in_label.setText(QCoreApplication.translate("ViewerWindow", u"Coordinates stored in", None))
        self.coord_x_label.setText(QCoreApplication.translate("ViewerWindow", u"X", None))
        self.coord_y_label.setText(QCoreApplication.translate("ViewerWindow", u"Y", None))
        self.coord_z_label.setText(QCoreApplication.translate("ViewerWindow", u"Z", None))
        self.viewer_controls_swap.setText(QCoreApplication.translate("ViewerWindow", u"Swap X / Y", None))
        self.crop_box.setTitle(QCoreApplication.translate("ViewerWindow", u"Crop by source index (inclusive)", None))
        self.crop_x_fields_label.setText(QCoreApplication.translate("ViewerWindow", u"X range", None))
        self.crop_x_to.setText(QCoreApplication.translate("ViewerWindow", u"to", None))
        self.crop_y_fields_label.setText(QCoreApplication.translate("ViewerWindow", u"Y range", None))
        self.crop_y_to.setText(QCoreApplication.translate("ViewerWindow", u"to", None))
        self.crop_apply.setText(QCoreApplication.translate("ViewerWindow", u"Apply crop", None))
        self.crop_reset.setText(QCoreApplication.translate("ViewerWindow", u"Restore full range", None))
        self.crop_info.setText(QCoreApplication.translate("ViewerWindow", u"X: columns / samples; Y: rows. Source indices are retained.", None))
        self.viewer_controls_filter_box.setTitle(QCoreApplication.translate("ViewerWindow", u"Crop by value bounds", None))
#if QT_CONFIG(tooltip)
        self.viewer_controls_filter_box.setToolTip(QCoreApplication.translate("ViewerWindow", u"Minimum and maximum are inclusive. Empty fields leave the corresponding bound open.", None))
#endif // QT_CONFIG(tooltip)
        self.viewer_controls_minimum_inline.setText(QCoreApplication.translate("ViewerWindow", u"Minimum", None))
        self.filter_low.setPlaceholderText(QCoreApplication.translate("ViewerWindow", u"No lower bound", None))
        self.viewer_controls_maximum_inline.setText(QCoreApplication.translate("ViewerWindow", u"Maximum", None))
        self.filter_high.setPlaceholderText(QCoreApplication.translate("ViewerWindow", u"No upper bound", None))
        self.viewer_controls_outside_bounds_label.setText(QCoreApplication.translate("ViewerWindow", u"Outside bounds", None))
        self.viewer_controls_filter_hint.setText(QCoreApplication.translate("ViewerWindow", u"Clamp retains boundary values. Highlighting is optional; nonfinite and clipped samples stay excluded from derivatives.", None))
        self.viewer_controls_apply_filter.setText(QCoreApplication.translate("ViewerWindow", u"Apply", None))
        self.revert_value_bounds.setText(QCoreApplication.translate("ViewerWindow", u"Revert", None))
#if QT_CONFIG(tooltip)
        self.revert_value_bounds.setToolTip(QCoreApplication.translate("ViewerWindow", u"Clear minimum and maximum and restore values within the current X/Y crop.", None))
#endif // QT_CONFIG(tooltip)
        self.magnitude_controls.setTitle(QCoreApplication.translate("ViewerWindow", u"Magnitude (dB)", None))
        self.viewer_controls_magnitude_floor_label.setText(QCoreApplication.translate("ViewerWindow", u"Magnitude floor", None))
#if QT_CONFIG(tooltip)
        self.db_floor.setToolTip(QCoreApplication.translate("ViewerWindow", u"Magnitude relative to the selected region's peak (0 dB). Source complex values are unchanged.", None))
#endif // QT_CONFIG(tooltip)
        self.sampling_controls.setTitle(QCoreApplication.translate("ViewerWindow", u"Display sampling", None))
        self.viewer_controls_maximum_grid_edge_label.setText(QCoreApplication.translate("ViewerWindow", u"Maximum grid edge", None))
#if QT_CONFIG(tooltip)
        self.max_edge.setToolTip(QCoreApplication.translate("ViewerWindow", u"Maximum samples along the longer grid edge; the shorter edge follows its aspect ratio.\n"
"0 / All samples keeps every pixel. Source data and slice samples are unchanged.", None))
#endif // QT_CONFIG(tooltip)
        self.grid_sampling_presets.setText(QCoreApplication.translate("ViewerWindow", u"Presets", None))
        self.viewer_controls_maximum_cloud_points_label.setText(QCoreApplication.translate("ViewerWindow", u"Maximum cloud points", None))
        self.viewer_controls_hint.setText(QCoreApplication.translate("ViewerWindow", u"Grid size limits 2D points and 3D sampling. Set 0 for all samples. Image pixels, profiles and numeric exports retain full resolution.", None))
        self.tabs.setTabText(self.tabs.indexOf(self.primary_view), QCoreApplication.translate("ViewerWindow", u"2D image", None))
        self.tabs.setTabText(self.tabs.indexOf(self.secondary_view), QCoreApplication.translate("ViewerWindow", u"3D surface", None))
        self.tabs.setTabText(self.tabs.indexOf(self.raw_view), QCoreApplication.translate("ViewerWindow", u"Raw data", None))
        self.profile_selector_profile_inline.setText(QCoreApplication.translate("ViewerWindow", u"Profile", None))
        self.profile_direction.setItemText(0, QCoreApplication.translate("ViewerWindow", u"Row", None))
        self.profile_direction.setItemText(1, QCoreApplication.translate("ViewerWindow", u"Column", None))

        self.profile_toggle.setText(QCoreApplication.translate("ViewerWindow", u"Select current", None))
    # retranslateUi

