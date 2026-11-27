"""Compact rule editor with PDF-source discovery and explicit target style faces."""

from PySide6 import QtCore, QtGui, QtWidgets
from utils import *
from .engine import _Embedding
from .model import ReplacementRule
from .ui_settings import Ui_RulePanel


class RulePanel(QtWidgets.QWidget, Ui_RulePanel):
    """Edit a draft; Add/Update commits it to the active replacement list.

    Signals request discovery work from the host instead of reading PDFs/fonts
    on the GUI thread. Text fields remain drafts until the user commits them.
    """

    scanRequested = QtCore.Signal(str)
    scanPagesRequested = QtCore.Signal()
    scanCurrentRequested = QtCore.Signal()
    catalogRequested = QtCore.Signal()
    fileRequested = QtCore.Signal(str)
    commitRequested = QtCore.Signal(bool)  # True adds, False updates selected.
    matchChanged = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.catalog: list[FontFace] = []
        self._selected_face: FontFace | None = None
        self._loading = False
        self.setupUi(self)

        self.names.setPlaceholderText("All fonts; or PDF names separated by ;")
        self.names.setToolTip("Exact original PDF font names, without the subset prefix. Separate names with semicolons. Blank matches all fonts.")
        self.scan_pages.setToolTip("Enter physical pages to find fonts and text colors; defaults to all. This only scopes discovery, not replacement.")
        self.scan_pages.clicked.connect(self.scanPagesRequested.emit)
        self.scan_all.setToolTip("Find fonts and text colors throughout the PDF.")
        self.scan_all.clicked.connect(lambda: self.scanRequested.emit("all"))
        self.scan_current.setToolTip("Find fonts and text colors on the currently displayed physical page.")
        self.scan_current.clicked.connect(self.scanCurrentRequested.emit)
        self.sources.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.sources.header().setStretchLastSection(False)
        for column, width in enumerate((160, 80, 75, 90)):
            self.sources.setColumnWidth(column, width)
        self.sources.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sources.setToolTip("Select one or more discovered PDF fonts to fill Source fonts. Clear the text field to match all fonts.")
        self.sources.itemSelectionChanged.connect(self._select_sources)
        self.sizes.setPlaceholderText("All sizes; e.g. 12,14-18")
        self.ignored = self.ignored_range.field
        self.ignored.setPlaceholderText("None; e.g. 1,2,-1; append |odd or |even")
        self.ignored.setToolTip("Physical pages to exclude. Append |odd or |even to filter page numbers.")
        self.source_colors.setPlaceholderText("All colors; e.g. #000; #F00")
        self.source_colors.setToolTip("Match original fill or stroke at 8-bit RGB precision. Separate colors with semicolons; RGB input is also supported.")
        self.found_colors.addItem("Discovered colors…", None)
        self.found_colors.activated.connect(self._select_color)

        self.installed_button.clicked.connect(self.catalogRequested.emit)
        self.file_button.clicked.connect(self._font_file)
        self.search.setPlaceholderText("Search names / localized aliases")
        self.search.textChanged.connect(self._search_fonts)
        self.target.setToolTip("Click a result to select its family and available styles. Search accepts canonical names and localized aliases.")
        self.target.itemSelectionChanged.connect(self._target_selected)
        self.selected_target.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.styles = {
            FontStyle.REGULAR: self.regular_face,
            FontStyle.BOLD: self.bold_face,
            FontStyle.ITALIC: self.italic_face,
            FontStyle.BOLD_ITALIC: self.bold_italic_face,
        }
        for combo in self.styles.values():
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(10)
            combo.addItem("Not assigned", None)
            combo.setToolTip("An exact matching style is required only when the selected PDF text uses it. Load additional files for missing styles; there is no silent fallback.")
            combo.currentIndexChanged.connect(self._show_selected_target)
        self.embedding.addItem("Used glyphs (subset)", _Embedding.SUBSET)
        self.embedding.addItem("Full font face", _Embedding.FULL)
        self.embedding.setCurrentIndex(0)
        self.embedding.setToolTip("Default: embed only glyphs used by replaced text. Full font embeds the entire selected face.")
        self.remove_original.setToolTip("Only remove original font programs no longer needed by text, ignored pages, annotations or retaining rules.")
        self.color.setPlaceholderText("Keep original; or #000 / rgb(0,0,0)")
        self.color.setToolTip("Recolor matched text only. Required in color-only mode; otherwise blank keeps the original color.")
        self.color_only.toggled.connect(lambda checked: self.font_controls.setEnabled(not checked))
        self.pages = self.pages_range.field
        self.pages.setText("all")
        self.pages.setPlaceholderText("all; or 1,2,5-10,-1; append |odd or |even")
        self.pages.setToolTip("Physical pages for this rule: all (default), 1,2,5-10, -1 for the last page, or none. Append |odd or |even to filter page numbers. Ignore pages is subtracted from this selection. Applies to preview and export.")
        self.add.clicked.connect(lambda: self.commitRequested.emit(True))
        self.update_button.clicked.connect(lambda: self.commitRequested.emit(False))
        self.source_colors_button.setToolTip("Append a source color")
        self.source_colors_button.clicked.connect(lambda: self._choose_color(self.source_colors, append=True))
        self.color_button.setToolTip("Choose the replacement text color")
        self.color_button.clicked.connect(lambda: self._choose_color(self.color, append=False))
        for field in (self.names, self.sizes, self.source_colors):
            field.editingFinished.connect(self.matchChanged.emit)

    def _choose_color(self, field: QtWidgets.QLineEdit, *, append: bool) -> None:
        initial = QtGui.QColor("black")
        if field.text().strip():
            try:
                initial = QtGui.QColor.fromRgbF(*Input.parse_color(field.text().split(";")[-1].strip()))
            except ValueError:
                pass  # The text remains editable and is validated on Add / Update.
        color = QtWidgets.QColorDialog.getColor(initial, self, "Text color")
        if color.isValid():
            value = color.name().upper()
            current = field.text().strip()
            field.setText(f"{current}; {value}" if append and current else value)
            if field is self.source_colors:
                self.matchChanged.emit()

    def _font_file(self) -> None:
        from ..common.preferences import choose_open_file
        path = choose_open_file(self, "Target font", "Fonts (*.ttf *.otf *.ttc *.otc)", kind="open-font")
        if path:
            self.fileRequested.emit(path)

    def _select_sources(self) -> None:
        if not self._loading:
            self.names.setText("; ".join(str(item.data(0, QtCore.Qt.ItemDataRole.UserRole)) for item in self.sources.selectedItems()))
            self.matchChanged.emit()

    def _select_color(self, index: int) -> None:
        color = self.found_colors.itemData(index)
        if color is not None:
            current = self.source_colors.text().strip()
            self.source_colors.setText(f"{current}; {color}" if current else color)
            self.matchChanged.emit()

    def set_sources(self, names: list[str], colors: list[int], details: dict[str, str] | None = None) -> None:
        """Show bold source names and metadata columns, retaining exact rule names."""
        self._loading = True
        self.sources.clear()
        for name in names:
            detail = (details or {}).get(name, "")
            summary = detail.split("\n", 1)[0]
            fields = summary.split("; ", 2) if summary else []
            font_type, embedding, sizes = (fields + ["", "", ""])[:3]
            item = QtWidgets.QTreeWidgetItem([name, font_type, embedding.removeprefix("embedded: "), sizes.removesuffix(" pt")])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, name)
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            for column in range(self.sources.columnCount()):
                item.setToolTip(column, f"{name}\n{detail}" if detail else name)
            self.sources.addTopLevelItem(item)
        self._loading = False
        self.found_colors.clear()
        self.found_colors.addItem("Discovered colors…", None)
        for value in colors:
            self.found_colors.addItem(f"#{value:06X}", f"#{value:06X}")

    def add_faces(self, faces: list[FontFace]) -> None:
        """Merge discovered faces, preserving existing explicit style selections."""
        previous = {style: combo.currentData() for style, combo in self.styles.items()}
        merged = {(face.path, face.index): face for face in self.catalog}
        merged.update({(face.path, face.index): face for face in faces})
        self.catalog = sorted(merged.values(), key=lambda face: (face.family.casefold(), face.name.casefold()))
        for style, combo in self.styles.items():
            combo.clear()
            combo.addItem("Not assigned", None)
            for face in self.catalog:
                if face.style == style:
                    combo.addItem(face.name, face)
                    combo.setItemData(combo.count() - 1, str(face.path), QtCore.Qt.ItemDataRole.ToolTipRole)
            found = combo.findData(previous[style])
            combo.setCurrentIndex(max(0, found))
        self._search_fonts()

    def _search_fonts(self) -> None:
        blocker = QtCore.QSignalBlocker(self.target)
        self.target.clear()
        matches = Font.search_faces(self.catalog, self.search.text())
        for face in matches:
            aliases = " / ".join(alias for alias in face.aliases if alias != face.name)
            style = face.style.name.replace("_", " ").title()
            item = QtWidgets.QListWidgetItem(f"{face.name} [{style}]\n{aliases or face.family}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, face)
            item.setToolTip(f"Name: {face.name}\nFamily: {face.family}\nAliases: {aliases}\nStyle: {style}\nFile: {face.path}\nCollection index: {face.index}")
            self.target.addItem(item)
            if self._selected_face == face:
                self.target.setCurrentItem(item)
        if not self.catalog:
            self.target_status.setText("No fonts loaded. Click Load installed fonts or Font file…")
        elif not matches:
            self.target_status.setText("No matching fonts. Try another name or load a font file.")
        else:
            self.target_status.setText(f"{len(matches)} matching faces — click one to select.")
        del blocker

    def _target_selected(self) -> None:
        item = self.target.currentItem()
        face = item.data(QtCore.Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(face, FontFace):
            self.select_face(face)

    def select_face(self, face: FontFace) -> None:
        """Choose a target family, assigning only its available exact style faces."""
        family = Font.family_faces(face, self.catalog)
        self._selected_face = face
        for style, combo in self.styles.items():
            combo.setCurrentIndex(max(0, combo.findData(family.get(style))))
        self._show_selected_target()
        blocker = QtCore.QSignalBlocker(self.target)
        for index in range(self.target.count()):
            item = self.target.item(index)
            if item.data(QtCore.Qt.ItemDataRole.UserRole) == face:
                self.target.setCurrentItem(item)
                break
        del blocker

    def _show_selected_target(self) -> None:
        faces = [combo.currentData() for combo in self.styles.values() if isinstance(combo.currentData(), FontFace)]
        families = ", ".join(dict.fromkeys(face.family for face in faces))
        self.selected_target.setText(f"Selected: {families}" if families else "Selected: none")

    def read_rule(self) -> ReplacementRule:
        """Read draft controls; the host validates them against the open PDF."""
        faces = {style: combo.currentData() for style, combo in self.styles.items()
                 if isinstance(combo.currentData(), FontFace)}
        return ReplacementRule(tuple(name.strip() for name in self.names.text().split(";") if name.strip()),
            self.sizes.text().strip(), self.ignored.text().strip(), self.source_colors.text().strip(),
            self.color.text().strip(), faces, _Embedding(self.embedding.currentData()), self.remove_original.isChecked(),
            self.pages.text().strip() or "all", self.color_only.isChecked())

    def read_match_rule(self) -> ReplacementRule:
        """Read current text filters only; exclude targets and export page scope."""
        return ReplacementRule(
            names=tuple(name.strip() for name in self.names.text().split(";") if name.strip()),
            sizes=self.sizes.text().strip(), source_colors=self.source_colors.text().strip(),
            color_only=True)

    def load_rule(self, rule: ReplacementRule) -> None:
        """Populate controls from a selected active rule without committing edits."""
        self.names.setText("; ".join(rule.names))
        self.sizes.setText(rule.sizes)
        self.ignored.setText(rule.ignored)
        self.pages.setText(rule.pages)
        self.color_only.setChecked(rule.color_only)
        self.source_colors.setText(rule.source_colors)
        self.color.setText(rule.color)
        self._selected_face = rule.faces.get(FontStyle.REGULAR) or next(iter(rule.faces.values()), None)
        self.add_faces(list(rule.faces.values()))
        for style, combo in self.styles.items():
            combo.setCurrentIndex(max(0, combo.findData(rule.faces.get(style))))
        self.embedding.setCurrentIndex(self.embedding.findData(rule.embedding))
        self.remove_original.setChecked(rule.remove_original)
        self._show_selected_target()
        self.matchChanged.emit()
