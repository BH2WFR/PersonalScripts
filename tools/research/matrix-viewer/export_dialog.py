"""Modal numeric export settings, reusing the viewer's existing export controls.

Requirements: PySide6. Usage: created by ViewerWindow; show through a context menu.
The dialog owns persistent settings and stays open while background saves finish.
Complex sources first ask whether to export the displayed scalar channel or both
complex components. The same question supports adding independent slice matrices
in memory. The chosen region/slice is preserved in either case.
"""

from PySide6 import QtCore, QtWidgets

from .complex_input import ComplexDataChoice as ComplexExportChoice, choose_complex_data


def choose_complex_export(parent: QtWidgets.QWidget, source: str, channel: str,
                          *, prefer_complex: bool = True, slice_only: bool = False,
                          in_memory: bool = False) -> ComplexExportChoice | None:
    """Choose scalar or complex values for file export or a slice snapshot.

    Args:
        parent: Owning viewer window.
        source: Selected matrix's session name.
        channel: Displayed component, such as Real, Imaginary or Magnitude.
        prefer_complex: Default button; False highlights the current channel.
        slice_only: Describe the result as a selected 1D slice; default False.
        in_memory: Describe adding session matrices without saving; default False.

    Returns:
        Selected representation, or None when cancelled/closed.

    Side effects:
        Runs a modal question. Does not modify the source or export settings.
    """
    action = "added to the matrix list" if in_memory else "exported"
    result = ("The selected Slice becomes one 1D complex array, containing both real and imaginary parts. "
              if slice_only else "Both choices support 1D signals, 2D matrices and selected 1D slices. ")
    destination = "\nIndependent session matrices are added unchecked; no file is saved." if in_memory else ""
    return choose_complex_data(parent, source, channel,
                               title="Add complex Slice matrix" if in_memory else "Export complex matrix",
                               action=action, prefer_complex=prefer_complex,
                               details=f"{result}Complex data supports X/Y cropping; value bounds are ignored.{destination}")


class MatrixExportDialog(QtWidgets.QDialog):
    """Keep export settings outside the plotting workspace.

    Args:
        controls: Existing export group, reparented into this dialog.
        parent: Viewer owning the data, worker jobs and save callbacks.

    Side effects:
        Reparents controls. Closing hides the dialog without cancelling exports.
    """

    def __init__(self, controls: QtWidgets.QGroupBox, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export matrix")
        self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        self.resize(570, 460)
        layout = QtWidgets.QVBoxLayout(self)
        self.source_info = QtWidgets.QLabel()
        self.source_info.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.source_info.setWordWrap(True)
        self.source_info.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.source_info)
        layout.addWidget(controls)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
