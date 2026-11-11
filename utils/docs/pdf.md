# PDF utilities

[Utility index](../README.md)

Implementation: [pdf.py](../pdf.py).

## API reference

| Need | Use |
| --- | --- |
| Open a PDF for processing | `with Pdf.open_document(path, password=None, interactive=True) as (document, password): ...`; all PDF tools use this authenticated context manager for input files; closes on success, failure, or cancellation; reuse the returned password with `interactive=False` for secondary/background readers |
| Allocate a private PDF object | `Pdf.new_object(document, value="<<>>", data=None) -> int`; adds a new object and optional decoded stream in memory, without changing a source xref |
| Resolve a PDF resource dictionary | `Pdf.read_dictionary(document, xref, key) -> str`; direct/indirect dictionary syntax, null becomes empty; child references remain shared; used by font replacement and image binarization |
| Authenticate an already open PDF | `Pdf.unlock(document, password=None, interactive=True) -> str`; validates PDF input, silently handles empty-password protection, tries a supplied password, otherwise prompts privately with retry and cancellation; False raises instead of prompting; does not recover a password from an already authenticated document |
| Detect PDF/A identification | `Pdf.has_pdfa_identification(document) -> bool`; read-only check for XMP identification elements/attributes, independent of encryption; namespace declarations alone do not count; malformed PDF/A XMP raises ValueError; does not validate PDF/A conformance |
| Save an ordinary PDF | `Pdf.save_new(document, output_path, compact=True, overwrite=False) -> None`; removes encryption and PDF/A identification while retaining other metadata; default exclusive creation cleans its partial file on failure; explicitly authorized `overwrite=True` stages beside the destination before replacement and rejects the source; use `compact=False` for continued editing to preserve live object references; PyMuPDF loads lazily |
| Read effective PDF page labels | `Pdf.read_page_labels(document) -> list[str]`; preserves blank labels, falls back to physical page numbers when no label rules exist |
| Render a bounded PDF preview | `Pdf.render_page(page, dpi=200, rotation=0, max_pixels=12_000_000, annotations=True) -> Pixmap`; opaque RGB, extra clockwise rotation, integer rounding kept inside pixel budget; no Qt or file writes |
| Rotate within a fixed preview canvas | `Pdf.rotate_pixmap(pixmap, angle) -> Pixmap`; opaque RGB only, clockwise -180..180 around center, unchanged dimensions/origin/DPI, white fill and edge clipping; zero returns input, otherwise lazy PySide6 without QApplication; no PDF edits |
| Read editable bookmarks | `Pdf.read_bookmarks(document) -> list[PdfBookmark]`; depth-first title/one-based page/level/original_xref; non-page actions retain nonpositive targets |
| Append a bookmark | `Pdf.append_bookmark(document, title, page_index, parent=None) -> int`; zero-based page, optional parent outline xref; preserves existing entries and returns new xref |
| Replace or clear bookmarks | `Pdf.write_bookmarks(document, bookmarks) -> None`; validates hierarchy/targets before mutation; [] clears; retained same-document xrefs preserve style/collapse and unchanged destinations/actions; does not save |
| Number or clear selected labels | `Pdf.number_page_labels(labels, indexes, first=1, prefix="")`, `Pdf.clear_page_labels(labels, indexes)`; mutate label lists only, indexes are zero-based; apply with write_page_labels |
| Generate body/TOC labels | `Pdf.generate_page_labels(labels, body_pdf, body_book, toc_pages, toc_prefix="C")`; one-based physical mapping, positive printed body number; TOC takes precedence, other front matter remains |
| Set literal PDF page labels | `Pdf.write_page_labels(document, labels: Sequence[str]) -> None`; requires one string per page, empty strings mean blank labels; changes memory only and retains page content/bookmarks |

## Input and output policy

Open existing PDFs through `Pdf.open_document()`. Reuse the returned password
with `interactive=False` for background readers; use `Pdf.unlock()` when the
document is already open. New empty documents and generated in-memory page
buffers may use PyMuPDF directly. Keep passwords in memory, never in external
command arguments.

Save final output through `Pdf.save_new()`: remove encryption, permission
restrictions and PDF/A identification while retaining unrelated metadata.
Preserve the source and use exclusive output creation by default. Explicitly
authorized replacement stages the result before publication; failures retain
the previous output. Ghostscript compression stages unprotected input privately
and publishes the validated result through the same save helper.

## Internal implementation notes

`_OutputStream` deliberately has no filename: PyMuPDF writes through the
exclusively opened handle instead of reopening a path. Callers use `save_new()`.
`_process_pdfa_identification()` shares namespace-aware detection/removal while
retaining unrelated XMP.

Page-label helpers decode the PDF number tree and encode literal prefixes through
PyMuPDF's PDF-string encoder, preserving Unicode, escapes and blank labels.
`PdfBookmark.original_xref` belongs to one open document and becomes stale after
compact saving; reread bookmarks after reopening. Replacement validates first,
preserves retained actions/styles and recalculates visible descendants bottom-up.
Label-edit helpers mutate plain lists. GUI workers share bounded RGB rendering.

GUI source/output protection and worker publication are documented in the
[PDF tools README](../../tools/document-processing/pdf-tools/README.md).
Standalone checks: `test/test_pdf_utils.py`.
