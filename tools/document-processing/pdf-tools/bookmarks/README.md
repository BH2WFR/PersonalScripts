# PDF Bookmark Editor

Run `pdf-bookmark-editor.py` from the document-processing directory. Its **Page labels**
tab provides the integrated label editor; the tool is GUI-only. Dependencies are PySide6, PyMuPDF, PyYAML, cryptography, LiteLLM, OpenAI, HTTPX and truststore, declared in the
root requirements. Implementation lives here; the entry only loads this package.

The **Pages** context menu groups **Edit label** and **Clear label** separately.
Edit opens a text dialog for one selected page; with multiple pages it opens
**Page labels**, fills their range and shows a tooltip. Clear affects only the
selected rows, regardless of the range entered in the tab. Label edits are
disabled during processing, including recognition pauses.

The **Bookmarks** context menu includes **Expand all** and **Collapse over level 3**.
The latter shows levels 1–3 and folds deeper descendants. Both are view-only
actions, available during recognition pauses and from empty tree space.

## Workflow

1. Open/drop a PDF, choose its physical TOC page range and click **Mark TOC**.
   Each click replaces the previous TOC tasks with fresh tasks for that range,
   resetting crops, rotations, page requirements, drafts, status and recognition
   context. Existing bookmarks remain; removed TOC sources become manual entries.
   **Clear TOC** beside **Mark TOC** removes all TOC tasks and recognition settings
   while keeping existing bookmarks and the current page. It is disabled when
   no TOC pages are marked or processing is active, including pauses.
   In **Pages**, select one page and toggle **This page is TOC** in its context
   menu to mark/unmark just that page while preserving other tasks. The checkbox
   follows the selected page and is disabled during processing, including pauses.
   **Use current page** beside the first/last TOC page and first body PDF page
   fills that field from the viewer. TOC bounds are applied only by **Mark TOC**;
   the body-page button immediately updates the printed-to-physical mapping.
   With exactly one row selected in **Pages**, the right-click menu can set
   either TOC bound or the first body PDF page. The body action asks for that
   page's printed (logical) number before updating both mapping fields;
   cancelling leaves the mapping unchanged. TOC bounds still require **Mark TOC**.
   Each marked page gets a red recognition rectangle, initially the whole page.
   **Draw recognition box** enables dragging one replacement rectangle; uncheck
   it to pan. **Whole page** resets the crop; **Unmark** removes the recognition
   task while retaining already accepted bookmarks as manual entries.
2. Set the first body PDF page and its printed page number. Rotate a tilted TOC
   page before cropping: changing rotation resets its crop. Rotation keeps the
   original canvas dimensions and content scale, turns around the center, fills
   exposed areas white and clips content outside the page. Rotation/cropping
   affect recognition images only. One PDF page must contain one book page;
   split multi-up scans before using this tool.
3. Select an API preset or type an OpenAI-compatible base/full chat URL under **API**.
   Enter its key if required and click **Get models**, or type a vision-capable model name.
   **Vision models only (strict)** filters the next lookup by explicit image-input
   metadata, excluding unknown capabilities and image-generation-only models.
   OpenRouter publishes input modalities. SiliconFlow supplements its API list
   with the official model center's `vlm` metadata and matches exact model IDs;
   this public request carries no API key. If that website is unavailable or its
   format changes, lookup reports an error. Some compatible catalogs omit capabilities. An
   empty filtered list explains this limitation. Uncheck to list all models or
   enter a model manually; **Test API** verifies actual image access. Changing the
   filter clears the old list without automatically sending a request.
   Cloud services and local Ollama/LM Studio servers use the same workflow.
   Set temperature, output-token limit, timeout and context-image limit as needed.
   Add book-wide or current-page transcription requirements under **Recognition**.
   By default, duplicate numeric/written ordinals for the same entry are simplified:
   `1. 第一条：xxx` becomes `1. xxx`. Different numbers, distinct hierarchy levels
   and meaningful title text are retained; explicit user requirements take priority.
4. **Run TOC** sends one cropped JPEG at a time, in physical TOC-page order.
   Run/Retry commits the focused editor first. If changing the page or rotation
   needs a new preview, that single click starts recognition after rendering;
   repeated clicks do not queue extra runs. Stop or closing cancels the pending start.
   Pending-only mode skips completed/manually applied pages. Browse each page's
   draft and errors with the page navigator after the queue finishes or stops.
   **Retry page** replaces that page's entries, preserving other pages and
   directory-page order. **Retry all** resends every marked page in order,
   ignoring pending-only mode. Both include explicit complete-replacement instructions
   and the latest book-wide/current-page requirements.
   **Clear conversation before this run / retry** clears previous exchanges once,
   before the queue begins; leave it unchecked to retain the book's conversation.
   Recognition and PDF export share the icon-and-text **Pause / Resume** and
   **Stop** buttons beside progress in the preview area's bottom toolbar. They
   stay visible and disabled when idle; there are no separate controls on the left.
   Rerunning manually edited results asks before replacing them. **Pause** waits
   for the current request to finish before the next TOC page; **Resume** continues
   the remaining queue. While recognition is paused, Pages and Bookmarks allow
   scrolling, selection and navigation, including page-number/arrow controls.
   Bookmark editing, dragging, hierarchy changes and page deletion remain locked.
   Browsing does not change the queued page; Resume continues from the original
   position after any preview finishes. Manual pauses keep settings locked.
   Problem pauses allow clarification on the failed page and API-setting edits.
   **Stop** also works
   while paused and aborts
   the current HTTP request and retains completed results in this session.
   Export the PDF to keep the resulting bookmarks before quitting.
   Page statuses use blue for pending, green for done/modified and red for errors
   or requests for information.
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
   identification; source files are protected and existing outputs require
   explicit overwrite confirmation before staged replacement.
   During PDF export, the bottom row provides the shared **Pause / Resume** and
   **Stop** controls. They take effect at safe steps, including after an active
   MuPDF save returns; cancelling before publication retains an existing output.

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

By default, a parent heading without a printed page number inherits its first
following child's page within that section, including nested parent headings.
Explicit user rules take priority (for example, child page minus two).
Unresolved child pages still require clarification; sibling sections are not used.

Use `errors: []` when all entries are reliable. Unresolved page numbers, uncertain
titles/hierarchy, unreadable content and cropped-off entries must be reported,
never guessed or silently omitted. A problem marks the source TOC page **needs
information**, leaves its previous accepted bookmarks unchanged, and pauses the
queue on that page. Connection, parsing and incomplete-response errors also pause.
A warning opens; confirming it focuses **Information**, which displays each issue's
location, description and requested clarification. Its inline answer editor shares
the current page's requirements. **Retry & continue** (or the footer **Resume**)
retries only the blocked page, then continues the original remaining queue after
success. It preserves earlier results and conversation regardless of the clear-context
checkbox. Another failure pauses again; no automatic paid retries occur.
Progress counts successful pages, without counting failed attempts twice.
Connection failures can be retried without typing an answer. **Stop** discards
the remaining queue, retaining results and page instructions; use it before changing
the crop or manually correcting YAML. A response with partial entries and errors stays entirely in the
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
focuses the inline editor in **Information**. Supply the missing details,
then click **Retry & continue** while paused, or **Retry page** when idle.
The retry includes the previous problem and new
requirements, replacing only this page's entries in TOC order after success.
Alternatively correct the YAML entries and clear resolved errors, then apply it.

The final tree is authoritative for export. Tree edits do not rewrite the raw
per-page YAML; reapplying that YAML replaces that page's tree entries. Double-click
a title/target or press F2 to edit. New bookmarks point to the currently displayed
PDF page. Single-click navigates after the double-click interval; **Ctrl/Shift**
selects multiple bookmarks without navigating. Right-click keeps an existing
multi-selection. Move, delete, retarget-to-current-page and hierarchy actions
apply to the selection; parent/descendant overlap is processed only once when
moving subtrees. Rename and target editing require a single selection; their
context-menu actions and inline editing are disabled for multiple selections.
Bookmark tooltips show the full title, level and target page on separate lines.
**Delete bookmark** offers three radio options when descendants exist: delete only
the bookmark and keep descendant levels (default), delete only the bookmark and
move descendants up one level, or include all descendants. Retained levels may
attach to a preceding parent. Missing required parents reject
the entire batch instead of silently promoting children. Multi-selection offers
**Apply to all**, remembering both deletion scope and promotion for that batch. Already removed
descendants are skipped; Cancel discards the entire batch. Deletion is one undo step.

Drag selected subtrees above/below another item or onto it to become its children;
drop on blank space to append at the root. Nonconsecutive selections are allowed:
selected subtrees retain their original relative order, as do unselected entries.
Dropping a selection onto itself or its descendants is rejected. Each operation
produces one undo step and preserves bookmark identities/targets.

Toolbar/right-click hierarchy actions include:

- **Set level...** (right-click) accepts an absolute target level. By default,
  descendants move by the same level difference, preserving relative subtree
  levels; overlapping parent/child selections are handled once at the parent.
  Uncheck **Move descendants with selected bookmarks** to set every selected item
  to that level while leaving unselected levels unchanged. Reading order and
  target pages stay unchanged; parent relationships may change. Invalid hierarchy
  changes are rejected as a whole, and a successful batch is one undo step.
- **Indent (with descendants)** (`→`) increases selected subtree levels together.
- **Indent (selected items only)** (`→¹`) increases only explicitly selected levels.
  Direct children keep their original level and become peers of the indented item;
  deeper descendants retain their hierarchy. Reading order never changes in either
  indent mode. A selection requiring a missing parent is rejected as a whole.

- **Outdent (keep order)**, also the toolbar's left arrow, promotes the selected
  subtree without changing depth-first reading order. Following siblings become
  its children at their existing levels.
- **Outdent (move below parent)** promotes the subtree after its former parent's
  remaining children, preserving those children's parentage.

Tooltips use the shared 250-logical-pixel popup; long words and URLs wrap too.

**Clear bookmarks** clears the final tree, retaining drafts; **Undo** restores recent tree
changes (up to 50, current session only). **Add Cover + TOC** is explicit. Recognition
replaces original PDF bookmarks by default; check **Keep existing PDF bookmarks**
to retain them alongside new entries.

## API, context and manual interaction

Text and image inference uses `litellm.acompletion` in a cancellable background
thread. Existing compatible URLs/model IDs and `llm.yaml` profiles remain valid.
The HTTP client belongs to one request: no automatic retries or redirects, a
bounded response and an overall timeout. Empty keys send no Authorization header.
TLS uses native system certificates through `truststore`, with certificate and
hostname verification enabled by default. **Skip certificate verification** in
the API tab disables these checks for the selected source, including recognition,
API tests, model lists and balances. It defaults to off and follows the same
per-source Save/Load behavior as other API settings. HTTP endpoints such as local
Ollama/LM Studio work without enabling this option. On Windows/macOS, `SSL_CERT_FILE` / `SSL_CERT_DIR`
do not replace native trust; Linux follows the system OpenSSL CA locations,
including its native environment overrides. Normal proxy routing is unchanged. Timeout remains
in seconds, default 180. Recognition failures open a resizable dialog with complete,
scrollable plain-text diagnostics and **Copy error**; Information retains the error.
Error causes are not shortened, and submitted API keys are still redacted.
LiteLLM uses bundled pricing metadata, does not load `.env`, and has message logging
disabled. Stop cancels the HTTP operation; the queue advances only after cleanup.
The first inference lazily initializes the library and can take a few seconds.

Model catalogs retain the existing same-host HTTP adapters, including Alibaba
pagination and SiliconFlow chat filtering. LiteLLM's current generic discovery
discards custom path prefixes and turns some failures into empty lists; it does
not preserve this tool's lookup behavior. Account balances retain native adapters.

Other tools can reuse `Llm.acompletion` without Qt or PDF dependencies:

```python
from utils import *

# Inside an async function; settings/key belong to the selected source.
result = await Llm.acompletion(
    settings, key, messages=history,
    system_prompt="Transcribe accurately.", prompt="Read this page.",
    images=[Llm.image_content(png_bytes, mime_type="image/png")],
)
text = result.text
# Check result.finish_reason == "stop" before accepting a complete transcription.
```

Omit images for text-only prompts, or provide the complete message list directly.
`max_context_images` limits images across history and current input together,
retaining the newest N images and all text; 0 means unlimited. History remains
caller-owned: retain the user message and returned assistant text for the next turn.

The editable API dropdown includes DeepSeek, Kimi, Alibaba Model Studio (Beijing
and Singapore), OpenRouter, SiliconFlow, Ollama and LM Studio. Selecting a preset fills its URL;
custom URLs, including Alibaba workspace-specific hosts, remain editable.
Settings are stored per source in shared user `llm.yaml`, managed by `utils.Llm`.
Startup and **Load** read the file; **Save** and closing the window write it.
Load replaces unsaved API drafts. Editing fields and switching URLs do not write.
Switching URLs restores that source's in-memory model, parameters, API key and balance key;
new sources start without keys. Base URLs and their chat-completions URLs identify
the same source. Read/write locks last only for file I/O. A busy file returns an
error immediately, shown in the API status, tooltip and console; failed saves
retain drafts and prevent closing until a retry succeeds. Keys use `!encrypted`
values; their key is owned by `utils/llm.py`, independent of other modules;
the bundled fixed key provides obfuscation, not protection against someone who
has the source code. PDF passwords and recognition conversations stay in memory.

For local inference, start a server with a vision-capable model:

- [Ollama's OpenAI-compatible API](https://docs.ollama.com/api/openai-compatibility):
  preset base URL `http://localhost:11434/v1`.
- [LM Studio's compatible chat API](https://lmstudio.ai/docs/developer/openai-compat/chat-completions):
  preset base URL `http://localhost:1234/v1`.

Use **Get models** and **Test API (small image)** as with a cloud endpoint.
The key may be empty unless the server requires authentication. An editable LAN
URL can point to a server on another computer. The tool does not install/download
models or host inference itself; selecting a text-only model cannot recognize images.

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

**Get models** makes a GET (authenticated when a key is supplied) without PDF content, even before a book
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

Each request adds one new cropped page image as an `image_url` data URL in the
last user message. Previous requests and replies from the current book are
included chronologically, including failed replies and their diagnostics.
The prompt explicitly restricts recognition to the last image and requests a
complete replacement on retry. Latest requirements, accepted preceding entries
and the current page's previous draft/problem help correct earlier answers.

**Context images** caps images across the entire request, including the current page:
the default **5** allows the current image plus the four newest historical
images; **1** sends only the current image; **0** is unlimited. Older image parts
are replaced with omission markers while historical text/replies remain.
This is an image-count limit, not a text/token budget. Increasing it can include
older images again because the session retains the original conversation.

**Clear conversation before this run / retry** removes earlier exchanges once at
queue start and starts the accepted-entry context at its first page. It preserves
bookmarks, drafts and user requirements; the current page's previous draft/problem
still accompanies retries as explicit correction information. Subsequent pages
in that run accumulate a fresh conversation. Closing/opening a book also resets
conversation memory. Nothing is stored as a provider-hosted conversation or sent
to the PDF worker. The usage label reports the last request's image count and
API-reported input tokens, not a percentage of a model's context window.

The default model is `deepseek-flash`; model names are editable. See the provider's
[vision documentation](https://api-docs.deepseek.com/guides/vision/).
**Reasoning effort** is a per-source dropdown, enabled by default. Switching API
or model refreshes its choices; Save/Load and window close persist the selection.
**Server default (no override)** sends no reasoning controls. Known unsupported
saved levels stay visible with a warning and must be changed before recognition.

| API | Request controls and available effort |
| --- | --- |
| DeepSeek | `thinking.type` plus `reasoning_effort`: low/high/max; temperature omitted while explicitly thinking |
| Kimi | Model-dependent: thinking toggle on K2.6; K3 always thinks with low/high/max; K2.7 Code always thinks |
| Alibaba / SiliconFlow | `enable_thinking`; token budgets are not treated as effort levels. Alibaba DeepSeek V4 also supports low/high/max |
| OpenRouter | Nested `reasoning.enabled` or `reasoning.effort`; underlying model decides supported levels |
| Other compatible endpoints | `reasoning_effort`; enabled defaults to medium; model support is required |

Choices reflect known API/model families, not live capability discovery. For an
unsupported model or proxy dialect, select Server default to omit the controls.
No model calls happen on opening a
PDF, changing settings or navigating. Balance queries may run when credential
editing finishes as described above. **Run**/**Retry** sends book images.
**Test API (small image)** sends a generated color square to the configured model,
even before opening a PDF. It checks authentication, model access and image input,
reports elapsed time and returned errors, and does not alter book drafts or context.
It is a real API request using the selected reasoning mode and output-token budget;
only explicit **Off** caps output at 32 tokens. Testing never silently disables
mandatory reasoning. **Stop** cancels it.
API keys persist encrypted per source; PDF passwords stay in memory.

**Copy system prompt** and **Copy recognition image** support manual use with an
external model; paste its YAML/JSON result into the current page's draft. Responses
truncated by an output-token limit or rejected by validation remain available for
inspection without replacing accepted bookmarks. Connection failures mark the
page failed and pause the queue for an explicit retry. The next page is sent only
after the current response finishes and passes validation. A request introduces only one
new page to recognize; retained historical images are context, not additional
recognition tasks. No concurrent recognition or automatic paid retry is used.

## Labels and saving

In **Pages**, select one page or use **Ctrl/Shift** to select multiple pages,
then choose **Delete selected pages...**, the right-click action, or **Delete**.
Confirm whether later bookmark targets should follow their original pages or
keep their numeric targets. Nonconsecutive selections are mapped individually:
deleting pages 2, 5 and 8 moves old page 7 to 5, and old page 10 to 7.
Bookmarks targeting removed pages can be deleted or moved to the preceding
retained page (the first retained page if none precedes it). Children of removed
bookmarks survive with promoted levels. At least one PDF page must remain.

Deletion cannot be undone and clears bookmark undo history, preview cache and
recognition conversation. It affects the current session; the source PDF stays
unchanged, and **Export PDF** writes the remaining pages. Page navigation, new
bookmarks, TOC tasks and physical page fields use the new numbering immediately.
Printed-page recognition and generated body labels retain gaps for deleted pages.
Recognition targeting a removed printed page requires correction before acceptance.
Retained TOC tasks keep their crops, drafts and requirements; deleted TOC tasks
are removed, while their surviving accepted bookmarks become manual entries.
If deleting the body anchor leaves no positive printed body page, choose a new
body mapping before recognition. Keeping numeric bookmark targets can leave
out-of-range targets, which must be corrected before export.

**Page labels** edits PDF navigation labels, not printed page content. Enter a
range such as `1,2,5-10,-1`, or select rows using Ctrl/Shift in **Pages**. The
**All / Odd / Even** radio buttons synchronize with `|odd` / `|even` suffixes;
All retains the entire entered range. Numbered
labels allow a prefix and signed starting number. Clear selected/all labels, or
generate C1/C2 labels for TOC pages and consecutive body numbers from the mapping;
unrelated front matter keeps its current labels.

There are no project files, project-open/save buttons or autosaves. Open/drop PDFs
only. Drafts, crops and API settings are session state and are not written into the
exported PDF. Export saves the final bookmark tree and page labels. When closing
or opening another book with unexported changes, choose export, discard or cancel;
an export must succeed before the pending action continues. Binarize's separate
JSON project functionality is unchanged.

**Close** releases the PDF and clears session/cache/API fields while keeping the
window open at its startup state. Export defaults use the shared filename helper
to append `_1`, `_2`, … when needed. Selecting an existing output asks **Overwrite**
or **Return**; only a successful staged save replaces it. The source is always
protected. A completion dialog appears after a successful export.

## Preview performance

Click the viewer to focus it. PgUp/Left/Up moves to the previous page;
PgDn/Right/Down moves to the next page, including in crop-editing mode.
These shortcuts are shared with PDF Binarizer and leave text-editor keys alone.

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
