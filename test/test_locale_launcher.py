"""Windows GUI routing and native locale regression checks."""

from __future__ import annotations

from contextlib import chdir
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
RAW_ARGUMENTS = '  --file "C:\\目录 with spaces\\a.txt"\t""  "a\\\\"  --literal=%PATH%&  '
if sys.platform == "win32":
    sys.path.insert(0, str(ROOT / "tools/windows"))
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtWidgets import QApplication
    from locale_launcher import settings, ui


@unittest.skipUnless(sys.platform == "win32", "Windows locale APIs")
class LauncherTests(unittest.TestCase):
    def test_inputs_and_actions(self) -> None:
        app = QApplication.instance() or QApplication([])
        ui.configure_qt_application(app)
        startup = Path(self.enterContext(tempfile.TemporaryDirectory()))
        selected = startup / "工作 folder"
        selected.mkdir()
        with chdir(startup):
            window = ui.Launcher()
        self.addCleanup(window.close)
        self.assertEqual(window.directory.text(), str(startup))
        self.assertFalse(window.run_button.isEnabled())
        for box in (window.region, window.page, window.language, window.zone):
            self.assertEqual(box.currentData(), "")
        self.assertEqual([window.region.itemData(i) for i in range(1, 5)], list(settings.PREFERRED_REGIONS))
        self.assertEqual([window.page.itemData(i) for i in range(1, 6)], ["936", "950", "949", "932", "65001"])
        target = ROOT / "tools/windows/_locale-info.com"
        with patch.object(ui.QFileDialog, "getOpenFileName", return_value=(str(target), "")):
            window.browse()
        self.assertEqual(window.path.text(), str(target))
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(target))])
        event = QDropEvent(QPointF(), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier)
        window.path.clear()
        window.dropEvent(event)
        self.assertEqual(window.path.text(), str(target))
        self.assertTrue(event.isAccepted())
        for copied_file in (True, False):
            if not copied_file:
                mime.clear()
                mime.setText(f'"{target}"')
            with patch("utils.qt_clipboard.QGuiApplication.clipboard", return_value=Mock(mimeData=lambda: mime)):
                window.path.clear()
                window.paste()
            self.assertEqual(window.path.text(), str(target))
        window.page.setCurrentIndex(window.page.findData("932"))
        self.assertEqual(window.arguments.text(), "")
        window.arguments.setText(RAW_ARGUMENTS)
        window.directory.clear()
        with patch.object(ui, "launch") as start:
            window.run_button.click()
            start.assert_called_with(target, settings.Selection(code_page=932), False, RAW_ARGUMENTS, startup)
            with patch.object(ui.QFileDialog, "getExistingDirectory", return_value=str(selected)) as picker:
                window.browse_directory()
                picker.assert_called_once_with(window, "Open folder", str(startup))
            self.assertEqual(window.directory.text(), str(selected))
            with patch.object(ui.QFileDialog, "getExistingDirectory", return_value=""):
                window.browse_directory()
            self.assertEqual(window.directory.text(), str(selected))
            window.directory.setText(selected.name)
            window.admin_button.click()
            start.assert_called_with(target, settings.Selection(code_page=932), True, RAW_ARGUMENTS, selected)
        with patch.object(settings, "start_elevated_executable") as elevated:
            settings.launch(target, settings.Selection(), True, RAW_ARGUMENTS, selected)
            elevated.assert_called_with(str(target), RAW_ARGUMENTS, str(selected))
            settings.launch(target, settings.Selection(code_page=932), True, RAW_ARGUMENTS, selected)
            exe, arguments, helper_dir = elevated.call_args.args
            self.assertEqual(Path(exe).name, "locale-start.exe")
            self.assertEqual(helper_dir, str(Path(exe).parent))
            self.assertEqual(arguments, subprocess.list2cmdline([str(target), "", "932", "", "", RAW_ARGUMENTS, str(selected)]))
            elevated.reset_mock()
            with self.assertRaisesRegex(ValueError, "working directory"):
                settings.launch(target, settings.Selection(), True, working_directory=selected / "missing")
            elevated.assert_not_called()
        with patch.object(ui.QMessageBox, "warning") as warning:
            window.select([str(target), str(target)])
            warning.assert_called_once()
            self.assertEqual(window.path.text(), str(target))

    @unittest.skipUnless(shutil.which("cl") and shutil.which("rc"), "requires an MSVC Developer Shell")
    def test_native_overrides(self) -> None:
        fixtures = ROOT / "test/fixtures"
        with tempfile.TemporaryDirectory(prefix="locale test ") as scratch:
            folder = Path(scratch)
            target = folder / "应用 probe.exe"
            subprocess.run(["rc", "/nologo", "/fo", "probe.res", str(fixtures / "locale-launcher-probe.rc")],
                           cwd=folder, check=True, capture_output=True)
            subprocess.run(["cl", "/nologo", "/utf-8", "/MT", "/EHsc", f"/Fe:{target}",
                            str(fixtures / "locale-launcher-probe.cpp"), "probe.res", "user32.lib"],
                           cwd=folder, check=True, capture_output=True)
            working_directory = folder / "测试 working directory"
            working_directory.mkdir()
            result = working_directory / "locale-probe.txt"

            def probe(selection: settings.Selection, arguments: str = "") -> list[str]:
                result.unlink(missing_ok=True)
                settings.launch(target, selection, False, arguments, working_directory)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if result.exists():
                        try:
                            lines = result.read_text(encoding="utf-8-sig").splitlines()
                            if len(lines) == 11:
                                return lines
                        except PermissionError:
                            pass  # The target has not closed the report yet.
                    time.sleep(0.05)
                self.fail(f"No complete report for {selection}")

            host = probe(settings.Selection())
            for selection in (settings.Selection(), settings.Selection(code_page=932)):
                for arguments in (RAW_ARGUMENTS, '""', '   ', 'a\\\"b "open quote'):
                    with self.subTest(selection=selection, arguments=arguments):
                        self.assertEqual(probe(selection, arguments)[10], f'"{target}" {arguments}')
            for selection in (settings.Selection(code_page=932), settings.Selection(region="zh-TW"),
                              settings.Selection(ui_language="ko-KR"), settings.Selection(time_zone="Tokyo Standard Time"),
                              settings.Selection("ja-JP", 65001, "zh-CN", "Pacific Standard Time")):
                with self.subTest(selection=selection):
                    data = probe(selection)
                    self.assertEqual(data[:4], [selection.region or host[0], str(selection.code_page or host[1]),
                                     {"ko-KR": "0412", "zh-CN": "0804"}.get(selection.ui_language, host[2]),
                                     selection.time_zone or host[3]])
                    if selection.code_page:
                        self.assertEqual(data[4 if selection.code_page == 932 else 5], "65e5")
                    self.assertEqual(data[6], data[7])
                    self.assertEqual(data[8], selection.ui_language or host[8])
                    self.assertEqual(data[9], {"ko-KR": "Korean resource", "zh-CN": "Chinese resource"}
                                     .get(selection.ui_language, host[9]))


if __name__ == "__main__":
    unittest.main()
