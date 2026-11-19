"""Round-trip PDF Info values and document XMP using an authenticated source."""

from typing import TypedDict

import pymupdf
from pymupdf import mupdf
from utils import *
from .xmp import FIELDS, Packet


class Property(TypedDict):
    """A text or PDF-syntax value with its original key for lossless renames."""

    original: str
    key: str
    value: str
    raw: bool


def _trailer(document: pymupdf.Document) -> mupdf.PdfObj:
    return mupdf.pdf_trailer(mupdf.pdf_document_from_fz_document(document.this))


def read_properties(document: pymupdf.Document) -> list[Property]:
    """Read literal dictionary keys, including spaces, Unicode and slash characters."""
    info = mupdf.pdf_dict_gets(_trailer(document), "Info")
    rows: list[Property] = []
    for index in range(mupdf.pdf_dict_len(info)):
        key = mupdf.pdf_to_name(mupdf.pdf_dict_get_key(info, index))
        obj = mupdf.pdf_dict_get_val(info, index)
        raw = not mupdf.pdf_is_string(obj)
        if raw:
            buffer = pymupdf.JM_object_to_buffer(obj, 1, 1)
            value = mupdf.fz_string_from_buffer(buffer)
        else:
            value = mupdf.pdf_to_text_string(obj)
        rows.append(Property(original=key, key=key, value=value, raw=raw))
    return rows


def _pdf_value(document: pymupdf.Document, row: Property) -> mupdf.PdfObj:
    if not row["raw"]:
        if "\0" in row["value"]:
            raise ValueError(f"Use PDF syntax to enter binary data for {row['key']}.")
        return mupdf.pdf_new_text_string(row["value"])
    # Parsing inside an array also handles indirect references as single values.
    data = ("[" + row["value"] + "\n]").encode("utf-8")
    stream = mupdf.fz_open_buffer(mupdf.fz_new_buffer_from_copied_data(data))
    lexer = mupdf.PdfLexbuf(mupdf.PDF_LEXBUF_SMALL)
    native = mupdf.pdf_document_from_fz_document(document.this)
    array = mupdf.pdf_parse_stm_obj(native, stream, lexer)
    if mupdf.pdf_array_len(array) != 1 or mupdf.pdf_lex(stream, lexer) != mupdf.PDF_TOK_EOF:
        raise ValueError(f"Enter one PDF value for {row['key']}.")
    return mupdf.pdf_array_get(array, 0)


def write_properties(document: pymupdf.Document, rows: list[Property]) -> None:
    """Replace the Info dictionary, retaining original objects for unchanged values."""
    originals = {row["key"]: row for row in read_properties(document)}
    keys = [row["key"] for row in rows]
    if len(set(keys)) != len(keys) or any(not key or "\0" in key for key in keys):
        raise ValueError("Each property needs a distinct, nonempty name without NUL.")
    if len(rows) == len(originals) and all(row == originals.get(row["key"]) for row in rows):
        return
    trailer = _trailer(document)
    if not rows:
        document.xref_set_key(-1, "Info", "null")
        return
    native = mupdf.pdf_document_from_fz_document(document.this)
    old = mupdf.pdf_dict_gets(trailer, "Info")
    new = mupdf.pdf_new_dict(native, len(rows))
    for row in rows:
        original = originals.get(row["original"])
        if original and (original["value"], original["raw"]) == (row["value"], row["raw"]):
            obj = mupdf.pdf_dict_gets(old, row["original"])
        else:
            obj = _pdf_value(document, row)
        mupdf.pdf_dict_puts(new, row["key"], obj)
    reference = mupdf.pdf_to_num(mupdf.pdf_add_object(native, new))
    # Adding the first object can create a new incremental trailer.
    document.xref_set_key(-1, "Info", f"{reference} 0 R")


def common_values(rows: list[Property], xml: str) -> dict[str, str]:
    """Prefer Info text, falling back to the corresponding XMP property."""
    try:
        packet = Packet(xml) if xml else None
    except ValueError:
        packet = None  # The raw editor can still repair a malformed packet.
    values = {key: packet.read(key) if packet else "" for key in FIELDS}
    values.update({row["key"]: row["value"] for row in rows if row["key"] in FIELDS and not row["raw"]})
    return values


def apply_edits(document: pymupdf.Document, extras: list[Property], common: dict[str, str],
                xml: str | None, marker: str, *, sync_xmp_title: bool = True) -> None:
    """Apply changed common fields to Info and existing XMP, then apply marker policy.

    A None XML draft preserves the original packet. An empty draft deletes it.
    A raw, non-text standard property stays in the table until explicitly edited.
    When sync_xmp_title is false the language editor owns the XMP title, including its absence.
    """
    original = read_properties(document)
    fields = {row["key"]: row for row in original if row["key"] in FIELDS and not row["raw"]}
    for key, value in common.items():
        if key not in FIELDS:
            raise ValueError(f"Unknown common field: {key}")
        if value:
            fields[key] = Property(original=key, key=key, raw=False, value=value)
        else:
            fields.pop(key, None)
    write_properties(document, [*fields.values(), *extras])
    if xml is not None:
        if xml.strip():
            Packet(xml)  # Validate the draft before passing it to MuPDF.
            document.set_xml_metadata(xml)
        else:
            document.del_xml_metadata()
    if marker != "keep":
        Pdf.remove_pdfa_identification(document)
    adding_marker = marker not in ("keep", "remove")
    current = document.get_xml_metadata()
    if adding_marker or (common and current):
        packet = Packet(current)
        # When creating the first packet for a marker, populate existing common values too.
        changes = common if current else {key: row["value"] for key, row in fields.items()}
        for key, value in changes.items():
            if key != "Title" or sync_xmp_title:
                packet.update(key, value)
        if adding_marker:
            packet.add_profile(marker)
        updated = packet.dom.toxml()
        Packet(updated)  # Reject XML-invalid input such as embedded control characters.
        document.set_xml_metadata(updated)


def identity(stat: os.stat_result) -> str:
    """Encode the input identity without passing unsigned OS integers through Qt."""
    return f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}"
