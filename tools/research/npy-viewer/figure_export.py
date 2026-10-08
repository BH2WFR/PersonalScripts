"""Render current plot/camera views as publication images without GUI controls.

Requirements: existing PySide6, pyqtgraph, PyVista, NumPy and Pillow packages.
Usage: FigureExportDialog supplies a live source and options on the Qt thread.
Qt plots paint at output resolution (SVG retains paths/text; images are embedded).
VTK captures the current camera at higher resolution using its existing mesh.
"""

from collections.abc import Callable
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from html import escape
from io import BytesIO
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets
from pyqtgraph.exporters.Exporter import Exporter
from pyqtgraph.exporters.SVGExporter import SVGExporter
from pyqtgraph.graphicsItems.PlotItem.PlotItem import PlotItem
from pyqtgraph.graphicsItems.ImageItem import ImageItem
from pyqtgraph.graphicsItems.PlotDataItem import PlotDataItem

from .plot_support import graphics_scene
from .surface_view import SurfaceCanvas

MAX_FIGURE_PIXELS = 32_000_000
MAX_VTK_CAPTURE_PIXELS = 64_000_000
FIGURE_MARGIN = 6
HEADER_GAP = 6
METERS_PER_INCH = 0.0254


class FigureView(StrEnum):
    """Rendered views available independently of numeric matrix exports."""

    IMAGE = "2D image"
    SURFACE = "3D view"
    SIGNAL = "1D plot / slice"
    DERIVATIVE = "1D derivative"


class FigureFormat(StrEnum):
    """Raster formats for every view, plus SVG for Qt plots."""

    PNG = "png"
    TIFF = "tiff"
    JPEG = "jpg"
    SVG = "svg"


@dataclass(frozen=True)
class FigureOptions:
    """Output dimensions, physical resolution and optional figure annotations.

    Width/height include margins and the heading. A None height follows the
    current plot aspect; an explicit height reflows the plot into that canvas.
    DPI describes print size, independently of the output pixel count.
    Font size only changes the optional title/legend, not the displayed axes.
    """

    width: int = 2400
    dpi: int = 300
    transparent: bool = False
    title: str = ""
    legend: bool = True
    annotation_size: int = 10
    height: int | None = None


@dataclass(frozen=True)
class FigureSource:
    """A live, UI-thread painter and metadata for exactly one displayed view."""

    view: FigureView
    size: QtCore.QSizeF
    background: QtGui.QColor
    foreground: QtGui.QColor
    paint: Callable[[QtGui.QPainter, QtCore.QRectF, bool], None]
    title: str
    stem: str
    legend: tuple[tuple[str, str], ...] = ()
    vector: bool = True
    note: str = ""
    svg: Callable[[QtCore.QSize, bool], bytes] | None = None


def figure_stem(name: str, view: FigureView) -> str:
    """Build a portable suggested filename from the displayed source and view."""
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:140] or "figure"
    suffix = {FigureView.IMAGE: "2d", FigureView.SURFACE: "3d",
              FigureView.SIGNAL: "1d", FigureView.DERIVATIVE: "derivative"}[view]
    return f"{clean}_{suffix}"


@contextmanager
def _hidden_items(items: tuple[QtWidgets.QGraphicsItem, ...]) -> Iterator[None]:
    visible = tuple(item.isVisible() for item in items)
    try:
        for item in items:
            item.hide()
        yield
    finally:
        for item, shown in zip(items, visible):
            item.setVisible(shown)


@contextmanager
def _full_detail(exporter: Exporter) -> Iterator[None]:
    """Use source image/curve samples, restoring screen downsampling afterward."""
    images: list[ImageItem] = []
    curves: list[tuple[PlotDataItem, int, bool, str]] = []
    try:
        for item in exporter.getPaintItems():
            if isinstance(item, ImageItem) and item.autoDownsample:
                images.append(item)
                item.setAutoDownsample(False)
            elif isinstance(item, PlotDataItem):
                ds, auto, method = item.opts["downsample"], item.opts["autoDownsample"], item.opts["downsampleMethod"]
                if auto or ds != 1:
                    curves.append((item, ds, auto, method))
                    item.setDownsampling(ds=1, auto=False, method=method)
        yield
    finally:
        for image in images:
            image.setAutoDownsample(True)
        for curve, ds, auto, method in curves:
            curve.setDownsampling(ds=ds, auto=auto, method=method)


@contextmanager
def _plot_geometry(plot: PlotItem, height: float) -> Iterator[QtCore.QRectF]:
    """Reflow a plot's axes for export and restore its geometry and view state."""
    native: object = plot
    view_box: object = plot.getViewBox()
    if not isinstance(native, QtWidgets.QGraphicsWidget) or not isinstance(view_box, QtCore.QObject):
        raise TypeError("Figure layout requires native PySide6 graphics widgets.")
    geometry = native.geometry()
    minimum = native.effectiveSizeHint(QtCore.Qt.SizeHint.MinimumSize).height()
    if height < minimum + 20:
        raise ValueError("Image height is too small for the axes and heading. Increase height or reduce width / annotations.")
    box = plot.getViewBox()
    state = box.getState()
    changed = abs(geometry.height() - height) > 0.01
    if not changed:
        rect = native.sceneBoundingRect()
        yield rect
        return
    # Freeze source coordinates while changing the plot's aspect. Only the
    # canvas is reflowed: tick text, titles and markers keep their proportions.
    with QtCore.QSignalBlocker(view_box):
        try:
            box.disableAutoRange()
            box.setAspectLocked(False)
            native.setGeometry(QtCore.QRectF(geometry.x(), geometry.y(), geometry.width(), height))
            plot.layout.activate()
            box.setRange(xRange=state["viewRange"][0], yRange=state["viewRange"][1], padding=0)
            for name in ("left", "bottom", "right", "top"):
                axis = plot.getAxis(name)
                axis.setGrid(axis.grid)
            yield native.sceneBoundingRect()
        finally:
            native.setGeometry(geometry)
            plot.layout.activate()
            box.setState(state)
            for name in ("left", "bottom", "right", "top"):
                axis = plot.getAxis(name)
                axis.setGrid(axis.grid)


def plot_source(view: FigureView, plot: PlotItem, widget: QtWidgets.QGraphicsView,
                title: str, stem: str, legend: tuple[tuple[str, str], ...] = (),
                hover_items: tuple[object, ...] = ()) -> FigureSource:
    """Capture a Qt plot's present geometry and paint it without hover cursors.

    Args:
        view: Image, signal or derivative view identifier.
        plot: Live plot, including its axes and any colorbar.
        widget: Checked PySide6 view owning the scene.
        title: Suggested editable figure title.
        stem: Suggested filename without extension.
        legend: Full, unelided (name, color) pairs.
        hover_items: Transient crosshairs to hide only during painting.

    Returns:
        A vector-capable source. It keeps the current data range and styles.

    Raises:
        TypeError: A hover item is not a native PySide6 graphics item.
    """
    native_scene: object = graphics_scene(widget)
    if not isinstance(native_scene, QtWidgets.QGraphicsScene):
        raise TypeError("Plot export requires a PySide6 graphics scene.")
    scene = native_scene
    rect = plot.sceneBoundingRect()
    source_rect = QtCore.QRectF(rect.x(), rect.y(), rect.width(), rect.height())
    hidden: list[QtWidgets.QGraphicsItem] = []
    for item in hover_items:
        if not isinstance(item, QtWidgets.QGraphicsItem):
            raise TypeError("Plot export requires PySide6 graphics items.")
        hidden.append(item)
    background = widget.backgroundBrush().color()
    pen = plot.getAxis("left").textPen().color()
    foreground = QtGui.QColor(pen.name())

    def paint(painter: QtGui.QPainter, target: QtCore.QRectF, transparent: bool) -> None:
        exporter = Exporter(plot)
        height = source_rect.width() * target.height() / target.width()
        with _plot_geometry(plot, height) as current_rect, _hidden_items(tuple(hidden)), _full_detail(exporter):
            try:
                exporter.setExportMode(True, {
                    "antialias": True, "painter": painter,
                    "background": QtGui.QColor(0, 0, 0, 0) if transparent else background,
                    "resolutionScale": target.width() / source_rect.width(),
                })
                scene.render(painter, target, current_rect)
            finally:
                exporter.setExportMode(False)

    def svg(size: QtCore.QSize, transparent: bool) -> bytes:
        # PyQtGraph reconstructs SVG clipping per item; QSvgGenerator alone
        # does not preserve ViewBox clips when zooming into a curve or image.
        height = source_rect.width() * size.height() / size.width()
        with _plot_geometry(plot, height), _hidden_items(tuple(hidden)):
            exporter = SVGExporter(plot)
            exporter.parameters()["width"] = size.width()
            exporter.parameters()["background"] = QtGui.QColor(0, 0, 0, 0) if transparent else background
            with _full_detail(exporter):
                result: object = exporter.export(toBytes=True)
        if not isinstance(result, bytes):
            raise RuntimeError("The SVG renderer did not produce document bytes.")
        return result

    return FigureSource(view, source_rect.size(), background, foreground, paint, title, stem, legend, svg=svg)


def surface_source(canvas: SurfaceCanvas, title: str, stem: str,
                   legend: tuple[tuple[str, str], ...], note: str) -> FigureSource:
    """Capture the existing 3D camera, axes and meshes at increased resolution.

    Args:
        canvas: Initialized VTK canvas with the current visible scene.
        title: Suggested title.
        stem: Suggested filename without extension.
        legend: Optional overlay names and colors.
        note: Description of current mesh sampling shown beside the preview.

    Returns:
        Raster-only source. Export does not change mesh density or the camera.
    """
    width, height = canvas.window_size
    if width <= 0 or height <= 0:
        raise RuntimeError("The 3D viewport is not initialized. Open the 3D tab before exporting.")
    background = QtGui.QColor(*canvas.background_color.int_rgb)
    foreground = QtGui.QColor("#dce5f2" if background.lightness() < 128 else "#263247")

    def paint(painter: QtGui.QPainter, target: QtCore.QRectF, transparent: bool) -> None:
        scale = max(1, math.ceil(target.width() / width))
        capture_height = max(1, round(width * target.height() / target.width()))
        if width * capture_height * scale * scale > MAX_VTK_CAPTURE_PIXELS:
            raise ValueError("3D capture exceeds 64 megapixels. Reduce the output dimensions.")
        original_alpha = canvas.image_transparent_background
        try:
            pixels = canvas.screenshot(return_img=True, transparent_background=transparent,
                                       window_size=(width, capture_height), scale=scale)
        finally:
            canvas.image_transparent_background = original_alpha
        if pixels is None:
            raise RuntimeError("The 3D renderer did not produce an image.")
        array = np.ascontiguousarray(pixels, dtype=np.uint8)
        format_ = QtGui.QImage.Format.Format_RGBA8888 if array.shape[2] == 4 else QtGui.QImage.Format.Format_RGB888
        image = QtGui.QImage(array.data, array.shape[1], array.shape[0], array.strides[0], format_).copy()
        if image.isNull():
            raise RuntimeError("Cannot allocate the 3D capture image.")
        painter.drawImage(target, image)

    return FigureSource(FigureView.SURFACE, QtCore.QSizeF(width, height), background,
                        foreground, paint, title, stem, legend, vector=False, note=note)


def _layout(source: FigureSource, options: FigureOptions) -> tuple[QtGui.QTextDocument, QtCore.QSizeF, QtCore.QRectF]:
    if source.size.width() <= 0 or source.size.height() <= 0:
        raise ValueError("The selected plot has no drawable area.")
    document = QtGui.QTextDocument()
    document.setDocumentMargin(0)
    font = QtGui.QFont(QtWidgets.QApplication.font())
    font.setPointSize(options.annotation_size)
    document.setDefaultFont(font)
    text_option = document.defaultTextOption()
    text_option.setWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(text_option)
    document.setTextWidth(source.size.width())
    sections: list[str] = []
    if options.title.strip():
        sections.append(f"<b>{escape(options.title)}</b>")
    if options.legend and source.legend:
        entries = [f'<span style="color:{QtGui.QColor(color).name()}"><b>—</b></span> {escape(label)}'
                   for label, color in source.legend]
        sections.append(" &nbsp; ".join(entries))
    document.setHtml(f'<div style="color:{source.foreground.name()}">' + "<br>".join(sections) + "</div>")
    header_height = document.size().height() + HEADER_GAP if sections else 0
    logical_width = source.size.width() + 2 * FIGURE_MARGIN
    plot_height = (source.size.height() if options.height is None else
                   options.height * logical_width / options.width - header_height - 2 * FIGURE_MARGIN)
    if plot_height <= 0:
        raise ValueError("Image height leaves no room for the plot. Increase height or reduce the title / legend.")
    rect = QtCore.QRectF(FIGURE_MARGIN, FIGURE_MARGIN + header_height,
                        source.size.width(), plot_height)
    return document, QtCore.QSizeF(logical_width,
                                  rect.bottom() + FIGURE_MARGIN), rect


def figure_size(source: FigureSource, options: FigureOptions) -> QtCore.QSize:
    """Return final pixel dimensions, including wrapped title/legend and margins.

    Raises:
        ValueError: Dimensions/DPI are invalid or output exceeds 32 megapixels.
    """
    if options.width < 64 or (options.height is not None and options.height < 64) or not 36 <= options.dpi <= 2400:
        raise ValueError("Use dimensions of at least 64 pixels and DPI between 36 and 2400.")
    _, size, _ = _layout(source, options)
    height = options.height if options.height is not None else max(1, round(options.width * size.height() / size.width()))
    if options.width * height > MAX_FIGURE_PIXELS:
        raise ValueError("Output exceeds 32 megapixels. Reduce the output dimensions or title/legend size.")
    return QtCore.QSize(options.width, height)


def _paint_figure(painter: QtGui.QPainter, source: FigureSource, options: FigureOptions,
                  size: QtCore.QSize, *, include_plot: bool = True) -> None:
    document, logical, rect = _layout(source, options)
    if not options.transparent:
        painter.fillRect(QtCore.QRect(QtCore.QPoint(0, 0), size), source.background)
    painter.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.TextAntialiasing
                           | QtGui.QPainter.RenderHint.SmoothPixmapTransform)
    # Render the plot directly in output pixels, allowing VTK to select its
    # capture scale and PyQtGraph to adjust export sampling to the target size.
    scale = size.width() / logical.width()
    target = QtCore.QRectF(rect.x() * scale, rect.y() * scale, rect.width() * scale, rect.height() * scale)
    if include_plot:
        source.paint(painter, target, options.transparent)
    painter.save()
    try:
        painter.scale(scale, scale)
        painter.translate(FIGURE_MARGIN, FIGURE_MARGIN)
        document.drawContents(painter)
    finally:
        painter.restore()


def render_figure(source: FigureSource, options: FigureOptions, *, preview_width: int | None = None) -> QtGui.QImage:
    """Render a raster on the Qt thread while preserving source state.

    Args:
        source: Prepared view and its rendering callbacks.
        options: Full output dimensions and appearance settings.
        preview_width: Optional maximum preview width; scales the full layout
            uniformly, including very short or tall custom canvases.
    """
    size = figure_size(source, options)
    if preview_width is not None:
        if preview_width <= 0:
            raise ValueError("Preview width must be positive.")
        width = min(size.width(), preview_width)
        size = QtCore.QSize(width, max(1, round(size.height() * width / size.width())))
    image = QtGui.QImage(size, QtGui.QImage.Format.Format_RGBA8888)
    if image.isNull():
        raise MemoryError("Cannot allocate the output image. Reduce its width.")
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    try:
        _paint_figure(painter, source, options, size)
    finally:
        painter.end()
    image.setDotsPerMeterX(round(options.dpi / METERS_PER_INCH))
    image.setDotsPerMeterY(round(options.dpi / METERS_PER_INCH))
    return image


def _svg_bytes(source: FigureSource, options: FigureOptions, size: QtCore.QSize) -> bytes:
    if source.svg is None:
        raise ValueError("This source has no vector renderer.")
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    generator = QtSvg.QSvgGenerator()
    generator.setOutputDevice(buffer)
    generator.setSize(size)
    generator.setViewBox(QtCore.QRect(QtCore.QPoint(0, 0), size))
    screen = QtGui.QGuiApplication.primaryScreen()
    if screen is not None:
        # Paint at the scene's logical DPI so Qt text retains its measured
        # size. Physical print dimensions are assigned to the final SVG root.
        generator.setResolution(round(screen.logicalDotsPerInchX()))
    generator.setTitle(options.title)
    painter = QtGui.QPainter(generator)
    if not painter.isActive():
        raise OSError("Cannot initialize SVG export.")
    try:
        _paint_figure(painter, source, options, size, include_plot=False)
    finally:
        painter.end()
    root = ET.fromstring(bytes(buffer.data()))
    _, logical, rect = _layout(source, options)
    scale = size.width() / logical.width()
    plot_size = QtCore.QSize(max(1, round(rect.width() * scale)), max(1, round(rect.height() * scale)))
    plot = ET.fromstring(source.svg(plot_size, options.transparent))
    _, _, plot_width, plot_height = (float(value) for value in plot.attrib["viewBox"].split())
    group = ET.SubElement(root, "{http://www.w3.org/2000/svg}g", {
        "transform": f"translate({rect.x() * scale:g},{rect.y() * scale:g}) "
                     f"scale({rect.width() * scale / plot_width:g},{rect.height() * scale / plot_height:g})",
    })
    # Flatten the nested SVG for consumers limited to SVG Tiny (including Qt).
    # Its percentage-sized background must use the original plot viewport.
    for child in plot:
        if child.get("width") == "100%":
            child.set("width", f"{plot_width:g}")
        if child.get("height") == "100%":
            child.set("height", f"{plot_height:g}")
        group.append(child)
    root.set("width", f"{size.width() / options.dpi * 25.4:g}mm")
    root.set("height", f"{size.height() / options.dpi * 25.4:g}mm")
    root.set("version", "1.1")
    root.attrib.pop("baseProfile", None)
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def save_figure(path: Path, format_: FigureFormat, source: FigureSource, options: FigureOptions) -> None:
    """Atomically save a plot with physical resolution metadata.

    Args:
        path: User-selected destination, with overwrite already confirmed.
        format_: PNG/TIFF/JPEG, or SVG for a vector-capable source.
        source: Current view captured by the modal dialog.
        options: Pixel dimensions, DPI, transparency and heading choices.

    Raises:
        ValueError: Unsupported vector/transparency choice or excessive size.
        OSError: Encoding, writing or atomic replacement failed.
    """
    if format_ == FigureFormat.SVG and not source.vector:
        raise ValueError("3D figures support PNG, TIFF and JPEG; SVG is unavailable.")
    if format_ == FigureFormat.JPEG and options.transparent:
        raise ValueError("JPEG cannot preserve transparency. Select PNG or TIFF.")
    size = figure_size(source, options)
    file = QtCore.QSaveFile(str(path))
    if not file.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(file.errorString())
    try:
        if format_ == FigureFormat.SVG:
            encoded = _svg_bytes(source, options, size)
            if file.write(encoded) != len(encoded):
                raise OSError(file.errorString())
        else:
            image = render_figure(source, options)
            pixels = Image.frombytes("RGBA", (image.width(), image.height()), image.constBits().tobytes(),
                                     "raw", "RGBA", image.bytesPerLine())
            data = BytesIO()
            dpi = (options.dpi, options.dpi)
            if format_ == FigureFormat.JPEG:
                pixels.convert("RGB").save(data, format="JPEG", dpi=dpi, quality=95, subsampling=0)
            elif format_ == FigureFormat.TIFF:
                pixels.save(data, format="TIFF", dpi=dpi, compression="tiff_lzw")
            else:
                pixels.save(data, format="PNG", dpi=dpi)
            encoded = data.getvalue()
            if file.write(encoded) != len(encoded):
                raise OSError(file.errorString())
        if not file.commit():
            raise OSError(file.errorString())
    except BaseException:
        file.cancelWriting()
        raise
