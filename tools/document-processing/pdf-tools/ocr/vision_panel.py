"""Per-mode transcription, formatting and conversation controls for image OCR."""

from PySide6 import QtCore, QtWidgets
from utils.qt_widgets import NoWheelComboBox
from .vision import FEATURES, OUTPUTS, VisionTask


class ModeOptions(QtWidgets.QScrollArea):
    """Edit one mode's preferences independently of provider settings."""
    clearRequested = QtCore.Signal()

    def __init__(self, formula: bool, saved: dict) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        page = QtWidgets.QWidget()
        self.setWidget(page)
        form = QtWidgets.QFormLayout(page)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)

        def choice(label: str, key: str, choices: list[tuple[str, str]], default: str = "") -> NoWheelComboBox:
            combo = NoWheelComboBox()
            for title, value in choices:
                combo.addItem(title, value)
            combo.setCurrentIndex(max(0, combo.findData(saved.get(key, default))))
            form.addRow(label, combo)
            return combo

        def check(label: str, key: str, default: bool = True) -> QtWidgets.QCheckBox:
            box = QtWidgets.QCheckBox(label)
            box.setChecked(saved.get(key, default) is True)
            form.addRow(box)
            return box

        self.context = QtWidgets.QLabel()
        self.reset_each = check("Reset context before each API request", "reset_each", False)
        self.clear = QtWidgets.QPushButton("Clear this context")
        self.clear.clicked.connect(self.clearRequested.emit)
        form.addRow(self.context, self.clear)
        self.content = choice("Image contains", "content", [
            ("Detect automatically", "auto"), ("Document (with or without math)", "mixed"), ("Formulas only", "formula")])
        self.output = choice("Output format", "output", [(label, name) for name, (label, _) in OUTPUTS.items()],
                             "markdown" if formula else "text")
        self.layout_choice = choice("Text layout", "layout", [
            ("Automatic", "auto"), ("Single column", "single"), ("Multiple columns", "columns")])
        self.keep_lines = check("Preserve visible line breaks", "keep_lines")
        self.delimiter = choice("Display math", "display", [
            ("Format default", "auto"), ("$$ … $$", "dollars"), (r"\[ … \]", "brackets")])
        self.inline = choice("Inline math", "inline", [
            ("Format default", "auto"), ("$ … $", "dollars"), (r"\( … \)", "parens")])
        self.multiline = choice("Multiline equations", "multiline", [
            ("Group by mathematical meaning", "auto"), ("Prefer one aligned block", "group"),
            ("Prefer separate blocks", "separate")])
        self.numbers = check("Keep equation numbers", "numbers")
        self.math_bold = check("Keep mathematical bold (e.g. vectors)", "math_bold")
        group = QtWidgets.QGroupBox("Preserve document formatting")
        grid = QtWidgets.QGridLayout(group)
        selected = saved.get("features", list(FEATURES))
        self.features: dict[str, QtWidgets.QCheckBox] = {}
        for i, name in enumerate(FEATURES):
            option = QtWidgets.QCheckBox(name)
            option.setChecked(not isinstance(selected, list) or name in selected)
            grid.addWidget(option, i // 2, i % 2)
            self.features[name] = option
        form.addRow(group)
        self.custom = QtWidgets.QPlainTextEdit()
        self.custom.setPlaceholderText("Additional instructions for this mode (optional)")
        form.addRow("Custom instructions", self.custom)
        prompt = saved.get("prompt")
        if isinstance(prompt, str):
            self.custom.setPlainText(prompt)
        self.content.currentIndexChanged.connect(self._availability)
        self.output.currentIndexChanged.connect(self._availability)
        self._availability()

    def _availability(self) -> None:
        prose = self.content.currentData() != "formula"
        markup = self.output.currentData() != "text"
        for widget in (self.layout_choice, self.keep_lines):
            widget.setEnabled(prose)
        for widget in (self.delimiter, self.multiline, self.numbers, self.math_bold):
            widget.setEnabled(markup)
        self.inline.setEnabled(prose and markup)
        for name, checkbox in self.features.items():
            checkbox.setEnabled(markup and (prose or name == "Colors"))

    def task(self) -> VisionTask:
        output = self.output.currentData()
        tex = output in ("fragment", "document")
        return VisionTask(output=output, content=self.content.currentData(), layout=self.layout_choice.currentData(),
                          keep_lines=self.keep_lines.isChecked(),
                          features=tuple(name for name, box in self.features.items() if box.isChecked()),
                          brackets=self.delimiter.currentData() == "brackets" or (tex and self.delimiter.currentData() == "auto"),
                          inline_parens=self.inline.currentData() == "parens" or (tex and self.inline.currentData() == "auto"),
                          multiline=self.multiline.currentData(), numbers=self.numbers.isChecked(),
                          math_bold=self.math_bold.isChecked(), custom=self.custom.toPlainText())

    def to_data(self) -> dict:
        task = self.task()
        return {"output": task.output, "content": task.content, "layout": task.layout, "keep_lines": task.keep_lines,
                "features": list(task.features), "display": self.delimiter.currentData(), "inline": self.inline.currentData(),
                "multiline": task.multiline, "numbers": task.numbers, "math_bold": task.math_bold,
                "prompt": task.custom, "reset_each": self.reset_each.isChecked()}


class VisionPanel(QtWidgets.QStackedWidget):
    """Restore both modes, including preferences from the original flat settings."""
    def load_modes(self, saved: object) -> None:
        """Create the text and formula pages from the window's saved preferences."""
        prefs = saved if isinstance(saved, dict) else {}
        text = {"layout": prefs.get("text_layout"), "keep_lines": prefs.get("keep_lines", True),
                "prompt": prefs.get("text_prompt")}
        formula = {"content": prefs.get("formula_content"), "display": prefs.get("formula_delimiter"),
                   "prompt": prefs.get("formula_prompt"), "math_bold": prefs.get("keep_style", True)}
        if prefs.get("keep_style") is False:
            formula["features"] = [name for name in FEATURES if name != "Colors"]
        self.text_page = ModeOptions(False, prefs["text"] if isinstance(prefs.get("text"), dict) else text)
        self.formula_page = ModeOptions(True, prefs["formula"] if isinstance(prefs.get("formula"), dict) else formula)
        self.addWidget(self.text_page)
        self.addWidget(self.formula_page)

    def active(self) -> ModeOptions:
        return self.formula_page if self.currentWidget() is self.formula_page else self.text_page

    def to_data(self) -> dict:
        return {"text": self.text_page.to_data(), "formula": self.formula_page.to_data()}
