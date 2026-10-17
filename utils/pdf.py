"""Shared PDF authentication and ordinary-PDF output; PyMuPDF is imported lazily."""

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Iterator, Sequence
from xml.dom import minidom
from xml.parsers.expat import ExpatError

from .ansi import FLRed, CRst
from .input import Input

if TYPE_CHECKING:
    import pymupdf


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
    def save_new(document: "pymupdf.Document", output_path: str | Path, *, compact: bool = True) -> None:
        """Save an unencrypted, non-PDF/A copy without overwriting existing files.

        Args:
            document: Open, authenticated PDF to save.
            output_path: New destination with an existing parent directory.
            compact: Compact object numbers and merge duplicates (default True).
                Use False for a document that will remain open for further edits
                and saves, preserving live object references.

        Raises:
            FileExistsError: The destination exists, including the input file.
            OSError: Opening or writing the destination fails.
            ValueError: PyMuPDF cannot save the document, or PDF/A XMP is malformed.

        Writes the PDF and removes only this call's new output on failure or
        interruption. Discards unreferenced objects, including replaced images.
        Removes PDF/A identification from the in-memory XMP before saving;
        does so even for unencrypted, unrestricted input. Retains other metadata
        and does not modify the source file.
        """
        from pymupdf.mupdf import PDF_ENCRYPT_NONE

        path = Path(output_path)
        with path.open("xb") as destination:
            try:
                _process_pdfa_identification(document, remove=True)
                document.save(_OutputStream(destination), garbage=3 if compact else 1, deflate=True,
                              encryption=PDF_ENCRYPT_NONE)
            except BaseException:
                destination.close()
                path.unlink(missing_ok=True)
                raise
