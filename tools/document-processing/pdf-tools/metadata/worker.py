"""Inspect and export in a serial worker. Only its private pipe carries passwords."""

from collections.abc import Callable
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
from typing import cast

from utils import *
from ..common.protocol import Json
from ..common.task_control import Cancelled, TaskControl
from .engine import Property, apply_edits, common_values, identity, read_properties


def run(request: dict[str, Json], progress: Callable[[dict[str, Json]], None]) -> dict[str, Json]:
    """Inspect a source or apply the draft to a fresh reader before staged publication."""
    path = Path(str(request["path"]))
    stat = path.stat()
    fingerprint = identity(stat)
    inspect = request["operation"] == "inspect"
    if not inspect and request.get("identity") != fingerprint:
        raise ValueError("The source file changed. Reopen it before exporting.")
    try:
        with Pdf.open_document(path, password=str(request.get("password", "")), interactive=False) as (document, _):
            if inspect:
                protected = document.xref_get_key(-1, "Encrypt")[0] != "null"
                if protected and not request.get("unlock"):
                    return {"kind": "unlock"}
                xml = document.get_xml_metadata()
                rows = read_properties(document)
                try:
                    marker = "present" if Pdf.has_pdfa_identification(document) else "absent"
                except ValueError:
                    marker = "unreadable XMP"
                return cast(dict[str, Json], {
                    "kind": "opened", "pages": document.page_count, "identity": fingerprint, "size": stat.st_size,
                    "format": document.metadata["format"], "protected": protected, "marker": marker,
                    "xml": xml, "rows": rows, "common": common_values(rows, xml),
                })
            if request["operation"] != "export":
                raise ValueError("Unknown metadata operation.")
            control = TaskControl.from_request(request, progress)
            control.checkpoint()
            protection = None
            if request.get("protect"):
                protection = PdfProtection(str(request["owner"]), str(request["user"]), cast(int, request["permissions"]))
            marker = str(request["marker"])
            apply_edits(document, cast(list[Property], request["extras"]), cast(dict[str, str], request["common"]),
                        cast(str | None, request["xml"]), marker, sync_xmp_title=request.get("sync_xmp_title") is not False)
            output = Path(str(request["output"]))
            control.save(document, output, path, overwrite=request["overwrite"] is True,
                         preserve_pdfa=marker != "remove", protection=protection)
            return {"kind": "exported", "path": str(output)}
    except PdfPasswordRequired:
        if inspect:
            return {"kind": "password" if request.get("unlock") else "unlock"}
        raise


def main() -> int:
    """Serve the GUI until its private pipe closes."""
    stream = sys.stdout

    def send(reply: dict[str, Json]) -> None:
        print(json.dumps(reply, ensure_ascii=True), file=stream, flush=True)

    for line in sys.stdin:
        try:
            with redirect_stdout(sys.stderr):
                reply = run(json.loads(line), send)
        except Cancelled as exc:
            reply = {"kind": "cancelled", "message": str(exc)}
        except Exception as exc:
            reply = {"kind": "error", "message": str(exc)}
        send(reply)
    return 0
