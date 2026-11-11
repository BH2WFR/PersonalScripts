#!/usr/bin/env python3
"""Standalone port of the text_actions Unicode inspector's Tk interface.

Analysis belongs to utils.unicode_text; keep original text separate from display
labels. All Tk calls stay on the GUI thread. Do not import the source project's
macOS selection hooks, named pasteboards or process-launch helpers.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils import *  # noqa: E402

HELP = f"""{FLYellow}UNICODE INSPECTOR{CRst}

Inspect text in a desktop window: code points, UTF-8 bytes, Unicode names and
categories, including invisible characters, with text statistics and copyable reports.

{FLYellow}Requirements:{CRst}
  Python with Tkinter; Windows, macOS or Linux with X11/XWayland.

{FLYellow}Usage:{CRst}
  python unicode-inspector.py [TEXT ... | --clip]
  Omit TEXT to enter text in the window; --clip reads the clipboard.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk


class UnicodeInspector:
    """Editable text, statistics and a character table using only Tk clipboard I/O."""

    ROW_BATCH = 400

    def __init__(self, root: tk.Tk, text: str = "") -> None:
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText

        self.root = root
        self._render_job: str | None = None
        self.report = UnicodeText.inspect("")
        root.title("Unicode Inspector")
        root.geometry("1100x720")
        root.minsize(800, 500)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        body = ttk.Frame(root, padding=12)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        header = ttk.Frame(body)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Text to inspect").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="Paste", command=self.paste).grid(row=0, column=1, padx=4)
        ttk.Button(header, text="Clear", command=lambda: self.set_text("")).grid(row=0, column=2, padx=4)
        ttk.Button(header, text="Analyze", command=self.analyze).grid(row=0, column=3, padx=(4, 0))
        self.original = ScrolledText(body, height=6, wrap="word", font="TkDefaultFont", undo=True)
        self.original.grid(row=1, column=0, sticky="ew", pady=(6, 12))
        self._text_input = TkTextInput(self.original)

        summary = ttk.Frame(body)
        summary.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.statistics: dict[str, tk.StringVar] = {}
        for column, (label, _) in enumerate(self.report.statistics.items()):
            block = ttk.Frame(summary)
            block.grid(row=0, column=column, padx=(0, 14), sticky="w")
            ttk.Label(block, text=label).pack(side="left", padx=(0, 5))
            value = tk.StringVar(root, "0")
            self.statistics[label] = value
            ttk.Entry(block, width=9, state="readonly", textvariable=value, justify="right").pack(side="left")

        table_frame = ttk.Frame(body)
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(table_frame, columns=UnicodeText.COLUMNS, show="headings", selectmode="extended")
        widths = (60, 150, 95, 80, 120, 180, 330)
        for column, width in zip(UnicodeText.COLUMNS, widths):
            self.table.heading(column, text=column)
            self.table.column(column, width=width, minwidth=50, stretch=column in ("Character", "Category", "Name"))
        for tag, color in (("control", "#b71c1c"), ("special", "#267333"),
                           ("non_ascii", "#1565c0"), ("non_bmp", "#875020")):
            self.table.tag_configure(tag, foreground=color)
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

        footer = ttk.Frame(body)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        self.status = tk.StringVar(root, "")
        ttk.Label(footer, textvariable=self.status, wraplength=360).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Copy Original", command=self.copy_original).grid(row=0, column=1, padx=4)
        ttk.Button(footer, text="Copy Selected Rows", command=self.copy_rows).grid(row=0, column=2, padx=4)
        ttk.Button(footer, text="Copy Full Report", command=self.copy_report).grid(row=0, column=3, padx=(4, 0))

        self.original.bind("<<Modified>>", self._on_modified)
        modifier = "Command" if root.tk.call("tk", "windowingsystem") == "aqua" else "Control"
        self.table.bind(f"<{modifier}-c>", self.copy_rows)
        root.bind(f"<{modifier}-Return>", self._analyze_event)
        root.bind(f"<{modifier}-w>", self.close)
        root.bind("<Escape>", self.close)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.set_text(text)
        self.original.focus_set()

    def _on_modified(self, event: object = None) -> None:
        if self.original.edit_modified():
            self.original.edit_modified(False)
            self.status.set("Text changed. Analyze to update the table.")

    def _analyze_event(self, event: object = None) -> str:
        self.analyze()
        return "break"

    def set_text(self, text: str) -> None:
        """Replace the editable text verbatim, including blank-only input, and analyze."""
        self.original.delete("1.0", "end")
        self.original.insert("1.0", text)
        self.original.edit_modified(False)
        self.analyze()

    def analyze(self) -> None:
        """Refresh the report and render table rows in cancellable GUI-thread batches."""
        if self._render_job is not None:
            self.root.after_cancel(self._render_job)
            self._render_job = None
        self.report = UnicodeText.inspect(self.original.get("1.0", "end-1c"))
        for label, value in self.report.statistics.items():
            self.statistics[label].set(str(value) if value is not None else "Invalid")
        children = self.table.get_children()
        if children:
            self.table.delete(*children)
        self.original.edit_modified(False)
        self._render_rows(0)

    def _render_rows(self, start: int) -> None:
        self._render_job = None
        end = min(start + self.ROW_BATCH, len(self.report.characters))
        for row in self.report.characters[start:end]:
            self.table.insert("", "end", iid=str(row.index), values=row.columns(), tags=(row.style,) if row.style else ())
        if end < len(self.report.characters):
            self.status.set(f"Loading {end:,} / {len(self.report.characters):,} code points…")
            self._render_job = self.root.after(1, self._render_rows, end)
        else:
            if self.original.get("1.0", "end-1c") != self.report.text:
                self.status.set("Text changed. Analyze to update the table.")
            else:
                self.status.set(f"{len(self.report.characters):,} code points. Indexes start at 0.")

    def paste(self) -> None:
        """Read text through Tk, leaving the window usable if the clipboard has no text."""
        from tkinter import TclError

        try:
            text = self.root.clipboard_get()
        except TclError:
            self.status.set("Clipboard has no readable text. Enter or paste text manually.")
            return
        self.set_text(text)

    def _copy(self, text: str) -> None:
        from tkinter import TclError

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update_idletasks()
        except TclError:
            self.status.set("Cannot copy this text to the clipboard.")
            return
        self.status.set("Copied to clipboard.")

    def copy_original(self) -> None:
        """Copy the current editor contents rather than display labels or stale input."""
        self._copy(self.original.get("1.0", "end-1c"))

    def copy_rows(self, event: object = None) -> str:
        """Copy selected rows in source order as tab-separated text."""
        indexes = sorted(int(item) for item in self.table.selection())
        if indexes:
            self._copy("\n".join("\t".join(self.report.characters[index].columns()) for index in indexes))
        else:
            self.status.set("Select one or more character rows to copy.")
        return "break"

    def copy_report(self) -> None:
        """Refresh first so the copied full report always matches the current text."""
        self.analyze()
        self._copy(UnicodeText.format_report(self.report))

    def close(self, event: object = None) -> str:
        """Cancel pending row insertion before destroying the window."""
        if self._render_job is not None:
            self.root.after_cancel(self._render_job)
            self._render_job = None
        self.root.destroy()
        return "break"


def main() -> int:
    """Open the standalone inspector; help and argument errors need no GUI runtime."""
    import argparse

    parser = Console.argument_parser(HELP)
    parser.add_argument("text", nargs="*", metavar="TEXT")
    parser.add_argument("--clip", "--from-clipboard", action="store_true", dest="clipboard")
    parser.add_argument("--pause", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.clipboard and args.text:
        parser.error("TEXT and --clip cannot be combined")
    try:
        import tkinter as tk
    except ImportError:
        print(f"{FLRed}Tkinter is unavailable. Install Tk support for this Python environment.{CRst}", file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"{FLRed}Cannot open the desktop window: {exc}{CRst}", file=sys.stderr)
        return 1
    try:
        inspector = UnicodeInspector(root, " ".join(args.text))
        if args.clipboard:
            inspector.paste()
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
