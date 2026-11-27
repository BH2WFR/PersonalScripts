#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from tqdm import tqdm

from utils import CmdCheck, Console, Environment


HELP = """COMPILE QT DESIGNER FORMS

Compile every .ui form under tools/ into ui_<name>.py beside the form.

Requirements:
  PySide6 (pyside6-uic on PATH) and tqdm.

Usage:
  conda run -n base python _pyside6_uic.py
"""


def _compile_form(compiler: str, form: Path) -> bool:
    """Compile one form and return whether its Python module changed."""
    output = form.with_name(f"ui_{form.stem}.py")
    result = subprocess.run(
        [compiler, form.name], cwd=form.parent, stdout=subprocess.PIPE, check=True,
    )
    source = result.stdout.replace(b"\r\n", b"\n")
    if not source.strip():
        raise ValueError("pyside6-uic produced no Python code")
    compile(source, str(output), "exec")

    if output.exists():
        existing = output.read_bytes()
        if existing.replace(b"\r\n", b"\n") == source:
            return False
        if b"\r\n" in existing:
            source = source.replace(b"\n", b"\r\n")

    with NamedTemporaryFile(dir=output.parent, delete_on_close=False) as temp:
        temp.write(source)
        temp.close()
        Path(temp.name).replace(output)
    return True


def main() -> int:
    """Regenerate tool forms and return a nonzero status if any failed."""
    Console.initialize_ansi_output()
    Console.argument_parser(HELP).parse_args()
    compiler = CmdCheck("pyside6-uic", hints={"any": "Install PySide6 in the active Python environment."})
    if not Environment.check_commands(compiler) or compiler.path is None:
        return 1

    root = Path(__file__).resolve().parent
    forms = sorted((root / "tools").rglob("*.ui"))
    updated = failed = 0
    for form in tqdm(forms, desc="Compiling", unit="form", disable=not sys.stderr.isatty()):
        try:
            if _compile_form(compiler.path, form):
                updated += 1
                tqdm.write(f"Compiled {form.relative_to(root)}")
        except (OSError, subprocess.CalledProcessError, SyntaxError, ValueError) as exc:
            failed += 1
            tqdm.write(f"Failed to compile {form.relative_to(root)}: {exc}", file=sys.stderr)
    print(f"{len(forms)} forms: {updated} updated, {len(forms) - updated - failed} unchanged, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
