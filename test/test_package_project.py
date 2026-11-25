"""Regression checks for release contents and atomic archive publication."""

import importlib.util
import os
from pathlib import Path
import subprocess
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
                         "deps/python/__pycache__/local.pyc", "deps/ocr-models/model.onnx"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "--", "tools/demo.py", "tools/private", "utils"], cwd=root, check=True)
            (root / "tools/demo.py").write_bytes(b"working tree")
            with patch.multiple(builder, ROOT=root, BUILD=build, RUNTIME=runtime):
                self.assertNotIn(root / "deps/ocr-models/model.onnx", builder.release_files(False))
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
                self.assertNotIn("tools/local.patch.yaml", names)
                self.assertNotIn("deps/python/__pycache__/local.pyc", names)
                original = archive.read_bytes()
                (root / "LICENSE").unlink()
                with self.assertRaises(FileNotFoundError):
                    builder.write_archive(True)
                self.assertEqual(archive.read_bytes(), original)
