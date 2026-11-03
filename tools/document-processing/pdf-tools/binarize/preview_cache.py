"""Bounded desktop preview cache with one latest result per page and view.

Qt pixmaps stay in the GUI process. Original pixels are independent of processing
settings; detected boxes and processed pixels require matching configuration.
The owning window clears the cache when adopting another PDF/project.
"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QPixmap

from .project import Config, Project, SKIP_ID
from ..common.page_cache import CACHE_BYTES, CACHE_PAGES, PageCache, pixmap_bytes

type Rectangle = tuple[float, float, float, float]


@dataclass(frozen=True)
class PreviewState:
    """Immutable page/configuration snapshot captured before submitting a job."""

    page: int
    original: bool
    config: Config | None
    region_input: Path | None
    show_regions: bool

    @classmethod
    def from_project(cls, project: Project) -> "PreviewState":
        """Snapshot the active view; skipped pages require neither settings nor boxes."""
        profile = project.profiles[project.assignments[project.current_page]]
        skipped = profile.id == SKIP_ID
        return cls(project.current_page, project.show_original or skipped,
                   None if skipped else profile.config,
                   None if skipped else project.output.region_input,
                   project.show_regions and not skipped)


@dataclass(frozen=True)
class PreviewFrame:
    """Detached pixels and region metadata; callers must not mutate the pixmap."""

    state: PreviewState
    pixmap: QPixmap
    regions: tuple[Rectangle, ...]
    regions_available: bool

    def matches_regions(self, state: PreviewState) -> bool:
        """Whether these boxes were calculated with the requested processing inputs."""
        return (self.regions_available and self.state.config == state.config
                and self.state.region_input == state.region_input)

    @property
    def size(self) -> int:
        """Estimated pixel storage in bytes, including 32-bit scanline alignment."""
        return pixmap_bytes(self.pixmap)


class PreviewCache:
    """Keep at most 100 physical pages and 512 MiB of decoded preview pixels.

    Args:
        max_bytes: Pixel-memory budget; defaults to 512 MiB.
        max_pages: Physical-page budget, counting both views together; defaults to 100.

    Reads refresh page recency. Inserting a view replaces its previous settings
    version, then evicts least recently used pages (both views) until within budget.
    """

    def __init__(self, max_bytes: int = CACHE_BYTES, max_pages: int = CACHE_PAGES) -> None:
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self._store = PageCache[dict[bool, PreviewFrame]](
            lambda views: sum(frame.size for frame in views.values()), max_bytes, max_pages)

    @property
    def size(self) -> int:
        """Return the current retained pixel storage in bytes."""
        return self._store.size

    def clear(self) -> None:
        """Release every cached page when the document session ends or changes."""
        self._store.clear()

    def get(self, state: PreviewState) -> PreviewFrame | None:
        """Return compatible pixels immediately, or None when rendering is required."""
        frame = (self._store.get(state.page) or {}).get(state.original)
        if frame is None:
            return None
        if not state.original and (frame.state.config != state.config
                                    or frame.state.region_input != state.region_input):
            return None
        if state.show_regions and not frame.matches_regions(state):
            return None
        return frame

    def put(self, frame: PreviewFrame) -> None:
        """Replace this page's same-view result and enforce memory/page bounds."""
        page, original = frame.state.page, frame.state.original
        views = dict(self._store.get(page) or {})
        views[original] = frame
        self._store.max_bytes, self._store.max_pages = self.max_bytes, self.max_pages
        self._store.put(page, views)
