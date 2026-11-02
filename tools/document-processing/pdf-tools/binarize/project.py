"""Validated profiles and portable JSON projects, independent of Qt and PDF I/O.

The engine's immutable settings remain canonical. Profiles store complete
settings; page assignments reference stable IDs rather than other pages.
"""

from dataclasses import dataclass, field, fields, replace
from enum import Enum
import json
import math
import os
from pathlib import Path
import tempfile
from typing import cast
from uuid import uuid4

from utils import *
from ..common.protocol import Json
from . import regions
from .settings import DEFAULT_DPI, DEFAULT_THRESHOLD, DEFAULT_WORKERS, MAX_WORKERS, _Processing, _validate_settings

type Scalar = bool | int | float | str | None
PROJECT_VERSION = 1
MAX_PROJECT_BYTES = 16 * 1024 * 1024
DEFAULT_ID = "default"
SKIP_ID = "no-processing"
BUILTIN_IDS = frozenset((DEFAULT_ID, SKIP_ID))
REGION_PATH_FIELDS = frozenset(("input", "export", "preview_dir"))


def mapping(value: Json, label: str) -> dict[str, Json]:
    """Require a JSON object; raise ValueError with its field name otherwise."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def integer(value: Json, label: str, minimum: int = 0) -> int:
    """Require an integer, rejecting booleans and values below minimum."""
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}.")
    return value


def text_value(value: Json, label: str) -> str:
    """Require a nonempty string and return it stripped."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string.")
    return value.strip()


def flag(value: Json, label: str) -> bool:
    """Require a JSON boolean rather than coercing strings or numbers."""
    if type(value) is not bool:
        raise ValueError(f"{label} must be true or false.")
    return value


@dataclass(frozen=True)
class Config:
    """One complete profile's immutable processing configuration."""

    dpi: int = DEFAULT_DPI
    threshold: int = DEFAULT_THRESHOLD
    processing: _Processing = field(default_factory=_Processing)

    def values(self) -> dict[str, Scalar]:
        """Return flat editable values, excluding task-level sidecar paths."""
        result: dict[str, Scalar] = {"dpi": self.dpi, "threshold": self.threshold}
        for item in fields(self.processing):
            if item.name != "regions":
                value = getattr(self.processing, item.name)
                result[item.name] = value.value if isinstance(value, Enum) else value
        for item in fields(self.processing.regions):
            if item.name not in REGION_PATH_FIELDS:
                value = getattr(self.processing.regions, item.name)
                result[f"regions.{item.name}"] = value.value if isinstance(value, Enum) else value
        return result

    @classmethod
    def from_values(cls, values: dict[str, Json]) -> "Config":
        """Validate flat fields and construct engine settings; reject unknown keys.

        Args:
            values: Complete or partial scalar settings; missing fields use defaults.

        Returns:
            An immutable, validated configuration.

        Raises:
            ValueError: Unknown fields, wrong types, nonfinite or invalid settings.
        """
        defaults = cls().values()
        unknown = values.keys() - defaults.keys()
        if unknown:
            raise ValueError(f"Unknown profile settings: {', '.join(sorted(unknown))}")
        merged = {**defaults, **values}
        for key, value in merged.items():
            original = defaults[key]
            if key == "regions.threshold":
                valid = value is None or type(value) in (float, int)
            elif type(original) is float:
                valid = type(value) in (float, int)
            else:
                valid = type(value) is type(original)
            if not valid or isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Invalid value for {key}: {value!r}")
        processing = _Processing()
        region_settings = processing.regions
        primary: dict[str, object] = {}
        regional: dict[str, object] = {}
        for key, value in merged.items():
            if key in ("dpi", "threshold"):
                continue
            target, name = (regional, key.removeprefix("regions.")) if key.startswith("regions.") else (primary, key)
            original = getattr(region_settings if target is regional else processing, name)
            target[name] = type(original)(value) if isinstance(original, Enum) else value
        processing = replace(processing, **primary, regions=replace(region_settings, **regional))
        if processing.regions.mode in (regions._Mode.TEXT, regions._Mode.TEXT_INVERT):
            raise ValueError("Text overlay modes belong to region JSON, not page profiles.")
        dpi, threshold = cast(int, merged["dpi"]), cast(int, merged["threshold"])
        _validate_settings(dpi, threshold, 1, processing)
        return cls(dpi, threshold, processing)


@dataclass
class Profile:
    """Stable identity, editable label, and a complete processing snapshot."""

    id: str
    name: str
    config: Config = field(default_factory=Config)


@dataclass
class OutputOptions:
    """Task settings shared by all profiles; no output path is forced on reload."""

    workers: int = DEFAULT_WORKERS
    export_regions: bool = False
    annotate_regions: bool = False
    region_input: Path | None = None
    open_preview: bool = True


@dataclass
class Project:
    """Document session with one profile assignment for every physical page.

    Paths and page counts describe an expected input. Opening/authentication and
    comparison with the actual PDF happen in the worker before adopting a project.
    """

    source: Path
    page_count: int
    profiles: dict[str, Profile]
    assignments: list[str]
    output: OutputOptions = field(default_factory=OutputOptions)
    current_page: int = 0
    show_original: bool = False
    auto_fit: bool = True
    show_regions: bool = False

    @classmethod
    def create(cls, source: Path, page_count: int) -> "Project":
        """Create a new session with the default profile on every page."""
        if page_count < 1:
            raise ValueError("The PDF has no pages.")
        profiles = {key: Profile(key, key) for key in (DEFAULT_ID, SKIP_ID)}
        return cls(source.resolve(), page_count, profiles, [DEFAULT_ID] * page_count)

    def add_profile(self, name: str, source_id: str) -> str:
        """Add a named copy and return its ID; existing assignments do not change."""
        name = self._name(name)
        identity = uuid4().hex
        source_id = DEFAULT_ID if source_id == SKIP_ID else source_id
        self.profiles[identity] = Profile(identity, name, self.profiles[source_id].config)
        return identity

    def _name(self, name: str, current: str | None = None) -> str:
        name = text_value(name, "Profile name")
        if any(profile.id != current and profile.name.casefold() == name.casefold()
               for profile in self.profiles.values()):
            raise ValueError("A profile with that name already exists.")
        return name

    def rename(self, identity: str, name: str) -> None:
        """Rename a custom profile, preserving assignments; built-ins are fixed."""
        if identity in BUILTIN_IDS:
            raise ValueError("Built-in profiles cannot be renamed.")
        self.profiles[identity].name = self._name(name, identity)

    def remove(self, identity: str, replacement: str) -> None:
        """Replace all references before deleting a custom profile."""
        if identity in BUILTIN_IDS or identity == replacement or replacement not in self.profiles:
            raise ValueError("Select a custom profile and a valid replacement.")
        self.assignments = [replacement if item == identity else item for item in self.assignments]
        del self.profiles[identity]

    def assign(self, identity: str, expression: str) -> tuple[int, ...]:
        """Atomically assign a profile to a validated physical-page expression."""
        if identity not in self.profiles:
            raise ValueError("Unknown profile.")
        pages = Input.parse_index_ranges(expression, item_count=self.page_count)
        if not pages:
            raise ValueError("Enter page numbers, for example 1,2,5-10.")
        for index in pages:
            self.assignments[index] = identity
        return pages

    def to_data(self, base: Path | None = None) -> dict[str, Json]:
        """Return a JSON-safe snapshot; use paths relative to base when possible."""
        def path_text(path: Path) -> str:
            try:
                return os.path.relpath(path, base) if base is not None else str(path)
            except ValueError:  # Different Windows drives.
                return str(path)

        return {
            "format": "pdf-binarize-project", "version": PROJECT_VERSION,
            "pdf": path_text(self.source), "page_count": self.page_count,
            "profiles": [{"id": profile.id, "name": profile.name,
                          "settings": cast(dict[str, Json], profile.config.values())}
                         for profile in self.profiles.values()],
            "page_profiles": cast(list[Json], list(self.assignments)),
            "output": {"workers": self.output.workers, "export_regions": self.output.export_regions,
                       "annotate_regions": self.output.annotate_regions, "open_preview": self.output.open_preview,
                       "region_input": path_text(self.output.region_input) if self.output.region_input else None},
            "view": {"page": self.current_page + 1, "show_original": self.show_original,
                     "auto_fit": self.auto_fit, "show_regions": self.show_regions},
        }

    @classmethod
    def from_data(cls, data: dict[str, Json], base: Path) -> "Project":
        """Validate a project without opening its PDF; resolve paths against base.

        Raises ValueError for unsupported versions, invalid profiles, assignments,
        view state or output settings. Does not modify files or an active session.
        """
        if data.get("format") != "pdf-binarize-project" or type(data.get("version")) is not int or data["version"] != PROJECT_VERSION:
            raise ValueError("Unsupported PDF binarizer project format/version.")
        count = integer(data.get("page_count"), "Page count", 1)
        source = (base / text_value(data.get("pdf"), "PDF path")).resolve()
        rows = data.get("profiles")
        if not isinstance(rows, list):
            raise ValueError("Profiles must be a list.")
        profiles: dict[str, Profile] = {}
        for row in rows:
            item = mapping(row, "Profile")
            identity = text_value(item.get("id"), "Profile ID")
            name = text_value(item.get("name"), "Profile name")
            if identity in profiles or any(profile.name.casefold() == name.casefold() for profile in profiles.values()):
                raise ValueError("Duplicate profile ID or name.")
            if identity in BUILTIN_IDS and identity != name:
                raise ValueError("Built-in profile names must remain unchanged.")
            profiles[identity] = Profile(identity, name, Config.from_values(mapping(item.get("settings"), "Settings")))
        if not BUILTIN_IDS <= profiles.keys():
            raise ValueError("The default and no-processing profiles are required.")
        assignments = data.get("page_profiles")
        if (not isinstance(assignments, list) or len(assignments) != count or
                any(not isinstance(item, str) or item not in profiles for item in assignments)):
            raise ValueError("Page/profile assignments do not match the page count or profiles.")
        options = mapping(data.get("output", {}), "Output")
        workers = integer(options.get("workers", DEFAULT_WORKERS), "Workers", 1)
        if workers > MAX_WORKERS:
            raise ValueError(f"Workers cannot exceed {MAX_WORKERS}.")
        region_path = options.get("region_input")
        output = OutputOptions(workers, flag(options.get("export_regions", False), "Export regions"),
                               flag(options.get("annotate_regions", False), "Annotations"),
                               (base / text_value(region_path, "Region JSON")).resolve() if region_path is not None else None,
                               flag(options.get("open_preview", True), "Open saved preview"))
        view = mapping(data.get("view", {}), "View")
        page = integer(view.get("page", 1), "Current page", 1)
        if page > count:
            raise ValueError("The current page is outside the PDF.")
        return cls(source, count, profiles, cast(list[str], list(assignments)), output, page - 1,
                   flag(view.get("show_original", False), "Show original"),
                   flag(view.get("auto_fit", True), "Auto fit page"),
                   flag(view.get("show_regions", False), "Show regions"))

    @classmethod
    def load(cls, path: Path) -> "Project":
        """Read a bounded UTF-8 JSON project; missing PDFs are resolved by the GUI."""
        if path.stat().st_size > MAX_PROJECT_BYTES:
            raise ValueError("Project JSON is too large.")
        return cls.from_data(mapping(json.loads(path.read_text(encoding="utf-8")), "Project"), path.parent)

    def save(self, path: Path) -> None:
        """Atomically save an explicitly selected JSON project without embedding passwords.

        Args:
            path: Destination selected by the user. An existing project is replaced.

        Raises:
            OSError: Writing/replacing the project fails. The previous file survives
                failures before the atomic replace.
        """
        if path.resolve() == self.source.resolve() or path.suffix.lower() != ".json":
            raise ValueError("Save the project as a JSON file, separate from the PDF.")
        data = self.to_data(path.parent)
        self.from_data(data, path.parent)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                             dir=path.parent, prefix=".pdf-project-", suffix=".json", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
