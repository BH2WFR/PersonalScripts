"""Regression tests for independent scan layers, detection and general denoising.

Requires the ordinary pdf-binarize dependencies. Run with:
conda run -n base python -m unittest discover -s test -p test_pdf_binarize_regions.py
Uses repository tmp/ for temporary PDFs; no source fixtures are modified.
"""

import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import pymupdf

from test_pdf_binarize import ROOT, app, make_source

regions = app.regions


class ScanRegionsTests(unittest.TestCase):
    """Check actual PDF decoders and readable-text boundaries, not just sizes."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="scan-layers-", dir=ROOT / "tmp")
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.source = self.folder / "source.pdf"
        make_source(self.source)

    def config(self, pages: dict[str, object]) -> Path:
        """Write overrides bound to the test source; each test owns its folder."""
        path = self.folder / "regions.json"
        data = {"version": 1, "sha256": regions._identity(self.source), "page_count": 3, "pages": pages}
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_all_crop_modes_actual_pdf_depth_filter_and_white_hole(self) -> None:
        values = np.random.default_rng(4).integers(0, 256, (37, 53, 3), dtype=np.uint8)
        for mode in regions._Mode:
            for dither in regions._Dither:
                with self.subTest(mode=mode, dither=dither), Image.fromarray(values) as image:
                    settings = regions._Settings(enabled=True, mode=mode, dither=dither)
                    region = regions._Region((.1, .1, .9, .9), mode, dither)
                    encoded = app._encode_page(image.copy(), 72, 180, app._Processing(regions=settings), (region,))
                    self.assertIsInstance(encoded, regions._Page)
                    self.assertEqual(len(encoded.layers), 1)
                    with pymupdf.open(stream=regions._assemble(encoded), filetype="pdf") as doc:
                        info = doc[0].get_images()
                        expected_bits = 1 if mode in (regions._Mode.TEXT, regions._Mode.TEXT_INVERT) else (
                            8 if mode in (regions._Mode.KEEP, regions._Mode.GRAY8) else (2 if mode.value.endswith("2") else 4))
                        self.assertEqual(sorted(item[4] for item in info), sorted([1, expected_bits]))
                        base = next(item for item in info if "CCITT" in item[8])
                        pix = pymupdf.Pixmap(doc, base[0])
                        binary = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
                        x0, y0, x1, y1 = regions._pixel_box(region.rect, image.size)
                        self.assertTrue((binary[y0:y1, x0:x1] == 255).all())
                        if expected_bits > 1:
                            crop = next(item for item in info if item[4] == expected_bits)
                            self.assertEqual(crop[8], "DCTDecode" if mode in (regions._Mode.KEEP, regions._Mode.GRAY8) else "FlateDecode")
                            crop_pix = pymupdf.Pixmap(doc, crop[0])
                            self.assertEqual((crop_pix.width, crop_pix.height), (x1 - x0, y1 - y0))
                            if expected_bits in (2, 4):
                                samples = np.frombuffer(crop_pix.samples, dtype=np.uint8).reshape(-1, crop_pix.n)
                                self.assertLessEqual(len(np.unique(samples, axis=0)), 1 << expected_bits)
                        # Exercise rendered placement, not just xref metadata.
                        self.assertEqual(doc[0].get_pixmap().width, image.width)

    def test_gray8_color_conversion_and_full_gray_ramp_without_quantization(self) -> None:
        values = np.random.default_rng(9).integers(0, 256, (40, 256, 3), dtype=np.uint8)
        values[0] = np.arange(256, dtype=np.uint8)[:, None]
        with Image.fromarray(values) as image, image.convert("L") as expected:
            for codec in regions._Codec:
                for dither in regions._Dither:
                    with self.subTest(codec=codec, dither=dither):
                        region = regions._Region((0, 0, 1, 1), mode=regions._Mode.GRAY8, codec=codec, dither=dither)
                        encoded = app._encode_page(image.copy(), 72, 180,
                            app._Processing(regions=regions._Settings(enabled=True)), (region,))
                        with pymupdf.open(stream=regions._assemble(encoded), filetype="pdf") as doc:
                            crop = next(item for item in doc[0].get_images() if item[4] == 8)
                            self.assertEqual(crop[5], "DeviceGray")
                            self.assertEqual(crop[8], "DCTDecode" if codec is regions._Codec.JPEG else "FlateDecode")
                            pix = pymupdf.Pixmap(doc, crop[0])
                            self.assertEqual(pix.n, 1)
                            if codec is regions._Codec.FLATE:
                                self.assertEqual(pix.samples, expected.tobytes())
                                self.assertEqual(len(set(pix.samples[:256])), 256)

    def test_uncertain_color_panel_inherits_selected_gray_mode_and_dither(self) -> None:
        with Image.new("RGB", (60, 60), (180, 60, 30)) as image:
            panel = regions._Panel((.1, .1, .9, .9), reliable=False, reversed=False)
            for mode, bits in ((regions._Mode.GRAY2, 2), (regions._Mode.GRAY4, 4), (regions._Mode.GRAY8, 8)):
                settings = regions._Settings(mode=mode, dither=regions._Dither.ORDERED,
                                             clean_background=True, codec=regions._Codec.FLATE)
                with self.subTest(mode=mode), patch.object(regions, "_text_panels", return_value=(panel,)):
                    encoded = app._encode_page(image.copy(), 72, 180,
                        app._Processing(mode=app._BinarizeMode.SAUVOLA, regions=settings))
                    self.assertEqual(encoded.regions[0].mode, mode)
                    self.assertEqual(encoded.regions[0].dither, settings.dither)
                    with pymupdf.open(stream=regions._assemble(encoded), filetype="pdf") as doc:
                        crop = next(item for item in doc[0].get_images() if item[4] == bits)
                        self.assertEqual(crop[5], "DeviceGray")

    def test_gray8_menu_skips_dither_and_region_json_roundtrips(self) -> None:
        replies = ["y", "", "", "gray8", "flate", "", "n", "n"]
        with patch("builtins.input", side_effect=replies) as prompts, contextlib.redirect_stdout(io.StringIO()):
            processing = app._configure_enhancements(app.DEFAULT_PROCESSING)
        self.assertEqual(processing.regions.mode, regions._Mode.GRAY8)
        self.assertEqual(processing.regions.codec, regions._Codec.FLATE)
        self.assertFalse(any("Dithering" in str(call.args) for call in prompts.call_args_list))
        config = self.config({"1": [{"rect": [0, 0, 1, 1], "mode": "gray8", "codec": "flate"}]})
        loaded = regions._read_config(config, self.source, 3, regions._Settings())
        exported = self.folder / "gray8.json"
        regions._write_config(exported, self.source, 3, loaded)
        self.assertEqual(regions._read_config(exported, self.source, 3, regions._Settings()), loaded)

    def test_packed_gray_roundtrip_odd_width_and_predictor(self) -> None:
        for bits in (2, 4):
            for width in (1, 3, 17, 53):
                levels = 1 << bits
                values = np.tile((np.arange(width) % levels) * (255 // (levels - 1)), (31, 1)).astype(np.uint8)
                with self.subTest(bits=bits, width=width), Image.fromarray(values) as image:
                    mode = regions._Mode.GRAY2 if bits == 2 else regions._Mode.GRAY4
                    encoded = app._encode_page(image.copy(), 72, 180,
                        app._Processing(regions=regions._Settings(enabled=True)), (regions._Region((0, 0, 1, 1), mode),))
                    with pymupdf.open(stream=regions._assemble(encoded), filetype="pdf") as doc:
                        xref = next(item[0] for item in doc[0].get_images() if item[4] == bits)
                        pix = pymupdf.Pixmap(doc, xref)
                        self.assertEqual(pix.samples, values.tobytes())

    def test_palette_constant_color_and_lossless_keep_exact(self) -> None:
        for color in ((10, 120, 230), (133, 133, 133)):
            for mode in (regions._Mode.KEEP, regions._Mode.COLOR2, regions._Mode.COLOR4):
                with self.subTest(color=color, mode=mode), Image.new("RGB", (19, 13), color) as image:
                    region = regions._Region((0, 0, 1, 1), mode=mode, codec=regions._Codec.FLATE)
                    encoded = app._encode_page(image.copy(), 72, 180,
                        app._Processing(regions=regions._Settings(enabled=True)), (region,))
                    with pymupdf.open(stream=regions._assemble(encoded), filetype="pdf") as doc:
                        xref = next(item[0] for item in doc[0].get_images() if item[4] > 1)
                        pix = pymupdf.Pixmap(doc, xref)
                        if pix.n == 1:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        self.assertEqual(pix.samples, image.tobytes())

    def test_denoise_general_dpi_scaled_and_nearby_punctuation_preserved(self) -> None:
        with Image.new("1", (100, 100), 1) as image:
            draw = ImageDraw.Draw(image)
            draw.rectangle((30, 20, 35, 45), fill=0)
            draw.point((39, 45), fill=0)  # punctuation close to a glyph
            draw.point((80, 80), fill=0)  # isolated scan noise
            draw.line((60, 20, 60, 24), fill=0)  # narrow meaningful stroke
            original = image.tobytes()
            for scale in (1, 2, 3):
                with image.resize((100 * scale, 100 * scale), Image.Resampling.NEAREST) as scaled:
                    for enabled in (False, True):
                        settings = regions._Settings(enabled=enabled, denoise=True)
                        encoded = app._encode_page(scaled.convert("L"), 240 * scale, 180,
                                                   app._Processing(regions=settings), () if enabled else None)
                        payload = regions._assemble(encoded) if isinstance(encoded, regions._Page) else encoded
                        with pymupdf.open(stream=payload, filetype="pdf") as doc:
                            pix = pymupdf.Pixmap(doc, doc[0].get_images()[0][0])
                            values = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
                            self.assertEqual(values[80 * scale, 80 * scale], 255)
                            self.assertEqual(values[45 * scale, 39 * scale], 0)
                            self.assertEqual(values[22 * scale, 60 * scale], 0)
            self.assertEqual(image.tobytes(), original)

    def test_denoise_keeps_dotted_line_and_does_not_touch_protected_pixels(self) -> None:
        with Image.new("L", (100, 100), 255) as image:
            draw = ImageDraw.Draw(image)
            for x in range(10, 80, 5):
                draw.point((x, 20), fill=0)
            draw.point((90, 90), fill=0)
            region = regions._Region((.8, .8, 1, 1), codec=regions._Codec.FLATE)
            encoded = app._encode_page(image.copy(), 240, 180,
                app._Processing(regions=regions._Settings(enabled=True, denoise=True)), (region,))
            with pymupdf.open(stream=regions._assemble(encoded), filetype="pdf") as doc:
                base_xref = next(item[0] for item in doc[0].get_images() if item[4] == 1)
                samples = pymupdf.Pixmap(doc, base_xref).samples
                self.assertTrue(all(samples[20 * 100 + x] == 0 for x in range(10, 80, 5)))
                crop_xref = next(item[0] for item in doc[0].get_images() if item[4] == 8)
                self.assertEqual(pymupdf.Pixmap(doc, crop_xref).samples, image.crop((80, 80, 100, 100)).tobytes())

    def test_detector_rejects_gray_text_and_binary_antialiased_arrows(self) -> None:
        for kind in ("text", "arrow"):
            with Image.new("RGB", (1200, 1700), "white") as image:
                draw = ImageDraw.Draw(image)
                if kind == "text":
                    draw.rectangle((100, 300, 700, 650), fill=(215, 215, 215))
                    font = ImageFont.load_default(size=24)
                    for y in range(330, 630, 45):
                        draw.text((130, y), "Readable text should become black", font=font, fill=(90, 90, 90))
                else:
                    draw.line((100, 400, 1000, 400), fill=(80, 80, 80), width=9)
                    draw.polygon(((1000, 400), (950, 350), (950, 450)), fill=(80, 80, 80))
                    draw.ellipse((200, 600, 600, 1000), outline=(80, 80, 80), width=9)
                with image.filter(ImageFilter.GaussianBlur(.6)) as blurred, io.BytesIO() as stream:
                    blurred.save(stream, "JPEG", quality=45)
                    stream.seek(0)
                    with Image.open(stream) as scan:
                        for profile in regions._Profile:
                            with self.subTest(kind=kind, profile=profile):
                                self.assertEqual(regions._detect(scan, regions._Settings(profile=profile)), ())

    def test_detector_profiles_are_monotone_and_threshold_overrides_profile(self) -> None:
        with Image.new("RGB", (1200, 1700), "white") as image:
            texture = np.random.default_rng(8).integers(60, 230, (300, 400), dtype=np.uint8)
            texture = cv2.GaussianBlur(texture, (31, 31), 0)
            texture = cv2.normalize(texture, None, 70, 230, cv2.NORM_MINMAX).astype(np.uint8)
            image.paste(Image.fromarray(texture), (150, 300))
            counts = [len(regions._detect(image, regions._Settings(profile=profile))) for profile in regions._Profile]
            self.assertGreater(counts[-1], 0)
            self.assertEqual(counts, sorted(counts))
            a = regions._detect(image, regions._Settings(profile=regions._Profile.TEXT_FIRST, threshold=.6))
            b = regions._detect(image, regions._Settings(profile=regions._Profile.IMAGE_FIRST))
            self.assertEqual(a, b)

    def test_cleanup_preserves_white_counters_and_reversed_heading(self) -> None:
        with Image.new("RGB", (1200, 1700), "white") as image:
            draw = ImageDraw.Draw(image)
            draw.ellipse((10, 10, 80, 80), fill=(80, 80, 80))
            draw.ellipse((30, 30, 60, 60), fill="white")
            draw.rectangle((100, 200, 1100, 300), fill=(140, 140, 140))
            draw.text((160, 225), "READABLE TITLE 123", font=ImageFont.load_default(size=42), fill="white")
            with image.convert("L") as gray, app._sauvola(gray, 31, .08) as thresholded:
                with regions._clean_background(image, thresholded) as base:
                    original = np.asarray(gray)[210:290, 120:1000]
                    result = np.asarray(base)[210:290, 120:1000]
                    self.assertTrue(result[original > 250].all())
                    self.assertFalse(result[original == 140].any())
                    self.assertEqual(base.getpixel((40, 40)), 255)
                    self.assertEqual(base.getpixel((20, 40)), 0)

    def test_mixed_table_text_both_polarities_stay_black(self) -> None:
        with Image.new("L", (800, 200), 200) as image:
            draw = ImageDraw.Draw(image)
            draw.rectangle((400, 0, 799, 199), fill=120)
            font = ImageFont.load_default(size=28)
            draw.text((60, 70), "DARK TEXT", font=font, fill=70)
            draw.text((460, 70), "LIGHT TEXT", font=font, fill=245)
            gray = np.asarray(image)
            output = regions._text_panel(gray, np.full_like(gray, 255))
            self.assertTrue((output[gray == 70] == 0).all())
            self.assertTrue((output[gray == 245] == 0).all())
            self.assertEqual(int(output[150, 150]), 255)
            self.assertEqual(int(output[150, 650]), 255)

    def test_gradient_dark_text_and_vertical_reversed_text_at_two_scales(self) -> None:
        """Dark gradient ends must clear without sacrificing low-contrast glyphs."""
        with Image.new("L", (1200, 1700), 255) as image:
            gradient = np.tile(np.linspace(125, 225, 800, dtype=np.uint8), (100, 1))
            image.paste(Image.fromarray(gradient), (100, 200))
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default(size=32)
            draw.text((130, 230), "DARK TEXT IN A GRADIENT PANEL", font=font, fill=65)
            draw.rectangle((100, 400, 210, 850), fill=130)
            for y, text in ((440, "A"), (550, "B"), (660, "C")):
                draw.text((135, y), text, font=font, fill=245)
            for scale in (1, 2):
                with self.subTest(scale=scale), image.resize((1200 * scale, 1700 * scale)) as enlarged:
                    panels = regions._text_panels(enlarged)
                    self.assertTrue(any(panel.reliable and panel.reversed for panel in panels))
                    with app._sauvola(enlarged, 31 * scale | 1, .2) as binary:
                        with regions._clean_background(enlarged, binary, panels) as result:
                            values = np.asarray(result)
                            original = np.asarray(enlarged)
                            # Broad gradient ends remain white, including the dark end.
                            self.assertGreater(values[270*scale:285*scale, 120*scale:850*scale].mean(), .99)
                            area = (slice(220*scale, 270*scale), slice(120*scale, 850*scale))
                            self.assertGreater((~values[area])[original[area] <= 66].mean(), .98)
                            area = (slice(420*scale, 800*scale), slice(120*scale, 190*scale))
                            self.assertGreater(values[area][original[area] >= 244].mean(), .98)
                            self.assertLess(values[area][original[area] == 130].mean(), .01)

    def test_plain_gray_text_does_not_become_protected_panel(self) -> None:
        with Image.new("L", (1200, 1700), 255) as image:
            draw = ImageDraw.Draw(image)
            for y in range(100, 1500, 70):
                draw.text((100, y), "Ordinary gray text, not a shaded panel.",
                          font=ImageFont.load_default(size=38), fill=130)
            self.assertEqual(regions._text_panels(image), ())

    def test_uncertain_shaded_text_keeps_original_crop_and_explicit_empty_overrides(self) -> None:
        """Cleanup alone may protect uncertain lettering, but imported [] wins."""
        with Image.new("RGB", (1200, 1700), "white") as image:
            draw = ImageDraw.Draw(image)
            draw.rectangle((100, 200, 900, 400), fill=(150, 150, 150))
            font = ImageFont.load_default(size=38)
            # Equal high-contrast opposite signs close together mimic embossed text.
            for x in range(130, 800, 90):
                draw.text((x, 250), "H", font=font, fill=(60, 60, 60))
                draw.text((x + 25, 250), "H", font=font, fill=(240, 240, 240))
            panels = regions._text_panels(image)
            self.assertTrue(any(not panel.reliable for panel in panels))
            settings = regions._Settings(clean_background=True, codec=regions._Codec.FLATE)
            processing = app._Processing(mode=app._BinarizeMode.SAUVOLA, regions=settings)
            encoded = app._encode_page(image.copy(), 240, 180, processing)
            self.assertIsInstance(encoded, regions._Page)
            self.assertGreater(len(encoded.layers), 0)
            with pymupdf.open(stream=regions._assemble(encoded), filetype="pdf") as doc:
                for layer, region in zip(encoded.layers, encoded.regions):
                    self.assertEqual(region.mode, regions._Mode.KEEP)
                    xref = next(item[0] for item in doc[0].get_images() if item[2:4] == (layer.width, layer.height))
                    pix = pymupdf.Pixmap(doc, xref)
                    with image.crop(layer.box).convert("L") as crop:
                        self.assertEqual(pix.samples, crop.tobytes())
            overridden = app._encode_page(image.copy(), 240, 180, processing, ())
            self.assertEqual(overridden.layers, ())

    def test_cleanup_does_not_restore_original_dark_ink_across_the_whole_page(self) -> None:
        """Respect incoming threshold/levels away from detected shaded panels."""
        with Image.new("L", (1200, 1700), 255) as original, Image.new("1", original.size, 1) as binary:
            ImageDraw.Draw(original).line((100, 100, 900, 100), fill=70, width=2)
            with regions._clean_background(original, binary, ()) as result:
                self.assertEqual(result.tobytes(), binary.tobytes())

    def test_config_precedence_empty_page_source_binding_and_invalid_bounds(self) -> None:
        path = self.config({"1": {"defaults": {"mode": "gray2", "quality": 60},
                           "regions": [{"rect": [0, 0, .5, .5], "quality": 20}]}, "2": []})
        settings = regions._Settings(enabled=True, input=path, quality=10)
        loaded = regions._read_config(path, self.source, 3, settings)
        self.assertEqual(loaded[0][0].quality, 20)
        self.assertEqual(loaded[0][0].mode, regions._Mode.GRAY2)
        self.assertEqual(loaded[1], ())
        self.assertNotIn(2, loaded)
        for change in ({"sha256": "wrong"}, {"page_count": 4},
                       {"pages": {"0": []}}, {"pages": {"1": [{"rect": [0, 0, float("nan"), 1]}]}},
                       {"pages": {"1": [{"rect": [0, 0, 1, 1], "quality": 2.5}]}},
                       {"pages": {"1": [{"rect": [0, 0, 1, 1], "mode": "bogus"}]}}):
            data = json.loads(path.read_text(encoding="utf-8"))
            data.update(change)
            invalid = self.folder / "invalid.json"
            invalid.write_text(json.dumps(data), encoding="utf-8")
            with self.subTest(change=change), self.assertRaises(ValueError):
                regions._read_config(invalid, self.source, 3, settings)

    def test_layered_preview_parallel_serial_skips_geometry_and_source_preserved(self) -> None:
        original = self.source.read_bytes()
        path = self.config({str(n): [{"rect": [.1, .1, .7, .6], "mode": "color2", "dither": "diffusion"}]
                            for n in (1, 2, 3)})
        settings = regions._Settings(input=path, denoise=True)
        processing = app._Processing(upscale=2, regions=settings)
        outputs: list[Path] = []
        main_thread = threading.get_ident()
        assemble = regions._assemble

        def checked_assemble(encoded: regions._Page) -> bytes:
            self.assertEqual(threading.get_ident(), main_thread)
            return assemble(encoded)

        for workers in (1, 3):
            target = self.folder / f"full-{workers}.pdf"
            outputs.append(target)
            with contextlib.redirect_stdout(io.StringIO()), patch.object(regions, "_assemble", side_effect=checked_assemble):
                app._binarize_pdf(self.source, target, 72, 180, workers, "1", processing=processing)
        preview = self.folder / "preview.pdf"
        exported = self.folder / "resolved.json"
        annotated = self.folder / "annotations"
        with contextlib.redirect_stdout(io.StringIO()):
            app._preview_pdf(self.source, preview, 2, 72, 180,
                replace(processing, regions=replace(settings, export=exported, preview_dir=annotated)))
        with pymupdf.open(outputs[0]) as serial, pymupdf.open(outputs[1]) as parallel, pymupdf.open(preview) as one:
            for index in range(3):
                self.assertEqual(serial[index].get_pixmap().samples, parallel[index].get_pixmap().samples)
            self.assertEqual(one[0].get_pixmap().samples, serial[1].get_pixmap().samples)
            self.assertEqual(one[0].rect, serial[1].rect)
            self.assertEqual(serial.get_toc(), [[1, "Chapter", 1], [2, "Nested", 2], [1, "Final", 3]])
            self.assertEqual(serial[0].get_images()[0][4], 8)
        self.assertEqual(set(json.loads(exported.read_text(encoding="utf-8"))["pages"]), {"2"})
        self.assertEqual([p.name for p in annotated.iterdir()], ["page-0002.png"])
        self.assertEqual(self.source.read_bytes(), original)

    def test_invalid_sidecars_prevent_rendering_and_output_overwrite(self) -> None:
        path = self.config({})
        target = self.folder / "output.pdf"
        for settings in (regions._Settings(enabled=True, export=path),
                         regions._Settings(enabled=True, export=target),
                         regions._Settings(input=self.folder / "missing.json")):
            with patch.object(app, "_render_page") as render, self.assertRaises((OSError, ValueError)):
                app._binarize_pdf(self.source, target, 72, 180, 1, processing=app._Processing(regions=settings))
            render.assert_not_called()
            self.assertFalse(target.exists())

    def test_interactive_general_denoise_and_invalid_settings(self) -> None:
        target = self.folder / "general.pdf"
        with (
            patch.object(app.Input, "resolve_input_path", return_value=str(self.source)),
            patch.object(app.Input, "resolve_output_path", return_value=str(target)),
            patch.object(app, "_configure", return_value=(72, 180, app.DEFAULT_PROCESSING)),
            patch("builtins.input", side_effect=["n", "y", "", "", "n", "n", "3", ""]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(app.main(), 0)
        with pymupdf.open(target) as doc:
            self.assertTrue(all(len(page.get_images()) == 1 and page.get_images()[0][4] == 1 for page in doc))
        for settings in (regions._Settings(quality=0), regions._Settings(threshold=float("nan")),
                         regions._Settings(contrast=float("inf")), regions._Settings(denoise_area=float("nan")),
                         regions._Settings(denoise_distance=0), regions._Settings(clean_background=True),
                         regions._Settings(export=self.folder / "invalid.json")):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                app._validate_settings(72, 180, 1, app._Processing(regions=settings))

    def test_interactive_enhancements_enable_denoise_without_regions(self) -> None:
        replies = ["n", "y", "", "", "n"]
        with patch("builtins.input", side_effect=replies), contextlib.redirect_stdout(io.StringIO()):
            settings = app._configure_enhancements(app.DEFAULT_PROCESSING)
        self.assertTrue(settings.regions.denoise)
        self.assertFalse(settings.regions.enabled)
        with patch("builtins.input", return_value=""), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app._configure_enhancements(settings), settings)

    def test_encrypted_region_export_and_layer_failure_leave_source_intact(self) -> None:
        make_source(self.source, password="test-open", aes=True)
        original = self.source.read_bytes()
        config = self.config({"2": [{"rect": [.1, .1, .8, .8]}]})
        settings = app._Processing(regions=regions._Settings(input=config))
        output = self.folder / "encrypted-result.pdf"
        with patch.object(app.Input, "input_password", return_value="test-open"), contextlib.redirect_stdout(io.StringIO()):
            app._binarize_pdf(self.source, output, 72, 180, 3, processing=settings)
        with pymupdf.open(output) as doc:
            self.assertFalse(doc.is_encrypted)
            self.assertEqual(len(doc[1].get_images()), 2)
        failed = self.folder / "failed.pdf"
        with (patch.object(app.Input, "input_password", return_value="test-open"),
              patch.object(regions, "_encode_crop", side_effect=RuntimeError("crop failure")),
              contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "crop failure")):
            app._binarize_pdf(self.source, failed, 72, 180, 3, processing=settings)
        self.assertFalse(failed.exists())
        self.assertEqual(list(self.folder.glob(".pdf-binary-*")), [])
        self.assertEqual(self.source.read_bytes(), original)

    def test_overlapping_regions_paint_in_order_and_keep_crop_resolution(self) -> None:
        with Image.new("RGB", (80, 60), (120, 60, 20)) as image:
            first = regions._Region((.1, .1, .7, .8), mode=regions._Mode.GRAY2)
            last = regions._Region((.3, .3, .9, .9), codec=regions._Codec.FLATE)
            encoded = app._encode_page(image.copy(), 72, 180,
                app._Processing(upscale=2, regions=regions._Settings(enabled=True)), (first, last))
            with pymupdf.open(stream=regions._assemble(encoded), filetype="pdf") as doc:
                pix = doc[0].get_pixmap(dpi=72)
                self.assertEqual(pix.pixel(40, 30), (120, 60, 20))
                self.assertEqual(pix.pixel(0, 0), (0, 0, 0))
                crop = next(item for item in doc[0].get_images() if item[4] == 8)
                self.assertEqual(crop[2:4], (48, 36))

    def test_interactive_region_import_repeated_previews_and_full_export(self) -> None:
        config = self.config({"2": [{"rect": [.1, .1, .7, .6], "mode": "gray2"}]})
        preview_one = self.folder / "first.pdf"
        preview_two = self.folder / "second.pdf"
        complete = self.folder / "complete.pdf"
        with (
            patch.object(app.Input, "resolve_input_path", side_effect=[str(self.source), str(config)]),
            patch.object(app.Input, "resolve_output_path", side_effect=[str(preview_one), str(preview_two), str(complete)]),
            patch.object(app, "_configure", return_value=(72, 180, app.DEFAULT_PROCESSING)),
            patch.object(app.System, "open_with_default_app") as viewer,
            patch("builtins.input", side_effect=["", "", "", "y", "2", "n", "y", "y", "y", "1", "2", "1", "-1", "3", "1"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(app.main(), 0)
            viewer.assert_not_called()
        for path, pages in ((preview_one, {"2"}), (preview_two, {"3"}), (complete, {"2", "3"})):
            data = json.loads(path.with_suffix(".regions.json").read_text(encoding="utf-8"))
            self.assertEqual(set(data["pages"]), pages)
            annotations = path.with_name(f"{path.stem}_regions")
            self.assertEqual({p.name for p in annotations.iterdir()}, {f"page-{int(p):04d}.png" for p in pages})
        with pymupdf.open(preview_one) as preview, pymupdf.open(complete) as full:
            self.assertEqual(preview[0].get_pixmap().samples, full[1].get_pixmap().samples)
            self.assertEqual(full[0].get_images()[0][4], 8)
            self.assertEqual(sorted(item[4] for item in full[1].get_images()), [1, 2])

    def test_output_menu_can_clear_import_and_disable_sidecars(self) -> None:
        config = self.config({})
        processing = app._Processing(regions=regions._Settings(input=config))
        options = app._OutputOptions(workers=2, open_preview=False, export_regions=True, annotate_regions=True)
        with patch("builtins.input", side_effect=["", "", "n", "n", "n"]), contextlib.redirect_stdout(io.StringIO()):
            updated, output = app._configure_output(processing, options)
        self.assertIsNone(updated.regions.input)
        self.assertEqual(output, app._OutputOptions(workers=2, open_preview=False))

    def test_interactive_bad_preview_returns_to_menu_without_overwriting(self) -> None:
        target = self.folder / "existing.pdf"
        target.write_bytes(b"Existing file must survive")
        messages = io.StringIO()
        with (
            patch.object(app.Input, "resolve_input_path", return_value=str(self.source)),
            patch.object(app.Input, "resolve_output_path", return_value=str(target)),
            patch.object(app, "_configure", return_value=(72, 180, app.DEFAULT_PROCESSING)),
            patch("builtins.input", side_effect=["", "", "", "", "1", "1", "0"]),
            contextlib.redirect_stdout(messages),
        ):
            self.assertEqual(app.main(), 0)
        self.assertIn("Conversion failed", messages.getvalue())
        self.assertEqual(target.read_bytes(), b"Existing file must survive")

    def test_first_setup_includes_illustration_protection_before_action_menu(self) -> None:
        target = self.folder / "first-setup.pdf"
        messages = io.StringIO()

        def detect(image: Image.Image, settings: regions._Settings) -> tuple[regions._Region, ...]:
            self.assertTrue(settings.enabled)
            self.assertEqual(settings.mode, regions._Mode.GRAY2)
            self.assertEqual(settings.dither, regions._Dither.ORDERED)
            return (regions._Region((.1, .1, .7, .6), settings.mode, settings.dither),)

        with (
            patch.object(app.Input, "resolve_input_path", return_value=str(self.source)),
            patch.object(app.Input, "resolve_output_path", return_value=str(target)),
            patch.object(app, "_configure", return_value=(72, 180, app.DEFAULT_PROCESSING)),
            patch.object(regions, "_detect", side_effect=detect) as detected,
            patch.object(app.System, "open_with_default_app"),
            patch("builtins.input", side_effect=["y", "", "", "gray2", "ordered", "1", "n", "n", "n", "1", "2", "0"]) as prompts,
            contextlib.redirect_stdout(messages),
        ):
            self.assertEqual(app.main(), 0)
            detected.assert_called_once()
        text = messages.getvalue()
        prompt_text = "\n".join(str(call.args[0]) for call in prompts.call_args_list if call.args)
        self.assertLess(prompt_text.index("Automatically preserve illustrations"), prompt_text.index("Choose action"))
        self.assertNotIn("JPEG quality=30", text)
        with pymupdf.open(target) as doc:
            self.assertEqual(sorted(item[4] for item in doc[0].get_images()), [1, 2])


if __name__ == "__main__":
    try:
        unittest.main()
    except KeyboardInterrupt:
        app.Console.print_keyboard_interrupt_message_and_exit()
