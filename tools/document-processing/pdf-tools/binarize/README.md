# PDF binarizer internals

The shared engine is used by `../../pdf-binarize.py` (GUI) and
`../../pdf-binarize-old.py` (terminal). It is imported as
`personal_pdf_tools.binarize`; the launcher/compiler only list the entries.
Dependencies: PyMuPDF >= 1.28, pypdf >= 6, Pillow with libtiff, numpy,
opencv-python and tqdm. They are declared in the root `requirements.txt`.

## Ownership

| Module | Responsibility |
| --- | --- |
| `cli.py` | Preserved terminal setup and preview/settings/convert menu |
| `app.py`, `panel.py` | Desktop window and grouped profile controls |
| `project.py`, `worker.py` | JSON projects and isolated profile-aware processing |
| `settings.py` | Immutable settings, defaults and validation |
| `workflow.py` | Authentication, page skips, safe output and sidecar files |
| `objects.py` | Content parsing, resource isolation, transforms, image jobs and vector colors |
| `raster.py` | Levels, enlargement, sharpening and 1-bit encoding |
| `regions.py` | Region detection, shaded-text cleanup, denoising and crop codecs |

## Processing

The original document stays in memory. Only image invocations and optionally
vector paint are rewritten. Text byte strings, fonts, OCR rendering modes, page
geometry, clipping, paint order, links, annotations, widgets, metadata and exact
bookmark destinations are retained. PDF/A identification and encryption are
removed by the repository's ordinary PDF save policy. Input files and existing
outputs are never overwritten.

Images inside nested Form XObjects and inline images are supported. Their axis
lengths on the page determine sampling at the chosen DPI. Detection and crop
extraction use the original image rendering, before levels and binarization.
The thresholded image has white holes underneath separate illustration crops.
They form one isolated PDF transparency group, retaining the source placement,
clipping, transparency and layer visibility. One full-page scan therefore follows
the same image algorithm as before. Text-only pages do not acquire raster images.
Existing 1-bit stencil masks retain their shape and inherited color.

Changed pages and forms receive private resource dictionaries. Before processing,
shared image/form resources on skipped pages are also copied. Read-only fonts and
annotation appearances remain shared. Identical processed image uses at the same
size/settings share the encoded result; differing page region overrides do not.
MuPDF stays on the main thread. A bounded worker queue owns independent Pillow
images; cancellation closes all images and waits for encoders before cleanup.

The vector-color menu defaults to **off**. When on, solid strokes/fills become
black unless their color is white; their geometry stays vector. Source colors
are restored before any following text. Tiling patterns are processed recursively,
retaining their text and vector paths. Gradients and shading patterns are rendered
as separate 1-bit paint images with alpha masks at base DPI, without rasterizing
the surrounding page. Transparency/blending remain PDF graphics-state effects;
black paint may therefore appear gray when the source specifies partial opacity.

The terminal preview uses the same object pipeline and extracts one physical page. It retains
that page's text and annotations; destinations outside the extracted page and the
whole-document outline cannot be included in a one-page preview. Full conversion
retains them. Negative physical page numbers count from the end; terminal skip selections
accept `1-3,5,-1`. After choosing full conversion and its output path, press Enter
to keep physical pages `1,2` unchanged (only `1` for a single-page PDF), or enter
`none` to process every page. Other page selections override this cover default.
An explicit empty `skip_pages` string in internal calls still skips nothing.

## Image settings

Fixed thresholding defaults to 180; Sauvola defaults to window 31, k 0.2, R 128.
Image processing order: detect/crop, levels, Lanczos enlargement, optional Unsharp
Mask, binarize, shaded-text cleanup, isolated-speck removal, white holes and crops.
Levels, sharpening, denoising, shaded cleanup and region detection default off;
upscale defaults to 1. Window and radius are specified in base pixels and scale
with enlargement. Crop resolution stays at base DPI. Speck size/distance scale
from 240 DPI and protect nearby punctuation.

Shaded-text cleanup requires Sauvola and considers local text polarity. Gradient
fills can become white; flat reversed labels retain white text on black. Uncertain
panels follow the selected crop depth without contrast enhancement. Preview is
recommended for faint lettering. Explicit region lists override automatic crops.

Detection profiles text-first/balanced/image-first use 1.0/0.8/0.6 thresholds.
Higher values protect fewer regions; these are heuristic scores, not probabilities.
The binary background always uses lossless CCITT Group 4, which has no quality
parameter. `keep` and `gray8` use JPEG (quality 30 by default) or lossless Flate;
`gray8` removes color without reducing the 256 available gray levels. `gray2`,
`gray4`, `color2`, `color4` use genuine packed 2/4-bit Flate images (4/16 levels or
palette colors). Dithering and contrast enhancement are optional and default off.

## Optional review files

Advanced terminal output settings control workers, automatic preview opening and review
files. Region JSON is bound to the source SHA-256 and page count. Rectangles use
normalized displayed-page coordinates, origin top-left, x right/y down. A listed
page overrides detection, `[]` means no boxes, and missing pages use automatic
detection when enabled. Each region can override mode, dither, contrast, quality
and codec; page objects can contain `defaults` and `regions`. Later boxes paint on
top. `text`/`text-invert` modes produce cleaned binary text overlays.

The engine maps page rectangles to each intersected image; rotated or sheared
rectangles use enclosing bounds. Sidecar annotations are review PNGs, not PDF
annotations. Export paths derive from the chosen PDF path; skipped pages are
omitted. The JSON always records resolved crop settings.

Run regression checks from the repository root with:

```text
conda run -n base python -m unittest discover -s test -p "test_pdf_binarize*.py"
```
