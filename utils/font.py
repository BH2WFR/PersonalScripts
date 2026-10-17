"""Installed-font discovery and name search; fontTools is imported lazily.

Windows uses font registry entries and system/user directories, macOS uses
standard font directories, and Linux also consults fontconfig when available.
Reading font metadata requires fonttools; catalogs also use tqdm for progress.
Discovery and name search do not require either dependency.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import locale
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import cast

from .ansi import CRst, FGray, FLCyan, FLGreen, FLYellow
from .environment import Environment


@contextmanager
def _quiet_font_timestamps() -> Iterator[None]:
    """Suppress only fontTools' automatically corrected legacy timestamp warning.

    The filter is scoped to metadata reads and removed even on failure. Other
    font warnings and errors continue through the caller's logging configuration.
    """
    logger = logging.getLogger("fontTools.ttLib.tables._h_e_a_d")

    def keep(record: logging.LogRecord) -> bool:
        return not (
            record.levelno == logging.WARNING
            and record.msg == "'%s' timestamp seems very low; regarding as unix timestamp"
            and record.args in (("created",), ("modified",))
        )

    logger.addFilter(keep)
    try:
        yield
    finally:
        logger.removeFilter(keep)


class FontStyle(Enum):
    """Font face style, with values representing (bold, italic) flags."""

    REGULAR = (False, False)
    BOLD = (True, False)
    ITALIC = (False, True)
    BOLD_ITALIC = (True, True)


@dataclass(frozen=True)
class FontFace:
    """Immutable metadata for one face in a font file or collection.

    Attributes:
        path: Absolute font file path returned by Font.read_faces.
        index: Zero-based face index within the file.
        name: Canonical PostScript name, or full/family name when absent.
        family: Preferred family name used to match style variants.
        aliases: Available canonical and localized names from the name table.
        style: Regular, bold, italic, or bold-italic classification.
        full_names: Non-localized full/PostScript names for display classification.
        family_names: Non-localized legacy/typographic/WWS family names.
    """

    path: Path
    index: int
    name: str
    family: str
    aliases: tuple[str, ...]
    style: FontStyle
    full_names: tuple[str, ...] = ()
    family_names: tuple[str, ...] = ()

    def label(self) -> str:
        """Return an ANSI-colored name, distinct aliases, and style.

        Returns:
            Canonical name in light cyan, full names in the terminal's default
            color, family names in gray, localized
            aliases in light green, uncolored slash separators, and gray style.
            Does not print or change the face metadata.
        """
        full_names = {name.casefold() for name in self.full_names}
        family_names = {name.casefold() for name in self.family_names}
        labels: list[str] = []
        for alias in self.aliases:
            folded = alias.casefold()
            if folded == self.name.casefold():
                continue
            color = CRst if folded in full_names else FGray if folded in family_names else FLGreen
            labels.append(f"{color}{alias}{CRst}")
        aliases = " / ".join(labels)
        return f"{FLCyan}{self.name}{CRst}  {aliases}  {FGray}[{self.style.name}]{CRst}"


class Font:
    """Discover installed fonts and search metadata independently of PDF tools.

    File reads load fontTools on demand; importing this module does not require
    it. Methods never install fonts or modify font files.
    """

    FILE_SUFFIXES: frozenset[str] = frozenset({".ttf", ".otf", ".ttc", ".otc"})

    @staticmethod
    def read_faces(path: Path) -> list[FontFace]:
        """Read all faces and localized aliases from a font file.

        Args:
            path: TTF/OTF font or TTC/OTC collection path.

        Returns:
            Metadata in collection order. Chinese aliases are ordered first
            under a Chinese locale; otherwise English aliases are preferred.
            All readable aliases remain searchable regardless of locale.
            Suppresses only fontTools' legacy timestamp correction warning;
            other diagnostics remain visible. No font files are changed.

        Raises:
            ImportError: fonttools is not installed.
            OSError: The file cannot be read.
            ValueError: Font metadata contains invalid values.
            KeyError: A required font table is absent.
            fontTools.ttLib.TTLibError: The file is not a supported font.
        """
        from fontTools.ttLib import TTCollection, TTFont
        from fontTools.ttLib.tables._n_a_m_e import table__n_a_m_e

        # ── collection and language selection ──────────────────
        count = 1
        if path.suffix.casefold() in {".ttc", ".otc"}:
            collection = TTCollection(path, lazy=True)
            count = len(collection.fonts)
            collection.close()
        faces: list[FontFace] = []
        language = (locale.getlocale()[0] or "").casefold()
        preferred = 0x804 if language.startswith("zh") or "chinese" in language else 0x409

        # ── names and style metadata ───────────────────────────
        for index in range(count):
            with _quiet_font_timestamps(), TTFont(path, fontNumber=index, lazy=True) as font:
                names = cast(table__n_a_m_e, font["name"])
                family = names.getBestFamilyName() or path.stem
                canonical = names.getDebugName(6) or names.getBestFullName() or family
                records = sorted(names.names, key=lambda record: (record.langID != preferred, record.nameID != 4))
                aliases: list[str] = []
                full_names: list[str] = []
                family_names: list[str] = []
                for record in records:
                    if record.nameID not in (1, 4, 6, 16, 21):
                        continue
                    try:
                        value = record.toUnicode().strip()
                    except (UnicodeError, LookupError):
                        continue
                    if value and value not in aliases:
                        aliases.append(value)
                    # Preserve name-table roles and language, rather than guessing
                    # from spelling or whether a name contains non-ASCII characters.
                    neutral_or_english = (
                        (record.platformID == 3 and record.langID & 0x3FF == 9)
                        or (record.platformID == 1 and record.langID == 0)
                        or (record.platformID == 0 and record.langID in (0, 0xFFFF))
                    )
                    if value and neutral_or_english:
                        category = full_names if record.nameID in (4, 6) else family_names
                        if value not in category:
                            category.append(value)
                os2 = font.get("OS/2")
                # fontTools creates these scalar fields dynamically when decoding tables.
                flags = int(getattr(os2, "fsSelection")) if os2 is not None else 0
                weight = int(getattr(os2, "usWeightClass")) if os2 is not None else 0
                mac_style = int(getattr(font["head"], "macStyle"))
                bold = weight >= 600 or bool(mac_style & 1)
                italic = bool(flags & 1 or mac_style & 2)
                faces.append(FontFace(path.resolve(), index, canonical, family, tuple(aliases),
                                      FontStyle((bold, italic)), tuple(full_names), tuple(family_names)))
        return faces

    @staticmethod
    def system_font_paths() -> list[Path]:
        """Discover installed TTF/OTF/TTC/OTC files on Windows, macOS or Linux.

        Returns:
            Sorted, deduplicated absolute paths to existing font files. Missing
            directories and inaccessible Windows registry keys are skipped.

        Raises:
            OSError: An existing fontconfig executable cannot be launched, or
                filesystem discovery fails.

        Reads registry/directories and optionally runs Linux fc-list; no files
        are modified. fontconfig is optional, with font-directory fallback.
        """
        roots: list[Path] = []
        paths: set[Path] = set()

        # ── platform-specific locations ────────────────────────
        if sys.platform == "win32":
            import winreg

            roots = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
                     Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Microsoft/Windows/Fonts"]
            key_name = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        for index in range(winreg.QueryInfoKey(key)[1]):
                            _, value, _ = winreg.EnumValue(key, index)
                            if not isinstance(value, str):
                                continue
                            path = Path(os.path.expandvars(value))
                            candidates = [path] if path.is_absolute() else [root / path for root in roots]
                            paths.update(candidate for candidate in candidates if candidate.is_file())
                except OSError:
                    continue
        elif sys.platform == "darwin":
            roots = [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library/Fonts"]
        else:
            roots = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
                     Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "fonts"]
            executable = Environment.which("fc-list")
            if executable:
                result = subprocess.run([executable, "--format=%{file}\n"], capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", check=False)
                if result.returncode == 0:
                    paths.update(Path(line) for line in result.stdout.splitlines() if Path(line).is_file())

        # ── directory scan and canonical paths ─────────────────
        for root in roots:
            if root.is_dir():
                paths.update(path for path in root.rglob("*") if path.suffix.casefold() in Font.FILE_SUFFIXES and path.is_file())
        return sorted({path.resolve() for path in paths if path.suffix.casefold() in Font.FILE_SUFFIXES})

    @staticmethod
    def read_catalog(paths: Sequence[Path], *, show_progress: bool = False) -> list[FontFace]:
        """Read a searchable font catalog, skipping unreadable files.

        Args:
            paths: Font file paths, typically from system_font_paths().
            show_progress: Show a tqdm progress bar on interactive stderr when
                True. Defaults to False; redirected output never gets a bar.

        Returns:
            Faces sorted by family, style, then canonical name. Prints one
            aggregate warning when files cannot be read.

        Raises:
            ImportError: fonttools or tqdm is not installed.
        """
        from fontTools.ttLib import TTLibError
        from tqdm import tqdm

        faces: list[FontFace] = []
        failures = 0
        with tqdm(paths, desc="Reading font metadata", unit="file",
                  disable=not show_progress or not sys.stderr.isatty(), dynamic_ncols=True) as progress:
            for path in progress:
                try:
                    faces.extend(Font.read_faces(path))
                except (OSError, ValueError, KeyError, TTLibError):
                    failures += 1
        if failures:
            print(f"{FLYellow}Warning: could not read {failures} font file(s). You can specify a file directly.{CRst}")
        return sorted(faces, key=lambda face: (face.family.casefold(), face.style.name, face.name.casefold()))

    @staticmethod
    def search_faces(faces: Sequence[FontFace], query: str) -> list[FontFace]:
        """Search canonical, family and localized names without case sensitivity.

        Args:
            faces: Catalog to search; never modified.
            query: Whitespace-separated substrings. Every word must match at
                least one name of a face. Blank input matches every face.

        Returns:
            Matching faces in their original order.
        """
        words = query.casefold().split()
        return [face for face in faces if all(any(word in name.casefold() for name in
                (face.name, face.family, *face.aliases)) for word in words)]

    @staticmethod
    def family_faces(base: FontFace, catalog: Sequence[FontFace]) -> dict[FontStyle, FontFace]:
        """Find matching style variants, preferring files beside the chosen face.

        Args:
            base: Selected face; always retained for its own style.
            catalog: Candidate faces; family matching is case-insensitive.

        Returns:
            One face per available style. Missing styles are omitted. Candidates
            in the base directory win, then canonical name and path break ties.
        """
        candidates = sorted((face for face in catalog if face.family.casefold() == base.family.casefold()),
                            key=lambda face: (face.path.parent != base.path.parent, face.name.casefold(), str(face.path)))
        result: dict[FontStyle, FontFace] = {}
        for face in candidates:
            result.setdefault(face.style, face)
        result[base.style] = base
        return result
