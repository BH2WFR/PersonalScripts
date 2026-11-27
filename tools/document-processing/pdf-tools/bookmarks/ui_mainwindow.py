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
from PySide6.QtWidgets import (QApplication, QCheckBox, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QTabWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..common.crop_viewer import CropViewer
from ..common.navigation import PageTree
from ..common.page_toolbar import (PageToolbar, PreviewPane)
from utils.qt_widgets import (NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox)

class Ui_BookmarksWindow(object):
    def setupUi(self, BookmarksWindow):
        if not BookmarksWindow.objectName():
            BookmarksWindow.setObjectName(u"BookmarksWindow")
        BookmarksWindow.resize(1500, 950)
        BookmarksWindow.setMinimumSize(QSize(1050, 650))
        self.splitter = QSplitter(BookmarksWindow)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Horizontal)
        self.left = QWidget(self.splitter)
        self.left.setObjectName(u"left")
        self.left_layout = QVBoxLayout(self.left)
        self.left_layout.setObjectName(u"left_layout")
        self.left_layout.setContentsMargins(6, 6, 6, 6)
        self.files = QWidget(self.left)
        self.files.setObjectName(u"files")
        self.file_actions = QHBoxLayout(self.files)
        self.file_actions.setObjectName(u"file_actions")
        self.file_actions.setContentsMargins(0, 0, 0, 0)
        self.open_button = QPushButton(self.files)
        self.open_button.setObjectName(u"open_button")

        self.file_actions.addWidget(self.open_button)

        self.close_pdf_button = QPushButton(self.files)
        self.close_pdf_button.setObjectName(u"close_pdf_button")

        self.file_actions.addWidget(self.close_pdf_button)


        self.left_layout.addWidget(self.files)

        self.tabs = QTabWidget(self.left)
        self.tabs.setObjectName(u"tabs")
        self.recognition_scroll = QScrollArea()
        self.recognition_scroll.setObjectName(u"recognition_scroll")
        self.recognition_scroll.setWidgetResizable(True)
        self.recognition_scroll.setFrameShape(QFrame.NoFrame)
        self.recognition = QWidget()
        self.recognition.setObjectName(u"recognition")
        self.recognition_form = QFormLayout(self.recognition)
        self.recognition_form.setObjectName(u"recognition_form")
        self.toc_first_row_label = QLabel(self.recognition)
        self.toc_first_row_label.setObjectName(u"toc_first_row_label")

        self.recognition_form.setWidget(0, QFormLayout.LabelRole, self.toc_first_row_label)

        self.toc_first_row = QHBoxLayout()
        self.toc_first_row.setObjectName(u"toc_first_row")
        self.toc_first = NoWheelSpinBox(self.recognition)
        self.toc_first.setObjectName(u"toc_first")

        self.toc_first_row.addWidget(self.toc_first)

        self.toc_first_current_button = QPushButton(self.recognition)
        self.toc_first_current_button.setObjectName(u"toc_first_current_button")

        self.toc_first_row.addWidget(self.toc_first_current_button)

        self.toc_first_row.setStretch(0, 1)

        self.recognition_form.setLayout(0, QFormLayout.FieldRole, self.toc_first_row)

        self.toc_last_row_label = QLabel(self.recognition)
        self.toc_last_row_label.setObjectName(u"toc_last_row_label")

        self.recognition_form.setWidget(1, QFormLayout.LabelRole, self.toc_last_row_label)

        self.toc_last_row = QHBoxLayout()
        self.toc_last_row.setObjectName(u"toc_last_row")
        self.toc_last = NoWheelSpinBox(self.recognition)
        self.toc_last.setObjectName(u"toc_last")

        self.toc_last_row.addWidget(self.toc_last)

        self.toc_last_current_button = QPushButton(self.recognition)
        self.toc_last_current_button.setObjectName(u"toc_last_current_button")

        self.toc_last_row.addWidget(self.toc_last_current_button)

        self.toc_last_row.setStretch(0, 1)

        self.recognition_form.setLayout(1, QFormLayout.FieldRole, self.toc_last_row)

        self.body_pdf_row_label = QLabel(self.recognition)
        self.body_pdf_row_label.setObjectName(u"body_pdf_row_label")

        self.recognition_form.setWidget(2, QFormLayout.LabelRole, self.body_pdf_row_label)

        self.body_pdf_row = QHBoxLayout()
        self.body_pdf_row.setObjectName(u"body_pdf_row")
        self.body_pdf = NoWheelSpinBox(self.recognition)
        self.body_pdf.setObjectName(u"body_pdf")

        self.body_pdf_row.addWidget(self.body_pdf)

        self.body_pdf_current_button = QPushButton(self.recognition)
        self.body_pdf_current_button.setObjectName(u"body_pdf_current_button")

        self.body_pdf_row.addWidget(self.body_pdf_current_button)

        self.body_pdf_row.setStretch(0, 1)

        self.recognition_form.setLayout(2, QFormLayout.FieldRole, self.body_pdf_row)

        self.body_book_label = QLabel(self.recognition)
        self.body_book_label.setObjectName(u"body_book_label")

        self.recognition_form.setWidget(3, QFormLayout.LabelRole, self.body_book_label)

        self.body_book = NoWheelSpinBox(self.recognition)
        self.body_book.setObjectName(u"body_book")

        self.recognition_form.setWidget(3, QFormLayout.FieldRole, self.body_book)

        self.toc_actions = QHBoxLayout()
        self.toc_actions.setObjectName(u"toc_actions")
        self.mark_toc_button = QPushButton(self.recognition)
        self.mark_toc_button.setObjectName(u"mark_toc_button")
        font = QFont()
        font.setBold(True)
        self.mark_toc_button.setFont(font)

        self.toc_actions.addWidget(self.mark_toc_button)

        self.clear_toc_button = QPushButton(self.recognition)
        self.clear_toc_button.setObjectName(u"clear_toc_button")

        self.toc_actions.addWidget(self.clear_toc_button)


        self.recognition_form.setLayout(4, QFormLayout.SpanningRole, self.toc_actions)

        self.angle_label = QLabel(self.recognition)
        self.angle_label.setObjectName(u"angle_label")

        self.recognition_form.setWidget(5, QFormLayout.LabelRole, self.angle_label)

        self.angle = NoWheelDoubleSpinBox(self.recognition)
        self.angle.setObjectName(u"angle")

        self.recognition_form.setWidget(5, QFormLayout.FieldRole, self.angle)

        self.crop_row = QHBoxLayout()
        self.crop_row.setObjectName(u"crop_row")
        self.draw_crop = QCheckBox(self.recognition)
        self.draw_crop.setObjectName(u"draw_crop")

        self.crop_row.addWidget(self.draw_crop)

        self.whole_page = QPushButton(self.recognition)
        self.whole_page.setObjectName(u"whole_page")

        self.crop_row.addWidget(self.whole_page)

        self.unmark = QPushButton(self.recognition)
        self.unmark.setObjectName(u"unmark")

        self.crop_row.addWidget(self.unmark)


        self.recognition_form.setLayout(6, QFormLayout.SpanningRole, self.crop_row)

        self.requirement_scope = NoWheelComboBox(self.recognition)
        self.requirement_scope.setObjectName(u"requirement_scope")

        self.recognition_form.setWidget(7, QFormLayout.SpanningRole, self.requirement_scope)

        self.requirements = QPlainTextEdit(self.recognition)
        self.requirements.setObjectName(u"requirements")
        self.requirements.setMaximumSize(QSize(16777215, 105))

        self.recognition_form.setWidget(8, QFormLayout.SpanningRole, self.requirements)

        self.clear_context = QCheckBox(self.recognition)
        self.clear_context.setObjectName(u"clear_context")

        self.recognition_form.setWidget(9, QFormLayout.SpanningRole, self.clear_context)

        self.only_pending = QCheckBox(self.recognition)
        self.only_pending.setObjectName(u"only_pending")

        self.recognition_form.setWidget(10, QFormLayout.SpanningRole, self.only_pending)

        self.append_existing = QCheckBox(self.recognition)
        self.append_existing.setObjectName(u"append_existing")

        self.recognition_form.setWidget(11, QFormLayout.SpanningRole, self.append_existing)

        self.outline_actions = QHBoxLayout()
        self.outline_actions.setObjectName(u"outline_actions")
        self.add_roots = QPushButton(self.recognition)
        self.add_roots.setObjectName(u"add_roots")

        self.outline_actions.addWidget(self.add_roots)

        self.clear_bookmarks = QPushButton(self.recognition)
        self.clear_bookmarks.setObjectName(u"clear_bookmarks")

        self.outline_actions.addWidget(self.clear_bookmarks)

        self.undo_bookmarks = QPushButton(self.recognition)
        self.undo_bookmarks.setObjectName(u"undo_bookmarks")

        self.outline_actions.addWidget(self.undo_bookmarks)


        self.recognition_form.setLayout(12, QFormLayout.SpanningRole, self.outline_actions)

        self.recognition_scroll.setWidget(self.recognition)
        self.tabs.addTab(self.recognition_scroll, "")
        self.labels_tab = QWidget()
        self.labels_tab.setObjectName(u"labels_tab")
        self.label_form = QFormLayout(self.labels_tab)
        self.label_form.setObjectName(u"label_form")
        self.range_slot_label = QLabel(self.labels_tab)
        self.range_slot_label.setObjectName(u"range_slot_label")

        self.label_form.setWidget(0, QFormLayout.LabelRole, self.range_slot_label)

        self.range_slot = QVBoxLayout()
        self.range_slot.setObjectName(u"range_slot")

        self.label_form.setLayout(0, QFormLayout.FieldRole, self.range_slot)

        self.label_first_label = QLabel(self.labels_tab)
        self.label_first_label.setObjectName(u"label_first_label")

        self.label_form.setWidget(1, QFormLayout.LabelRole, self.label_first_label)

        self.label_first = NoWheelSpinBox(self.labels_tab)
        self.label_first.setObjectName(u"label_first")

        self.label_form.setWidget(1, QFormLayout.FieldRole, self.label_first)

        self.label_prefix_label = QLabel(self.labels_tab)
        self.label_prefix_label.setObjectName(u"label_prefix_label")

        self.label_form.setWidget(2, QFormLayout.LabelRole, self.label_prefix_label)

        self.label_prefix = QLineEdit(self.labels_tab)
        self.label_prefix.setObjectName(u"label_prefix")

        self.label_form.setWidget(2, QFormLayout.FieldRole, self.label_prefix)

        self.label_buttons = QGridLayout()
        self.label_buttons.setObjectName(u"label_buttons")
        self.label_numbered = QPushButton(self.labels_tab)
        self.label_numbered.setObjectName(u"label_numbered")

        self.label_buttons.addWidget(self.label_numbered, 0, 0, 1, 1)

        self.label_clear = QPushButton(self.labels_tab)
        self.label_clear.setObjectName(u"label_clear")

        self.label_buttons.addWidget(self.label_clear, 0, 1, 1, 1)

        self.label_clear_all = QPushButton(self.labels_tab)
        self.label_clear_all.setObjectName(u"label_clear_all")

        self.label_buttons.addWidget(self.label_clear_all, 1, 0, 1, 1)

        self.generate_labels = QPushButton(self.labels_tab)
        self.generate_labels.setObjectName(u"generate_labels")

        self.label_buttons.addWidget(self.generate_labels, 1, 1, 1, 1)

        self.label_buttons.setColumnStretch(0, 1)
        self.label_buttons.setColumnStretch(1, 1)

        self.label_form.setLayout(3, QFormLayout.SpanningRole, self.label_buttons)

        self.label_note = QLabel(self.labels_tab)
        self.label_note.setObjectName(u"label_note")
        self.label_note.setWordWrap(True)

        self.label_form.setWidget(4, QFormLayout.SpanningRole, self.label_note)

        self.tabs.addTab(self.labels_tab, "")

        self.left_layout.addWidget(self.tabs)

        self.run_actions = QHBoxLayout()
        self.run_actions.setObjectName(u"run_actions")
        self.run_button = QPushButton(self.left)
        self.run_button.setObjectName(u"run_button")

        self.run_actions.addWidget(self.run_button)

        self.retry_button = QPushButton(self.left)
        self.retry_button.setObjectName(u"retry_button")

        self.run_actions.addWidget(self.retry_button)

        self.retry_all_button = QPushButton(self.left)
        self.retry_all_button.setObjectName(u"retry_all_button")

        self.run_actions.addWidget(self.retry_all_button)


        self.left_layout.addLayout(self.run_actions)

        self.yaml_label = QLabel(self.left)
        self.yaml_label.setObjectName(u"yaml_label")

        self.left_layout.addWidget(self.yaml_label)

        self.result_tabs = QTabWidget(self.left)
        self.result_tabs.setObjectName(u"result_tabs")
        self.yaml = QPlainTextEdit()
        self.yaml.setObjectName(u"yaml")
        self.result_tabs.addTab(self.yaml, "")
        self.trace = QPlainTextEdit()
        self.trace.setObjectName(u"trace")
        self.result_tabs.addTab(self.trace, "")
        self.information_tab = QWidget()
        self.information_tab.setObjectName(u"information_tab")
        self.information_layout = QVBoxLayout(self.information_tab)
        self.information_layout.setObjectName(u"information_layout")
        self.information_status = QLabel(self.information_tab)
        self.information_status.setObjectName(u"information_status")
        self.information_status.setWordWrap(True)

        self.information_layout.addWidget(self.information_status)

        self.information = QPlainTextEdit(self.information_tab)
        self.information.setObjectName(u"information")

        self.information_layout.addWidget(self.information)

        self.instructions_label = QLabel(self.information_tab)
        self.instructions_label.setObjectName(u"instructions_label")

        self.information_layout.addWidget(self.instructions_label)

        self.information_input = QPlainTextEdit(self.information_tab)
        self.information_input.setObjectName(u"information_input")
        self.information_input.setMaximumSize(QSize(16777215, 100))

        self.information_layout.addWidget(self.information_input)

        self.information_retry = QPushButton(self.information_tab)
        self.information_retry.setObjectName(u"information_retry")

        self.information_layout.addWidget(self.information_retry)

        self.information_layout.setStretch(1, 1)
        self.result_tabs.addTab(self.information_tab, "")

        self.left_layout.addWidget(self.result_tabs)

        self.yaml_status = QLabel(self.left)
        self.yaml_status.setObjectName(u"yaml_status")
        self.yaml_status.setWordWrap(True)
        self.yaml_status.setMaximumSize(QSize(16777215, 65))

        self.left_layout.addWidget(self.yaml_status)

        self.yaml_actions = QWidget(self.left)
        self.yaml_actions.setObjectName(u"yaml_actions")
        self.yaml_buttons = QHBoxLayout(self.yaml_actions)
        self.yaml_buttons.setObjectName(u"yaml_buttons")
        self.yaml_buttons.setContentsMargins(0, 0, 0, 0)
        self.apply_yaml = QPushButton(self.yaml_actions)
        self.apply_yaml.setObjectName(u"apply_yaml")

        self.yaml_buttons.addWidget(self.apply_yaml)

        self.supplement_button = QPushButton(self.yaml_actions)
        self.supplement_button.setObjectName(u"supplement_button")

        self.yaml_buttons.addWidget(self.supplement_button)

        self.copy_image = QPushButton(self.yaml_actions)
        self.copy_image.setObjectName(u"copy_image")

        self.yaml_buttons.addWidget(self.copy_image)


        self.left_layout.addWidget(self.yaml_actions)

        self.left_layout.setStretch(4, 1)
        self.splitter.addWidget(self.left)
        self.right_column = QWidget(self.splitter)
        self.right_column.setObjectName(u"right_column")
        self.right_layout = QVBoxLayout(self.right_column)
        self.right_layout.setObjectName(u"right_layout")
        self.right_layout.setContentsMargins(3, 6, 6, 6)
        self.preview_pane = PreviewPane(self.right_column)
        self.preview_pane.setObjectName(u"preview_pane")
        self.preview_body = QWidget(self.preview_pane)
        self.preview_body.setObjectName(u"preview_body")
        self.preview_layout = QVBoxLayout(self.preview_body)
        self.preview_layout.setObjectName(u"preview_layout")
        self.preview_layout.setContentsMargins(0, 0, 0, 0)
        self.content = QSplitter(self.preview_body)
        self.content.setObjectName(u"content")
        self.content.setOrientation(Qt.Horizontal)
        self.viewer = CropViewer(self.content)
        self.viewer.setObjectName(u"viewer")
        self.content.addWidget(self.viewer)
        self.navigation = QTabWidget(self.content)
        self.navigation.setObjectName(u"navigation")
        self.pages_panel = QWidget()
        self.pages_panel.setObjectName(u"pages_panel")
        self.pages_layout = QVBoxLayout(self.pages_panel)
        self.pages_layout.setObjectName(u"pages_layout")
        self.pages_layout.setContentsMargins(0, 0, 0, 0)
        self.pages = PageTree(self.pages_panel)
        self.pages.setObjectName(u"pages")

        self.pages_layout.addWidget(self.pages)

        self.delete_pages_button = QPushButton(self.pages_panel)
        self.delete_pages_button.setObjectName(u"delete_pages_button")

        self.pages_layout.addWidget(self.delete_pages_button)

        self.navigation.addTab(self.pages_panel, "")
        self.content.addWidget(self.navigation)

        self.preview_layout.addWidget(self.content)

        self.footer = QHBoxLayout()
        self.footer.setObjectName(u"footer")
        self.status = QLabel(self.preview_body)
        self.status.setObjectName(u"status")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.status.sizePolicy().hasHeightForWidth())
        self.status.setSizePolicy(sizePolicy)

        self.footer.addWidget(self.status)

        self.progress_bar = QProgressBar(self.preview_body)
        self.progress_bar.setObjectName(u"progress_bar")
        self.progress_bar.setMinimumSize(QSize(180, 0))
        self.progress_bar.setMaximumSize(QSize(180, 16777215))

        self.footer.addWidget(self.progress_bar)

        self.task_slot = QHBoxLayout()
        self.task_slot.setObjectName(u"task_slot")

        self.footer.addLayout(self.task_slot)

        self.balance_summary = QLabel(self.preview_body)
        self.balance_summary.setObjectName(u"balance_summary")

        self.footer.addWidget(self.balance_summary)

        self.export_button = QPushButton(self.preview_body)
        self.export_button.setObjectName(u"export_button")

        self.footer.addWidget(self.export_button)

        self.footer.setStretch(0, 1)

        self.preview_layout.addLayout(self.footer)

        self.preview_layout.setStretch(0, 1)
        self.preview_pane.setCentralWidget(self.preview_body)
        self.toolbar = PageToolbar(self.preview_pane)
        self.toolbar.setObjectName(u"toolbar")
        self.toolbar.setMovable(False)
        self.preview_pane.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        self.right_layout.addWidget(self.preview_pane)

        self.splitter.addWidget(self.right_column)
        BookmarksWindow.setCentralWidget(self.splitter)
#if QT_CONFIG(shortcut)
        self.body_book_label.setBuddy(self.body_book)
        self.angle_label.setBuddy(self.angle)
        self.label_first_label.setBuddy(self.label_first)
        self.label_prefix_label.setBuddy(self.label_prefix)
#endif // QT_CONFIG(shortcut)

        self.retranslateUi(BookmarksWindow)

        QMetaObject.connectSlotsByName(BookmarksWindow)
    # setupUi

    def retranslateUi(self, BookmarksWindow):
        BookmarksWindow.setWindowTitle(QCoreApplication.translate("BookmarksWindow", u"PDF Bookmark Editor", None))
        self.open_button.setText(QCoreApplication.translate("BookmarksWindow", u"Open PDF", None))
        self.close_pdf_button.setText(QCoreApplication.translate("BookmarksWindow", u"Close", None))
        self.toc_first_row_label.setText(QCoreApplication.translate("BookmarksWindow", u"First TOC PDF page", None))
        self.toc_first_current_button.setText(QCoreApplication.translate("BookmarksWindow", u"Use current", None))
        self.toc_last_row_label.setText(QCoreApplication.translate("BookmarksWindow", u"Last TOC PDF page", None))
        self.toc_last_current_button.setText(QCoreApplication.translate("BookmarksWindow", u"Use current", None))
        self.body_pdf_row_label.setText(QCoreApplication.translate("BookmarksWindow", u"First body PDF page", None))
        self.body_pdf_current_button.setText(QCoreApplication.translate("BookmarksWindow", u"Use current", None))
        self.body_book_label.setText(QCoreApplication.translate("BookmarksWindow", u"Its printed page number", None))
        self.mark_toc_button.setText(QCoreApplication.translate("BookmarksWindow", u"Mark TOC", None))
        self.clear_toc_button.setText(QCoreApplication.translate("BookmarksWindow", u"Clear TOC", None))
        self.angle_label.setText(QCoreApplication.translate("BookmarksWindow", u"Current TOC rotation", None))
        self.draw_crop.setText(QCoreApplication.translate("BookmarksWindow", u"Draw recognition box", None))
        self.whole_page.setText(QCoreApplication.translate("BookmarksWindow", u"Whole page", None))
        self.unmark.setText(QCoreApplication.translate("BookmarksWindow", u"Unmark", None))
        self.clear_context.setText(QCoreApplication.translate("BookmarksWindow", u"Clear conversation before this run / retry", None))
        self.only_pending.setText(QCoreApplication.translate("BookmarksWindow", u"Run only pending / failed pages", None))
        self.append_existing.setText(QCoreApplication.translate("BookmarksWindow", u"Keep existing PDF bookmarks", None))
        self.add_roots.setText(QCoreApplication.translate("BookmarksWindow", u"Add Cover + TOC", None))
        self.clear_bookmarks.setText(QCoreApplication.translate("BookmarksWindow", u"Clear bookmarks", None))
        self.undo_bookmarks.setText(QCoreApplication.translate("BookmarksWindow", u"Undo", None))
        self.tabs.setTabText(self.tabs.indexOf(self.recognition_scroll), QCoreApplication.translate("BookmarksWindow", u"Recognition", None))
        self.range_slot_label.setText(QCoreApplication.translate("BookmarksWindow", u"PDF pages", None))
        self.label_first_label.setText(QCoreApplication.translate("BookmarksWindow", u"Starting number", None))
        self.label_prefix_label.setText(QCoreApplication.translate("BookmarksWindow", u"Prefix", None))
        self.label_numbered.setText(QCoreApplication.translate("BookmarksWindow", u"Apply numbered labels", None))
        self.label_clear.setText(QCoreApplication.translate("BookmarksWindow", u"Clear selected labels", None))
        self.label_clear_all.setText(QCoreApplication.translate("BookmarksWindow", u"Clear all labels", None))
        self.generate_labels.setText(QCoreApplication.translate("BookmarksWindow", u"Generate TOC + body labels", None))
        self.label_note.setText(QCoreApplication.translate("BookmarksWindow", u"Navigation labels only; printed page content stays unchanged.", None))
        self.tabs.setTabText(self.tabs.indexOf(self.labels_tab), QCoreApplication.translate("BookmarksWindow", u"Page labels", None))
        self.run_button.setText(QCoreApplication.translate("BookmarksWindow", u"Run TOC", None))
        self.retry_button.setText(QCoreApplication.translate("BookmarksWindow", u"Retry page", None))
        self.retry_all_button.setText(QCoreApplication.translate("BookmarksWindow", u"Retry all", None))
        self.yaml_label.setText(QCoreApplication.translate("BookmarksWindow", u"YAML draft \u2014 current TOC page", None))
        self.result_tabs.setTabText(self.result_tabs.indexOf(self.yaml), QCoreApplication.translate("BookmarksWindow", u"YAML draft", None))
        self.result_tabs.setTabText(self.result_tabs.indexOf(self.trace), QCoreApplication.translate("BookmarksWindow", u"Request / errors", None))
        self.information_status.setText(QCoreApplication.translate("BookmarksWindow", u"No page selected.", None))
        self.instructions_label.setText(QCoreApplication.translate("BookmarksWindow", u"Additional instructions for this page", None))
        self.information_retry.setText(QCoreApplication.translate("BookmarksWindow", u"Retry page", None))
        self.result_tabs.setTabText(self.result_tabs.indexOf(self.information_tab), QCoreApplication.translate("BookmarksWindow", u"Information", None))
        self.yaml_status.setText(QCoreApplication.translate("BookmarksWindow", u"Valid YAML updates the tree. Export uses the tree.", None))
        self.apply_yaml.setText(QCoreApplication.translate("BookmarksWindow", u"Apply YAML", None))
        self.supplement_button.setText(QCoreApplication.translate("BookmarksWindow", u"Add page information", None))
        self.copy_image.setText(QCoreApplication.translate("BookmarksWindow", u"Copy recognition image", None))
        ___qtreewidgetitem = self.pages.headerItem()
        ___qtreewidgetitem.setText(2, QCoreApplication.translate("BookmarksWindow", u"TOC task", None));
        ___qtreewidgetitem.setText(1, QCoreApplication.translate("BookmarksWindow", u"Label", None));
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("BookmarksWindow", u"Page", None));
        self.delete_pages_button.setText(QCoreApplication.translate("BookmarksWindow", u"Delete selected pages...", None))
        self.navigation.setTabText(self.navigation.indexOf(self.pages_panel), QCoreApplication.translate("BookmarksWindow", u"Pages", None))
        self.status.setText(QCoreApplication.translate("BookmarksWindow", u"Open or drop a PDF.", None))
        self.balance_summary.setText(QCoreApplication.translate("BookmarksWindow", u"API balance: not queried", None))
        self.export_button.setText(QCoreApplication.translate("BookmarksWindow", u"Export PDF", None))
        self.toolbar.setWindowTitle("")
    # retranslateUi

