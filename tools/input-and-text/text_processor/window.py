"""Clipboard editor and operation controls using Qt's logical-coordinate layout."""

from collections.abc import Callable
from functools import partial
import re
import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QDropEvent, QTextCursor
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit, QStyle, QWidget

from utils import ConfigStore, path_text as paths, text_transforms as transforms
from utils.qt_clipboard import local_file_paths, read_clipboard_paths
from utils.qt_styles import set_button_style
from utils.qt_widgets import configure_qt_application, monospace_ui_font
from .ui_mainwindow import Ui_TextProcessor
from .ui_regex_dialog import Ui_RegexDialog


type Transform = Callable[[str], str]
_USE_RESULT = "use_result_for_next_operation"
_VARIABLE_SYNTAX = "variable_syntax"


def _raw(editor: QPlainTextEdit) -> str:
    # toPlainText() silently folds nonbreaking spaces into ordinary spaces.
    return editor.document().toRawText().replace("\u2029", "\n")


class RegexDialog(QDialog, Ui_RegexDialog):
    """Keep the expression, replacement and validation feedback together."""

    def __init__(self, window: "TextProcessor") -> None:
        super().__init__(window)
        self.processor = window
        self.setupUi(self)
        set_button_style(self.buttons.button(QDialogButtonBox.StandardButton.Ok), "orange")
        self.buttons.accepted.connect(self._replace)
        self.buttons.rejected.connect(self.reject)
        self.pattern.textChanged.connect(self.error.clear)
        self.replacement.textChanged.connect(self.error.clear)

    def _replace(self) -> None:
        try:
            flags = 0 if self.match_case.isChecked() else re.IGNORECASE
            result = re.sub(self.pattern.text(), self.replacement.text(), self.processor.operation_input(), flags=flags)
        except (re.error, IndexError, OverflowError) as exc:
            self.error.setText(str(exc))
            return
        self.error.clear()
        self.processor.result.setPlainText(result)
        self.accept()


class TextProcessor(QWidget, Ui_TextProcessor):
    """Apply one operation to the input and show its selectable result."""

    def __init__(self, *, from_clipboard: bool = False) -> None:
        super().__init__()
        self.setupUi(self)
        self.regex = RegexDialog(self)
        self.source.pasted.connect(self._sync_result_from_input)
        for target in (self, self.source.viewport(), self.result.viewport()):
            target.installEventFilter(self)
        font = monospace_ui_font()
        for editor in (self.source, self.result):
            editor.setFont(font)
        self.wrap.toggled.connect(self._set_wrap)
        self._set_wrap(self.wrap.isChecked())
        self.load_paths.clicked.connect(self._get_clipboard_paths)
        self.load_text.clicked.connect(self._load_clipboard_text)
        self.regex_button.clicked.connect(self.regex.exec)
        self.apply_result.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.apply_result.clicked.connect(lambda: self.source.setPlainText(_raw(self.result)))
        self.reset_result.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.reset_result.clicked.connect(self._sync_result_from_input)
        self.clear_result.clicked.connect(self.result.clear)
        self.clear_all.clicked.connect(self._clear_all)
        self.copy_result.clicked.connect(lambda: QApplication.clipboard().setText(_raw(self.result)))
        for button in (
            self.quick_clean, self.convert_separators, self.apply_path_action,
            self.to_tilde, self.to_home_variable, self.shorten_variable,
            self.clean_pdf, self.apply_text_action, self.style_letters, self.extract_hostnames,
            self.trim_lines, self.remove_blank_lines, self.indent_lines, self.expand_tabs,
            self.regex_button,
        ):
            set_button_style(button, "orange")
        for button in (self.to_absolute, self.expand_variable, self.plain_letters, self.unindent_lines, self.reset_result):
            set_button_style(button, "green")
        set_button_style(self.copy_result, "blue")
        self._configure_paths()
        self._configure_text()
        self._configure_lines()
        self.preference_notice.hide()
        self.store = ConfigStore("text-processor.yaml")
        self._restore_preferences()
        self.chain.toggled.connect(partial(self._save_preference, _USE_RESULT))
        self.variable_syntax.currentTextChanged.connect(partial(self._save_preference, _VARIABLE_SYNTAX))
        if from_clipboard:
            try:
                text, native_paths = read_clipboard_paths(parse_text_paths=False)
            except (OSError, RuntimeError) as exc:
                print(f"Could not load clipboard: {exc}", file=sys.stderr)
            else:
                self.source.setPlainText("\n".join(native_paths) if native_paths else text)
                self._sync_result_from_input()
        self.source.setFocus()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Route file drops on the window and its editors to the end of Input."""
        if not isinstance(event, QDropEvent) or not event.mimeData().hasUrls():
            return super().eventFilter(watched, event)
        urls = event.mimeData().urls()
        if not any(url.isLocalFile() for url in urls):
            return super().eventFilter(watched, event)
        if not (event.possibleActions() & Qt.DropAction.CopyAction):
            event.ignore()
            return True
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if event.type() == QEvent.Type.Drop:
            cursor = self.source.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            separator = "" if cursor.atBlockStart() else "\n"
            cursor.insertText(separator + "\n".join(local_file_paths(urls)))
            self.source.setTextCursor(cursor)
            self._sync_result_from_input()
        return True

    def _restore_preferences(self) -> None:
        try:
            saved = self.store.load()
        except (OSError, ValueError) as exc:
            self.preference_notice.setText(f"Could not load preferences: {exc}")
            self.preference_notice.show()
            saved = {}
        self.chain.setChecked(saved.get(_USE_RESULT) is not False)
        syntax = saved.get(_VARIABLE_SYNTAX)
        default = "cmd" if sys.platform == "win32" else "Bash"
        self.variable_syntax.setCurrentText(syntax if isinstance(syntax, str) and syntax in paths.ENV_STYLES else default)

    def _save_preference(self, key: str, value: bool | str) -> None:
        try:
            self.store.update({key: value})
        except (OSError, ValueError) as exc:
            self.preference_notice.setText(f"Could not save {key}: {exc}")
            self.preference_notice.show()
        else:
            self.preference_notice.hide()

    def _set_wrap(self, enabled: bool) -> None:
        mode = QPlainTextEdit.LineWrapMode
        for editor in (self.source, self.result):
            editor.setLineWrapMode(mode.WidgetWidth if enabled else mode.NoWrap)

    def _clear_all(self) -> None:
        self.source.clear()
        self.result.clear()

    def operation_input(self) -> str:
        """Select the visible result for chaining, falling back to the original input."""
        if self.chain.isChecked() and not self.result.document().isEmpty():
            return _raw(self.result)
        return _raw(self.source)

    def _apply(self, transform: Transform) -> None:
        self.result.setPlainText(transform(self.operation_input()))

    def _lines(self, transform: Transform) -> None:
        self._apply(lambda text: transforms.map_lines(text, transform))

    def _paths(self, transform: Transform) -> None:
        self._lines(lambda line: paths.transform_quoted_path(line, transform))

    def _sync_result_from_input(self) -> None:
        self.result.setPlainText(_raw(self.source))

    def _load_clipboard_text(self) -> None:
        mime = QApplication.clipboard().mimeData()
        # Qt also synthesizes text from file URLs when no plain text was copied.
        if mime is not None and any(fmt.partition(";")[0] == "text/plain" for fmt in mime.formats()):
            text = mime.text()
            if text.strip():
                self.source.insertPlainText(text)
                self._sync_result_from_input()
                return
        QMessageBox.warning(self, "Load text from clipboard", "No non-blank text found on the clipboard.")

    def _get_clipboard_paths(self) -> None:
        _, copied = read_clipboard_paths(preserve_text_separators=True)
        if not copied:
            QMessageBox.warning(self, "Load paths from clipboard", "No file paths found on the clipboard.")
            return
        self.source.setPlainText("\n".join(copied))
        self._sync_result_from_input()

    def _configure_paths(self) -> None:
        self.quick_clean.clicked.connect(lambda: self._lines(
            lambda line: paths.forward_path(paths.remove_file_prefix(paths.remove_quotes(line.strip())))))
        self.source_separator.addItems(list(paths.SEPARATORS))
        self.target_separator.addItems(list(paths.SEPARATORS))
        self.target_separator.setCurrentText("Forward slash")
        self.convert_separators.clicked.connect(lambda: self._paths(partial(
            paths.convert_separators, source=paths.SEPARATORS[self.source_separator.currentText()],
            target=paths.SEPARATORS[self.target_separator.currentText()],
        )))
        conversions: dict[str, Transform] = {
            "Windows → MSYS Bash": paths.to_msys,
            "MSYS → Windows (backslash)": partial(paths.from_msys, separator="\\"),
            "MSYS → Windows (forward slash)": partial(paths.from_msys, separator="/"),
            "MSYS → Windows (double backslash)": partial(paths.from_msys, separator="\\\\"),
            "Add file:// prefix": paths.add_file_prefix,
            "Remove file:// prefix": paths.remove_file_prefix,
        }
        quotes: dict[str, Transform] = {
            "Remove single quotes": partial(paths.remove_quotes, allowed="'"),
            "Remove double quotes": partial(paths.remove_quotes, allowed='"'),
            "Remove all paired quotes": paths.remove_quotes,
            "Add single quotes": partial(paths.add_quotes, mark="'"),
            "Add double quotes": partial(paths.add_quotes, mark='"'),
        }
        self.path_action.addItems([*conversions, *quotes])

        def apply_path_action() -> None:
            name = self.path_action.currentText()
            if name in quotes:
                self._lines(quotes[name])
            else:
                self._paths(conversions[name])

        self.apply_path_action.clicked.connect(apply_path_action)
        self.variable_syntax.addItems(list(paths.ENV_STYLES))
        self.to_tilde.clicked.connect(lambda: self._paths(partial(paths.home_path, target="~")))
        self.to_absolute.clicked.connect(lambda: self._paths(partial(paths.home_path, target="Absolute")))
        self.to_home_variable.clicked.connect(lambda: self._paths(
            partial(paths.home_path, target=self.variable_syntax.currentText())))
        self.shorten_variable.clicked.connect(lambda: self._paths(
            partial(paths.shorten_environment, style=self.variable_syntax.currentText())))
        self.expand_variable.clicked.connect(lambda: self._paths(paths.expand_environment))

    def _configure_text(self) -> None:
        self.clean_pdf.clicked.connect(lambda: self._apply(transforms.clean_pdf))
        actions: dict[str, Transform] = {
            "Expand ligatures": transforms.expand_ligatures,
            "Normalize spaces": transforms.normalize_spaces,
            "Join spaced letters": lambda text: re.sub(r" +", lambda m: " " if len(m[0]) > 1 else "", text),
            "Fullwidth → halfwidth": transforms.to_halfwidth,
            "Halfwidth → fullwidth": transforms.to_fullwidth,
            "Uppercase": str.upper, "Lowercase": str.lower, "Title case": transforms.title_words,
        }
        self.text_action.addItems(list(actions))
        self.apply_text_action.clicked.connect(lambda: self._apply(actions[self.text_action.currentText()]))
        for style in transforms.LETTER_STYLES:
            preview = transforms.style_letters("123ABCabc", style)
            self.letter_styles.addItem(f"{style}  {preview}", style)
        self.style_letters.clicked.connect(lambda: self._apply(
            partial(transforms.style_letters, style=self.letter_styles.currentData())))
        self.plain_letters.clicked.connect(lambda: self._apply(transforms.plain_letters))
        self.extract_hostnames.clicked.connect(lambda: self._lines(transforms.url_hostname))

    def _configure_lines(self) -> None:
        trim: dict[str, Transform] = {"Trim both sides": str.strip, "Trim left": str.lstrip, "Trim right": str.rstrip}
        self.trim_side.addItems(list(trim))
        self.trim_lines.clicked.connect(lambda: self._lines(trim[self.trim_side.currentText()]))
        self.remove_blank_lines.clicked.connect(lambda: self._apply(transforms.remove_blank_lines))
        self.indent_unit.addItems(["Spaces", "Tab"])
        self.indent_width.setRange(1, 32)
        self.indent_width.setValue(4)

        def prefix() -> str:
            return "\t" if self.indent_unit.currentText() == "Tab" else " " * self.indent_width.value()

        self.indent_lines.clicked.connect(lambda: self._lines(lambda line: prefix() + line))
        self.unindent_lines.clicked.connect(lambda: self._lines(lambda line: line.removeprefix(prefix())))
        self.expand_tabs.clicked.connect(lambda: self._lines(partial(transforms.expand_tabs, width=self.indent_width.value())))


def run(*, from_clipboard: bool = False) -> int:
    """Open the editor in a Fusion-styled Qt application."""
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv)
    configure_qt_application(app)
    window = TextProcessor(from_clipboard=from_clipboard)
    window.show()
    return app.exec()
