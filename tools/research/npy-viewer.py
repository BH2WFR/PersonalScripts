#!/usr/bin/env python3
"""Browse NPY, NPZ, MAT, CSV/TXT and images in a linked Qt matrix/signal viewer.

Numeric files accept nonempty dense 1D/2D boolean, integer, real and complex
arrays. MATLAB legacy/v7.3 files expose supported top-level variables like NPZ
members in the matrix list. MATLAB row/column vectors default to
signal mode without squeezing the stored source array.
Transform > Laplace converts an indexed/XY signal (including complex values)
to a complex 2D plane with sigma rows and angular-frequency omega columns.
The 2D view fits those axes independently so narrow sigma ranges remain readable.
Choose dt/unit, sigma range/count, optional zero padding, precision and explicit
crop/bounds/zero filling. Defaults preserve the full input, with 129 sigma rows
over ±4 / duration. Output is limited to 1 GiB; exponential spans are limited
to 30 to avoid extreme numerical conditioning. Computation starts on Generate.
Inverse Laplace uses one complete sigma row, defaulting to the row nearest zero
for recorded planes. It restores the source length and coordinates as a complex
1D signal; preprocessing is not undone. External/reloaded complex planes need
the row's sigma, angular-frequency step, column order, original length and origin.
The finite-record convention is dt * FFT(f[n] * exp(-sigma*n*dt)), with centered
frequencies and time zero at the first selected sample. Full frequency columns
are required for inversion. Exported arrays omit the in-session metadata.
The Transform menu retains Fourier alongside Laplace. Both run in background
workers and ask whether to display only the generated matrix after completion.
Transform > Complex matrix merge combines independently selected matrix channels
as real + imaginary or nonnegative linear magnitude + phase (rad/deg). Complete
source channels must have matching shapes and sample grids; crop, bounds and
overlay alignment are ignored. XY inputs require the same unique uniform grid.
Generated results retain full complex storage and appear as new matrix entries.
Two-row/column XY and three-row/column XYZ interpretations work for MAT too.
Numeric 2-by-N/N-by-2 arrays with N > 2 ask whether to open as 1D XY or 2D
before loading into the workspace; 3-by-N/N-by-3 arrays with N > 3 ask whether
to open as XYZ point clouds or 2D matrices, including each qualifying archive member.
Cancel keeps the current session. Images and explicit --mode choices skip the
prompt; complex arrays offer 2D only because XY/XYZ require real coordinates.
Unsupported types (object, string, struct, cell, sparse), higher-dimensional
arrays and unreadable files produce an error dialog with the file and reason.
The left-side matrix tree chooses a source array or archive member. Its children
choose image channels/combinations, numeric channels or a complex array's
real/imaginary part, phase (rad/deg) or magnitude. Matrix names can be changed
for the session without renaming source files; metadata remains in the selector.
Open file replaces the session; Add overlay or dropping another file appends.
NPZ/MAT members appear in a resizable tree with file/member names. Multichannel
matrices are expandable groups without checkboxes; single-channel matrices are
checkable rows without a channel child. Single matrix mode is the default:
clicking a channel or single-channel matrix displays it exclusively; clicking a
multichannel matrix expands its channels without changing visibility.
Multiple matrices mode allows
checkboxes to combine compatible channels, including channels of one matrix,
in independent solid colors. Switching back retains the edited checked channel,
or the first checked channel if the edited one is hidden. In multiple mode,
row clicks only choose the editing target; checkboxes control visibility.
Adding files in single mode retains the list but shows
only the new file's first member. Remove / Remove all release session data without deleting files. Indexed signals
and XY tables can share a plot; matrices and point clouds form separate groups.
XY alignment supports original coordinates, start/end, center and stretch,
relative to a selectable reference (the first matrix by default). Alignment
only transforms display coordinates; derivatives keep source coordinates.
2D overlays encode scalar intensity in opacity, and 3D overlays use solid meshes.
Aligned matrix slices use the nearest source row/column and identify its index.
Both 3D slice styles use the shared 3D color setting, including in overlay mode.
Raw data names its source channel; the header dropdown browses source matrices by name
without changing plot selection and is disabled with zero or one matrix.
Unchecked channels remain hidden from the raw table.
Curve legends sit beside the title outside the plot, scrolling horizontally
when needed. Overlay derivatives are lazy and cached for each source slice.

Includes inclusive X/Y source-index cropping, lazy gap-aware derivatives,
X-only or XY curve zoom, and adjustable 3D sampling and height.
Value bounds can be reverted independently of X/Y cropping and color limits.
XY derivatives use sorted actual X coordinates and treat repeated X as gaps.
The derivative tab computes on demand and reuses unchanged data and plots.
Actual derivative calculations print source row/column indices and timing.
Uses native Qt Fusion painting with compact layouts: main content margins are
2 px at the top and 6 px elsewhere; panel padding and vertical gaps are 2 px.
The three resize dividers are blue, amber on hover and orange while dragging.
All viewer combo boxes ignore wheel changes, including while focused; mouse
clicks and keyboard selection still work. Open dropdown lists remain scrollable.
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
and complex values. Complex crop/slice exports default to preserving both
components without value bounds; uncheck Export complex matrix to save only
the current display component. Detection uses the source dtype, including zero
imaginary parts. Complex CSV/TXT produces matching _real/_imag files.
MAT stores 1D arrays as column vectors. Default filenames include the source
member, processing ranges and layout; existing names receive a numeric suffix.
Export scope chooses the selected source or all currently visible matrices.
Visible exports apply the displayed channel, crop, value bounds and XY alignment,
retaining each source as a separate full-resolution XY or XYZ table. Camera
zoom and 3D height multipliers are excluded. MAT packs separate named variables;
NPY/CSV/TXT use one file per matrix. Separate files (including complex text's
real/imaginary pair) each get a save dialog with a descriptive default filename.
All destinations are collected before writing; cancelling cancels the batch.
Export figure opens a separate preview dialog for the current 2D image, 3D
surface/cloud, 1D signal/slice or derivative, including visible overlays.
It preserves zoom, camera, colors, axes, colorbars and selection markers while
omitting GUI controls and hover cursors. Output supports PNG, lossless TIFF,
JPEG, and SVG for 2D/1D plots (embedded pixels for image data, vector curves/text).
Choose image width/height, print DPI, transparent background (except JPEG),
optional title and a wrapped full-name legend. Aspect locking links width and
height to the original plot; unlock it to set both dimensions independently.
The final dimensions include annotations. Axes reflow and 3D is rendered in the
new viewport; original viewer geometry/ranges/camera are restored afterward.
Default width is 2400 px and DPI is 300. 2D/curve exports disable screen
downsampling temporarily; 3D uses the existing sampled mesh at higher image
resolution. Only selecting derivative export requests its lazy computation.
Closing the dialog restores the original tabs. Saves replace files atomically.

Fourier opens a modal FFT/IFFT dialog for the selected signal, image channel,
complex matrix, crop or slice. Results become independent complex matrices in
the tree. A completion dialog offers to display only the new result (Yes) or
keep the current view and add it unchecked (No).
FFT uses complete centered spectra; IFFT restores recorded axes and
normalization for generated spectra. Sampling intervals/units, axes, padding,
normalization, precision, optional mean removal and periodic windows are configurable.
NaN/Inf are rejected unless explicit zero filling is enabled; XY input must have
unique uniformly spaced X. Point clouds are unsupported. Calculations run on
demand in a worker at full resolution. Frequency coordinates are shared by plots,
surfaces, profiles, derivatives and coordinate-table exports. Magnitude (dB)
uses the selected region's peak as 0 dB, with an adjustable floor. Complex data
remain intact. Ordinary exported array files do not retain Fourier metadata;
external IFFT requires specifying spectrum order, frequency spacing and normalization.
Windowing, mean removal and value bounds cannot be undone by IFFT.

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
                     "Numeric 2-by-N/N-by-2 arrays with N > 2 prompt for 1D XY or 2D; 3-by-N/N-by-3 arrays with N > 3 prompt for XYZ point cloud or 2D, including archive members. Cancel preserves the workspace. Images and explicit --mode choices skip the prompt; complex XY/XYZ is unavailable. "
                     "Unsupported types, higher-dimensional arrays and unreadable files show a clear error dialog. "
                     "The left-side matrix/channel tree selects sources and their image channels, combinations, numeric channels or complex components (real, imaginary, phase in radians/degrees, or magnitude). "
                     "Add overlay or dropping another file appends; NPZ/MAT members join a resizable tree with independent channel settings and colors. Rename changes session labels, not source files. "
                     "Multichannel matrices are expandable groups without checkboxes; single-channel matrices have a checkbox on the matrix row and no child row. "
                     "Single matrix mode is the default: clicking a channel or single-channel matrix displays it exclusively; clicking a multichannel matrix expands its channels without changing visibility. "
                     "Multiple matrices mode permits compatible channel checkboxes to overlay, including channels of one matrix. Row clicks only change the editing target in this mode. Switching back to single mode keeps the edited checked channel, or the first checked channel. "
                     "Adding files in single mode retains the list and shows only the new file's first member. Remove / Remove all release session entries without deleting files. Indexed signals and XY tables can share a plot. "
                     "Raw data names its source matrix/channel. Its header dropdown browses matrices by name without changing plot selection, is disabled with zero or one matrix, and keeps unchecked channels hidden. "
                     "Curve legends sit beside the title outside the plot and scroll if necessary. "
                     "Align X/Y to a selectable reference, initially the first matrix, using original coordinates, start/end, center or stretch. "
                     "Alignment is display-only; raw data and derivatives retain source coordinates. Visible-matrix export includes alignment. 2D scalar values control opacity; 3D uses solid colors. "
                     "Raised curves and translucent sections use the shared 3D color setting in single and overlay modes. "
                     "XY derivatives use actual X spacing; repeated X values are gaps. Derivative tabs load on demand and reuse unchanged results. "
                     "Derivative calculations print source indices and timing. "
                     "Revert value bounds independently of X/Y cropping and color limits. "
                     "The Export group saves originals, results and slices as NPY/MAT/CSV/TXT, with independent XY cropping and value bounds. "
                     "Export 2D matrices as XYZ clouds or 1D signals as two-row/column XY tables. "
                     "Complex text exports split into _real/_imag files; MAT uses variable matrix and column vectors for 1D. "
                     "Selected complex matrices default to exporting both components (also for crops/slices); uncheck Export complex matrix to save the displayed component. Original export always retains complex storage. "
                     "Default export filenames include source, ranges and layout. "
                     "Export scope selects one matrix or all visible results in aligned XY/XYZ tables, preserving separate matrices. MAT stores named variables; NPY/CSV/TXT save separate files. "
                     "Separate outputs each get a save dialog with a suggested name; cancelling any dialog cancels the batch before writing. "
                     "Export figure previews the current 2D/3D/1D/derivative view with overlays, zoom and camera preserved. "
                     "Save PNG/TIFF/JPEG, or SVG for 2D/1D; choose pixel width/height, optional aspect locking, DPI (default 300), transparency, title and legend. "
                     "2D/curve figures use full source detail; 3D retains current mesh sampling. Derivatives remain lazy. "
                     "Transform > Fourier opens FFT/IFFT settings for a signal, scalar image channel, complex matrix, crop or slice and adds a new complex result to the tree. "
                     "Transform > Complex matrix merge combines two selected source channels as real + imaginary or linear magnitude + phase (rad/deg). Shapes and grids must match; display crops, bounds and alignment are ignored. XY inputs require matching unique uniform X grids. "
                     "Transform > Laplace converts a 1D/XY signal to a complex sigma/omega plane; its 2D view fits each axis independently. Choose dt/unit, sigma range/count, padding and precision; optional crop/bounds/zero filling are explicit. "
                     "Default: 129 sigma rows over +/-4/duration, full centered angular-frequency columns, normalization dt*FFT. The first selected sample is the kernel time origin. Output is limited to 1 GiB and abs(sigma)*duration to 30. "
                     "Inverse Laplace restores a complex 1D signal from one complete sigma row; recorded planes default to sigma nearest zero and restore source sampling/length automatically. "
                     "External/reloaded planes need sigma, angular-frequency interval, column order, original length, unit and origin. This is a finite-record numerical transform; preprocessing is not undone. "
                     "After calculation, Yes displays only the new result; No keeps the current view and adds the result unchecked. "
                     "Choose sampling intervals/units, axes, padding, normalization, precision and optional windows/mean removal; all default preprocessing is off. "
                     "Full-resolution transforms run only on Generate. FFT stores centered full spectra; paired IFFT restores recorded coordinates and normalization. "
                     "XY input needs unique uniform sampling; NaN/Inf require explicit zero filling. Point clouds cannot be transformed. "
                     "Frequency axes carry through views, derivatives and XY/XYZ exports. Magnitude (dB) has a configurable floor and a 0 dB peak. "
                     "Plain array exports omit transform metadata; external IFFT needs manual order, frequency spacing and normalization. IFFT cannot undo windows, mean removal or bounds. "
                     "Images expose file bit depth, individual channels, grayscale matrices and RGB/RGBA/monochrome color views. "
                     "Monochrome images hide RGB color; all images offer RGBA modes only with source alpha. No synthetic A channel is added. "
                     "RGB/RGBA and gray+alpha profiles show separate channel curves and lazy per-channel derivatives. "
                     "RGBA/gray+alpha profiles weight color/monochrome by normalized alpha, keeping the separate A curve unchanged. "
                     "1D/XY data use full-height 1D plot, 1D Derivative and Raw data tabs in one row, hiding unrelated 2D/3D controls. "
                     "Raw 8-bit image integers optionally display/copy in hexadecimal; floating-point and 16-bit images stay decimal. "
                     "Native Fusion widgets use compact layouts: main content margins are top 2 px and other sides 6 px, panel padding and vertical gaps 2 px, horizontal gaps 4 px. "
                     "The three resize dividers are blue, with amber hover and orange drag feedback. "
                     "Combo boxes ignore wheel changes even with focus; click/keyboard selection and open-list scrolling remain available. "
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
