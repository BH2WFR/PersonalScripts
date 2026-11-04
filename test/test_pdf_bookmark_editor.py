"""Verify batch outline edits, internal drops and bounded PDF-tool tooltips.

Run with conda base: python -m unittest discover -s test -p test_pdf_bookmark_editor.py.
Uses offscreen Qt and synthetic rows; no PDF or network access is needed.
"""

from unittest.mock import patch
import unittest
from test_pdf_bookmarks_gui import QtCore, QtGui, QtTest, QtWidgets
from personal_pdf_tools.common.bookmark_editor import BookmarkEditor, OutlineRow, IDENTITY_ROLE
from personal_pdf_tools.common.tooltips import TooltipFilter


class BookmarkEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def setUp(self) -> None:
        self.editor = BookmarkEditor(editable=True, current_page=lambda: 9)
        self.editor.resize(500, 500)
        self.editor.show()
        self.addCleanup(self.editor.close)
        self.events: list[list[OutlineRow]] = []
        self.editor.changed.connect(self.events.append)

    def load(self, entries: list[tuple[str, int]]) -> None:
        self.editor.load([OutlineRow(name, name, index + 1, level) for index, (name, level) in enumerate(entries)])
        self.application.processEvents()

    def items(self) -> dict[str, QtWidgets.QTreeWidgetItem]:
        result: dict[str, QtWidgets.QTreeWidgetItem] = {}
        iterator = QtWidgets.QTreeWidgetItemIterator(self.editor.tree)
        while iterator.value() is not None:
            item = iterator.value()
            result[str(item.data(0, IDENTITY_ROLE))] = item
            iterator += 1
        return result

    def select(self, *names: str) -> None:
        self.editor.tree.clearSelection()
        items = self.items()
        for name in names:
            items[name].setSelected(True)
        if names:
            self.editor.tree.setCurrentItem(items[names[0]], 0, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)

    def result(self) -> list[tuple[str, int]]:
        return [(row.id, row.level) for row in self.editor.rows()]

    def test_indent_modes_keep_reading_order_and_descendant_targets(self) -> None:
        rows = [("A", 1), ("a", 2), ("B", 1), ("b", 2), ("bb", 3), ("C", 1)]
        for children, levels in ((True, [1, 2, 2, 3, 4, 1]), (False, [1, 2, 2, 2, 3, 1])):
            with self.subTest(children=children):
                self.load(rows)
                self.select("B")
                self.editor._indent(children)
                self.assertEqual([row.id for row in self.editor.rows()], [name for name, _ in rows])
                self.assertEqual([row.level for row in self.editor.rows()], levels)
                self.assertEqual([row.page for row in self.editor.rows()], list(range(1, 7)))
                self.assertEqual(self.editor._selected_ids(), {"B"})

    def test_multiselect_indent_is_atomic_and_ancestor_moves_once(self) -> None:
        rows = [("A", 1), ("B", 1), ("b", 2), ("C", 1), ("c", 2)]
        self.load(rows)
        self.select("B", "b", "C")
        self.editor._indent()
        self.assertEqual(self.result(), [("A", 1), ("B", 2), ("b", 3), ("C", 2), ("c", 3)])
        self.assertEqual(len(self.events), 1)
        self.load(rows)
        self.select("A", "C")
        with patch.object(QtWidgets.QMessageBox, "warning") as warning:
            self.editor._indent(False)
        warning.assert_called_once()
        self.assertEqual(self.result(), rows)
        self.assertEqual(len(self.events), 1)

    def test_indent_toolbar_and_context_actions_have_distinct_modes(self) -> None:
        rows = [("A", 1), ("B", 1), ("b", 2)]
        for label, levels in (("Indent (with descendants)", [1, 2, 3]),
                              ("Indent (selected items only)", [1, 2, 2])):
            self.load(rows)
            self.select("B")
            menu = self.editor._make_context_menu(self.items()["B"])
            next(action for action in menu.actions() if action.text() == label).trigger()
            self.assertEqual([row.level for row in self.editor.rows()], levels)
        self.load(rows)
        self.select("B")
        toolbar = self.editor.findChild(QtWidgets.QToolBar)
        next(action for action in toolbar.actions() if action.text() == "→").trigger()
        self.assertEqual([row.level for row in self.editor.rows()], [1, 2, 3])

    def test_shift_ctrl_and_right_click_keep_multiselection_without_navigation(self) -> None:
        self.load([(name, 1) for name in "ABCDE"])
        tree = self.editor.tree
        items = self.items()
        requested: list[int] = []
        self.editor.pageRequested.connect(requested.append)
        for name, modifier in (("B", QtCore.Qt.KeyboardModifier.NoModifier),
                               ("D", QtCore.Qt.KeyboardModifier.ShiftModifier),
                               ("A", QtCore.Qt.KeyboardModifier.ControlModifier)):
            QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.MouseButton.LeftButton, modifier,
                                   tree.visualItemRect(items[name]).center())
        self.assertEqual(self.editor._selected_ids(), set("ABCD"))
        menu = self.editor._make_context_menu(items["C"])
        with patch.object(self.editor, "_make_context_menu", return_value=menu):
            QtCore.QTimer.singleShot(20, menu.close)
            QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.MouseButton.RightButton,
                                   pos=tree.visualItemRect(items["C"]).center())
            QtCore.QTimer.singleShot(20, menu.close)
            self.editor._context_menu(tree.visualItemRect(items["C"]).center())
        QtTest.QTest.qWait(QtWidgets.QApplication.doubleClickInterval() + 20)
        self.assertFalse(requested)
        self.assertEqual(self.editor._selected_ids(), set("ABCD"))
        self.editor.load(self.editor.rows())
        self.assertEqual(self.editor._selected_ids(), set("ABCD"))

    def test_nonconsecutive_drag_moves_subtrees_once_and_keeps_unselected_order(self) -> None:
        self.load([("A", 1), ("a", 2), ("B", 1), ("C", 1), ("c", 2), ("D", 1)])
        self.select("A", "a", "C")
        self.assertTrue(self.editor._drop(self.items()["D"], QtWidgets.QAbstractItemView.DropIndicatorPosition.BelowItem))
        self.assertEqual(self.result(), [("B", 1), ("D", 1), ("A", 1), ("a", 2), ("C", 1), ("c", 2)])
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.editor._selected_ids(), {"A", "a", "C"})
        before = self.result()
        self.assertFalse(self.editor._drop(self.items()["a"], QtWidgets.QAbstractItemView.DropIndicatorPosition.OnItem))
        self.assertEqual(self.result(), before)

    def test_drag_across_parents_rebases_roots_and_drop_handler_commits_once(self) -> None:
        self.load([("A", 1), ("a", 2), ("B", 1), ("b", 2), ("C", 1)])
        self.select("a", "B")
        target = self.items()["C"]
        tree = self.editor.tree
        class Drop(QtGui.QDropEvent):
            def source(self) -> QtCore.QObject:
                return tree
        event = Drop(QtCore.QPointF(tree.visualItemRect(target).center()), QtCore.Qt.DropAction.MoveAction,
                     QtCore.QMimeData(), QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        with patch.object(tree, "dropIndicatorPosition", return_value=QtWidgets.QAbstractItemView.DropIndicatorPosition.OnItem):
            tree.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(self.result(), [("A", 1), ("C", 1), ("a", 2), ("B", 2), ("b", 3)])
        self.assertEqual(len(self.events), 1)

    def test_batch_delete_target_and_both_outdent_modes(self) -> None:
        rows = [("A", 1), ("B", 2), ("b", 3), ("C", 2), ("D", 2), ("E", 1)]
        for keep, expected in ((True, [("A", 1), ("B", 1), ("b", 2), ("C", 2), ("D", 1), ("E", 1)]),
                               (False, [("A", 1), ("C", 2), ("B", 1), ("b", 2), ("D", 1), ("E", 1)])):
            self.load(rows)
            self.select("B", "D")
            self.editor._outdent(keep)
            self.assertEqual(self.result(), expected)
        self.load(rows)
        self.select("B", "b", "D")
        self.editor._set_selected_targets()
        self.assertEqual([row.page for row in self.editor.rows()], [1, 9, 9, 4, 9, 6])
        self.editor._delete()
        self.assertEqual(self.result(), [("A", 1), ("C", 2), ("E", 1)])

    def test_batch_move_retains_selection_and_drag_does_not_use_default_cleanup(self) -> None:
        self.load([("A", 1), ("B", 1), ("b", 2), ("C", 1), ("D", 1)])
        self.select("B", "b", "D")
        self.editor._move(-1)
        self.assertEqual(self.result(), [("B", 1), ("b", 2), ("A", 1), ("D", 1), ("C", 1)])
        self.assertEqual(self.editor._selected_ids(), {"B", "b", "D"})
        with patch("personal_pdf_tools.common.bookmark_editor.QtGui.QDrag") as drag:
            self.editor.tree.startDrag(QtCore.Qt.DropAction.MoveAction)
        drag.return_value.setMimeData.assert_called_once()
        drag.return_value.exec.assert_called_once_with(QtCore.Qt.DropAction.MoveAction)
        self.assertEqual(len(self.events), 1)

    def test_tooltip_width_long_tokens_tree_cells_and_dynamic_widgets(self) -> None:
        tooltips = TooltipFilter(self.editor)
        label = QtWidgets.QLabel(self.editor)
        label.setToolTip("A long hint " * 30 + "https://example.com/" + "x" * 400)
        event = QtGui.QHelpEvent(QtCore.QEvent.Type.ToolTip, QtCore.QPoint(2, 2), QtCore.QPoint(100, 100))
        self.assertTrue(tooltips.eventFilter(label, event))
        self.assertLessEqual(tooltips.popup.width(), 250)
        self.assertEqual(tooltips.popup.document.toPlainText(), label.toolTip())
        self.assertGreater(tooltips.popup.height(), 50)
        self.assertLessEqual(tooltips.popup.document.idealWidth(), 234)
        self.load([("A", 1)])
        tree = self.editor.tree
        self.items()["A"].setToolTip(0, "Cell hint " * 20)
        point = tree.visualItemRect(self.items()["A"]).center()
        event = QtGui.QHelpEvent(QtCore.QEvent.Type.ToolTip, QtCore.QPoint(20, point.y()), QtCore.QPoint(100, 100))
        self.assertTrue(tooltips.eventFilter(tree.viewport(), event))
        self.assertTrue(tooltips.popup.document.toPlainText().startswith("Cell hint"))
        self.assertLessEqual(tooltips.popup.width(), 250)
        tooltips.popup.hide()


if __name__ == "__main__":
    unittest.main()
