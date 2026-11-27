"""Two-pane editor for the language alternatives of an XMP title."""

import re

from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets

from utils.qt_styles import on_theme_change, theme_text_color, theme_tint
from .ui_titles import Ui_TitleDialog


def _language_name(tag: str) -> str:
    if tag.lower() == "x-default":
        return "Default (x-default)"
    locale = QtCore.QLocale
    language = locale.codeToLanguage(tag.split("-")[0])
    if language in (locale.Language.AnyLanguage, locale.Language.C):
        return tag
    return f"{locale.languageToString(language)} ({tag})"


class _LanguageDelegate(QtWidgets.QStyledItemDelegate):
    def initStyleOption(self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex) -> None:
        super().initStyleOption(option, index)
        brush = index.data(QtCore.Qt.ItemDataRole.ForegroundRole)
        if isinstance(brush, QtGui.QBrush):
            palette: QtGui.QPalette = option.palette  # pyright: ignore[reportAttributeAccessIssue]
            palette.setBrush(QtGui.QPalette.ColorRole.HighlightedText, brush)
            view = cast(QtWidgets.QWidget, self.parent())
            palette.setColor(QtGui.QPalette.ColorRole.Highlight, theme_tint("green", view, selected=True))


class TitleDialog(QtWidgets.QDialog, Ui_TitleDialog):
    """Edit a private draft so Cancel rolls back every operation, including Remove all."""

    def __init__(self, titles: dict[str, str], parent: QtWidgets.QWidget, *, has_property: bool) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.titles = dict(titles)
        self.removed_all = False
        self._has_property = has_property
        locale = QtCore.QLocale
        tags = {locale.languageToCode(language) for language in locale.Language
                if language not in (locale.Language.AnyLanguage, locale.Language.C)}
        tags.discard("")
        tags.update(("x-default", "zh-Hans", "zh-Hant"))
        self._tags = {tag.lower(): tag for tag in tags}
        self._tags.update((tag.lower(), tag) for tag in titles)
        self._labels = {tag: _language_name(tag) for tag in self._tags.values()}

        self.languages.setItemDelegate(_LanguageDelegate(self.languages))
        self.add_language.clicked.connect(self._add_language)
        self.clear_one.clicked.connect(self._clear_one)
        self.split.setChildrenCollapsible(False)
        self.split.setStretchFactor(1, 2)
        self.clear_all = self.buttons.addButton("Remove all multilingual titles", QtWidgets.QDialogButtonBox.ButtonRole.ResetRole)
        self.clear_all.setToolTip("Remove the entire XMP title property. Keep the ordinary PDF title.")
        self.clear_all.clicked.connect(self._clear_all)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.languages.currentItemChanged.connect(self._select)
        self.editor.textChanged.connect(self._edit)
        on_theme_change(self.languages, self._color_languages)
        self._list_languages(None)
        self._select()

    def _tag(self) -> str:
        item = self.languages.currentItem()
        assert item is not None
        return item.data(QtCore.Qt.ItemDataRole.UserRole)

    def _list_languages(self, selected: str | None) -> None:
        ordered = sorted(self._labels, key=lambda tag: (
            not bool(self.titles.get(tag)), tag != "x-default", self._labels[tag].casefold()))
        with QtCore.QSignalBlocker(self.languages):
            self.languages.clear()
            for tag in ordered:
                item = QtWidgets.QListWidgetItem(self._labels[tag], self.languages)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, tag)
                if self.titles.get(tag):
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
            self._color_languages()
            self.languages.setCurrentRow(ordered.index(selected) if selected else 0)
            current = self.languages.currentItem()
            assert current is not None
            self.languages.scrollToItem(current)

    def _color_languages(self) -> None:
        foreground, background = theme_text_color("green", self.languages), theme_tint("green", self.languages)
        for row in range(self.languages.count()):
            item = self.languages.item(row)
            if item.font().bold():
                item.setForeground(foreground)
                item.setBackground(background)

    def _select(self) -> None:
        tag = self._tag()
        self.label.setText(f"Title · {self._labels[tag]}")
        with QtCore.QSignalBlocker(self.editor):
            self.editor.setPlainText(self.titles.get(tag, ""))
        self._buttons()

    def _buttons(self) -> None:
        self.clear_one.setEnabled(self._tag() in self.titles)
        self.clear_all.setEnabled(bool(self.titles) or self._has_property and not self.removed_all)

    def _edit(self) -> None:
        tag = self._tag()
        had_text = bool(self.titles.get(tag))
        text = self.editor.toPlainText()
        if text:
            self.titles[tag] = text
        else:
            self.titles.pop(tag, None)
        if had_text != bool(text):
            self._list_languages(tag)
        self._buttons()

    def _clear_one(self) -> None:
        self.editor.clear()
        self._edit()  # Also remove an existing empty rdf:li.

    def _clear_all(self) -> None:
        tag = self._tag()
        self.titles.clear()
        self.removed_all = True
        self._list_languages(tag)
        self._select()

    def _add_language(self) -> None:
        text, ok = QtWidgets.QInputDialog.getText(self, "Add language", "Language tag (e.g. en-GB or zh-Hant):")
        if not ok:
            return
        tag = text.strip()
        if not re.fullmatch(r"[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*", tag):
            QtWidgets.QMessageBox.warning(self, "Invalid language", "Enter a language tag with hyphen-separated subtags.")
            return
        tag = self._tags.setdefault(tag.lower(), tag)
        self._labels.setdefault(tag, _language_name(tag))
        self._list_languages(tag)
        self._select()
        self.editor.setFocus()
