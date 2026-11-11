# Font discovery and matching

[Utility index](../README.md)

Implementation: [font.py](../font.py).

## API reference

| Need | Use |
| --- | --- |
| Discover installed font files | `Font.system_font_paths() -> list[Path]`; sorted unique absolute TTF/OTF/TTC/OTC paths from Windows registry/directories, macOS directories, or Linux fontconfig/directories; `Font.FILE_SUFFIXES` contains supported suffixes |
| Read font names and styles | `Font.read_faces(path: Path) -> list[FontFace]`; collection order, canonical name, family, all readable aliases, full_names/family_names classified by name-table role and language, and `FontStyle` regular/bold/italic/bold-italic; imports fonttools lazily |
| Build a font catalog | `Font.read_catalog(paths: Sequence[Path], show_progress=False) -> list[FontFace]`; sorts by family/style/name, skips unreadable files with an aggregate warning; True shows a tqdm bar on interactive stderr; fonttools and tqdm are imported lazily |
| Search font names and aliases | `Font.search_faces(faces, query) -> list[FontFace]`; case-insensitive substrings across canonical/family/localized names, all whitespace-separated terms must match, blank query returns all faces in input order |
| Match a font family's styles | `Font.family_faces(base, catalog) -> dict[FontStyle, FontFace]`; selected face wins its own style, other styles prefer nearby files, unavailable styles are omitted |
| Format a font face label | `FontFace.label() -> str`; canonical name uses FLCyan, full names use the terminal default color, family names use FGray, localized aliases use FLGreen, slash separators are uncolored, and style uses FGray; returns text without printing |

## Internal metadata handling

`_quiet_font_timestamps()` scopes a logging filter to font metadata reads. It
suppresses only fontTools' automatically corrected legacy created/modified
timestamp warning, leaves other diagnostics visible and removes the filter
afterward. Font files are never rewritten to silence warnings.
