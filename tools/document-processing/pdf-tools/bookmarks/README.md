# PDF bookmarks and page labels

Run `pdf-bookmarks-add.py` from the document-processing directory. Its **Page labels**
tab provides the integrated label editor; the tool is GUI-only. Dependencies are PySide6, PyMuPDF and PyYAML, already declared in the
root requirements. Implementation lives here; the entry only loads this package.

## Workflow

1. Open/drop a PDF, choose its physical TOC page range and click **Mark TOC**.
   **Use current page** beside the first/last TOC page and first body PDF page
   fills that field from the viewer. TOC bounds are applied only by **Mark TOC**;
   the body-page button immediately updates the printed-to-physical mapping.
   Each marked page gets a red recognition rectangle, initially the whole page.
   **Draw recognition box** enables dragging one replacement rectangle; uncheck
   it to pan. **Whole page** resets the crop; **Unmark** removes the recognition
   task while retaining already accepted bookmarks as manual entries.
2. Set the first body PDF page and its printed page number. Rotate a tilted TOC
   page before cropping: changing rotation resets its crop. Rotation/cropping
   affect recognition images only. One PDF page must contain one book page;
   split multi-up scans before using this tool.
3. Select an API preset or type an OpenAI-compatible base/full chat URL under **API**.
   Enter its key and click **Get models**, or type a vision-capable model name.
   Set temperature, output-token limit and timeout as needed.
   Add book-wide or current-page transcription requirements under **Recognition**.
4. **Run TOC queue** sends one cropped JPEG at a time, in physical TOC-page order.
   Pending-only mode skips completed/manually applied pages. **Retry this page**
   replaces that page's entries, preserving other pages and directory-page order.
   Rerunning manually edited results asks before replacing them. **Stop** aborts
   the current HTTP request and retains completed results in this session.
   Export the PDF to keep the resulting bookmarks before quitting.
5. Edit the current page's YAML draft or edit the final bookmark tree. Valid YAML
   updates the tree after a short editing pause; invalid manual YAML blocks export
   until corrected/reapplied. Each entry's `page` in YAML means a printed page;
   the tree's target means a physical PDF page. Model issues and unreadable `null`
   pages must be resolved before that page's draft is applied. A negative printed page counts backward before 1,
   with no page zero. Levels begin at 1 and cannot skip a level in the final tree.
6. **Export PDF** writes a new file beside the source by default. Page text,
   graphics, links, annotations and attachments are retained. Existing outline
   actions, destinations, styles and collapse states survive if the entry is kept
   and its target is unchanged. Shared PDF policy removes encryption and PDF/A
   identification; source and existing output files are never overwritten.

Example draft (comments are retained verbatim):

```yaml
# Printed page numbers, not physical PDF page numbers
- {page: 1, level: 1, index: "Chapter 1", title: "Introduction"}
- {page: 3, level: 2, index: "1.1", title: "First section"}
```

The model returns an envelope with `entries` and `errors`; plain entry lists above
remain supported for manual editing. Each problem describes its location and the
information needed, for example:

```yaml
entries:
  - {page: null, level: 1, index: "Chapter 1", title: "Introduction"}
errors:
  - {error_message: "Page number is cut off", location: "Introduction, right edge", needs: "Provide the printed page or a wider crop"}
```

Use `errors: []` when all entries are reliable. Missing page numbers, uncertain
titles/hierarchy, unreadable content and cropped-off entries must be reported,
never guessed or silently omitted. A problem marks the source TOC page **needs
information**, leaves its previous accepted bookmarks unchanged, and lets the
queue continue. A response with partial entries and errors stays entirely in the
draft until resolved. Failed/unfinished drafts block export until corrected,
successfully retried or explicitly removed with **Unmark** (which keeps previously
accepted bookmarks). **Clear bookmarks** explicitly discards the final outline
and clears draft export blockers.

Select the problem page in **Pages**. **Request / errors** shows recent attempts,
newest first: physical source page, time, API/model settings, crop/rotation,
body mapping, exact text prompt/context, raw reply and failure reason. No image
payload or API key is logged. History is session-only, limited per page to ten
records and roughly two million characters; very large records are truncated,
while the latest full reply remains the draft until edited. **Add page information**
focuses this page's requirements. Supply the missing details or adjust the crop,
then click **Retry this page**. The retry includes the previous problem and new
requirements, replacing only this page's entries in TOC order after success.
Alternatively correct the YAML entries and clear resolved errors, then apply it.

The final tree is authoritative for export. Tree edits do not rewrite the raw
per-page YAML; reapplying that YAML replaces that page's tree entries. Double-click
a title/target or press F2 to edit; toolbar arrows move complete subtrees or change
their level. New bookmarks point to the currently displayed PDF page. Single-click
navigates after the double-click interval; **Ctrl+click** or **right-click** selects
without navigating. The right-click menu offers navigation, retargeting to the
current page, title/page editing, addition, deletion and both outdent modes:

- **Outdent (keep order)**, also the toolbar's left arrow, promotes the selected
  subtree without changing depth-first reading order. Following siblings become
  its children at their existing levels.
- **Outdent (move below parent)** promotes the subtree after its former parent's
  remaining children, preserving those children's parentage.

**Clear bookmarks** clears the final tree, retaining drafts; **Undo** restores recent tree
changes (up to 50, current session only). **Add Cover + TOC** is explicit. Recognition
replaces original PDF bookmarks by default; check **Keep existing PDF bookmarks**
to retain them alongside new entries.

## API, context and manual interaction

The editable API dropdown includes DeepSeek, Kimi, Alibaba Model Studio (Beijing
and Singapore), OpenRouter and SiliconFlow. Selecting a preset fills its URL;
custom URLs, including Alibaba workspace-specific hosts, remain editable.
Changing endpoints clears the old model choices; changing hosts also clears the
key. Settings and keys remain in memory only.

**API balance** stays visible beside the export button; API settings also show
the last update time and a **Refresh API balance** button. It queries the provider's
available account balance, including usable grants/vouchers where reported, with
its currency; it never substitutes an API key spending cap. Editing a key/URL and
leaving the field, completing API Test, or finishing a TOC queue refreshes it.
There is no periodic polling. **Balance key** is optional and defaults to the API
key; a supplied key is used only for the balance GET, never for model calls.
Changing hosts clears both keys. Changing either key or the URL cancels an old
lookup and clears its value so balances cannot leak across accounts.

Supported balance APIs and limitations:

- [DeepSeek](https://api-docs.deepseek.com/api/get-user-balance/): available balance
  and currency from `/user/balance`; all returned currencies are displayed.
- [Kimi China](https://platform.kimi.com/docs/api/balance): CNY available balance
  from `/v1/users/me/balance`, using the configured `api.moonshot.cn` endpoint.
- [OpenRouter](https://openrouter.ai/docs/api/api-reference/credits/get-remaining-credits):
  USD credits minus usage. Enter a **management key** in Balance key; the ordinary
  inference key may return a permissions error.
- [SiliconFlow](https://api-docs.siliconflow.cn/docs/release-notes/overview) retired
  `/user/info` on 2026-08-14. No request is made to this obsolete endpoint.
- [Alibaba cloud billing](https://help.aliyun.com/en/user-center/developer-reference/api-bssopenapi-2017-12-14-overview)
  uses separate cloud credentials, not a Model Studio API key; this GUI does not
  implement that billing integration. Custom proxies and unknown routes are also
  marked unsupported rather than probing guessed paths or forwarding their keys.

Balance lookups use a separate, cancellable single-request client with a maximum
30-second timeout and the shared size/redirect protections. They send no document
or model input and do not block page navigation or add work to the TOC queue.
Repeated refreshes cannot accumulate; **Stop** cancels an active lookup. Failures
show “unavailable” and their reason, never a misleading zero or stale balance.

**Get models** makes an authenticated GET without PDF content, even before a book
is opened. It fills the editable model dropdown with unique, sorted IDs, retaining
an already typed model name. Failed/empty lookups leave manual entry available.
Catalog membership does not guarantee image input or inference permission;
**Test API** tests the selected model. Discovery shares the serial API client,
Stop button, timeout and response-size limit; it cannot queue behind recognition.

Compatible providers use `/models` alongside `/chat/completions`. Official Alibaba
hosts use `/api/v1/models` with serial pagination (at most 100 pages / 10,000 models),
while SiliconFlow requests chat models. The total timeout covers all catalog pages.
No redirects are followed with credentials. Endpoint references:

- [Kimi endpoints and model discovery](https://www.kimi.com/help/kimi-api/api-troubleshooting)
- [Alibaba compatible endpoints](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
  and [paginated model list](https://help.aliyun.com/zh/model-studio/list-models)
- [OpenRouter model list](https://openrouter.ai/docs/api/api-reference/models/get-models)
- [SiliconFlow model list](https://api-docs.siliconflow.cn/docs/api/models-get)

Requests use `messages` with a current-page `image_url` data URL, plus accepted
earlier entries from this book as text. Future pages and previous versions of the
retried page are excluded; its previous error is included as diagnostic text.
Earlier images are not resent. **Clear context before
this run** sets a new context boundary at its first page; earlier final bookmarks
remain in the session. This is a book-scoped text context, not a provider-hosted
conversation. The usage label shows the last API-reported input-token count,
not an estimated percentage of a model's context window.

The default model is `deepseek-flash`; model names are editable. See the provider's
[vision documentation](https://api-docs.deepseek.com/guides/vision/).
For the official DeepSeek host, requests disable thinking so temperature applies.
Other endpoints receive standard fields only. No model calls happen on opening a
PDF, changing settings or navigating. Balance queries may run when credential
editing finishes as described above. **Run**/**Retry** sends book images.
**Test API (small image)** sends a generated color square to the configured model,
even before opening a PDF. It checks authentication, model access and image input,
reports elapsed time and returned errors, and does not alter book drafts or context.
It is a small real API request (up to 32 output tokens); **Stop** cancels it.
Keys and PDF passwords stay in memory.

**Copy system prompt** and **Copy recognition image** support manual use with an
external model; paste its YAML/JSON result into the current page's draft. Responses
truncated by an output-token limit or rejected by validation remain available for
inspection without replacing accepted bookmarks. Connection failures mark the
page failed and allow the queue to continue. The next image is sent only after
the current response finishes and is validated; no multi-page image request or
concurrent recognition is used. There is no automatic paid retry.

## Labels and saving

**Page labels** edits PDF navigation labels, not printed page content. Enter a
range such as `1,2,5-10,-1`, or select rows using Ctrl/Shift in **Pages**. Numbered
labels allow a prefix and signed starting number. Clear selected/all labels, or
generate C1/C2 labels for TOC pages and consecutive body numbers from the mapping;
unrelated front matter keeps its current labels.

There are no project files, project-open/save buttons or autosaves. Open/drop PDFs
only. Drafts, crops and API settings are session state and are not written into the
exported PDF. Export saves the final bookmark tree and page labels. When closing
or opening another book with unexported changes, choose export, discard or cancel;
an export must succeed before the pending action continues. Binarize's separate
JSON project functionality is unchanged.

## Preview performance

Click the viewer to focus it. PgUp/Left/Up moves to the previous page;
PgDn/Right/Down moves to the next page, including in crop-editing mode.
These shortcuts are shared with PDF Binarize and leave text-editor keys alone.

Uncached pages render at the same 200 DPI as recognition inputs, with a 12-million
pixel cap. Packed RGB pixels cross a reusable shared-memory slot without PNG
encoding or base64. Cached navigation needs no worker request. The cache retains
one latest rotation per physical page within 512 MiB and 100 pages; rotation
changes require a matching render, and opening another PDF clears the cache.
Crop changes reuse the same pixels. There is only one pending render/request;
render tasks cannot accumulate. No background full-book rendering is performed.

## Module ownership and checks

- `model.py`: in-memory book sessions, YAML parsing and ordered replacement.
- `recognition.py`: TOC prompt and ordered book-specific context, using `Llm` payload helpers.
- `worker.py`: serial inspection/preview/export orchestration over shared `Pdf` operations.
- Repository `utils/llm.py`: generic settings, presets, image/chat bodies and response parsing.
- Repository `utils/_llm_qt.py`: lazy, single-request transport, obtained through `Llm.create_qt_client()`.
- Repository `utils/pdf.py`: bookmark read/append/replace, page labels and bounded RGB rendering.
- `app.py`: book session, settings, queue, drafts, label editing and export UI.
- `../common/crop_viewer.py`: optional single red crop over the shared viewer.
- `../common/bookmark_editor.py`: optional tree editing, default read-only.
- `../common/page_cache.py`: reusable per-page memory/count bounds and LRU eviction.
- `../common/pixel_transfer.py`: shared RGB publication used by both PDF GUIs.

Run `test_pdf_bookmarks_gui.py` for generated-PDF, offscreen GUI and loopback HTTP
tests; `test_pdf_tools.py` retains PDF structure/authentication/export regressions.
`test_llm.py` and `test_pdf_utils.py` exercise public helpers without the GUI package;
ordinary utility imports do not load Qt or PyMuPDF. No new dependencies are needed.
Tests do not call a paid API or upload a real book. A live provider/key must be
tested separately; API compatibility does not guarantee transcription accuracy.
