import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import *

# Remove macOS quarantine attribute from files/folders to
# bypass "unidentified developer cannot be opened" warning.


def _remove_attrs(file_path: str, clear_provenance: bool) -> tuple[bool, bool]:
    """Remove quarantine and optionally provenance from a single file.
    Returns (quarantine_removed, provenance_removed)."""
    q = subprocess.run(["xattr", "-d", "com.apple.quarantine", file_path],
                       capture_output=True, text=True)
    p_removed = False
    if clear_provenance:
        p = subprocess.run(["xattr", "-d", "com.apple.provenance", file_path],
                           capture_output=True, text=True)
        p_removed = p.returncode == 0
    return q.returncode == 0, p_removed


def main() -> int:
    Utils.print_banner("REMOVE QUARANTINE ATTRIBUTE TOOL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
REMOVE QUARANTINE ATTRIBUTE TOOL
================================

Usage:
  python {script_name} <path1> <path2> ...    specify multiple paths, skip interaction
  python {script_name} <path> -r              specify path, recursive for directories
  python {script_name} <path> --provenance    also remove com.apple.provenance
  python {script_name}                        no arguments, interactive mode
  python {script_name} --help                 show this help

{FLYellow}Description:{CRst}
  macOS only. Remove quarantine attribute from files/folders to
  bypass "unidentified developer cannot be opened" warning.
  For directories, supports recursive or non-recursive processing.

{FLYellow}Requirements:{CRst}
  macOS only. Uses xattr (built-in). No external dependencies.
""")
        return 0

    #============ system check ===========
    if sys.platform != "darwin":
        print(f"{FLRed}ERROR: This script only runs on macOS. Current platform: {sys.platform}{CRst}\n")
        return 1

    #============ user interaction ===========
    is_recursive = "-r" in sys.argv or "--recursive" in sys.argv
    filepaths: list[str] = []
    if len(sys.argv) > 1:
        for i in range(1, len(sys.argv)):
            p = sys.argv[i].strip()
            if not p.startswith("-") and p:
                filepaths.append(p)
    else:
        filepaths = Input.resolve_input_paths_multi(
            prompt_text="Enter file or directory paths (one per line)",
            path_type="any",
        )

    # dedup (CLI args may have duplicates) and resolve paths
    valid_paths = list(dict.fromkeys(filepaths))
    valid_paths = [os.path.abspath(os.path.expanduser(p)) for p in valid_paths]

    #============ directory processing mode ===========
    dir_paths = [p for p in valid_paths if os.path.isdir(p)]
    if dir_paths and not is_recursive:
        if len(sys.argv) > 1:
            print(f"{FLYellow}  -> directories detected, using non-recursive mode (use -r for recursive){CRst}")
        else:
            print(f"\n{FLYellow}{len(dir_paths)} directory path(s) detected:{CRst}")
            for d in dir_paths:
                print(f"    {FLCyan}{d}{CRst}")
            is_recursive = Menu.select(
                [
                    MenuOption(["0"], "Non-recursive (directory itself + files directly inside)"),
                    MenuOption(["1"], "Recursive (all files/folders inside)"),
                ],
                prompt="Choose", separator=False,
            )
            if is_recursive is None:
                return 0
            is_recursive = (is_recursive == "1")

    #============ provenance confirmation ===========
    CLEAR_PROVENANCE = False
    if len(sys.argv) > 1:
        CLEAR_PROVENANCE = "--provenance" in sys.argv
    else:
        print(f"\n  {FLMagenta}[?]{CRst} {FLYellow}Also remove {FLCyan}com.apple.provenance{FLYellow} attribute?{CRst}")
        print(f"  {FGray}This tracks which app created the file (macOS 13+). Usually harmless to remove.{CRst}")
        choice = input(f"{FLCyan}Remove provenance? (y/N){CRst}: ").strip().lower()
        CLEAR_PROVENANCE = choice in ("y", "yes")

    #============ main processing ===========
    total_files = 0
    quarantine_cleared = 0
    provenance_cleared = 0
    perm_error_count = 0
    fail_count = 0

    for filepath in valid_paths:
        print(f"\n{FLYellow}  -> removing quarantine from: {filepath}{CRst}")

        if os.path.isdir(filepath):
            if is_recursive:
                dir_total = 0
                dir_q = 0
                dir_p = 0
                for root, dirs, files in os.walk(filepath, onerror=lambda *_: None):
                    # Also count directories
                    for name in dirs:
                        fp = os.path.join(root, name)
                        if os.path.islink(fp):
                            continue
                        dir_total += 1
                        try:
                            q, p = _remove_attrs(fp, CLEAR_PROVENANCE)
                            if q: dir_q += 1
                            if p: dir_p += 1
                        except PermissionError:
                            dir_total += 1
                            perm_error_count += 1
                    for name in files:
                        fp = os.path.join(root, name)
                        if os.path.islink(fp):
                            continue
                        dir_total += 1
                        try:
                            q, p = _remove_attrs(fp, CLEAR_PROVENANCE)
                            if q: dir_q += 1
                            if p: dir_p += 1
                        except PermissionError:
                            dir_total += 1
                            perm_error_count += 1
                # Also clear the top-level directory itself
                dir_total += 1
                q, p = _remove_attrs(filepath, CLEAR_PROVENANCE)
                if q: dir_q += 1
                if p: dir_p += 1
                total_files += dir_total
                quarantine_cleared += dir_q
                provenance_cleared += dir_p
                print(f"  {FLGreen}OK (recursive): {filepath}{CRst}")
                print(f"    {FGray}Scanned: {dir_total}  "
                      f"Quarantine cleared: {FLYellow}{dir_q}{FGray}  "
                      f"Provenance cleared: {FLYellow}{dir_p}{CRst}")

            else:
                # non-recursive: directory itself + direct children
                dir_total = 0
                dir_q = 0
                dir_p = 0
                q, p = _remove_attrs(filepath, CLEAR_PROVENANCE)
                dir_total += 1
                if q: dir_q += 1
                if p: dir_p += 1
                try:
                    for entry in os.listdir(filepath):
                        entry_path = os.path.join(filepath, entry)
                        # Include both files and subdirectories (non-recursive, just top level)
                        if os.path.islink(entry_path):
                            continue
                        dir_total += 1
                        if os.path.isfile(entry_path):
                            q, p = _remove_attrs(entry_path, CLEAR_PROVENANCE)
                            if q: dir_q += 1
                            if p: dir_p += 1
                        elif os.path.isdir(entry_path):
                            q, p = _remove_attrs(entry_path, CLEAR_PROVENANCE)
                            if q: dir_q += 1
                            if p: dir_p += 1
                except PermissionError:
                    perm_error_count += 1
                total_files += dir_total
                quarantine_cleared += dir_q
                provenance_cleared += dir_p
                print(f"  {FLGreen}OK (non-recursive): {filepath}{CRst}")
                print(f"    {FGray}Scanned: {dir_total}  "
                      f"Quarantine cleared: {FLYellow}{dir_q}{FGray}  "
                      f"Provenance cleared: {FLYellow}{dir_p}{CRst}")

        else:
            # single file
            total_files += 1
            q, p = _remove_attrs(filepath, CLEAR_PROVENANCE)
            if q: quarantine_cleared += 1
            if p: provenance_cleared += 1
            if q or p:
                parts = []
                if q: parts.append("quarantine")
                if p: parts.append("provenance")
                print(f"  {FLGreen}OK: {filepath}{CRst}  ({', '.join(parts)})")
            else:
                print(f"  {FGray}No matching attributes: {filepath}{CRst}")

    parts = [f"{FGray}Scanned: {total_files}{CRst}"]
    parts.append(f"Quarantine cleared: {FLYellow}{quarantine_cleared}{CRst}")
    parts.append(f"Provenance cleared: {FLYellow}{provenance_cleared}{CRst}")
    if perm_error_count:
        parts.append(f"{FLYellow}Permission denied: {perm_error_count}{CRst}")
    if fail_count:
        parts.append(f"{FLRed}Failed: {fail_count}{CRst}")
    print(f"\n{FLGreen}Done. {CRst}" + f"  ".join(parts) + "\n")
    return 0


if __name__ == "__main__":
    raise sys.exit(main())
