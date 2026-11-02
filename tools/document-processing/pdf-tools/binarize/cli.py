"""Interactive setup and conversion menu."""

import dataclasses
from pathlib import Path
from typing import cast
import pymupdf
from pymupdf.mupdf import FzErrorBase
from pypdf.errors import PyPdfError
from utils import *
from . import regions
from .settings import *
from .settings import (_Processing, _OutputOptions, _Action, _BinarizeMode, _validate_settings,
                       _PROFILE_LABELS, _IMAGE_MODE_LABELS, _CODEC_LABELS, _DITHER_LABELS)
from .workflow import _binarize_pdf, _preview_pdf

def _configure(
    dpi: int, threshold: int, processing: _Processing,
) -> tuple[int, int, _Processing]:
    """Prompt for current image settings, retaining each value on Enter."""
    mode = cast(_BinarizeMode, Menu.select(
        [MenuOption(["F"], "Fixed threshold", _BinarizeMode.FIXED),
         MenuOption(["S"], "Sauvola adaptive threshold", _BinarizeMode.SAUVOLA)],
        prompt="Binarization mode", default_key="F" if processing.mode is _BinarizeMode.FIXED else "S",
        separator=False,
    ))
    dpi = int(Input.input_number("Base render DPI", default=dpi, min_value=MIN_DPI, max_value=MAX_DPI,
                                 allow_float=False))
    window, k = processing.window, processing.k
    if mode is _BinarizeMode.FIXED:
        threshold = int(Input.input_number(
            "Threshold (higher = more black)", default=threshold,
            min_value=MIN_THRESHOLD, max_value=MAX_THRESHOLD, allow_float=False,
        ))
    else:
        while True:
            window = int(Input.input_number(
                "Sauvola window (odd, in base rendered pixels)", default=window,
                min_value=3, max_value=MAX_SAUVOLA_WINDOW, allow_float=False,
            ))
            if window % 2:
                break
            print(f"{FLRed}Window size must be odd.{CRst}")
        k = float(Input.input_number(
            "Sauvola k (smaller generally retains more black)", default=k,
            min_value=0, min_value_allowed=False, max_value=1,
        ))
    levels = bool(Menu.select(
        [MenuOption(["N"], "Off", False), MenuOption(["Y"], "On (black/white points)", True)],
        prompt="Adjust levels before binarizing?", default_key="Y" if processing.levels else "N",
        inline=True, separator=False,
    ))
    black_point, white_point = processing.black_point, processing.white_point
    if levels:
        black_point = int(Input.input_number(
            "Black point (darker values become black)", default=black_point,
            min_value=0, max_value=GRAY_LEVELS - 2, allow_float=False,
        ))
        white_point = int(Input.input_number(
            "White point (lighter values become white)", default=max(white_point, black_point + 1),
            min_value=black_point + 1, max_value=GRAY_LEVELS - 1, allow_float=False,
        ))
    upscale = int(Input.input_number(
        "Upscale factor (Lanczos; 2x uses about 4x image memory)", default=processing.upscale,
        min_value=DEFAULT_UPSCALE, max_value=MAX_UPSCALE, allow_float=False,
    ))
    sharpen = bool(Menu.select(
        [MenuOption(["N"], "Off", False), MenuOption(["Y"], "On (Unsharp Mask)", True)],
        prompt="Sharpen before binarizing?", default_key="Y" if processing.sharpen else "N",
        inline=True, separator=False,
    ))
    radius, percent = processing.sharpen_radius, processing.sharpen_percent
    if sharpen:
        radius = float(Input.input_number(
            "Sharpening radius (base rendered pixels)", default=radius, min_value=0,
            min_value_allowed=False, max_value=MAX_SHARPEN_RADIUS,
        ))
        percent = int(Input.input_number(
            "Sharpening amount (%)", default=percent, min_value=1,
            max_value=MAX_SHARPEN_PERCENT, allow_float=False,
        ))
    return dpi, threshold, dataclasses.replace(processing,
        mode=mode, window=window, k=k, sharpen=sharpen, sharpen_radius=radius,
        sharpen_percent=percent, levels=levels, black_point=black_point,
        white_point=white_point, upscale=upscale,
    )


def _toggle(prompt: str, current: bool) -> bool:
    """Prompt for an on/off choice, retaining the current value on Enter."""
    return bool(Menu.select([MenuOption(["N"], "Off", False), MenuOption(["Y"], "On", True)],
                            prompt=prompt, default_key="Y" if current else "N", inline=True, separator=False))


def _configure_enhancements(processing: _Processing) -> _Processing:
    """Guide illustration protection first, then independent noise cleanup."""
    settings = processing.regions
    print(f"\n{FLYellow}Illustration preservation{CRst}")
    print(f"{FGray}Protect detected illustrations from text binarization and compress them separately.\n"
          f"When off, illustrations are binarized; shaded-text cleanup can still protect uncertain text panels.{CRst}")
    enabled = _toggle("Automatically preserve illustrations?", settings.enabled)
    profile, threshold = settings.profile, settings.threshold
    mode, dither, contrast, quality, codec = settings.mode, settings.dither, settings.contrast, settings.quality, settings.codec
    if enabled or settings.input is not None:
        if enabled:
            profile = cast(regions._Profile, Menu.select(
                [MenuOption([value.value], label, value) for value, label in _PROFILE_LABELS.items()],
                prompt="Detection profile", default_key=profile.value, separator=False))
            cutoff = (regions._PROFILE_THRESHOLDS[profile]
                      if threshold is None or profile != settings.profile else threshold)
            threshold = float(Input.input_number("Region threshold (higher = fewer boxes)", default=cutoff,
                                                 min_value=.1, max_value=2))
        mode = cast(regions._Mode, Menu.select(
            [MenuOption([value.value], label, value) for value, label in _IMAGE_MODE_LABELS.items()],
            prompt="Protected image mode", default_key=mode.value, separator=False))
        if mode in (regions._Mode.KEEP, regions._Mode.GRAY8):
            codec = cast(regions._Codec, Menu.select(
                [MenuOption([value.value], label, value) for value, label in _CODEC_LABELS.items()],
                prompt="Illustration compression", default_key=codec.value, separator=False))
            if codec is regions._Codec.JPEG:
                quality = int(Input.input_number("JPEG crop quality (CCITT background is always lossless)",
                    default=quality, min_value=1, max_value=95, allow_float=False))
        else:
            dither = cast(regions._Dither, Menu.select(
                [MenuOption([value.value], label, value) for value, label in _DITHER_LABELS.items()],
                prompt="Dithering (can increase size)", default_key=dither.value, separator=False))
        contrast = float(Input.input_number("Crop contrast (1 = off)", default=contrast, min_value=1, max_value=4))
    print(f"\n{FLYellow}Noise and background cleanup{CRst}")
    denoise = _toggle("Remove isolated binary specks (also works without illustration protection)?", settings.denoise)
    area, distance = settings.denoise_area, settings.denoise_distance
    if denoise:
        area = float(Input.input_number("Maximum speck area at 240 DPI", default=area,
                                       min_value=0, min_value_allowed=False, max_value=100))
        distance = float(Input.input_number("Required distance from other ink at 240 DPI", default=distance,
                                           min_value=1, max_value=100))
    clean = _toggle("Clean shaded text (auto polarity; preserve uncertain panels; requires Sauvola)?", settings.clean_background)
    if clean:
        effective_codec = codec if mode in (regions._Mode.KEEP, regions._Mode.GRAY8) else regions._Codec.FLATE
        print(f"{FGray}Gradient fills become white; flat reversed labels stay white-on-black.\n"
              f"Uncertain text panels use {mode.value}/{effective_codec.value} without contrast enhancement"
              f"{f' (quality {quality})' if effective_codec is regions._Codec.JPEG else ''}. Preview to check lettering.{CRst}")
    if clean and processing.mode is not _BinarizeMode.SAUVOLA:
        print(f"{FLCyan}Switching to Sauvola for background cleanup.{CRst}")
        processing = dataclasses.replace(processing, mode=_BinarizeMode.SAUVOLA)
    settings = dataclasses.replace(settings, enabled=enabled, profile=profile, threshold=threshold, mode=mode,
        dither=dither, contrast=contrast, quality=quality, codec=codec, denoise=denoise, denoise_area=area,
        denoise_distance=distance, clean_background=clean)
    return dataclasses.replace(processing, regions=settings)


def _configure_output(
    processing: _Processing, options: _OutputOptions,
) -> tuple[_Processing, _OutputOptions]:
    """Configure workers, viewer and region files through interactive prompts."""
    workers = int(Input.input_number(
        "Parallel image encoders (1 = serial)", default=options.workers,
        min_value=1, max_value=MAX_WORKERS, allow_float=False,
    ))
    open_preview = _toggle("Open exported previews in the default viewer?", options.open_preview)
    region_input = processing.regions.input
    if _toggle("Import a region JSON configuration?", region_input is not None):
        region_input = Path(Input.resolve_input_path(
            str(region_input or ""), prompt="Region JSON path",
        ))
    else:
        region_input = None
    export_regions = _toggle("Save region JSON beside each PDF?", options.export_regions)
    annotate_regions = _toggle("Save box annotations beside each PDF?", options.annotate_regions)
    settings = dataclasses.replace(processing.regions, input=region_input)
    return dataclasses.replace(processing, regions=settings), _OutputOptions(
        workers=workers, open_preview=open_preview,
        export_regions=export_regions, annotate_regions=annotate_regions,
    )


def _processing_for_output(
    processing: _Processing, options: _OutputOptions, output_path: Path,
) -> _Processing:
    """Derive per-export sidecar paths so repeated previews use fresh destinations."""
    settings = dataclasses.replace(
        processing.regions,
        export=output_path.with_suffix(".regions.json") if options.export_regions else None,
        preview_dir=output_path.with_name(f"{output_path.stem}_regions") if options.annotate_regions else None,
    )
    regions._validate(settings)
    return dataclasses.replace(processing, regions=settings)


def _configure_session(
    dpi: int, threshold: int, processing: _Processing, options: _OutputOptions,
) -> tuple[int, int, _Processing, _OutputOptions]:
    """Run the same complete, ordered setup on first use and later adjustments."""
    print(f"\n{FLYellow}PDF elements{CRst}")
    print(f"{FGray}Only images are processed. Native text, OCR and interactive objects are retained.{CRst}")
    processing = dataclasses.replace(processing, vectors=_toggle(
        "Also convert vector colors (non-white to black; white stays white)?", processing.vectors))
    print(f"\n{FLYellow}Image text processing{CRst}")
    dpi, threshold, processing = _configure(dpi, threshold, processing)
    processing = _configure_enhancements(processing)
    if _toggle("Change advanced output settings (workers, viewer, region files)?", False):
        processing, options = _configure_output(processing, options)
    return dpi, threshold, processing, options


def main() -> int:
    """Run the interactive scan-compression menu without command-line options.

    Returns:
        Zero after conversion or quitting, or one if the input cannot be opened.

    Prompts for paths, settings and opening passwords; writes new PDFs and
    optional region review files. Conversion errors return to the menu.
    Existing files and the source are never overwritten.
    """
    # ── introduction and input ──────────────────────────
    Console.print_banner("PDF BINARIZE")
    description = (
        "Compress image objects with 1-bit text and optional illustration crops.\n"
        "Keep native text, OCR, links, annotations and bookmarks; optionally blacken vectors.\n"
        "Preview before converting. CCITT is lossless; JPEG crop quality defaults to 30."
    )
    print(f"{FGray}{description}{CRst}")
    dpi, threshold, processing = DEFAULT_DPI, DEFAULT_THRESHOLD, DEFAULT_PROCESSING
    options = _OutputOptions()
    try:
        input_path = Path(Input.resolve_input_path("", prompt="Input PDF path"))
        if not input_path.is_file():
            raise FileNotFoundError(f"Input PDF not found: {input_path}")
        dpi, threshold, processing, options = _configure_session(dpi, threshold, processing, options)

        # ── preview / adjustment / final conversion loop ─────────
        while True:
            details = (f"threshold={threshold}" if processing.mode is _BinarizeMode.FIXED
                       else f"window={processing.window}, k={processing.k:g}")
            levels_info = f"{processing.black_point}/{processing.white_point}" if processing.levels else "off"
            settings = processing.regions
            print(f"\n{FGray}Vector colors: {'non-white to black' if processing.vectors else 'unchanged'}.{CRst}")
            print(f"\n{FLCyan}{dpi} base DPI; {processing.mode.value}; {details}; "
                  f"levels={levels_info}; upscale={processing.upscale}x ({dpi * processing.upscale} DPI); "
                  f"sharpen={'on' if processing.sharpen else 'off'}{CRst}")
            if settings.enabled or settings.input is not None:
                codec = settings.codec if settings.mode in (regions._Mode.KEEP, regions._Mode.GRAY8) else regions._Codec.FLATE
                quality_info = f"; JPEG quality={settings.quality}" if codec is regions._Codec.JPEG else ""
                detection_info = (f"auto ({settings.profile.value}, threshold={settings.cutoff:g})"
                                  if settings.enabled else "imported regions only")
                print(f"{FLCyan}Illustration protection: {detection_info}; "
                      f"image={settings.mode.value}/{codec.value}{quality_info}{CRst}")
            else:
                print(f"{FLCyan}Illustration protection: off; illustrations will be binarized with text.{CRst}")
            print(f"{FGray}Denoise={'on' if settings.denoise else 'off'}; "
                  f"background cleanup={'on' if settings.clean_background else 'off'}{CRst}")
            if settings.clean_background:
                fallback_codec = (settings.codec if settings.mode in (regions._Mode.KEEP, regions._Mode.GRAY8)
                                  else regions._Codec.FLATE)
                fallback_info = (f"{settings.mode.value}/{fallback_codec.value}, quality {settings.quality}"
                                 if fallback_codec is regions._Codec.JPEG else f"{settings.mode.value}/{fallback_codec.value}")
                print(f"{FGray}Shaded text: local polarity; uncertain panels follow image mode "
                      f"({fallback_info}); imported page regions take priority.{CRst}")
            print(f"{FGray}Workers={options.workers}; open preview={'yes' if options.open_preview else 'no'}; "
                  f"region input={settings.input or 'none'}; "
                  f"save JSON={'yes' if options.export_regions else 'no'}; "
                  f"annotations={'yes' if options.annotate_regions else 'no'}{CRst}")
            action = Menu.select(
                [MenuOption(["1"], "Preview one page", _Action.PREVIEW),
                 MenuOption(["2"], "Change settings", _Action.SETTINGS),
                 MenuOption(["3"], "Convert full PDF", _Action.CONVERT),
                 MenuOption(["0"], "Quit", _Action.QUIT)],
                prompt="Choose action", default_key="3",
            )
            if action is _Action.QUIT:
                return 0
            try:
                if action is _Action.SETTINGS:
                    dpi, threshold, processing, options = _configure_session(dpi, threshold, processing, options)
                    continue
                _validate_settings(dpi, threshold, options.workers, processing)
                if action is _Action.PREVIEW:
                    page_number = int(Input.input_number(
                        "Physical PDF page to preview (-1 = last)", default=1, allow_float=False,
                    ))
                    default_output = input_path.with_name(
                        f"{input_path.stem}_preview_p{page_number}_{processing.mode.value}.pdf",
                    )
                    output_path = Path(Input.resolve_output_path(str(default_output), prompt="Preview PDF path"))
                    effective = _processing_for_output(processing, options, output_path)
                    _preview_pdf(input_path, output_path, page_number, dpi, threshold, effective)
                    print(f"{FLGreen}Preview PDF saved to:{CRst} {FGray}{output_path}{CRst}")
                    if options.open_preview:
                        try:
                            System.open_with_default_app(str(output_path))
                        except OSError as exc:
                            print(f"{FLYellow}Preview saved; could not open the viewer: {exc}{CRst}")
                else:
                    default_output = input_path.with_name(f"{input_path.stem}_binary.pdf")
                    output_path = Path(Input.resolve_output_path(str(default_output), prompt="Output PDF path"))
                    effective = _processing_for_output(processing, options, output_path)
                    _binarize_pdf(input_path, output_path, dpi, threshold, options.workers, None,
                                  processing=effective)
                    print(f"{FLGreen}Compressed PDF saved to:{CRst} {FGray}{output_path}{CRst}")
                    print(f"{FGray}Size: {Console.format_size(input_path.stat().st_size)}"
                          f" -> {Console.format_size(output_path.stat().st_size)}{CRst}")
                    return 0
            except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase, PyPdfError) as exc:
                print(f"{FLRed}Conversion failed: {exc}. Adjust settings or choose another output.{CRst}")
    except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase, PyPdfError) as exc:
        print(f"{FLRed}Binarization failed: {exc}{CRst}")
        return 1




