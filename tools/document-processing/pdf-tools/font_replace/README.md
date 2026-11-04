# PDF Font Replace

Run `../../pdf-font-replace.py` or select `pdf-font-replace`
in the repository launcher. Requires PySide6, PyMuPDF >= 1.28, fonttools and tqdm;
the implementation lives in this package, loaded as `personal_pdf_tools.font_replace`.

## Workflow

1. Open or drop a PDF. The source remains untouched; passwords stay in memory.
2. Under **Match**, scan selected physical pages for source fonts and colors.
   **Scan in pages** opens a page input dialog, defaulting to `all` on each use.
   **Scan all** immediately scans the whole PDF; **Scan current** immediately
   scans only the viewed physical page. Invalid page ranges can be corrected
   in the dialog; Cancel does not start a scan.
   A warning dialog appears when the selected pages contain no discoverable fonts.
   Blank discovery pages means the whole document; `1,2,5-10,-1` is supported.
   Discovery scope only supplies choices. **Apply to pages** (below the tabs)
   defaults to `all` and accepts `1,2,5-10,-1` or `none` through
   `Input.parse_index_ranges`. **Ignore pages** is subtracted from that selection.
   Select fonts from the list, or enter exact PDF font names separated by `;`.
   Columns show bold font names, PDF font type, embedded status and effective
   sizes, with resizable widths and Ctrl/Shift multi-selection. Hover for full
   PDF resource names, encoding, format, object references, scanned page ranges
   and text colors. Statistics cover the discovery scope. These are PDF metadata,
   not inferred names from an installed font; missing metadata is marked unknown.
   Display details never become part of the rule's exact source-name filter.
   Extraction names use strict UTF-8 recovery and resource-backed Unicode aliases
   for legacy byte names; no Chinese or Korean codepage is assumed. Discovery,
   filtering and replacement share this normalization, retaining style suffixes.
   Blank source names, sizes and original colors mean all values.
3. Under **Target**, click **Load installed fonts** or choose a TTF/OTF/TTC/OTC file.
   Type a name or localized alias in the search box. Results appear directly in
   a list with canonical names, aliases and styles; hover for family/file details.
   Click a result to choose it and automatically fill its available style variants.
   **Selected** shows the current target family; filtering does not change it.
   Empty catalogs and unmatched searches have explicit instructions. The
   individual style selectors allow additional files to supply missing variants.
   Required missing styles or glyphs produce an error instead of a fallback.
   **Embed target** defaults to **Used glyphs (subset)**; full-face embedding is
   optional. **Change color only (keep original font)** disables font choices and
   requires only **New text color**. It changes no font programs or text positions.
   **Match text colors** filters original fill/stroke; blank matches all colors.
   Both color fields accept RGB/hex input and offer a color-picker button.
4. **Add rule** appends the draft; **Update selected** replaces the selected rule.
   Either action validates the fields and refreshes the preview. Selecting a rule
   loads its settings. Delete supports multiple rows; Clear removes every rule.
   Arrow buttons move a single rule. Matching always uses original text, and
   the first matching row wins; replacements never cascade into later rules.
5. Toggle **Show original (raw)** to compare against the untouched page. Its
   warning color indicates that replacement results are hidden; the toggle stays
   selected when navigating. Pages and bookmarks are navigation-only.
6. **Export PDF** applies all active rules to a fresh copy of the full document.
   The default is `<source>_fonts.pdf`, numbered when occupied. Existing output
   replacement requires confirmation and uses staged publication; sources cannot
   be overwritten. No matches writes no output. Close discards session state
   after confirmation if committed rules have not been exported.

Rules and editor drafts are session-only, with no project files. Uncommitted
editor changes do not affect previews or exports. Export progress reports pages;
font embedding/cleanup/saving may continue afterward. Initial version waits for
active operations to finish before closing; it has no mid-export cancellation.

## Fidelity and preview ownership

The migrated content-stream engine preserves original character origins,
advances, text strings and drawing order. Glyph ink bounds can differ; there is
no reflow, redaction or page rasterization in exported PDFs. Images, links,
annotations, bookmarks, page labels and unrelated metadata are retained.
The shared save policy removes encryption and PDF/A identification.

Filters use effective page-space sizes, inclusive ranges and 8-bit RGB colors.
Source colors are separated by semicolons; each accepts the shared RGB/hex syntax.
Fill or stroke can match; opacity is retained. Output color affects matched text.
Embedding defaults to a target subset and retained original font programs;
optional cleanup only removes originals not needed by other text or resources.
Horizontal Identity-H and ordinary simple fonts are supported. Vertical/Type3
fonts, ambiguous Unicode mappings, variable targets and inline-image content
streams remain unsupported by the replacement engine.
Color-only rules bypass Unicode/glyph/style decoding and retain original font
resources, including when another rule removes unused originals. Their counts
are reported as text-show runs, separately from font-replaced character counts.

One persistent QProcess owns all MuPDF work on its main thread, with no queued
render jobs. Original views render directly from a retained read-only document.
Processed previews use a fresh one-page copy with physical-page exclusions
remapped correctly. GUI pixels cross the shared RGB buffer and are cached within
512 MiB / 100 physical pages, with separate raw and latest-result slots per page.
Rule revisions invalidate processed reuse. Cache hits are immediate; original
misses skip debounce, and processed misses use one 300 ms timer. Navigation and
settings lock during work, while viewer zoom/pan remain available. Previews render
at 200 DPI subject to the shared pixel cap; export is independent of preview DPI.

| Module | Responsibility |
| --- | --- |
| `engine.py` | Original PDF parsing, rule matching, font embedding and resource isolation |
| `model.py` | Worker serialization and user-expression validation |
| `panel.py` | Draft rule controls and font/color discovery choices |
| `worker.py` | Serial PDF/font discovery, isolated previews and safe export |
| `app.py` | Three-column window, rule ordering, navigation, caching and jobs |

Run `python -m unittest discover -s test -p "test_pdf_font_replace*.py"` through
the project's conda interpreter. Tests use generated redistributable fonts/PDFs
and an offscreen Qt window, including the real background process.
