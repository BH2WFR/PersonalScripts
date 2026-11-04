"""Serializable replacement rules; no PDF or Qt operations during validation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from utils import *
from ..common.protocol import Json
from .engine import _Embedding, _Rule, _rgb_key


def face_data(face: FontFace) -> dict[str, Json]:
    """Encode font metadata for the private worker protocol without ANSI labels."""
    return {"path": str(face.path), "index": face.index, "name": face.name,
            "family": face.family, "style": face.style.name,
            "aliases": list(face.aliases), "full_names": list(face.full_names),
            "family_names": list(face.family_names)}


def read_face(data: dict[str, Json]) -> FontFace:
    """Decode worker metadata; font bytes are verified by the replacement engine."""
    return FontFace(Path(str(data["path"])), int(cast(int, data["index"])),
                    str(data["name"]), str(data["family"]),
                    tuple(str(value) for value in cast(list[Json], data["aliases"])),
                    FontStyle[str(data["style"])],
                    tuple(str(value) for value in cast(list[Json], data.get("full_names", []))),
                    tuple(str(value) for value in cast(list[Json], data.get("family_names", []))))


@dataclass
class ReplacementRule:
    """One editable rule matching original PDF text, never earlier rule output.

    Empty source names mean all fonts. Applied pages default to all; ignored
    pages are subtracted. Both use utils.Input range syntax. Empty colors mean
    all sources / retain originals, except color-only rules require a target.
    Source colors are separated by semicolons, allowing commas inside RGB values.
    """

    names: tuple[str, ...] = ()
    sizes: str = ""
    ignored: str = ""
    source_colors: str = ""
    color: str = ""
    faces: dict[FontStyle, FontFace] = field(default_factory=dict)
    embedding: _Embedding = _Embedding.SUBSET
    remove_original: bool = False
    pages: str = "all"
    color_only: bool = False

    def compile(self, page_count: int) -> _Rule:
        """Validate user expressions and return an engine rule.

        Args:
            page_count: Positive physical input page count for exclusions.
        Raises:
            ValueError: Invalid ranges, colors, or no replacement face selected.
        """
        sizes = Input.parse_real_ranges(self.sizes)
        if any(low <= 0 for low, _ in sizes):
            raise ValueError("Font sizes must be greater than zero.")
        selected = set(Input.parse_index_ranges(self.pages.strip() or "all", item_count=page_count))
        excluded = set(Input.parse_index_ranges(self.ignored, item_count=page_count))
        ignored = tuple(index for index in range(page_count) if index not in selected or index in excluded)
        if self.color_only and not self.color.strip():
            raise ValueError("Choose a new text color for a color-only rule.")
        if not self.color_only and not self.faces:
            raise ValueError("Select a target font or load a font file first.")
        if any(style != face.style for style, face in self.faces.items()):
            raise ValueError("Target faces must match their assigned styles.")
        colors = None
        if self.source_colors.strip():
            colors = frozenset(_rgb_key(Input.parse_color(value.strip()))
                               for value in self.source_colors.split(";"))
        return _Rule(set(self.names) if self.names else None, sizes, ignored, dict(self.faces),
                     self.embedding, self.remove_original and not self.color_only,
                     Input.parse_color(self.color) if self.color.strip() else None, colors, self.color_only)

    def to_data(self) -> dict[str, Json]:
        """Return a detached JSON-safe representation for an isolated worker."""
        return {"names": list(self.names), "sizes": self.sizes, "ignored": self.ignored,
                "source_colors": self.source_colors, "color": self.color,
                "faces": [face_data(face) for face in self.faces.values()],
                "embedding": self.embedding.value, "remove_original": self.remove_original,
                "pages": self.pages, "color_only": self.color_only}

    @classmethod
    def from_data(cls, data: dict[str, Json]) -> "ReplacementRule":
        """Decode a private worker payload; compile validates expressions next."""
        faces = [read_face(cast(dict[str, Json], row)) for row in cast(list[Json], data["faces"])]
        return cls(tuple(str(name) for name in cast(list[Json], data["names"])),
                   str(data["sizes"]), str(data["ignored"]), str(data["source_colors"]),
                   str(data["color"]), {face.style: face for face in faces},
                   _Embedding(str(data["embedding"])), data["remove_original"] is True,
                   str(data.get("pages", "all")), data.get("color_only") is True)

    def labels(self) -> tuple[str, str]:
        """Return the source/target columns for the ordered replacement list."""
        source = ", ".join(self.names) if self.names else "All fonts"
        target = ", ".join(dict.fromkeys(face.family for face in self.faces.values()))
        if self.color_only:
            source = f"{source} · {self.source_colors or 'All colors'}"
            target = f"Color → {self.color} (keep font)"
        elif self.color:
            target = f"{target} · {self.color}"
        return source, target
