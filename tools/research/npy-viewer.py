#!/usr/bin/env python3
"""Browse NPY, NPZ, MAT, CSV/TXT and images in a linked Qt matrix/signal viewer.

Numeric files accept nonempty dense 1D/2D boolean, integer, real and complex
arrays. MATLAB legacy/v7.3 files expose top-level variables like NPZ members;
only the selected variable is loaded. MATLAB row/column vectors default to
signal mode without squeezing the stored source array.
Two-row/column XY and three-row/column XYZ interpretations work for MAT too.
Unsupported types (object, string, struct, cell, sparse), higher-dimensional
arrays and unreadable files produce an error dialog with the file and reason.
The first selector chooses an NPZ array or MAT variable; a single-file source
is shown as a disabled entry. The second selector chooses image channels and
combinations or a complex array's real/imaginary part, phase (rad/deg) or magnitude.
Multiple-NPY switching is not implemented.

Includes inclusive X/Y source-index cropping, lazy gap-aware derivatives,
X-only or XY curve zoom, and adjustable 3D sampling and height.
Value bounds can be reverted independently of X/Y cropping and color limits.
XY derivatives use sorted actual X coordinates and treat repeated X as gaps.
The derivative tab computes on demand and reuses unchanged data and plots.
Actual derivative calculations print source row/column indices and timing.
Uses the native Qt Fusion widget style.
Images expose source channels, stored bit depth, RGB grayscale and
alpha-weighted RGBA grayscale as selectable matrices, plus RGB/RGBA/monochrome color
rendering in both 2D and 3D. Image loading prints decoder diagnostics.
Monochrome images hide RGB color. All images offer RGBA modes only when a
source alpha channel exists; RGB images never acquire a synthetic A channel.
RGB/RGBA color profiles overlay R/G/B[/A] curves; gray+alpha overlays M/A.
RGBA/gray+alpha profiles multiply color/monochrome by normalized alpha before
filtering and differentiation, while A remains an independent source-value curve.
Channel derivatives load on demand. Colors are red/green/blue, black M and dark
yellow A; filtering and derivative jump checks apply to each channel separately.
Raw data is available as a read-only spreadsheet. Two-row/column tables can
be XY signals; three-row/column tables can be XYZ point clouds. CSV/TXT accepts
UTF-8, comma/semicolon/tab separators, an optional textual header and empty
cells (NaN). Point clouds retain physical XYZ proportions by default.
TXT files must contain numeric CSV-style tables; unrecognized text reports a
load error. Raw table columns default to 48 px and can be adjusted below the table.
1D/XY data use full-height 1D plot, 1D Derivative and Raw data tabs in one row,
hiding 2D/3D-only controls.
Returning to a matrix restores the linked image/surface and profile layout.
An image-only Hexadecimal checkbox formats 8-bit integer source values as
#VV, #RRGGBB, #RRGGBBAA or #GGAA (gray+alpha). It is disabled for floating-point
and 16-bit image matrices. Clipboard copies use
the displayed format; numeric arrays and exports keep their original values.
The Export group saves selected slices, current results or original source
matrices as NPY, MAT (variable 'matrix'), CSV or tab-separated TXT. Slice export
is hidden in signal mode. XY cropping and value bounds can be applied separately.
Hidden/nonfinite samples become NaN in processed arrays. Full-resolution 2D
matrices can become XYZ point clouds (nonfinite points omitted); 1D signals
can become two-row/column XY tables, retaining original sample coordinates.
Color result exports use grayscale. Original export preserves the source dtype
and complex values; complex crop/slice export can also preserve both components
without value bounds. Complex CSV/TXT produces matching _real/_imag files.
MAT stores 1D arrays as column vectors. Default filenames include the source
member, processing ranges and layout; existing names receive a numeric suffix.

Requirements:
    Python 3.13+; numpy, opencv-python, Pillow, matplotlib, PySide6, pyqtgraph,
    pyvista, pyvistaqt, vtk, scipy and h5py (requirements-research.txt).

Usage:
    python npy-viewer.py [file] [--key NAME] [--max-edge 512]
    python npy-viewer.py data.npy --mode signal --channel-axis 1
    python npy-viewer.py measurements.csv --mode xy
    python npy-viewer.py coordinates.npy --mode points
    python npy-viewer.py measurements.mat --key signal
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
DEPENDENCIES = "numpy opencv-python Pillow matplotlib PySide6 pyqtgraph pyvista pyvistaqt vtk scipy h5py"


def main() -> int:
    """Parse arguments and run the GUI, returning its exit status.

    Side effects:
        Selects PySide6 for this process, imports the viewer package, opens
        a Qt window and runs its event loop. Prints dependency errors.
    """
    parser = argparse.ArgumentParser(
        description=("Browse NPY/NPZ/MAT/CSV/TXT/images as a raw table, 2D image, 3D surface or point cloud, and 1D/XY profiles with derivatives. "
                     "Numeric files require nonempty dense 1D/2D arrays. MAT supports legacy/v7.3 numeric and logical variables, including complex arrays; "
                     "select a variable with --key or the GUI. MAT vectors default to signal mode; two/three-row or column matrices also support XY/XYZ modes. "
                     "Unsupported types, higher-dimensional arrays and unreadable files show a clear error dialog. "
                     "Separate selectors choose the source array and its image channel/combination or complex component (real, imaginary, phase in radians/degrees, or magnitude). "
                     "XY derivatives use actual X spacing; repeated X values are gaps. Derivative tabs load on demand and reuse unchanged results. "
                     "Derivative calculations print source indices and timing. "
                     "Revert value bounds independently of X/Y cropping and color limits. "
                     "The Export group saves originals, results and slices as NPY/MAT/CSV/TXT, with independent XY cropping and value bounds. "
                     "Export 2D matrices as XYZ clouds or 1D signals as two-row/column XY tables. "
                     "Complex text exports split into _real/_imag files; MAT uses variable matrix and column vectors for 1D. "
                     "Default export filenames include source, ranges and layout. "
                     "Images expose file bit depth, individual channels, grayscale matrices and RGB/RGBA/monochrome color views. "
                     "Monochrome images hide RGB color; all images offer RGBA modes only with source alpha. No synthetic A channel is added. "
                     "RGB/RGBA and gray+alpha profiles show separate channel curves and lazy per-channel derivatives. "
                     "RGBA/gray+alpha profiles weight color/monochrome by normalized alpha, keeping the separate A curve unchanged. "
                     "1D/XY data use full-height 1D plot, 1D Derivative and Raw data tabs in one row, hiding unrelated 2D/3D controls. "
                     "Raw 8-bit image integers optionally display/copy in hexadecimal; floating-point and 16-bit images stay decimal. "
                     "TXT must contain a numeric CSV-style table. Image loading prints format, depth and decoder diagnostics."),
        epilog=(f"Dependencies: {DEPENDENCIES}. Indices and axis numbers are zero-based. "
                "1D wheel zooms X; Ctrl+wheel zooms XY. 3D middle drag or Ctrl+left drag orbits; "
                "right drag or Alt+middle drag rolls the view."),
    )
    parser.add_argument("file", nargs="?", type=Path, help="File to open; omit for an empty GUI")
    parser.add_argument("--key", help="Initial MAT variable, NPZ member or image matrix label (e.g. R, G, B, A, Monochrome)")
    parser.add_argument("--mode", choices=("matrix", "signal", "xy", "points"),
                        help="Interpret as a matrix, indexed signal, XY table (2 rows/columns), or XYZ cloud (3 rows/columns)")
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
