"""Verify TOC models, actual PDF exports, offscreen GUI and local vision HTTP requests.

Uses generated PDFs and a loopback mock API; never uploads a user's book.
Run: conda run -n base python -m unittest discover -s test -p test_pdf_bookmarks_gui.py.
"""

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import runpy
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *
ENTRY = ROOT / "tools/document-processing/pdf-bookmarks-add.py"
runpy.run_path(str(ENTRY))["load_app"]("bookmarks.model")
from personal_pdf_tools.bookmarks.model import Bookmark, BookSession, NeedsInformation, Status, TocPage, parse_draft
from personal_pdf_tools.bookmarks.recognition import build_request
from personal_pdf_tools.bookmarks.app import BookmarksWindow
from personal_pdf_tools.bookmarks.worker import Worker, export_project
from personal_pdf_tools.common.bookmark_editor import BookmarkEditor, OutlineRow


def wait_for(predicate: Callable[[], bool], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for GUI/network state.")
        QtWidgets.QApplication.processEvents()
        QtTest.QTest.qWait(10)


class BookmarksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="bookmarks-test-")
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.source = self.folder / "source.pdf"
        with pymupdf.open() as doc:
            for i in range(6):
                page = doc.new_page(width=200, height=300)
                page.insert_text((15, 30), f"Page {i + 1}: table of contents", fontsize=10)
                page.draw_rect((15, 80, 180, 190), color=(.2, .4, .6), fill=(.8, .8, .8))
            doc.set_toc([[1, "Original", 3], [2, "Child", 4]])
            outline = doc.get_outline_xrefs()[0]
            doc.xref_set_key(outline, "F", "2")
            doc.xref_set_key(outline, "C", "[1 0 0]")
            doc.xref_set_key(outline, "Count", "-1")
            doc[0].add_text_annot((10, 60), "Preserve annotation")
            doc[0].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(0, 0, 30, 20), "page": 4})
            doc.embfile_add("note.txt", b"preserve attachment")
            doc.save(self.source)
        self.project = BookSession(self.source, 6, [str(i) for i in range(1, 7)], body_pdf=3)
        self.project.toc = {1: TocPage(1), 2: TocPage(2)}

    def window(self) -> BookmarksWindow:
        window = BookmarksWindow(ENTRY)
        window.show()
        self.addCleanup(self.close_window, window)
        window.open_path(self.source)
        wait_for(lambda: window.session is not None and window._shown is not None and not window.runner.busy)
        return window

    def close_window(self, window: BookmarksWindow) -> None:
        window._stop()
        wait_for(lambda: not window.runner.busy and window.client.reply is None and window.balance_client.reply is None)
        window.dirty = False
        window.close()
        self.application.processEvents()

    def api_server(self, *, delay: float = 0, finish: str = "stop", status: int = 200,
                   catalogs: list[dict[str, object]] | None = None,
                   replies: list[str] | None = None,
                   gate: threading.Event | None = None) -> tuple[str, list[dict[str, object]]]:
        requests: list[dict[str, object]] = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                requests.append({"method": "GET", "path": self.path, "authorization": self.headers.get("Authorization")})
                page = int(parse_qs(urlsplit(self.path).query).get("page_no", ["1"])[0])
                responses = catalogs or [{"data": [{"id": "vision-z"}, {"id": "vision-a"}, {"id": "vision-z"}]}]
                data = responses[min(page - 1, len(responses) - 1)]
                payload = json.dumps(data if status == 200 else {"error": {"message": "Rejected test-key credentials"}}).encode()
                time.sleep(delay)
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    if status == 302:
                        self.send_header("Location", "/must-not-follow")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def do_POST(self) -> None:
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(data)
                attempt = len(requests)
                text = data["messages"][-1]["content"][0]["text"]
                match = re.search(r"PDF page: (\d+)", text)
                page = int(match.group(1)) if match else None
                time.sleep(delay)
                if gate is not None and attempt == 1:
                    gate.wait(5)
                content = f'- {{page: {page}, level: 1, title: "Recognized {page}"}}' if page else "red"
                if replies:
                    content = replies[min(attempt - 1, len(replies) - 1)]
                payload = json.dumps({"choices": [{"message": {"content": content},
                                                   "finish_reason": finish}], "usage": {"prompt_tokens": 321}} if status == 200
                                     else {"error": {"message": "Rejected test-key credentials"}}).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
            def log_message(self, format: str, *args: object) -> None:
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}/v1", requests

    def test_model_catalog_urls_and_validation(self) -> None:
        self.assertEqual(Llm.models_url("https://example.com/prefix/v1/chat/completions/"),
                         "https://example.com/prefix/v1/models")
        self.assertEqual(Llm.models_url("https://api.moonshot.cn/v1"), "https://api.moonshot.cn/v1/models")
        self.assertEqual(Llm.models_url("https://openrouter.ai/api/v1"), "https://openrouter.ai/api/v1/models")
        self.assertEqual(Llm.models_url("https://api.siliconflow.cn/v1"), "https://api.siliconflow.cn/v1/models?sub_type=chat")
        for host in ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "test.cn-beijing.maas.aliyuncs.com"):
            self.assertEqual(Llm.models_url(f"https://{host}/compatible-mode/v1", 2),
                             f"https://{host}/api/v1/models?page_no=2&page_size=100")
        self.assertEqual(Llm.models_url("https://dashscope.aliyuncs.com.example.com/v1"),
                         "https://dashscope.aliyuncs.com.example.com/v1/models")
        for invalid in ("file:///test", "https://key@example.com/v1", "https://example.com/v1?key=secret"):
            with self.assertRaises(ValueError):
                Llm.models_url(invalid)
        self.assertEqual(Llm.parse_models({"output": {"total": 1, "models": [{"model": "qwen-vl"}]}}), (["qwen-vl"], 1))
        for invalid in ({}, {"data": "bad"}, {"data": [{"name": "missing ID"}]},
                        {"data": [{"id": ""}]}, {"output": {"models": [], "total": 10001}}):
            with self.assertRaises(ValueError):
                Llm.parse_models(invalid)

    def test_balance_refresh_uses_key_only_and_does_not_require_a_pdf_or_model(self) -> None:
        endpoint, requests = self.api_server(catalogs=[{"balance_infos": [{"currency": "CNY", "total_balance": "12.3456"}]}])
        window = BookmarksWindow(ENTRY)
        self.addCleanup(self.close_window, window)
        window.api_url.setEditText(endpoint)
        window.api_key.setText("test-key")
        window.api_model.setCurrentText("")
        with patch.object(Llm, "balance_url", return_value=f"{endpoint}/user/balance"):
            window.api_key.editingFinished.emit()
            window._refresh_balance()  # A repeated refresh must not accumulate work.
            wait_for(lambda: window.balance_client.reply is None)
        self.assertEqual(requests, [{"method": "GET", "path": "/v1/user/balance", "authorization": "Bearer test-key"}])
        self.assertEqual(window.balance_summary.text(), "API balance: CNY 12.3456")
        self.assertIn("Updated", window.balance_status.text())
        self.assertIsNone(window.session)
        self.assertFalse(window._cursor_busy)
        window.api_key.setText("different-key")
        self.assertNotIn("12.3456", window.balance_summary.text())
        window.api_url.setEditText("https://api.siliconflow.cn/v1")
        window._refresh_balance()
        self.assertIn("unsupported", window.balance_summary.text())
        self.assertEqual(len(requests), 1)

    def test_balance_failure_cancel_and_credential_change_never_show_stale_balance(self) -> None:
        window = self.window()
        before = window.session.to_data()
        for status in (401, 302, 200):
            endpoint, requests = self.api_server(status=status, catalogs=[{"data": {"limit_remaining": 999}}])
            window.api_url.setEditText(endpoint)
            window.api_key.setText("test-key")
            with patch.object(Llm, "balance_url", return_value=f"{endpoint}/user/balance"):
                window._refresh_balance()
                self.assertTrue(window.viewer.navigation_enabled)
                wait_for(lambda: window.balance_client.reply is None)
            self.assertIn("unavailable", window.balance_summary.text())
            self.assertNotIn("test-key", window.balance_status.text())
            self.assertEqual(len(requests), 1)
        for action in ("cancel", "key", "timeout"):
            endpoint, requests = self.api_server(delay=.2, catalogs=[{"balance_infos": [{"currency": "CNY", "total_balance": "999"}]}])
            window.api_url.setEditText(endpoint)
            window.api_key.setText("test-key")
            window.balance_key.setText("management-key")
            with patch.object(Llm, "balance_url", return_value=f"{endpoint}/user/balance"):
                window._refresh_balance()
                wait_for(lambda: len(requests) == 1)
                self.assertEqual(requests[0]["authorization"], "Bearer management-key")
                if action == "cancel":
                    window._stop()
                elif action == "key":
                    window.balance_key.setText("replacement-key")
                else:
                    window.balance_client.timer.start(1)
                wait_for(lambda: window.balance_client.reply is None)
                QtTest.QTest.qWait(250)
            self.assertNotIn("999", window.balance_summary.text())
            self.assertTrue(window.balance_button.isEnabled())
        self.assertEqual(window.session.bookmarks, BookSession.from_data(before, self.folder).bookmarks)

    def test_api_test_refreshes_balance_with_separate_key_and_close_cancels_lookup(self) -> None:
        endpoint, requests = self.api_server(catalogs=[{"balance_infos": [{"currency": "USD", "total_balance": "3.50"}]}])
        window = BookmarksWindow(ENTRY)
        window.show()
        self.addCleanup(self.close_window, window)
        window.api_url.setEditText(endpoint)
        window.api_model.setCurrentText("test-model")
        window.api_key.setText("inference-key")
        window.balance_key.setText("management-key")
        with patch.object(Llm, "balance_url", return_value=f"{endpoint}/user/balance"), \
                patch.object(window.client, "send", wraps=window.client.send) as send:
            window._test_api()
            wait_for(lambda: not window._testing and window.balance_client.reply is None)
            self.assertEqual(send.call_args.args[1], "inference-key")
        self.assertEqual(len(requests), 2)
        self.assertIn("messages", requests[0])
        self.assertEqual(requests[1]["authorization"], "Bearer management-key")
        self.assertEqual(window.balance_summary.text(), "API balance: USD 3.50")
        endpoint, requests = self.api_server(delay=.2)
        window.api_url.setEditText(endpoint)
        self.assertEqual(window.balance_key.text(), "")
        window.api_key.setText("new-key")
        with patch.object(Llm, "balance_url", return_value=f"{endpoint}/user/balance"):
            window._refresh_balance()
            wait_for(lambda: len(requests) == 1)
            window.close()
            wait_for(lambda: window.balance_client.reply is None and not window.isVisible())

    def test_api_presets_custom_endpoint_and_model_fetch_without_pdf(self) -> None:
        endpoint, requests = self.api_server()
        window = BookmarksWindow(ENTRY)
        self.addCleanup(self.close_window, window)
        self.assertTrue(window.api_url.isEditable())
        self.assertTrue(window.fetch_button.isEnabled())
        for index, (_, url) in enumerate(Llm.PRESETS):
            window.api_url.setCurrentIndex(index)
            window.api_url.activated.emit(index)
            self.assertEqual(window._read_api().base_url, url)
        window.api_key.setText("previous-host-key")
        window.api_url.setEditText(endpoint)
        self.assertEqual(window.api_key.text(), "")
        window.api_key.setText("test-key")
        window.api_model.setCurrentText("manual-vision")
        self.assertEqual(requests, [])  # Configuration changes never send a request.
        window.fetch_button.click()
        self.assertFalse(window.fetch_button.isEnabled())
        self.assertTrue(window.stop_button.isEnabled())
        wait_for(lambda: not window._fetching)
        self.assertEqual(requests, [{"method": "GET", "path": "/v1/models", "authorization": "Bearer test-key"}])
        self.assertEqual([window.api_model.itemText(i) for i in range(window.api_model.count())], ["vision-a", "vision-z"])
        self.assertEqual(window.api_model.currentText(), "manual-vision")
        self.assertIn("2 models", window.models_status.text())
        self.assertFalse(window._cursor_busy)
        window.api_url.setEditText("http://[")  # Partial URL edits must not raise in a Qt slot.
        self.assertEqual(window.api_model.count(), 0)

    def test_model_lookup_pagination_and_failure_preserve_manual_choice(self) -> None:
        catalogs = [{"output": {"total": 3, "models": [{"model": "c"}, {"model": "a"}]}},
                    {"output": {"total": 3, "models": [{"model": "b"}]}}]
        endpoint, requests = self.api_server(catalogs=catalogs)
        window = BookmarksWindow(ENTRY)
        self.addCleanup(self.close_window, window)
        window.api_url.setEditText(endpoint)
        with patch.object(Llm, "models_url", side_effect=lambda base, page=1: f"{endpoint}/models?page_no={page}"):
            window._fetch_models()
            wait_for(lambda: not window._fetching)
        self.assertEqual(len(requests), 2)
        self.assertEqual([window.api_model.itemText(i) for i in range(window.api_model.count())], ["a", "b", "c"])
        endpoint, requests = self.api_server(catalogs=catalogs[:1])
        window.api_url.setEditText(endpoint)
        with patch.object(Llm, "models_url", side_effect=lambda base, page=1: f"{endpoint}/models?page_no={page}"):
            window._fetch_models()
            wait_for(lambda: not window._fetching)
        self.assertEqual(len(requests), 2)
        self.assertIn("pagination stalled", window.models_status.text())
        for status, catalog in ((401, None), (302, None), (200, [{"data": "malformed"}]), (200, [{"data": []}])):
            endpoint, requests = self.api_server(status=status, catalogs=catalog)
            window.api_url.setEditText(endpoint)
            window.api_key.setText("test-key")
            window.api_model.setCurrentText("manual-model")
            window._fetch_models()
            wait_for(lambda: not window._fetching)
            self.assertEqual(window.api_model.currentText(), "manual-model")
            self.assertEqual(len(requests), 1)
            self.assertNotIn("test-key", window.models_status.text())
            self.assertIn("0 models" if catalog == [{"data": []}] else "Cannot fetch", window.models_status.text())
            self.assertTrue(window.fetch_button.isEnabled())

    def test_model_lookup_cancellation_and_timeout_do_not_queue_or_edit_book(self) -> None:
        endpoint, requests = self.api_server(delay=.2)
        window = self.window()
        window.api_url.setEditText(endpoint)
        window.api_model.setCurrentText("manual-model")
        before = window.session.to_data()
        for timeout in (False, True):
            window._fetch_models()
            window._fetch_models()  # A second click/request cannot queue another lookup.
            wait_for(lambda: len(requests) == (2 if timeout else 1))
            if timeout:
                window.client.timer.start(1)
            else:
                window._stop()
            wait_for(lambda: not window._fetching)
            self.assertIn("timed out" if timeout else "stopped", window.models_status.text())
            self.assertIsNone(window.client.reply)
            self.assertEqual(window.session.to_data(), before)
            self.assertFalse(window._cursor_busy)

    def test_current_page_buttons_fill_toc_bounds_and_remap_body(self) -> None:
        window = self.window()
        for button, page, target in zip(window.current_page_buttons, (2, 3, 4),
                                        (window.toc_first, window.toc_last, window.body_pdf)):
            window.go_page(page)
            wait_for(lambda: not window.runner.busy)
            button.click()
            self.assertEqual(target.value(), page)
            self.assertEqual(window.session.current_page, page)
        self.assertEqual(window.session.toc, {})  # Marking still requires Mark TOC.
        self.assertEqual(window.session.body_pdf, 4)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(set(window.session.toc), {2, 3})

    def test_yaml_comments_null_fences_and_strict_types(self) -> None:
        text = '# comment\n- {page: 20, level: 2, index: "1.1", title: "Title: value"}\n- {page: null, level: 2, title: "Unclear"}'
        rows = parse_draft(text, 1, 17, 20)
        self.assertEqual(rows[0].page, 17)
        self.assertEqual(rows[0].title, "1.1 Title: value")
        self.assertEqual(rows[1].page, 0)
        self.assertEqual(parse_draft('```yaml\n[]\n```', 1, 1, 1), [])
        for invalid in ('- {page: true, level: 1, title: "Bad"}', '- {page: 1.5, level: 1, title: "Bad"}',
                        '- {page: 0, level: 1, title: "Bad"}', '- {page: 1, page: 2, level: 1, title: "Bad"}',
                        '- {page: 1, level: 1, index: 1.1, title: "Bad"}', '!!python/object:example {}',
                        '- &a {page: 1, level: 1, title: "Bad"}\n- *a'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_draft(invalid, 1, 1, 1)

    def test_retry_replaces_only_source_page_and_keeps_context_order(self) -> None:
        project = self.project
        project.apply_draft(2, '- {page: 3, level: 1, title: "Later"}')
        project.apply_draft(1, '- {page: 1, level: 1, title: "Earlier"}')
        project.toc[1].status = Status.DONE
        project.toc[2].status = Status.DONE
        project.apply_draft(1, '- {page: 2, level: 1, title: "Corrected"}')
        self.assertEqual([item.title for item in project.bookmarks], ["Corrected", "Later"])
        body = build_request(project, 2, b"jpeg")
        payload = json.dumps(body)
        self.assertIn("Corrected", payload)
        self.assertNotIn("Later", payload)
        project.context_start = 2
        self.assertNotIn("Corrected", json.dumps(build_request(project, 2, b"jpeg")))
        self.assertEqual(Llm.completion_url("https://example.com/v1/"), "https://example.com/v1/chat/completions")
        with self.assertRaises(ValueError):
            Llm.completion_url("https://key@example.com")

    def test_structured_recognition_errors_and_unresolved_pages_are_atomic(self) -> None:
        self.project.apply_draft(1, '- {page: 1, level: 1, title: "Accepted"}')
        before = list(self.project.bookmarks)
        problem = ('entries: [{page: 2, level: 1, title: "Partial"}]\nerrors:\n'
                   '  - {error_message: "Missing page", location: "Right column, second row", needs: "Provide printed page"}')
        with self.assertRaisesRegex(NeedsInformation, "Right column, second row"):
            self.project.apply_draft(1, problem)
        with self.assertRaisesRegex(NeedsInformation, "Unclear"):
            self.project.apply_draft(1, '- {page: null, level: 1, title: "Unclear"}')
        self.assertEqual(self.project.bookmarks, before)
        for bad in ('entries: []\nerrors: "Missing page"',
                    'entries: []\nerrors: [{error_message: "Problem"}]',
                    'entries: []\nerrors: [{error_message: true, location: "Row 2", needs: "Number"}]',
                    'entries: []\nerrors: []\nextra: false'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_draft(bad, 1, 1, 1)
        self.project.apply_draft(1, 'entries: [{page: 2, level: 1, title: "Resolved"}]\nerrors: []')
        self.assertEqual(self.project.bookmarks[0].title, "Resolved")

    def test_problem_page_queue_trace_supplement_and_single_page_retry(self) -> None:
        problem = ('entries: []\nerrors:\n'
                   '  - {error_message: "Missing number", location: "Chapter Alpha, right edge", needs: "Provide printed page"}')
        gate = threading.Event()
        endpoint, requests = self.api_server(gate=gate, replies=[problem,
            'entries: [{page: 2, level: 1, title: "Beta"}]\nerrors: []',
            'entries: [{page: 1, level: 1, title: "Alpha"}]\nerrors: []'])
        self.addCleanup(gate.set)
        window = self.window()
        window.toc_last.setValue(2)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        window.api_url.setEditText(endpoint)
        window.api_model.setCurrentText("test-model")
        window.api_key.setText("test-key")
        window._run_all()
        wait_for(lambda: len(requests) == 1)
        QtTest.QTest.qWait(150)
        self.assertEqual(len(requests), 1)
        self.assertEqual(window.session.toc[2].status, Status.PENDING)
        gate.set()
        wait_for(lambda: not window._running and not window.runner.busy)
        task = window.session.toc[1]
        self.assertEqual(task.status, Status.NEEDS_INFO)
        self.assertTrue(task.draft_invalid)
        self.assertEqual(task.raw_response, problem)
        self.assertEqual(window.session.toc[2].status, Status.DONE)
        self.assertEqual([item.title for item in window.session.bookmarks], ["Beta"])
        self.assertNotIn("Missing number", json.dumps(requests[1]))
        with patch.object(window, "_error") as error, patch.object(QtWidgets.QFileDialog, "getSaveFileName") as dialog:
            self.assertFalse(window._export())
            error.assert_called_once()
            dialog.assert_not_called()
        window.go_page(1)
        wait_for(lambda: not window.runner.busy)
        self.assertIn("Chapter Alpha, right edge", window.trace.toPlainText())
        self.assertIn('"crop"', window.trace.toPlainText())
        self.assertNotIn("test-key", window.trace.toPlainText())
        self.assertNotIn("data:image", window.trace.toPlainText())
        window.supplement_button.click()
        self.assertEqual(window.requirement_scope.currentIndex(), 1)
        window.requirements.setPlainText("Alpha has printed page 1.")
        self.assertEqual(window.session.requirements, "")
        self.assertEqual(len(requests), 2)
        window._retry()
        wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual(len(requests), 3)
        self.assertIn("Missing number", json.dumps(requests[2]))
        self.assertIn("Alpha has printed page 1.", json.dumps(requests[2]))
        self.assertNotIn('"Beta"', json.dumps(requests[2]))
        self.assertEqual([item.title for item in window.session.bookmarks], ["Alpha", "Beta"])
        self.assertEqual(task.status, Status.DONE)
        self.assertFalse(task.draft_invalid)
        self.assertEqual(len(task.history), 2)
        self.assertIn("Missing number", window.trace.toPlainText())
        self.assertEqual(len(window.session.toc[2].history), 1)
        self.assertNotIn("history", window.session.to_data()["toc"][0])

    def test_manual_issue_resolution_retains_raw_response_and_clears_page_error(self) -> None:
        window = self.window()
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        before = list(window.session.bookmarks)
        window.yaml.setPlainText('- {page: null, level: 1, title: "Missing"}')
        wait_for(lambda: window.session.toc[1].status == Status.NEEDS_INFO)
        self.assertEqual(window.session.bookmarks, before)
        window.yaml.setPlainText('entries: [{page: 1, level: 1, title: "Resolved"}]\nerrors: []')
        wait_for(lambda: window.session.toc[1].status == Status.MODIFIED)
        self.assertFalse(window.session.toc[1].draft_invalid)
        self.assertEqual(window.session.toc[1].error, "")
        self.assertEqual(window.pages.topLevelItem(0).text(2), Status.MODIFIED.value)

    def test_session_transport_keeps_comments_and_no_credentials(self) -> None:
        self.project.toc[1].draft = '# keep this comment\n[]'
        self.project.toc[1].status = Status.RUNNING
        self.project.toc[1].crop = (.1, .2, .8, .9)
        self.project.toc[1].angle = -2.5
        data = self.project.to_data()
        loaded = BookSession.from_data(data, self.folder)
        self.assertEqual(loaded.toc[1].status, Status.INTERRUPTED)
        self.assertEqual(loaded.toc[1].draft, self.project.toc[1].draft)
        self.assertEqual(loaded.toc[1].crop, (.1, .2, .8, .9))
        self.assertNotIn("api_key", json.dumps(data))
        self.assertNotIn("password", json.dumps(data))

    def test_export_preserves_pixels_links_annotations_attachments_and_original_bookmark_style(self) -> None:
        with pymupdf.open(self.source) as original:
            toc = original.get_toc(False)
            self.project.bookmarks = [Bookmark(row[1], row[2], row[0], original_xref=row[3]["xref"]) for row in toc]
            pixels = [page.get_pixmap().samples for page in original]
            original_bytes = self.source.read_bytes()
        self.project.bookmarks[0].title = "Renamed"
        self.project.bookmarks.append(Bookmark("New", 6))
        Pdf.generate_page_labels(self.project.labels, 3, 20, [1, 2])
        target = self.folder / "result.pdf"
        export_project(self.project, target)
        with pymupdf.open(target) as result:
            self.assertEqual([page.get_pixmap().samples for page in result], pixels)
            self.assertEqual(result.embfile_get("note.txt"), b"preserve attachment")
            self.assertEqual(result[0].get_links()[0]["page"], 4)
            self.assertEqual(next(result[0].annots()).info["content"], "Preserve annotation")
            self.assertEqual(result.get_toc()[0], [1, "Renamed", 3])
            self.assertTrue(result.get_toc(False)[0][3]["bold"])
            self.assertTrue(result.get_toc(False)[0][3]["collapse"])
            self.assertEqual(Pdf.read_page_labels(result), ["C1", "C2", "20", "21", "22", "23"])
        self.assertEqual(self.source.read_bytes(), original_bytes)
        with self.assertRaises(FileExistsError):
            export_project(self.project, target)
        self.project.bookmarks = [Bookmark("Bad target", 0)]
        with self.assertRaises(ValueError):
            self.project.validate_export()

    def test_label_partial_edits_and_clear_preserve_other_pages(self) -> None:
        values = ["i", "ii", "1", "2", "3", "4"]
        Pdf.number_page_labels(values, (2, 4), -1, "A-")
        self.assertEqual(values, ["i", "ii", "A--1", "2", "A-0", "4"])
        Pdf.clear_page_labels(values, (1, 5))
        Pdf.generate_page_labels(values, 4, 10, (2,))
        self.assertEqual(values, ["i", "C1", "A--1", "10", "11", "12"])

    def test_tree_editing_is_optional_and_moves_whole_subtrees(self) -> None:
        readonly = BookmarkEditor()
        readonly.load([OutlineRow("a", "A", 1, 1)])
        self.assertFalse(readonly.tree.topLevelItem(0).flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
        editor = BookmarkEditor(editable=True)
        editor.load([OutlineRow("a", "A", 1, 1), OutlineRow("b", "B", 2, 2), OutlineRow("c", "C", 3, 1)])
        editor.tree.setCurrentItem(editor.tree.topLevelItem(1))
        editor._move(-1)
        self.assertEqual([row.id for row in editor.rows()], ["c", "a", "b"])
        editor.tree.setCurrentItem(editor.tree.topLevelItem(1))
        editor._indent()
        self.assertEqual([row.level for row in editor.rows()], [1, 2, 3])
        editor._outdent()
        self.assertEqual([row.level for row in editor.rows()], [1, 1, 2])
        editor.tree.currentItem().setText(1, "5")
        self.assertEqual(editor.rows()[1].page, 5)

    def test_gui_red_box_yaml_update_clear_undo_and_label_tab(self) -> None:
        window = self.window()
        window.toc_first.setValue(1)
        window.toc_last.setValue(2)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        self.assertTrue(window.viewer._crop_item.isVisible())
        self.assertEqual(window.viewer._crop, (0, 0, 1, 1))
        self.assertEqual(window.viewer._crop_item.pen().widthF(), 4)
        window._crop_changed((.1, .2, .8, .9))
        window.viewer.set_crop((.1, .2, .8, .9))
        image = window._image()
        self.assertLess(image.width(), window.viewer._original.width())
        window.body_pdf.setValue(3)
        window._mapping_changed()
        window.yaml.setPlainText('# note\n- {page: 1, level: 1, title: "Generated"}')
        wait_for(lambda: bool(window.session.bookmarks) and window.session.bookmarks[0].title == "Generated")
        self.assertEqual(window.tree.rows()[0].page, 3)
        window._clear_bookmarks()
        self.assertFalse(window.session.bookmarks)
        self.assertIn("# note", window.session.toc[1].draft)
        window._undo_bookmarks()
        self.assertEqual(window.session.bookmarks[0].title, "Generated")
        window._label_generate()
        self.assertEqual(window.session.labels[:4], ["C1", "C2", "1", "2"])
        window.angle.setValue(2.5)
        window._rotation_changed()
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(window.viewer._crop, (0, 0, 1, 1))

    def test_real_serial_queue_retry_and_api_payload(self) -> None:
        endpoint, requests = self.api_server()
        window = self.window()
        window.toc_last.setValue(2)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        window.body_pdf.setValue(3)
        window._mapping_changed()
        window.api_url.setEditText(endpoint)
        window.api_model.setCurrentText("test-model")
        window.api_key.setText("test-key")
        window._run_all()
        wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual(len(requests), 2)
        self.assertEqual([entry.title for entry in window.session.bookmarks], ["Recognized 1", "Recognized 2"])
        self.assertEqual([entry.page for entry in window.session.bookmarks], [3, 4])
        self.assertIn("data:image/jpeg;base64,", json.dumps(requests[0]))
        self.assertNotIn("Recognized 1", json.dumps(requests[0]))
        self.assertIn("Recognized 1", json.dumps(requests[1]))
        window.go_page(1)
        wait_for(lambda: not window.runner.busy)
        window._retry()
        wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual(len(requests), 3)
        self.assertNotIn("Recognized 2", json.dumps(requests[2]))
        self.assertEqual(len(window.session.bookmarks), 2)
        self.assertEqual(window.session.last_prompt_tokens, 321)

    def test_stop_aborts_request_and_does_not_send_next_page(self) -> None:
        endpoint, requests = self.api_server(delay=.3)
        window = self.window()
        window.toc_last.setValue(2)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        window.api_url.setEditText(endpoint)
        window.api_model.setCurrentText("test-model")
        window._run_all()
        wait_for(lambda: len(requests) == 1)
        window._stop()
        wait_for(lambda: window.client.reply is None and not window.runner.busy)
        QtTest.QTest.qWait(400)
        self.assertEqual(len(requests), 1)
        self.assertEqual(window.session.toc[1].status, Status.INTERRUPTED)
        self.assertEqual(window.session.toc[2].status, Status.PENDING)

    def test_truncated_api_response_preserves_draft_without_applying(self) -> None:
        endpoint, _ = self.api_server(finish="length")
        window = self.window()
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        before = list(window.session.bookmarks)
        window.api_url.setEditText(endpoint)
        window.api_model.setCurrentText("test-model")
        window._run_all()
        wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual(window.session.toc[1].status, Status.ERROR)
        self.assertIn("Recognized", window.session.toc[1].raw_response)
        self.assertEqual(window.session.bookmarks, before)

    def test_invalid_manual_yaml_cannot_export_stale_tree(self) -> None:
        window = self.window()
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        before = list(window.session.bookmarks)
        window.yaml.setPlainText('- {page: bad, level: 1, title: "Invalid"}')
        wait_for(lambda: window.session.toc[1].draft_invalid)
        self.assertEqual(window.session.bookmarks, before)
        with patch.object(window, "_error") as error, patch.object(QtWidgets.QFileDialog, "getSaveFileName") as dialog:
            window._export()
            error.assert_called_once()
            dialog.assert_not_called()
        window._clear_bookmarks()
        self.assertFalse(window.session.toc[1].draft_invalid)

    def test_project_options_and_corrupt_fields(self) -> None:
        self.project.keep_existing = True
        self.project.pending_only = False
        self.project.clear_context = True
        data = self.project.to_data()
        restored = BookSession.from_data(data, self.folder)
        self.assertTrue(restored.keep_existing)
        self.assertFalse(restored.pending_only)
        self.assertTrue(restored.clear_context)
        for name, value in (("toc", "bad"), ("bookmarks", [{}]), ("keep_existing", "yes")):
            with self.subTest(name=name), self.assertRaises(ValueError):
                BookSession.from_data({**data, name: value}, self.folder)
        for field, value in (("draft", 3), ("crop", [0, 0, 0, 1]), ("angle", float("nan"))):
            invalid = json.loads(json.dumps(data))
            invalid["toc"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                BookSession.from_data(invalid, self.folder)

    def test_worker_authentication_export_and_label_retry(self) -> None:
        encrypted = self.folder / "protected.pdf"
        with Pdf.open_document(self.source, interactive=False) as (document, _):
            document.save(encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
        worker = Worker()
        self.addCleanup(worker.close)
        with self.assertRaises(ValueError):
            worker.run({"operation": "inspect", "path": str(encrypted), "password": "bad"})
        opened = worker.run({"operation": "inspect", "path": str(encrypted), "password": "secret"})
        project = BookSession.from_data({"format": "pdf-bookmarks-session", "version": 1,
            "source": str(encrypted), "page_count": opened["page_count"], "labels": opened["labels"],
            "bookmarks": opened["bookmarks"]}, self.folder)
        Pdf.clear_page_labels(project.labels, (1, 2))
        target = self.folder / "decrypted.pdf"
        with patch.object(Pdf, "save_new", side_effect=OSError("Simulated write failure")):
            with self.assertRaises(OSError):
                export_project(project, target, "secret")
        self.assertFalse(target.exists())
        export_project(project, target, "secret")
        with Pdf.open_document(target, interactive=False) as (document, _):
            self.assertFalse(document.is_encrypted)
            self.assertEqual(Pdf.read_page_labels(document), ["1", "", "", "4", "5", "6"])
            self.assertEqual(document.get_toc(), [[1, "Original", 3], [2, "Child", 4]])

    def test_manual_targets_stay_fixed_when_body_anchor_changes(self) -> None:
        project = self.project
        project.apply_draft(1, '- {page: -1, level: 1, title: "Preface"}\n- {page: 1, level: 1, title: "Body"}')
        self.assertEqual([entry.page for entry in project.bookmarks], [2, 3])
        project.bookmarks[1].logical_page = None
        project.bookmarks[1].page = 6
        project.remap(4, 1)
        self.assertEqual([entry.page for entry in project.bookmarks], [3, 6])
        before = list(project.labels)
        with self.assertRaises(ValueError):
            Pdf.generate_page_labels(project.labels, 99, 1, [1])
        self.assertEqual(project.labels, before)

    def test_shared_viewer_page_keys_and_crop_focus(self) -> None:
        window = self.window()
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        window.draw_crop.setChecked(True)
        window.yaml.setFocus()
        QtTest.QTest.mouseClick(window.viewer.viewport(), QtCore.Qt.MouseButton.LeftButton,
                               pos=window.viewer.viewport().rect().center())
        self.assertTrue(window.viewer.hasFocus())
        for forward, back in ((QtCore.Qt.Key.Key_PageDown, QtCore.Qt.Key.Key_PageUp),
                              (QtCore.Qt.Key.Key_Right, QtCore.Qt.Key.Key_Left),
                              (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_Up)):
            with self.subTest(forward=forward):
                QtTest.QTest.keyClick(window.viewer, forward)
                wait_for(lambda: not window.runner.busy)
                self.assertEqual(window.session.current_page, 2)
                QtTest.QTest.keyClick(window.viewer, back)
                wait_for(lambda: not window.runner.busy)
                self.assertEqual(window.session.current_page, 1)
        window.viewer.navigation_enabled = False
        QtTest.QTest.keyClick(window.viewer, QtCore.Qt.Key.Key_PageDown)
        self.assertEqual(window.session.current_page, 1)
        window.viewer.navigation_enabled = True
        QtTest.QTest.keyClick(window.viewer, QtCore.Qt.Key.Key_Right, QtCore.Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(window.session.current_page, 1)
        window.yaml.setFocus()
        for key in (QtCore.Qt.Key.Key_PageDown, QtCore.Qt.Key.Key_Right, QtCore.Qt.Key.Key_Down):
            QtTest.QTest.keyClick(window.yaml, key)
        self.assertEqual(window.session.current_page, 1)

    def test_mouse_crop_and_double_click_edit_does_not_navigate(self) -> None:
        window = self.window()
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        window.draw_crop.setChecked(True)
        bounds = window.viewer._bounds
        start = window.viewer.mapFromScene(bounds.width() * .1, bounds.height() * .2)
        end = window.viewer.mapFromScene(bounds.width() * .8, bounds.height() * .9)
        QtTest.QTest.mousePress(window.viewer.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=start)
        QtTest.QTest.mouseMove(window.viewer.viewport(), end)
        QtTest.QTest.mouseRelease(window.viewer.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=end)
        for actual, expected in zip(window.session.toc[1].crop, (.1, .2, .8, .9)):
            self.assertAlmostEqual(actual, expected, places=2)
        editor = window.tree
        item = editor.tree.topLevelItem(0)
        with patch.object(window, "go_page") as navigate:
            editor._navigate(item, 0)
            editor.tree.itemDoubleClicked.emit(item, 0)
            QtTest.QTest.qWait(QtWidgets.QApplication.doubleClickInterval() + 30)
            navigate.assert_not_called()

    def test_add_targets_current_page_and_ctrl_click_only_selects(self) -> None:
        window = self.window()
        window.go_page(5)
        wait_for(lambda: not window.runner.busy)
        editor = window.tree
        first = editor.tree.topLevelItem(0)
        point = editor.tree.visualItemRect(first).center()
        QtTest.QTest.mouseClick(editor.tree.viewport(), QtCore.Qt.MouseButton.LeftButton,
                               QtCore.Qt.KeyboardModifier.ControlModifier, point)
        QtTest.QTest.qWait(QtWidgets.QApplication.doubleClickInterval() + 30)
        self.assertIs(editor.tree.currentItem(), first)
        self.assertEqual(window.session.current_page, 5)
        editor._add()
        self.assertEqual(editor.rows()[-1].page, 5)
        self.assertEqual(window.session.bookmarks[-1].page, 5)

    def test_outdent_modes_and_right_click_selection(self) -> None:
        window = self.window()
        editor = window.tree
        rows = [OutlineRow(name, name, i + 1, level) for i, (name, level) in
                enumerate((("A", 1), ("B", 2), ("B1", 3), ("C", 2), ("D", 1)))]
        for keep_order, names, levels in ((True, ["A", "B", "B1", "C", "D"], [1, 1, 2, 2, 1]),
                                          (False, ["A", "C", "B", "B1", "D"], [1, 2, 1, 2, 1])):
            editor.load(rows)
            editor.tree.setCurrentItem(editor.tree.topLevelItem(0).child(0))
            editor._outdent(keep_order)
            self.assertEqual([row.id for row in editor.rows()], names)
            self.assertEqual([row.level for row in editor.rows()], levels)
        editor.load(rows)
        target = editor.tree.topLevelItem(0).child(0)
        editor._navigate(target, 0)
        context_menu = editor._make_context_menu(target)
        with patch.object(editor, "_make_context_menu", return_value=context_menu):
            QtCore.QTimer.singleShot(30, context_menu.close)
            editor._context_menu(editor.tree.visualItemRect(target).center())
        self.assertIs(editor.tree.currentItem(), target)
        self.assertFalse(editor._navigation_timer.isActive())
        menu = editor._make_context_menu(target)
        self.assertIn("Outdent (keep order)", [action.text() for action in menu.actions()])
        self.assertIn("Outdent (move below parent)", [action.text() for action in menu.actions()])

    def test_cached_navigation_and_rotation_invalidation(self) -> None:
        window = self.window()
        window.go_page(2)
        wait_for(lambda: not window.runner.busy)
        with patch.object(window.runner, "start", wraps=window.runner.start) as start:
            window.go_page(1)
            self.assertEqual(window._shown, (1, 0))
            window.go_page(2)
            self.assertEqual(window._shown, (2, 0))
            start.assert_not_called()
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        with patch.object(window.runner, "start", wraps=window.runner.start) as start:
            window.angle.setValue(3)
            window._rotation_changed()
            start.assert_called_once()
            self.assertIn("pixel_buffer", start.call_args.args[0])
            wait_for(lambda: not window.runner.busy)
        self.assertEqual(window.preview_cache.get(1)[0], 3)
        window.preview_cache.max_pages = 1
        window.go_page(3)
        wait_for(lambda: not window.runner.busy)
        self.assertIsNone(window.preview_cache.get(1))
        self.assertLessEqual(window.preview_cache.size, window.preview_cache.max_bytes)

    def test_api_probe_without_pdf_and_failure_details(self) -> None:
        for status in (200, 401):
            endpoint, requests = self.api_server(status=status)
            window = BookmarksWindow(ENTRY)
            self.addCleanup(self.close_window, window)
            self.assertTrue(window.test_button.isEnabled())
            window.api_url.setEditText(endpoint)
            window.api_model.setCurrentText("test-model")
            window.api_key.setText("test-key")
            window._test_api()
            wait_for(lambda: not window._testing)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["max_tokens"], 32)
            self.assertIn("data:image/png;base64,", json.dumps(requests[0]))
            self.assertIsNone(window.session)
            self.assertIn("passed" if status == 200 else "401", window.test_status.text())
            self.assertNotIn("test-key", window.test_status.text())

    def test_export_before_closing_and_no_project_entry(self) -> None:
        window = self.window()
        self.assertEqual(window.file_drops.suffixes, (".pdf",))
        self.assertFalse(hasattr(window, "_save"))
        window._clear_bookmarks()
        target = self.folder / "cleared.pdf"
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Save), \
                patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(target), "PDF")):
            window.close()
        wait_for(lambda: not window.isVisible() and not window.runner.busy)
        self.assertFalse(window.dirty)
        with Pdf.open_document(target, interactive=False) as (document, _):
            self.assertEqual(document.get_toc(), [])

    def test_failed_export_does_not_close_or_discard_edits(self) -> None:
        window = self.window()
        window._clear_bookmarks()
        target = self.folder / "exists.pdf"
        target.write_bytes(b"Existing content")
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Save), \
                patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(target), "PDF")), \
                patch.object(window, "_error") as error:
            window.close()
            wait_for(lambda: not window.runner.busy)
            error.assert_called_once()
        self.assertTrue(window.isVisible())
        self.assertTrue(window.dirty)
        self.assertFalse(window.session.bookmarks)
        self.assertIsNone(window._after_export)
        self.assertEqual(target.read_bytes(), b"Existing content")


if __name__ == "__main__":
    unittest.main()
