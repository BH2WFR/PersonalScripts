"""System event viewer: ui implementation."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sys
import threading
import xml.etree.ElementTree as ET
from .models import (
    DEFAULT_SIZE,
    DEFAULT_UNCHECKED_EVENT_KINDS,
    DIAGNOSTIC_EVENT_KINDS,
    EventKind,
    EVENT_FILTER_GROUPS,
    EVENT_FILTER_LABELS,
    GUI_STYLE,
    LOGIN_EVENT_KINDS,
    MODERN_EVENT_KINDS,
    PLATFORM_EVENT_KINDS,
    PowerEvent,
    QueryResult,
    SourceState,
    TIMESTAMP_FORMAT,
    TimeRange,
    UTC,
)
from . import history


def _launch_gui() -> int:
    """Load the Qt GUI after CLI help/dependency checks and run its event loop."""
    from PySide6 import QtCore, QtGui, QtWidgets
    from utils.qt_widgets import NoWheelComboBox, install_no_wheel_controls

    class QueryWorker(QtCore.QThread):
        """Run log collection off the GUI thread and deliver results via Qt signals."""

        completed = QtCore.Signal(object)
        failed = QtCore.Signal(str)
        progress = QtCore.Signal(str)

        def __init__(self, start: dt.datetime, end: dt.datetime, parent: QtCore.QObject) -> None:
            super().__init__(parent)
            self.start_time, self.end_time = start, end
            self.cancelled = threading.Event()

        def run(self) -> None:
            """Emit a complete result or failure; exceptions never escape the worker thread."""
            try:
                result = history.query_events(self.start_time, self.end_time, self.cancelled, self.progress.emit)
                self.completed.emit(result)
            except Exception as exc:
                self.failed.emit(str(exc))

    class EventsModel(QtCore.QAbstractTableModel):
        """Read-only event model; formatting does not allocate a widget for each cell."""

        HEADERS = ("Time (local)", "Event", "Details", "Source", "User / session")

        def __init__(self, parent: QtCore.QObject) -> None:
            super().__init__(parent)
            self.events: list[PowerEvent] = []

        def rowCount(self, parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex = QtCore.QModelIndex()) -> int:
            """Return the number of top-level events; this table has no child rows."""
            return 0 if parent.isValid() else len(self.events)

        def columnCount(self, parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex = QtCore.QModelIndex()) -> int:
            """Return the fixed number of event columns."""
            return len(self.HEADERS)

        def data(self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole) -> object:
            """Return rendered cells, raw tooltips or stable sort values for an event."""
            if not index.isValid() or not 0 <= index.row() < len(self.events):
                return None
            event = self.events[index.row()]
            if role == QtCore.Qt.ItemDataRole.UserRole:
                return event.timestamp.timestamp() if index.column() == 0 else self.data(index)
            if role == QtCore.Qt.ItemDataRole.ToolTipRole:
                return event.summary
            if role != QtCore.Qt.ItemDataRole.DisplayRole:
                return None
            return (event.timestamp.astimezone().strftime(TIMESTAMP_FORMAT), event.kind.value,
                    event.summary, event.source, event.session)[index.column()]

        def headerData(self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.ItemDataRole.DisplayRole) -> object:
            """Return English horizontal labels or row numbers."""
            if role != QtCore.Qt.ItemDataRole.DisplayRole:
                return None
            return self.HEADERS[section] if orientation == QtCore.Qt.Orientation.Horizontal else section + 1

        def replace(self, events: list[PowerEvent]) -> None:
            """Replace the current query atomically and notify attached views."""
            self.beginResetModel()
            self.events = events
            self.endResetModel()

    class EventFilter(QtCore.QSortFilterProxyModel):
        """Filter cached events by checkbox selection without querying the OS again."""

        def __init__(self, model: EventsModel, parent: QtCore.QObject) -> None:
            super().__init__(parent)
            self.events_model = model
            self.allowed: set[EventKind] = set(EventKind)
            self.setSourceModel(model)
            self.setSortRole(QtCore.Qt.ItemDataRole.UserRole)

        def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
            """Include a row when its event type is enabled."""
            return self.events_model.events[source_row].kind in self.allowed

    class PowerEventsWindow(QtWidgets.QMainWindow):
        """System history browser with cancellable queries, compact filters and evidence detail."""

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("System Event Viewer")
            self.resize(*DEFAULT_SIZE)
            self.settings = QtCore.QSettings(
                QtCore.QSettings.defaultFormat(), QtCore.QSettings.Scope.UserScope,
                "PersonalScripts", "PowerEvents",
            )
            self.worker: QueryWorker | None = None
            self.result: QueryResult | None = None
            self.status_message = ""
            self.closing = False
            self.available_kinds = PLATFORM_EVENT_KINDS.get(sys.platform, frozenset())
            self.checkboxes: dict[EventKind, QtWidgets.QCheckBox] = {}
            self._build_ui()
            self._restore_settings()
            self._apply_range()
            QtCore.QTimer.singleShot(0, self._query)

        def _build_ui(self) -> None:
            """Build native Qt controls and connect query/filter/export actions."""
            central = QtWidgets.QWidget(self)
            layout = QtWidgets.QVBoxLayout(central)
            layout.setContentsMargins(6, 6, 6, 4)
            layout.setSpacing(4)
            self.setCentralWidget(central)

            # ── time range and query controls ───────────
            bar = QtWidgets.QHBoxLayout()
            bar.setSpacing(4)
            self.range_box = NoWheelComboBox()
            self.range_box.addItems([value.value for value in TimeRange])
            self.range_box.currentIndexChanged.connect(self._apply_range)
            self.start_edit = QtWidgets.QDateTimeEdit()
            self.end_edit = QtWidgets.QDateTimeEdit()
            for editor in (self.start_edit, self.end_edit):
                editor.setCalendarPopup(True)
                editor.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
                editor.setMinimumWidth(180)
            self.query_button = QtWidgets.QPushButton("Query / Refresh")
            self.query_button.clicked.connect(self._query)
            self.query_button.setToolTip("Query / Refresh (F5)")
            self.refresh_shortcut = QtGui.QShortcut(QtGui.QKeySequence("F5"), self)
            self.refresh_shortcut.setAutoRepeat(False)
            self.refresh_shortcut.activated.connect(self.query_button.click)
            self.cancel_button = QtWidgets.QPushButton("Cancel")
            self.cancel_button.setEnabled(False)
            self.cancel_button.clicked.connect(self._cancel)
            for text, widget in (("Range", self.range_box), ("From", self.start_edit), ("Until", self.end_edit)):
                label = QtWidgets.QLabel(text)
                label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
                bar.addWidget(label)
                bar.addWidget(widget)
            bar.addSpacing(8)
            divider = QtWidgets.QFrame()
            divider.setFrameShape(QtWidgets.QFrame.Shape.VLine)
            divider.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
            bar.addWidget(divider)
            bar.addSpacing(8)
            bar.addWidget(self.query_button)
            bar.addWidget(self.cancel_button)
            layout.addLayout(bar)
            self.start_edit.setToolTip("Local time; inclusive start.")
            self.end_edit.setToolTip("Local time; exclusive end.")

            # ── event visibility controls ───────────────
            filter_bar = QtWidgets.QHBoxLayout()
            filter_bar.setSpacing(3)
            filter_title = QtWidgets.QLabel("Show events")
            filter_title.setToolTip("Filters apply instantly to loaded events, without querying again.")
            filter_bar.addWidget(filter_title)
            self.select_all_button = QtWidgets.QToolButton()
            self.select_none_button = QtWidgets.QToolButton()
            self.reset_types_button = QtWidgets.QToolButton()
            for button, label in ((self.select_all_button, "All"), (self.select_none_button, "None"),
                                  (self.reset_types_button, "Reset")):
                button.setText(label)
                filter_bar.addWidget(button)
            self.select_all_button.clicked.connect(lambda: self._select_types(True))
            self.select_none_button.clicked.connect(lambda: self._select_types(False))
            self.reset_types_button.clicked.connect(self._reset_types)
            self.reset_types_button.setToolTip("Restore default event filters; retain dates and layout.")
            filter_bar.addStretch(1)
            layout.addLayout(filter_bar)
            self.filter_panel = QtWidgets.QWidget()
            self.filter_panel.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
            self.filter_grid = QtWidgets.QGridLayout(self.filter_panel)
            self.filter_grid.setContentsMargins(2, 0, 2, 0)
            self.filter_grid.setHorizontalSpacing(6)
            self.filter_grid.setVerticalSpacing(1)
            self.filter_columns = 0
            for kind, members in EVENT_FILTER_GROUPS.items():
                checkbox = QtWidgets.QCheckBox(EVENT_FILTER_LABELS.get(kind, kind.value))
                available = members & self.available_kinds
                supported = bool(available)
                checkbox.setEnabled(supported)
                checkbox.setChecked(bool(available - DEFAULT_UNCHECKED_EVENT_KINDS))
                if not supported:
                    checkbox.setToolTip("This event type is not collected on the current platform.")
                elif len(members) > 1:
                    checkbox.setToolTip("Includes: " + ", ".join(value.value for value in EventKind if value in available))
                checkbox.toggled.connect(self._filter)
                self.checkboxes[kind] = checkbox
            layout.addWidget(self.filter_panel)
            self._layout_filters()

            # ── event table and evidence tabs ───────────
            self.model = EventsModel(self)
            self.proxy = EventFilter(self.model, self)
            self.table = QtWidgets.QTableView()
            self.table.setModel(self.proxy)
            self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.table.setAlternatingRowColors(True)
            self.table.setWordWrap(False)
            self.table.setSortingEnabled(True)
            self.table.sortByColumn(0, QtCore.Qt.SortOrder.DescendingOrder)
            rows = self.table.verticalHeader()
            rows.hide()
            row_height = self.table.fontMetrics().height() + 4
            rows.setMinimumSectionSize(row_height)
            rows.setDefaultSectionSize(row_height)
            rows.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Fixed)
            for index, width in enumerate((155, 380, 220, 160), start=1):
                self.table.setColumnWidth(index, width)
            self.table.selectionModel().selectionChanged.connect(self._show_detail)
            self.detail = QtWidgets.QPlainTextEdit()
            self.detail.setReadOnly(True)
            self.detail.setPlaceholderText("Select an event to inspect its original evidence.")
            xml_page = QtWidgets.QWidget()
            xml_layout = QtWidgets.QVBoxLayout(xml_page)
            xml_layout.setContentsMargins(0, 0, 0, 0)
            self.xml_notice = QtWidgets.QLabel("Select an event to inspect its XML.")
            self.xml_notice.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            self.xml_notice.setWordWrap(True)
            self.xml_tree = QtWidgets.QTreeWidget()
            self.xml_tree.setHeaderLabels(["Node", "Value", "Attributes"])
            self.xml_tree.setAlternatingRowColors(True)
            self.xml_tree.setUniformRowHeights(True)
            self.xml_tree.setColumnWidth(0, 240)
            self.xml_tree.setColumnWidth(1, 280)
            self.xml_tree.hide()
            xml_layout.addWidget(self.xml_notice)
            xml_layout.addWidget(self.xml_tree, 1)
            self.sources = QtWidgets.QPlainTextEdit()
            self.sources.setReadOnly(True)
            tabs = QtWidgets.QTabWidget()
            tabs.addTab(self.detail, "Event details")
            tabs.addTab(xml_page, "XML")
            tabs.addTab(self.sources, "Sources and coverage")
            splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
            splitter.addWidget(self.table)
            splitter.addWidget(tabs)
            splitter.setSizes([470, 170])
            layout.addWidget(splitter, 1)
            self.summary = QtWidgets.QLabel("Ready")
            self.summary.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            self.summary.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
            self.export_button = QtWidgets.QPushButton("Export CSV...")
            self.export_button.setEnabled(False)
            self.export_button.clicked.connect(lambda: self._export(".csv"))
            self.export_json_button = QtWidgets.QPushButton("Export JSON...")
            self.export_json_button.setEnabled(False)
            self.export_json_button.clicked.connect(lambda: self._export(".json"))
            footer = QtWidgets.QHBoxLayout()
            footer.addWidget(self.summary, 1)
            footer.addWidget(self.export_button)
            footer.addWidget(self.export_json_button)
            layout.addLayout(footer)

        def _layout_filters(self) -> None:
            """Fit as many complete checkbox columns as the current window can display."""
            cell_width = max(checkbox.sizeHint().width() for checkbox in self.checkboxes.values()) + 6
            columns = max(1, (self.width() - 16) // cell_width)
            if columns == self.filter_columns:
                return
            for column in range(self.filter_columns):
                self.filter_grid.setColumnStretch(column, 0)
            for checkbox in self.checkboxes.values():
                self.filter_grid.removeWidget(checkbox)
            for index, checkbox in enumerate(self.checkboxes.values()):
                self.filter_grid.addWidget(checkbox, index // columns, index % columns)
            for column in range(columns):
                self.filter_grid.setColumnStretch(column, 1)
            self.filter_columns = columns

        def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
            """Reflow the compact filter area when the window width changes."""
            super().resizeEvent(event)
            if hasattr(self, "filter_grid"):
                self._layout_filters()

        def _restore_settings(self) -> None:
            """Restore presentation preferences; relative date ranges are not stored as fixed dates."""
            geometry = self.settings.value("geometry")
            if isinstance(geometry, QtCore.QByteArray):
                self.restoreGeometry(geometry)
            header = self.settings.value("columns")
            if isinstance(header, QtCore.QByteArray):
                self.table.horizontalHeader().restoreState(header)
            # Fit timestamps even when an older saved layout used a wider column.
            self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
            value = str(self.settings.value("range", TimeRange.DAY.value))
            index = self.range_box.findText(value)
            self.range_box.setCurrentIndex(max(0, index))
            selected = self.settings.value("types")
            # Use category defaults for new filters; explicit saved choices survive.
            known = self.settings.value("knownTypes", [kind.value for kind in EventKind
                                        if kind not in MODERN_EVENT_KINDS | LOGIN_EVENT_KINDS | DIAGNOSTIC_EVENT_KINDS | {EventKind.DEVICE_EJECT_BLOCKED}])
            enabled = set(self.available_kinds - DEFAULT_UNCHECKED_EVENT_KINDS)
            if isinstance(selected, list) and isinstance(known, list):
                for kind in self.available_kinds:
                    if kind.value in known:
                        if kind.value in selected:
                            enabled.add(kind)
                        else:
                            enabled.discard(kind)
            # Keep a merged group enabled if either previously separate type was on.
            for kind, checkbox in self.checkboxes.items():
                checkbox.setChecked(bool(EVENT_FILTER_GROUPS[kind] & enabled))
            if value == TimeRange.CUSTOM.value:
                for key, editor in (("start", self.start_edit), ("end", self.end_edit)):
                    saved = str(self.settings.value(key, ""))
                    parsed = QtCore.QDateTime.fromString(saved, QtCore.Qt.DateFormat.ISODate)
                    if parsed.isValid():
                        editor.setDateTime(parsed)
            self._filter()

        def _apply_range(self) -> None:
            """Update date controls for relative ranges; retain custom selections."""
            selected = TimeRange(self.range_box.currentText())
            custom = selected == TimeRange.CUSTOM
            self.start_edit.setEnabled(custom)
            self.end_edit.setEnabled(custom)
            now = QtCore.QDateTime.currentDateTime()
            if custom:
                if self.start_edit.date().year() < 2001:
                    self.start_edit.setDateTime(now.addDays(-1))
                    self.end_edit.setDateTime(now)
                return
            end = now
            if selected == TimeRange.TODAY:
                start = QtCore.QDateTime(now.date(), QtCore.QTime(0, 0))
            elif selected == TimeRange.YESTERDAY:
                end = QtCore.QDateTime(now.date(), QtCore.QTime(0, 0))
                start = end.addDays(-1)
            elif selected == TimeRange.DAY:
                start = now.addSecs(-24 * 60 * 60)
            else:
                start = now.addDays(-7 if selected == TimeRange.WEEK else -30)
            self.start_edit.setDateTime(start)
            self.end_edit.setDateTime(end)

        def _query(self) -> None:
            """Start a new worker; reject reversed ranges and overlapping queries."""
            if self.worker is not None:
                return
            self._apply_range()
            start = dt.datetime.fromtimestamp(self.start_edit.dateTime().toSecsSinceEpoch(), UTC)
            end = dt.datetime.fromtimestamp(self.end_edit.dateTime().toSecsSinceEpoch(), UTC)
            if start >= end:
                QtWidgets.QMessageBox.warning(self, "Invalid range", "Choose an end time after the start time.")
                return
            self.worker = QueryWorker(start, end, self)
            self.worker.completed.connect(self._loaded)
            self.worker.failed.connect(self._failed)
            self.worker.progress.connect(self._set_status)
            self.worker.finished.connect(self._finished)
            self.query_button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.export_button.setEnabled(False)
            self.export_json_button.setEnabled(False)
            self._set_status("Querying...")
            self.worker.start()

        def _cancel(self) -> None:
            """Request cancellation without blocking the GUI thread."""
            if self.worker is not None:
                self.worker.cancelled.set()
                self.cancel_button.setEnabled(False)
                self._set_status("Cancelling...")

        def _loaded(self, result: object) -> None:
            """Install a completed result and display all source errors alongside successful sources."""
            if not isinstance(result, QueryResult):
                return
            self.result = result
            self._clear_details()
            self.model.replace(result.events)
            self.sources.setPlainText("\n\n".join(
                f"{status.source}: {status.state.value} ({status.count} matching events)\n{status.message}"
                for status in result.statuses
            ))
            self.status_message = ""
            self._filter()

        def _failed(self, message: str) -> None:
            """Keep previous results on cancellation or unexpected errors and surface the cause."""
            self._filter()
            self._set_status("Cancelled" if message == "Query cancelled." else "Query failed")
            if message != "Query cancelled.":
                QtWidgets.QMessageBox.warning(self, "Query failed", message)

        def _finished(self) -> None:
            """Release the finished worker; close only after cancellation has reaped its child."""
            worker, self.worker = self.worker, None
            if worker is not None:
                worker.deleteLater()
            self.query_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.export_button.setEnabled(self.proxy.rowCount() > 0)
            self.export_json_button.setEnabled(self.proxy.rowCount() > 0)
            if self.closing:
                self.close()

        def _select_types(self, checked: bool) -> None:
            """Toggle all event types with one final proxy refresh."""
            for checkbox in self.checkboxes.values():
                blocker = QtCore.QSignalBlocker(checkbox)
                checkbox.setChecked(checked and checkbox.isEnabled())
                del blocker
            self._filter()

        def _reset_types(self) -> None:
            """Restore category defaults without changing query bounds or loaded records."""
            for kind, checkbox in self.checkboxes.items():
                blocker = QtCore.QSignalBlocker(checkbox)
                checkbox.setChecked(bool((EVENT_FILTER_GROUPS[kind] & self.available_kinds) - DEFAULT_UNCHECKED_EVENT_KINDS))
                del blocker
            self._filter()

        def _selected_types(self) -> set[EventKind]:
            """Expand grouped controls to supported event types for filtering and persistence."""
            return {member for kind, checkbox in self.checkboxes.items()
                    if checkbox.isEnabled() and checkbox.isChecked()
                    for member in EVENT_FILTER_GROUPS[kind] if member in self.available_kinds}

        def _filter(self) -> None:
            """Apply checkbox states to cached events and update the result count."""
            if not hasattr(self, "proxy"):
                return
            self.proxy.allowed = self._selected_types()
            self.proxy.invalidate()
            self._clear_details()
            self.export_button.setEnabled(self.worker is None and self.proxy.rowCount() > 0)
            self.export_json_button.setEnabled(self.worker is None and self.proxy.rowCount() > 0)
            self._update_summary()

        def _set_status(self, message: str) -> None:
            """Show query/export feedback in the same footer as the result count."""
            self.status_message = message
            self._update_summary()

        def _update_summary(self) -> None:
            """Keep the footer on one line; retain exact query times in its tooltip."""
            if self.result is None:
                self.summary.setText(self.status_message or "Ready")
                self.summary.setToolTip(self.summary.text())
                return
            shown, total = self.proxy.rowCount(), len(self.model.events)
            count = f"{total:,} events" if shown == total else f"{shown:,} / {total:,} events"
            start, end = self.result.start.astimezone(), self.result.end.astimezone()
            parts = [count, self.status_message or f"{start:%Y-%m-%d %H:%M} – {end:%Y-%m-%d %H:%M}"]
            errors = sum(status.state == SourceState.ERROR for status in self.result.statuses)
            if errors:
                parts.append(f"{errors} source{'s' if errors != 1 else ''} unavailable")
            self.summary.setText("  |  ".join(parts))
            self.summary.setToolTip(
                f"{shown:,} shown / {total:,} loaded\n"
                f"Local range: {start.strftime(TIMESTAMP_FORMAT)} to {end.strftime(TIMESTAMP_FORMAT)} (end exclusive)\n"
                f"{self.status_message or 'Query complete'}. See Sources and coverage for log availability."
            )

        def _clear_details(self) -> None:
            """Clear both evidence views when the selection or query changes."""
            self.detail.clear()
            self.xml_tree.clear()
            self.xml_tree.hide()
            self.xml_notice.setText("Select an event to inspect its XML.")
            self.xml_notice.show()

        def _show_xml(self, event: PowerEvent) -> None:
            """Display XML structure as plain text, preserving child order and namespaces in tooltips."""
            self.xml_tree.clear()
            self.xml_tree.hide()
            self.xml_notice.show()
            if not event.xml:
                self.xml_notice.setText("This event has no XML record. See Event details for its original evidence.")
                return
            try:
                root = ET.fromstring(event.xml)
            except ET.ParseError as exc:
                self.xml_notice.setText(f"Cannot display this XML: {exc}. See Event details for the original record.")
                return
            pending = [(root, self.xml_tree.invisibleRootItem())]
            while pending:
                element, parent = pending.pop()
                name = element.tag.rsplit("}", 1)[-1]
                if name == "Data" and element.get("Name"):
                    name = f"Data [{element.get('Name')}]"
                value = element.text or ""
                attributes = "; ".join(f"{key.rsplit('}', 1)[-1]}={json.dumps(value, ensure_ascii=False)}"
                                       for key, value in element.attrib.items())
                item = QtWidgets.QTreeWidgetItem([name, value.strip(), attributes])
                item.setToolTip(0, element.tag)
                item.setToolTip(1, value)
                item.setToolTip(2, "\n".join(f"{key}={value}" for key, value in element.attrib.items()))
                parent.addChild(item)
                pending.extend((child, item) for child in reversed(element))
            self.xml_tree.expandToDepth(1)
            self.xml_notice.hide()
            self.xml_tree.show()

        def _show_detail(self) -> None:
            """Show the selected row's metadata and original evidence without interpreting it as HTML."""
            index = self.table.currentIndex()
            if not index.isValid():
                self._clear_details()
                return
            event = self.model.events[self.proxy.mapToSource(index).row()]
            self.detail.setPlainText(
                f"Time: {event.timestamp.astimezone().isoformat()}\nEvent: {event.kind.value}\n"
                f"Source: {event.source}\nSession: {event.session or 'Not recorded'}\n"
                f"Boot ID: {event.boot_id or 'Not recorded'}\nRecord ID: {event.record_id or 'Not recorded'}\n"
                f"\n{event.summary}\n\nOriginal evidence:\n{event.raw}"
            )
            self._show_xml(event)

        def _export(self, suffix: str) -> None:
            """Save visible rows in display order using the requested .csv or .json format."""
            if self.result is None:
                return
            format_name = suffix[1:].upper()
            filename, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, f"Export visible events as {format_name}", f"system-events{suffix}",
                f"{format_name} (*{suffix})",
            )
            if not filename:
                return
            path = Path(filename)
            if not path.suffix:
                path = path.with_suffix(suffix)
                if path.exists() and QtWidgets.QMessageBox.question(self, "Replace file?", f"Replace {path.name}?") != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
            if path.suffix.lower() != suffix:
                QtWidgets.QMessageBox.warning(self, "Invalid extension", f"Choose a {suffix} export file.")
                return
            events = [self.model.events[self.proxy.mapToSource(self.proxy.index(row, 0)).row()]
                      for row in range(self.proxy.rowCount())]
            try:
                history.export_events(path, events, self.result)
            except (OSError, ValueError) as exc:
                QtWidgets.QMessageBox.warning(self, "Export failed", str(exc))
                return
            self._set_status(f"Exported {len(events):,} events ({format_name})")
            self.summary.setToolTip(f"{self.summary.toolTip()}\nSaved to: {path}")

        def closeEvent(self, event: QtGui.QCloseEvent) -> None:
            """Cancel active collection before closing, then persist presentation preferences."""
            if self.worker is not None:
                self.closing = True
                self._cancel()
                event.ignore()
                return
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("columns", self.table.horizontalHeader().saveState())
            self.settings.setValue("range", self.range_box.currentText())
            selected = self._selected_types()
            self.settings.setValue("types", [kind.value for kind in EventKind if kind in selected])
            self.settings.setValue("knownTypes", [kind.value for kind in EventKind if kind in self.available_kinds])
            for key, editor in (("start", self.start_edit), ("end", self.end_edit)):
                self.settings.setValue(key, editor.dateTime().toString(QtCore.Qt.DateFormat.ISODate))
            super().closeEvent(event)

    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QtWidgets.QApplication([sys.argv[0]])
    if not isinstance(application, QtWidgets.QApplication):
        raise RuntimeError("A non-GUI Qt application is already running.")
    application.setStyle(GUI_STYLE)
    install_no_wheel_controls(application)
    window = PowerEventsWindow()
    window.show()
    # Keep a reference when embedded in another Qt session (also used by GUI tests).
    application.setProperty("powerEventsWindow", window)
    return application.exec() if owns_application else 0

