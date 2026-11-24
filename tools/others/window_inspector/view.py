"""PySide6 counterpart of the Caps+W inspector."""

import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from typing import Any

import psutil
from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeyEvent, QKeySequence, QShortcut, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QSplitter, QToolBar, QTreeWidget,
    QAbstractItemView, QTabWidget, QToolTip, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from utils.qt_widgets import NoWheelComboBox, NoWheelSpinBox, configure_qt_application, show_cursor_tooltip

from .model import (
    Backend, CONTROLS_HINT, INITIAL_HINT, LOADED_HINT, MIN_OPACITY_PERCENT, ProcessInfo, Properties, PropertyGroup, Rows, Window,
    end_process, find_window, prepare_restart, process_info,
)
from .picker import Finder, Outline


IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
PREVIEW_MS = 3000
PRIORITIES = {"Low": 0x40, "BelowNormal": 0x4000, "Normal": 0x20,
              "AboveNormal": 0x8000, "High": 0x80, "Realtime": 0x100}
CONTROL_COLUMNS = ["#", "HWND", "ClassNN", "Text", "Class", "Position and size"] if IS_WINDOWS else ["#", "Role", "Subrole", "Title"]


class _Table(QTreeWidget):
    def __init__(self, headers: list[str]) -> None:
        super().__init__()
        self.setHeaderLabels(headers)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)


class _ValueTable(_Table):
    """Fill the available width while allowing a long value to scroll horizontally."""

    def __init__(self, headers: list[str]) -> None:
        super().__init__(headers)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

    def sizeHintForColumn(self, column: int) -> int:
        content_width = super().sizeHintForColumn(column)
        if column == 1:
            return max(content_width, self.viewport().width() - self.columnWidth(0))
        return content_width


def _vertical_separator() -> QFrame:
    separator = QFrame()
    separator.setFrameShape(QFrame.Shape.VLine)
    separator.setFrameShadow(QFrame.Shadow.Sunken)
    return separator


class Inspector(QWidget):
    def __init__(self, backend: Backend, *, top: bool = False) -> None:
        super().__init__()
        self.backend = backend
        self.target: Window | None = None
        self.process: psutil.Process | None = None
        self.loaded = False
        self.window_controls: list[QWidget | QAction] = []
        self.target_controls: list[QWidget | QAction] = []
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.job: Future[Any] | None = None
        self.job_ready: Callable[[Any], None] = lambda result: None
        self.poll = QTimer(self, interval=50)
        self.poll.timeout.connect(self._finish_job)
        self.return_focus = QTimer(self, singleShot=True)
        self.return_focus.setTimerType(Qt.TimerType.PreciseTimer)
        self.return_focus.timeout.connect(self._finish_preview)
        self.preview_tick = QTimer(self, singleShot=True)
        self.preview_tick.setTimerType(Qt.TimerType.PreciseTimer)
        self.preview_tick.timeout.connect(self._update_countdown)
        self.setWindowTitle("Window Inspector")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, top)
        initial_size = QSize(1080, 720)
        if screen := self.screen():
            initial_size = initial_size.boundedTo(screen.availableGeometry().size() * 0.95)
        self.resize(initial_size)
        self.setMinimumHeight(400)
        self.outline = Outline(self, backend)
        self._build()
        self._set_list([], False)
        self._clear()
        self.list_button.setFocus()

    def _row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self.body.addLayout(row)
        return row

    def _button(self, row: QHBoxLayout, label: str, tip: str, callback: Callable[[], None],
                *, needs_target: bool = True) -> QPushButton:
        button = QPushButton(label)
        button.setToolTip(tip)
        button.clicked.connect(lambda: self.guard(callback))
        row.addWidget(button)
        if needs_target:
            self.target_controls.append(button)
        return button

    def _action(self, bar: QToolBar, label: str, tip: str, callback: Callable[[], None]) -> QAction:
        action = QAction(label, bar)
        action.setToolTip(tip)
        action.triggered.connect(lambda: self.guard(callback))
        bar.addAction(action)
        self.target_controls.append(action)
        return action

    def _window_toggle(self, bar: QToolBar, label: str, tip: str) -> None:
        action = self._action(bar, label, tip, partial(self._window_action, label))
        action.setCheckable(True)
        self.toggles[label] = action

    def _build(self) -> None:
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(8, 4, 8, 8)
        self.body.setSpacing(6)
        header = self._row()
        self.finder = Finder(self.backend, self.outline)
        self.finder.picked.connect(lambda w: self.guard(partial(self.load, w)))
        self.finder.started.connect(self._cancel_preview)
        header.addWidget(self.finder)
        self.selector = NoWheelComboBox()
        self.editor = QLineEdit()
        self.selector.setLineEdit(self.editor)
        self.selector.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # Qt installs a completer for the editor. PySide6 6.8 omits its null reset from the stub.
        self.selector.setCompleter(None)  # pyright: ignore[reportArgumentType]
        self.selector.setMaxVisibleItems(12)
        self.selector.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        header.addWidget(self.selector, 1)
        self.editor.setToolTip("Search by window title, process name, window ID, or PID (for example, PID:1234).")
        self.selector.activated.connect(self._selected)
        self.editor.textEdited.connect(self._edited)
        self.editor.returnPressed.connect(lambda: self.guard(self.search))
        self.list_button = self._button(header, "Refresh List", "Load the current list of windows.", self.refresh_list, needs_target=False)
        self._button(header, "Find", "Inspect the first window matching your search.", self.search, needs_target=False)

        options = self._row()
        finder_hint = QLabel("⬆️ Drag the finder onto a window")
        finder_hint.setIndent(max(0, (self.finder.width() - finder_hint.fontMetrics().horizontalAdvance("↑")) // 2))
        options.addWidget(finder_hint)
        options.addStretch()
        self.hidden_windows = QCheckBox("Include hidden windows")
        self.hidden_windows.setToolTip("Include hidden windows when listing or searching.")
        self.hidden_windows.clicked.connect(lambda: self.guard(self.refresh_list) if self.loaded else None)
        options.addWidget(self.hidden_windows)
        self.pin = QCheckBox("Keep inspector on top")
        self.pin.setToolTip("Keep Window Inspector above other windows.")
        self.pin.setChecked(bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        self.pin.toggled.connect(self._pin)
        options.addWidget(self.pin)
        options.addWidget(_vertical_separator())
        self._button(options, "Refresh Info", "Read the selected window and process details again.", self.refresh)
        self.window_controls.append(self._button(options, "Read Controls", "List the controls exposed by the selected window.", self.read_controls))

        actions_group = QGroupBox("Actions")
        self.body.addWidget(actions_group)
        bars = QGridLayout(actions_group)
        bars.setContentsMargins(6, 0, 6, 0)
        bars.setColumnStretch(1, 1)
        bars.setVerticalSpacing(0)
        caption_font = self.font()
        caption_font.setBold(True)
        process_bar, window_bar = QToolBar("Process"), QToolBar("Window")
        for row, bar in enumerate((process_bar, window_bar)):
            bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            bar.setStyleSheet("QToolBar { border: 0; padding: 0; }")
            bar.setAccessibleName(bar.windowTitle())
            caption = QLabel(f"{bar.windowTitle()}:")
            caption.setFont(caption_font)
            bars.addWidget(caption, row, 0)
        process_row = QHBoxLayout()
        process_row.setSpacing(6)
        bars.addLayout(process_row, 0, 1)
        process_row.addWidget(process_bar)
        window_row = QHBoxLayout()
        window_row.setSpacing(6)
        bars.addLayout(window_row, 1, 1)
        window_row.addWidget(window_bar)
        self._action(process_bar, "Properties", "Show properties for the selected path.", partial(self._file, True))
        self._action(process_bar, "Show File", "Reveal the selected path in its containing folder.", partial(self._file, False))
        process_bar.addSeparator()
        self._action(process_bar, "Restart", "End the process and relaunch it with its original arguments.", partial(self._end, True))
        self._action(process_bar, "Terminate", "Force the process to quit, including all of its windows.", partial(self._end, False))

        self.priority: NoWheelComboBox | NoWheelSpinBox
        if IS_WINDOWS:
            self.priority = NoWheelComboBox()
            self.priority.setToolTip("Choose the scheduling priority for the selected process.")
            for label, value in PRIORITIES.items():
                self.priority.addItem(label, value)
            self.priority.activated.connect(lambda: self.guard(self._set_priority))
        else:
            self.priority = NoWheelSpinBox()
            self.priority.setRange(-20, 19)
            self.priority.setKeyboardTracking(False)
            self.priority.valueChanged.connect(lambda: self.guard(self._set_priority))
            self.priority.setToolTip("Select a nice value from −20 to 19. Lower values give the process higher priority.")
        process_row.addWidget(_vertical_separator())
        priority_label = QLabel("Priority:")
        priority_label.setFont(caption_font)
        priority_label.setBuddy(self.priority)
        process_row.addWidget(priority_label)
        process_row.addWidget(self.priority)
        self.target_controls.append(self.priority)
        process_row.addStretch()

        for label, tip in (("Activate", "Bring the window to the front for three seconds."),
                           ("Center", "Bring the window forward, center it, and highlight it for three seconds."),
                           ("Reset Size", "Bring the window forward, restore its default size, center it, and highlight it for three seconds."),
                           ("Highlight", "Outline the window on screen for three seconds.")):
            self._action(window_bar, label, tip, partial(self._window_action, label))
        self.toggles: dict[str, QAction] = {}
        window_bar.addSeparator()
        self._action(window_bar, "Minimize", "Minimize the selected window.", partial(self._window_action, "Minimize"))
        self._action(window_bar, "Close Window", "Ask the selected window to close.", partial(self._window_action, "Close Window"))
        if IS_WINDOWS:
            window_bar.addSeparator()
            self._window_toggle(window_bar, "Always on Top", "Keep the selected window above other windows.")
            self._action(window_bar, "Opacity", "Adjust the opacity of the selected window.", self._edit_opacity)
            self._window_toggle(window_bar, "Click-through", "Let mouse clicks pass through the selected window.")
            window_bar.addSeparator()
            self._action(window_bar, "Enable Controls", "Enable disabled controls in the selected window.",
                         self._enable_controls)
            self._action(window_bar, "Show Controls", "Show hidden controls in the selected window.",
                         self._show_controls)
            self._action(window_bar, "Enable Menus", "Enable disabled menu items in the selected window.",
                         self._enable_menus)
        self.window_controls.extend(a for a in window_bar.actions() if not a.isSeparator())
        window_row.addStretch()

        details_group = QGroupBox("Window details")
        self.body.addWidget(details_group, 1)
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(-1, -1, -1, 2)
        fields = QGridLayout()
        fields.setHorizontalSpacing(6)
        fields.setVerticalSpacing(2)
        details_layout.addLayout(fields)
        self.fields: dict[str, QLineEdit] = {}
        for i, label in enumerate(("Title", "Process", "Path", "Command line")):
            fields.addWidget(QLabel(label), i, 0)
            field = QLineEdit(readOnly=True)
            field.setStyleSheet("max-height: 1.2em;")
            self.fields[label] = field
            if IS_MACOS and label == "Path":
                self.paths = NoWheelComboBox()
                self.paths.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
                self.paths.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                self.paths.setToolTip("Choose the executable, application bundle or window document.")
                self.paths.currentIndexChanged.connect(lambda: self.fields["Path"].setText(self.paths.currentData() or ""))
                path_row = QHBoxLayout()
                path_row.setSpacing(fields.horizontalSpacing())
                path_row.addWidget(self.paths)
                path_row.addWidget(field, 1)
                fields.addLayout(path_row, i, 1)
            else:
                fields.addWidget(field, i, 1)
        fields.setColumnStretch(1, 1)
        self.info, self.controls = _ValueTable(["Property", "Value"]), _Table(CONTROL_COLUMNS)
        self.info.setRootIsDecorated(True)
        self.info.setIndentation(round(self.info.indentation() * 0.8))
        self.info.setColumnWidth(0, self.info.fontMetrics().horizontalAdvance("Layered click-through") + 2 * self.info.indentation() + 12)
        widths = (45, 100, 100, 190, 100, 170) if IS_WINDOWS else (45, 140, 150, 200)
        for i, width in enumerate(widths):
            self.controls.setColumnWidth(i, width)
        self.info.itemDoubleClicked.connect(self._copy_property)
        self.controls.itemDoubleClicked.connect(self._copy_control)
        split = QSplitter()
        split.addWidget(self.info)
        self.arguments = _ValueTable(["#", "Argument"])
        self.arguments.header().setResizeContentsPrecision(-1)
        self.arguments.setColumnWidth(0, 45)
        self.arguments.itemDoubleClicked.connect(lambda item, col: self._copy(item.text(col)))
        self.tabs = QTabWidget()
        self.tabs.addTab(self.controls, "Controls")
        self.tabs.addTab(self.arguments, "Arguments")
        split.addWidget(self.tabs)
        copy_tables = (self.info, self.controls, self.arguments) if IS_MACOS else (self.arguments,)
        for table in copy_tables:
            table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            shortcut = QShortcut(QKeySequence.StandardKey.Copy, table)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(partial(self._copy_rows, table))
        if IS_MACOS:
            QShortcut(QKeySequence.StandardKey.Close, self).activated.connect(self.close)
        split.setSizes([330, 498])
        details_layout.addWidget(split, 1)
        self.status = QLabel()
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer = self._row()
        footer.addWidget(self.status, 1)
        if IS_MACOS:
            footer.addWidget(QLabel("Double-click a cell to copy it."))
            self._button(footer, "Copy All", "Copy the displayed details, controls and arguments.", self._copy_all)
        else:
            footer.addWidget(QLabel("Double-click a row to copy its contents."))
        self.finder.message.connect(self.status.setText)

    def guard(self, action: Callable[[], None]) -> None:
        """Native objects may disappear between any two GUI events."""
        try:
            action()
        except (OSError, RuntimeError, ValueError, psutil.Error, subprocess.SubprocessError) as exc:
            self._feedback(str(exc))

    def _pin(self, checked: bool) -> None:
        # QWidget.setWindowFlag hides a visible widget. Change the live Cocoa
        # window's level through QWindow so a preview never unmaps the inspector.
        if IS_MACOS and (handle := self.windowHandle()) is not None:
            handle.setFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
            return
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    def _restore_focus(self) -> None:
        self._pin(self.pin.isChecked())
        if IS_MACOS:
            from .macos import activate_inspector
            activate_inspector()
        self.raise_()
        self.activateWindow()

    def _finish_preview(self) -> None:
        self.preview_tick.stop()
        self.return_focus.stop()
        QToolTip.hideText()
        self.outline.hide()
        self._restore_focus()
        self.status.setText("Returned to Window Inspector.")

    def _update_countdown(self) -> None:
        remaining = self.return_focus.remainingTime()
        if remaining <= 0:
            return
        seconds = (remaining + 999) // 1000
        unit = "second" if seconds == 1 else "seconds"
        message = f"Focus returns to Window Inspector in {seconds} {unit}."
        self.status.setText(message)
        show_cursor_tooltip(message, duration_ms=remaining)
        if seconds > 1:
            self.preview_tick.start(remaining - (seconds - 1) * 1000)

    def _cancel_preview(self) -> None:
        if self.return_focus.isActive():
            self._finish_preview()
        else:
            self.outline.hide()

    def _preview(self, target: Window, *, refresh_geometry: bool) -> None:
        if not self.return_focus.isActive() or self.target != target:
            return
        try:
            if IS_MACOS:
                from .macos import check_active
                check_active(target)
            self.outline.show(target)
            if refresh_geometry:
                self.refresh()
            self._update_countdown()
        except (RuntimeError, OSError, psutil.Error):
            self._cancel_preview()
            raise

    def _set_list(self, entries: list[Window], loaded: bool) -> None:
        self.loaded = loaded
        hint = LOADED_HINT if loaded else INITIAL_HINT
        with QSignalBlocker(self.selector):
            self.selector.clear()
            self.selector.addItem(hint)
            model = self.selector.model()
            assert isinstance(model, QStandardItemModel)
            model.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
            for entry in entries:
                self.selector.addItem(entry.label, entry)
            self.selector.setCurrentIndex(-1)
            self.editor.setPlaceholderText(hint)

    def refresh_list(self) -> None:
        self._list_for(self._list_ready)

    def _list_for(self, completed: Callable[[list[Window]], None]) -> None:
        read = partial(self.backend.windows, self.hidden_windows.isChecked())
        if IS_WINDOWS:
            completed(read())
        else:
            self.status.setText("Reading window list…")
            self._start_job(read, completed)

    def _list_ready(self, entries: list[Window]) -> None:
        self._set_list(entries, True)
        if self.target in entries:
            self.refresh()
        else:
            self._clear()
        self.status.setText(f"Window list refreshed ({len(entries)} windows).")

    def _selected(self, index: int) -> None:
        entry = self.selector.itemData(index)
        if isinstance(entry, Window):
            self.guard(partial(self.load, entry))

    def _edited(self, text: str) -> None:
        self._clear(keep_text=True)

    def search(self) -> None:
        query = self.editor.text().strip()
        if self.target is not None and query == self.target.label:
            self.refresh()
            return
        if IS_MACOS and not query:
            self._feedback("Enter a window title, application name, window ID or PID.")
            return

        def select(entries: list[Window]) -> None:
            if IS_MACOS and not self.loaded:
                self._set_list(entries, True)
                self.editor.setText(query)
            target = find_window(entries, query)
            if target is None:
                self._clear(keep_text=True)
                raise ValueError("No matching window found.")
            self.load(target)
        if IS_MACOS and self.loaded:
            select([self.selector.itemData(i) for i in range(1, self.selector.count())])
        else:
            self._list_for(select)

    def _clear(self, keep_text: bool = False) -> None:
        self.target = self.process = None
        self._cancel_preview()
        if not keep_text:
            self.selector.setCurrentIndex(-1)
            self.editor.clear()
        for field in self.fields.values():
            field.clear()
        self.info.clear()
        self.controls.clear()
        self.arguments.clear()
        if IS_MACOS:
            self.paths.clear()
        if isinstance(self.priority, QComboBox):
            self.priority.setCurrentIndex(-1)
        else:
            self.priority.clear()
        for toggle in self.toggles.values():
            toggle.setChecked(False)
        for widget in self.target_controls:
            widget.setEnabled(False)
        self.status.setText("Select a window to inspect.")

    def load(self, target: Window) -> None:
        previous = self.process if self.target == target else None
        collapsed: set[str] = set()
        if self.target == target:
            for index in range(self.info.topLevelItemCount()):
                group = self.info.topLevelItem(index)
                if group is not None and not group.isExpanded():
                    collapsed.add(group.text(0))
        if self.target != target:
            self._clear()
        try:
            data = self.backend.snapshot(target)
            try:
                process = previous or psutil.Process(target.pid)
                if not process.is_running():
                    raise RuntimeError("The process has exited. Select another window.")
                details = process_info(process)
            except psutil.AccessDenied:
                process = None
                details = ProcessInfo("", "", "", None, [])
            self.backend.checked(data.window)
        except (OSError, RuntimeError, psutil.Error):
            self._clear()
            raise
        self.process = process
        target = data.window
        self.target = target
        index = next((i for i in range(1, self.selector.count()) if self.selector.itemData(i) == target), -1)
        if index < 0:
            if not self.loaded and self.selector.count() > 1:
                self.selector.removeItem(1)
            self.selector.addItem(target.label, target)
            index = self.selector.count() - 1
        self.selector.setItemText(index, target.label)
        self.selector.setItemData(index, target)
        self.selector.setCurrentIndex(index)
        for field, text in zip(self.fields.values(), (target.title, details.name or target.kind, details.path, details.command)):
            field.setText(text)
            field.setCursorPosition(0)
        if IS_MACOS:
            previous_path = self.paths.currentText()
            self.paths.clear()
            paths = dict(data.paths)
            if details.path:
                paths = {"Executable": details.path, **paths}
            for label, path in paths.items():
                self.paths.addItem(label, path)
            self.paths.setCurrentIndex(max(0, self.paths.findText(previous_path)) if paths else -1)
        self.arguments.clear()
        self.arguments.addTopLevelItems([QTreeWidgetItem([str(i), arg]) for i, arg in enumerate(details.arguments)])
        rows = data.rows + details.rows
        if details.priority is not None:
            name = next((k for k, v in PRIORITIES.items() if IS_WINDOWS and v == details.priority), str(details.priority))
            rows.append((PropertyGroup.PROCESS, "Priority", name))
            if isinstance(self.priority, QComboBox):
                self.priority.setCurrentIndex(self.priority.findData(int(details.priority)))
            else:
                with QSignalBlocker(self.priority):
                    self.priority.setValue(details.priority)
        else:
            if isinstance(self.priority, QComboBox):
                self.priority.setCurrentIndex(-1)
            else:
                self.priority.clear()
        self.info.clear()
        self._show_properties(rows, collapsed)
        self.controls.clear()
        hint = QTreeWidgetItem([CONTROLS_HINT])
        self.controls.addTopLevelItem(hint)
        hint.setFirstColumnSpanned(True)
        hint.setFlags(Qt.ItemFlag.NoItemFlags)
        for widget in self.target_controls:
            widget.setEnabled(True)
        if target.id == 0:
            for control in self.window_controls:
                control.setEnabled(False)
        self.priority.setEnabled(details.priority is not None and self.process is not None)
        if IS_WINDOWS:
            self.toggles["Always on Top"].setChecked(data.topmost)
            self.toggles["Click-through"].setChecked(data.through)
        description = target.label if IS_MACOS else f"window 0x{target.id:08X} (PID {target.pid})"
        self.status.setText(f"Inspecting {description}.")

    def _checked(self) -> Window:
        if self.target is None:
            raise RuntimeError("Select a window first.")
        try:
            if self.process is not None and not self.process.is_running():
                raise RuntimeError("The process has exited. Select another window.")
            return self.backend.checked(self.target)
        except (OSError, RuntimeError, psutil.Error):
            self._clear()
            raise

    def refresh(self) -> None:
        self.load(self._checked())

    def _show_properties(self, rows: Properties, collapsed: set[str]) -> None:
        groups = {category: QTreeWidgetItem([category.value]) for category in PropertyGroup}
        for category, name, value in rows:
            QTreeWidgetItem(groups[category], [name, value])
        heading_font = self.info.font()
        heading_font.setBold(True)
        for category, group in groups.items():
            if group.childCount():
                self.info.addTopLevelItem(group)
                group.setFirstColumnSpanned(True)
                group.setFont(0, heading_font)
                group.setExpanded(category.value not in collapsed)

    def _copy_property(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is not None:
            self._copy(item.text(column if IS_MACOS else 1))

    def _copy_rows(self, table: QTreeWidget) -> None:
        rows = [item for item in table.selectedItems() if item.flags() & Qt.ItemFlag.ItemIsSelectable]
        if rows:
            self._copy("\n".join("\t".join(item.text(i) for i in range(table.columnCount())) for item in rows))

    def _copy_all(self) -> None:
        sections = ["\n".join(f"{label}\t{field.text()}" for label, field in self.fields.items())]
        for label, table in (("Properties", self.info), ("Controls", self.controls), ("Arguments", self.arguments)):
            rows = []
            for i in range(table.topLevelItemCount()):
                item = table.topLevelItem(i)
                if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
                    continue
                rows.append("\t".join(item.text(j) for j in range(table.columnCount())).rstrip("\t"))
                for k in range(item.childCount()):
                    child = item.child(k)
                    if child is not None:
                        rows.append(f"{child.text(0)}\t{child.text(1)}")
            sections.append("\n".join([label, *rows]))
        self._copy("\n\n".join(sections))

    def _feedback(self, message: str) -> None:
        self.status.setText(message)
        if IS_MACOS:
            show_cursor_tooltip(message, parent=self, duration_ms=1500)

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self._feedback("Copied to clipboard.")

    def _copy_control(self, item: QTreeWidgetItem, column: int) -> None:
        if item.flags() & Qt.ItemFlag.ItemIsEnabled:
            text = item.text(column) if IS_MACOS else "\t".join(item.text(i) for i in range(self.controls.columnCount()))
            self._copy(text)

    def _start_job(self, work: Callable[[], Any], completed: Callable[[Any], None]) -> None:
        if self.job is not None:
            return
        self.job_ready = completed
        self.job = self.executor.submit(work)
        self.setEnabled(False)
        self.poll.start()

    def _finish_job(self) -> None:
        if self.job is not None and self.job.done():
            self.poll.stop()
            job, self.job = self.job, None
            self.setEnabled(True)
            self.guard(lambda: self.job_ready(job.result()))

    def read_controls(self) -> None:
        target = self._checked()
        def render(rows: Rows) -> None:
            if self._checked() != target:
                return
            self.controls.clear()
            self.controls.addTopLevelItems([QTreeWidgetItem(row) for row in rows])
            self.tabs.setCurrentWidget(self.controls)
            limit = " (showing up to 500 direct children)" if IS_MACOS and len(rows) == 500 else ""
            self._feedback(f"Controls found: {len(rows)}{limit}.")
        self.status.setText("Reading controls…")
        self._start_job(partial(self.backend.controls, target), render)

    def _enable_controls(self) -> None:
        target = self._checked()
        total, enabled = self.backend.enable_controls(target)
        self.status.setText(f"Enabled {enabled} of {total} controls.")

    def _show_controls(self) -> None:
        target = self._checked()
        total, shown = self.backend.show_controls(target)
        self.status.setText(f"Showed {shown} of {total} controls.")

    def _enable_menus(self) -> None:
        target = self._checked()
        total, enabled = self.backend.enable_menu(target)
        if total:
            self.status.setText(f"Enabled {enabled} of {total} menu items.")
        else:
            self.status.setText("The selected window has no standard menu bar.")

    def _file(self, properties: bool) -> None:
        self._checked()
        path = self.fields["Path"].text()
        if not path or not os.path.exists(path):
            raise RuntimeError("The selected path is unavailable.")
        if IS_WINDOWS:
            self.pin.setChecked(False)
        self.backend.file_action(path, properties)
        if IS_MACOS:
            self.pin.setChecked(False)

    def _set_priority(self) -> None:
        self._checked()
        value = self.priority.currentData() if isinstance(self.priority, QComboBox) else self.priority.value()
        if self.process is None or value is None:
            raise RuntimeError("The process or priority is unavailable.")
        try:
            self.process.nice(value)
        finally:
            self.refresh()

    def _edit_opacity(self) -> None:
        target = self._checked()
        current = self.backend.snapshot(target).opacity
        dialog = QDialog(self)
        dialog.setWindowTitle("Window opacity")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(dialog)
        spin = NoWheelSpinBox()
        spin.setAccessibleName("Window opacity")
        spin.setToolTip(f"Choose an opacity from {MIN_OPACITY_PERCENT}% to 100%.")
        spin.setRange(MIN_OPACITY_PERCENT, 100)
        spin.setSuffix("%")
        spin.setValue(current)
        layout.addWidget(spin)
        buttons = QDialogButtonBox.StandardButton
        box = QDialogButtonBox(buttons.Ok | buttons.Reset)
        layout.addWidget(box)
        ok, reset = box.button(buttons.Ok), box.button(buttons.Reset)
        ok.setDefault(True)
        ok.setToolTip("Apply this opacity to the selected window.")
        reset.setToolTip("Restore the selected window to 100% opacity.")
        box.accepted.connect(dialog.accept)

        def restore() -> None:
            spin.setValue(100)
            dialog.accept()

        def apply() -> None:
            if self.target == target:
                self.guard(partial(self._window_action, "Opacity", spin.value()))

        reset.clicked.connect(restore)
        dialog.accepted.connect(apply)
        dialog.open()
        spin.setFocus()
        spin.selectAll()

    def _confirm(self, action: str, message: str, details: str = "") -> bool:
        buttons = QMessageBox.StandardButton
        box = QMessageBox(QMessageBox.Icon.Warning, action, message, buttons.Yes | buttons.No, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(buttons.No)
        if details:
            box.setDetailedText(details)
        return box.exec() == buttons.Yes

    def _end(self, restart: bool) -> None:
        target, process = self._checked(), self.process
        if process is None:
            raise RuntimeError("Cannot access the selected process.")
        verb = "Restart" if restart else "Terminate"
        plan = prepare_restart(process) if restart and IS_MACOS else None
        path = process.exe() if IS_MACOS else self.fields["Path"].text()
        details = ""
        if plan:
            arguments = "\n".join(f"[{index}] {arg!r}" for index, arg in enumerate(plan.arguments))
            details = f"Working directory: {plan.cwd}\nCommand: {shlex.join(plan.arguments)}\n\nArguments:\n{arguments}"
        if not self._confirm(f"{verb} process", f"{verb} {self.fields['Process'].text()} (PID {target.pid})?\n"
                             f"Unsaved work in its windows may be lost.\n{path}", details):
            return
        if self._checked() != target or self.process is not process:
            return
        def completed(_: None) -> None:
            self._clear()
            self.status.setText("Process restarted." if restart else "Process terminated.")
        self.status.setText("Restarting process…" if restart else "Terminating process…")
        self._start_job(partial(end_process, process, restart, plan), completed)

    def _window_action(self, action: str, value: int = 0) -> None:
        target = self._checked()
        if action == "Highlight":
            self.outline.show(target, PREVIEW_MS)
            return
        if action == "Close Window":
            if self._confirm(action, f"Close this window?\n{target.title}") and self._checked() == target:
                self.backend.act(target, action)
                if IS_MACOS:
                    # An application may ask the user to save and keep the window open.
                    QTimer.singleShot(300, self, lambda: self.guard(self.refresh) if self.target == target else None)
                else:
                    self._clear()
                self.status.setText("Close request sent.")
            return
        if action in ("Activate", "Center", "Reset Size"):
            self._pin(False)
            try:
                self.backend.act(target, "Activate")
                change_geometry = action != "Activate"
                if change_geometry:
                    self.backend.act(target, action)
                self.preview_tick.stop()
                self.return_focus.start(PREVIEW_MS)
                # Allow the target's event loop to apply its new position before drawing.
                QTimer.singleShot(300 if IS_MACOS else 100, self,
                                  lambda: self.guard(partial(self._preview, target, refresh_geometry=change_geometry)))
            except Exception:
                self._finish_preview()
                raise
            return
        if action in self.toggles:
            value = int(self.toggles[action].isChecked())
        try:
            self.backend.act(target, action, value)
        except (RuntimeError, OSError):
            self.refresh()
            raise
        if action == "Opacity":
            self.refresh()
            return
        if action == "Click-through" and not value:
            self._restore_focus()
        if IS_MACOS:
            self._feedback(f"{action} request sent.")
        # Other processes apply show/position changes on their own event loop.
        QTimer.singleShot(150, self, lambda: self.guard(self.refresh) if self.target == target and self.job is None else None)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self.finder.dragging:
                self.finder.cancel()
                self.status.setText("Window selection canceled.")
            else:
                self.close()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        if IS_MACOS and self.job is not None:
            event.ignore()
            self._feedback("Please wait for the current operation to finish.")
            return
        self.finder.cancel()
        if self.return_focus.isActive():
            QToolTip.hideText()
        self.preview_tick.stop()
        self.return_focus.stop()
        self.poll.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)


def run(backend: Backend, foreground: Window | None, *, top: bool = False) -> int:
    """Open the inspector using the window captured before Qt takes focus."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    configure_qt_application(app)
    inspector = Inspector(backend, top=top)
    if foreground is not None:
        inspector.guard(partial(inspector.load, foreground))
    inspector.show()
    if IS_MACOS:
        QTimer.singleShot(100, inspector, inspector._restore_focus)
    return app.exec()
