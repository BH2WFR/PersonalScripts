"""Regression checks for release contents and atomic archive publication."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_builder", ROOT / "package-project.py")
assert spec is not None and spec.loader is not None
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReleaseTests(unittest.TestCase):
    def test_menu_tasks_and_unattended_packaging(self) -> None:
        # None means the operation must not run. A bool is its expected argument.
        cases = (
            ([], [""], None, None),
            ([], ["1"], True, None),
            ([], ["2", "y"], False, True),
            ([], ["2", "n"], False, False),
            ([], ["2", ""], False, False),
            (["build-runtime"], [], True, None),
            (["package"], [], False, False),
            (["package", "--with-resources"], [], False, True),
            (["package", "--refresh"], [], True, False),
            (["package", "--with-resources", "--refresh"], [], True, True),
            (["--refresh"], [], True, False),
            (["--with-resources"], [], False, True),
            (["--refresh", "--with-resources"], [], True, True),
        )
        with tempfile.TemporaryDirectory() as folder:
            build = Path(folder)
            archive = build / "fixture.zip"
            archive.touch()
            for args, answers, refresh, resources in cases:
                with (
                    self.subTest(args=args, answers=answers),
                    patch.object(sys, "argv", ["package-project.py", *args]),
                    patch("builtins.input", side_effect=answers) as prompt,
                    patch.object(builder.Environment, "check_commands", return_value=True),
                    patch.object(builder, "BUILD", build),
                    patch.object(builder, "prepare_runtime") as prepare,
                    patch.object(builder, "write_archive", return_value=archive) as write,
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(builder.main(), 0)
                    self.assertEqual(prompt.call_count, len(answers))
                    if refresh is None:
                        prepare.assert_not_called()
                    else:
                        prepare.assert_called_once_with(refresh=refresh)
                    if resources is None:
                        write.assert_not_called()
                    else:
                        write.assert_called_once_with(resources)

    def test_invalid_command_combinations_exit_before_work(self) -> None:
        for args in (["unknown"], ["build-runtime", "--with-resources"], ["build-runtime", "--refresh"]):
            with (
                self.subTest(args=args),
                patch.object(sys, "argv", ["package-project.py", *args]),
                patch.object(builder.Menu, "select") as menu,
                patch.object(builder.Environment, "check_commands") as check,
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                builder.main()
            self.assertEqual(error.exception.code, 2)
            menu.assert_not_called()
            check.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows ACL inheritance")
    def test_staging_inherits_the_same_permissions_as_an_ordinary_directory(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            reference = parent / "reference"
            reference.mkdir()
            with builder.staging_directory(parent, "archive") as stage:
                expected = subprocess.check_output(["icacls", "."], cwd=reference)
                self.assertEqual(subprocess.check_output(["icacls", "."], cwd=stage), expected)

    def test_archive_uses_working_tree_and_preserves_prior_output_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            build = root / "BUILD"
            build.mkdir()
            runtime = root / "deps/python"
            for name in (*builder.ROOT_FILES, "tools/demo.py", "tools/private/model.json",
                         "tools/local.patch.yaml", "utils/__init__.py", "deps/python/python",
                         "deps/python/__pycache__/local.pyc", "deps/ocr-models/model.onnx", "deps/tools/helper"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "--", "tools/demo.py", "tools/private", "utils"], cwd=root, check=True)
            (root / "tools/demo.py").write_bytes(b"working tree")
            with patch.multiple(builder, ROOT=root, BUILD=build, RUNTIME=runtime):
                base_files = list(builder.release_files(False))
                self.assertIn(runtime / "python", base_files)
                self.assertNotIn(root / "deps/tools/helper", base_files)
                self.assertNotIn(root / "deps/ocr-models/model.onnx", base_files)
                archive = builder.write_archive(True)
                if zipfile.is_zipfile(archive):
                    with zipfile.ZipFile(archive) as release:
                        names = release.namelist()
                        self.assertEqual(release.read("tools/demo.py"), b"working tree")
                else:
                    with tarfile.open(archive) as release:
                        names = release.getnames()
                        script = release.extractfile("tools/demo.py")
                        assert script is not None
                        self.assertEqual(script.read(), b"working tree")
                self.assertIn("tools/private/model.json", names)
                self.assertIn("deps/ocr-models/model.onnx", names)
                self.assertIn("deps/tools/helper", names)
                self.assertNotIn("tools/local.patch.yaml", names)
                self.assertNotIn("deps/python/__pycache__/local.pyc", names)
                original = archive.read_bytes()
                (root / "LICENSE").unlink()
                with self.assertRaises(FileNotFoundError):
                    builder.write_archive(True)
                self.assertEqual(archive.read_bytes(), original)
