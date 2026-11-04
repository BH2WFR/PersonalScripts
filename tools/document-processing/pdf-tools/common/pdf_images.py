"""Displayed PDF image occurrences and their effective page resolutions."""

from dataclasses import dataclass
import math

import pymupdf


@dataclass(frozen=True)
class ImageElement:
    codec: str
    width: int
    height: int
    dpi_x: float
    dpi_y: float
    # Visible position in page points, measured from the displayed page's top left.
    position: tuple[float, float, float, float]
    # The same visible bounds scaled to [0, 1] for the raster preview overlay.
    bounds: tuple[float, float, float, float]

    def to_data(self) -> dict[str, object]:
        return {"codec": self.codec, "width": self.width, "height": self.height,
                "dpi_x": self.dpi_x, "dpi_y": self.dpi_y,
                "position": list(self.position), "bounds": list(self.bounds)}

    @classmethod
    def from_data(cls, data: dict[str, object]) -> "ImageElement":
        return cls(str(data["codec"]), int(data["width"]), int(data["height"]),
                   float(data["dpi_x"]), float(data["dpi_y"]),
                   tuple(float(value) for value in data["position"]),  # type: ignore[arg-type]
                   tuple(float(value) for value in data["bounds"]))  # type: ignore[arg-type]


def _codec(document: pymupdf.Document, xref: int) -> str:
    if not xref:
        return "Inline / unknown"
    _, filters = document.xref_get_key(xref, "Filter")
    for name, label in (("DCTDecode", "JPEG"), ("JPXDecode", "JPEG 2000"),
                        ("JBIG2Decode", "JBIG2"), ("CCITTFaxDecode", "CCITT"),
                        ("FlateDecode", "Flate"), ("LZWDecode", "LZW"),
                        ("RunLengthDecode", "Run-length")):
        if name in filters:
            return label
    return "Uncompressed" if filters == "null" else "Unknown"


def inspect_images(page: pymupdf.Page) -> tuple[ImageElement, ...]:
    """Report each visible image placement, including repeated and nested images.

    Effective DPI comes from pixel count and the placement transform, not the
    often inaccurate XResolution/YResolution tags stored in the image stream.
    """
    visible = page.rect
    elements = []
    for info in page.get_image_info(xrefs=True):
        matrix = info["transform"]
        axis_x = math.hypot(matrix[0], matrix[1])
        axis_y = math.hypot(matrix[2], matrix[3])
        if not axis_x or not axis_y:
            continue
        bbox = pymupdf.Rect(info["bbox"]) & visible
        if bbox.is_empty:
            continue
        x0, y0 = bbox.x0 - visible.x0, bbox.y0 - visible.y0
        x1, y1 = bbox.x1 - visible.x0, bbox.y1 - visible.y0
        elements.append(ImageElement(
            _codec(page.parent, info["xref"]), info["width"], info["height"],
            info["width"] * 72 / axis_x, info["height"] * 72 / axis_y,
            (x0, y0, x1, y1),
            (x0 / visible.width, y0 / visible.height, x1 / visible.width, y1 / visible.height)))
    return tuple(elements)
