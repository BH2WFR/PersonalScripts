#!/usr/bin/env python3
"""Browse NPY, NPZ and images in a linked Qt matrix/signal viewer.

Includes inclusive X/Y source-index cropping, lazy gap-aware derivatives,
X-only or XY curve zoom, and adjustable 3D sampling and height.
Uses the native Qt Fusion widget style.

Requirements:
    Python 3.13+; numpy, opencv-python, matplotlib, PySide6, pyqtgraph,
    pyvista, pyvistaqt and vtk (requirements-research.txt).

Usage:
    python npy-viewer.py [file] [--key NAME] [--max-edge 512]
    python npy-viewer.py data.npy --mode signal --channel-axis 1
"""

import argparse
import importlib
import importlib.util
import os
from pathlib import Path
import sys
from typing import Callable, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils import *  # noqa: E402

PACKAGE_NAME = "personal_npy_viewer"
DEPENDENCIES = "numpy opencv-python matplotlib PySide6 pyqtgraph pyvista pyvistaqt vtk"


def main() -> int:
    """Parse arguments and run the GUI, returning its exit status.

    Side effects:
        Selects PySide6 for this process, imports the viewer package, opens
        a Qt window and runs its event loop. Prints dependency errors.
    """
    parser = argparse.ArgumentParser(
        description="Browse NPY/NPZ/images as a 2D image, 3D surface and 1D profile with optional derivatives.",
        epilog=(f"Dependencies: {DEPENDENCIES}. Indices and axis numbers are zero-based. "
                "1D wheel zooms X; Ctrl+wheel zooms XY. 3D right drag or Alt+middle drag rolls the view."),
    )
    parser.add_argument("file", nargs="?", type=Path, help="File to open; omit for an empty GUI")
    parser.add_argument("--key", help="Initial NPZ member name")
    parser.add_argument("--mode", choices=("matrix", "signal"), help="Interpret data as a matrix or signal")
    parser.add_argument("--channel-axis", type=int, help="Channel axis (negative indices accepted)")
    parser.add_argument("--max-edge", type=int, default=512, help="3D maximum grid edge; 0 = full resolution (default: 512)")
    args = parser.parse_args()
    if args.max_edge < 0 or args.max_edge == 1:
        parser.error("--max-edge must be 0 (full resolution) or at least 2")

    # ── dependency checks and package loading ──────────────
    Console.set_locale_utf8()
    os.environ["QT_API"] = "pyside6"
    os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
    package_dir = Path(__file__).with_name("npy-viewer")
    try:
        spec = importlib.util.spec_from_file_location(
            PACKAGE_NAME, package_dir / "__init__.py",
            submodule_search_locations=[str(package_dir)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load viewer from {package_dir}")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        spec.loader.exec_module(package)
        app_module = importlib.import_module(f"{PACKAGE_NAME}.app")
    except ImportError as exc:
        print(f"{FLRed}Viewer dependency could not be imported: {exc}{CRst}")
        print(f"Install with: conda run -n base python -m pip install {DEPENDENCIES}")
        return 1
    System.enable_dpi_awareness()
    run = cast(Callable[[Path | None, str | None, str | None, int | None, int], int], app_module.run)
    return run(args.file, args.key, args.mode, args.channel_axis, args.max_edge)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
