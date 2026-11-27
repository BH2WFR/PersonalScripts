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
from PySide6.QtWidgets import (QApplication, QCheckBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QSpacerItem,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget)

from ..common.range_input import PageRangeField
from utils.qt_widgets import NoWheelComboBox

class Ui_RulePanel(object):
    def setupUi(self, RulePanel):
        if not RulePanel.objectName():
            RulePanel.setObjectName(u"RulePanel")
        self.main_layout = QVBoxLayout(RulePanel)
        self.main_layout.setObjectName(u"main_layout")
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget(RulePanel)
        self.tabs.setObjectName(u"tabs")
        self.match_page = QWidget()
        self.match_page.setObjectName(u"match_page")
        self.match_layout = QVBoxLayout(self.match_page)
        self.match_layout.setObjectName(u"match_layout")
        self.names_form = QFormLayout()
        self.names_form.setObjectName(u"names_form")
        self.names_label = QLabel(self.match_page)
        self.names_label.setObjectName(u"names_label")

        self.names_form.setWidget(0, QFormLayout.LabelRole, self.names_label)

        self.names = QLineEdit(self.match_page)
        self.names.setObjectName(u"names")

        self.names_form.setWidget(0, QFormLayout.FieldRole, self.names)


        self.match_layout.addLayout(self.names_form)

        self.scan_row = QWidget(self.match_page)
        self.scan_row.setObjectName(u"scan_row")
        self.scan_layout = QHBoxLayout(self.scan_row)
        self.scan_layout.setObjectName(u"scan_layout")
        self.scan_layout.setContentsMargins(0, 0, 0, 0)
        self.scan_pages = QPushButton(self.scan_row)
        self.scan_pages.setObjectName(u"scan_pages")

        self.scan_layout.addWidget(self.scan_pages)

        self.scan_all = QPushButton(self.scan_row)
        self.scan_all.setObjectName(u"scan_all")

        self.scan_layout.addWidget(self.scan_all)

        self.scan_current = QPushButton(self.scan_row)
        self.scan_current.setObjectName(u"scan_current")

        self.scan_layout.addWidget(self.scan_current)


        self.match_layout.addWidget(self.scan_row)

        self.sources = QTreeWidget(self.match_page)
        self.sources.setObjectName(u"sources")
        self.sources.setRootIsDecorated(False)
        self.sources.setUniformRowHeights(True)
        self.sources.setAlternatingRowColors(True)

        self.match_layout.addWidget(self.sources)

        self.filters = QFormLayout()
        self.filters.setObjectName(u"filters")
        self.sizes_label = QLabel(self.match_page)
        self.sizes_label.setObjectName(u"sizes_label")

        self.filters.setWidget(0, QFormLayout.LabelRole, self.sizes_label)

        self.sizes = QLineEdit(self.match_page)
        self.sizes.setObjectName(u"sizes")

        self.filters.setWidget(0, QFormLayout.FieldRole, self.sizes)

        self.ignored_range_label = QLabel(self.match_page)
        self.ignored_range_label.setObjectName(u"ignored_range_label")

        self.filters.setWidget(1, QFormLayout.LabelRole, self.ignored_range_label)

        self.ignored_range = PageRangeField(self.match_page)
        self.ignored_range.setObjectName(u"ignored_range")

        self.filters.setWidget(1, QFormLayout.FieldRole, self.ignored_range)

        self.source_colors_row_label = QLabel(self.match_page)
        self.source_colors_row_label.setObjectName(u"source_colors_row_label")

        self.filters.setWidget(2, QFormLayout.LabelRole, self.source_colors_row_label)

        self.source_colors_row = QWidget(self.match_page)
        self.source_colors_row.setObjectName(u"source_colors_row")
        self.source_colors_layout = QHBoxLayout(self.source_colors_row)
        self.source_colors_layout.setObjectName(u"source_colors_layout")
        self.source_colors_layout.setContentsMargins(0, 0, 0, 0)
        self.source_colors = QLineEdit(self.source_colors_row)
        self.source_colors.setObjectName(u"source_colors")

        self.source_colors_layout.addWidget(self.source_colors)

        self.source_colors_button = QPushButton(self.source_colors_row)
        self.source_colors_button.setObjectName(u"source_colors_button")
        self.source_colors_button.setMinimumSize(QSize(28, 0))
        self.source_colors_button.setMaximumSize(QSize(28, 16777215))

        self.source_colors_layout.addWidget(self.source_colors_button)

        self.source_colors_layout.setStretch(0, 1)

        self.filters.setWidget(2, QFormLayout.FieldRole, self.source_colors_row)

        self.found_colors_label = QLabel(self.match_page)
        self.found_colors_label.setObjectName(u"found_colors_label")

        self.filters.setWidget(3, QFormLayout.LabelRole, self.found_colors_label)

        self.found_colors = NoWheelComboBox(self.match_page)
        self.found_colors.setObjectName(u"found_colors")

        self.filters.setWidget(3, QFormLayout.FieldRole, self.found_colors)


        self.match_layout.addLayout(self.filters)

        self.match_layout.setStretch(2, 1)
        self.tabs.addTab(self.match_page, "")
        self.target_page = QWidget()
        self.target_page.setObjectName(u"target_page")
        self.target_layout = QVBoxLayout(self.target_page)
        self.target_layout.setObjectName(u"target_layout")
        self.color_only = QCheckBox(self.target_page)
        self.color_only.setObjectName(u"color_only")

        self.target_layout.addWidget(self.color_only)

        self.font_controls = QWidget(self.target_page)
        self.font_controls.setObjectName(u"font_controls")
        self.font_layout = QVBoxLayout(self.font_controls)
        self.font_layout.setObjectName(u"font_layout")
        self.font_layout.setContentsMargins(0, 0, 0, 0)
        self.font_actions = QHBoxLayout()
        self.font_actions.setObjectName(u"font_actions")
        self.installed_button = QPushButton(self.font_controls)
        self.installed_button.setObjectName(u"installed_button")

        self.font_actions.addWidget(self.installed_button)

        self.file_button = QPushButton(self.font_controls)
        self.file_button.setObjectName(u"file_button")

        self.font_actions.addWidget(self.file_button)


        self.font_layout.addLayout(self.font_actions)

        self.search = QLineEdit(self.font_controls)
        self.search.setObjectName(u"search")

        self.font_layout.addWidget(self.search)

        self.target_status = QLabel(self.font_controls)
        self.target_status.setObjectName(u"target_status")
        self.target_status.setWordWrap(True)

        self.font_layout.addWidget(self.target_status)

        self.target = QListWidget(self.font_controls)
        self.target.setObjectName(u"target")
        self.target.setMinimumSize(QSize(0, 80))
        self.target.setMaximumSize(QSize(16777215, 145))

        self.font_layout.addWidget(self.target)

        self.selected_target = QLabel(self.font_controls)
        self.selected_target.setObjectName(u"selected_target")
        self.selected_target.setWordWrap(True)

        self.font_layout.addWidget(self.selected_target)

        self.target_form = QFormLayout()
        self.target_form.setObjectName(u"target_form")
        self.regular_face_label = QLabel(self.font_controls)
        self.regular_face_label.setObjectName(u"regular_face_label")

        self.target_form.setWidget(0, QFormLayout.LabelRole, self.regular_face_label)

        self.regular_face = NoWheelComboBox(self.font_controls)
        self.regular_face.setObjectName(u"regular_face")

        self.target_form.setWidget(0, QFormLayout.FieldRole, self.regular_face)

        self.bold_face_label = QLabel(self.font_controls)
        self.bold_face_label.setObjectName(u"bold_face_label")

        self.target_form.setWidget(1, QFormLayout.LabelRole, self.bold_face_label)

        self.bold_face = NoWheelComboBox(self.font_controls)
        self.bold_face.setObjectName(u"bold_face")

        self.target_form.setWidget(1, QFormLayout.FieldRole, self.bold_face)

        self.italic_face_label = QLabel(self.font_controls)
        self.italic_face_label.setObjectName(u"italic_face_label")

        self.target_form.setWidget(2, QFormLayout.LabelRole, self.italic_face_label)

        self.italic_face = NoWheelComboBox(self.font_controls)
        self.italic_face.setObjectName(u"italic_face")

        self.target_form.setWidget(2, QFormLayout.FieldRole, self.italic_face)

        self.bold_italic_face_label = QLabel(self.font_controls)
        self.bold_italic_face_label.setObjectName(u"bold_italic_face_label")

        self.target_form.setWidget(3, QFormLayout.LabelRole, self.bold_italic_face_label)

        self.bold_italic_face = NoWheelComboBox(self.font_controls)
        self.bold_italic_face.setObjectName(u"bold_italic_face")

        self.target_form.setWidget(3, QFormLayout.FieldRole, self.bold_italic_face)

        self.embedding_label = QLabel(self.font_controls)
        self.embedding_label.setObjectName(u"embedding_label")

        self.target_form.setWidget(4, QFormLayout.LabelRole, self.embedding_label)

        self.embedding = NoWheelComboBox(self.font_controls)
        self.embedding.setObjectName(u"embedding")

        self.target_form.setWidget(4, QFormLayout.FieldRole, self.embedding)


        self.font_layout.addLayout(self.target_form)

        self.remove_original = QCheckBox(self.font_controls)
        self.remove_original.setObjectName(u"remove_original")

        self.font_layout.addWidget(self.remove_original)


        self.target_layout.addWidget(self.font_controls)

        self.color_form = QFormLayout()
        self.color_form.setObjectName(u"color_form")
        self.color_row_label = QLabel(self.target_page)
        self.color_row_label.setObjectName(u"color_row_label")

        self.color_form.setWidget(0, QFormLayout.LabelRole, self.color_row_label)

        self.color_row = QWidget(self.target_page)
        self.color_row.setObjectName(u"color_row")
        self.color_layout = QHBoxLayout(self.color_row)
        self.color_layout.setObjectName(u"color_layout")
        self.color_layout.setContentsMargins(0, 0, 0, 0)
        self.color = QLineEdit(self.color_row)
        self.color.setObjectName(u"color")

        self.color_layout.addWidget(self.color)

        self.color_button = QPushButton(self.color_row)
        self.color_button.setObjectName(u"color_button")
        self.color_button.setMinimumSize(QSize(28, 0))
        self.color_button.setMaximumSize(QSize(28, 16777215))

        self.color_layout.addWidget(self.color_button)

        self.color_layout.setStretch(0, 1)

        self.color_form.setWidget(0, QFormLayout.FieldRole, self.color_row)


        self.target_layout.addLayout(self.color_form)

        self.position_note = QLabel(self.target_page)
        self.position_note.setObjectName(u"position_note")
        self.position_note.setWordWrap(True)

        self.target_layout.addWidget(self.position_note)

        self.target_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.target_layout.addItem(self.target_stretch)

        self.target_layout.setStretch(4, 1)
        self.tabs.addTab(self.target_page, "")

        self.main_layout.addWidget(self.tabs)

        self.scope = QFormLayout()
        self.scope.setObjectName(u"scope")
        self.pages_range_label = QLabel(RulePanel)
        self.pages_range_label.setObjectName(u"pages_range_label")

        self.scope.setWidget(0, QFormLayout.LabelRole, self.pages_range_label)

        self.pages_range = PageRangeField(RulePanel)
        self.pages_range.setObjectName(u"pages_range")

        self.scope.setWidget(0, QFormLayout.FieldRole, self.pages_range)


        self.main_layout.addLayout(self.scope)

        self.rule_actions = QHBoxLayout()
        self.rule_actions.setObjectName(u"rule_actions")
        self.add = QPushButton(RulePanel)
        self.add.setObjectName(u"add")

        self.rule_actions.addWidget(self.add)

        self.update_button = QPushButton(RulePanel)
        self.update_button.setObjectName(u"update_button")

        self.rule_actions.addWidget(self.update_button)


        self.main_layout.addLayout(self.rule_actions)

        self.hint = QLabel(RulePanel)
        self.hint.setObjectName(u"hint")
        self.hint.setWordWrap(True)

        self.main_layout.addWidget(self.hint)

        self.main_layout.setStretch(0, 1)
#if QT_CONFIG(shortcut)
        self.names_label.setBuddy(self.names)
        self.sizes_label.setBuddy(self.sizes)
        self.ignored_range_label.setBuddy(self.ignored_range)
        self.source_colors_row_label.setBuddy(self.source_colors_row)
        self.found_colors_label.setBuddy(self.found_colors)
        self.regular_face_label.setBuddy(self.regular_face)
        self.bold_face_label.setBuddy(self.bold_face)
        self.italic_face_label.setBuddy(self.italic_face)
        self.bold_italic_face_label.setBuddy(self.bold_italic_face)
        self.embedding_label.setBuddy(self.embedding)
        self.color_row_label.setBuddy(self.color_row)
        self.pages_range_label.setBuddy(self.pages_range)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(RulePanel)

        QMetaObject.connectSlotsByName(RulePanel)
    # setupUi

    def retranslateUi(self, RulePanel):
        self.names_label.setText(QCoreApplication.translate("RulePanel", u"Source fonts", None))
        self.scan_pages.setText(QCoreApplication.translate("RulePanel", u"Scan in pages", None))
        self.scan_all.setText(QCoreApplication.translate("RulePanel", u"Scan all", None))
        self.scan_current.setText(QCoreApplication.translate("RulePanel", u"Scan current", None))
        ___qtreewidgetitem = self.sources.headerItem()
        ___qtreewidgetitem.setText(3, QCoreApplication.translate("RulePanel", u"Size (pt)", None));
        ___qtreewidgetitem.setText(2, QCoreApplication.translate("RulePanel", u"Embedded", None));
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("RulePanel", u"Type", None));
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("RulePanel", u"Font", None));
        self.sizes_label.setText(QCoreApplication.translate("RulePanel", u"Font sizes (pt)", None))
        self.ignored_range_label.setText(QCoreApplication.translate("RulePanel", u"Ignore pages", None))
        self.source_colors_row_label.setText(QCoreApplication.translate("RulePanel", u"Match text colors", None))
        self.source_colors_button.setText(QCoreApplication.translate("RulePanel", u"\u2026", None))
        self.found_colors_label.setText(QCoreApplication.translate("RulePanel", u"Append color", None))
        self.tabs.setTabText(self.tabs.indexOf(self.match_page), QCoreApplication.translate("RulePanel", u"Match", None))
        self.color_only.setText(QCoreApplication.translate("RulePanel", u"Change color only (keep original font)", None))
        self.installed_button.setText(QCoreApplication.translate("RulePanel", u"Load installed fonts", None))
        self.file_button.setText(QCoreApplication.translate("RulePanel", u"Font file\u2026", None))
        self.target_status.setText(QCoreApplication.translate("RulePanel", u"Load installed fonts or choose a font file first.", None))
        self.selected_target.setText(QCoreApplication.translate("RulePanel", u"Selected: none", None))
        self.regular_face_label.setText(QCoreApplication.translate("RulePanel", u"Regular", None))
        self.bold_face_label.setText(QCoreApplication.translate("RulePanel", u"Bold", None))
        self.italic_face_label.setText(QCoreApplication.translate("RulePanel", u"Italic", None))
        self.bold_italic_face_label.setText(QCoreApplication.translate("RulePanel", u"Bold Italic", None))
        self.embedding_label.setText(QCoreApplication.translate("RulePanel", u"Embed target", None))
        self.remove_original.setText(QCoreApplication.translate("RulePanel", u"Remove unused original font embeddings", None))
        self.color_row_label.setText(QCoreApplication.translate("RulePanel", u"New text color", None))
        self.color_button.setText(QCoreApplication.translate("RulePanel", u"\u2026", None))
        self.position_note.setText(QCoreApplication.translate("RulePanel", u"Positions and advances stay fixed. Missing glyphs or styles stop replacement.", None))
        self.tabs.setTabText(self.tabs.indexOf(self.target_page), QCoreApplication.translate("RulePanel", u"Target", None))
        self.pages_range_label.setText(QCoreApplication.translate("RulePanel", u"Apply to pages", None))
        self.add.setText(QCoreApplication.translate("RulePanel", u"Add rule", None))
        self.update_button.setText(QCoreApplication.translate("RulePanel", u"Update selected", None))
        self.hint.setText(QCoreApplication.translate("RulePanel", u"Mark matches previews current filters directly. Add / Update commits replacement rules.", None))
        pass
    # retranslateUi

