"""Page-range editors with synchronized All/Odd/Even controls.

Requires PySide6 and utils.Input range syntax. Controls edit the existing text
expression; callers retain ownership of validation, defaults and committing it.
"""

from PySide6 import QtCore, QtWidgets
from utils import *


class RangeInput(QtWidgets.QWidget):
    """Wrap a page-range text field with mutually exclusive parity buttons.

    Args:
        field: Existing line edit, reparented into this control. Its text,
            signals and public API remain the source of truth for callers.
        parent: Optional owning widget.

    All removes only the parity suffix, retaining the entered range. Odd/Even
    replace the suffix; an empty range becomes all before adding the filter.
    Typed suffixes and programmatic setText calls update the buttons without
    rewriting text or emitting additional text changes. Invalid expressions
    remain available for the caller's normal parser validation.
    """

    def __init__(self, field: QtWidgets.QLineEdit, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = field
        self.setFocusProxy(field)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(field)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Parity:"))
        self.group = QtWidgets.QButtonGroup(self)
        self.buttons: dict[RangeParity | None, QtWidgets.QRadioButton] = {}
        for parity, title in ((None, "All"), (RangeParity.ODD, "Odd"), (RangeParity.EVEN, "Even")):
            button = QtWidgets.QRadioButton(title)
            button.setToolTip("Keep all page numbers in the entered range." if parity is None
                              else f"Keep {parity.value} physical page numbers in the entered range.")
            self.group.addButton(button)
            self.buttons[parity] = button
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.buttons[None].clicked.connect(lambda: self._choose(None))
        self.buttons[RangeParity.ODD].clicked.connect(lambda: self._choose(RangeParity.ODD))
        self.buttons[RangeParity.EVEN].clicked.connect(lambda: self._choose(RangeParity.EVEN))
        field.textChanged.connect(self._sync)
        self._sync(field.text())

    def _sync(self, text: str) -> None:
        """Reflect a recognized typed suffix without changing the expression."""
        parity: RangeParity | None = None
        if text.count("|") == 1:
            try:
                parity = RangeParity(text.rsplit("|", 1)[1].strip().casefold())
            except ValueError:
                pass
        self.buttons[parity].setChecked(True)

    def _choose(self, parity: RangeParity | None) -> None:
        """Keep the base expression and replace/remove its parity suffix."""
        expression = self.field.text().split("|", 1)[0].strip()
        self.field.setText(expression if parity is None else f"{expression or 'all'}|{parity.value}")


class PageRangeDialog(QtWidgets.QDialog):
    """Modal page-range input with the same parity controls as embedded fields.

    Args:
        parent: Owning tool window.
        title: Dialog window title.
        label: Description of the requested page selection.
        text: Initial expression, default empty.
    """

    def __init__(
        self, parent: QtWidgets.QWidget | None, title: str, label: str, *, text: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        layout = QtWidgets.QVBoxLayout(self)
        description = QtWidgets.QLabel(label)
        description.setWordWrap(True)
        layout.addWidget(description)
        self.field = QtWidgets.QLineEdit(text)
        self.field.setPlaceholderText("all; or 1,2,5-10,-1; append |odd or |even")
        self.range_input = RangeInput(self.field)
        layout.addWidget(self.range_input)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.field.selectAll()
        self.field.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)

    @staticmethod
    def get_text(
        parent: QtWidgets.QWidget | None, title: str, label: str, *, text: str = "",
    ) -> tuple[str, bool]:
        """Show a page selector and return its expression and acceptance state.

        Args:
            parent: Owning tool window.
            title: Dialog title.
            label: Selection prompt.
            text: Initial expression (default empty).

        Returns:
            Edited text and True for OK, or False for Cancel/window close.
            The caller validates accepted expressions before applying them.
        """
        dialog = PageRangeDialog(parent, title, label, text=text)
        try:
            accepted = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
            return dialog.field.text(), accepted
        finally:
            dialog.deleteLater()
