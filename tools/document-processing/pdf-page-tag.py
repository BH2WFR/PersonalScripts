#!/usr/bin/env python3
"""Edit PDF navigation page labels through a persistent interactive menu.

Load once, then add numbered labels to an inclusive page interval, clear all
labels, or clear selected labels using ranges such as 1,2-3,-1. Physical page
numbers start at 1; negative page numbers count from the end. Adding labels
requires a start page, defaults the end to -1 (last page), the first sequence
number to 1, and the prefix to empty. Sequence numbers may be negative or zero.
Overlapping edits replace only the selected labels; all other labels remain.
Clearing means blank navigation labels, not deleting printed page content.

Edits stay in memory until Save or Save and exit. Every save prompts for a new
output path (default: <input>_tagged.pdf), avoids overwriting existing files,
and writes an unencrypted copy retaining bookmarks, page content and metadata.
PDF/A identification is automatically removed while other metadata is retained.
Save returns to the menu. Exit without saving discards edits since the last
save; previously saved copies remain. No temporary PDF or page files are used.

Requirements:
    - pip: PyMuPDF

Usage:
    python pdf-page-tag.py [input.pdf]
    python pdf-page-tag.py input.pdf -o output.pdf
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

try:
    import pymupdf
    from pymupdf.mupdf import FzErrorBase
except ImportError as exc:
    print(f"{FLRed}Missing PDF dependency: {exc.name}{CRst}")
    print(f"{FGray}Install with: pip install PyMuPDF{CRst}")
    sys.exit(1)


class _Action(enum.StrEnum):
    ADD = "add"
    CLEAR_ALL = "clear_all"
    CLEAR_PART = "clear_part"
    SAVE = "save"
    SAVE_EXIT = "save_exit"
    EXIT = "exit"


def _input_page(prompt: str, page_count: int, *, default: int | None = None) -> int:
    """Prompt until a valid physical page is entered; return its zero-based index."""
    while True:
        number = int(Input.input_number(
            prompt, default=default, min_value=-page_count, max_value=page_count,
            allow_float=False, exit_on_empty=False,
        ))
        try:
            return Input.parse_index_ranges(str(number), item_count=page_count)[0]
        except ValueError as exc:
            print(f"{FLRed}{exc}{CRst}")


def _add_tags(labels: list[str]) -> None:
    """Prompt for an interval, sequence start and prefix; replace its labels in memory."""
    start = _input_page("Start PDF page (required; -1 = last)", len(labels))
    while True:
        end = _input_page("End PDF page (-1 = last)", len(labels), default=-1)
        if end >= start:
            break
        print(f"{FLRed}The end page must not precede the start page.{CRst}")
    first_number = int(Input.input_number("Starting sequence number", default=1, allow_float=False))
    prefix = Input.prompt(f"{FLYellow}Prefix (empty for none): {CRst}")
    labels[start:end + 1] = [f"{prefix}{first_number + offset}" for offset in range(end - start + 1)]
    print(f"{FLGreen}Updated PDF pages {start + 1}-{end + 1}: {labels[start]} ... {labels[end]}{CRst}")


def _edit_tags(document: pymupdf.Document, default_output: str) -> int:
    """Run the menu until exit; save new copies on request and retry save failures."""
    labels = Pdf.read_page_labels(document)
    dirty = False
    while True:
        print(f"\n{FGray}{document.page_count} pages; {'unsaved edits' if dirty else 'no unsaved edits'}.{CRst}")
        action = Menu.select(
            [
                MenuOption(["A", "1"], "Add tags", _Action.ADD),
                MenuOption(["C", "2"], "Clear all tags", _Action.CLEAR_ALL),
                MenuOption(["P", "3"], "Clear selected tags", _Action.CLEAR_PART),
                MenuOption(["S", "4"], "Save", _Action.SAVE),
                MenuOption(["W", "5"], "Save and exit", _Action.SAVE_EXIT),
                MenuOption(["Q", "6"], "Exit without saving", _Action.EXIT),
            ],
            prompt="Page-tag editor", required=True,
        )

        # ── in-memory edits ────────────────────────────────────
        if action is _Action.ADD:
            _add_tags(labels)
            dirty = True
        elif action is _Action.CLEAR_ALL:
            labels[:] = [""] * len(labels)
            dirty = True
            print(f"{FLGreen}All page tags cleared in memory.{CRst}")
        elif action is _Action.CLEAR_PART:
            indexes = Input.input_index_ranges(
                "PDF pages to clear (e.g. 1,2-3,-1; empty to cancel)", item_count=len(labels),
            )
            if indexes:
                for index in indexes:
                    labels[index] = ""
                dirty = True
                print(f"{FLGreen}Cleared tags on {len(indexes)} pages.{CRst}")

        # ── explicit saves and exits ───────────────────────────
        elif action in (_Action.SAVE, _Action.SAVE_EXIT):
            try:
                output = Input.resolve_output_path(default_output, prompt="Save PDF as", path_type="file")
                if dirty:
                    Pdf.write_page_labels(document, labels)
                Pdf.save_new(document, output, compact=False)
            except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase) as exc:
                print(f"{FLRed}Save failed: {exc}. Edits remain available; choose Save to retry.{CRst}")
                continue
            dirty = False
            default_output = output
            print(f"{FLGreen}Saved:{CRst} {FGray}{output}{CRst}")
            if action is _Action.SAVE_EXIT:
                return 0
        elif action is _Action.EXIT:
            print(f"{FGray}Exited without saving pending edits. Earlier saved copies are unchanged.{CRst}")
            return 0


def main() -> int:
    """Load a PDF and run its label editor, returning 0 on exit or 1 on failure.

    Reads CLI arguments, prompts for paths/password and edits, prints status,
    and writes new PDF copies only when a save action is selected.
    """
    Console.print_banner("PDF PAGE TAG EDITOR")
    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
{FLYellow}Usage:{CRst}
  python {script_name} [input.pdf] [-o output.pdf]

{FLYellow}Description:{CRst}
  Load once and repeatedly edit PDF navigation page labels in memory.
  Menu: Add, Clear all, Clear selected, Save, Save and exit, Exit without saving.
  Add: start PDF page required; end defaults to -1 (last); sequence starts at 1;
       prefix defaults to empty (examples: A-, C). Signed sequences are allowed.
  Physical PDF pages start at 1; negative page numbers count from the end.
  Clear selected accepts 1,2-3,-1; empty input cancels. Clearing makes labels blank.
  Content and bookmarks are retained. Each save writes an unencrypted new copy
  with collision avoidance; default filename is <input>_tagged.pdf.
  Automatically removes PDF/A identification while retaining other metadata.
  Save returns to the menu. Exit without saving discards only pending edits.
  Existing copies remain; no temporary PDF or page files are created.

{FLYellow}Options:{CRst}
  input.pdf           PDF to load; prompted when omitted
  -o, --output PATH   suggested output path, prompted when saving
  -h, --help          show this help

{FLYellow}Requirements:{CRst}
  {FGray}pip install PyMuPDF{CRst}
""")
        return 0

    # ── arguments and input document ───────────────────────────
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("input", nargs="?")
    parser.add_argument("-o", "--output")
    args = parser.parse_args()
    filepath = args.input or Input.resolve_input_path(
        os.path.expanduser("~/input.pdf"), prompt="Enter input PDF file path", path_type="file",
    )
    source = Path(filepath)
    default_output = args.output or str(source.with_name(f"{source.stem}_tagged.pdf"))
    try:
        with Pdf.open_document(source) as (document, _):
            if not document.page_count:
                raise ValueError("The PDF contains no pages.")
            print(f"{FLGreen}PDF loaded. Total pages: {document.page_count}{CRst}")
            return _edit_tags(document, default_output)
    except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase) as exc:
        print(f"{FLRed}PDF editing failed: {exc}{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        Console.print_keyboard_interrupt_message_and_exit()
