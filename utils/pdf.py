"""Shared PDF authentication, bookmarks, labels, rendering and safe new-file output.

PyMuPDF is imported lazily; fixed-canvas pixmap rotation also lazily uses PySide6.
Importing utils never loads PDF or GUI libraries.
Operations on open documents stay in memory until Pdf.save_new is explicitly called.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import math
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, BinaryIO, Iterator, Sequence
from xml.dom import minidom
from xml.parsers.expat import ExpatError

from .ansi import FLRed, CRst
from .input import Input

if TYPE_CHECKING:
    import pymupdf


@dataclass(frozen=True)
class PdfBookmark:
    """Portable outline entry, independent of GUI identity and recognition state.

    Attributes:
        title: Display title, including Unicode characters.
        page: One-based physical target; nonpositive values retain an original
            non-page action only when original_xref identifies that source entry.
        level: One-based hierarchy depth in depth-first reading order.
        original_xref: Optional source outline xref for retaining styles/actions.
            Valid only in the same open document before object renumbering.
    """

    title: str
    page: int
    level: int = 1
    original_xref: int | None = None


_PDFA_NAMESPACES: tuple[str, ...] = (
    "http://www.aiim.org/pdfa/ns/id/",
    "http://www.aiim.org/pdfa/ns/id",  # Original PDF/A-1 specification typo.
)


def _process_pdfa_identification(document: "pymupdf.Document", *, remove: bool) -> bool:
    """Detect or remove PDF/A XMP properties using the same namespace rules.

    Args:
        document: Open, authenticated PDF to inspect or update before saving.
        remove: Remove matching properties in memory when True; otherwise read only.

    Returns:
        Whether any PDF/A identification property was found. A namespace
        declaration alone does not count as an identification property.

    Raises:
        ValueError: XMP mentioning PDF/A cannot be parsed safely.

    Handles element and attribute properties regardless of namespace prefix.
    Does not alter pages, other XMP schemas, or files on disk.
    """
    xml = document.get_xml_metadata()
    if not any(namespace in xml for namespace in _PDFA_NAMESPACES):
        return False
    try:
        metadata = minidom.parseString(xml)
    except ExpatError as exc:
        raise ValueError("Cannot process PDF/A identification: malformed XMP metadata.") from exc

    with metadata:
        found = False
        for element in list(metadata.getElementsByTagName("*")):
            if element.namespaceURI in _PDFA_NAMESPACES:
                found = True
                if remove and element.parentNode is not None:
                    element.parentNode.removeChild(element)
                continue
            for attribute in list(element.attributes.values()):
                if attribute.namespaceURI in _PDFA_NAMESPACES:
                    found = True
                    if remove:
                        element.removeAttributeNode(attribute)
        if found and remove:
            # DOM keeps existing prefixes, including those used in QName values.
            document.set_xml_metadata(metadata.toxml())
        return found


class _OutputStream:
    """Expose seekable output without a name that PyMuPDF would reopen."""

    def __init__(self, stream: BinaryIO) -> None:
        self.write = stream.write
        self.seek = stream.seek
        self.tell = stream.tell
        self.truncate = stream.truncate


class Pdf:
    """Common PDF operations used by the document-processing scripts."""

    @staticmethod
    def rotate_pixmap(pixmap: "pymupdf.Pixmap", angle: float) -> "pymupdf.Pixmap":
        """Rotate rendered RGB content on a fixed white canvas without shrinking.

        Args:
            pixmap: Nonempty, opaque RGB pixmap; never modified.
            angle: Clockwise degrees from -180 to 180; finite. Rotation is
                around the image center, clipping content beyond the canvas.
        Returns:
            RGB pixmap with unchanged dimensions, origin and DPI. Zero degrees
            returns the input itself; other angles allocate a new pixmap.
        Raises:
            ValueError: Angle is invalid or pixmap is not nonempty opaque RGB.
            ImportError: PyMuPDF or, for nonzero rotation, PySide6 is unavailable.
        Uses smooth interpolation. Requires no QApplication and performs no
        PDF edits, file writes or shared-memory operations.
        """
        import pymupdf

        if not math.isfinite(angle) or not -180 <= angle <= 180:
            raise ValueError("Rotation must be between -180 and 180 degrees.")
        if (pixmap.width <= 0 or pixmap.height <= 0 or pixmap.alpha or pixmap.colorspace is None
                or pixmap.colorspace.name != pymupdf.csRGB.name):
            raise ValueError("Rotation requires a nonempty opaque RGB pixmap.")
        if angle == 0:
            return pixmap
        from PySide6 import QtCore, QtGui

        width, height = pixmap.width, pixmap.height
        samples = pixmap.samples
        source = QtGui.QImage(samples, width, height, width * 3, QtGui.QImage.Format.Format_RGB888)
        target = QtGui.QImage(width, height, QtGui.QImage.Format.Format_RGB888)
        target.fill(QtCore.Qt.GlobalColor.white)
        painter = QtGui.QPainter(target)
        try:
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
            painter.translate(width / 2, height / 2)
            painter.rotate(angle)
            painter.drawImage(QtCore.QPointF(-width / 2, -height / 2), source)
        finally:
            painter.end()
        # QImage aligns rows to four bytes; PyMuPDF expects packed RGB.
        pixels = target.constBits()
        stride = target.bytesPerLine()
        packed = b"".join(pixels[y * stride:y * stride + width * 3] for y in range(height))
        result = pymupdf.Pixmap(pymupdf.csRGB, width, height, packed, False)
        result.set_origin(pixmap.x, pixmap.y)
        result.set_dpi(pixmap.xres, pixmap.yres)
        return result

    @staticmethod
    def render_page(page: "pymupdf.Page", *, dpi: float = 200, rotation: float = 0,
                    max_pixels: int = 12_000_000, annotations: bool = True) -> "pymupdf.Pixmap":
        """Render a page as opaque RGB with a strict integer-pixel budget.

        Args:
            page: Page from an open, authenticated PDF; never modified.
            dpi: Positive finite requested DPI, reduced when the budget requires.
            rotation: Additional clockwise rotation in degrees, from -180 to 180;
                the page's existing PDF rotation remains in effect.
            max_pixels: Positive maximum width times height, including rounding.
            annotations: Render PDF annotations when True.
        Returns:
            RGB Pixmap owned by the caller. No Qt, files or shared memory involved.
        Raises:
            ValueError: Parameters or page dimensions are invalid.
        """
        import pymupdf

        if (not math.isfinite(dpi) or dpi <= 0 or not math.isfinite(rotation)
                or not -180 <= rotation <= 180 or type(max_pixels) is not int or max_pixels < 4):
            raise ValueError("Use positive DPI, at least four pixels and rotation between -180 and 180 degrees.")
        rect = page.rect
        if rect.is_empty or rect.is_infinite:
            raise ValueError("Cannot render a page with invalid dimensions.")
        scale = dpi / 72
        matrix = pymupdf.Matrix(scale, scale).prerotate(rotation)
        area = (rect * matrix).get_area()
        if area > max_pixels:
            scale *= math.sqrt(max_pixels / area)
        # Account for integer bounding-box rounding before allocating the pixmap.
        while True:
            matrix = pymupdf.Matrix(scale, scale).prerotate(rotation)
            bounds = (rect * matrix).irect
            pixels = bounds.width * bounds.height
            if pixels <= max_pixels:
                break
            scale *= min(.999, math.sqrt(max_pixels / pixels))
        return page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False, annots=annotations)

    @staticmethod
    def read_bookmarks(document: "pymupdf.Document") -> list[PdfBookmark]:
        """Read editable bookmark rows while retaining source object identities.

        Args:
            document: Open, authenticated source PDF.
        Returns:
            Depth-first rows, including non-page entries. Source xrefs allow
            write_bookmarks to preserve exact destinations/actions and styles.
        Does not modify the document; xrefs must not be reused in another PDF.
        """
        return [PdfBookmark(str(title), int(page), int(level), int(destination["xref"]))
                for level, title, page, destination in document.get_toc(False)]

    @staticmethod
    def append_bookmark(document: "pymupdf.Document", title: str, page_index: int,
                        parent: int | None = None) -> int:
        """Append a fit-page bookmark without rebuilding existing outline entries.

        Args:
            document: Open, authenticated PDF to modify in memory.
            title: Unicode display title.
            page_index: Zero-based physical target page index.
            parent: Existing parent outline xref, or None for a root entry.
        Returns:
            New bookmark xref, usable as a parent for subsequent insertions.
        Raises:
            ValueError: Target/parent is invalid or the ancestor chain is cyclic.
        Preserves existing destinations, actions, styles and expansion states;
        modifies the outline only and does not save a file.
        """
        import pymupdf

        if type(page_index) is not int or not 0 <= page_index < document.page_count:
            raise ValueError("Bookmark target must be a valid zero-based page index.")
        if parent is None:
            kind, reference = document.xref_get_key(document.pdf_catalog(), "Outlines")
            if kind == "xref":
                parent = int(reference.split()[0])
            else:
                parent = Pdf.new_object(document, "<< /Type /Outlines /Count 0 >>")
                document.xref_set_key(document.pdf_catalog(), "Outlines", f"{parent} 0 R")
        if not 0 < parent < document.xref_length():
            raise ValueError("Invalid parent outline reference.")
        ancestors: dict[int, int] = {}
        ancestor = parent
        while ancestor:
            if ancestor in ancestors:
                raise ValueError("Cyclic bookmark ancestors.")
            kind, value = document.xref_get_key(ancestor, "Count")
            count = int(value) if kind == "int" else 0
            ancestors[ancestor] = count
            if count < 0:
                break
            kind, reference = document.xref_get_key(ancestor, "Parent")
            ancestor = int(reference.split()[0]) if kind == "xref" else 0
        kind, reference = document.xref_get_key(parent, "Last")
        previous = int(reference.split()[0]) if kind == "xref" else None
        page_xref = document.page_xref(page_index)
        xref = Pdf.new_object(document, f"<< /Title {pymupdf.get_pdf_str(title)} /Parent {parent} 0 R "
                              f"/Dest [{page_xref} 0 R /Fit] >>")
        if previous is None:
            document.xref_set_key(parent, "First", f"{xref} 0 R")
        else:
            document.xref_set_key(previous, "Next", f"{xref} 0 R")
            document.xref_set_key(xref, "Prev", f"{previous} 0 R")
        document.xref_set_key(parent, "Last", f"{xref} 0 R")
        for ancestor, count in ancestors.items():
            document.xref_set_key(ancestor, "Count", str(count - 1 if count < 0 else count + 1))
        return xref

    @staticmethod
    def write_bookmarks(document: "pymupdf.Document", bookmarks: Sequence[PdfBookmark]) -> None:
        """Replace an outline while preserving retained entries' PDF semantics.

        Args:
            document: Open, authenticated source PDF to modify in memory.
            bookmarks: Depth-first rows; an empty sequence clears the outline.
                Original xrefs must come from this same document. Retained entries
                keep color/style/collapse state; unchanged page targets also keep
                exact destinations or non-page actions. New/retargeted entries fit
                the whole target page.
        Raises:
            ValueError: Hierarchy, target or source outline reference is invalid.
        Validates all rows before replacing the outline. Does not change page
        objects, labels or save files. Saving with compaction invalidates xrefs.
        """
        originals = {entry.original_xref: entry for entry in Pdf.read_bookmarks(document)}
        previous_level = 0
        for entry in bookmarks:
            if type(entry.level) is not int or not 1 <= entry.level <= previous_level + 1:
                raise ValueError("Bookmark levels must start at one and cannot skip a level.")
            previous_level = entry.level
            original = originals.get(entry.original_xref) if entry.original_xref is not None else None
            if entry.original_xref is not None and original is None:
                raise ValueError("An original bookmark no longer exists in the PDF. Reopen the source.")
            if not isinstance(entry.title, str) or type(entry.page) is not int or entry.page > document.page_count:
                raise ValueError("Invalid bookmark title or target page.")
            if entry.page <= 0 and (original is None or original.page != entry.page):
                raise ValueError(f"Resolve the target of {entry.title!r} before export.")

        # Rebuild links, retaining references to old objects until the next save.
        document.xref_set_key(document.pdf_catalog(), "Outlines", "null")
        parents: list[int] = []
        children: dict[int, list[int]] = {0: []}
        collapsed: set[int] = set()
        for entry in bookmarks:
            original = originals.get(entry.original_xref)
            parents = parents[:entry.level - 1]
            parent = parents[-1] if parents else None
            xref = Pdf.append_bookmark(document, entry.title, max(0, entry.page - 1), parent)
            children.setdefault(parent or 0, []).append(xref)
            children[xref] = []
            parents.append(xref)
            if original is not None:
                assert entry.original_xref is not None
                keys = ["C", "F"]
                if original.page == entry.page:
                    keys.extend(("Dest", "A"))
                for key in keys:
                    _, value = document.xref_get_key(entry.original_xref, key)
                    document.xref_set_key(xref, key, value)
                kind, value = document.xref_get_key(entry.original_xref, "Count")
                if kind == "int" and int(value) < 0:
                    collapsed.add(xref)
        # Children were appended after parents, so reverse insertion order gives
        # a bottom-up count without Python recursion limits on deep outlines.
        visible: dict[int, int] = {}
        for parent in reversed(children):
            visible[parent] = sum(1 + (0 if child in collapsed else visible[child]) for child in children[parent])
            if parent:
                document.xref_set_key(parent, "Count", str(-visible[parent] if parent in collapsed else visible[parent]))
        kind, value = document.xref_get_key(document.pdf_catalog(), "Outlines")
        if kind == "xref":
            document.xref_set_key(int(value.split()[0]), "Count", str(visible[0]))

    @staticmethod
    def number_page_labels(labels: list[str], indexes: Sequence[int], first: int = 1, prefix: str = "") -> None:
        """Number selected navigation labels in caller-specified order.

        Args:
            labels: Mutable label list, normally obtained from read_page_labels.
            indexes: Zero-based selected page indexes in numbering order.
            first: Starting integer, including negative values or zero.
            prefix: Literal prefix placed before each decimal number.
        Raises:
            ValueError: Any page index is outside the label list.
        Mutates the list only; write_page_labels explicitly applies it to a PDF.
        """
        if any(not 0 <= index < len(labels) for index in indexes):
            raise ValueError("Label pages must be inside the PDF.")
        for offset, index in enumerate(indexes):
            labels[index] = f"{prefix}{first + offset}"

    @staticmethod
    def clear_page_labels(labels: list[str], indexes: Sequence[int]) -> None:
        """Blank selected navigation labels in a mutable list.

        Args:
            labels: One navigation label per physical page.
            indexes: Zero-based page indexes to clear.
        Raises:
            ValueError: Any index is outside the label list.
        Leaves unselected labels intact; does not modify a PDF or save files.
        """
        if any(not 0 <= index < len(labels) for index in indexes):
            raise ValueError("Label pages must be inside the PDF.")
        for index in indexes:
            labels[index] = ""

    @staticmethod
    def generate_page_labels(labels: list[str], body_pdf: int, body_book: int,
                             toc_pages: Sequence[int], *, toc_prefix: str = "C") -> None:
        """Generate body numbering and TOC labels while retaining other front matter.

        Args:
            labels: Mutable navigation label list, one entry per physical page.
            body_pdf: One-based physical first body page.
            body_book: Positive printed number of the first body page.
            toc_pages: One-based physical TOC pages, sorted/deduplicated internally.
            toc_prefix: TOC label prefix; defaults to C1, C2, etc.
        Raises:
            ValueError: Body/TOC page mapping is outside the document.
        Mutates only the list; TOC labels take precedence over body numbering.
        """
        if not 1 <= body_pdf <= len(labels) or body_book < 1 or any(not 1 <= page <= len(labels) for page in toc_pages):
            raise ValueError("Invalid body/TOC page mapping.")
        Pdf.number_page_labels(labels, list(range(body_pdf - 1, len(labels))), body_book)
        for number, page in enumerate(sorted(set(toc_pages)), 1):
            labels[page - 1] = f"{toc_prefix}{number}"

    @staticmethod
    def new_object(document: "pymupdf.Document", value: str = "<<>>", data: bytes | None = None) -> int:
        """Allocate a new PDF object, optionally with a decoded content stream.

        Args:
            document: Authenticated PDF to modify in memory.
            value: Valid PDF object syntax; defaults to an empty dictionary.
            data: Decoded stream bytes, or None for a non-stream object.

        Returns:
            The newly allocated cross-reference number.

        Raises:
            ValueError: The document is closed or the object syntax is invalid.

        Mutates only a new object in memory. Does not save or overwrite a file.
        """
        xref = document.get_new_xref()
        document.update_object(xref, value)
        if data is not None:
            document.update_stream(xref, data)
        return xref

    @staticmethod
    def read_dictionary(document: "pymupdf.Document", xref: int, key: str) -> str:
        """Resolve a direct/indirect dictionary without copying its child objects.

        Args:
            document: Open PDF containing the dictionary owner.
            xref: Owner object's cross-reference number.
            key: PDF key or slash-separated nested key path.

        Returns:
            Serialized dictionary syntax; an absent/null entry becomes ``<< >>``.

        Raises:
            ValueError: The entry is not a dictionary or the owner is invalid.

        Read-only; indirect references inside the dictionary remain references.
        """
        kind, value = document.xref_get_key(xref, key)
        if kind == "xref":
            return document.xref_object(int(value.split()[0]))
        if kind == "dict":
            return value
        if kind == "null":
            return "<< >>"
        raise ValueError(f"Expected a dictionary for object {xref}/{key}.")

    @staticmethod
    def has_pdfa_identification(document: "pymupdf.Document") -> bool:
        """Check for PDF/A identification independently of encryption or permissions.

        Args:
            document: Open, authenticated PDF to inspect.

        Returns:
            True when XMP contains PDF/A identification elements or attributes,
            regardless of namespace prefix or PDF/A version. A bare namespace
            declaration or ordinary text mentioning PDF/A returns False.

        Raises:
            ValueError: XMP mentioning a PDF/A namespace cannot be parsed safely.

        Does not modify metadata, save files, or read user input. This checks
        identification properties, not conformance to the PDF/A specification.
        """
        return _process_pdfa_identification(document, remove=False)

    @staticmethod
    @contextmanager
    def open_document(
        path: str | Path, *, password: str | None = None, interactive: bool = True,
    ) -> Iterator[tuple["pymupdf.Document", str]]:
        """Open and authenticate a PDF, closing it on success, failure, or cancellation.

        Args:
            path: Existing input PDF path.
            password: Known password to try before prompting. Keep the returned
                password in memory when another reader must open the same file.
            interactive: Allow private password prompts and retries. Set False
                for background readers; missing or rejected passwords then fail.

        Yields:
            The authenticated document and its accepted password (empty for
            input that needs none). Use this helper in a ``with`` statement.

        Raises:
            OSError: The file cannot be read.
            ValueError: The input is invalid, is not PDF, or authentication fails
                without interaction or is cancelled by empty password input.
            EOFError: Password input closes unexpectedly.
            KeyboardInterrupt: The user cancels the operation.

        Delegates all password interaction to unlock. Does not modify the source,
        write a decrypted temporary file, or persist passwords.
        """
        import pymupdf

        with pymupdf.open(path) as document:
            accepted_password = Pdf.unlock(document, password=password, interactive=interactive)
            yield document, accepted_password

    @staticmethod
    def read_page_labels(document: "pymupdf.Document") -> list[str]:
        """Read one effective navigation label for every PDF page.

        Args:
            document: Open, authenticated PDF.

        Returns:
            Labels in physical page order, including intentional blanks. When
            no label rules exist, returns physical page numbers starting at 1.

        Does not modify the document or read user input.
        """
        import pymupdf.mupdf as mupdf
        from pymupdf.utils import construct_label

        # Decode actual PDF strings: get_label() parses serialized rules as
        # plain text, corrupting Unicode and escaped parentheses/backslashes.
        native = mupdf.pdf_document_from_fz_document(document.this)
        root = mupdf.pdf_dict_gets(mupdf.pdf_trailer(native), "Root")
        pending = [mupdf.pdf_dict_gets(root, "PageLabels")]
        rules: dict[int, tuple[str, str, int]] = {}
        visited: set[int] = set()
        while pending:
            node = pending.pop()
            reference = mupdf.pdf_to_num(node)
            if reference:
                if reference in visited:
                    continue
                visited.add(reference)
            nums = mupdf.pdf_dict_gets(node, "Nums")
            for offset in range(0, mupdf.pdf_array_len(nums) - 1, 2):
                start = mupdf.pdf_array_get_int(nums, offset)
                rule = mupdf.pdf_array_get(nums, offset + 1)
                prefix = mupdf.pdf_to_text_string(mupdf.pdf_dict_gets(rule, "P"))
                style = mupdf.pdf_to_name(mupdf.pdf_dict_gets(rule, "S"))
                first = max(1, mupdf.pdf_to_int(mupdf.pdf_dict_gets(rule, "St")))
                rules[start] = (prefix, style, first)
            kids = mupdf.pdf_dict_gets(node, "Kids")
            pending.extend(mupdf.pdf_array_get(kids, index) for index in range(mupdf.pdf_array_len(kids)))

        # Expand rules once so subsequent edits can affect arbitrary pages.
        labels = [str(index + 1) for index in range(document.page_count)]
        starts = sorted(rules)
        for position, start in enumerate(starts):
            end = starts[position + 1] if position + 1 < len(starts) else document.page_count
            prefix, style, first = rules[start]
            for index in range(max(0, start), min(end, document.page_count)):
                number = first + index - start
                if style in ("A", "a"):
                    # PDF uses A..Z, AA..ZZ, AAA..ZZZ (not spreadsheet numbering).
                    letter = chr(ord("A" if style == "A" else "a") + (number - 1) % 26)
                    labels[index] = f"{prefix}{letter * ((number - 1) // 26 + 1)}"
                else:
                    labels[index] = construct_label(style, prefix, number)
        return labels

    @staticmethod
    def write_page_labels(document: "pymupdf.Document", labels: Sequence[str]) -> None:
        """Set literal navigation labels in memory without changing page content.

        Args:
            document: Open, authenticated PDF to update.
            labels: Exactly one string per physical page; empty strings make
                labels blank instead of restoring automatic physical numbering.

        Raises:
            ValueError: Label count differs from the PDF page count.

        Modifies only page-label rules; does not save the document to disk.
        """
        if len(labels) != document.page_count:
            raise ValueError("Provide exactly one label per PDF page.")
        import pymupdf

        # set_page_labels() interpolates prefixes as raw PDF strings. Encode
        # each literal properly so arbitrary user prefixes remain valid PDF.
        rules = " ".join(
            f"{index} << /P {pymupdf.get_pdf_str(label)} >>" for index, label in enumerate(labels)
        )
        document.xref_set_key(document.pdf_catalog(), "PageLabels", f"<< /Nums [{rules}] >>")

    @staticmethod
    def unlock(
        document: "pymupdf.Document", *, password: str | None = None, interactive: bool = True,
    ) -> str:
        """Authenticate a PDF, prompting privately only when necessary.

        Args:
            document: Open PDF; empty-password protection is handled silently.
            password: Known password to try before asking the user.
            interactive: Whether missing or incorrect passwords may prompt.

        Returns:
            Accepted password, or an empty string if no password was needed.
            For an already authenticated document, returns the supplied password
            or an empty string; it cannot recover a previous reader's password.

        Raises:
            ValueError: Input is not PDF, empty password input cancels, or a
                password is required but interactive is False.

        Prompts and prints retry messages; does not persist the password.
        """
        if not document.is_pdf:
            raise ValueError("The input must be a PDF document.")
        if not document.is_encrypted:
            return (password or "") if document.needs_pass else ""
        if document.authenticate(""):
            return ""
        if password is not None and document.authenticate(password):
            return password
        if not interactive:
            raise ValueError("The PDF requires a valid opening password.")
        if password is not None:
            print(f"{FLRed}Incorrect password. Please try again.{CRst}")
        while True:
            password = Input.input_password("PDF opening password (empty to cancel)")
            if not password:
                raise ValueError("No password provided. Operation cancelled.")
            if document.authenticate(password):
                return password
            print(f"{FLRed}Incorrect password. Please try again.{CRst}")

    @staticmethod
    def save_new(document: "pymupdf.Document", output_path: str | Path, *, compact: bool = True,
                 overwrite: bool = False) -> None:
        """Save an unencrypted, non-PDF/A copy with explicit replacement support.

        Args:
            document: Open, authenticated PDF to save.
            output_path: Destination with an existing parent directory.
            compact: Compact object numbers and merge duplicates (default True).
                Use False for a document that will remain open for further edits
                and saves, preserving live object references.
            overwrite: Explicit permission to replace an existing output after
                a complete staged save. Defaults False. The input is protected.

        Raises:
            FileExistsError: The destination exists and overwrite is False.
            OSError: Opening or writing the destination fails.
            ValueError: The destination is the source with overwrite=True,
                PyMuPDF cannot save the document, or PDF/A XMP is malformed.

        Writes the PDF and removes only this call's new output on failure or
        interruption. With overwrite=True, replaces the destination only after
        a complete staged save. Discards unreferenced objects, including replaced images.
        Removes PDF/A identification from the in-memory XMP before saving;
        does so even for unencrypted, unrestricted input. Retains other metadata
        and does not modify the source file.
        """
        from pymupdf.mupdf import PDF_ENCRYPT_NONE

        path = Path(output_path)
        if overwrite:
            if document.name and (Path(document.name).resolve() == path.resolve()
                    or path.exists() and Path(document.name).exists() and os.path.samefile(document.name, path)):
                raise ValueError("The source PDF cannot be overwritten.")
            with tempfile.TemporaryDirectory(prefix=".pdf-save-", dir=path.parent) as directory:
                staged = Path(directory) / "result.pdf"
                Pdf.save_new(document, staged, compact=compact)
                os.replace(staged, path)
            return
        with path.open("xb") as destination:
            try:
                _process_pdfa_identification(document, remove=True)
                document.save(_OutputStream(destination), garbage=3 if compact else 1, deflate=True,
                              encryption=PDF_ENCRYPT_NONE)
            except BaseException:
                destination.close()
                path.unlink(missing_ok=True)
                raise
