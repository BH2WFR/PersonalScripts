#!/usr/bin/env python3
"""Browse NPY, NPZ, MAT, Excel, CSV/TXT and images in a linked Qt matrix/signal viewer.

The detailed notes below are for maintainers and coding agents. Keep the CLI
description a concise user-facing overview; document implementation behavior
and detailed defaults here instead of expanding command-line help.

Numeric files accept nonempty dense 1D/2D boolean, integer, real and complex
arrays. MATLAB legacy/v7.3 files expose supported top-level variables like NPZ
members in the matrix list. MATLAB row/column vectors default to
signal mode without squeezing the stored source array.
NPZ/MAT files with multiple members open a checkbox list with Select all/none
and source dimensions. Only selected matrices are loaded. XLSX/XLSM/XLS worksheets
use the same list, with independent one-based row/column bounds and header mode.
CSV/TXT also offer range/header/delimiter settings before numeric conversion.
Excel reads cached formula results; missing XLSX/XLSM caches report the source
cell. Legacy XLS uses xlrd; blank saved results become gaps, and Excel error or
date/time cells report their coordinates. XLS/XLSM are data-only input; export
writes XLSX workbooks. Imported indices start at zero after excluding headings.
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
Transform > Data conversion creates a new full-resolution matrix from the active
channel, its current crop or selected slice, with optional source value bounds.
Operations include amplitude dB (20 log10(abs(x)/reference)), power dB
(10 log10(x/reference)), deg2rad, rad2deg, magnitude, log10, ln and affine scaling.
dB defaults to a 0 dB peak and -120 dB floor; fixed positive references and an
optional floor are configurable. All-zero peak inputs use reference 1. Undefined
real logs, negative power and nonfinite inputs become gaps. Full complex input
is available for amplitude dB, magnitude and affine scaling; other operations
use the selected real component. XY converts Y and points convert Z without
sorting or changing coordinates. Color composites use grayscale height. Results
retain physical axes, carry formula/source provenance in tooltips, and support
normal viewing and export. Value conversions discard FFT/Laplace inverse records.
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
real/imaginary part, phase (rad) or magnitude. Matrix names can be changed
for the session without renaming source files; metadata remains in the selector.
Open file (Ctrl+O) replaces the session; Add file (Ctrl+Shift+O) or dropping
another file appends. File commands and Fit views sit in the matrix panel,
leaving the top of the window for plots. Right-click matrix rows for visibility,
rename, color, processing and export actions; right-clicking selects the editing
target without changing visibility. Plot context menus offer fitting, figure
export and view-specific controls. A 3D right drag still rolls the camera.
The 3D menu's XYZ scale 1:1:1 (data units) action disables automatic height
scaling, sets Z multipliers to one for all visible layers, and resets stretched
XYZ alignments to original coordinates while retaining translation alignments.
It fits the 3D camera without changing its orientation or projection. Equal
data-unit scales do not calibrate pixel coordinates into physical distances.
By default, matrix heights span roughly 30% of the longer XY side; point clouds
keep a height multiplier of one.
Image, signal and derivative context menus offer X:Y scale 1:1 (data units).
Uncheck it for independent axes. The choice persists across single/overlay views;
locked plots link wheel zoom and retain equal unit lengths when resized/exported,
expanding a visible range if necessary. This does not convert physical units.
NPZ/MAT/Excel members appear in a resizable tree with file/member names. Multichannel
matrices are expandable groups without checkboxes; single-channel matrices are
checkable rows without a channel child. Single matrix mode is the default:
clicking a channel or single-channel matrix displays it exclusively; clicking a
multichannel matrix expands its channels without changing visibility.
Hide / Hide all controls appear only in Multiple matrices mode.
Multiple matrices mode allows checkboxes to combine compatible channels, including channels of one matrix,
in independent solid colors. Switching back retains the edited checked channel,
or the first checked channel if the edited one is hidden. In multiple mode,
row clicks only choose the editing target; checkboxes control visibility.
Adding files in single mode retains the list but shows
only the new file's first member. Remove / Remove all release session data without deleting files.
Rename remains in the context menu and on F2; Remove all is folded into Remove's
arrow menu to keep the matrix panel compact.
Indexed signals and XY tables can share a plot; matrices and point clouds form separate groups.
XY alignment supports original coordinates, start/end, center and stretch,
relative to a selectable reference (the first matrix by default). Alignment
only transforms display coordinates; derivatives keep source coordinates.
Z alignment for overlaid surfaces and point clouds supports original, minimum,
maximum, center and stretch relative to the same reference. It is applied after
each layer's height multiplier, using visible full-resolution value bounds.
3D surfaces, clipping caps and slice markers move together; 2D images, signal
values and numeric exports are unchanged. Constant-height stretch uses centering.
2D overlays encode scalar intensity in opacity, and 3D overlays use solid meshes.
RGBA overlays retain explicit byte levels when downsampled; moving profile lines
repaint the full image viewport without rebuilding unchanged image buffers.
Automatic 3D overlay height uses the combined range of visible automatic layers,
so bounding one component cannot excessively magnify an unbounded component.
The first nonempty 3D overlay fits its camera even when loaded through a hidden tab.
Aligned matrix slices use the nearest source row/column and identify its index.
Moving a slice automatically fits the signal and derivative Y ranges by default,
including overlays. Disable Auto Y on slice change in the profile context menu
to retain Y scale. X zoom is unchanged; Fit curve can refit the current plot.
First-time derivative display still fits its data and remains lazily computed.
Both 3D slice styles use the shared 3D color setting, including in overlay mode.
Show Inf / -Inf / NaN markers is off by default, with editable blue/green/magenta
colors per channel. Signals place Inf/-Inf at the visible finite maximum/minimum
and NaN at zero; without finite visible samples the infinity markers also use zero.
Nonfinite X coordinates cannot be plotted. Matrix images mark original pixels
with opaque colors. 1D nonfinite dots default to 3 px; the
per-channel size control accepts 0.5 to 20 px and leaves 2D pixel coloring intact.
Highlight clipped values defaults on; turning it off retains
clamping and normal curve/image/surface colors. Appearance options preserve raw
values, processed numeric export semantics and lazy derivative caches. Figure
exports include the currently enabled annotations.
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
Right-click Export opens an independent modal settings window for selected
slices, current results or original matrices as NPY, MAT (variable 'matrix'),
XLSX, CSV or tab-separated TXT. The left sidebar contains no export controls.
Export channel appears only for multichannel/complex sources and selects the
active real-valued component; uncheck crop/bounds to retain its complete values.
Whole multichannel matrix exports retain every source channel and its axis order;
spatial/sample crop applies across channels and bounds apply to each channel.
Original image export retains all original pixels, including alpha. Slice export
is hidden in signal mode. XY cropping and value bounds can be applied separately.
Hidden/nonfinite samples become NaN in processed arrays. Full-resolution 2D
matrices can become XYZ point clouds (nonfinite points omitted); 1D signals
can become two-row/column XY tables, retaining original sample coordinates.
Color channel exports use grayscale; whole-image export keeps source channels.
Original export preserves the source dtype and complex values.
Complex single-matrix exports first ask for Current channel or Complex data
(real + imaginary), including 1D signals, 2D matrices and their 1D slices.
The matrix panel and export window explicitly identify complex sources.
Both components are preserved without value bounds when choosing Complex data;
Current channel exports only the displayed scalar values. Choosing Current channel
from Export original matrix exports the full component without crop or bounds.
Detection uses the source dtype, including zero imaginary parts. Complex CSV/TXT
produces matching _real/_imag files. Visible-matrix exports keep displayed channels.
XLSX uses one worksheet per matrix (real/imaginary sheets for complex data),
with 1D values in columns. Large integers and NaN/Inf use numeric text. Excel
row/column limits and unsupported precision raise errors; NPY preserves dtypes.
MAT stores 1D arrays as column vectors. Default filenames include the source
member, processing ranges and layout; existing names receive a numeric suffix.
Export scope chooses the selected source, its current channel or all visible matrices.
The 1D slice context menu offers Add visible slices to matrices: each current
curve becomes an independent, unchecked 1D entry in the session. It retains
source-index crop, physical/aligned coordinates, alpha weighting and its own
value-bound settings. Complex sources ask for the displayed scalar channels or
both parts in one complex 1D array (without value bounds), just as slice file
export does. Identical complex slices from one source are added only once;
cancelling any question cancels the batch. RGB(A)/MA views contribute each
displayed trace. Moving/removing the source does
not change these copies. This writes no files and does not persist after closing.
Visible exports apply the displayed channel, crop, value bounds and XY alignment,
retaining each source as a separate full-resolution XY or XYZ table. Camera
zoom, 3D height multipliers and Z alignment are excluded. MAT packs separate named variables;
XLSX packs separate worksheets; NPY/CSV/TXT use one file per matrix. Separate files (including complex text's
real/imaginary pair) each get a save dialog with a descriptive default filename.
All destinations are collected before writing; cancelling cancels the batch.
Real 2D arrays in Array layout also support normalized PNG/BMP: one source cell
per pixel, 8-bit grayscale, finite minimum/maximum mapped to 0/255 after crop/bounds.
Constants and nonfinite gaps become black; entirely nonfinite inputs are rejected.
Complex or multichannel sources require a scalar channel. No axes, colormap,
camera or overlay alignment is baked into these matrix images; use Export figure
for the rendered view. Saves report progress/completion inside the export dialog.
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
the tree. Input range distinguishes full matrices/signals, cropped matrices/signals,
full 1D Slice and cropped 1D Slice, with the selected source row/column named.
Full scopes ignore current X/Y and value bounds. Cropped real channels use the
inclusive X/Y region and Z/value bounds. Finite outliers default to their nearest
bound, with 0/valid maximum/valid minimum alternatives, independently of the
viewer's Clamp/Hide mode. NaN, +Inf and -Inf each offer 0 (default), valid maximum
or valid minimum. Extrema use original finite, in-bound samples from the selected
input, before replacement; an empty reference pool requires zero filling.
Full complex input replaces an entire sample with 0+0j if either component is
nonfinite. Complex phase channels only offer zero filling; nonfinite original
complex samples are phase gaps. Both full complex and phase input ignore Z/value
bounds but retain X/Y cropping. Phase views also disable value bounds in the UI.
Samples are never deleted or compressed; replacement counts are logged and stored
in transform provenance. Original data remain unchanged.
The dialog snapshots row/column, crop and bounds when opened; full Slice spans
the entire selected source axis and crop Slice retains the crop's axis origin.
A completion dialog offers to display only the new result (Yes) or
keep the current view and add it unchecked (No).
FFT uses complete centered spectra; IFFT restores recorded axes and
normalization for generated spectra. Sampling intervals/units, axes, padding,
normalization, precision, optional mean removal and periodic windows are configurable.
XY input must have unique uniformly spaced X. Point clouds are unsupported. Calculations run on
demand in a worker at full resolution. Frequency coordinates are shared by plots,
surfaces, profiles, derivatives and coordinate-table exports. Complex display
offers Real, Imaginary, Magnitude, Phase (rad) and Magnitude (dB). The dB view
uses the selected region's peak as 0 dB and an adjustable floor (default -120 dB).
Data conversion provides custom dB references and degree-valued phase as separate
matrices. Complex data remain intact. Ordinary exported array files do not retain Fourier metadata;
external IFFT requires specifying spectrum order, frequency spacing and normalization.
Windowing, mean removal and value bounds cannot be undone by IFFT.

Requirements:
    Python 3.13+; numpy, opencv-python, Pillow, matplotlib, PySide6, pyqtgraph,
    pyvista, pyvistaqt, vtk, scipy, h5py and openpyxl (requirements-research.txt).
    xlrd is required for legacy .xls input; other formats do not require it.

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
DEPENDENCIES = "numpy opencv-python Pillow matplotlib PySide6 pyqtgraph pyvista pyvistaqt vtk scipy h5py openpyxl xlrd"


def main() -> int:
    """Parse arguments and run the GUI, returning its exit status.

    Side effects:
        Selects PySide6 for this process, imports the viewer package, opens
        a Qt window and runs its event loop. Prints dependency errors.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Browse NPY/NPZ/MAT/Excel/CSV/TXT and images in linked raw-data, 2D image, 3D surface/point-cloud and 1D/XY/"
            " views, with slices and lazy derivatives. "
            "Open a file from the command line or use the matrix panel. Ctrl+O replaces the session; Ctrl+Shift+O or dropping"
            " another file adds it. Single matrix mode shows one channel; Multiple matrices mode overlays compatible data with"
            " separate colors, settings and a selectable alignment reference. Right-click matrices or plots for processing, "
            "fitting and export actions. "
            "Numeric files support dense 1D/2D boolean, integer, real and complex arrays. MAT supports legacy and v7.3 files. "
            "NPZ/MAT/Excel files offer member/sheet selection; Excel and CSV/TXT imports allow ranges and header handling. "
            "Two-row/column arrays can open as XY signals, and three-row/column arrays as XYZ point clouds. Ambiguous shapes "
            "prompt for a choice. Unsupported data and unreadable files show an error dialog. "
            "Images expose bit depth, individual channels, grayscale combinations and RGB/RGBA/monochrome color views. "
            "Complex data offer Real, Imaginary, Magnitude, Phase (rad) and Magnitude (dB). Raw data can copy selections; "
            "8-bit image values also support hexadecimal display. "
            "Crop by source indices or value bounds, select a row/column slice, and adjust 3D sampling and height. "
            "Plot menus offer X:Y=1:1 or XYZ=1:1:1 data scales. Slice plots auto-fit Y by default; disable Auto Y to retain it. "
            "Optional Inf/-Inf/NaN markers have configurable colors and 1D size. Clipped-value highlighting is enabled by "
            "default and can be disabled. Derivatives compute only when requested and reuse unchanged results. "
            "Transform tools create new matrices: Fourier FFT/IFFT, 1D Laplace and its inverse, data conversions (dB, angles, "
            "logs, magnitude, scale/offset), and complex merging from real/imaginary or magnitude/phase channels. "
            "Fourier supports full/cropped matrices and slices, with separate complex/channel handling of invalid values. "
            "Full complex and phase inputs ignore value bounds. Fourier/Laplace require uniform XY sampling; no point clouds. "
            "Review sampling and preprocessing in each dialog. Plain array exports do not retain transform metadata. "
            "Export original matrices, processed results or slices as NPY, MAT, XLSX, CSV or TXT; choose a whole matrix, "
            "one channel or all visible results. Complex sources ask for channel or complex data; text splits real/imaginary files. "
            "A slice menu keeps independent in-memory 1D matrices, asking channel/complex for complex sources. "
            "Signals can export as XY tables and matrices as XYZ point clouds. Real 2D arrays also export as normalized grayscale PNG/BMP. "
            "Export figure opens a preview dialog for the current 2D, 3D, 1D or derivative view. Save PNG/TIFF/JPEG, or "
            "SVG for 2D/1D; set image dimensions, DPI, transparency, title and legend. Zoom, camera and visible styling "
            "are retained. Separate numeric outputs receive suggested filenames."
        ),
        epilog=(f"Dependencies: {DEPENDENCIES} (xlrd only for XLS input). Indices and axis numbers are zero-based. "
                "1D wheel zooms X (XY while 1:1 is locked); Ctrl+wheel zooms XY. 3D middle drag or Ctrl+left drag orbits; "
                "right drag or Alt+middle drag rolls the view."),
    )
    parser.add_argument("file", nargs="?", type=Path, help="File to open; omit for an empty GUI")
    parser.add_argument("--key", help="Initial MAT variable, NPZ member, Excel worksheet or image matrix label (e.g. R, G, B, A, Monochrome)")
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
        importlib.import_module("openpyxl")
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
