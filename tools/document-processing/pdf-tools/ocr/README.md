# PDF OCR

[`../../pdf-ocr.py`](../../pdf-ocr.py) starts the PySide6 desktop tool. The
left column contains recognition and preview settings, the center shows the
original or colored OCR overlay and a read-only text tab, and the right column
contains shared page/bookmark navigation. OCR runs explicitly on the current
page or during export, never on page turns. Preview rendering is debounced by
300 ms; the shared worker accepts one task at a time without a queue.

Settings are grouped into **OCR** (ignored pages, languages and recognition),
**Layout** (tiles and text anchors), **Preprocess** (input-only image cleanup),
and **Preview** (overlay appearance).

The companion [Image OCR](../../image-ocr.py) accepts local files, batch drops and
clipboard images. Each row shows display dimensions and encoded file size. Clipboard
sizes refer to temporary PNGs. Adding an image opens its preview. Recognize current processes the active row;
Recognize all processes the list in order. Recognized text, Copy all and Save
contain only the latest run. GIF and TIFF inputs use their first frame.

Local OCR runs on CPU. Each Vision API mode keeps its own conversation for
each endpoint until the window closes. Successful requests and replies
accumulate across runs. **Context images** in API settings limits all images
in each request (default 5). At 0, the whole selection is sent in one request
and all images in the active conversation carry over to the next request.
With a positive limit, current images take priority.
For seven new images with a limit of five, the second request contains the
last three images of the first group and both remaining images. Earlier text
and replies remain in context. Clear the active conversation or select **Reset
context before each API request** for independent groups. Set the image limit
to one as well for independent single-image requests. Failed, stopped or
unmatched replies do not enter history. Multi-image requests require an ordered
JSON array with one transcription per current image.

**Recognition** stores independent preferences for both modes. Select plain
text, Markdown, a LaTeX fragment or a complete LaTeX document. Document export
wraps the batch in one Unicode ctexart document for XeLaTeX. Markdown has live
preview; both LaTeX formats display source. Math formatting includes inline
and display delimiters, grouping related equation lines, retaining existing
numbers and preserving mathematical bold separately from prose. Choose which
document structures and styles to keep, reading order, line breaks and any
custom instructions. Isolated letters are identified as variables by context.

**API exchange** shows the latest run by HTTP request, labeled with its images. Select Request
or Response to inspect the HTTP method and endpoint, status, JSON or error body.
Image data is abbreviated in the viewer; **Copy raw body** includes the full
serialized payload. Session files are replaced by the next API batch and removed
when the window closes.

**Local formula — PaddleOCR** accepts one tightly cropped equation per image.
Install the optional PaddlePaddle CPU runtime and tokenizers in the
environment running Image OCR. Select **Install model** in formula mode to download
the official `LaTeX_OCR_rec` files (98.9 MiB). Downloads resume at verified
file boundaries. **Uninstall model** removes the downloaded files. Recognition is enabled once the runtime and model are available. The worker loads the PaddleOCR graph directly with Paddle Inference once per batch. This model
recognizes mathematical structure from grayscale input. For a whole screenshot
containing prose and equations, use the Vision API formula mode.

**Formula preview** appears when you select Markdown output or local formula recognition.
It updates as each image completes. Qt WebEngine displays
locally generated HTML from markdown-it-py and MathJax 2 SVG output. Install
local MathJax 2 assets under `share/mathjax` in the Python environment, or reuse
those shipped with Spyder or nbclassic. Without markdown-it-py, only TeX is
typeset. Copy and Save always use the original recognized source.

Both tools gray out missing language extensions. Install one in **Manage models**
and close the dialog to enable it. Removing the last selected extension restores
the default Chinese and English selection.

## Recognition and storage

RapidOCR 3.10 uses small PaddleOCR ONNX models on CPU. The wheel bundles the
PP-OCRv6 small detector/Chinese-Japanese-English recognizer and the v2 angle
classifier (about 30 MiB of models). **Manage models** is available even before
opening a PDF. It lists bundled and extension models, versions, installed sizes
and the total local footprint, with Download / Repair, Verify, Delete and Open
folder actions. The local inventory is offline; only Download contacts the model
host. Downloaded PP-OCRv5 mobile recognizers live in
`ConfigStore.directory()/models/pdf-ocr`. Korean is about 12.9 MiB; Thai is about
7.55 MiB. These are model-file sizes, excluding shared runtime packages.

The catalog reads URLs and SHA-256 hashes from the installed RapidOCR registry.
Downloads are explicit, streamed in the serial worker, and staged beside the
destination. Hash verification and a final cancellation check precede atomic
replacement. Failed/cancelled downloads remove the temporary stage and retain any
old file; retry starts a fresh download (no partial resume). Pause/Stop act between
chunks; a stalled network read can take up to its 10-second inactivity timeout.
Bundled models are read-only. Delete removes just the selected extension file;
inference sessions are released first, and existing PDFs/results remain intact.
Missing or corrupt models stop inference with a manager/repair hint instead of
silently downloading. Active model files are verified before creating sessions.
Updating RapidOCR refreshes the available registry; the GUI does not install or
upgrade Python packages or fetch unlisted model URLs.
The language checklist defaults to Chinese and English. Chinese, Japanese and
English share one multilingual recognizer; Korean/English uses the Korean model.
Selecting Korean together with Chinese or Japanese runs both pipelines, resolving overlapping lines by
recognition confidence; scores are not calibrated across models, so use a
document-specific language selection when possible. Checkboxes select models, not
a strict output-character whitelist. At least one language must remain checked.
Old language presets are migrated when preferences are read; new preferences
store a `languages` list. For local text OCR, no GPU, PaddlePaddle, PaddleX or LLM is
required. Recognition is local; model downloads are the only network operation.
The language list also exposes extension groups: Latin (v5), East Slavic,
Cyrillic, Greek, Arabic, Thai, Devanagari, Tamil and Telugu. Download the matching
model, then check its language/group in OCR settings. English explicitly selected
with these groups retains the bundled English pipeline; Korean/English keeps its
existing single-model behavior. Only selected pipelines are loaded. Selecting
many groups increases memory and inference time; use the document's languages.
The bundled PP-OCRv6 model already declares French, German, Spanish, Portuguese,
Vietnamese and other Latin-script languages; the Latin v5 entry is an optional
specialized alternative. See the
[versioned model routes](https://github.com/RapidAI/RapidOCR/blob/v3.10.0/python/rapidocr/default_models.yaml).

`rapidocr` and `onnxruntime` occupy roughly 84 MiB installed in the tested Windows
Python 3.13 environment, including the bundled models and bytecode. The additional
OmegaConf/FlatBuffers packages and Korean model bring this installation to about
99 MiB; already installed shared dependencies and pip caches are additional. The runtime imports
`cv2`: an existing working OpenCV installation is sufficient, although RapidOCR
declares `opencv-python-headless`. Avoid installing competing OpenCV wheels over
one another; when reusing OpenCV, install RapidOCR with `--no-deps` and provide
its other declared dependencies. The project retains its existing OpenCV choice.

Recognition parameters and preview font/color are saved in the `ocr` section of
`config-pdf-tools.yaml`. Ignore ranges, PDF passwords, results and page pixels are
not persisted. Existing text spans (including invisible OCR) are masked in the
recognition input to avoid duplicate anchors. Annotations are excluded from OCR.
This is additive OCR, not replacement of an existing inaccurate text layer.

Results are cached per page for the active recognition settings. Changing OCR,
tiling or preprocessing parameters clears them; changing anchor margins, overlay
appearance or ignored pages does not. Pause/Stop
take effect between inference calls/pages and while inserting anchors. Completed
page results remain available after stopping. Native inference must finish its
current call; model downloads have chunk-level checkpoints. Pixel previews use the shared
512 MiB/100-page cache. No whole-book image cache is retained.

## Tiles, anchors and preprocessing

Tiled recognition is off by default. When enabled, a page is rendered once
(within the shared 24-megapixel OCR limit), then processed in overlapping square
crops, default 1600 pixels with 20% overlap. The detector's maximum side still
applies to each crop. Tiles run serially with cancellation checkpoints between
calls. Coordinates are mapped to the whole page; overlap midpoints assign each
anchor to one tile, followed by cross-tile overlap suppression for positional
jitter. Nearby horizontal line fragments are joined for text copying and export.
Long words or lines cut by a seam may need a larger overlap or tile.
Reading order remains approximate, particularly for columns and vertical text.

English positions default to words; Characters requests letter coordinates for
English/numeric lines. Chinese character coordinates remain enabled. Horizontal
and vertical anchor margins default to 0%; each value applies on both sides,
relative to the original anchor width/height along its text axes. For example,
10% vertical adds 10% of the original height at both top and bottom; -10% shrinks
each side. Raw cached anchors are immutable. Preview and PDF export use the same
adjustment, without rerunning inference.

Preprocessing defaults to off and never changes source pixels in the output.
Options are grayscale conversion, Auto levels (1st/99th luminance percentiles),
local contrast (CLAHE, configurable clip limit), and either 3×3 median filtering
or gentle bilateral filtering. Denoising precedes contrast; cleanup runs before
tiling, and existing text is masked afterwards. Color is retained unless grayscale
is selected. These operations preserve geometry; no deskew or page warping is
performed. Inspect recognition after enabling cleanup: contrast can amplify noise
and median filtering can remove punctuation or thin strokes. The page preview
continues to show the original scan beneath the recognized text.

## PDF output and anchors

Export adds hidden text to a fresh opening of the source PDF. It does not replace
images, rasterize vectors, recolor text or recompress scans. Original text, OCR,
links, annotations, bookmarks and page labels remain; ignored pages receive no
text. The shared save policy removes encryption and PDF/A identification, writes
to a staged file and publishes only when complete. The source cannot be replaced.

RapidOCR character/word quadrilaterals are normalized in rendered-page space,
then mapped through the page's derotation matrix for insertion. New text uses a
separate subset of MuPDF's CJK font. If any needed characters are missing, a
compact Unicode anchor font is generated with a distinct glyph ID per character
and zero advance for nonspacing marks; it has generic outlines and is used only
in invisible rendering mode 3. This avoids full-font downloads and retains
Unicode mappings for Thai/Indic/Arabic text. Original fonts are not rewritten.
The anchor font is not suitable for visible text. Complex shaping is not
performed: RTL/mixed-direction copying and reading order can differ across PDF
viewers, and word/line anchors remain approximate. The preview draws independently with Qt's
chosen font and color and never enters the exported PDF. Character positions are
estimated by the OCR recognizer: highlighting is approximate, especially for
vertical or curved text. This tool prioritizes usable anchors over transcription
accuracy or complex reading order.

The recognized-text tab can show the current page or all recognized pages with
page separators. At the top of the OCR settings, the ignored-page list shows
physical pages and bookmark titles, followed by a separator. **Add pages** accepts
ranges such as `1,2,5-10`; **Add current** adds the displayed page. Duplicate pages
are merged, **Remove** includes selected rows again, and **Clear** empties the list.
Right-click in Pages or Bookmarks to ignore/include selected
pages; bookmarks refer only to their destination pages, not entire chapters.

Implementation: `model.py` validates settings/results and adjusts anchor margins;
`backend.py` owns inference, `tiling.py` owns overlap geometry and deduplication,
and `preprocessing.py` owns input cleanup; `models.py` owns the trusted registry,
download/checksum/storage logic, `model_dialog.py` owns model management, and
`anchor_font.py` supplies Unicode fallback anchors;
`engine.py` owns masking/coordinate mapping/text insertion; `worker.py` owns source
and result lifetimes; `panel.py` and `app.py` own GUI state. Check with
`python -m unittest discover -s test -p "test_pdf_ocr*.py"`.
