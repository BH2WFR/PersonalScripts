"""Modal numeric export settings, reusing the viewer's existing export controls.

Requirements: PySide6. Usage: created by ViewerWindow; show through a context menu.
The dialog owns persistent settings and stays open while background saves finish.
"""

from PySide6 import QtCore, QtWidgets


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
        layout.addWidget(controls)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
