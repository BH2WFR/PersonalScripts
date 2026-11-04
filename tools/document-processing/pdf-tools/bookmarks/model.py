"""Single-book-page TOC sessions, strict YAML drafts and ordered result replacement.

Printed page numbers belong to recognition drafts; editable export entries use
physical PDF pages. Credentials and rendered images are never serialized.
"""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import math
from pathlib import Path
import re
from typing import cast
from uuid import uuid4

import yaml
from utils import *

MAX_DRAFT = 1_000_000
type Rect = tuple[float, float, float, float]


class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    NEEDS_INFO = "needs information"
    INTERRUPTED = "interrupted"
    MODIFIED = "modified"


@dataclass
class Bookmark:
    """One export entry; page is one-based, zero marks an unresolved/non-page target."""

    title: str
    page: int
    level: int = 1
    id: str = field(default_factory=lambda: uuid4().hex)
    source_page: int | None = None
    logical_page: int | None = None
    original_xref: int | None = None


@dataclass
class TocPage:
    """Session-only recognition input, drafts and bounded request history for one page."""

    page: int
    crop: Rect = (0, 0, 1, 1)
    angle: float = 0
    requirements: str = ""
    draft: str = ""
    raw_response: str = ""
    status: Status = Status.PENDING
    error: str = ""
    edited: bool = False
    draft_invalid: bool = False
    request_trace: str = ""
    history: list[str] = field(default_factory=list)


@dataclass
class ConversationTurn:
    """One actual vision exchange, in memory only; never sent to the PDF worker."""

    page: int
    prompt: str
    image: bytes = field(repr=False)
    response: str = ""
    error: str = ""


class NeedsInformation(ValueError):
    """Recognition cannot be accepted until missing or ambiguous content is resolved."""


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[object, object]:
        result: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("YAML keys must be unique strings.")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def parse_draft(text: str, source_page: int, body_pdf: int, body_book: int) -> list[Bookmark]:
    """Parse YAML/JSON entries without coercing booleans, floats or unknown fields.

    Accept an entries/errors envelope or a legacy entry list. Explicit model
    problems raise NeedsInformation (a ValueError) before accepting any entries.
    A null printed page remains unresolved. A single fenced YAML/JSON response
    is accepted; commentary outside the fence is rejected. Raises ValueError
    for malformed or oversized drafts. Does not change the caller's raw text.
    """
    if len(text) > MAX_DRAFT:
        raise ValueError("The YAML draft is too large.")
    clean = text.strip()
    fenced = re.fullmatch(r"```(?:yaml|yml|json)?\s*\n(.*?)\n```", clean, re.DOTALL)
    if fenced:
        clean = fenced.group(1)
    try:
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(clean)):
            raise ValueError("YAML anchors and aliases are not supported.")
        data = yaml.load(clean, Loader=_UniqueLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if isinstance(data, dict):
        if set(data) != {"entries", "errors"} or not isinstance(data["entries"], list) or not isinstance(data["errors"], list):
            raise ValueError("Expected entries and errors lists, or a plain entry list.")
        problems: list[str] = []
        for number, issue in enumerate(data["errors"], 1):
            if (not isinstance(issue, dict) or set(issue) != {"error_message", "location", "needs"}
                    or any(not isinstance(value, str) or not value.strip() for value in issue.values())):
                raise ValueError(f"Error {number}: error_message, location and needs must be nonempty strings.")
            problems.append(f"{issue['location']}: {issue['error_message']}\nNeeded: {issue['needs']}")
        if problems:
            raise NeedsInformation("\n\n".join(problems))
        data = data["entries"]
    if not isinstance(data, list):
        raise ValueError("Expected a YAML list; use [] for an empty TOC page.")
    if len(data) > 10_000:
        raise ValueError("Too many entries in one TOC page.")
    entries: list[Bookmark] = []
    for number, row in enumerate(data, 1):
        if not isinstance(row, dict) or set(row) - {"page", "level", "index", "title"}:
            raise ValueError(f"Entry {number}: expected page, level, index and title fields only.")
        page, level = row.get("page"), row.get("level")
        title, index = row.get("title"), row.get("index", "")
        if "page" not in row or page is not None and (type(page) is not int or page == 0):
            raise ValueError(f"Entry {number}: page must be a nonzero integer or null.")
        if type(level) is not int or not 1 <= level <= 32:
            raise ValueError(f"Entry {number}: level must be an integer from 1 to 32.")
        if not isinstance(title, str) or not title.strip() or not isinstance(index, str):
            raise ValueError(f"Entry {number}: title/index must be quoted strings; title cannot be empty.")
        physical = 0 if page is None else body_pdf + (page if page > 0 else page + 1) - body_book
        entries.append(Bookmark(f"{index} {title}".strip(), physical, level,
                                source_page=source_page, logical_page=page))
    return entries


@dataclass
class BookSession:
    """Editable book session; page order determines recognition merge order."""

    source: Path
    page_count: int
    labels: list[str]
    bookmarks: list[Bookmark] = field(default_factory=list)
    toc: dict[int, TocPage] = field(default_factory=dict)
    body_pdf: int = 1
    body_book: int = 1
    requirements: str = ""
    api: LlmSettings = field(default_factory=LlmSettings)
    current_page: int = 1
    context_start: int = 1
    last_prompt_tokens: int = 0
    keep_existing: bool = False
    pending_only: bool = True
    clear_context: bool = False
    conversation: list[ConversationTurn] = field(default_factory=list, repr=False)

    def apply_draft(self, page: int, draft: str) -> None:
        """Replace one source page atomically, rejecting model issues/unresolved pages.

        Args:
            page: Physical TOC page already present in this session.
            draft: YAML/JSON envelope or legacy list with printed page targets.
        Raises:
            NeedsInformation: The model reports an issue or a printed page is null.
            ValueError: Draft syntax or entry fields are invalid.
        Only successful validation changes bookmarks and the page's accepted draft.
        """
        entries = parse_draft(draft, page, self.body_pdf, self.body_book)
        unresolved = [f"Entry {number} ({item.title}): printed page is missing or unreadable."
                      for number, item in enumerate(entries, 1) if item.logical_page is None]
        if unresolved:
            raise NeedsInformation("\n".join(unresolved) + "\nNeeded: provide the printed page number or its mapping.")
        retained = [item for item in self.bookmarks if item.source_page != page]
        insertion = next((i for i, item in enumerate(retained)
                          if item.source_page is not None and item.source_page > page), len(retained))
        self.bookmarks = retained[:insertion] + entries + retained[insertion:]
        self.toc[page].draft = draft
        self.toc[page].error = ""
        self.toc[page].edited = False
        self.toc[page].draft_invalid = False

    def remap(self, body_pdf: int, body_book: int) -> None:
        """Update recognition-derived targets; explicitly edited physical pages stay fixed."""
        if not 1 <= body_pdf <= self.page_count or body_book < 1:
            raise ValueError("The body anchor must be inside the PDF; printed start must be positive.")
        self.body_pdf, self.body_book = body_pdf, body_book
        for item in self.bookmarks:
            if item.logical_page is not None:
                number = item.logical_page if item.logical_page > 0 else item.logical_page + 1
                item.page = body_pdf + number - body_book

    def validate_export(self) -> None:
        """Reject unresolved targets and skipped hierarchy levels before modifying a PDF."""
        previous = 0
        for item in self.bookmarks:
            if not item.title.strip() or not 1 <= item.level <= previous + 1:
                raise ValueError(f"Invalid title/hierarchy: {item.title!r}. The first level must be 1; do not skip levels.")
            if not 1 <= item.page <= self.page_count and not (item.original_xref and item.page <= 0):
                raise ValueError(f"Resolve the physical target page for {item.title!r}: {item.page}.")
            previous = item.level

    def to_data(self) -> dict[str, object]:
        """Serialize this in-memory session for the private export worker only."""
        # Avoid serializing/copying the vision conversation into worker payloads.
        data = {key: value for key, value in self.__dict__.items() if key != "conversation"}
        data["bookmarks"] = [asdict(item) for item in self.bookmarks]
        data["labels"] = list(self.labels)
        data["api"] = asdict(self.api)
        data["source"] = str(self.source)
        data["toc"] = [{key: value for key, value in asdict(self.toc[page]).items()
                        if key not in ("request_trace", "history")} for page in sorted(self.toc)]
        return {"format": "pdf-bookmarks-session", "version": 1, **data}

    @classmethod
    def from_data(cls, data: dict[str, object], base: Path) -> "BookSession":
        """Validate and restore worker payloads; running tasks become interrupted."""
        if data.get("format") != "pdf-bookmarks-session" or data.get("version") != 1:
            raise ValueError("Unsupported bookmarks session.")
        try:
            source = (base / str(data["source"])).resolve()
            count = data["page_count"]
            labels = data["labels"]
            if type(count) is not int or count < 1 or not isinstance(labels, list) or len(labels) != count or not all(isinstance(v, str) for v in labels):
                raise ValueError("Invalid page count/labels.")
            session = cls(source, count, cast(list[str], list(labels)))
            for name in ("keep_existing", "pending_only", "clear_context"):
                value = data.get(name, getattr(session, name))
                if type(value) is not bool:
                    raise ValueError(f"Invalid {name}.")
                setattr(session, name, value)
            for field_name in ("body_pdf", "body_book", "current_page", "context_start", "last_prompt_tokens"):
                value = data.get(field_name, getattr(session, field_name))
                if type(value) is not int or value < (0 if field_name == "last_prompt_tokens" else 1):
                    raise ValueError(f"Invalid {field_name}.")
                setattr(session, field_name, value)
            if max(session.current_page, session.body_pdf, session.context_start) > count:
                raise ValueError("Saved page is outside the PDF.")
            session.requirements = str(data.get("requirements", ""))
            api = data.get("api", {})
            if not isinstance(api, dict):
                raise ValueError("Invalid API settings.")
            session.api = LlmSettings(**api)
            if (not isinstance(session.api.base_url, str) or not isinstance(session.api.model, str)
                    or not math.isfinite(session.api.temperature) or not 0 <= session.api.temperature <= 2
                    or type(session.api.max_tokens) is not int or not 1 <= session.api.max_tokens <= 65536
                    or type(session.api.timeout_seconds) is not int or not 5 <= session.api.timeout_seconds <= 1800
                    or type(session.api.max_context_images) is not int or session.api.max_context_images < 0):
                raise ValueError("Invalid API settings.")
            toc_rows = data.get("toc", [])
            bookmark_rows = data.get("bookmarks", [])
            if not isinstance(toc_rows, list) or not isinstance(bookmark_rows, list):
                raise ValueError("TOC pages and bookmarks must be lists.")
            for row in toc_rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid TOC page.")
                item = TocPage(**row)
                if type(item.page) is not int or not 1 <= item.page <= count or item.page in session.toc:
                    raise ValueError("Invalid/duplicate TOC page.")
                crop = tuple(float(v) for v in item.crop)
                if len(crop) != 4 or not 0 <= crop[0] < crop[2] <= 1 or not 0 <= crop[1] < crop[3] <= 1:
                    raise ValueError("Invalid recognition crop.")
                if not math.isfinite(item.angle) or not -180 <= item.angle <= 180:
                    raise ValueError("Invalid rotation.")
                if (any(not isinstance(value, str) for value in
                        (item.requirements, item.draft, item.raw_response, item.error))
                        or type(item.edited) is not bool or type(item.draft_invalid) is not bool
                        or len(item.draft) > MAX_DRAFT):
                    raise ValueError("Invalid TOC draft/requirements.")
                item.crop = cast(Rect, crop)
                item.status = Status(item.status)
                if item.status == Status.RUNNING:
                    item.status = Status.INTERRUPTED
                session.toc[item.page] = item
            seen: set[str] = set()
            for row in bookmark_rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid bookmark entry.")
                item = Bookmark(**row)
                if (not isinstance(item.id, str) or item.id in seen or not isinstance(item.title, str)
                        or type(item.page) is not int or type(item.level) is not int or not 1 <= item.level <= 32
                        or item.logical_page is not None and type(item.logical_page) is not int
                        or item.original_xref is not None and type(item.original_xref) is not int
                        or item.source_page is not None and item.source_page not in session.toc):
                    raise ValueError("Invalid bookmark entry.")
                seen.add(item.id)
                session.bookmarks.append(item)
            return session
        except (TypeError, KeyError, OverflowError) as exc:
            raise ValueError(f"Invalid session: {exc}") from exc
