"""Image thresholding, region protection and CCITT encoding; no PDF mutation."""

from contextlib import ExitStack
import io
from PIL import Image, ImageFilter
import numpy as np
from numpy.typing import NDArray
from . import regions
from .settings import *
from .settings import _Processing, _BinarizeMode

def _window_mean(values: NDArray[np.float64], window: int) -> NDArray[np.float64]:
    """Return valid square-window means using a strip-local integral image."""
    integral = np.pad(values, ((1, 0), (1, 0)), mode="constant")
    np.cumsum(integral, axis=0, out=integral)
    np.cumsum(integral, axis=1, out=integral)
    return (integral[window:, window:] - integral[:-window, window:]
            - integral[window:, :-window] + integral[:-window, :-window]) / (window * window)


def _sauvola(gray: Image.Image, window: int, k: float) -> Image.Image:
    """Return a 1-bit Sauvola image, using reflected edges and bounded float strips.

    Input is an 8-bit grayscale image retained by the caller. R is fixed at 128.
    Strips include the entire neighborhood halo so boundaries introduce no seams.
    The caller owns the returned image. No images are written to disk.
    """
    values = np.asarray(gray, dtype=np.uint8)
    radius = window // 2
    padded = np.pad(values, ((radius, radius), (radius, radius)), mode="reflect")
    result = np.empty(values.shape, dtype=np.uint8)
    for start in range(0, gray.height, SAUVOLA_STRIP_ROWS):
        end = min(start + SAUVOLA_STRIP_ROWS, gray.height)
        strip = padded[start:end + window - 1].astype(np.float64)
        mean = _window_mean(strip, window)
        np.square(strip, out=strip)
        variance = np.maximum(_window_mean(strip, window) - mean * mean, 0)
        cutoff = mean * (1 + k * (np.sqrt(variance) / SAUVOLA_R - 1))
        result[start:end] = (values[start:end] > cutoff).astype(np.uint8) * 255
    with Image.fromarray(result) as binary_gray:
        return binary_gray.convert("1", dither=Image.Dither.NONE)


def _threshold_image(gray: Image.Image, threshold: int, processing: _Processing) -> Image.Image:
    """Return an owned 1-bit image after levels, upscaling and optional sharpening.

    Retains the caller's grayscale image and closes intermediates on success or
    failure. Output dimensions are multiplied by upscale. Window/radius settings
    use base rendered pixels; both scale automatically, with the window rounded
    up to odd. No dithering or temporary image files are used.
    """
    with ExitStack() as images:
        working = gray
        if processing.levels:
            span = processing.white_point - processing.black_point
            levels_lut = [round(max(0, min(GRAY_LEVELS - 1,
                (value - processing.black_point) * (GRAY_LEVELS - 1) / span)))
                for value in range(GRAY_LEVELS)]
            working = images.enter_context(working.point(levels_lut))
        scale = processing.upscale
        if scale != DEFAULT_UPSCALE:
            working = images.enter_context(working.resize(
                (working.width * scale, working.height * scale), Image.Resampling.LANCZOS,
            ))
        if processing.sharpen:
            working = images.enter_context(working.filter(ImageFilter.UnsharpMask(
                radius=processing.sharpen_radius * scale, percent=processing.sharpen_percent,
                threshold=SHARPEN_NOISE_THRESHOLD,
            )))
        if processing.mode is _BinarizeMode.SAUVOLA:
            window = processing.window * scale
            if window % 2 == 0:
                window += 1
            return _sauvola(working, window, processing.k)
        threshold_lut = [0 if value < threshold else 255 for value in range(GRAY_LEVELS)]
        return working.point(threshold_lut, mode="1")

def _encode_page(
    rendered: Image.Image, dpi: int, threshold: int, processing: _Processing = DEFAULT_PROCESSING,
    overrides: tuple[regions._Region, ...] | None = None,
) -> bytes | regions._Page:
    """Threshold one rendered page and return an independent CCITT PDF buffer.

    Takes ownership of rendered and closes it even on failure. Each worker owns
    its image and PDF buffer; no PyMuPDF objects enter worker threads.
    """
    settings = processing.regions
    with rendered, io.BytesIO() as page_pdf, ExitStack() as images:
        boxes = overrides if overrides is not None else (regions._detect(rendered, settings) if settings.enabled else ())
        panels = regions._text_panels(rendered) if settings.clean_background else ()
        if overrides is None:
            # Leave imported page lists authoritative, including explicit [].
            # Existing protected illustrations take priority over panel guesses.
            for panel in panels:
                box = regions._pixel_box(panel.rect, rendered.size)
                if not panel.reliable and not any(
                    regions._intersection(box, regions._pixel_box(region.rect, rendered.size)) > 0 for region in boxes
                ):
                    boxes += (regions._Region(panel.rect, mode=settings.mode, dither=settings.dither,
                                              quality=settings.quality, codec=settings.codec),)
        layers: list[regions._Layer] = []
        # Crops retain their native rendered resolution, unaffected by text-only
        # levels, enlargement and sharpening. Map bounds to the enlarged base.
        output_size = (rendered.width * processing.upscale, rendered.height * processing.upscale)
        for region in boxes:
            box = regions._pixel_box(region.rect, rendered.size)
            with rendered.crop(box) as crop:
                layer = regions._encode_crop(crop, regions._pixel_box(region.rect, output_size), region)
                layers.append(layer)
        with rendered.convert("L") as gray:
            binary = images.enter_context(_threshold_image(gray, threshold, processing))
            if settings.clean_background:
                original = images.enter_context(gray.resize(output_size, Image.Resampling.LANCZOS))
                binary = images.enter_context(regions._clean_background(original, binary, panels))
            if settings.denoise:
                binary = images.enter_context(regions._denoise(binary, dpi * processing.upscale, settings))
            for region in boxes:
                binary.paste(1, regions._pixel_box(region.rect, output_size))
            binary.save(page_pdf, format="PDF", resolution=dpi * processing.upscale)
        encoded = page_pdf.getvalue()
        if settings.active:
            annotation = regions._annotation(rendered, boxes) if settings.preview_dir else None
            return regions._Page(encoded, output_size, tuple(layers), boxes, annotation)
        return encoded



