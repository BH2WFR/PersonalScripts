"""Batch input, OCR subprocess and language availability checks."""

import json
import pymupdf
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from test_pdf_ocr_gui import QtCore, QtGui, QtWidgets, ROOT, wait_for
from personal_pdf_tools.ocr.image_app import ImageWindow
from personal_pdf_tools.ocr.model import Settings
from personal_pdf_tools.ocr.panel import SettingsPanel


class ImageOcrTests(unittest.TestCase):
    def test_cold_start_uses_only_pyside(self) -> None:
        # The other GUI tests preload PySide6 and cannot reproduce binding-order failures.
        script = """
import importlib
import sys
app = importlib.import_module("pdf-ocr").load_app("ocr.image_app")
from PySide6 import QtCore, QtWidgets
application = QtWidgets.QApplication([])
assert not any(name.startswith("PyQt6.") for name in sys.modules)
"""
        subprocess.run([sys.executable, "-c", script], cwd=ROOT / "tools/document-processing",
                       check=True, timeout=30)

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_missing_language_fallback_and_refresh(self) -> None:
        with patch("personal_pdf_tools.ocr.panel.inventory", return_value=[]) as inventory:
            panel = SettingsPanel(Settings(languages=("korean",)))
            korean = panel.language_list.item(3)
            self.assertFalse(korean.flags() & QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.assertIn("separately", korean.text())
            self.assertEqual(panel.selected_languages(), ("chinese", "english"))
            inventory.return_value = [{"key": "korean", "size": 100}]
            panel.refresh_languages()
            self.assertTrue(korean.flags() & QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.assertEqual(korean.text(), "Korean")
            panel.deleteLater()

    def test_drop_clipboard_and_batch_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("personal_pdf_tools.ocr.image_app.read_preferences", return_value={}):
            window = ImageWindow(ROOT / "tools/document-processing/image-to-text-and-formula.py")
            try:
                with pymupdf.open() as fixture:
                    page = fixture.new_page(width=480, height=100)
                    page.insert_text((20, 65), "Sample image", fontsize=32)
                    image = QtGui.QImage.fromData(page.get_pixmap().tobytes("png"))
                files = [Path(directory) / f"sample-{i}.png" for i in (1, 2)]
                for path in files:
                    self.assertTrue(image.save(str(path)))
                mime = QtCore.QMimeData()
                mime.setUrls([QtCore.QUrl.fromLocalFile(str(path)) for path in files])
                event = QtGui.QDropEvent(QtCore.QPointF(), QtCore.Qt.DropAction.CopyAction, mime,
                    QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
                self.assertTrue(window.drop_filter.eventFilter(window.list.viewport(), event))
                with patch.object(QtWidgets.QApplication, "clipboard") as clipboard:
                    clipboard.return_value.image.return_value = image
                    window._paste()
                self.assertEqual(len(window.rows), 3)
                self.assertIs(window.tabs.currentWidget(), window.viewer)
                self.assertEqual(window.list.topLevelItem(0).text(1), "480 × 100")
                self.assertTrue(window.list.topLevelItem(0).text(2))
                window.tabs.setCurrentWidget(window.viewer)
                window.run_button.click()
                wait_for(lambda: not window.runner.busy, timeout=60)
                self.assertEqual(len(window.results), 3, window.status.text())
                self.assertIs(window.tabs.currentWidget(), window.text)
                self.assertEqual(window.text.toPlainText(), window._all_text())
                self.assertEqual(window._all_text().lower().count("sample"), 3, window.results)
                with patch("personal_pdf_tools.ocr.image_app.choose_save_file", return_value=str(Path(directory) / "out.txt")):
                    window._save()
                self.assertEqual((Path(directory) / "out.txt").read_text(encoding="utf-8"), window._all_text())
                window.current_button.click()
                wait_for(lambda: not window.runner.busy)
                self.assertEqual(len(window.results), 1)
                self.assertEqual(window.text.toPlainText().lower().count("sample"), 1)
            finally:
                wait_for(lambda: not window.runner.busy)
                window.close()
                window.deleteLater()

    def test_formula_request_and_empty_result(self) -> None:
        from test_pdf_bookmarks_gui import BookmarksTests, wait_for as wait_for_api
        server = BookmarksTests()
        self.addCleanup(server.doCleanups)
        endpoint, requests = server.api_server(replies=[r"Vector: $$\textcolor{red}{\mathbf{x}}$$",
                                                       r"\frac{a}{b}", "[NO_TEXT]", '["first image","second image"]'])
        with tempfile.TemporaryDirectory() as folder, patch("utils.config.ConfigStore.directory", return_value=Path(folder)):
            window = ImageWindow(ROOT / "tools/document-processing/image-to-text-and-formula.py")
            try:
                path = Path(folder) / "equation.png"
                image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_RGB32)
                image.fill(QtGui.QColor("white"))
                image.save(str(path))
                window.add_file(path)
                window.mode.setCurrentIndex(2)
                panel = window.vision_options
                self.assertIs(window.api_tabs.currentWidget(), panel)
                self.assertIs(panel.currentWidget(), panel.formula_page)
                window.api_tabs.setCurrentWidget(window.api_form)
                window.api_url.setEditText(endpoint)
                window.api_model.setEditText("vision-test")
                window.api_tabs.setCurrentWidget(panel)
                formula = panel.formula_page
                formula.content.setCurrentIndex(formula.content.findData("mixed"))
                formula.delimiter.setCurrentIndex(formula.delimiter.findData("brackets"))
                formula.custom.setPlainText("保留公式编号\nKeep equation tags.")
                with patch.object(QtWidgets.QMessageBox, "information") as notice:
                    window.current_button.click()
                    wait_for_api(lambda: not window._running and not window.runner.busy, timeout=45)
                    self.assertEqual(window.text.toPlainText(), "Vector: " + "\\\u005b\n" + r"\textcolor{red}{\mathbf{x}}" + "\n\\]")
                    self.assertTrue(requests[0]["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
                    prompt = requests[0]["messages"][-1]["content"][0]["text"]
                    self.assertIn("all surrounding prose", prompt)
                    self.assertIn("保留公式编号\nKeep equation tags.", prompt)
                    self.assertIn(r"\[ and \]", prompt)
                    self.assertIs(window.tabs.currentWidget(), window.text)
                    formula.content.setCurrentIndex(formula.content.findData("formula"))
                    formula.features["Colors"].setChecked(False)
                    window.current_button.click()
                    wait_for_api(lambda: not window._running and not window.runner.busy)
                    self.assertEqual(window.text.toPlainText(), "\\[\n" + r"\frac{a}{b}" + "\n\\]")
                    prompt = requests[1]["messages"][-1]["content"][0]["text"]
                    self.assertIn("only the equations", prompt)
                    self.assertIn("Omit colors", prompt)
                    self.assertEqual(requests[1]["messages"][-2]["role"], "assistant")
                    window.current_button.click()
                    wait_for_api(lambda: not window._running and not window.runner.busy)
                    notice.assert_called_once()
                    self.assertEqual(window.text.toPlainText(), "")
                    second = Path(folder) / "another.png"
                    image.save(str(second))
                    window.add_file(second)
                    window.mode.setCurrentIndex(1)
                    self.assertIs(panel.currentWidget(), panel.text_page)
                    text_page = panel.text_page
                    text_page.layout_choice.setCurrentIndex(text_page.layout_choice.findData("columns"))
                    text_page.keep_lines.setChecked(False)
                    text_page.custom.setPlainText("Preserve footnote numbers.")
                    window.run_button.click()
                    self.assertFalse(panel.isEnabled())
                    wait_for_api(lambda: not window._running and not window.runner.busy)
                    self.assertEqual(window.text.toPlainText(), "first image\n\nsecond image")
                    window.show()
                    log = window.api_log
                    window.tabs.setCurrentWidget(log)
                    self.assertEqual(log.images.count(), 1)
                    self.assertIn("another.png", log.images.currentText())
                    log.images.setCurrentIndex(0)
                    self.assertIn("base64 characters", log.body.toPlainText())
                    self.assertIn("POST " + endpoint, log.status.text())
                    with patch.object(QtWidgets.QApplication, "clipboard") as clipboard:
                        log.copy.click()
                        raw = clipboard.return_value.setText.call_args.args[0]
                        self.assertEqual(json.loads(raw), requests[-1])
                    log.direction.setCurrentIndex(1)
                    self.assertIn("HTTP 200", log.status.text())
                    response = json.loads(log.body.toPlainText())
                    self.assertEqual(json.loads(response["choices"][0]["message"]["content"]), ["first image","second image"])
                    self.assertEqual(response["usage"]["prompt_tokens"], 321)
                    self.assertEqual(len(requests[-1]["messages"]), 2)
                    prompt = requests[-1]["messages"][-1]["content"][0]["text"]
                    self.assertIn("each column", prompt)
                    self.assertIn("Join lines", prompt)
                    self.assertIn("Preserve footnote numbers.", prompt)
                    self.assertNotIn("Keep equation tags.", prompt)
                    window.mode.setCurrentIndex(2)
                    self.assertEqual(formula.custom.toPlainText(), "保留公式编号\nKeep equation tags.")
                    saved = panel.to_data()
                    rejected, other_requests = server.api_server(status=401)
                    window.api_url.setEditText(rejected)
                    window.api_model.setEditText("vision-test")
                    window.api_key.setText("test-key")
                    window.current_button.click()
                    wait_for_api(lambda: not window._running and not window.runner.busy)
                    window.tabs.setCurrentWidget(log)
                    self.assertEqual(log.images.count(), 1)
                    self.assertIn("HTTP 401", log.status.text())
                    self.assertIn("[redacted]", log.body.toPlainText())
                    self.assertNotIn("test-key", log.body.toPlainText())
                    self.assertEqual(len(other_requests[0]["messages"]), 2)
            finally:
                window.close()
                window.deleteLater()
            reopened = ImageWindow(ROOT / "tools/document-processing/image-to-text-and-formula.py")
            try:
                self.assertEqual(reopened.vision_options.to_data(), saved)
            finally:
                reopened.close()
                reopened.deleteLater()

    def test_context_cap_reset_and_document_export(self) -> None:
        from test_pdf_bookmarks_gui import BookmarksTests, wait_for as wait_for_api
        from utils import Llm
        server = BookmarksTests()
        self.addCleanup(server.doCleanups)
        fragments = [f"Page {n} with $x$." for n in range(7)]
        endpoint, requests = server.api_server(replies=[
            json.dumps(fragments[:5]), json.dumps(fragments[5:]), "single", "again", "fresh", "independent",
            "markdown", "fragment", json.dumps(fragments), "next"])
        with tempfile.TemporaryDirectory() as folder, patch("utils.config.ConfigStore.directory", return_value=Path(folder)):
            window = ImageWindow(ROOT / "tools/document-processing/image-to-text-and-formula.py")
            try:
                page = window.vision_options.formula_page
                window.mode.setCurrentIndex(2)
                page.output.setCurrentIndex(page.output.findData("document"))
                window.api_url.setEditText(endpoint)
                window.api_model.setEditText("vision-test")
                for n in range(7):
                    img = QtGui.QImage(16, 16, QtGui.QImage.Format.Format_RGB32)
                    img.fill(QtGui.QColor(30*n, 0, 0))
                    path = Path(folder) / f"{n}.png"
                    img.save(str(path))
                    window.add_file(path)
                def finish() -> None:
                    wait_for_api(lambda: not window._running and not window.runner.busy, timeout=45)
                window.run_button.click()
                finish()
                if window.rendered is not None:
                    self.assertFalse(window.tabs.isTabVisible(window.tabs.indexOf(window.rendered)))
                self.assertEqual(len(requests), 2)
                a, b = (req["messages"] for req in requests)
                self.assertEqual([Llm.image_count(m) for m in (a, b)], [5, 5])
                self.assertEqual(b[1]["content"][-3:], a[1]["content"][-3:])
                self.assertEqual(b[-2]["content"], json.dumps(fragments[:5]))
                self.assertEqual(Llm.image_count(b[-1:]), 2)
                self.assertIn("isolated single Latin or Greek letter", b[-1]["content"][0]["text"])
                source = window.text.toPlainText()
                self.assertEqual(source.count(r"\documentclass"), 1)
                self.assertEqual(source.count(r"\end{document}"), 1)
                self.assertEqual(source.count(r"\(x\)"), 7)
                self.assertEqual(list(window.results.values()), [s.replace("$x$", r"\(x\)") for s in fragments])
                out = Path(folder) / "book.tex"
                with patch("personal_pdf_tools.ocr.image_app.choose_save_file", return_value=str(out)) as chooser:
                    window._save()
                    self.assertEqual(chooser.call_args.args[2].suffix, ".tex")
                self.assertEqual(out.read_text(encoding="utf-8"), source)
                window.current_button.click()
                finish()
                self.assertEqual(len(requests[-1]["messages"]), 6)
                self.assertEqual(Llm.image_count(requests[-1]["messages"]), 5)
                page.clear.click()
                window.current_button.click()
                finish()
                self.assertEqual(len(requests[-1]["messages"]), 2)
                page.reset_each.setChecked(True)
                for _ in range(2):
                    window.current_button.click()
                    finish()
                    self.assertEqual(len(requests[-1]["messages"]), 2)
                self.assertFalse(page.clear.isEnabled())
                for format_name in ("markdown", "fragment"):
                    page.output.setCurrentIndex(page.output.findData(format_name))
                    window.current_button.click()
                    finish()
                    if window.rendered is not None:
                        self.assertTrue(window.tabs.isTabVisible(window.tabs.indexOf(window.rendered)))
                    self.assertNotIn(r"\documentclass", window.text.toPlainText())
                page.reset_each.setChecked(False)
                window.context_images.setValue(0)
                before = len(requests)
                window.run_button.click()
                finish()
                self.assertEqual(len(requests), before + 1)
                unlimited = requests[-1]["messages"]
                self.assertEqual(Llm.image_count(unlimited), len(fragments))
                window.current_button.click()
                finish()
                self.assertEqual(len(requests), before + 2)
                next_turn = requests[-1]["messages"]
                self.assertEqual(next_turn[:-2], unlimited)
                self.assertEqual(next_turn[-2]["content"], json.dumps(fragments))
                self.assertEqual(Llm.image_count(next_turn), len(fragments) + 1)
            finally:
                window.close()
                window.deleteLater()

    def test_document_formatting_and_batch_alignment(self) -> None:
        from personal_pdf_tools.ocr.vision import VisionTask, batch_results, transcription
        task = VisionTask("markdown", features=("Tables",), inline_parens=True, multiline="group", numbers=False)
        prompt = task.prompt(1)
        for instruction in ("Preserve tables", "Omit bold prose", "Preserve mathematical bold", "Omit displayed equation numbers",
                            "one display block with aligned rows", r"其中 \(x\) 为半径"):
            self.assertIn(instruction, prompt)
        fence = chr(96) * 3
        code = f"{fence}\n$x$ example\n{fence}"
        self.assertEqual(transcription(code, task), code)
        self.assertEqual(transcription("变量 $x$。\n" + code, task), "变量 " + r"\(x\)。" + "\n" + code)
        for bad in ('["only one"]', '["one", {}]', 'unstructured text'):
            with self.assertRaises(ValueError):
                batch_results(bad, 2, task)

    def test_offline_formula_controls(self) -> None:
        from personal_pdf_tools.ocr import local_formula
        from personal_pdf_tools.ocr.worker import Worker
        with tempfile.TemporaryDirectory() as folder, patch("utils.config.ConfigStore.directory", return_value=Path(folder)):
            window = ImageWindow(ROOT / "tools/document-processing/image-to-text-and-formula.py")
            self.addCleanup(window.close)
            image = QtGui.QImage(10, 10, QtGui.QImage.Format.Format_RGB32)
            image.fill(QtGui.QColor("white"))
            path = Path(folder) / "blank.png"
            image.save(str(path))
            window.add_file(path)
            with patch.object(local_formula, "runtime_hint", return_value="Install paddlepaddle"), \
                    patch.object(QtWidgets.QMessageBox, "warning") as warning:
                window.mode.setCurrentIndex(3)
                warning.assert_called_once()
                self.assertTrue(window.formula_install.isEnabled())
                self.assertFalse(window.current_button.isEnabled())
            worker = Worker()
            self.addCleanup(worker.close)

            def submit(request: dict) -> bool:
                window._completed(worker.run(request))
                return True

            def download(asset, _control) -> None:
                target = local_formula.models.model_path(asset)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"x")

            with patch.object(local_formula, "runtime_hint", return_value=""), \
                    patch.object(local_formula, "FILES", {"config.json": (1, "0" * 64)}), \
                    patch.object(local_formula.models, "download", side_effect=download), \
                    patch.object(window.runner, "start", side_effect=submit), \
                    patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.Yes):
                window.mode.setCurrentIndex(0)
                window.mode.setCurrentIndex(3)
                self.assertFalse(window.run_button.isEnabled())
                window.formula_install.click()
                self.assertTrue(window.run_button.isEnabled())
                self.assertTrue(window.current_button.isEnabled())
                window.formula_remove.click()
                self.assertFalse(window.run_button.isEnabled())
                self.assertFalse(window.current_button.isEnabled())
                window.mode.setCurrentIndex(0)
                self.assertTrue(window.run_button.isEnabled())

    def test_markdown_and_math_preview(self) -> None:
        from personal_pdf_tools.ocr.formula_preview import markdown_html
        source = "# Formula\n\n" + r"**Vector**: \[\textcolor{red}{\mathbf{x}}\] plus $$a_b$$." + "\n\n"
        source += "$$\na^2\n$$\n\n" + chr(96) + "$code$" + chr(96) + " <script>"
        html = markdown_html(source)
        for expected in ("<h1>Formula</h1>", "<strong>Vector</strong>", r"\[\textcolor{red}{\mathbf{x}}\]",
                         r"\[a_b\]", r"\[a^2\]", "<code>$code$</code>", "&lt;script&gt;"):
            self.assertIn(expected, html)

    def test_formula_preview_preserves_native_window(self) -> None:
        if self.app.platformName() != "windows":
            self.skipTest("Requires the native Windows Qt platform")
        with tempfile.TemporaryDirectory() as folder, patch("utils.config.ConfigStore.directory", return_value=Path(folder)):
            window = ImageWindow(ROOT / "tools/document-processing/image-to-text-and-formula.py")
            self.addCleanup(window.close)
            preview = window.rendered
            if preview is None:
                self.skipTest("Requires local MathJax and Qt WebEngine")
            window.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
            window.show()
            self.app.processEvents()
            handle = window.winId()
            surface = window.windowHandle()

            tab = window.tabs.indexOf(preview)
            self.assertFalse(window.tabs.isTabVisible(tab))
            window.mode.setCurrentIndex(2)
            options = window.vision_options.formula_page.output
            for output in ("markdown", "text", "fragment", "document", "markdown"):
                options.setCurrentIndex(options.findData(output))
                self.assertEqual(window.tabs.isTabVisible(tab), output in ("markdown", "fragment"))
            window.output_format = window.vision_options.active().task().output
            window.rows["equation"] = QtWidgets.QTreeWidgetItem()
            window._progress({"image": "equation", "done": 1, "total": 1, "text": "$$x^2$$"})
            window._completed({"kind": "images-complete", "total": 1, "failed": 0})
            self.assertIs(window.tabs.currentWidget(), window.text)
            def typeset() -> bool:
                if not preview.ready or preview.browser is None:
                    return False
                count = []
                preview.browser.page().runJavaScript("document.querySelectorAll('#output svg').length", 0, count.append)
                wait_for(lambda: bool(count))
                return count[0] == 1

            for _ in range(3):
                window.tabs.setCurrentWidget(preview)
                wait_for(typeset)
                self.assertEqual(window.winId(), handle)
                self.assertIs(window.windowHandle(), surface)
                window.tabs.setCurrentWidget(window.text)
                self.assertEqual(window.winId(), handle)

            options.setCurrentIndex(options.findData("fragment"))
            window.output_format = "fragment"
            fragment = r"Speed \(v\) follows. \[\frac{d}{t}\] **literal**"
            window._progress({"image": "equation", "done": 1, "total": 1, "text": fragment})
            window.tabs.setCurrentWidget(preview)

            def fragment_typeset() -> bool:
                assert preview.browser is not None
                result = []
                preview.browser.page().runJavaScript(
                    "document.querySelectorAll('#output svg').length === 2 && "
                    "document.querySelector('#output').textContent.includes('**literal**')", 0, result.append)
                wait_for(lambda: bool(result))
                return result[0] is True

            wait_for(fragment_typeset)
            self.assertEqual(window.text.toPlainText(), fragment)
