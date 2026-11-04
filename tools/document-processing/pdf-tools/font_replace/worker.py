"""Serial PDF/font worker: discovery, clean previews and full-document export."""

from collections.abc import Callable, Sequence
from contextlib import ExitStack, closing, redirect_stdout
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import cast

import pymupdf
from utils import *
from ..common.pixel_transfer import preview_reply
from ..common.protocol import Json
from .engine import _Engine, _font_name, _page_font_aliases, _pdf_fonts, _rgb_key, _source_names, SUBSET_PREFIX
from .model import ReplacementRule, face_data


def _font_details(document: pymupdf.Document, pages: Sequence[int], names: list[str]) -> tuple[dict[str, str], list[int]]:
    """Describe used source fonts from scanned pages without extracting font files.

    Resource metadata comes from the PDF, never a guessed installed-font match.
    Descendant arrays and dictionaries may be direct or indirect PDF objects.
    Sizes, colors and page ranges describe only the selected discovery pages.
    Returned display strings are separate from exact names used by rules.
    """
    sizes: dict[str, set[float]] = {name: set() for name in names}
    colors: dict[str, set[int]] = {name: set() for name in names}
    used_pages: dict[str, set[int]] = {name: set() for name in names}
    resources: dict[str, set[str]] = {name: set() for name in names}
    types: dict[str, set[str]] = {name: set() for name in names}
    embedded: dict[str, set[str]] = {name: set() for name in names}
    metadata: dict[int, tuple[set[str], str, str, str]] = {}
    mupdf = pymupdf.mupdf
    native = mupdf.pdf_document_from_fz_document(document.this)
    for index in pages:
        page = document[index]
        aliases = _page_font_aliases(page)
        used: set[str] = set()
        for span in page.get_texttrace():
            name = _font_name(span["font"])
            name = aliases.get(name, name)
            if not span["chars"] or name not in sizes:
                continue
            used.add(name)
            sizes[name].add(round(float(span["size"]), 2))
            used_pages[name].add(index + 1)
            if span["type"] in (0, 1):
                colors[name].add(_rgb_key(span["color"]))
        for row in page.get_fonts(full=True):
            xref, extension, subtype, full_name, alias, encoding = row[:6]
            if xref not in metadata:
                matched = {_font_name(full_name)}
                if xref:
                    try:
                        matched.update(_source_names(document, xref))
                    except (RuntimeError, ValueError):
                        pass  # Resource names remain available for malformed font descriptors.
                    # Resolve objects structurally: a descendant need not have
                    # its own xref, and DescendantFonts can reference an array.
                    owner = mupdf.pdf_load_object(native, xref)
                    if subtype == "Type0":
                        owner = mupdf.pdf_array_get(mupdf.pdf_dict_gets(owner, "DescendantFonts"), 0)
                    descriptor = mupdf.pdf_dict_gets(owner, "FontDescriptor")
                    has_program = any(mupdf.pdf_is_stream(mupdf.pdf_dict_gets(descriptor, key))
                                      for key in ("FontFile", "FontFile2", "FontFile3"))
                    state = ("yes" if has_program else "no") if mupdf.pdf_is_dict(owner) else "unknown"
                    if subtype == "Type3":
                        state = "Type3 glyph streams"
                else:
                    state = "unknown"
                prefix = SUBSET_PREFIX.match(full_name)
                display_name = f"{prefix[0] if prefix else ''}{_font_name(full_name)}"
                description = f"PDF name: {display_name}; type: {subtype}; encoding: {encoding or 'unspecified'}; format: {extension}; embedded: {state}"
                metadata[xref] = matched, description, subtype, state
            matched, description, subtype, state = metadata[xref]
            for name in used & matched:
                resources[name].add(f"{description}; resource: /{alias}; xref: {xref}")
                types[name].add(subtype)
                embedded[name].add(state)
    details: dict[str, str] = {}
    for name in names:
        size_text = ", ".join(f"{size:g}" for size in sorted(sizes[name]))
        type_text = " / ".join(sorted(types[name])) or "unknown type"
        embedding = " / ".join(sorted(embedded[name])) or "unknown"
        page_text = Input.format_integer_ranges(Input.merge_integer_ranges(used_pages[name]))
        color_text = ", ".join(f"#{value:06X}" for value in sorted(colors[name])) or "No solid painted text"
        details[name] = (f"{type_text}; embedded: {embedding}; {size_text} pt\n"
                         f"Scanned physical pages: {page_text}\nText colors: {color_text}\n"
                         f"{'\n'.join(sorted(resources[name]))}")
    return details, sorted({color for values in colors.values() for color in values})


class Worker:
    """Retain an authenticated read-only source; every mutation uses a clean copy."""

    def __init__(self, progress: Callable[[dict[str, Json]], None] | None = None) -> None:
        self._inputs = ExitStack()
        self._source: pymupdf.Document | None = None
        self._identity: tuple[str, int, int, str] | None = None
        self.password = ""
        self.progress = progress
        self.catalog: list[FontFace] | None = None

    def close(self) -> None:
        """Release the worker-owned PDF and its authentication context."""
        self._inputs.close()
        self._source = None
        self._identity = None

    def _progress(self, done: int, total: int) -> None:
        if self.progress is not None:
            self.progress({"kind": "progress", "done": done, "total": total})

    def run(self, request: dict[str, Json]) -> dict[str, Json]:
        """Execute one request on the worker main thread; errors propagate to UI.

        Args:
            request: JSON object naming catalog, font_file, inspect, scan,
                preview or export. Page numbers are one-based.
        Returns:
            JSON-safe completion; preview pixels use the shared buffer if supplied.
        Raises:
            ValueError, OSError: Invalid inputs, unsupported fonts or failed I/O.
        Only export writes files, through Pdf.save_new; never modifies the source.
        """
        operation = request["operation"]
        # ── target discovery does not require a PDF ────────────
        if operation == "catalog":
            if self.catalog is None:
                self.catalog = Font.read_catalog(Font.system_font_paths())
            return {"kind": "fonts", "faces": [face_data(face) for face in self.catalog]}
        if operation == "font_file":
            faces = Font.read_faces(Path(str(request["font_path"])))
            return {"kind": "fonts", "faces": [face_data(face) for face in faces]}

        # ── keep originals open for fast page turns ────────────
        path = Path(str(request["path"]))
        password = str(request.get("password", ""))
        stat = path.stat()
        identity = (str(path), stat.st_mtime_ns, stat.st_size, password)
        if self._source is None or self._identity != identity:
            self.close()
            self._source, self.password = self._inputs.enter_context(
                Pdf.open_document(path, password=password, interactive=False))
            self._identity = identity
        source = self._source
        assert source is not None
        if not source.page_count:
            raise ValueError("The PDF has no pages.")
        if operation == "inspect":
            return cast(dict[str, Json], {"kind": "opened", "page_count": source.page_count,
                "labels": Pdf.read_page_labels(source), "bookmarks": source.get_toc(),
                "password": self.password})
        if operation == "scan":
            pages = Input.parse_index_ranges(str(request.get("pages", "all")).strip() or "all",
                                             item_count=source.page_count)
            names = _pdf_fonts(source, pages)
            details, colors = _font_details(source, pages, names)
            return cast(dict[str, Json], {"kind": "scan", "names": names, "colors": colors, "details": details})

        page_number = int(cast(int, request.get("page", 1)))
        if not 1 <= page_number <= source.page_count:
            raise ValueError("Page number is outside this PDF.")
        raw = request.get("raw") is True
        rules = [ReplacementRule.from_data(cast(dict[str, Json], row)).compile(source.page_count)
                 for row in cast(list[Json], request.get("rules", []))] if not raw else []

        # ── previews rewrite only a fresh, isolated page ───────
        if operation == "preview":
            count = 0
            recolored_runs = 0
            with pymupdf.open() as preview:
                if rules:
                    preview.insert_pdf(source, from_page=page_number - 1, to_page=page_number - 1)
                    eligible = [replace(rule, ignored=()) for rule in rules
                                if page_number - 1 not in rule.ignored]
                    if eligible:
                        engine = _Engine(preview, eligible)
                        count = engine.run([0])
                        recolored_runs = engine.recolored_runs
                    page = preview[0]
                else:
                    page = source[page_number - 1]
                pixmap = Pdf.render_page(page)
                return preview_reply({"kind": "preview", "page": page_number, "raw": raw,
                    "count": count, "recolored_runs": recolored_runs,
                    "width": pixmap.width, "height": pixmap.height},
                    pixmap.samples if request.get("pixel_buffer") else pixmap.tobytes("png"), request)

        # ── output starts from the complete original document ──
        if operation == "export":
            if not rules:
                raise ValueError("Add at least one replacement rule before exporting.")
            output = Path(str(request["output"]))
            with Pdf.open_document(path, password=self.password, interactive=False) as (document, _):
                engine = _Engine(document, rules)
                count = engine.run(range(document.page_count), self._progress)
                if not count and not engine.recolored_runs:
                    return {"kind": "no_matches"}
                engine.remove_original_embeddings()
                Pdf.save_new(document, output, compact=False, overwrite=request.get("overwrite") is True)
            return {"kind": "exported", "path": str(output), "count": count,
                    "recolored_runs": engine.recolored_runs}
        raise ValueError(f"Unknown operation: {operation}")


def main() -> int:
    """Serve serial JSON lines; stdout is reserved for the protocol."""
    stream = sys.stdout

    def send(message: dict[str, Json]) -> None:
        stream.write(f"{json.dumps(message, ensure_ascii=True)}\n")
        stream.flush()

    with closing(Worker(send)) as worker:
        for line in sys.stdin:
            try:
                with redirect_stdout(sys.stderr):
                    reply = worker.run(json.loads(line))
            except Exception as exc:
                reply = {"kind": "error", "message": str(exc),
                         "code": "password" if "password" in str(exc).lower() else "error"}
            send(reply)
    return 0
