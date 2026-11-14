#!/usr/bin/env python3
"""Port of MyDll3 Dictionary conversion; preserves source-code sorting."""

import sys
from enum import StrEnum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils import *  # noqa: E402
from utils.rime import Rime, RimeEntry, RimeFormat


HELP = """RIME AUX CODE GENERATOR

Extract first-code or first/last-code auxiliary tables from a UTF-8 Rime shape
dictionary. Output uses character=code lines. Single-length codes can be kept,
repeated, or prefixed with one letter; optional filters restrict characters
and exclude code prefixes.

Requirements:
  Python packages: PyYAML, tqdm.

Usage:
  python rime-aux-code-generator.py
  Follow the command-line prompts to select files and conversion rules.
"""


class AuxMode(StrEnum):
    """Positions extracted from the original shape code."""

    FIRST = "first"
    FIRST_LAST = "first-last"


class SingleCodeMode(StrEnum):
    """Treatment of a one-letter code in first/last mode."""

    KEEP = "keep"
    REPEAT = "repeat"
    PREFIX = "prefix"


def generate_aux_rows(
    entries: list[RimeEntry],
    *,
    mode: AuxMode = AuxMode.FIRST,
    single: SingleCodeMode = SingleCodeMode.KEEP,
    prefix: str = "x",
    single_char_only: bool = True,
    excluded_prefixes: tuple[str, ...] = (),
    allowed_texts: set[str] | None = None,
) -> list[str]:
    """Convert and deduplicate pairs, retaining distinct codes for each character.

    Rows are sorted by the original code, as in the C++ implementation.
    None disables the character filter; an empty set deliberately matches none.
    Unicode supplementary-plane characters count as single characters.
    """
    mode, single = AuxMode(mode), SingleCodeMode(single)
    if single == SingleCodeMode.PREFIX and (len(prefix) != 1 or prefix not in string.ascii_letters):
        raise ValueError("The prefix must be one ASCII letter.")
    rows: dict[str, None] = {}
    for entry in sorted(entries, key=lambda entry: entry.code):
        if (not entry.text or not entry.code
                or (single_char_only and len(entry.text) != 1)
                or entry.code.startswith(excluded_prefixes)
                or (allowed_texts is not None and entry.text not in allowed_texts)):
            continue
        if any(char.isspace() for char in entry.code):
            continue  # Phrase/syllable codes cannot form a shape-code auxiliary.
        code = entry.code[0]
        if mode == AuxMode.FIRST_LAST:
            if len(entry.code) > 1:
                code += entry.code[-1]
            elif single == SingleCodeMode.REPEAT:
                code *= 2
            elif single == SingleCodeMode.PREFIX:
                code = prefix + code
        rows.setdefault(f"{entry.text}={code}", None)
    return list(rows)


def main() -> int:
    parser = Console.argument_parser(HELP)
    parser.parse_args()
    Console.print_banner("RIME AUX CODE GENERATOR")
    try:
        import yaml  # noqa: F401
        import tqdm  # noqa: F401
    except ImportError:
        print(f"{FLRed}Install dependencies: python -m pip install PyYAML tqdm{CRst}")
        return 1

    try:
        source = Path(Input.resolve_input_path("", "Shape dictionary (.dict.yaml or TSV)"))
        mode = AuxMode(Menu.select([
            MenuOption(["1"], "First code", AuxMode.FIRST),
            MenuOption(["2"], "First and last codes", AuxMode.FIRST_LAST),
        ], default_key="1", required=True))
        single = SingleCodeMode.KEEP
        prefix = "x"
        if mode == AuxMode.FIRST_LAST:
            single = SingleCodeMode(Menu.select([
                MenuOption(["1"], "Keep a single code (a -> a)", SingleCodeMode.KEEP),
                MenuOption(["2"], "Repeat a single code (a -> aa)", SingleCodeMode.REPEAT),
                MenuOption(["3"], "Prefix a single code (a -> xa)", SingleCodeMode.PREFIX),
            ], prompt="Single-length codes", default_key="1", required=True))
            if single == SingleCodeMode.PREFIX:
                while True:
                    prefix = Input.prompt(f"{FLYellow}Prefix letter [x]: {CRst}", default="x")
                    if len(prefix) == 1 and prefix in string.ascii_letters:
                        break
                    print(f"{FLRed}Enter one ASCII letter.{CRst}")
        single_char_only = Menu.select([
            MenuOption(["1"], "Single characters only", True),
            MenuOption(["2"], "Include phrases", False),
        ], prompt="Text selection", default_key="1", required=True)
        excluded = Input.prompt(
            f"{FLYellow}Excluded code prefixes, comma-separated (e.g. x,z,yyy; Enter = none): {CRst}",
            separator=",", deduplicate=True,
        )
        filter_path: Path | None = None
        allowed: set[str] | None = None
        if Menu.select([
            MenuOption(["Y"], "Use a reference dictionary as a character filter", True),
            MenuOption(["N"], "No reference filter", False),
        ], default_key="N", required=True):
            filter_path = Path(Input.resolve_input_path("", "Reference dictionary"))
            reference = Rime.read(filter_path, format=RimeFormat.DICT, read_weights=False, progress=True)
            allowed = {entry.text for entry in reference.entries if len(entry.text) == 1}
            print(f"Reference: {len(allowed)} characters; {reference.invalid_rows} malformed rows skipped.")
        result = Rime.read(source, format=RimeFormat.DICT, read_weights=False, progress=True)
        rows = generate_aux_rows(
            result.entries, mode=mode, single=single, prefix=prefix,
            single_char_only=bool(single_char_only), excluded_prefixes=tuple(excluded), allowed_texts=allowed,
        )
        print(f"Read {len(result.entries)} entries; skipped {result.invalid_rows} malformed rows.")
        if not rows:
            raise ValueError("No auxiliary entries remain after filtering; no output written.")
        stem = source.name.removesuffix(".dict.yaml") if source.name.endswith(".dict.yaml") else source.stem
        output = Path(Input.resolve_output_path(str(source.with_name(f"{stem}_aux_{mode.value}.txt"))))
        sources = [source] + ([filter_path] if filter_path is not None else [])
        Rime.write_rows(output, rows, sources=sources, overwrite=True)
        print(f"{FLGreen}Saved {len(rows)} auxiliary entries:{CRst} {FGray}{output}{CRst}")
        return 0
    except (OSError, UnicodeError, ValueError, EOFError) as exc:
        print(f"{FLRed}Error: {exc}{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
