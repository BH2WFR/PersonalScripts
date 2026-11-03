"""Bounded per-page LRU storage shared by desktop PDF preview caches."""

from collections import OrderedDict
from collections.abc import Callable

from PySide6.QtGui import QPixmap

CACHE_BYTES = 512 * 1024 * 1024
CACHE_PAGES = 100


def pixmap_bytes(pixmap: QPixmap) -> int:
    """Return pixel storage including 32-bit scanline alignment."""
    return ((pixmap.width() * pixmap.depth() + 31) // 32) * 4 * pixmap.height()


class PageCache[T]:
    """Keep recently used pages within both a byte budget and a page count.

    Args:
        measure: Return the retained byte size of one page value.
        max_bytes: Pixel budget, default 512 MiB.
        max_pages: Page budget, default 100. Nonpositive limits disable retention.

    A put replaces that page's previous value. Reads refresh recency. Values
    must not be mutated in place; submit a replacement so accounting stays valid.
    """

    def __init__(self, measure: Callable[[T], int], max_bytes: int = CACHE_BYTES,
                 max_pages: int = CACHE_PAGES) -> None:
        self.measure = measure
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.size = 0
        self._pages: OrderedDict[int, tuple[T, int]] = OrderedDict()

    def clear(self) -> None:
        """Release all page values and reset byte accounting."""
        self._pages.clear()
        self.size = 0

    def get(self, page: int) -> T | None:
        """Return a page value and refresh its recency, or None for a miss."""
        entry = self._pages.get(page)
        if entry is None:
            return None
        self._pages.move_to_end(page)
        return entry[0]

    def put(self, page: int, value: T) -> None:
        """Replace a page and evict oldest values until both budgets are met."""
        previous = self._pages.pop(page, None)
        if previous is not None:
            self.size -= previous[1]
        size = self.measure(value)
        if 0 <= size <= self.max_bytes and self.max_pages > 0:
            self._pages[page] = value, size
            self.size += size
        while self._pages and (self.size > self.max_bytes or len(self._pages) > self.max_pages):
            _, (_, removed) = self._pages.popitem(last=False)
            self.size -= removed
