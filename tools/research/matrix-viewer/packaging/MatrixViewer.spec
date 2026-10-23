# -*- mode: python ; coding: utf-8 -*-
"""Build the Windows viewer as a non-UPX, one-directory application.

Requirements: PyInstaller 6 and the viewer's runtime dependencies in the selected
environment. Base can also use current-user site-packages when Python enables
them; dedicated environments remain isolated. No packages are installed here.
Usage from the repository root:
    conda run -n base python -P -X utf8 -m PyInstaller --clean \
        --distpath D:/Portable_Programs --workpath BUILD/MatrixViewer/work \
        tools/research/matrix-viewer/packaging/MatrixViewer.spec

The source directory has a hyphen, so stage only its top-level Python modules
as personal_matrix_viewer for static analysis and frozen imports. Tests, manual
samples and packaging helpers are not application resources. The launcher keeps
its existing source-mode loader and uses normal imports when frozen.
Keep the console for existing diagnostic output. Distribute the entire
MatrixViewer directory, including _internal. UPX and one-file extraction are off.
UTF-8 interpreter mode also keeps redirected diagnostics safe on Windows.
"""

from importlib import metadata
import filecmp
import hashlib
import json
import os
from pathlib import Path
import shutil
import site
import sys

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.config import CONF


APP_NAME = "MatrixViewer"
PACKAGE_NAME = "personal_matrix_viewer"
PACKAGING_DIR = Path(CONF["specpath"]).resolve()
SOURCE_DIR = PACKAGING_DIR.parent
PROJECT_DIR = SOURCE_DIR.parents[2]
ENVIRONMENT_DIR = Path(sys.prefix).resolve()
WORK_DIR = Path(CONF["workpath"]).resolve()
STAGING_DIR = WORK_DIR / "viewer-source"
PACKAGE_DIR = STAGING_DIR / PACKAGE_NAME

# Use only the selected environment and, for base, its enabled user-site.
if sys.platform != "win32":
    raise SystemExit("This release configuration targets Windows.")
is_base = any((ENVIRONMENT_DIR / "conda-meta").glob("conda-[0-9]*.json"))
use_user_site = is_base and site.ENABLE_USER_SITE is True
package_roots = (ENVIRONMENT_DIR, Path(site.getusersitepackages()).resolve()) if use_user_site else (ENVIRONMENT_DIR,)
for search_path in sys.path:
    candidate = Path(search_path).resolve()
    if "site-packages" in candidate.parts and not any(candidate.is_relative_to(root) for root in package_roots):
        raise SystemExit("Foreign site-packages detected outside the selected package scope.")
if use_user_site:
    os.environ.pop("PYTHONNOUSERSITE", None)
else:
    os.environ["PYTHONNOUSERSITE"] = "1"
os.environ.pop("PYTHONPATH", None)
os.environ["QT_API"] = "pyside6"
os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
os.environ["PYVISTA_VTK_BACKEND"] = "vtk"

# Staging is generated build output, never the live source directory.
if not PACKAGE_DIR.resolve().is_relative_to(WORK_DIR):
    raise SystemExit("The generated package path must remain inside the work directory.")
PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
modules = sorted(SOURCE_DIR.glob("*.py"))
for obsolete in PACKAGE_DIR.glob("*.py"):
    if not (SOURCE_DIR / obsolete.name).is_file():
        obsolete.unlink()
for source in modules:
    target = PACKAGE_DIR / source.name
    if not target.exists() or not filecmp.cmp(source, target, shallow=False):
        shutil.copy2(source, target)

# The cache must also notice content-only source edits and package upgrades.
# Custom hooksconfig entries participate in Analysis's cache identity.
build_versions: dict[str, str] = {}
for distribution in metadata.distributions():
    # Keep the first distribution on sys.path, including user-site precedence.
    build_versions.setdefault(distribution.metadata["Name"], distribution.version)
build_inputs = [*modules, SOURCE_DIR.with_suffix(".py"), *sorted((PROJECT_DIR / "utils").glob("*.py")),
                *sorted(PACKAGING_DIR.rglob("*.py")), PACKAGING_DIR / "MatrixViewer.spec"]
input_hashes = {str(path.relative_to(PROJECT_DIR)): hashlib.sha256(path.read_bytes()).hexdigest() for path in build_inputs}

excludes = [
    "__main__",  # ModuleGraph adds this itself; include it upfront to keep its cache key stable.
    "PyQt5", "PyQt6", "PySide2", "tkinter", "_tkinter",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "IPython", "ipykernel", "ipywidgets", "jupyter", "notebook",
    "torch", "tensorflow", "jax", "cupy", "pandas", "sympy",
    "trame", "trame_vtk", "trame_vuetify", "trame_pyvista", "cvista",
    "pymupdf", "fitz", "win10toast", "pytest",
    # Unused PyVista conversions and remote/movie I/O can pull large optional stacks from base.
    "trimesh", "meshio", "pyarrow", "imageio", "fsspec",
    "vtk",  # PyVista uses vtkmodules; the eager vtk shim imports every module.
]
hiddenimports = [PACKAGE_NAME, "openpyxl", "xlrd", "pyvista.plotting"]
hiddenimports.extend(f"{PACKAGE_NAME}.{source.stem}" for source in modules if source.stem != "__init__")

analysis = Analysis(
    [str(SOURCE_DIR.with_suffix(".py"))],
    pathex=[str(PROJECT_DIR), str(STAGING_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[str(PACKAGING_DIR / "hooks")],
    hooksconfig={"matplotlib": {"backends": ["Agg"]},
                 "matrix_viewer": {"environment": build_versions, "inputs": input_hashes,
                                   "package_roots": [str(root) for root in package_roots], "python": sys.version}},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Reject modules from other environments and unapproved external locations.
# Windows system DLLs are legitimate dependencies.
allowed_roots = (*package_roots, PROJECT_DIR, WORK_DIR, Path(os.environ["SystemRoot"]).resolve())
foreign_sources: set[str] = set()
for _name, source, _kind in [*analysis.pure, *analysis.binaries, *analysis.datas]:
    if source:
        path = Path(source).resolve()
        if not any(path.is_relative_to(root) for root in allowed_roots):
            foreign_sources.add(str(path))
if foreign_sources:
    raise SystemExit(f"Files outside the selected package scope were collected: {sorted(foreign_sources)}")

manifest = {
    "application": APP_NAME,
    "layout": "onedir",
    "upx": False,
    "utf8_mode": True,
    "user_site_enabled": use_user_site,
    "python": sys.version.split()[0],
    "build_environment": build_versions,
    "modules": sorted(name for name, _source, _kind in analysis.pure),
    "binaries": sorted(name for name, _source, _kind in analysis.binaries),
    "excluded_optional_modules": excludes,
}
manifest_path = WORK_DIR / "build-manifest.json"
manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True)
if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8") != manifest_text:
    manifest_path.write_text(manifest_text, encoding="utf-8")
analysis.datas.append(("build-manifest.json", str(manifest_path), "DATA"))

archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    [("X utf8", None, "OPTION")],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    contents_directory="_internal",
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
