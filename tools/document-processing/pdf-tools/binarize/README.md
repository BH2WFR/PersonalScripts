# PDF binarizer internals

The engine is used by the `../../pdf-binarize.py` GUI. It is imported as
`personal_pdf_tools.binarize`; the launcher/compiler only list the entry.
Preview rendering uses the shared `utils.Pdf.render_page` RGB/pixel-budget helper;
image segmentation and binary encoding remain binarizer-specific.
Dependencies: PyMuPDF >= 1.28, pypdf >= 6, Pillow with libtiff, numpy,
opencv-python and tqdm. They are declared in the root `requirements.txt`.

## Ownership

| Module | Responsibility |
| --- | --- |
| `app.py`, `panel.py` | Desktop window and grouped profile controls |
| `project.py`, `worker.py` | JSON projects and isolated profile-aware processing |
| `settings.py` | Immutable settings, defaults and validation |
| `workflow.py` | Authentication, page skips, safe output and sidecar files |
| `objects.py` | Content parsing, resource isolation, transforms, image jobs and vector colors |
| `raster.py` | Levels, enlargement, sharpening and 1-bit encoding |
| `regions.py` | Region detection, shaded-text cleanup, denoising and crop codecs |
| `chromatic.py` | Colored foreground, sparse frame splitting and text-like color classification |

## Processing

The original document stays in memory. Only image invocations and optionally
vector paint are rewritten. Text byte strings, fonts, OCR rendering modes, page
geometry, clipping, paint order, links, annotations, widgets, metadata and exact
bookmark destinations are retained. PDF/A identification and encryption are
removed by the repository's ordinary PDF save policy. Input files are protected;
existing output PDFs can be replaced after explicit confirmation and a successful
staged export. Optional review sidecars still require unused destinations.

Images inside nested Form XObjects and inline images are supported. Their axis
lengths on the page determine sampling at **Sampling target (DPI)**. By default
each axis is capped at the source image's effective native resolution.
**Render at target DPI** asks the PDF renderer to enlarge a lower-DPI image;
this can preserve visible pixel steps. The separate **Lanczos text enlargement**
resizes the sampled grayscale before binarization. For example, native sampling
of a 96-DPI JPEG followed by 3x Lanczos yields roughly 288-DPI one-bit text.
Both sampling modes reduce higher-DPI images; neither setting changes viewer zoom.
Preview and export use the same policy, saved separately in each profile.
The right-side Images tab lists the displayed page's image placements, PDF
encoding, effective DPI, pixel dimensions and position in points from the page's
top left. Original and processed views list their own elements. Click a row to
outline it in blue; click again, empty space or Esc to clear the outline.
Above the list, page size is shown in points and millimeters. A main-scan DPI
appears when one image covers at least 80% of the page, while preview DPI is
calculated from the actual displayed raster size; PDF pages have no intrinsic DPI.
Detection and crop
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

The vector-color setting defaults to **off**. When on, solid strokes/fills become
black unless their color is white; their geometry stays vector. Source colors
are restored before any following text. Tiling patterns are processed recursively,
retaining their text and vector paths. Gradients and shading patterns are rendered
as separate 1-bit paint images with alpha masks at base DPI, without rasterizing
the surrounding page. Transparency/blending remain PDF graphics-state effects;
black paint may therefore appear gray when the source specifies partial opacity.

The preview uses the same object pipeline and extracts one physical page. It retains
that page's text and annotations; destinations outside the extracted page and the
whole-document outline cannot be included in a one-page preview. Full conversion
retains them. Assign the no-processing profile to pages that should remain unchanged;
new GUI sessions process all pages by default, including covers.
Apply to pages accepts page ranges or `all`; the default profile's page ranges
are hidden in the left list to keep it compact. The shared range parser also
recognizes `none` as an empty selection, which cannot assign a profile.
The page dialog offers **All / Odd / Even** radio buttons synchronized with
`|odd` / `|even` suffixes; All retains the entire entered range.

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
Detection combines gray texture with a separate color-foreground pass. The latter
retains small colored text/icons and large illustrations, suppresses pale paper
and color fringes next to neutral ink, and splits sparse decorative frames so
their body text can still be binarized. Very faint colors can fall below detection;
use Red boxes to review difficult pages.

**Colored text mode** defaults to **Follow illustration settings**. The optional
Color4/Color8 paths encode text-like colored strokes in 16/256 indexed colors,
with separate contrast (default 1.5, 1 disables it), no dithering, and lossless
Flate. Detection is geometric/color-based, not OCR: small monochrome icons can
qualify too. Text embedded in a larger illustration follows that illustration;
explicit imported regions retain their own resolved settings. Old projects load
with Follow, and new settings persist independently in each profile.

**Whiten text crop background** is an independent, initially disabled option
for detected colored text, including Follow mode. Pixels become pure white when
all source RGB channels reach **Text crop white point** (default 235). Lower
values remove more background but may erase pale strokes. This runs before crop
contrast and palette quantization; these crops use Flate, with a reserved white
palette entry, to keep the cleaned pixels exactly white. It does not change
ordinary illustrations or the black/white points for binary text.

**Whiten image crop background** separately cleans automatically protected
illustrations and uncertain shaded-text panels. It defaults off, with an
**Image crop white point** of 235. The same RGB test runs before contrast and
quantization, with 255 leaving the source unchanged. Detected colored text keeps
its own whitening controls, even in Follow mode; imported region lists remain
authoritative. The image codec is retained to avoid unexpectedly inflating large
illustrations: JPEG can reintroduce near-white pixels, while Flate preserves
cleaned white exactly. Lower white points can remove pale illustration details.

The binary background always uses lossless CCITT Group 4, which has no quality
parameter. `keep` and `gray8` use JPEG (quality 30 by default) or lossless Flate;
`gray8` removes color without reducing the 256 available gray levels. `gray2`,
`gray4`, `color2`, `color4` use genuine packed 2/4-bit Flate images (4/16 levels or
palette colors). `color8` uses 8-bit palette indices (256 colors), unlike `gray8`
which removes color. Quantization/contrast can lose detail; Flate preserves the
resulting indices exactly. Dithering and general crop contrast default off.

## Optional review files

The GUI Output tab controls workers, automatic preview opening and optional review
files. Region JSON is bound to the source SHA-256 and page count. Rectangles use
normalized displayed-page coordinates, origin top-left, x right/y down. A listed
page overrides detection, `[]` means no boxes, and missing pages use automatic
detection when enabled. Each region can override mode, dither, contrast, quality
and codec, plus `white_point` (255 leaves source white unchanged); page objects can contain `defaults` and `regions`. Later boxes paint on
top. `text`/`text-invert` modes produce cleaned binary text overlays.

The engine maps page rectangles to each intersected image; rotated or sheared
rectangles use enclosing bounds. Sidecar annotations are review PNGs, not PDF
annotations. Export paths derive from the chosen PDF path; skipped pages are
omitted. The JSON always records resolved crop settings.

Run regression checks from the repository root with:

```text
conda run -n base python -m unittest discover -s test -p "test_pdf_binarize*.py"
```
