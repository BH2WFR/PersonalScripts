# PDF desktop tools

`../pdf-bookmarks-add.py` opens the TOC recognition, bookmark editor and page-label
GUI, including its Page labels tab. See [bookmarks/README.md](bookmarks/README.md)
for the workflow, API testing, recognition queue and export behavior. This tool
keeps drafts in memory and saves only PDFs; it has no project files. It requires PySide6, PyMuPDF
and PyYAML. Shared optional crop and editable-tree widgets live in `common/`;
the binarizer retains its read-only navigator.

Both GUIs reuse bounded page-cache storage and shared-memory RGB transport;
bookmark previews retain one latest rotation per page within 512 MiB / 100 pages.
`utils.Pdf` owns bounded RGB rendering and generic bookmark/page-label operations.
`utils.Llm` owns model settings, presets, payloads and a lazily created Qt API client;
the bookmark package retains only its TOC prompt and book-context construction.
They also share focus-scoped PgUp/Left/Up and PgDn/Right/Down page shortcuts.
Clicking the viewer gives it keyboard focus, including while drawing a TOC crop;
keys in text and settings editors retain their normal editing behavior.

The remaining sections describe PDF Binarize.

Run `../pdf-binarize.py` without arguments to open the PySide6/Fusion desktop
application.

Dependencies: PySide6, PyMuPDF >= 1.28, pypdf >= 6, Pillow with libtiff, numpy,
opencv-python and tqdm, already declared in the repository requirements.
See `binarize/README.md` for image algorithms,
supported PDF constructs, crop codecs and region JSON semantics.

## Layout and navigation

The left column independently owns the file toolbar, profile list and settings
tabs. The profile list fits two to six occupied rows, then scrolls.
One right toolbar groups compact page arrows, a page field/count, zoom controls
and the original checkbox with vertical separators. Enter or focus loss jumps pages.
Preview/navigation fill the remaining height; status and export share one bottom row.
Progress and Cancel appear only during export. Drag in one PDF or project JSON,
or use the Open buttons; network-share paths and Unicode filenames are supported.

On Windows, Explorer cannot drop files into a program running as administrator.
This includes a program started by an elevated VS Code/terminal. The title marks
administrator mode and the Open PDF tooltip explains it. Use Open PDF in that
session, or start the tool from a normal, non-elevated terminal to enable drops.

Physical page numbers are one-based; the navigator also displays PDF page labels
when present. The Pages tab lists every page and its profile, while Bookmarks
preserves the PDF's hierarchy. Click either tree to navigate. Non-page bookmarks
remain visible without a page action. Printed page numbers are not OCR-detected.

The viewer supports cursor-centered wheel zoom, an editable percentage with a `%`
suffix, drag panning, fit page, fit width and 100% (one preview pixel per Qt logical
view pixel). Auto fit is on by default: each page turn fits the whole new page;
turn it off to retain the current zoom. PgUp/Left/Up and PgDn/Right/Down turn pages
only while the viewer has focus, leaving parameter editors' keys alone.
Original/result comparison
retains position on the same page. The original checkbox remains checked across
navigation. Editing processing settings or turning pages while showing originals
colors it amber and explains the state in its tooltip; uncheck it to inspect the
current processed result. Warnings do not reserve a blank row above the page.
No channel/bit-depth/compression information panel is included.

Red boxes toggles detected image-region outlines as independent viewer overlays;
it never alters the image pixels or the exported PDF. Processed previews already
include region coordinates, so showing/hiding their boxes needs no new PDF work.
Showing boxes on an original also runs detection under the current profile and can
take longer than plain original viewing. No-processing pages have no detected boxes.

## Profiles and projects

New PDFs assign every page to `default`; covers are not automatically skipped.
The `default` and `no-processing` built-ins cannot be deleted or renamed. Selecting
a profile assigns it to the selected page(s) and loads its controls. Turning pages selects the
already assigned profile without changing that assignment. `no-processing`
disables processing controls while leaving whole-project output options available.

Add copy duplicates the current configuration (default when copying no-processing).
Profiles contain complete settings, so later edits to default do not affect custom
copies. Editing a profile affects all pages referring to it. Ctrl-click individual
pages or Shift-click a range in Pages, then click a profile on the left to apply it
to the selection, including when that profile is already current. Modifier-clicks
only select pages: they do not start rendering or lock the next selection. Normal
page turns select one page. The old range-entry and Apply button are removed.
Deleting a custom profile requires choosing a replacement for all its references.

Save project writes versioned UTF-8 JSON atomically, including relative PDF and
optional region-input paths, profiles, per-page assignments, output options and
current page/original-view/auto-fit/red-box state. Older projects use auto fit on
and red boxes off. Passwords and preview caches are never saved.
The optional imported region JSON remains a separate file referenced by the project.
If a PDF is missing, locate it using the file chooser. A different page count
offers Choose PDF again, Exit (cancel this opening) or Open another project; the
existing workspace is retained until validation succeeds. Equal page counts do
not assert equal document contents. Relocating a PDF marks the project unsaved.

Export PDF defaults to a new `<source>_binary.pdf` beside the input. Save shown page
exports the current original/result view, optionally opening it externally. Output
PDFs are never overwritten. Saving an existing project JSON is allowed after the
user selects Save; Save as uses the standard overwrite-confirming dialog.
PDF/A identification and encryption are removed by the shared ordinary-PDF policy;
native text, OCR, links, annotations, widgets, geometry and bookmarks remain in
full-document output. Single-page previews cannot retain other-page destinations.

## Preview and process ownership

Cached pages display immediately without a timer, worker request or pixel transfer.
An uncached processed page restarts one 300 ms timer; only the latest selected page
is retained. Original/no-processing views skip this delay even on cache misses;
their first render still needs PDF work.
Numeric fields commit on focus loss/Enter or mouse release; sliders commit on
release. Typing/dragging postpones a pending preview until the edit is committed.
Invalid edits stop preview/export until corrected. Only an actively focused edit
can defer rendering; stale editor flags cannot block profile/original changes.
Request revisions prevent an obsolete result replacing a more recent selection.
Dialogs suspend pending timers.

One persistent QProcess accepts at most one outstanding request. It owns all MuPDF
calls on its main thread. During work, navigation and processing controls are
disabled and the cursor is busy; zoom/pan remain available. There is no render-job
queue. The GUI caches decoded pixels and region metadata for at most 100 physical
pages and 512 MiB, evicting the least recently viewed pages when either limit is
reached. Each page has separate original/processed slots; a new result overwrites
that view's previous settings version. Processed pixels and region overlays must
match the current configuration and region-input path. Plain originals can be
reused after profile edits. The cache is cleared when opening a PDF/project and
on exit; reopen after external changes to the PDF or imported region JSON. Cache
limits cover retained pixels, excluding the current viewer's mipmaps, shared
transfer slot and processing workspace. The worker retains one authenticated read-only
source document, replacing it when the input identity changes. Plain originals
render directly from it without copying pages or running image processing.
Each processed preview starts with a clean page extract, never a previous result.
One lazy shared-memory RGB slot transfers pixels to the GUI without PNG encoding,
base64 or temporary files. The GUI detaches the pixels before another request can
reuse the slot. Both the source handle and shared memory are released on exit.

Image processing uses the selected DPI and the actual crop/text codecs. The final
page is rasterized for display at up to 300 DPI and 16 million pixels; zooming only
scales this display image. Export resolution is unaffected by that display limit.
Full export uses a separate untouched input document and processes pages by profile,
with a separate engine/cache for each configuration. Shared skipped-page resources
remain isolated. Final page order and original document-level objects are retained.

Export stages a PDF beside the destination, then publishes it through exclusive
creation. Cancel is cooperative at page/publication boundaries: the current image
operation or PDF save may finish first. Partial publication is removed on handled
failure/cancellation. Optional region/annotation sidecars are published afterwards;
a sidecar error explicitly reports the already saved PDF.

## Module ownership

| Module | Responsibility |
| --- | --- |
| `common/viewer.py` | Raster display, zoom, focus-scoped page keys and region overlays |
| `common/navigation.py` | Reusable physical-page and bookmark trees |
| `common/file_drop.py` | Route PDF/project drops from child controls to the owning window |
| `common/jobs.py` | Single-request subprocess transport, progress and failure recovery |
| `common/preview_buffer.py` | Bounded RGB shared-memory transport owned by the GUI |
| `common/protocol.py` | JSON value types, with no Qt dependency |
| `binarize/app.py` | Desktop window, project actions and lazy preview scheduling |
| `binarize/preview_cache.py` | Bounded GUI cache, latest per-page views and settings/region matching |
| `binarize/panel.py` | Extensible settings field table and commit rules |
| `binarize/project.py` | Pure configuration/profile model and JSON persistence |
| `binarize/worker.py` | PDF inspection, clean previews and profile-aware export |
| `binarize/workflow.py` | Conversion/preview orchestration and shared review output |
| `binarize/settings.py` | Canonical processing defaults and validation |
| `binarize/objects.py` | Content streams, image objects, vector paint and resource isolation |
| `binarize/raster.py`, `binarize/regions.py` | Image algorithms, segmentation and encoding |

The entry loads this directory as `personal_pdf_tools`. Launcher discovery hides
internals; the compiler recursively stages both subpackages under that valid import
name for either entry. `--pdf-tools-worker` is private process plumbing, not a
user-facing conversion interface. Future tools can reuse common components while
providing their own settings model, panel and worker dispatcher.

Run the engine, project, Qt and integration checks with:

```text
conda run -n base python -m unittest discover -s test -p "test_pdf_binarize*.py"
```
