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
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QSizePolicy, QSpacerItem, QTabWidget, QVBoxLayout,
    QWidget)

from text_processor.editor import InputEditor
from utils.qt_widgets import (NoWheelComboBox, NoWheelSpinBox)

class Ui_TextProcessor(object):
    def setupUi(self, TextProcessor):
        if not TextProcessor.objectName():
            TextProcessor.setObjectName(u"TextProcessor")
        TextProcessor.resize(740, 660)
        TextProcessor.setAcceptDrops(True)
        self.main_layout = QVBoxLayout(TextProcessor)
        self.main_layout.setObjectName(u"main_layout")
        self.input_toolbar = QHBoxLayout()
        self.input_toolbar.setObjectName(u"input_toolbar")
        self.input_label = QLabel(TextProcessor)
        self.input_label.setObjectName(u"input_label")

        self.input_toolbar.addWidget(self.input_label)

        self.input_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.input_toolbar.addItem(self.input_stretch)

        self.wrap = QCheckBox(TextProcessor)
        self.wrap.setObjectName(u"wrap")
        self.wrap.setChecked(True)

        self.input_toolbar.addWidget(self.wrap)

        self.clipboard_separator = QFrame(TextProcessor)
        self.clipboard_separator.setObjectName(u"clipboard_separator")
        self.clipboard_separator.setFrameShape(QFrame.Shape.VLine)
        self.clipboard_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.input_toolbar.addWidget(self.clipboard_separator)

        self.load_paths = QPushButton(TextProcessor)
        self.load_paths.setObjectName(u"load_paths")
        font = QFont()
        font.setBold(True)
        self.load_paths.setFont(font)

        self.input_toolbar.addWidget(self.load_paths)

        self.load_text = QPushButton(TextProcessor)
        self.load_text.setObjectName(u"load_text")
        self.load_text.setFont(font)

        self.input_toolbar.addWidget(self.load_text)


        self.main_layout.addLayout(self.input_toolbar)

        self.source = InputEditor(TextProcessor)
        self.source.setObjectName(u"source")

        self.main_layout.addWidget(self.source)

        self.tabs = QTabWidget(TextProcessor)
        self.tabs.setObjectName(u"tabs")
        self.path_tab = QWidget()
        self.path_tab.setObjectName(u"path_tab")
        self.path_tab_layout = QGridLayout(self.path_tab)
        self.path_tab_layout.setObjectName(u"path_tab_layout")
        self.cleanup_label = QLabel(self.path_tab)
        self.cleanup_label.setObjectName(u"cleanup_label")

        self.path_tab_layout.addWidget(self.cleanup_label, 0, 0, 1, 1)

        self.cleanup_controls = QHBoxLayout()
        self.cleanup_controls.setObjectName(u"cleanup_controls")
        self.quick_clean = QPushButton(self.path_tab)
        self.quick_clean.setObjectName(u"quick_clean")

        self.cleanup_controls.addWidget(self.quick_clean)

        self.cleanup_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.cleanup_controls.addItem(self.cleanup_stretch)


        self.path_tab_layout.addLayout(self.cleanup_controls, 0, 1, 1, 1)

        self.separators_separator = QFrame(self.path_tab)
        self.separators_separator.setObjectName(u"separators_separator")
        self.separators_separator.setFrameShape(QFrame.Shape.HLine)
        self.separators_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.path_tab_layout.addWidget(self.separators_separator, 1, 0, 1, 2)

        self.separators_label = QLabel(self.path_tab)
        self.separators_label.setObjectName(u"separators_label")

        self.path_tab_layout.addWidget(self.separators_label, 2, 0, 1, 1)

        self.separators_controls = QHBoxLayout()
        self.separators_controls.setObjectName(u"separators_controls")
        self.source_separator = NoWheelComboBox(self.path_tab)
        self.source_separator.setObjectName(u"source_separator")

        self.separators_controls.addWidget(self.source_separator)

        self.to_label = QLabel(self.path_tab)
        self.to_label.setObjectName(u"to_label")

        self.separators_controls.addWidget(self.to_label)

        self.target_separator = NoWheelComboBox(self.path_tab)
        self.target_separator.setObjectName(u"target_separator")

        self.separators_controls.addWidget(self.target_separator)

        self.convert_separators = QPushButton(self.path_tab)
        self.convert_separators.setObjectName(u"convert_separators")

        self.separators_controls.addWidget(self.convert_separators)

        self.separators_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.separators_controls.addItem(self.separators_stretch)


        self.path_tab_layout.addLayout(self.separators_controls, 2, 1, 1, 1)

        self.path_operation_separator = QFrame(self.path_tab)
        self.path_operation_separator.setObjectName(u"path_operation_separator")
        self.path_operation_separator.setFrameShape(QFrame.Shape.HLine)
        self.path_operation_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.path_tab_layout.addWidget(self.path_operation_separator, 3, 0, 1, 2)

        self.path_operation_label = QLabel(self.path_tab)
        self.path_operation_label.setObjectName(u"path_operation_label")

        self.path_tab_layout.addWidget(self.path_operation_label, 4, 0, 1, 1)

        self.path_operation_controls = QHBoxLayout()
        self.path_operation_controls.setObjectName(u"path_operation_controls")
        self.path_action = NoWheelComboBox(self.path_tab)
        self.path_action.setObjectName(u"path_action")

        self.path_operation_controls.addWidget(self.path_action)

        self.apply_path_action = QPushButton(self.path_tab)
        self.apply_path_action.setObjectName(u"apply_path_action")

        self.path_operation_controls.addWidget(self.apply_path_action)

        self.path_operation_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.path_operation_controls.addItem(self.path_operation_stretch)


        self.path_tab_layout.addLayout(self.path_operation_controls, 4, 1, 1, 1)

        self.path_tab_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.path_tab_layout.addItem(self.path_tab_stretch, 5, 0, 1, 2)

        self.path_tab_layout.setColumnStretch(1, 1)
        self.tabs.addTab(self.path_tab, "")
        self.environment_tab = QWidget()
        self.environment_tab.setObjectName(u"environment_tab")
        self.environment_tab_layout = QGridLayout(self.environment_tab)
        self.environment_tab_layout.setObjectName(u"environment_tab_layout")
        self.syntax_label = QLabel(self.environment_tab)
        self.syntax_label.setObjectName(u"syntax_label")

        self.environment_tab_layout.addWidget(self.syntax_label, 0, 0, 1, 1)

        self.syntax_controls = QHBoxLayout()
        self.syntax_controls.setObjectName(u"syntax_controls")
        self.variable_syntax = NoWheelComboBox(self.environment_tab)
        self.variable_syntax.setObjectName(u"variable_syntax")

        self.syntax_controls.addWidget(self.variable_syntax)

        self.syntax_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.syntax_controls.addItem(self.syntax_stretch)


        self.environment_tab_layout.addLayout(self.syntax_controls, 0, 1, 1, 1)

        self.home_path_separator = QFrame(self.environment_tab)
        self.home_path_separator.setObjectName(u"home_path_separator")
        self.home_path_separator.setFrameShape(QFrame.Shape.HLine)
        self.home_path_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.environment_tab_layout.addWidget(self.home_path_separator, 1, 0, 1, 2)

        self.home_path_label = QLabel(self.environment_tab)
        self.home_path_label.setObjectName(u"home_path_label")

        self.environment_tab_layout.addWidget(self.home_path_label, 2, 0, 1, 1)

        self.home_path_controls = QHBoxLayout()
        self.home_path_controls.setObjectName(u"home_path_controls")
        self.to_tilde = QPushButton(self.environment_tab)
        self.to_tilde.setObjectName(u"to_tilde")

        self.home_path_controls.addWidget(self.to_tilde)

        self.to_absolute = QPushButton(self.environment_tab)
        self.to_absolute.setObjectName(u"to_absolute")

        self.home_path_controls.addWidget(self.to_absolute)

        self.to_home_variable = QPushButton(self.environment_tab)
        self.to_home_variable.setObjectName(u"to_home_variable")

        self.home_path_controls.addWidget(self.to_home_variable)

        self.home_path_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.home_path_controls.addItem(self.home_path_stretch)


        self.environment_tab_layout.addLayout(self.home_path_controls, 2, 1, 1, 1)

        self.system_paths_separator = QFrame(self.environment_tab)
        self.system_paths_separator.setObjectName(u"system_paths_separator")
        self.system_paths_separator.setFrameShape(QFrame.Shape.HLine)
        self.system_paths_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.environment_tab_layout.addWidget(self.system_paths_separator, 3, 0, 1, 2)

        self.system_paths_label = QLabel(self.environment_tab)
        self.system_paths_label.setObjectName(u"system_paths_label")

        self.environment_tab_layout.addWidget(self.system_paths_label, 4, 0, 1, 1)

        self.system_paths_controls = QHBoxLayout()
        self.system_paths_controls.setObjectName(u"system_paths_controls")
        self.shorten_variable = QPushButton(self.environment_tab)
        self.shorten_variable.setObjectName(u"shorten_variable")

        self.system_paths_controls.addWidget(self.shorten_variable)

        self.expand_variable = QPushButton(self.environment_tab)
        self.expand_variable.setObjectName(u"expand_variable")

        self.system_paths_controls.addWidget(self.expand_variable)

        self.system_paths_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.system_paths_controls.addItem(self.system_paths_stretch)


        self.environment_tab_layout.addLayout(self.system_paths_controls, 4, 1, 1, 1)

        self.environment_tab_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.environment_tab_layout.addItem(self.environment_tab_stretch, 5, 0, 1, 2)

        self.environment_tab_layout.setColumnStretch(1, 1)
        self.tabs.addTab(self.environment_tab, "")
        self.text_tab = QWidget()
        self.text_tab.setObjectName(u"text_tab")
        self.text_tab_layout = QGridLayout(self.text_tab)
        self.text_tab_layout.setObjectName(u"text_tab_layout")
        self.pdf_text_label = QLabel(self.text_tab)
        self.pdf_text_label.setObjectName(u"pdf_text_label")

        self.text_tab_layout.addWidget(self.pdf_text_label, 0, 0, 1, 1)

        self.pdf_text_controls = QHBoxLayout()
        self.pdf_text_controls.setObjectName(u"pdf_text_controls")
        self.clean_pdf = QPushButton(self.text_tab)
        self.clean_pdf.setObjectName(u"clean_pdf")

        self.pdf_text_controls.addWidget(self.clean_pdf)

        self.pdf_text_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.pdf_text_controls.addItem(self.pdf_text_stretch)


        self.text_tab_layout.addLayout(self.pdf_text_controls, 0, 1, 1, 1)

        self.text_operation_separator = QFrame(self.text_tab)
        self.text_operation_separator.setObjectName(u"text_operation_separator")
        self.text_operation_separator.setFrameShape(QFrame.Shape.HLine)
        self.text_operation_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.text_tab_layout.addWidget(self.text_operation_separator, 1, 0, 1, 2)

        self.text_operation_label = QLabel(self.text_tab)
        self.text_operation_label.setObjectName(u"text_operation_label")

        self.text_tab_layout.addWidget(self.text_operation_label, 2, 0, 1, 1)

        self.text_operation_controls = QHBoxLayout()
        self.text_operation_controls.setObjectName(u"text_operation_controls")
        self.text_action = NoWheelComboBox(self.text_tab)
        self.text_action.setObjectName(u"text_action")

        self.text_operation_controls.addWidget(self.text_action)

        self.apply_text_action = QPushButton(self.text_tab)
        self.apply_text_action.setObjectName(u"apply_text_action")

        self.text_operation_controls.addWidget(self.apply_text_action)

        self.text_operation_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.text_operation_controls.addItem(self.text_operation_stretch)


        self.text_tab_layout.addLayout(self.text_operation_controls, 2, 1, 1, 1)

        self.text_tab_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.text_tab_layout.addItem(self.text_tab_stretch, 3, 0, 1, 2)

        self.text_tab_layout.setColumnStretch(1, 1)
        self.tabs.addTab(self.text_tab, "")
        self.letter_tab = QWidget()
        self.letter_tab.setObjectName(u"letter_tab")
        self.letter_tab_layout = QGridLayout(self.letter_tab)
        self.letter_tab_layout.setObjectName(u"letter_tab_layout")
        self.letter_style_label = QLabel(self.letter_tab)
        self.letter_style_label.setObjectName(u"letter_style_label")

        self.letter_tab_layout.addWidget(self.letter_style_label, 0, 0, 1, 1)

        self.letter_style_controls = QHBoxLayout()
        self.letter_style_controls.setObjectName(u"letter_style_controls")
        self.letter_styles = NoWheelComboBox(self.letter_tab)
        self.letter_styles.setObjectName(u"letter_styles")

        self.letter_style_controls.addWidget(self.letter_styles)

        self.style_letters = QPushButton(self.letter_tab)
        self.style_letters.setObjectName(u"style_letters")

        self.letter_style_controls.addWidget(self.style_letters)

        self.plain_letters = QPushButton(self.letter_tab)
        self.plain_letters.setObjectName(u"plain_letters")

        self.letter_style_controls.addWidget(self.plain_letters)

        self.letter_style_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.letter_style_controls.addItem(self.letter_style_stretch)


        self.letter_tab_layout.addLayout(self.letter_style_controls, 0, 1, 1, 1)

        self.letter_tab_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.letter_tab_layout.addItem(self.letter_tab_stretch, 1, 0, 1, 2)

        self.letter_tab_layout.setColumnStretch(1, 1)
        self.tabs.addTab(self.letter_tab, "")
        self.url_tab = QWidget()
        self.url_tab.setObjectName(u"url_tab")
        self.url_tab_layout = QGridLayout(self.url_tab)
        self.url_tab_layout.setObjectName(u"url_tab_layout")
        self.hostnames_label = QLabel(self.url_tab)
        self.hostnames_label.setObjectName(u"hostnames_label")

        self.url_tab_layout.addWidget(self.hostnames_label, 0, 0, 1, 1)

        self.hostnames_controls = QHBoxLayout()
        self.hostnames_controls.setObjectName(u"hostnames_controls")
        self.extract_hostnames = QPushButton(self.url_tab)
        self.extract_hostnames.setObjectName(u"extract_hostnames")

        self.hostnames_controls.addWidget(self.extract_hostnames)

        self.hostnames_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.hostnames_controls.addItem(self.hostnames_stretch)


        self.url_tab_layout.addLayout(self.hostnames_controls, 0, 1, 1, 1)

        self.url_tab_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.url_tab_layout.addItem(self.url_tab_stretch, 1, 0, 1, 2)

        self.url_tab_layout.setColumnStretch(1, 1)
        self.tabs.addTab(self.url_tab, "")
        self.line_tab = QWidget()
        self.line_tab.setObjectName(u"line_tab")
        self.line_tab_layout = QGridLayout(self.line_tab)
        self.line_tab_layout.setObjectName(u"line_tab_layout")
        self.trim_label = QLabel(self.line_tab)
        self.trim_label.setObjectName(u"trim_label")

        self.line_tab_layout.addWidget(self.trim_label, 0, 0, 1, 1)

        self.trim_controls = QHBoxLayout()
        self.trim_controls.setObjectName(u"trim_controls")
        self.trim_side = NoWheelComboBox(self.line_tab)
        self.trim_side.setObjectName(u"trim_side")

        self.trim_controls.addWidget(self.trim_side)

        self.trim_lines = QPushButton(self.line_tab)
        self.trim_lines.setObjectName(u"trim_lines")

        self.trim_controls.addWidget(self.trim_lines)

        self.blank_lines_separator = QFrame(self.line_tab)
        self.blank_lines_separator.setObjectName(u"blank_lines_separator")
        self.blank_lines_separator.setFrameShape(QFrame.Shape.VLine)
        self.blank_lines_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.trim_controls.addWidget(self.blank_lines_separator)

        self.blank_lines_label = QLabel(self.line_tab)
        self.blank_lines_label.setObjectName(u"blank_lines_label")

        self.trim_controls.addWidget(self.blank_lines_label)

        self.remove_blank_lines = QPushButton(self.line_tab)
        self.remove_blank_lines.setObjectName(u"remove_blank_lines")

        self.trim_controls.addWidget(self.remove_blank_lines)

        self.trim_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.trim_controls.addItem(self.trim_stretch)


        self.line_tab_layout.addLayout(self.trim_controls, 0, 1, 1, 1)

        self.indent_separator = QFrame(self.line_tab)
        self.indent_separator.setObjectName(u"indent_separator")
        self.indent_separator.setFrameShape(QFrame.Shape.HLine)
        self.indent_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.line_tab_layout.addWidget(self.indent_separator, 1, 0, 1, 2)

        self.indent_label = QLabel(self.line_tab)
        self.indent_label.setObjectName(u"indent_label")

        self.line_tab_layout.addWidget(self.indent_label, 2, 0, 1, 1)

        self.indent_controls = QHBoxLayout()
        self.indent_controls.setObjectName(u"indent_controls")
        self.indent_unit = NoWheelComboBox(self.line_tab)
        self.indent_unit.setObjectName(u"indent_unit")

        self.indent_controls.addWidget(self.indent_unit)

        self.indent_width_label = QLabel(self.line_tab)
        self.indent_width_label.setObjectName(u"indent_width_label")

        self.indent_controls.addWidget(self.indent_width_label)

        self.indent_width = NoWheelSpinBox(self.line_tab)
        self.indent_width.setObjectName(u"indent_width")

        self.indent_controls.addWidget(self.indent_width)

        self.indent_lines = QPushButton(self.line_tab)
        self.indent_lines.setObjectName(u"indent_lines")

        self.indent_controls.addWidget(self.indent_lines)

        self.unindent_lines = QPushButton(self.line_tab)
        self.unindent_lines.setObjectName(u"unindent_lines")

        self.indent_controls.addWidget(self.unindent_lines)

        self.tabs_separator = QFrame(self.line_tab)
        self.tabs_separator.setObjectName(u"tabs_separator")
        self.tabs_separator.setFrameShape(QFrame.Shape.VLine)
        self.tabs_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.indent_controls.addWidget(self.tabs_separator)

        self.tabs_label = QLabel(self.line_tab)
        self.tabs_label.setObjectName(u"tabs_label")

        self.indent_controls.addWidget(self.tabs_label)

        self.expand_tabs = QPushButton(self.line_tab)
        self.expand_tabs.setObjectName(u"expand_tabs")

        self.indent_controls.addWidget(self.expand_tabs)

        self.indent_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.indent_controls.addItem(self.indent_stretch)


        self.line_tab_layout.addLayout(self.indent_controls, 2, 1, 1, 1)

        self.line_tab_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.line_tab_layout.addItem(self.line_tab_stretch, 3, 0, 1, 2)

        self.line_tab_layout.setColumnStretch(1, 1)
        self.tabs.addTab(self.line_tab, "")

        self.main_layout.addWidget(self.tabs)

        self.operation_toolbar = QHBoxLayout()
        self.operation_toolbar.setObjectName(u"operation_toolbar")
        self.chain_label = QLabel(TextProcessor)
        self.chain_label.setObjectName(u"chain_label")

        self.operation_toolbar.addWidget(self.chain_label)

        self.chain = QCheckBox(TextProcessor)
        self.chain.setObjectName(u"chain")

        self.operation_toolbar.addWidget(self.chain)

        self.operation_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.operation_toolbar.addItem(self.operation_stretch)

        self.regex_separator = QFrame(TextProcessor)
        self.regex_separator.setObjectName(u"regex_separator")
        self.regex_separator.setFrameShape(QFrame.Shape.VLine)
        self.regex_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.operation_toolbar.addWidget(self.regex_separator)

        self.regex_label = QLabel(TextProcessor)
        self.regex_label.setObjectName(u"regex_label")

        self.operation_toolbar.addWidget(self.regex_label)

        self.regex_button = QPushButton(TextProcessor)
        self.regex_button.setObjectName(u"regex_button")

        self.operation_toolbar.addWidget(self.regex_button)


        self.main_layout.addLayout(self.operation_toolbar)

        self.result_toolbar = QHBoxLayout()
        self.result_toolbar.setObjectName(u"result_toolbar")
        self.result_label = QLabel(TextProcessor)
        self.result_label.setObjectName(u"result_label")

        self.result_toolbar.addWidget(self.result_label)

        self.result_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.result_toolbar.addItem(self.result_stretch)

        self.apply_result = QPushButton(TextProcessor)
        self.apply_result.setObjectName(u"apply_result")

        self.result_toolbar.addWidget(self.apply_result)

        self.reset_result = QPushButton(TextProcessor)
        self.reset_result.setObjectName(u"reset_result")

        self.result_toolbar.addWidget(self.reset_result)

        self.clear_separator = QFrame(TextProcessor)
        self.clear_separator.setObjectName(u"clear_separator")
        self.clear_separator.setFrameShape(QFrame.Shape.VLine)
        self.clear_separator.setFrameShadow(QFrame.Shadow.Sunken)

        self.result_toolbar.addWidget(self.clear_separator)

        self.clear_result = QPushButton(TextProcessor)
        self.clear_result.setObjectName(u"clear_result")

        self.result_toolbar.addWidget(self.clear_result)

        self.clear_all = QPushButton(TextProcessor)
        self.clear_all.setObjectName(u"clear_all")

        self.result_toolbar.addWidget(self.clear_all)

        self.copy_result = QPushButton(TextProcessor)
        self.copy_result.setObjectName(u"copy_result")

        self.result_toolbar.addWidget(self.copy_result)


        self.main_layout.addLayout(self.result_toolbar)

        self.result = QPlainTextEdit(TextProcessor)
        self.result.setObjectName(u"result")
        self.result.setReadOnly(True)

        self.main_layout.addWidget(self.result)

        self.preference_notice = QLabel(TextProcessor)
        self.preference_notice.setObjectName(u"preference_notice")
        self.preference_notice.setWordWrap(True)

        self.main_layout.addWidget(self.preference_notice)

        self.main_layout.setStretch(1, 1)
        self.main_layout.setStretch(5, 1)

        self.retranslateUi(TextProcessor)

        QMetaObject.connectSlotsByName(TextProcessor)
    # setupUi

    def retranslateUi(self, TextProcessor):
        TextProcessor.setWindowTitle(QCoreApplication.translate("TextProcessor", u"Text and Path Processor", None))
        self.input_label.setText(QCoreApplication.translate("TextProcessor", u"Input:", None))
        self.wrap.setText(QCoreApplication.translate("TextProcessor", u"Word wrap", None))
        self.load_paths.setText(QCoreApplication.translate("TextProcessor", u"Load paths from clipboard", None))
        self.load_text.setText(QCoreApplication.translate("TextProcessor", u"Load text from clipboard", None))
#if QT_CONFIG(accessibility)
        self.source.setAccessibleName(QCoreApplication.translate("TextProcessor", u"Input", None))
#endif // QT_CONFIG(accessibility)
        self.cleanup_label.setText(QCoreApplication.translate("TextProcessor", u"Cleanup:", None))
        self.quick_clean.setText(QCoreApplication.translate("TextProcessor", u"Quick clean paths", None))
#if QT_CONFIG(tooltip)
        self.quick_clean.setToolTip(QCoreApplication.translate("TextProcessor", u"Remove paired quotes and file://, then convert backslashes to forward slashes.", None))
#endif // QT_CONFIG(tooltip)
        self.separators_label.setText(QCoreApplication.translate("TextProcessor", u"Separators:", None))
        self.to_label.setText(QCoreApplication.translate("TextProcessor", u"to", None))
        self.convert_separators.setText(QCoreApplication.translate("TextProcessor", u"Convert", None))
        self.path_operation_label.setText(QCoreApplication.translate("TextProcessor", u"Path operation:", None))
        self.apply_path_action.setText(QCoreApplication.translate("TextProcessor", u"Apply to lines", None))
        self.tabs.setTabText(self.tabs.indexOf(self.path_tab), QCoreApplication.translate("TextProcessor", u"File paths", None))
        self.syntax_label.setText(QCoreApplication.translate("TextProcessor", u"Variable syntax:", None))
        self.home_path_label.setText(QCoreApplication.translate("TextProcessor", u"Home path:", None))
        self.to_tilde.setText(QCoreApplication.translate("TextProcessor", u"To ~", None))
        self.to_absolute.setText(QCoreApplication.translate("TextProcessor", u"To absolute", None))
        self.to_home_variable.setText(QCoreApplication.translate("TextProcessor", u"To home variable", None))
        self.system_paths_label.setText(QCoreApplication.translate("TextProcessor", u"System paths:", None))
        self.shorten_variable.setText(QCoreApplication.translate("TextProcessor", u"Use longest variable", None))
        self.expand_variable.setText(QCoreApplication.translate("TextProcessor", u"Expand variable", None))
        self.tabs.setTabText(self.tabs.indexOf(self.environment_tab), QCoreApplication.translate("TextProcessor", u"Home && variables", None))
        self.pdf_text_label.setText(QCoreApplication.translate("TextProcessor", u"PDF text:", None))
        self.clean_pdf.setText(QCoreApplication.translate("TextProcessor", u"Clean copied PDF text", None))
        self.text_operation_label.setText(QCoreApplication.translate("TextProcessor", u"Text operation:", None))
        self.apply_text_action.setText(QCoreApplication.translate("TextProcessor", u"Apply", None))
        self.tabs.setTabText(self.tabs.indexOf(self.text_tab), QCoreApplication.translate("TextProcessor", u"Text", None))
        self.letter_style_label.setText(QCoreApplication.translate("TextProcessor", u"Style:", None))
        self.style_letters.setText(QCoreApplication.translate("TextProcessor", u"Style letters and digits", None))
        self.plain_letters.setText(QCoreApplication.translate("TextProcessor", u"Restore plain letters and digits", None))
        self.tabs.setTabText(self.tabs.indexOf(self.letter_tab), QCoreApplication.translate("TextProcessor", u"Letter Style", None))
        self.hostnames_label.setText(QCoreApplication.translate("TextProcessor", u"Hostnames:", None))
        self.extract_hostnames.setText(QCoreApplication.translate("TextProcessor", u"Extract URL hostnames", None))
        self.tabs.setTabText(self.tabs.indexOf(self.url_tab), QCoreApplication.translate("TextProcessor", u"URL", None))
        self.trim_label.setText(QCoreApplication.translate("TextProcessor", u"Trim:", None))
        self.trim_lines.setText(QCoreApplication.translate("TextProcessor", u"Trim lines", None))
        self.blank_lines_label.setText(QCoreApplication.translate("TextProcessor", u"Blank lines:", None))
        self.remove_blank_lines.setText(QCoreApplication.translate("TextProcessor", u"Remove blank lines", None))
        self.indent_label.setText(QCoreApplication.translate("TextProcessor", u"Indent:", None))
        self.indent_width_label.setText(QCoreApplication.translate("TextProcessor", u"Width:", None))
        self.indent_lines.setText(QCoreApplication.translate("TextProcessor", u"Indent", None))
        self.unindent_lines.setText(QCoreApplication.translate("TextProcessor", u"Unindent", None))
        self.tabs_label.setText(QCoreApplication.translate("TextProcessor", u"Tabs:", None))
        self.expand_tabs.setText(QCoreApplication.translate("TextProcessor", u"Tabs to spaces", None))
        self.tabs.setTabText(self.tabs.indexOf(self.line_tab), QCoreApplication.translate("TextProcessor", u"Lines", None))
        self.chain_label.setText(QCoreApplication.translate("TextProcessor", u"Chaining:", None))
        self.chain.setText(QCoreApplication.translate("TextProcessor", u"Use result for the next operation", None))
        self.regex_label.setText(QCoreApplication.translate("TextProcessor", u"Find and replace:", None))
        self.regex_button.setText(QCoreApplication.translate("TextProcessor", u"Regex replace\u2026", None))
        self.result_label.setText(QCoreApplication.translate("TextProcessor", u"Result:", None))
        self.apply_result.setText(QCoreApplication.translate("TextProcessor", u"Apply", None))
#if QT_CONFIG(accessibility)
        self.apply_result.setAccessibleName(QCoreApplication.translate("TextProcessor", u"Apply result to input", None))
#endif // QT_CONFIG(accessibility)
        self.reset_result.setText(QCoreApplication.translate("TextProcessor", u"Reset", None))
        self.clear_result.setText(QCoreApplication.translate("TextProcessor", u"Clear result", None))
        self.clear_all.setText(QCoreApplication.translate("TextProcessor", u"Clear all", None))
        self.copy_result.setText(QCoreApplication.translate("TextProcessor", u"Copy result", None))
#if QT_CONFIG(accessibility)
        self.result.setAccessibleName(QCoreApplication.translate("TextProcessor", u"Result", None))
#endif // QT_CONFIG(accessibility)
    # retranslateUi

