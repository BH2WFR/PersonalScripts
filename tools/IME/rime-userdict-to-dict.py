#!/usr/bin/env python3
"""Port of MyDll3 UserDictionary; first occurrence wins for duplicate pairs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils import *  # noqa: E402
from utils.rime import Rime, RimeEntry, RimeFormat


HELP = """RIME USERDICT TO DICT

Convert a UTF-8 Rime userdb.txt sync snapshot or text/code/weight text export
to a standard .dict.yaml dictionary. Deleted entries are excluded; weights
can be retained, scaled, or omitted. Binary .userdb databases must first be
exported or synchronized to text in Rime.

Requirements:
  Python packages: PyYAML, tqdm.

Usage:
  python rime-userdict-to-dict.py
  Follow the command-line prompts to select input, weights and output.
"""


def convert_entries(
    entries: list[RimeEntry], *, use_weights: bool = True, factor: float = 1.0,
) -> list[RimeEntry]:
    """Drop deleted entries, scale weights by truncation, and sort by code/text.

    Duplicate text/code pairs retain their first non-deleted occurrence, as in
    the original converter. Deletions are excluded even when weights are off.
    Raises ValueError for negative/non-finite factors or overflowing products.
    """
    if not math.isfinite(factor) or factor < 0:
        raise ValueError("Weight factor must be finite and non-negative.")
    unique: dict[tuple[str, str], RimeEntry] = {}
    for entry in entries:
        if entry.weight < 0 or not entry.text or not entry.code:
            continue
        key = (entry.code, entry.text)
        if key in unique:
            continue
        weight = 0
        if use_weights:
            if factor == 1:
                weight = entry.weight
            else:
                try:
                    scaled = entry.weight * factor
                    if not math.isfinite(scaled):
                        raise ValueError("Scaled weight is too large.")
                    weight = int(scaled)
                except OverflowError as exc:
                    raise ValueError("Scaled weight is too large.") from exc
        unique[key] = RimeEntry(entry.text, entry.code, weight)
    return [unique[key] for key in sorted(unique)]


def dictionary_rows(entries: list[RimeEntry], name: str) -> list[str]:
    """Build a standalone dictionary without importing preset vocabulary."""
    if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name) is None: # c 为负数时不包含
        raise ValueError("Dictionary name must use ASCII letters, digits, underscores, dots or hyphens.")
    rows = [
        "# Rime dictionary", "# encoding: utf-8", "", "---",
        f"name: {json.dumps(name)}", 'version: "1.0"', "sort: by_weight",
        "use_preset_vocabulary: false", "columns: [text, code, weight]", "...", "",
    ]
    rows.extend(
        f"{entry.text}\t{entry.code}" + (f"\t{entry.weight}" if entry.weight > 0 else "")
        for entry in entries
    )
    return rows


def main() -> int:
    parser = Console.argument_parser(HELP)
    parser.parse_args()
    Console.print_banner("RIME USERDICT TO DICT")
    try:
        import yaml  # noqa: F401
        import tqdm  # noqa: F401
    except ImportError:
        print(f"{FLRed}Install dependencies: python -m pip install PyYAML tqdm{CRst}")
        return 1

    try:
        source = Path(Input.resolve_input_path("", "Rime user dictionary text file"))
        format = RimeFormat(Menu.select([
            MenuOption(["1"], "Auto-detect text format", RimeFormat.AUTO),
            MenuOption(["2"], "Sync snapshot: code / text / c=...", RimeFormat.USERDB),
            MenuOption(["3"], "Text export or dictionary: text / code / weight", RimeFormat.DICT),
        ], default_key="1", required=True))
        use_weights = Menu.select([
            MenuOption(["1"], "Keep weights (optional scaling)", True),
            MenuOption(["2"], "Omit weights", False),
        ], default_key="1", required=True)
        factor = 1.0
        if use_weights:
            while True:
                factor = float(Input.input_number("Weight multiplier", default=1.0, min_value=0))
                if math.isfinite(factor):
                    break
                print(f"{FLRed}Enter a finite multiplier.{CRst}")
        result = Rime.read(source, format=format, progress=True)
        entries = convert_entries(result.entries, use_weights=bool(use_weights), factor=factor)
        deleted = sum(entry.weight < 0 for entry in result.entries)
        print(f"Read {len(result.entries)} entries; excluded {deleted} deleted entries; "
              f"skipped {result.invalid_rows} malformed rows.")
        if result.invalid_lines:
            print(f"{FLYellow}Malformed input line examples: {result.invalid_lines}{CRst}")
        if not entries:
            raise ValueError("No valid entries remain; no output written.")
        stem = source.name
        for suffix in (".userdb.txt", ".dict.yaml", ".txt", ".tsv"):
            if stem.endswith(suffix):
                stem = stem.removesuffix(suffix)
                break
        output = Path(Input.resolve_output_path(str(source.with_name(f"{stem}_custom.dict.yaml"))))
        default_name = re.sub(r"[^A-Za-z0-9_.-]", "_", output.name.removesuffix(".dict.yaml"))
        if not default_name or default_name[0] in ".-":
            default_name = "custom" + default_name
        while True:
            name = Input.prompt(f"{FLYellow}Dictionary name [{default_name}]: {CRst}", default=default_name)
            try:
                rows = dictionary_rows(entries, name)
                break
            except ValueError as exc:
                print(f"{FLRed}{exc}{CRst}")
        Rime.write_rows(output, rows, sources=[source], overwrite=True)
        print(f"{FLGreen}Saved {len(entries)} dictionary entries:{CRst} {FGray}{output}{CRst}")
        return 0
    except (OSError, UnicodeError, ValueError, EOFError) as exc:
        print(f"{FLRed}Error: {exc}{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
