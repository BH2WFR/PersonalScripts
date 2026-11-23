"""Clipboard editor and operation controls using Qt's logical-coordinate layout."""

from collections.abc import Callable, Iterable
from functools import partial
import re
import sys

from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QStyle, QTabWidget, QVBoxLayout, QWidget,
)

from utils import ConfigStore, path_text as paths, text_transforms as transforms
from utils.qt_clipboard import read_clipboard_paths
from utils.qt_widgets import NoWheelComboBox, NoWheelSpinBox, install_no_wheel_controls


type Transform = Callable[[str], str]
_USE_RESULT = "use_result_for_next_operation"
_VARIABLE_SYNTAX = "variable_syntax"


def _combo(labels: Iterable[str]) -> NoWheelComboBox:
    control = NoWheelComboBox()
    control.addItems(list(labels))
    return control


def _button(label: str, action: Callable[[], object]) -> QPushButton:
    control = QPushButton(label)
    control.clicked.connect(action)
    return control


def _row(*widgets: QWidget) -> QHBoxLayout:
    layout = QHBoxLayout()
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch()
    return layout


def _raw(editor: QPlainTextEdit) -> str:
    # toPlainText() silently folds nonbreaking spaces into ordinary spaces.
    return editor.document().toRawText().replace("\u2029", "\n")


class RegexDialog(QDialog):
    """Keep the expression, replacement and validation feedback together."""

    def __init__(self, window: "TextProcessor") -> None:
        super().__init__(window)
        self.processor = window
        self.setWindowTitle("Regular expression replacement")
        self.pattern = QLineEdit()
        self.replacement = QLineEdit()
        self.pattern.setPlaceholderText(r"(\w+),\s*(\w+)")
        self.replacement.setPlaceholderText(r"\2 \1")
        self.match_case = QCheckBox("Match case")
        self.match_case.setChecked(True)
        self.error = QLabel()
        self.error.setWordWrap(True)
        form = QFormLayout(self)
        form.addRow("Pattern", self.pattern)
        form.addRow("Replacement", self.replacement)
        form.addRow(QLabel(r"Use \1 or \g<name> for a captured group."))
        form.addRow(self.match_case)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._replace)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

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


class TextProcessor(QWidget):
    """Apply one operation to the input and show its selectable result."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Text Processor")
        self.source = QPlainTextEdit()
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.source.setAccessibleName("Input")
        self.result.setAccessibleName("Result")
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFamilies(["Consolas", font.family(), "Menlo", "DejaVu Sans Mono",
                          "Sarasa Mono SC", "Noto Sans Mono CJK SC", "Microsoft YaHei", "PingFang SC"])
        for editor in (self.source, self.result):
            editor.setFont(font)
        wrap = QCheckBox("Word wrap")
        wrap.toggled.connect(self._set_wrap)
        wrap.setChecked(True)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Input"))
        top.addStretch()
        top.addWidget(wrap)
        top.addWidget(_button("Paste from Clipboard", self.source.paste))
        layout.addLayout(top)
        layout.addWidget(self.source, 1)

        tabs = QTabWidget()
        tabs.addTab(self._path_tab(), "File paths")
        tabs.addTab(self._environment_tab(), "Home && variables")
        tabs.addTab(self._text_tab(), "Text")
        tabs.addTab(self._letter_style_tab(), "Letter Style")
        tabs.addTab(self._url_tab(), "URL")
        tabs.addTab(self._line_tab(), "Lines")
        layout.addWidget(tabs)
        self.regex = RegexDialog(self)
        controls = QHBoxLayout()
        self.chain = QCheckBox("Use result for the next operation")
        controls.addWidget(self.chain)
        controls.addStretch()
        controls.addWidget(_button("Regex replace…", self.regex.exec))
        layout.addLayout(controls)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Result"))
        bottom.addStretch()
        apply_result = _button("Apply", lambda: self.source.setPlainText(_raw(self.result)))
        apply_result.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        apply_result.setAccessibleName("Apply result to input")
        bottom.addWidget(apply_result)
        reset_result = _button("Reset", lambda: self.result.setPlainText(_raw(self.source)))
        reset_result.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        bottom.addWidget(reset_result)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        bottom.addWidget(divider)
        bottom.addWidget(_button("Clear result", self.result.clear))
        bottom.addWidget(_button("Clear all", self._clear_all))
        copy_result = _button("Copy result", lambda: QApplication.clipboard().setText(_raw(self.result)))
        copy_font = copy_result.font()
        copy_font.setBold(True)
        copy_result.setFont(copy_font)
        bottom.addWidget(copy_result)
        layout.addLayout(bottom)
        layout.addWidget(self.result, 1)
        self.preference_notice = QLabel()
        self.preference_notice.setWordWrap(True)
        self.preference_notice.hide()
        layout.addWidget(self.preference_notice)
        self.store = ConfigStore("text-processor.yaml")
        self._restore_preferences()
        self.chain.toggled.connect(partial(self._save_preference, _USE_RESULT))
        self.variable_syntax.currentTextChanged.connect(partial(self._save_preference, _VARIABLE_SYNTAX))
        self.resize(740, 660)

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

    def _get_clipboard_paths(self) -> None:
        source, copied = read_clipboard_paths()
        self.source.setPlainText(source)
        self.clipboard_notice.setVisible(not copied)
        if copied:
            self.result.setPlainText("\n".join(copied))

    def _path_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        quick = _button("Quick clean paths", lambda: self._lines(
            lambda line: paths.forward_path(paths.remove_file_prefix(paths.remove_quotes(line.strip())))))
        quick.setToolTip("Remove paired quotes and file://, then convert backslashes to forward slashes.")
        get_paths = _button("Get paths from clipboard", self._get_clipboard_paths)
        self.clipboard_notice = QLabel("No file paths found on the clipboard.")
        self.clipboard_notice.setWordWrap(True)
        self.clipboard_notice.hide()
        layout.addLayout(_row(quick, get_paths, self.clipboard_notice))
        source = _combo(paths.SEPARATORS)
        target = _combo(paths.SEPARATORS)
        target.setCurrentText("Forward slash")

        def separator() -> str:
            return paths.SEPARATORS[target.currentText()]

        layout.addLayout(_row(QLabel("From"), source, QLabel("to"), target,
                              _button("Convert", lambda: self._paths(partial(paths.convert_separators,
                                      source=paths.SEPARATORS[source.currentText()], target=separator())))))
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
        actions = {**conversions, **quotes}
        action = _combo(actions)

        def apply_path_action() -> None:
            name = action.currentText()
            if name in quotes:
                self._lines(quotes[name])
            else:
                self._paths(conversions[name])

        layout.addLayout(_row(action, _button("Apply to lines", apply_path_action)))
        return tab

    def _environment_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        shell = self.variable_syntax = _combo(paths.ENV_STYLES)
        layout.addLayout(_row(QLabel("Variable syntax"), shell))
        layout.addLayout(_row(
            QLabel("Home path"),
            _button("To ~", lambda: self._paths(partial(paths.home_path, target="~"))),
            _button("To absolute", lambda: self._paths(partial(paths.home_path, target="Absolute"))),
            _button("To home variable", lambda: self._paths(partial(paths.home_path, target=shell.currentText()))),
        ))
        layout.addLayout(_row(
            QLabel("System paths"),
            _button("Use longest variable", lambda: self._paths(partial(paths.shorten_environment, style=shell.currentText()))),
            _button("Expand variable", lambda: self._paths(paths.expand_environment)),
        ))
        return tab

    def _text_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addLayout(_row(_button("Clean copied PDF text", lambda: self._apply(transforms.clean_pdf))))
        actions: dict[str, Transform] = {
            "Expand ligatures": transforms.expand_ligatures,
            "Normalize spaces": transforms.normalize_spaces,
            "Join spaced letters": lambda text: re.sub(r" +", lambda m: " " if len(m[0]) > 1 else "", text),
            "Fullwidth → halfwidth": transforms.to_halfwidth,
            "Halfwidth → fullwidth": transforms.to_fullwidth,
            "Uppercase": str.upper, "Lowercase": str.lower, "Title case": transforms.title_words,
        }
        action = _combo(actions)
        layout.addLayout(_row(action, _button("Apply", lambda: self._apply(actions[action.currentText()]))))
        layout.addStretch()
        return tab

    def _letter_style_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        styles = NoWheelComboBox()
        for style in transforms.LETTER_STYLES:
            preview = transforms.style_letters("123ABCabc", style)
            styles.addItem(f"{style}  {preview}", style)
        layout.addLayout(_row(styles,
                              _button("Style letters and digits", lambda: self._apply(
                                  partial(transforms.style_letters, style=styles.currentData())))))
        layout.addLayout(_row(_button("Restore plain letters and digits", lambda: self._apply(transforms.plain_letters))))
        layout.addStretch()
        return tab

    def _url_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addLayout(_row(_button("Extract URL hostnames", lambda: self._lines(transforms.url_hostname))))
        layout.addStretch()
        return tab

    def _line_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        trim: dict[str, Transform] = {"Trim both sides": str.strip, "Trim left": str.lstrip, "Trim right": str.rstrip}
        side = _combo(trim)
        layout.addLayout(_row(side, _button("Trim lines", lambda: self._lines(trim[side.currentText()])),
                              _button("Remove blank lines", lambda: self._apply(transforms.remove_blank_lines))))
        unit = _combo(("Spaces", "Tab"))
        width = NoWheelSpinBox()
        width.setRange(1, 32)
        width.setValue(4)

        def prefix() -> str:
            return "\t" if unit.currentText() == "Tab" else " " * width.value()

        layout.addLayout(_row(QLabel("Indent with"), unit, QLabel("Space / tab width"), width))
        layout.addLayout(_row(_button("Indent", lambda: self._lines(lambda line: prefix() + line)),
                              _button("Unindent", lambda: self._lines(lambda line: line.removeprefix(prefix()))),
                              _button("Tabs to spaces", lambda: self._lines(
                                  partial(transforms.expand_tabs, width=width.value())))))
        return tab


def run() -> int:
    """Open the editor in a Fusion-styled Qt application."""
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv)
    app.setStyle("Fusion")
    install_no_wheel_controls(app)
    window = TextProcessor()
    window.show()
    return app.exec()
