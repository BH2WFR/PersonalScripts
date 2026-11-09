# PDF desktop tools

PDF tools share `config-pdf-tools.yaml` in the directory returned by
`ConfigStore.directory()` (all platforms: `~/.config/PersonalScripts`).
Open/save PDF directories are shared across tools; project, region and font
dialogs keep separate histories. Missing directories fall back to the current
document's directory or the native dialog default. Dragged PDFs update history
after a successful open. Reads/writes lock only during file actions; contention
returns immediately with console/tooltip feedback. API profiles live separately
in llm.yaml through utils.Llm: startup/Load reads, Save/window close writes;
book contents, PDF passwords and recognition conversations are not persisted.
`common/preferences.py` uses the project's shared locked, atomic YAML store;
windows never write their own stale full-file snapshots.

All four desktop tools share **Pause / Resume** and **Stop** for PDF export.
The icon-and-text buttons stay in the preview area's bottom row beside progress;
they are disabled when idle. Font discovery and PDF font scans use them as well.
Pause switches to a play icon and Resume label while a pause is requested.
Pause takes effect at the next safe step and
clears the busy cursor after acknowledgement. Resume continues the same task;
Stop also works while paused and restores editing. Settings stay locked during
pause. A page operation or MuPDF save already in progress finishes first.
Exports stage their PDF before publication, so cancellation during saving retains
an existing output. Brief page previews have no pause/stop controls.
The bookmark recognition queue uses the same footer buttons as PDF export:
Pause waits for the current HTTP request; Stop aborts it and retains completed pages.
During a recognition pause, Pages/Bookmarks remain navigable while structural
editing stays locked; browsing never changes the recognition queue's position.
The command-line compression/decryption tools are unchanged.

`../pdf-split-pages.py` opens the visual page splitter: two left settings groups,
colored numbered crop overlays, and read-only pages/bookmarks with output start
indexes. Move all frames or individual crops, keep pages whole, and export equal
child paper sizes with centered crops and blank padding. See
[split_pages/README.md](split_pages/README.md). It reuses the shared viewer, bounded
cache, serial jobs, RGB transfer, file actions and tooltips; exports never rasterize.

`../pdf-font-replace.py` opens the font replacement GUI: ordered source/target
rules on the left, raw/result comparison in the center, and read-only page/bookmark
navigation on the right. See [font_replace/README.md](font_replace/README.md) for
matching, font discovery and export behavior. It shares the viewer, cache budgets,
RGB transport, serial job runner, file dialogs and tooltip handling below.

`../pdf-bookmarks-add.py` opens the TOC recognition, bookmark editor and page-label
GUI, including its Page labels tab. See [bookmarks/README.md](bookmarks/README.md)
for the workflow, API testing, recognition queue and export behavior. This tool
keeps recognition drafts in memory and has no project files; API preferences are
saved separately. It requires PySide6, PyMuPDF, PyYAML, cryptography, LiteLLM,
OpenAI and HTTPX. Shared `Llm.acompletion` handles text/vision conversations;
GUI inference runs in a cancellable background thread with bounded image context.
Shared optional crop and editable-tree widgets live in `common/`;
the binarizer retains its read-only navigator.

Both GUIs reuse bounded page-cache storage and shared-memory RGB transport;
bookmark previews retain one latest rotation per page within 512 MiB / 100 pages.
`utils.Pdf` owns bounded RGB rendering and generic bookmark/page-label operations.
`utils.Llm` owns cloud/local model presets, payloads, context-image limits and a lazily created Qt API client;
the bookmark package retains only its TOC prompt and book-context construction.
All four GUIs share focus-scoped PgUp/Left/Up and PgDn/Right/Down page shortcuts
in both the viewer and **Pages**. Navigation selects and reveals the current
page in Pages. Plain page keys replace a batch selection with the destination;
Ctrl/Shift retains normal multi-selection without starting a preview. Rendering
temporarily blocks navigation, then restores Pages focus for continued key turns.
`common/navigation.py` owns the shared `PageTree`; `common/viewer.py` owns the
page-key mapping used by both widgets. Clicking the viewer gives it keyboard
focus, including while drawing a TOC crop; keys in text and settings editors
retain their normal editing behavior.
Shared bookmark lists use the theme's indentation minus one en and give the
title the remaining column width. Every cell shows Title, Page and Level in its
tooltip. Right-click offers **Expand all** and **Collapse over level 3** (keep
the first three levels visible), including in read-only tools; these actions
only change the displayed tree.
Both windows install `common/tooltips.py`: widget/action and tree-cell hints wrap
within 250 logical pixels, including long unbroken URLs. The window-scoped filter
also covers controls rebuilt by Close and newly created settings.

The remaining sections describe PDF Binarize.

Run `../pdf-binarize.py` without arguments to open the PySide6/Fusion desktop
application.

Dependencies: PySide6, PyMuPDF >= 1.28, pypdf >= 6, Pillow with libtiff, numpy,
opencv-python, tqdm, PyYAML and cryptography, already declared in the repository requirements.
See `binarize/README.md` for image algorithms,
supported PDF constructs, crop codecs and region JSON semantics.

## Layout and navigation

The left column independently owns the file toolbar, profile list and settings
tabs. The two-column profile list displays names and assigned page ranges, with
twice the previous height (four to twelve visible rows), then scrolls. Its action
buttons sit above the list. Settings use group boxes and separators; hover over
parameter labels for their purpose, tuning direction and suggested starting values.
One right toolbar groups compact page arrows, a page field/count, zoom controls
and the original checkbox with vertical separators. Enter or focus loss jumps pages.
Preview/navigation fill the remaining height; status and export share one bottom row.
Progress appears during export; Pause/Resume and Stop remain visible, disabled when idle.
Drag in one PDF or project JSON,
or use the Open buttons; network-share paths and Unicode filenames are supported.

On Windows, Explorer cannot drop files into a program running as administrator.
This includes a program started by an elevated VS Code/terminal. The title marks
administrator mode and the Open PDF tooltip explains it. Use Open PDF in that
session, or start the tool from a normal, non-elevated terminal to enable drops.

Physical page numbers are one-based; the navigator also displays PDF page labels
when present. The Pages tab lists every page and its profile, while Bookmarks
preserves the PDF's hierarchy. Click either tree to navigate. Non-page bookmarks
remain visible without a page action. The Images tab lists individual image
placements on the displayed original or processed page: encoding, effective DPI,
pixel size and page position. Click one to outline it in blue; click again, empty
space or Esc to clear. It refreshes with the preview after a profile or view change.
Printed page numbers are not OCR-detected.

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
The Images tab reports each image's PDF encoding; there is no separate page-wide
channel or bit-depth information panel.

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

Add copy prompts for a name, initially the current physical page number, and
duplicates the current configuration (default when copying no-processing).
Right-click profiles to rename/delete them or apply them to typed page ranges.
**Apply to pages…** also appears above the list and accepts `1,2,4-10` through the
shared page-range parser. Invalid ranges leave all assignments unchanged.
Page-range fields and dialogs use `common/range_input.py`: **All / Odd / Even**
radio buttons synchronize with `|odd` / `|even` suffixes. All keeps the entire
entered range; the other choices filter physical page numbers. The component
retains each caller's original text field, validation and commit behavior.
Profiles contain complete settings, so later edits to default do not affect custom
copies. Editing a profile affects all pages referring to it. Ctrl-click individual
pages or Shift-click a range in Pages, then click a profile on the left to apply it
to the selection, including when that profile is already current. Modifier-clicks
only select pages: they do not start rendering or lock the next selection. Normal
page turns select one page. Typed-range assignment complements tree selection.
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
PDFs use numbered defaults and require explicit confirmation to replace. Saving an existing project JSON is allowed after the
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
queue. The GUI caches decoded pixels, region boxes and image metadata for at most 100 physical
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
creation. Pause and Stop are cooperative at page/publication boundaries: the current
page's image encoders or PDF save finish first. Pause shows a pending state until
the worker acknowledges it; once paused, processing sleeps and the busy cursor
clears. Resume continues the same export. Stop also works while paused, removes
incomplete output and restores parameter editing so a new export can be started.
Settings remain locked during pause to keep the running export consistent.
Partial publication is removed on handled
failure/cancellation. Optional region/annotation sidecars are published afterwards;
a sidecar error explicitly reports the already saved PDF.

## Module ownership

Both tools' **Close** action releases the PDF, clears cached previews/session
state, and restores the startup window. Unsaved changes use the existing
save/export/discard prompt. Successful exports show a completion dialog; Binarize
includes source/output sizes and percentage change. `Paths.available_path` suggests
unused `_1`, `_2`, … names. Selecting an existing output offers **Overwrite** or
**Return**; replacement is published only after successful staging. Sources cannot
be overwritten. These shared save-dialog rules live in `common/file_actions.py`.

| Module | Responsibility |
| --- | --- |
| `common/viewer.py` | Raster display, zoom, focus-scoped page keys and red/blue overlays |
| `common/navigation.py` | Reusable physical-page, bookmark and image trees |
| `common/pdf_images.py` | Read displayed image placements, encoding and effective DPI |
| `common/bookmark_editor.py` | Optional batch outline editing, hierarchy modes and subtree dragging; `show_level=True` adds a derived middle Level column; `set_editing_enabled(False)` locks mutations while preserving scrolling, selection and navigation |
| `common/tooltips.py` | Window-scoped tooltips with strict width and long-token wrapping |
| `common/file_drop.py` | Route PDF/project drops from child controls to the owning window |
| `common/jobs.py` | Single-request subprocess transport, task-private control markers, progress and failure recovery |
| `common/task_buttons.py` | Reusable Pause/Resume and Stop controls bound to a job runner |
| `common/task_control.py` | Worker checkpoints, cancellation exception and staged PDF publication without Qt |
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
| `binarize/raster.py`, `binarize/regions.py`, `binarize/chromatic.py` | Image algorithms, gray/color segmentation and encoding |

The entry loads this directory as `personal_pdf_tools`. Launcher discovery hides
internals; the compiler recursively stages both subpackages under that valid import
name for either entry. `--pdf-tools-worker` is private process plumbing, not a
user-facing conversion interface. Future tools can reuse common components while
providing their own settings model, panel and worker dispatcher.

Run the engine, project, Qt and integration checks with:

```text
conda run -n base python -m unittest discover -s test -p "test_pdf_binarize*.py"
```
