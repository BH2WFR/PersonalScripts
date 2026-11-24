"""Resolve the viewer's runtime distributions from the selected Python installation."""

from collections import deque
from importlib import metadata, util
import os
from pathlib import Path
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


# These are runtime features of the viewer, including legacy Excel and Qt font fallback.
VIEWER_REQUIREMENTS = (
    "numpy", "opencv-python", "Pillow", "matplotlib", "PySide6", "pyqtgraph",
    "pyvista", "pyvistaqt", "vtk", "scipy", "h5py", "openpyxl", "xlrd", "fonttools",
)


def _opencv_provider() -> str:
    """Find the installed OpenCV distribution supplying the active cv2 package."""
    spec = util.find_spec("cv2")
    if spec and spec.origin:
        origin = Path(spec.origin).resolve()
        providers = ("opencv-python", "opencv-python-headless", "opencv-contrib-python", "opencv-contrib-python-headless")
        for name in providers:
            try:
                dist = metadata.distribution(name)
            except metadata.PackageNotFoundError:
                continue
            if Path(str(dist.locate_file("cv2/__init__.py"))).resolve() == origin:
                return name
    raise ValueError("No installed OpenCV distribution supplies the active cv2 package.")


def runtime_distributions(requirements: tuple[str, ...]) -> dict[str, metadata.Distribution]:
    """Resolve installed Requires-Dist entries, evaluating markers and requested extras."""
    pending = deque(Requirement(_opencv_provider() if name == "opencv-python" else name) for name in requirements)
    selected: dict[str, metadata.Distribution] = {}
    expanded: set[tuple[str, str]] = set()
    while pending:
        req = pending.popleft()
        name = canonicalize_name(req.name)
        if name not in selected:
            selected[name] = metadata.distribution(name)
        dist = selected[name]
        if req.specifier and not req.specifier.contains(dist.version, prereleases=True):
            raise ValueError(f"Viewer build requires {req}, found {name} {dist.version}.")
        for extra in {"", *req.extras}:
            if (name, extra) in expanded:
                continue
            expanded.add((name, extra))
            for entry in dist.requires or ():
                dependency = Requirement(entry)
                if dependency.marker is None or dependency.marker.evaluate({"extra": extra}):
                    pending.append(dependency)
    return selected


def unrelated_modules(distributions: dict[str, metadata.Distribution]) -> list[str]:
    """Translate the distribution allowlist into PyInstaller's module exclusion API."""
    owners = metadata.packages_distributions()
    return sorted(name for name, providers in owners.items()
                  if name not in sys.stdlib_module_names
                  and not any(canonicalize_name(provider) in distributions for provider in providers))


def owned_files(distributions: dict[str, metadata.Distribution]) -> set[Path]:
    """Index installed file records to check hook data and shared namespace packages."""
    paths: set[Path] = set()
    for name, dist in distributions.items():
        files = dist.files
        if files is None:
            raise ValueError(f"Cannot audit {name}: the installed file list is missing.")
        root = Path(str(dist.locate_file(""))).resolve()
        paths.update(Path(os.path.normpath(root / file)) for file in files)
    return paths
