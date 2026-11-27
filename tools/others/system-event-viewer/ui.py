"""System event viewer: ui implementation."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sys
import threading
from typing import cast
import xml.etree.ElementTree as ET
from .models import (
    DEFAULT_UNCHECKED_EVENT_KINDS,
    EventKind,
    EVENT_FILTER_GROUPS,
    EVENT_FILTER_LABELS,
    GUI_STYLE,
    PLATFORM_EVENT_KINDS,
    PowerEvent,
    QueryResult,
    SourceState,
    TIMESTAMP_FORMAT,
    TimeRange,
    UTC,
)
from . import history


MAX_STRUCTURED_NODES = 10_000
QUERY_DEBOUNCE_MS = 250


def _json_evidence(event: PowerEvent) -> list[tuple[str, object]]:
    """Decode native JSON evidence, including the metadata/body pair of an IPS report.

    Returns no documents for plain text. Invalid JSON raises ValueError, keeping
    the original evidence available instead of silently showing a partial parse.
    """
    payload = event.raw.strip()
    is_ips = event.source == "DiagnosticReports / .ips"
    if is_ips and payload.startswith("Report: "):
        payload = payload.partition("\n\n")[2].lstrip()
    if not payload.startswith(("{", "[")):
        return []
    if not is_ips:
        return [("JSON", json.loads(payload))]
    header, end = json.JSONDecoder().raw_decode(payload)
    remaining = payload[end:].strip()
    if remaining:
        return [("Metadata", header), ("Report", json.loads(remaining))]
    return [("JSON", header)]


def _launch_gui() -> int:
    """Load the Qt GUI after CLI help/dependency checks and run its event loop."""
    from PySide6 import QtCore, QtGui, QtWidgets
    from utils.qt_widgets import configure_qt_application
    from .ui_mainwindow import Ui_PowerEventsWindow

    class QueryWorker(QtCore.QThread):
        """Run log collection off the GUI thread and deliver results via Qt signals."""

        completed = QtCore.Signal(object)
        failed = QtCore.Signal(str)
        progress = QtCore.Signal(str)

        def __init__(self, start: dt.datetime, end: dt.datetime, selected_kinds: frozenset[EventKind],
                     parent: QtCore.QObject) -> None:
            super().__init__(parent)
            self.start_time, self.end_time = start, end
            self.selected_kinds = selected_kinds
            self.cancelled = threading.Event()

        def run(self) -> None:
            """Emit a complete result or failure; exceptions never escape the worker thread."""
            try:
                result = history.query_events(self.start_time, self.end_time, self.cancelled, self.progress.emit,
                                              selected_kinds=self.selected_kinds)
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

    class PowerEventsWindow(QtWidgets.QMainWindow, Ui_PowerEventsWindow):
        """System history browser with cancellable queries, compact filters and evidence detail."""

        def __init__(self) -> None:
            super().__init__()
            self.settings = QtCore.QSettings(
                QtCore.QSettings.defaultFormat(), QtCore.QSettings.Scope.UserScope,
                "PersonalScripts", "PowerEvents",
            )
            self.worker: QueryWorker | None = None
            self.result: QueryResult | None = None
            self.status_message = ""
            self.closing = False
            self.initializing = True
            self.query_succeeded = False
            self.query_timer = QtCore.QTimer(self)
            self.query_timer.setSingleShot(True)
            self.query_timer.setInterval(QUERY_DEBOUNCE_MS)
            self.query_timer.timeout.connect(self._query)
            self.available_kinds = PLATFORM_EVENT_KINDS.get(sys.platform, frozenset())
            self.checkboxes: dict[EventKind, QtWidgets.QCheckBox] = {}
            self._build_ui()
            self._restore_settings()
            self._apply_range()
            self.initializing = False
            self._set_status("Select event types to query history.")

        def _build_ui(self) -> None:
            """Build native Qt controls and connect query/filter/export actions."""
            self.setupUi(self)
            self.range_box.addItems([value.value for value in TimeRange])
            self.range_box.currentIndexChanged.connect(self._apply_range)
            self.query_button.clicked.connect(self._query)
            self.refresh_shortcut = QtGui.QShortcut(QtGui.QKeySequence("F5"), self)
            self.refresh_shortcut.setAutoRepeat(False)
            self.refresh_shortcut.activated.connect(self.query_button.click)
            self.cancel_button.clicked.connect(self._cancel)
            self.select_all_button.clicked.connect(lambda: self._select_types(True))
            self.select_none_button.clicked.connect(lambda: self._select_types(False))
            self.reset_types_button.clicked.connect(self._reset_types)
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
                checkbox.toggled.connect(self._types_changed)
                self.checkboxes[kind] = checkbox
            self._layout_filters()

            # ── event table and evidence tabs ───────────
            self.model = EventsModel(self)
            self.proxy = EventFilter(self.model, self)
            self.table.setModel(self.proxy)
            self.table.setSortingEnabled(True)
            self.table.sortByColumn(0, QtCore.Qt.SortOrder.DescendingOrder)
            rows = self.table.verticalHeader()
            row_height = self.table.fontMetrics().height() + 4
            rows.setMinimumSectionSize(row_height)
            rows.setDefaultSectionSize(row_height)
            rows.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Fixed)
            for index, width in enumerate((155, 380, 220, 160), start=1):
                self.table.setColumnWidth(index, width)
            self.table.selectionModel().selectionChanged.connect(self._show_detail)
            self.structured_tree.setColumnWidth(0, 240)
            self.structured_tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
            self.structured_tree.hide()
            self.splitter.setSizes([470, 170])
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.export_button.clicked.connect(lambda: self._export(".csv"))
            self.export_json_button.clicked.connect(lambda: self._export(".json"))

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
            """Restore layout/date preferences, always leaving event selections cleared."""
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
            if value == TimeRange.CUSTOM.value:
                for key, editor in (("start", self.start_edit), ("end", self.end_edit)):
                    saved = str(self.settings.value(key, ""))
                    parsed = QtCore.QDateTime.fromString(saved, QtCore.Qt.DateFormat.ISODate)
                    if parsed.isValid():
                        editor.setDateTime(parsed)
            self._reset_types()

        def _apply_range(self) -> None:
            """Update date controls for relative ranges; retain custom selections."""
            selected = TimeRange(self.range_box.currentText())
            custom = selected == TimeRange.CUSTOM
            self.start_edit.setEnabled(custom and self.worker is None)
            self.end_edit.setEnabled(custom and self.worker is None)
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
            self.query_timer.stop()
            if self.worker is not None or self.closing:
                return
            if not self._selected_types():
                self.query_succeeded = False
                self._set_query_busy(False)
                self._set_status("Select event types to query history.")
                return
            self._apply_range()
            start = dt.datetime.fromtimestamp(self.start_edit.dateTime().toSecsSinceEpoch(), UTC)
            end = dt.datetime.fromtimestamp(self.end_edit.dateTime().toSecsSinceEpoch(), UTC)
            if start >= end:
                QtWidgets.QMessageBox.warning(self, "Invalid range", "Choose an end time after the start time.")
                return
            self.worker = QueryWorker(start, end, frozenset(self._selected_types()), self)
            self.worker.completed.connect(self._loaded)
            self.worker.failed.connect(self._failed)
            self.worker.progress.connect(self._set_status)
            self.worker.finished.connect(self._finished)
            self.query_succeeded = False
            self._set_query_busy(True)
            self._set_status("Querying...")
            self.worker.start()

        def _set_query_busy(self, busy: bool) -> None:
            """Lock query inputs and animate progress; restore platform/date restrictions when idle."""
            for kind, checkbox in self.checkboxes.items():
                checkbox.setEnabled(not busy and bool(EVENT_FILTER_GROUPS[kind] & self.available_kinds))
            for button in (self.select_all_button, self.select_none_button, self.reset_types_button):
                button.setEnabled(not busy)
            self.range_box.setEnabled(not busy)
            custom = self.range_box.currentText() == TimeRange.CUSTOM.value
            self.start_edit.setEnabled(not busy and custom)
            self.end_edit.setEnabled(not busy and custom)
            self.query_button.setEnabled(not busy)
            self.cancel_button.setEnabled(busy)
            self.export_button.setEnabled(not busy and self.proxy.rowCount() > 0)
            self.export_json_button.setEnabled(not busy and self.proxy.rowCount() > 0)
            self.progress_bar.setRange(0, 0 if busy else 1)
            if not busy:
                self.progress_bar.setValue(0)

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
            self.query_succeeded = True
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
            self._set_query_busy(False)
            self._filter()
            self.progress_bar.setToolTip("Query complete." if self.query_succeeded else self.status_message)
            if self.closing:
                self.close()

        def _select_types(self, checked: bool) -> None:
            """Toggle all event types and schedule one refresh for the batch."""
            before = self._selected_types()
            for checkbox in self.checkboxes.values():
                blocker = QtCore.QSignalBlocker(checkbox)
                checkbox.setChecked(checked and checkbox.isEnabled())
                del blocker
            if self._selected_types() != before:
                self._types_changed()
            else:
                self._filter()

        def _reset_types(self) -> None:
            """Restore category defaults, coalescing changes into one refresh."""
            before = self._selected_types()
            for kind, checkbox in self.checkboxes.items():
                blocker = QtCore.QSignalBlocker(checkbox)
                checkbox.setChecked(bool((EVENT_FILTER_GROUPS[kind] & self.available_kinds) - DEFAULT_UNCHECKED_EVENT_KINDS))
                del blocker
            if self._selected_types() != before:
                self._types_changed()
            else:
                self._filter()

        def _types_changed(self) -> None:
            """Filter immediately and debounce checkbox changes before querying."""
            self._filter()
            if not self.initializing and not self.closing and self.worker is None:
                self.query_timer.start()

        def _selected_types(self) -> set[EventKind]:
            """Expand checked groups, retaining selections while controls are disabled for a query."""
            return {member for kind, checkbox in self.checkboxes.items()
                    if checkbox.isChecked()
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
            self.progress_bar.setToolTip(message)
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
            self.structured_tree.clear()
            self.structured_tree.hide()
            self.structured_notice.setText("Select an event to inspect its XML or JSON.")
            self.structured_notice.show()

        def _show_structured(self, event: PowerEvent) -> None:
            """Show XML or JSON as plain-text nodes without modifying original evidence."""
            self.structured_tree.clear()
            self.structured_tree.hide()
            self.structured_notice.show()
            format_name = "XML" if event.xml else "JSON"
            self.structured_tree.setHeaderLabels(["Node", "Value", "Attributes" if event.xml else "Type"])
            self.structured_tree.setColumnWidth(2, 260 if event.xml else 100)
            try:
                if event.xml:
                    self._populate_xml(event.xml)
                    complete = True
                else:
                    documents = _json_evidence(event)
                    if not documents:
                        self.structured_notice.setText(
                            "This event has no XML or JSON record. See Event details for its original evidence.")
                        return
                    complete = self._populate_json(documents)
            except (ET.ParseError, ValueError, RecursionError) as exc:
                self.structured_tree.clear()
                self.structured_notice.setText(
                    f"Cannot display this {format_name}: {exc}. See Event details for the original record.")
                return
            self.structured_tree.expandToDepth(1)
            if complete:
                self.structured_notice.hide()
            else:
                self.structured_notice.setText(
                    f"Showing the first {MAX_STRUCTURED_NODES:,} nodes. Event details retains the complete record.")
            self.structured_tree.show()

        def _populate_xml(self, text: str) -> None:
            """Preserve XML child order, attributes and namespace tooltips."""
            root = ET.fromstring(text)
            pending = [(root, self.structured_tree.invisibleRootItem())]
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

        def _populate_json(self, documents: list[tuple[str, object]]) -> bool:
            """Render ordered objects/arrays and explicit scalar types within a node budget."""
            pending: list[tuple[str, object, QtWidgets.QTreeWidgetItem]] = [
                (name, value, self.structured_tree.invisibleRootItem()) for name, value in reversed(documents)
            ]
            count = 0
            while pending and count < MAX_STRUCTURED_NODES:
                name, value, parent = pending.pop()
                children: list[tuple[str, object]] = []
                if isinstance(value, dict):
                    children = list(cast(dict[str, object], value).items())
                    text, kind = f"{len(children):,} fields", "object"
                elif isinstance(value, list):
                    children = [(f"[{index}]", child) for index, child in enumerate(cast(list[object], value))]
                    text, kind = f"{len(children):,} items", "array"
                else:
                    text = json.dumps(value, ensure_ascii=False)
                    kind = ("null" if value is None else "boolean" if isinstance(value, bool)
                            else "string" if isinstance(value, str) else "number")
                item = QtWidgets.QTreeWidgetItem([name, text, kind])
                item.setToolTip(0, name)
                item.setToolTip(1, text)
                parent.addChild(item)
                count += 1
                pending.extend((key, child, item) for key, child in reversed(children))
            return not pending

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
            self._show_structured(event)

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
            self.closing = True
            self.query_timer.stop()
            if self.worker is not None:
                self._cancel()
                event.ignore()
                return
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("columns", self.table.horizontalHeader().saveState())
            self.settings.setValue("range", self.range_box.currentText())
            self.settings.remove("types")
            self.settings.remove("knownTypes")
            for key, editor in (("start", self.start_edit), ("end", self.end_edit)):
                self.settings.setValue(key, editor.dateTime().toString(QtCore.Qt.DateFormat.ISODate))
            super().closeEvent(event)

    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QtWidgets.QApplication([sys.argv[0]])
    if not isinstance(application, QtWidgets.QApplication):
        raise RuntimeError("A non-GUI Qt application is already running.")
    configure_qt_application(application, GUI_STYLE)
    window = PowerEventsWindow()
    window.show()
    # Keep a reference when embedded in another Qt session (also used by GUI tests).
    application.setProperty("powerEventsWindow", window)
    return application.exec() if owns_application else 0
