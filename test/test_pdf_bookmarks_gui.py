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
from personal_pdf_tools.bookmarks.model import Bookmark, BookSession, ConversationTurn, NeedsInformation, Status, TocPage, parse_draft
from personal_pdf_tools.bookmarks.recognition import build_request
from personal_pdf_tools.bookmarks.app import BookmarksWindow
from personal_pdf_tools.bookmarks.worker import Worker, export_project
from personal_pdf_tools.common.bookmark_editor import BookmarkEditor, OutlineRow, _DeletionChoice


def wait_for(predicate: Callable[[], bool], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for GUI/network state.")
        QtWidgets.QApplication.processEvents()
        # Let Python API workers run as well as pumping the GUI event queue.
        time.sleep(.01)


class BookmarksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def setUp(self) -> None:
        notice = patch.object(QtWidgets.QMessageBox, "information")
        self.notice = notice.start()
        self.addCleanup(notice.stop)
        self.real_warning = BookmarksWindow._show_recognition_warning
        warning = patch.object(BookmarksWindow, "_show_recognition_warning")
        self.warning = warning.start()
        self.addCleanup(warning.stop)
        directory = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="bookmarks-test-")
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.enterContext(patch("utils.config.ConfigStore.directory", return_value=self.folder / "user-config"))
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
                   vision_html: str | None = None,
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
                if self.path == "/models-page" and vision_html is not None:
                    payload = vision_html.encode("utf-8")
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
        self.assertEqual(window.balance_status.text(), "API account balance: CNY 12.3456")
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
        window.api_url.setEditText(endpoint)

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

    def test_strict_model_filter_paginates_unfiltered_rows_and_reports_unknowns(self) -> None:
        catalogs = [{"output": {"total": 3, "models": [{"model": "text"}, {"model": "vision-name-only"}]}},
                    {"output": {"total": 3, "models": [{"model": "reader", "architecture": {"input_modalities": ["image", "text"]}}]}}]
        endpoint, requests = self.api_server(catalogs=catalogs)
        window = BookmarksWindow(ENTRY)
        self.addCleanup(self.close_window, window)
        window.api_url.setEditText(endpoint)
        window.vision_models_only.setChecked(True)
        self.assertFalse(requests)
        with patch.object(Llm, "models_url", side_effect=lambda base, page=1: f"{endpoint}/models?page_no={page}"):
            window._fetch_models()
            wait_for(lambda: not window._fetching)
        self.assertEqual(len(requests), 2)
        self.assertEqual([window.api_model.itemText(i) for i in range(window.api_model.count())], ["reader"])
        self.assertIn("confirmed image-input", window.models_status.text())
        endpoint, requests = self.api_server(catalogs=[{"data": [{"id": "unknown"}]}])
        window.api_url.setEditText(endpoint)
        window._fetch_models()
        wait_for(lambda: not window._fetching)
        self.assertEqual(window.api_model.count(), 0)
        self.assertIn("may omit capability metadata", window.models_status.text())
        window.vision_models_only.setChecked(False)
        self.assertEqual(len(requests), 1)
        window._fetch_models()
        wait_for(lambda: not window._fetching)
        self.assertEqual([window.api_model.itemText(i) for i in range(window.api_model.count())], ["unknown"])

    def test_siliconflow_vision_filter_intersects_catalog_without_forwarding_key(self) -> None:
        rows = [{"modelName": name, "vlm": True, "type": "text"} for name in ("reader", "not-in-account")]
        flight = f'1:{json.dumps({"models": rows})}\n'
        html = f'<script>self.__next_f.push({json.dumps([1, flight])})</script>'
        endpoint, requests = self.api_server(catalogs=[{"data": [{"id": "reader"}, {"id": "text"}]}], vision_html=html)
        window = BookmarksWindow(ENTRY)
        self.addCleanup(self.close_window, window)
        window.api_url.setEditText(endpoint)
        window.api_key.setText("test-key")
        window.vision_models_only.setChecked(True)
        public_url = f"{endpoint.removesuffix('/v1')}/models-page"
        with patch.object(Llm, "vision_catalog_url", return_value=public_url):
            window._fetch_models()
            wait_for(lambda: not window._fetching)
            self.assertEqual([window.api_model.itemText(i) for i in range(window.api_model.count())], ["reader"])
            self.assertIn("1 confirmed", window.models_status.text())
            self.assertEqual(requests, [
                {"method": "GET", "path": "/v1/models", "authorization": "Bearer test-key"},
                {"method": "GET", "path": "/models-page", "authorization": None},
            ])
            window.vision_models_only.setChecked(False)
            window._fetch_models()
            wait_for(lambda: not window._fetching)
            self.assertEqual(len(requests), 3)  # No public request when unfiltered.
            self.assertEqual(window.api_model.count(), 2)

    def test_siliconflow_metadata_failure_cancel_and_timeout_are_explicit(self) -> None:
        window = BookmarksWindow(ENTRY)
        self.addCleanup(self.close_window, window)
        window.vision_models_only.setChecked(True)
        for action in ("malformed", "cancel", "timeout"):
            endpoint, requests = self.api_server(vision_html="<html>Unavailable</html>", delay=.2)
            window.api_url.setEditText(endpoint)
            window.api_model.setCurrentText("manual-model")
            public_url = f"{endpoint.removesuffix('/v1')}/models-page"
            with patch.object(Llm, "vision_catalog_url", return_value=public_url):
                window._fetch_models()
                wait_for(lambda: len(requests) == 2)
                if action == "cancel":
                    window._stop()
                elif action == "timeout":
                    window.client.timer.start(1)
                wait_for(lambda: not window._fetching)
            expected = {"malformed": "metadata is missing", "cancel": "stopped", "timeout": "timed out"}[action]
            self.assertIn(expected, window.models_status.text())
            self.assertIn("capability lookup failed", window.models_status.text())
            self.assertEqual(window.api_model.currentText(), "manual-model")
            self.assertFalse(window.client.timer.isActive())
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
        recognition_buttons = (window.run_button, window.retry_button, window.retry_all_button)
        self.assertTrue(all(not button.isEnabled() for button in recognition_buttons))
        for button, page, target in zip(window.current_page_buttons, (2, 3, 4),
                                        (window.toc_first, window.toc_last, window.body_pdf)):
            window.go_page(page)
            wait_for(lambda: not window.runner.busy)
            button.click()
            self.assertEqual(target.value(), page)
            self.assertEqual(window.session.current_page, page)
        self.assertEqual(window.session.toc, {})  # Marking still requires Mark TOC.
        self.assertTrue(all(not button.isEnabled() for button in recognition_buttons))
        self.assertEqual(window.session.body_pdf, 4)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(set(window.session.toc), {2, 3})
        self.assertTrue(all(button.isEnabled() for button in recognition_buttons))
        window.go_page(4)
        wait_for(lambda: not window.runner.busy)
        self.assertTrue(window.run_button.isEnabled())
        self.assertTrue(window.retry_all_button.isEnabled())
        self.assertFalse(window.retry_button.isEnabled())
        for page in (2, 3):
            window.go_page(page)
            wait_for(lambda: not window.runner.busy)
            self.assertTrue(window.retry_button.isEnabled())
            window._unmark_toc()
            self.assertFalse(window.retry_button.isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in recognition_buttons))

    def test_mark_toc_replaces_tasks_and_clears_stale_editor_and_context(self) -> None:
        window = self.window()
        session = window.session
        window.toc_first.setValue(1)
        window.toc_last.setValue(2)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        session.toc[1].angle = 15
        session.toc[1].requirements = "Old requirements"
        session.toc[1].crop = (.1, .2, .8, .9)
        session.toc[1].status = Status.ERROR
        session.toc[2].draft = "Old draft"
        session.conversation = [ConversationTurn(1, "Old prompt", b"image", "Old reply")]
        retained = Bookmark("Retained result", 3, source_page=1, logical_page=1)
        removed = Bookmark("Removed source result", 4, source_page=2, logical_page=2)
        session.bookmarks.extend([retained, removed])
        window.yaml.setPlainText("Stale editor text")
        window.draft_timer.start()
        window._active = 2  # A previous stopped recognition may retain its page.
        window.toc_last.setValue(1)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(session.toc, {1: TocPage(1)})
        self.assertEqual(session.conversation, [])
        self.assertEqual(window.yaml.toPlainText(), "")
        self.assertFalse(window.draft_timer.isActive())
        self.assertIsNone(window._active)
        self.assertEqual(retained.source_page, 1)
        self.assertIsNone(removed.source_page)
        self.assertIsNone(removed.logical_page)
        self.assertIn(removed, session.bookmarks)
        BookSession.from_data(session.to_data(), self.folder)
        # Even repeating the same interval must start with fresh tasks.
        session.toc[1].requirements = "Reset again"
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(session.toc[1], TocPage(1))
        bookmarks_before = [(item.id, item.title, item.page, item.level) for item in session.bookmarks]
        current_page = session.current_page
        self.assertTrue(window.clear_toc_button.isEnabled())
        window.clear_toc_button.click()
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(session.toc, {})
        self.assertEqual(session.current_page, current_page)
        self.assertEqual([(item.id, item.title, item.page, item.level) for item in session.bookmarks], bookmarks_before)
        self.assertTrue(all(item.source_page is None for item in session.bookmarks))
        self.assertFalse(window.clear_toc_button.isEnabled())
        self.assertFalse(window.run_button.isEnabled())
        self.assertFalse(window.page_toc_action.isChecked())
        self.assertEqual(window.yaml.toPlainText(), "")
        BookSession.from_data(session.to_data(), self.folder)

    def test_page_toc_checkbox_tracks_selection_and_preserves_other_tasks(self) -> None:
        window = self.window()
        session = window.session
        window.toc_first.setValue(1)
        window.toc_last.setValue(2)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        other = session.toc[2]
        other.requirements = "Keep this"
        window.pages.clearSelection()
        window.pages.topLevelItem(3).setSelected(True)
        self.assertTrue(window.page_toc_action.isEnabled())
        self.assertFalse(window.page_toc_action.isChecked())
        window.page_toc_action.trigger()
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(set(session.toc), {1, 2, 4})
        self.assertIs(session.toc[2], other)
        self.assertEqual(other.requirements, "Keep this")
        self.assertEqual(session.current_page, 1)  # Selected row, not displayed page.
        self.assertTrue(window.page_toc_action.isChecked())
        window.page_toc_action.trigger()
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(set(session.toc), {1, 2})
        self.assertFalse(window.page_toc_action.isChecked())
        window.pages.topLevelItem(4).setSelected(True)
        self.assertFalse(window.page_toc_action.isVisible())
        self.assertFalse(window.page_toc_action.isEnabled())
        window.pages.clearSelection()
        window.pages.topLevelItem(1).setSelected(True)
        self.assertTrue(window.page_toc_action.isChecked())
        window._running = True
        window._recognition_paused = True
        try:
            window._enabled()
            self.assertFalse(window.page_toc_action.isEnabled())
            self.assertFalse(window.clear_toc_button.isEnabled())
            window._clear_toc()
            window._toggle_selected_toc(False)
            window._mark_toc()
            self.assertIs(session.toc[2], other)
            self.assertTrue(window.page_toc_action.isChecked())
        finally:
            window._running = False
            window._recognition_paused = False
            window._enabled()

    def test_page_context_mapping_uses_single_selection_and_atomic_body_prompt(self) -> None:
        window = self.window()
        window.pages.clearSelection()
        self.assertTrue(all(not action.isVisible() for action in window.page_mapping_actions))
        window.pages.topLevelItem(2).setSelected(True)
        self.assertTrue(all(action.isVisible() and action.isEnabled() for action in window.page_mapping_actions))
        window.page_mapping_actions[0].trigger()
        self.assertEqual(window.toc_first.value(), 3)
        window.pages.clearSelection()
        window.pages.topLevelItem(4).setSelected(True)
        window.page_mapping_actions[1].trigger()
        self.assertEqual(window.toc_last.value(), 5)
        self.assertEqual(window.session.current_page, 1)
        self.assertFalse(window.session.toc)
        window.session.bookmarks.append(Bookmark("Derived", 2, logical_page=38))
        before = window.session.to_data()
        with patch.object(QtWidgets.QInputDialog, "getInt", return_value=(37, False)):
            window.page_mapping_actions[2].trigger()
        self.assertEqual(window.session.to_data(), before)
        self.assertEqual((window.body_pdf.value(), window.body_book.value()), (1, 1))
        with patch.object(QtWidgets.QInputDialog, "getInt", return_value=(37, True)) as prompt:
            window.page_mapping_actions[2].trigger()
        self.assertIn("Physical PDF page 5", prompt.call_args.args[2])
        self.assertEqual((window.session.body_pdf, window.session.body_book), (5, 37))
        self.assertEqual((window.body_pdf.value(), window.body_book.value()), (5, 37))
        self.assertEqual(window.session.bookmarks[-1].page, 6)
        window.pages.topLevelItem(3).setSelected(True)
        self.assertTrue(all(not action.isVisible() for action in window.page_mapping_actions))
        with patch.object(QtWidgets.QInputDialog, "getInt") as prompt:
            window._set_selected_page(window.body_pdf)
            prompt.assert_not_called()
        self.assertTrue(window.delete_pages_action.isEnabled())

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

    def test_recognition_warning_preserves_long_plain_text_and_copy(self) -> None:
        window = self.window()
        message = "TLS certificate failure <not HTML>\n" + "diagnostic line\n" * 250 + "FINAL CAUSE"

        def inspect(dialog: QtWidgets.QDialog) -> int:
            dialog.show()
            self.application.processEvents()
            details = dialog.findChild(QtWidgets.QPlainTextEdit)
            assert details is not None
            self.assertTrue(details.isReadOnly())
            self.assertEqual(details.toPlainText(), message)
            self.assertGreater(details.verticalScrollBar().maximum(), 0)
            buttons = dialog.findChild(QtWidgets.QDialogButtonBox)
            assert buttons is not None
            copy = next(button for button in buttons.buttons() if button.text() == "Copy error")
            copy.click()
            self.assertEqual(QtWidgets.QApplication.clipboard().text(), message)
            return QtWidgets.QDialog.DialogCode.Accepted

        with patch.object(QtWidgets.QDialog, "exec", inspect):
            self.real_warning(window, 25, "error", message)

    def test_problem_page_queue_trace_supplement_and_single_page_retry(self) -> None:
        problem = ('entries: []\nerrors:\n'
                   '  - {error_message: "Missing number", location: "Chapter Alpha, right edge", needs: "Provide printed page"}')
        gate = threading.Event()
        endpoint, requests = self.api_server(gate=gate, replies=[problem,
            'entries: [{page: 1, level: 1, title: "Alpha"}]\nerrors: []',
            'entries: [{page: 2, level: 1, title: "Beta"}]\nerrors: []'])
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
        wait_for(lambda: window._recognition_paused and not window.runner.busy)
        task = window.session.toc[1]
        self.assertEqual(task.status, Status.NEEDS_INFO)
        self.assertTrue(task.draft_invalid)
        self.assertEqual(task.raw_response, problem)
        self.assertEqual(window.session.toc[2].status, Status.PENDING)
        self.assertEqual([item.title for item in window.session.bookmarks], ["Original", "Child"])
        self.assertTrue(window.pages.topLevelItem(0).font(2).bold())
        self.assertEqual(window.progress_bar.value(), 0)
        self.assertEqual(window.progress_bar.maximum(), 2)
        self.assertTrue(window.progress_bar.isVisible())
        self.assertFalse(window._cursor_busy)
        self.warning.assert_called_once()
        self.assertIs(window.result_tabs.currentWidget(), window.information_tab)
        self.assertTrue(window.information_input.hasFocus())
        self.assertIn("Location: Chapter Alpha, right edge", window.information.toPlainText())
        self.assertIn("Problem: Missing number", window.information.toPlainText())
        self.assertIn("Needed: Provide printed page", window.information.toPlainText())
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName") as dialog:
            self.assertFalse(window._export())
            dialog.assert_not_called()
        self.assertIn("Chapter Alpha, right edge", window.trace.toPlainText())
        self.assertIn('"crop"', window.trace.toPlainText())
        self.assertNotIn("test-key", window.trace.toPlainText())
        self.assertNotIn("data:image", window.trace.toPlainText())
        window.supplement_button.click()
        window.information_input.setPlainText("Alpha has printed page 1.")
        window.requirement_scope.setCurrentIndex(1)
        self.assertEqual(window.requirements.toPlainText(), "Alpha has printed page 1.")
        self.assertEqual(window.session.requirements, "")
        self.assertEqual(len(requests), 1)
        window.information_retry.click()
        wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual(len(requests), 3)
        self.assertIn("Missing number", requests[1]["messages"][-1]["content"][0]["text"])
        self.assertIn("Alpha has printed page 1.", requests[1]["messages"][-1]["content"][0]["text"])
        self.assertIn("RETRY this page", requests[1]["messages"][-1]["content"][0]["text"])
        self.assertNotIn("Missing number", requests[2]["messages"][-1]["content"][0]["text"])
        self.assertEqual([item.title for item in window.session.bookmarks], ["Alpha", "Beta"])
        self.assertEqual(task.status, Status.DONE)
        self.assertFalse(task.draft_invalid)
        self.assertEqual(len(task.history), 2)
        self.assertEqual(window.progress_bar.value(), 2)
        self.assertFalse(window.progress_bar.isVisible())
        self.assertEqual(task.issues, [])
        self.assertEqual(task.error, "")
        self.assertEqual(len(window.session.toc[2].history), 1)
        self.assertNotIn("history", window.session.to_data()["toc"][0])
        self.assertNotIn("issues", window.session.to_data()["toc"][0])
        window.go_page(1)
        wait_for(lambda: not window.runner.busy)
        self.assertIn("Missing number", window.trace.toPlainText())
        self.assertEqual(window.information_input.toPlainText(), "Alpha has printed page 1.")
        self.assertNotIn("Missing number", window.information.toPlainText())

    def test_connection_pause_retries_current_page_and_keeps_successful_prefix(self) -> None:
        window = self.window()
        window.toc_last.setValue(3)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        window.api_url.setEditText("http://localhost:1234/v1")
        window.api_model.setCurrentText("test-model")
        requests: list[dict[str, object]] = []
        pages: list[int] = []

        def send(settings: LlmSettings, key: str, body: dict[str, object]) -> None:
            requests.append(body)
            page = window.session.current_page
            pages.append(page)
            failed = len(requests) in (2, 3)
            QtCore.QTimer.singleShot(0, lambda: window._client_completed(
                "" if failed else f'- {{page: {page}, level: 1, title: "Accepted {page}"}}',
                0 if failed else 10, "Connection error: peer closed" if failed else ""))

        with patch.object(window.client, "send", side_effect=send):
            window._run_all()
            wait_for(lambda: window._recognition_paused)
            first = window.session.bookmarks[0]
            self.assertEqual(first.title, "Accepted 1")
            self.assertEqual(window._queue, [2, 3])
            self.assertEqual(window.progress_bar.value(), 1)
            self.assertIn("Connection error: peer closed", window.information.toPlainText())
            self.assertTrue(window.pages.isEnabled())
            self.assertTrue(window.information_input.isEnabled())
            self.assertTrue(window.tabs.widget(1).isEnabled())  # API settings can be repaired.
            self.assertEqual([window.pages.topLevelItem(i).foreground(2).color().name() for i in range(3)],
                             ["#16803c", "#c02020", "#1769c2"])
            window.go_page(5)
            wait_for(lambda: not window.runner.busy)
            self.assertEqual(window.session.current_page, 5)
            self.assertFalse(window.information_input.isEnabled())
            self.assertEqual(window._queue, [2, 3])
            window.pause_button.click()
            wait_for(lambda: window._recognition_paused)
            self.assertEqual(pages, [1, 2, 2])
            self.assertEqual(window._queue, [2, 3])
            self.assertEqual(window.progress_bar.value(), 1)
            self.assertIs(window.session.bookmarks[0], first)
            self.assertEqual(self.warning.call_count, 2)
            window.clear_context.setChecked(True)  # Resuming must not start a fresh run.
            window.information_input.setPlainText("Latest clarification for page 2.")
            window.information_retry.click()
            wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual(pages, [1, 2, 2, 2, 3])
        self.assertIs(window.session.bookmarks[0], first)
        self.assertEqual(len(window.session.conversation), 5)
        self.assertIn("Latest clarification for page 2.", json.dumps(requests[3]))
        self.assertEqual(window.progress_bar.value(), 3)
        self.assertEqual(window.session.toc[2].error, "")
        self.assertIsNone(window._problem_page)

    def test_last_page_problem_can_resume_or_stop_without_automatic_retry(self) -> None:
        for stop in (False, True):
            with self.subTest(stop=stop):
                window = self.window()
                window._mark_toc()
                wait_for(lambda: not window.runner.busy)
                window.api_url.setEditText("http://localhost:1234/v1")
                window.api_model.setCurrentText("test-model")
                with patch.object(window.client, "send") as send:
                    window._run_all()
                    wait_for(lambda: send.call_count == 1)
                    window._client_completed("This is not a YAML TOC", 10, "")
                    self.assertTrue(window._recognition_paused)
                    self.assertEqual(window._queue, [1])
                    self.assertEqual(window.progress_bar.value(), 0)
                    self.assertIn("Expected a YAML list", window.information.toPlainText())
                    self.application.processEvents()
                    self.assertEqual(send.call_count, 1)
                    if stop:
                        window.stop_button.click()
                        window.information_retry.click()  # Explicit new single-page retry after Stop.
                    else:
                        window.pause_button.click()
                    wait_for(lambda: send.call_count == 2)
                    window._client_completed("[]", 10, "")
                    wait_for(lambda: not window._running)
                    self.assertEqual(window.session.toc[1].status, Status.DONE)
                    self.assertEqual(window.progress_bar.value(), 1)
                    self.assertIsNone(window._problem_page)

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

    def test_delete_nonconsecutive_pages_and_repeated_mapping(self) -> None:
        project = BookSession(self.source, 10, [str(page) for page in range(1, 11)], body_pdf=3)
        project.toc = {1: TocPage(1), 2: TocPage(2), 6: TocPage(6, angle=3, requirements="Keep crop")}
        project.bookmarks = [Bookmark("Deleted parent", 2), Bookmark("Child", 7, 2),
                             Bookmark("Grandchild", 10, 3), Bookmark("Later", 10),
                             Bookmark("Detached", 9, source_page=2, logical_page=7)]
        project.current_page = 6
        project.conversation.append(ConversationTurn(2, "old", b"image"))
        project.delete_pages([2, 5, 8], shift=True, delete_bookmarks=True)
        self.assertEqual(project.source_pages, [1, 3, 4, 6, 7, 9, 10])
        self.assertEqual([(item.title, item.page, item.level) for item in project.bookmarks],
                         [("Child", 5, 1), ("Grandchild", 7, 2), ("Later", 7, 1), ("Detached", 6, 1)])
        self.assertIsNone(project.bookmarks[-1].source_page)
        self.assertIsNone(project.bookmarks[-1].logical_page)
        self.assertEqual((project.current_page, project.body_pdf, project.body_book), (4, 2, 1))
        self.assertEqual(project.toc[4].requirements, "Keep crop")
        self.assertFalse(project.conversation)
        project.apply_draft(1, '- {page: 5, level: 1, title: "Printed five"}')
        self.assertEqual(project.bookmarks[-1].page, 5)
        before = project.to_data()
        with self.assertRaises(NeedsInformation):
            project.apply_draft(1, '- {page: 3, level: 1, title: "Deleted printed page"}')
        self.assertEqual(project.to_data(), before)
        project.delete_pages([2, 6], shift=True, delete_bookmarks=False)
        self.assertEqual(project.source_pages, [1, 4, 6, 7, 10])
        self.assertEqual((project.body_pdf, project.body_book), (2, 2))
        project.apply_draft(1, '- {page: 5, level: 1, title: "Printed five"}')
        self.assertEqual(project.bookmarks[-1].page, 4)
        restored = BookSession.from_data(project.to_data(), self.folder)
        self.assertEqual(restored.to_data(), project.to_data())

    def test_delete_keep_numeric_targets_and_first_page_fallback(self) -> None:
        project = self.project
        project.bookmarks = [Bookmark("First", 1), Bookmark("Deleted", 4),
                             Bookmark("Last", 6, source_page=2, logical_page=4)]
        project.delete_pages([1, 4], shift=False, delete_bookmarks=False)
        self.assertEqual([item.page for item in project.bookmarks], [1, 2, 6])
        self.assertTrue(all(item.logical_page is None for item in project.bookmarks))
        project.remap(project.body_pdf, project.body_book)
        self.assertEqual([item.page for item in project.bookmarks], [1, 2, 6])
        with self.assertRaises(ValueError):
            project.validate_export()
        before = project.to_data()
        for pages in ([], [0], [5], [True], [1, 2, 3, 4]):
            with self.assertRaises(ValueError):
                project.delete_pages(pages, shift=True, delete_bookmarks=True)
            self.assertEqual(project.to_data(), before)
        for source_pages in ([1, 1, 2, 3], [1, 3, 2, 4], [1, 2], [1, 2, 3, True], [1, 2, 3, 7]):
            with self.assertRaises(ValueError):
                BookSession.from_data({**before, "source_pages": source_pages}, self.folder)

    def test_delete_body_anchor_without_remaining_body_requires_mapping(self) -> None:
        self.project.delete_pages([3, 4, 5, 6], shift=True, delete_bookmarks=True)
        self.assertTrue(self.project.mapping_required)
        with self.assertRaises(ValueError):
            self.project.apply_draft(1, '- {page: 1, level: 1, title: "Unmapped"}')
        self.project.remap(2, 1)
        self.project.apply_draft(1, '- {page: 1, level: 1, title: "Mapped"}')
        self.assertEqual(self.project.bookmarks[0].page, 2)

    def test_delete_export_preserves_retained_content_and_remaps_links(self) -> None:
        source_bytes = self.source.read_bytes()
        with Pdf.open_document(self.source, interactive=False) as (original, _):
            pixels = [page.get_pixmap().samples for page in original]
            self.project.bookmarks = [Bookmark(item.title, item.page, item.level, original_xref=item.original_xref)
                                      for item in Pdf.read_bookmarks(original)]
        self.project.delete_pages([2, 4], shift=True, delete_bookmarks=False)
        output = self.folder / "deleted.pdf"
        export_project(self.project, output)
        with Pdf.open_document(output, interactive=False) as (result, _):
            self.assertEqual(result.page_count, 4)
            self.assertEqual([page.get_pixmap().samples for page in result], [pixels[index] for index in (0, 2, 4, 5)])
            self.assertEqual(result.get_toc(), [[1, "Original", 2], [2, "Child", 2]])
            self.assertTrue(result.get_toc(False)[0][3]["bold"])
            self.assertEqual(result.get_toc(False)[0][3]["color"], (1, 0, 0))
            self.assertEqual(result[0].get_links()[0]["page"], 2)
            self.assertEqual(next(result[0].annots()).info["content"], "Preserve annotation")
            self.assertEqual(result.embfile_get("note.txt"), b"preserve attachment")
            self.assertEqual(Pdf.read_page_labels(result), ["1", "3", "5", "6"])
        self.assertEqual(self.source.read_bytes(), source_bytes)

    def test_delete_gui_cancel_commit_preview_and_new_page_numbers(self) -> None:
        window = self.window()
        window.navigation.setCurrentIndex(1)
        window.pages.clearSelection()
        for index in (1, 4):
            window.pages.topLevelItem(index).setSelected(True)
        window._remember_outline()
        before = window.session.to_data()
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Cancel):
            window._delete_pages()
        self.assertEqual(window.session.to_data(), before)
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Yes):
            window.delete_pages_action.trigger()
        wait_for(lambda: not window.runner.busy and window._shown is not None)
        self.assertEqual(window.session.source_pages, [1, 3, 4, 6])
        self.assertEqual(window.pages.topLevelItemCount(), 4)
        self.assertFalse(window._undo)
        self.assertEqual(window.page_number.maximum(), 4)
        self.assertEqual(window.toc_last.maximum(), 4)
        window.go_page(2)
        wait_for(lambda: not window.runner.busy and window._shown == (2, 0))
        with Pdf.open_document(self.source, interactive=False) as (original, _):
            pixmap = Pdf.render_page(original[2], dpi=200, max_pixels=12_000_000)
        expected = QtGui.QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QtGui.QImage.Format.Format_RGB888)
        self.assertEqual(window.viewer._original.toImage().convertToFormat(QtGui.QImage.Format.Format_RGB888), expected)
        window.toc_first.setValue(2)
        window.toc_last.setValue(2)
        window._mark_toc()
        self.assertIn(2, window.session.toc)
        window._add_roots()
        self.assertEqual(window.session.bookmarks[1].page, 2)

    def test_delete_gui_bookmark_policy_and_cancel(self) -> None:
        window = self.window()
        window.pages.clearSelection()
        window.pages.topLevelItem(2).setSelected(True)
        before = window.session.to_data()
        # Closing the second policy dialog must leave the entire session intact.
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Yes), \
                patch.object(QtWidgets.QMessageBox, "exec", return_value=0):
            window._delete_pages()
        self.assertEqual(window.session.to_data(), before)

        def choose_delete(dialog: QtWidgets.QMessageBox) -> int:
            button = next(button for button in dialog.buttons() if button.text() == "Delete bookmarks")
            button.click()
            return 0

        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Yes), \
                patch.object(QtWidgets.QMessageBox, "exec", choose_delete):
            window._delete_pages()
        wait_for(lambda: not window.runner.busy and window._shown is not None)
        self.assertEqual(window.session.page_count, 5)
        self.assertEqual([(item.title, item.page, item.level) for item in window.session.bookmarks], [("Child", 3, 1)])

    def test_delete_shift_choice_exports_and_deleted_target_style(self) -> None:
        for shift in (False, True):
            with self.subTest(shift=shift):
                project = BookSession(self.source, 6, [str(page) for page in range(1, 7)])
                with Pdf.open_document(self.source, interactive=False) as (original, _):
                    project.bookmarks = [Bookmark(item.title, item.page, item.level, original_xref=item.original_xref)
                                         for item in Pdf.read_bookmarks(original)]
                project.delete_pages([2, 3, 5], shift=shift, delete_bookmarks=False)
                if not shift:
                    # The original child target 4 is intentionally now out of range.
                    self.assertEqual(project.bookmarks[1].page, 4)
                    with self.assertRaises(ValueError):
                        project.validate_export()
                    project.bookmarks[1].page = 3
                output = self.folder / f"shift-{shift}.pdf"
                export_project(project, output)
                with Pdf.open_document(output, interactive=False) as (result, _):
                    self.assertEqual(result.get_toc(), [[1, "Original", 1], [2, "Child", 2 if shift else 3]])
                    self.assertTrue(result.get_toc(False)[0][3]["bold"])
                    self.assertEqual(result.get_toc(False)[0][3]["color"], (1, 0, 0))
                    self.assertEqual(result[0].get_links(), [])

    def test_delete_then_recognize_uses_current_pages_and_printed_gaps(self) -> None:
        base, requests = self.api_server(replies=['- {page: 4, level: 1, title: "Printed four"}'])
        window = self.window()
        window.pages.clearSelection()
        for index in (1, 4):
            window.pages.topLevelItem(index).setSelected(True)
        window.body_pdf.setValue(3)
        window._mapping_changed()
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Yes):
            window._delete_pages()
        wait_for(lambda: not window.runner.busy and window._shown is not None)
        window.api_url.setEditText(base)
        window.api_model.setCurrentText("vision-test")
        window.api_key.setText("test-key")
        window.toc_first.setValue(2)
        window.toc_last.setValue(2)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy and window._shown == (2, 0))
        window._run_all()
        wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual(window.session.toc[2].status, Status.DONE)
        self.assertEqual(window.session.bookmarks[-1].page, 4)
        self.assertIn("Physical PDF page: 2", requests[0]["messages"][-1]["content"][0]["text"])
        window._label_generate()
        self.assertEqual(window.session.labels, ["1", "C1", "2", "4"])

    def test_delete_pages_ctrl_shift_selection_and_scoped_shortcut(self) -> None:
        window = self.window()
        window.navigation.setCurrentIndex(1)
        self.application.processEvents()
        tree = window.pages
        tree.clearSelection()
        for index in (1, 4):
            QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                   QtCore.Qt.KeyboardModifier.ControlModifier,
                                   tree.visualItemRect(tree.topLevelItem(index)).center())
        self.assertEqual(sorted(int(item.text(0)) for item in tree.selectedItems()), [2, 5])
        self.assertEqual(window.session.current_page, 1)
        QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.MouseButton.LeftButton,
                               QtCore.Qt.KeyboardModifier.ShiftModifier,
                               tree.visualItemRect(tree.topLevelItem(5)).center())
        self.assertEqual(sorted(int(item.text(0)) for item in tree.selectedItems()), [2, 5, 6])
        self.assertEqual(window.session.current_page, 1)
        tree.setFocus()
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Cancel) as ask:
            QtTest.QTest.keyClick(tree, QtCore.Qt.Key.Key_Delete)
            self.assertEqual(ask.call_count, 1)
            window._running = True
            window._delete_pages()
            self.assertEqual(ask.call_count, 1)
            window._running = False
        self.assertEqual(window.session.page_count, 6)

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

    def test_bookmark_level_column_tracks_hierarchy_without_changing_page_targets(self) -> None:
        window = self.window()
        self.assertEqual([window.tree.tree.headerItem().text(i) for i in range(3)], ["Bookmark", "Level", "Page"])
        editor = BookmarkEditor(editable=True, show_level=True)
        self.addCleanup(editor.deleteLater)
        editor.load([OutlineRow("a", "A", 5, 1), OutlineRow("b", "B", 8, 2), OutlineRow("c", "C", 11, 1)])
        child = editor.tree.topLevelItem(0).child(0)
        self.assertEqual([child.text(i) for i in range(3)], ["B", "2", "8"])
        received: list[int] = []
        editor.pageRequested.connect(received.append)
        editor._go_selected(child)
        self.assertEqual(received, [7])
        child.setText(editor.page_column, "9")
        self.assertEqual(editor.rows()[1].page, 9)
        delegate = editor.tree.itemDelegateForColumn(1)
        self.assertIsNone(delegate.createEditor(editor.tree, QtWidgets.QStyleOptionViewItem(),
                                               editor.tree.indexFromItem(child, 1)))
        editor.tree.setCurrentItem(editor.tree.topLevelItem(1))
        editor._indent()
        self.assertEqual(editor.tree.currentItem().text(1), "2")
        self.assertEqual(editor.tree.currentItem().text(editor.page_column), "11")
        editor._outdent()
        self.assertEqual(editor.tree.currentItem().text(1), "1")
        self.assertEqual([row.page for row in editor.rows()], [5, 9, 11])

    def test_pages_label_menu_edits_selection_and_routes_batch_to_tab(self) -> None:
        window = self.window()
        window.label_range.setText("6")
        window.pages.clearSelection()
        window.pages.topLevelItem(1).setSelected(True)
        before = list(window.session.labels)
        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("Intro", False)):
            window.edit_label_action.trigger()
        self.assertEqual(window.session.labels, before)
        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("Intro", True)):
            window.edit_label_action.trigger()
        self.assertEqual(window.session.labels[1], "Intro")
        self.assertEqual(window.pages.topLevelItem(1).text(1), "Intro")
        self.assertEqual(window.session.labels[5], before[5])

        window.pages.topLevelItem(3).setSelected(True)
        with patch.object(QtWidgets.QToolTip, "showText") as tooltip:
            window.edit_label_action.trigger()
        tooltip.assert_called_once()
        self.assertIs(window.tabs.currentWidget(), window.labels_tab)
        self.assertEqual(Input.parse_index_ranges(window.label_range.text(), item_count=6), (1, 3))
        self.assertEqual(window.session.labels[1], "Intro")
        window.label_range.setText("6")
        window._running = True
        window._enabled()
        self.assertFalse(window.clear_label_action.isEnabled())
        self.assertFalse(window.edit_label_action.isEnabled())
        window._page_labels(clear=True)
        self.assertEqual(window.session.labels[1], "Intro")
        window._running = False
        window._enabled()
        window.clear_label_action.trigger()
        self.assertEqual(window.session.labels, [before[0], "", before[2], "", before[4], before[5]])

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
        original_size = window.viewer._original.size()
        window.angle.setValue(2.5)
        window._rotation_changed()
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(window.viewer._crop, (0, 0, 1, 1))
        self.assertEqual(window.viewer._original.size(), original_size)

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
        self.assertIn("Recognized 2", json.dumps(requests[2]))
        self.assertIn("RETRY this page", requests[2]["messages"][-1]["content"][0]["text"])
        self.assertEqual(len(window.session.bookmarks), 2)
        self.assertEqual(window.session.last_prompt_tokens, 321)

    def test_recognition_first_click_commits_rotation_and_waits_for_preview(self) -> None:
        for button_name in ("run_button", "retry_button", "retry_all_button"):
            with self.subTest(button=button_name):
                window = self.window()
                window._mark_toc()
                wait_for(lambda: not window.runner.busy)
                window.api_url.setEditText("http://localhost:1234/v1")
                window.api_model.setCurrentText("test-vision")
                window.angle.setFocus()
                self.application.processEvents()
                window.angle.setValue(3)
                self.assertEqual(window.session.toc[1].angle, 0)
                with patch.object(window.client, "send") as send:
                    QtTest.QTest.mouseClick(getattr(window, button_name), QtCore.Qt.MouseButton.LeftButton)
                    wait_for(lambda: not window.runner.busy)
                    self.assertEqual(send.call_count, 1)
                    self.assertEqual(window.session.toc[1].angle, 3)
                    self.assertEqual(window._shown, (1, 3))
                window._stop()

    def test_retry_first_click_uses_committed_page_number(self) -> None:
        window = self.window()
        window.toc_last.setValue(2)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        window.api_url.setEditText("http://localhost:1234/v1")
        window.api_model.setCurrentText("test-vision")
        window.page_number.setFocus()
        self.application.processEvents()
        window.page_number.setValue(2)
        self.assertEqual(window.session.current_page, 1)
        with patch.object(window.client, "send") as send:
            QtTest.QTest.mouseClick(window.retry_button, QtCore.Qt.MouseButton.LeftButton)
            wait_for(lambda: not window.runner.busy)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(window._active, 2)
            self.assertEqual(window._shown, (2, 0))
            body = send.call_args.args[2]
            self.assertIn("Physical PDF page: 2", body["messages"][-1]["content"][0]["text"])
        window._stop()

    def test_stop_cancels_pending_recognition_and_repeated_clicks_do_not_queue(self) -> None:
        window = self.window()
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        window.angle.setFocus()
        self.application.processEvents()
        window.angle.setValue(4)
        with patch.object(window.client, "send") as send:
            QtTest.QTest.mouseClick(window.run_button, QtCore.Qt.MouseButton.LeftButton)
            self.assertTrue(window.runner.busy)
            pending = window._pending_recognition
            self.assertIsNotNone(pending)
            window._request_recognition(window._retry)
            self.assertIs(window._pending_recognition, pending)
            self.assertTrue(window.stop_button.isEnabled())
            QtTest.QTest.mouseClick(window.stop_button, QtCore.Qt.MouseButton.LeftButton)
            wait_for(lambda: not window.runner.busy)
            self.assertIsNone(window._pending_recognition)
            self.assertFalse(window._running)
            self.assertEqual(send.call_count, 0)
            self.assertTrue(window.run_button.isEnabled())

    def test_failed_preview_discards_pending_recognition(self) -> None:
        window = self.window()
        with patch.object(window, "_run_all") as run, patch.object(window, "_error") as error:
            window._pending_recognition = run
            window._purpose = "preview"
            window._completed({"kind": "error", "message": "Preview failed"})
            self.assertIsNone(window._pending_recognition)
            window._continue_recognition()
            run.assert_not_called()
            error.assert_called_once_with("Preview failed")
            self.assertFalse(window.run_button.isEnabled())  # No TOC pages were marked.

    def test_close_cancels_recognition_waiting_for_preview(self) -> None:
        window = self.window()
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        window.angle.setFocus()
        self.application.processEvents()
        window.angle.setValue(4)
        with patch.object(window.client, "send") as send, patch.object(window, "_discard", return_value=True):
            QtTest.QTest.mouseClick(window.run_button, QtCore.Qt.MouseButton.LeftButton)
            self.assertIsNotNone(window._pending_recognition)
            window.close()
            wait_for(lambda: not window.runner.busy and not window.isVisible())
            self.assertIsNone(window._pending_recognition)
            send.assert_not_called()

    def test_conversation_budget_retry_all_clear_and_local_no_key(self) -> None:
        endpoint, requests = self.api_server(replies=['- {page: 1, level: 1, title: "Reply"}'] * 8)
        window = self.window()
        window.toc_last.setValue(2)
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        window.api_url.setEditText(endpoint)
        window.api_model.setCurrentText("local-vision")
        window.api_key.clear()
        window.context_images.setValue(1)
        window._run_all()
        wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(window.session.conversation), 2)
        self.assertEqual([Llm.image_count(request["messages"]) for request in requests], [1, 1])
        self.assertNotIn("conversation", window.session.to_data())
        self.assertNotIn("data:image", json.dumps(window.session.to_data()))
        window.requirements.setPlainText("Keep all titles; correct the hierarchy.")
        window.context_images.setValue(0)
        window._retry_all()
        wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual([turn.page for turn in window.session.conversation], [1, 2, 1, 2])
        self.assertEqual([Llm.image_count(request["messages"]) for request in requests], [1, 1, 3, 4])
        self.assertIn("correct the hierarchy", requests[2]["messages"][-1]["content"][0]["text"])
        self.assertEqual([entry.source_page for entry in window.session.bookmarks], [1, 2])
        window.clear_context.setChecked(True)
        window._retry_all()
        wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual([turn.page for turn in window.session.conversation], [1, 2])
        self.assertEqual([len(request["messages"]) for request in requests[-2:]], [2, 4])
        self.assertEqual([Llm.image_count(request["messages"]) for request in requests[-2:]], [1, 2])
        self.assertEqual(len(window.session.bookmarks), 2)
        window.go_page(1)
        wait_for(lambda: not window.runner.busy)
        window._retry()
        wait_for(lambda: not window._running and not window.runner.busy)
        self.assertEqual([turn.page for turn in window.session.conversation], [1])
        self.assertEqual([entry.source_page for entry in window.session.bookmarks], [1, 2])

    def test_conversation_uses_old_responses_as_context_and_excludes_worker_payload(self) -> None:
        project = self.project
        project.conversation = [ConversationTurn(1, "Earlier prompt", b"jpeg", "Ambiguous response", "Missing number")]
        project.toc[2].draft = "Previous incorrect draft"
        project.toc[2].requirements = "The first printed page is 3."
        project.api.max_context_images = 1
        body = build_request(project, 2, b"current", retry=True)
        self.assertEqual(len(body["messages"]), 4)
        self.assertEqual(Llm.image_count(body["messages"]), 1)
        self.assertIn("Missing number", body["messages"][2]["content"])
        self.assertIn("Previous incorrect draft", body["messages"][-1]["content"][0]["text"])
        self.assertIn("The first printed page is 3", body["messages"][-1]["content"][0]["text"])
        data = project.to_data()
        self.assertNotIn("conversation", data)
        self.assertEqual(BookSession.from_data(data, self.folder).conversation, [])

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

    def test_api_keys_and_models_restore_per_source(self) -> None:
        window = self.window()
        source_a = "http://127.0.0.1:18001/v1"
        source_b = "http://127.0.0.1:18002/v1"
        window.api_url.setEditText(source_a)
        window.api_key.setText("source-a-secret")
        window.balance_key.setText("source-a-balance")
        window.api_model.setCurrentText("model-a")
        self.assertFalse(window.skip_certificate_verification.isChecked())
        window.skip_certificate_verification.setChecked(True)
        window.reasoning_effort.setCurrentIndex(window.reasoning_effort.findData("high"))
        window.api_url.setEditText(source_b)
        self.assertEqual(window.api_key.text(), "")
        window.api_key.setText("source-b-secret")
        window.api_model.setCurrentText("model-b")
        self.assertFalse(window.skip_certificate_verification.isChecked())
        window.reasoning_effort.setCurrentIndex(window.reasoning_effort.findData("default"))
        window.api_url.setEditText(source_a)
        self.assertEqual(window.api_key.text(), "source-a-secret")
        self.assertEqual(window.balance_key.text(), "source-a-balance")
        self.assertEqual(window.api_model.currentText(), "model-a")
        self.assertTrue(window.skip_certificate_verification.isChecked())
        self.assertEqual(window.reasoning_effort.currentData(), "high")
        self.assertFalse(ConfigStore("llm.yaml").path.exists())
        with ConfigStore._locked_path(ConfigStore("llm.yaml").path), patch.object(Llm, "load_profiles") as reader:
            window.api_url.setEditText(source_b)
            self.assertEqual(window.api_key.text(), "source-b-secret")
            window.api_url.setEditText(source_a)
            reader.assert_not_called()
        window.save_api_button.click()
        raw = ConfigStore("llm.yaml").path.read_text(encoding="utf-8")
        self.assertNotIn("source-a-secret", raw)
        self.assertNotIn("source-b-secret", raw)
        restored = self.window()
        self.assertEqual(restored.api_key.text(), "source-a-secret")
        self.assertTrue(restored.skip_certificate_verification.isChecked())
        self.assertEqual(restored.reasoning_effort.currentData(), "high")
        restored.api_url.setEditText(source_b)
        self.assertEqual(restored.api_key.text(), "source-b-secret")
        self.assertEqual(restored.api_model.currentText(), "model-b")
        self.assertFalse(restored.skip_certificate_verification.isChecked())
        self.assertEqual(restored.reasoning_effort.currentData(), "default")
        self.assertIn(source_b, [restored.api_url.itemData(index) for index in range(restored.api_url.count())])
        restored.api_url.setEditText(source_a + "/chat/completions")
        self.assertEqual(restored.api_key.text(), "source-a-secret")

    def test_reasoning_options_follow_provider_model_and_worker_session(self) -> None:
        window = self.window()
        window.api_url.setEditText("https://api.deepseek.com")
        self.assertEqual(window.reasoning_effort.currentData(), "auto")
        self.assertEqual([window.reasoning_effort.itemData(i) for i in range(window.reasoning_effort.count())],
                         ["auto", "default", "none", "low", "high", "max"])
        window.reasoning_effort.setCurrentIndex(window.reasoning_effort.findData("low"))
        restored = BookSession.from_data(window.session.to_data(), self.folder)
        self.assertEqual(restored.api.reasoning_effort.value, "low")
        window.api_url.setEditText("https://api.moonshot.ai/v1")
        window.api_model.setCurrentText("kimi-k3")
        self.assertEqual(window.reasoning_effort.findData("none"), -1)
        window.reasoning_effort.setCurrentIndex(window.reasoning_effort.findData("high"))
        window.api_model.setCurrentText("kimi-k2.6")
        self.assertIn("not supported", window.reasoning_effort.currentText())
        with self.assertRaisesRegex(ValueError, "not available"):
            Llm.chat_request(window._read_api(), [{"role": "user", "content": "test"}])
        window.reasoning_effort.setCurrentIndex(window.reasoning_effort.findData("default"))
        self.assertNotIn("thinking", Llm.chat_request(window._read_api(), [{"role": "user", "content": "test"}]))

    def test_api_manual_load_busy_feedback_and_close_save(self) -> None:
        window = self.window()
        window.api_url.setEditText("http://127.0.0.1:19999/v1")
        window.api_key.setText("saved-key")
        window.save_api_button.click()
        store = ConfigStore("llm.yaml")
        saved = store.path.read_bytes()
        window.api_key.setText("draft-key")
        window.api_key.editingFinished.emit()
        self.assertEqual(store.path.read_bytes(), saved)
        with ConfigStore._locked_path(store.path), patch.object(QtWidgets.QToolTip, "showText") as tooltip:
            window.load_api_button.click()
            self.assertEqual(window.api_key.text(), "draft-key")
            window.save_api_button.click()
            self.assertEqual(store.path.read_bytes(), saved)
            window.dirty = False
            event = QtGui.QCloseEvent()
            window.closeEvent(event)
            self.assertFalse(event.isAccepted())
            self.assertIn("busy", window.api_config_status.text())
            self.assertTrue(tooltip.called)
        window.load_api_button.click()
        self.assertEqual(window.api_key.text(), "saved-key")
        window.api_key.setText("close-key")
        window.dirty = False
        window.close()
        self.assertEqual(Llm.load_profiles().get_api(window._api_base()).api_key, "close-key")

    def test_pause_queue_retains_finished_page_and_resume_or_stop(self) -> None:
        for stop in (False, True):
            with self.subTest(stop=stop):
                gate = threading.Event()
                self.addCleanup(gate.set)
                endpoint, requests = self.api_server(gate=gate)
                window = self.window()
                self.assertIs(window.pause_button, window.task_buttons.pause_button)
                self.assertIs(window.stop_button, window.task_buttons.stop_button)
                self.assertFalse(window.left.isAncestorOf(window.pause_button))
                self.assertTrue(window.pause_button.isVisible())
                self.assertFalse(window.pause_button.isEnabled())
                window.toc_last.setValue(2)
                window._mark_toc()
                wait_for(lambda: not window.runner.busy)
                window.api_url.setEditText(endpoint)
                window.api_model.setCurrentText("test-model")
                window._run_all()
                wait_for(lambda: len(requests) == 1)
                window.pause_button.click()
                self.assertFalse(window._recognition_paused)
                self.assertTrue(window._cursor_busy)
                window.pause_button.click()  # Withdraw a pending pause without starting another request.
                self.assertFalse(window._queue_pause_requested)
                self.assertEqual(len(requests), 1)
                window.pause_button.click()
                gate.set()
                wait_for(lambda: window._recognition_paused)
                self.assertFalse(window._cursor_busy)
                self.assertTrue(window.progress_bar.isVisible())
                self.assertTrue(window.pause_button.isVisible())
                self.assertLess(window.progress_bar.mapTo(window, QtCore.QPoint()).x(),
                                window.pause_button.mapTo(window, QtCore.QPoint()).x())
                self.assertLess(abs(window.progress_bar.mapTo(window, QtCore.QPoint()).y()
                                    - window.pause_button.mapTo(window, QtCore.QPoint()).y()), 8)
                self.assertEqual((window.progress_bar.value(), window.progress_bar.maximum()), (1, 2))
                self.assertEqual(window.status.text(), "Paused")
                self.assertEqual(window.session.toc[1].status, Status.DONE)
                self.assertEqual(window.session.toc[2].status, Status.PENDING)
                QtTest.QTest.qWait(100)
                self.assertEqual(len(requests), 1)
                self.assertTrue(window.pages.isEnabled())
                self.assertTrue(window.tree.isEnabled())
                self.assertFalse(window.tree.toolbar.isEnabled())
                self.assertFalse(window.delete_pages_action.isEnabled())
                self.assertFalse(window.delete_pages_button.isEnabled())
                before = window.tree.rows()
                window.tree._add()
                window.tree._delete()
                self.assertEqual(window.tree.rows(), before)
                with patch.object(QtWidgets.QMessageBox, "question") as question:
                    window._delete_pages()
                    question.assert_not_called()
                window.go_page(5)
                if window.runner.busy:
                    queue = list(window._queue)
                    window._toggle_queue_pause()
                    self.assertTrue(window._recognition_paused)
                    self.assertEqual(window._queue, queue)
                wait_for(lambda: not window.runner.busy)
                self.assertEqual(window.session.current_page, 5)
                self.assertTrue(window.pages.isEnabled())
                self.assertTrue(window.viewer.navigation_enabled)
                window.navigation.setCurrentWidget(window.pages)
                window.pages.setFocus()
                QtTest.QTest.keyClick(window.pages, QtCore.Qt.Key.Key_Down)
                wait_for(lambda: not window.runner.busy)
                self.assertEqual(window.session.current_page, 6)
                target = window.tree.tree.topLevelItem(0)
                self.assertFalse(target.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
                menu = window.tree._make_context_menu(target)
                self.assertEqual([action.text() for action in menu.actions() if not action.isSeparator()],
                                 ["Expand all", "Collapse over level 3", "Go to bookmark"])
                next(action for action in menu.actions() if action.text() == "Go to bookmark").trigger()
                menu.deleteLater()
                wait_for(lambda: not window.runner.busy)
                self.assertEqual(window.session.current_page, before[0].page)
                self.assertEqual(len(requests), 1)
                (window.stop_button if stop else window.pause_button).click()
                wait_for(lambda: not window._running and not window.runner.busy)
                self.assertEqual(window.session.toc[1].status, Status.DONE)
                self.assertEqual(window.session.toc[2].status, Status.PENDING if stop else Status.DONE)
                self.assertEqual(len(requests), 1 if stop else 2)
                self.assertFalse(window._recognition_paused)
                self.assertTrue(window.run_button.isEnabled())
                self.assertTrue(window.tree.toolbar.isEnabled())
                self.assertFalse(window.progress_bar.isVisible())
                self.assertEqual(window.progress_bar.value(), 1 if stop else 2)

    def test_truncated_api_response_preserves_draft_without_applying(self) -> None:
        endpoint, _ = self.api_server(finish="length")
        window = self.window()
        window._mark_toc()
        wait_for(lambda: not window.runner.busy)
        before = list(window.session.bookmarks)
        window.api_url.setEditText(endpoint)
        window.api_model.setCurrentText("test-model")
        window._run_all()
        wait_for(lambda: window._recognition_paused and not window.runner.busy)
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

    def test_pages_keys_follow_preview_and_preserve_modifier_selection(self) -> None:
        window = self.window()
        window.navigation.setCurrentIndex(1)
        tree = window.pages
        self.assertEqual([item.text(0) for item in tree.selectedItems()], ["1"])
        window.go_page(3)
        wait_for(lambda: not window.runner.busy)
        self.assertEqual([item.text(0) for item in tree.selectedItems()], ["3"])
        tree.setFocus()
        self.application.processEvents()
        QtTest.QTest.keyClick(tree, QtCore.Qt.Key.Key_Down)
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(window.session.current_page, 4)
        self.assertEqual([item.text(0) for item in tree.selectedItems()], ["4"])
        self.assertTrue(tree.hasFocus())
        QtTest.QTest.keyClick(tree, QtCore.Qt.Key.Key_Up, QtCore.Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(window.session.current_page, 4)
        self.assertEqual(sorted(item.text(0) for item in tree.selectedItems()), ["3", "4"])
        QtTest.QTest.keyClick(tree, QtCore.Qt.Key.Key_Left)
        wait_for(lambda: not window.runner.busy)
        self.assertEqual(window.session.current_page, 3)
        self.assertEqual([item.text(0) for item in tree.selectedItems()], ["3"])
        window.go_page(1)
        wait_for(lambda: not window.runner.busy)
        QtTest.QTest.keyClick(tree, QtCore.Qt.Key.Key_Up)
        self.assertEqual(window.session.current_page, 1)
        self.assertEqual([item.text(0) for item in tree.selectedItems()], ["1"])
        tree.topLevelItem(2).setSelected(True)
        previous = window.session
        window.open_path(self.source)
        wait_for(lambda: window.session is not previous and not window.runner.busy)
        self.assertEqual([item.text(0) for item in tree.selectedItems()], ["1"])

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

    def test_set_level_handles_overlapping_selection_and_descendant_modes_atomically(self) -> None:
        rows = [OutlineRow(name, name, i + 10, level) for i, (name, level) in enumerate(
            (("A", 1), ("B", 2), ("B1", 3), ("C", 2), ("D", 1), ("D1", 2), ("E", 1)))]
        editor = BookmarkEditor(editable=True, show_level=True)
        self.addCleanup(editor.deleteLater)
        changes: list[list[OutlineRow]] = []
        editor.changed.connect(changes.append)
        for with_children, expected in ((True, [1, 1, 2, 2, 1, 2, 1]),
                                        (False, [1, 1, 1, 2, 1, 2, 1])):
            editor.load(rows)
            editor.tree.clearSelection()
            parent = editor.tree.topLevelItem(0).child(0)
            for item in (parent, parent.child(0), editor.tree.topLevelItem(1)):
                item.setSelected(True)
            previous = len(changes)
            self.assertTrue(editor._set_selected_levels(1, with_children))
            self.assertEqual(len(changes), previous + 1)
            result = editor.rows()
            self.assertEqual([row.level for row in result], expected)
            self.assertEqual([(row.id, row.page) for row in result], [(row.id, row.page) for row in rows])
        editor.load(rows)
        editor.tree.clearSelection()
        editor.tree.setCurrentItem(editor.tree.topLevelItem(0).child(0))
        previous = len(changes)
        with patch.object(editor, "_reject") as rejected:
            self.assertFalse(editor._set_selected_levels(1, False))  # Leaves B1 at level 3.
            rejected.assert_called_once()
        self.assertEqual(editor.rows(), rows)
        self.assertEqual(len(changes), previous)
        self.assertFalse(editor._set_selected_levels(2, True))  # Unchanged.
        self.assertEqual(len(changes), previous)

    def test_delete_bookmarks_promotes_children_batches_and_cancels_atomically(self) -> None:
        rows = [OutlineRow(name, name, index + 1, level) for index, (name, level) in enumerate(
            (("A", 1), ("B", 2), ("C", 3), ("D", 1), ("E", 2), ("F", 1)))]
        editor = BookmarkEditor(editable=True, show_level=True)
        self.addCleanup(editor.deleteLater)
        changes: list[list[OutlineRow]] = []
        editor.changed.connect(changes.append)
        for decisions, expected, calls in (
                ([_DeletionChoice(promote_children=True, apply_to_all=True)], [("C", 1), ("E", 1), ("F", 1)], 1),
                ([_DeletionChoice(include_descendants=True, apply_to_all=True)], [("F", 1)], 1),
                ([_DeletionChoice(promote_children=True), _DeletionChoice(include_descendants=True),
                  _DeletionChoice(promote_children=True)], [("E", 1), ("F", 1)], 3),
                ([_DeletionChoice(promote_children=True), None], [(row.id, row.level) for row in rows], 2)):
            editor.load(rows)
            editor.tree.clearSelection()
            first = editor.tree.topLevelItem(0)
            for item in (first, first.child(0), editor.tree.topLevelItem(1)):
                item.setSelected(True)
            previous = len(changes)
            with patch.object(editor, "_confirm_bookmark_deletion", side_effect=decisions) as ask:
                editor._delete()
            self.assertEqual(ask.call_count, calls)
            self.assertEqual([(row.id, row.level) for row in editor.rows()], expected)
            self.assertEqual(len(changes), previous + (0 if decisions[-1] is None else 1))

    def test_delete_keeps_levels_by_default_and_rejects_missing_parents(self) -> None:
        rows = [OutlineRow(name, name, index + 1, level) for index, (name, level) in enumerate(
            (("Root", 1), ("Prior", 2), ("A", 2), ("B", 3), ("C", 4), ("D", 2), ("E", 3), ("Tail", 1)))]
        editor = BookmarkEditor(editable=True, show_level=True)
        self.addCleanup(editor.deleteLater)
        editor.load(rows)
        parent = editor.tree.topLevelItem(0)
        for item in (parent.child(1), parent.child(2)):
            item.setSelected(True)
        menu = editor._make_context_menu(parent.child(1))
        self.addCleanup(menu.deleteLater)
        for action in menu.actions():
            if action.text() in ("Rename", "Edit target page"):
                self.assertFalse(action.isEnabled())
        self.assertEqual(editor.tree.editTriggers(), QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        with patch.object(editor, "_confirm_bookmark_deletion", return_value=_DeletionChoice(apply_to_all=True)) as ask:
            editor._delete()
        ask.assert_called_once()
        self.assertEqual([(row.id, row.level) for row in editor.rows()],
                         [(row.id, row.level) for row in rows if row.id not in ("A", "D")])
        self.assertEqual(editor.tree.topLevelItem(0).child(0).child(0).text(0), "B")
        remaining = editor.rows()
        editor.tree.setCurrentItem(editor.tree.topLevelItem(0))
        self.assertNotEqual(editor.tree.editTriggers(), QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        with patch.object(editor, "_confirm_bookmark_deletion", return_value=_DeletionChoice()), \
                patch.object(editor, "_reject") as rejected:
            editor._delete()
        rejected.assert_called_once()
        self.assertEqual(editor.rows(), remaining)
        with patch.object(QtWidgets.QDialog, "exec", return_value=QtWidgets.QDialog.DialogCode.Accepted):
            self.assertEqual(editor._confirm_bookmark_deletion(rows[0], True), _DeletionChoice())
        with patch.object(QtWidgets.QDialog, "exec", return_value=QtWidgets.QDialog.DialogCode.Rejected):
            self.assertIsNone(editor._confirm_bookmark_deletion(rows[0], True))

    def test_bookmark_delete_dialog_tooltips_and_undo(self) -> None:
        window = self.window()
        editor = window.tree
        before = editor.rows()
        parent = editor.tree.topLevelItem(0)
        editor.tree.setCurrentItem(parent)
        menu = editor._make_context_menu(parent)
        self.addCleanup(menu.deleteLater)
        action = next(action for action in menu.actions() if action.text() == "Delete bookmark")

        def choose(dialog: QtWidgets.QDialog) -> int:
            checks = dialog.findChildren(QtWidgets.QCheckBox)
            self.assertFalse(checks)
            radios = dialog.findChildren(QtWidgets.QRadioButton)
            self.assertEqual(len(radios), 3)
            self.assertTrue(radios[0].isChecked())
            radios[1].click()
            self.assertEqual([radio.isChecked() for radio in radios], [False, True, False])
            return QtWidgets.QDialog.DialogCode.Accepted

        with patch.object(QtWidgets.QDialog, "exec", choose):
            action.trigger()
        self.assertEqual(len(window.session.bookmarks), len(before) - 1)
        self.assertEqual(editor.rows()[0].level, 1)
        window._undo_bookmarks()
        self.assertEqual(editor.rows(), before)
        child = editor.tree.topLevelItem(0).child(0)
        child.setText(0, "Complete updated title")
        child.setText(editor.page_column, "5")
        for column in range(editor.tree.columnCount()):
            self.assertEqual(child.toolTip(column), "Title: Complete updated title\nPage: 5\nLevel: 2")
        editor.tree.setCurrentItem(child)
        editor._outdent()
        self.assertEqual(editor.tree.currentItem().toolTip(0), "Title: Complete updated title\nPage: 5\nLevel: 1")

        def choose_all(dialog: QtWidgets.QDialog) -> int:
            checkbox = next(check for check in dialog.findChildren(QtWidgets.QCheckBox) if check.text() == "Apply to all")
            checkbox.setChecked(True)
            next(button for button in dialog.findChildren(QtWidgets.QRadioButton) if button.text() == "Include descendants").click()
            return QtWidgets.QDialog.DialogCode.Accepted

        with patch.object(QtWidgets.QDialog, "exec", choose_all):
            self.assertEqual(editor._confirm_bookmark_deletion(before[0], True),
                             _DeletionChoice(include_descendants=True, apply_to_all=True))

    def test_set_level_dialog_menu_cancel_and_undo(self) -> None:
        window = self.window()
        editor = window.tree
        before = editor.rows()
        child = editor.tree.topLevelItem(0).child(0)
        editor.tree.setCurrentItem(child)
        menu = editor._make_context_menu(child)
        self.addCleanup(menu.deleteLater)
        action = next(action for action in menu.actions() if action.text() == "Set level...")
        with patch.object(QtWidgets.QDialog, "exec", return_value=QtWidgets.QDialog.DialogCode.Rejected):
            action.trigger()
        self.assertEqual(editor.rows(), before)

        def choose(dialog: QtWidgets.QDialog) -> int:
            spin = dialog.findChild(QtWidgets.QSpinBox)
            checkbox = dialog.findChild(QtWidgets.QCheckBox)
            assert spin is not None and checkbox is not None
            self.assertEqual(spin.value(), 2)
            self.assertTrue(checkbox.isChecked())
            spin.setValue(1)
            return QtWidgets.QDialog.DialogCode.Accepted

        with patch.object(QtWidgets.QDialog, "exec", choose):
            action.trigger()
        self.assertEqual([item.level for item in window.session.bookmarks], [1, 1])
        self.assertEqual(editor.tree.topLevelItem(1).text(1), "1")
        window._undo_bookmarks()
        self.assertEqual(editor.rows(), before)

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
            self.assertEqual(requests[0]["max_tokens"], window.max_tokens.value())
            self.assertEqual(requests[0]["reasoning_effort"], "medium")
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
                patch.object(QtWidgets.QMessageBox, "exec", return_value=0), \
                patch.object(window, "_error") as error:
            window.close()
            wait_for(lambda: not window.runner.busy)
            error.assert_not_called()
        self.assertTrue(window.isVisible())
        self.assertTrue(window.dirty)
        self.assertFalse(window.session.bookmarks)
        self.assertIsNone(window._after_export)
        self.assertEqual(target.read_bytes(), b"Existing content")

    def test_close_pdf_resets_session_releases_file_and_reopens(self) -> None:
        window = self.window()
        window.api_key.setText("unsaved-test-key")
        window.dirty = False
        window._close_pdf()
        self.application.processEvents()
        self.assertTrue(window.isVisible())
        self.assertIsNone(window.session)
        self.assertEqual(window.api_key.text(), "unsaved-test-key")
        self.assertFalse(ConfigStore("llm.yaml").path.exists())
        self.assertFalse(window.close_pdf_button.isEnabled())
        moved = self.folder / "moved.pdf"
        self.source.rename(moved)
        window.open_path(moved)
        wait_for(lambda: window.session is not None and window._shown is not None and not window.runner.busy)
        self.assertEqual(window.session.source, moved)

    def test_export_overwrite_shows_completion(self) -> None:
        window = self.window()
        target = self.folder / "existing.pdf"
        target.write_bytes(b"Old output")
        with patch("personal_pdf_tools.bookmarks.app.choose_pdf_output", return_value=(target, True)):
            window._export()
        wait_for(lambda: not window.runner.busy)
        self.assertIn(str(target), self.notice.call_args.args[2])
        with pymupdf.open(target) as document:
            self.assertEqual(document.page_count, 6)


if __name__ == "__main__":
    unittest.main()
