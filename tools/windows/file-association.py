#!/usr/bin/env python3
"""Inspect and manage Windows file-association entries for one extension.

The interactive menu inspects registry locations that can contribute handlers
for a file extension, removes a selected source entry, or registers a new EXE
through a supported Open With entry point. It shows ProgIDs, application
identifiers, resolved commands, and whether referenced executables exist.

Requirements:
    - Windows 10 or later
    - Python standard library only (winreg, ctypes)

Usage:
    python file-association.py
    python file-association.py --view .txt
"""

from __future__ import annotations

import argparse
import base64
import binascii
import ctypes
import json
import os
import re
import sys
import winreg
from dataclasses import dataclass
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402


CLASSES_PATH = r"Software\Classes"
EXPLORER_FILE_EXTS_PATH = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
REGISTERED_APPLICATIONS_PATH = r"Software\RegisteredApplications"
SYSTEM_FILE_ASSOCIATIONS_PATH = rf"{CLASSES_PATH}\SystemFileAssociations"
PERSONAL_FILE_HANDLERS_PATH = r"Software\PersonalScripts\FileHandlers"

SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000

INVALID_EXTENSION_CHARACTERS = frozenset(r'\/:*?"<>|')
EXECUTABLE_TOKEN_PATTERN = re.compile(r'^\s*(?:"([^"]+)"|(\S+))')

SOURCE_ORDER: dict[str, int] = {
    "Explorer UserChoice": 0,
    "Extension default ProgID": 1,
    "Explorer OpenWithProgids": 2,
    "Classes OpenWithProgids": 3,
    "Explorer OpenWithList": 4,
    "Classes OpenWithList": 5,
    "RegisteredApplications / Capabilities": 6,
    "Applications / SupportedTypes": 7,
    "SystemFileAssociations shell verb": 8,
}


class RegistryScope(Enum):
    """Registry installation scope inspected by the tool."""

    USER = "Current user"
    MACHINE = "Local machine"


class DeleteKind(Enum):
    """Supported exact registry deletion operations."""

    VALUE = "value"
    KEY_TREE = "key-tree"


class RegistrationMethod(Enum):
    """Supported Windows file-handler registration entry points."""

    MODERN = "modern"
    OPEN_WITH_PROGIDS = "open-with-progids"
    APPLICATION_SUPPORTED_TYPES = "application-supported-types"


@dataclass(frozen=True)
class RegistryView:
    """One Windows registry architecture view."""

    name: str
    access_flag: int


@dataclass(frozen=True)
class AssociationReference:
    """One registry entry that advertises a handler for an extension."""

    source: str
    scope: RegistryScope
    view: RegistryView
    registry_path: str
    handler_id: str
    app_name: Optional[str] = None
    direct_command: Optional[str] = None
    command_registry_path: Optional[str] = None
    delete_kind: Optional[DeleteKind] = None
    delete_path: Optional[str] = None
    delete_value_name: Optional[str] = None
    delete_view_flags: tuple[int, ...] = ()


@dataclass(frozen=True)
class HandlerDefinition:
    """One concrete registry definition for a ProgID or application handler."""

    scope: RegistryScope
    view: RegistryView
    registry_path: str
    command: Optional[str]
    delegate_execute: Optional[str]
    executable_path: Optional[str]
    executable_exists: Optional[bool]


@dataclass(frozen=True)
class DeletionSpec:
    """Validated exact registry target selected for deletion."""

    extension: str
    source: str
    scope: RegistryScope
    view_flags: tuple[int, ...]
    kind: DeleteKind
    path: str
    value_name: Optional[str]
    handler_id: str


@dataclass(frozen=True)
class AddSpec:
    """Fully confirmed file-handler registration request."""

    extension: str
    method: RegistrationMethod
    executable_path: str
    app_name: str
    app_id: str
    progid: str
    arguments: str
    scope: RegistryScope


@dataclass(frozen=True)
class RegistryWrite:
    """One string value to create or replace in the registry."""

    path: str
    value_name: str
    value: str


@dataclass(frozen=True)
class RegistryValueSnapshot:
    """Prior state of a registry value used for best-effort rollback."""

    path: str
    value_name: str
    existed: bool
    value: str | int | bytes | list[str] | None
    value_type: int


def _combined_registry_view(views: set[RegistryView]) -> RegistryView:
    """Combine duplicate 32/64-bit results into one display view."""
    if len(views) == 1:
        return next(iter(views))
    view_names = " + ".join(
        view.name
        for view in sorted(views, key=lambda item: item.name, reverse=True)
    )
    return RegistryView(view_names, 0)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for interactive association management."""
    return argparse.ArgumentParser(
        description=(
            f"{FLYellow}WINDOWS FILE ASSOCIATION MANAGER{CRst}\n\n"
            "Inspect every known registry entry that can advertise an Open With "
            "handler for one file extension. Interactively remove an exact source "
            "entry or register an EXE for the current user or local machine."
        ),
        epilog=(
            f"{FLYellow}Options:{CRst}\n"
            f"  {FLCyan}--view EXTENSION{CRst}  Manage an extension without the first menu.\n"
            f"  {FLCyan}--help, -h{CRst}       Show this help message.\n\n"
            f"{FLYellow}Examples:{CRst}\n"
            f"  {FGray}python file-association.py{CRst}\n"
            f"  {FGray}python file-association.py --view .txt{CRst}\n\n"
            f"{FLYellow}Requirements:{CRst}\n"
            "  Windows 10 or later; Python standard library only."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _root_for_scope(scope: RegistryScope) -> int:
    """Return the predefined registry root for an installation scope.

    Args:
        scope: Current-user or local-machine scope.

    Returns:
        ``HKEY_CURRENT_USER`` or ``HKEY_LOCAL_MACHINE``.
    """
    if scope is RegistryScope.USER:
        return winreg.HKEY_CURRENT_USER
    return winreg.HKEY_LOCAL_MACHINE


def _scope_abbreviation(scope: RegistryScope) -> str:
    """Return the conventional short registry hive name for a scope."""
    if scope is RegistryScope.USER:
        return "HKCU"
    return "HKLM"


def _is_64_bit_windows() -> bool:
    """Return whether the operating system exposes 64-bit registry views."""
    architecture = os.environ.get("PROCESSOR_ARCHITECTURE", "")
    wow64_architecture = os.environ.get("PROCESSOR_ARCHITEW6432", "")
    return "64" in architecture or "64" in wow64_architecture


def _registry_views() -> tuple[RegistryView, ...]:
    """Return all registry architecture views available on this Windows host."""
    if _is_64_bit_windows():
        return (
            RegistryView("64-bit", winreg.KEY_WOW64_64KEY),
            RegistryView("32-bit", winreg.KEY_WOW64_32KEY),
        )
    return (RegistryView("native", 0),)


def _native_registry_view() -> RegistryView:
    """Return the process-native registry view for non-redirected user data."""
    return RegistryView("native", 0)


def _read_string_value(
    scope: RegistryScope,
    view: RegistryView,
    path: str,
    value_name: str,
) -> Optional[str]:
    """Read one registry value as a string, returning ``None`` if absent.

    Args:
        scope: Registry hive scope.
        view: Registry architecture view.
        path: Subkey path below the selected hive.
        value_name: Value name; an empty string reads the default value.

    Returns:
        The value converted to text, or ``None`` when the key/value is missing.

    Raises:
        PermissionError: If the current user cannot read an existing key.
        OSError: If Windows reports another registry access failure.
    """
    access = winreg.KEY_READ | view.access_flag
    try:
        with winreg.OpenKey(_root_for_scope(scope), path, 0, access) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
    except FileNotFoundError:
        return None
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _enum_values(
    scope: RegistryScope,
    view: RegistryView,
    path: str,
) -> list[tuple[str, str]]:
    """Enumerate value names and text representations below one registry key."""
    access = winreg.KEY_READ | view.access_flag
    try:
        key = winreg.OpenKey(_root_for_scope(scope), path, 0, access)
    except FileNotFoundError:
        return []

    values: list[tuple[str, str]] = []
    with key:
        index = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(key, index)
            except OSError as exc:
                if getattr(exc, "winerror", None) == 259:
                    break
                raise
            values.append((name, value if isinstance(value, str) else str(value)))
            index += 1
    return values


def _enum_subkeys(
    scope: RegistryScope,
    view: RegistryView,
    path: str,
) -> list[str]:
    """Enumerate immediate subkey names below one registry key."""
    access = winreg.KEY_READ | view.access_flag
    try:
        key = winreg.OpenKey(_root_for_scope(scope), path, 0, access)
    except FileNotFoundError:
        return []

    subkeys: list[str] = []
    with key:
        index = 0
        while True:
            try:
                subkeys.append(winreg.EnumKey(key, index))
            except OSError as exc:
                if getattr(exc, "winerror", None) == 259:
                    break
                raise
            index += 1
    return subkeys


def _normalize_extension(value: str) -> str:
    """Validate and normalize one registry file-extension key.

    Args:
        value: Extension with or without a leading period.

    Returns:
        Lowercase extension beginning with a period.

    Raises:
        ValueError: If the extension is empty or contains whitespace or a
            Windows-invalid filename character.
    """
    extension = value.strip()
    if not extension:
        raise ValueError("File extension cannot be empty.")
    if not extension.startswith("."):
        extension = f".{extension}"
    suffix = extension[1:]
    if not suffix:
        raise ValueError("File extension must contain characters after '.'.")
    if any(character.isspace() for character in suffix):
        raise ValueError("File extension cannot contain whitespace.")
    if any(character in INVALID_EXTENSION_CHARACTERS for character in suffix):
        raise ValueError("File extension contains a character invalid on Windows.")
    return extension.casefold()


def _application_handler_id(application_name: str) -> str:
    """Normalize a legacy executable name to an Applications handler ID."""
    normalized = application_name.strip()
    if normalized.casefold().startswith("applications\\"):
        return normalized
    return f"Applications\\{normalized}"


def _collect_class_references(extension: str) -> list[AssociationReference]:
    """Collect extension mappings under per-user and machine Classes keys."""
    references: list[AssociationReference] = []
    for scope in RegistryScope:
        for view in _registry_views():
            extension_path = rf"{CLASSES_PATH}\{extension}"
            default_progid = _read_string_value(scope, view, extension_path, "")
            if default_progid:
                references.append(AssociationReference(
                    source="Extension default ProgID",
                    scope=scope,
                    view=view,
                    registry_path=extension_path,
                    handler_id=default_progid,
                    delete_kind=DeleteKind.VALUE,
                    delete_path=extension_path,
                    delete_value_name="",
                    delete_view_flags=(view.access_flag,),
                ))

            progids_path = rf"{extension_path}\OpenWithProgids"
            for progid, _ in _enum_values(scope, view, progids_path):
                if progid:
                    references.append(AssociationReference(
                        source="Classes OpenWithProgids",
                        scope=scope,
                        view=view,
                        registry_path=progids_path,
                        handler_id=progid,
                        delete_kind=DeleteKind.VALUE,
                        delete_path=progids_path,
                        delete_value_name=progid,
                        delete_view_flags=(view.access_flag,),
                    ))

            open_with_list_path = rf"{extension_path}\OpenWithList"
            for application_name in _enum_subkeys(scope, view, open_with_list_path):
                references.append(AssociationReference(
                    source="Classes OpenWithList",
                    scope=scope,
                    view=view,
                    registry_path=rf"{open_with_list_path}\{application_name}",
                    handler_id=_application_handler_id(application_name),
                    app_name=application_name,
                    delete_kind=DeleteKind.KEY_TREE,
                    delete_path=rf"{open_with_list_path}\{application_name}",
                    delete_view_flags=(view.access_flag,),
                ))
            for value_name, value in _enum_values(scope, view, open_with_list_path):
                candidate = value or value_name
                if candidate and candidate.casefold() != "mrulist":
                    references.append(AssociationReference(
                        source="Classes OpenWithList",
                        scope=scope,
                        view=view,
                        registry_path=rf"{open_with_list_path} [{value_name}]",
                        handler_id=_application_handler_id(candidate),
                        app_name=candidate,
                        delete_kind=DeleteKind.VALUE,
                        delete_path=open_with_list_path,
                        delete_value_name=value_name,
                        delete_view_flags=(view.access_flag,),
                    ))
    return references


def _collect_explorer_references(extension: str) -> list[AssociationReference]:
    """Collect current-user FileExts UserChoice and Open With history entries."""
    references: list[AssociationReference] = []
    scope = RegistryScope.USER
    view = _native_registry_view()
    extension_path = rf"{EXPLORER_FILE_EXTS_PATH}\{extension}"

    user_choice_path = rf"{extension_path}\UserChoice"
    user_choice = _read_string_value(scope, view, user_choice_path, "ProgId")
    if user_choice:
        references.append(AssociationReference(
            source="Explorer UserChoice",
            scope=scope,
            view=view,
            registry_path=user_choice_path,
            handler_id=user_choice,
            delete_kind=DeleteKind.KEY_TREE,
            delete_path=user_choice_path,
            delete_view_flags=(view.access_flag,),
        ))

    progids_path = rf"{extension_path}\OpenWithProgids"
    for progid, _ in _enum_values(scope, view, progids_path):
        if progid:
            references.append(AssociationReference(
                source="Explorer OpenWithProgids",
                scope=scope,
                view=view,
                registry_path=progids_path,
                handler_id=progid,
                delete_kind=DeleteKind.VALUE,
                delete_path=progids_path,
                delete_value_name=progid,
                delete_view_flags=(view.access_flag,),
            ))

    open_with_list_path = rf"{extension_path}\OpenWithList"
    for value_name, application_name in _enum_values(scope, view, open_with_list_path):
        if value_name.casefold() == "mrulist" or not application_name:
            continue
        references.append(AssociationReference(
            source="Explorer OpenWithList",
            scope=scope,
            view=view,
            registry_path=rf"{open_with_list_path} [{value_name}]",
            handler_id=_application_handler_id(application_name),
            app_name=application_name,
            delete_kind=DeleteKind.VALUE,
            delete_path=open_with_list_path,
            delete_value_name=value_name,
            delete_view_flags=(view.access_flag,),
        ))
    return references


def _collect_registered_application_references(
    extension: str,
) -> list[AssociationReference]:
    """Collect Default Apps candidates declared through Capabilities."""
    references: list[AssociationReference] = []
    for scope in RegistryScope:
        for view in _registry_views():
            for registered_name, capability_path in _enum_values(
                scope,
                view,
                REGISTERED_APPLICATIONS_PATH,
            ):
                if not registered_name or not capability_path:
                    continue
                file_associations_path = rf"{capability_path}\FileAssociations"
                progid = _read_string_value(
                    scope,
                    view,
                    file_associations_path,
                    extension,
                )
                if not progid:
                    continue
                application_name = (
                    _read_string_value(scope, view, capability_path, "ApplicationName")
                    or registered_name
                )
                references.append(AssociationReference(
                    source="RegisteredApplications / Capabilities",
                    scope=scope,
                    view=view,
                    registry_path=(
                        f"{REGISTERED_APPLICATIONS_PATH} [{registered_name}] -> "
                        f"{file_associations_path} [{extension}]"
                    ),
                    handler_id=progid,
                    app_name=application_name,
                    delete_kind=DeleteKind.VALUE,
                    delete_path=file_associations_path,
                    delete_value_name=extension,
                    delete_view_flags=(view.access_flag,),
                ))
    return references


def _collect_supported_type_references(extension: str) -> list[AssociationReference]:
    """Collect Applications entries that explicitly declare the extension."""
    references: list[AssociationReference] = []
    for scope in RegistryScope:
        for view in _registry_views():
            applications_path = rf"{CLASSES_PATH}\Applications"
            for application_name in _enum_subkeys(scope, view, applications_path):
                application_path = rf"{applications_path}\{application_name}"
                supported_types_path = rf"{application_path}\SupportedTypes"
                supported_extensions = {
                    value_name.casefold()
                    for value_name, _ in _enum_values(scope, view, supported_types_path)
                }
                if extension.casefold() not in supported_extensions:
                    continue
                friendly_name = (
                    _read_string_value(scope, view, application_path, "FriendlyAppName")
                    or application_name
                )
                references.append(AssociationReference(
                    source="Applications / SupportedTypes",
                    scope=scope,
                    view=view,
                    registry_path=rf"{supported_types_path} [{extension}]",
                    handler_id=_application_handler_id(application_name),
                    app_name=friendly_name,
                    delete_kind=DeleteKind.VALUE,
                    delete_path=supported_types_path,
                    delete_value_name=extension,
                    delete_view_flags=(view.access_flag,),
                ))
    return references


def _collect_perceived_types(extension: str) -> set[str]:
    """Return PerceivedType values declared for an extension."""
    perceived_types: set[str] = set()
    for scope in RegistryScope:
        for view in _registry_views():
            extension_path = rf"{CLASSES_PATH}\{extension}"
            perceived_type = _read_string_value(scope, view, extension_path, "PerceivedType")
            if perceived_type:
                perceived_types.add(perceived_type)
    return perceived_types


def _collect_system_file_association_references(
    extension: str,
) -> list[AssociationReference]:
    """Collect direct shell verbs inherited from SystemFileAssociations."""
    references: list[AssociationReference] = []
    association_types = {extension, *_collect_perceived_types(extension)}
    for scope in RegistryScope:
        for view in _registry_views():
            for association_type in sorted(association_types, key=str.casefold):
                shell_path = rf"{SYSTEM_FILE_ASSOCIATIONS_PATH}\{association_type}\shell"
                for verb in _enum_subkeys(scope, view, shell_path):
                    command_path = rf"{shell_path}\{verb}\command"
                    command = _read_string_value(scope, view, command_path, "")
                    if not command:
                        continue
                    references.append(AssociationReference(
                        source="SystemFileAssociations shell verb",
                        scope=scope,
                        view=view,
                        registry_path=rf"{shell_path}\{verb}",
                        handler_id=rf"SystemFileAssociations\{association_type}\{verb}",
                        app_name=verb,
                        direct_command=command,
                        command_registry_path=command_path,
                        delete_kind=DeleteKind.KEY_TREE,
                        delete_path=rf"{shell_path}\{verb}",
                        delete_view_flags=(view.access_flag,),
                    ))
    return references


def _collect_references(extension: str) -> list[AssociationReference]:
    """Collect and deterministically order all handler-advertising entries."""
    references = [
        *_collect_explorer_references(extension),
        *_collect_class_references(extension),
        *_collect_registered_application_references(extension),
        *_collect_supported_type_references(extension),
        *_collect_system_file_association_references(extension),
    ]
    references_by_entry: dict[
        tuple[
            str,
            RegistryScope,
            str,
            str,
            Optional[str],
            Optional[str],
            Optional[str],
            Optional[DeleteKind],
            Optional[str],
            Optional[str],
        ],
        tuple[AssociationReference, set[RegistryView], set[int]],
    ] = {}
    for reference in references:
        entry_key = (
            reference.source,
            reference.scope,
            reference.registry_path,
            reference.handler_id,
            reference.app_name,
            reference.direct_command,
            reference.command_registry_path,
            reference.delete_kind,
            reference.delete_path,
            reference.delete_value_name,
        )
        existing = references_by_entry.get(entry_key)
        if existing is None:
            references_by_entry[entry_key] = (
                reference,
                {reference.view},
                set(reference.delete_view_flags),
            )
        else:
            existing[1].add(reference.view)
            existing[2].update(reference.delete_view_flags)

    unique_references = [
        AssociationReference(
            source=reference.source,
            scope=reference.scope,
            view=_combined_registry_view(views),
            registry_path=reference.registry_path,
            handler_id=reference.handler_id,
            app_name=reference.app_name,
            direct_command=reference.direct_command,
            command_registry_path=reference.command_registry_path,
            delete_kind=reference.delete_kind,
            delete_path=reference.delete_path,
            delete_value_name=reference.delete_value_name,
            delete_view_flags=tuple(sorted(view_flags)),
        )
        for reference, views, view_flags in references_by_entry.values()
    ]
    return sorted(
        unique_references,
        key=lambda item: (
            SOURCE_ORDER.get(item.source, len(SOURCE_ORDER)),
            item.scope.value,
            item.view.name,
            item.registry_path.casefold(),
            item.handler_id.casefold(),
        ),
    )


def _extract_executable(command: str) -> tuple[Optional[str], Optional[bool]]:
    """Best-effort resolve the executable token from a shell command string."""
    expanded_command = os.path.expandvars(command)
    match = EXECUTABLE_TOKEN_PATTERN.match(expanded_command)
    if match is None:
        return None, None
    executable = (match.group(1) or match.group(2) or "").strip()
    if not executable:
        return None, None
    if os.path.isabs(executable):
        return executable, os.path.isfile(executable)
    resolved = Environment.which(executable)
    if resolved is not None:
        return resolved, os.path.isfile(resolved)
    return executable, False


def _build_handler_definition(
    scope: RegistryScope,
    view: RegistryView,
    command_path: str,
) -> HandlerDefinition:
    """Build a resolved handler definition from one command registry key."""
    command = _read_string_value(scope, view, command_path, "")
    delegate_execute = _read_string_value(scope, view, command_path, "DelegateExecute")
    executable_path: Optional[str] = None
    executable_exists: Optional[bool] = None
    if command:
        executable_path, executable_exists = _extract_executable(command)
    return HandlerDefinition(
        scope=scope,
        view=view,
        registry_path=command_path,
        command=command,
        delegate_execute=delegate_execute,
        executable_path=executable_path,
        executable_exists=executable_exists,
    )


def _find_handler_definitions(
    reference: AssociationReference,
) -> list[HandlerDefinition]:
    """Resolve every user/machine definition for one advertised handler."""
    if reference.direct_command is not None:
        executable_path, executable_exists = _extract_executable(reference.direct_command)
        return [HandlerDefinition(
            scope=reference.scope,
            view=reference.view,
            registry_path=reference.command_registry_path or reference.registry_path,
            command=reference.direct_command,
            delegate_execute=None,
            executable_path=executable_path,
            executable_exists=executable_exists,
        )]

    definitions: list[HandlerDefinition] = []
    for scope in RegistryScope:
        for view in _registry_views():
            command_path = rf"{CLASSES_PATH}\{reference.handler_id}\shell\open\command"
            command = _read_string_value(scope, view, command_path, "")
            delegate_execute = _read_string_value(
                scope,
                view,
                command_path,
                "DelegateExecute",
            )
            if command is None and delegate_execute is None:
                continue
            definitions.append(_build_handler_definition(scope, view, command_path))

    definitions_by_command: dict[
        tuple[
            RegistryScope,
            str,
            Optional[str],
            Optional[str],
            Optional[str],
            Optional[bool],
        ],
        tuple[HandlerDefinition, set[RegistryView]],
    ] = {}
    for definition in definitions:
        command_key = (
            definition.scope,
            definition.registry_path,
            definition.command,
            definition.delegate_execute,
            definition.executable_path,
            definition.executable_exists,
        )
        existing = definitions_by_command.get(command_key)
        if existing is None:
            definitions_by_command[command_key] = (definition, {definition.view})
        else:
            existing[1].add(definition.view)

    return [
        HandlerDefinition(
            scope=definition.scope,
            view=_combined_registry_view(views),
            registry_path=definition.registry_path,
            command=definition.command,
            delegate_execute=definition.delegate_execute,
            executable_path=definition.executable_path,
            executable_exists=definition.executable_exists,
        )
        for definition, views in definitions_by_command.values()
    ]


def _format_registry_path(
    scope: RegistryScope,
    view: RegistryView,
    path: str,
) -> str:
    """Format a registry path with hive and architecture-view information."""
    return f"{_scope_abbreviation(scope)}\\{path} ({view.name})"


def _print_definition(definition: HandlerDefinition, indent: str = "      ") -> None:
    """Print one resolved command definition and executable status."""
    print(
        f"{indent}{FLCyan}Command key:{CRst} "
        f"{FGray}{_format_registry_path(definition.scope, definition.view, definition.registry_path)}{CRst}"
    )
    if definition.command is not None:
        print(f"{indent}{FLCyan}Command:{CRst}     {definition.command}")
    if definition.delegate_execute is not None:
        print(
            f"{indent}{FLCyan}DelegateExecute:{CRst} "
            f"{definition.delegate_execute or '(empty)'}"
        )
    if definition.executable_path is not None:
        if definition.executable_exists:
            status = f"{FLGreen}exists{CRst}"
        elif definition.executable_exists is False:
            status = f"{FLRed}missing or unresolved{CRst}"
        else:
            status = f"{FGray}unknown{CRst}"
        print(
            f"{indent}{FLCyan}Executable:{CRst}  "
            f"{definition.executable_path} ({status})"
        )


def _print_inspection(extension: str, references: list[AssociationReference]) -> None:
    """Print all association sources and their resolved handler definitions."""
    print(f"  {FLYellow}Extension:{CRst} {FLCyan}{extension}{CRst}")
    print(
        f"  {FGray}HKCR is a merged view and is not listed separately; "
        f"its HKCU/HKLM backing entries are shown below.{CRst}"
    )

    if not references:
        print(f"\n  {FLYellow}No file-association entries were found.{CRst}")
        return

    unique_handlers = {reference.handler_id.casefold() for reference in references}
    print(
        f"  {FGray}Found {len(references)} source entries advertising "
        f"{len(unique_handlers)} unique handlers.{CRst}"
    )

    for index, reference in enumerate(references, start=1):
        print()
        print(f"  {FGray}[{index}]{CRst} {FLYellow}{reference.source}{CRst}")
        print(f"      {FLCyan}Scope:{CRst}       {reference.scope.value} / {reference.view.name}")
        print(
            f"      {FLCyan}Entry:{CRst}       "
            f"{FGray}{_format_registry_path(reference.scope, reference.view, reference.registry_path)}{CRst}"
        )
        print(f"      {FLCyan}Handler:{CRst}     {reference.handler_id}")
        if reference.app_name:
            print(f"      {FLCyan}Application:{CRst} {reference.app_name}")

        definitions = _find_handler_definitions(reference)
        if not definitions:
            print(f"      {FGray}No shell\\open\\command definition was found.{CRst}")
            continue
        for definition in definitions:
            _print_definition(definition)


def _encode_payload(payload: dict[str, str | list[int]]) -> str:
    """Encode a confirmed operation for command-line elevation re-entry."""
    raw_payload = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw_payload.encode("utf-8")).decode("ascii")


def _decode_payload(encoded_payload: str) -> dict[str, str | list[int]]:
    """Decode and structurally validate an elevation re-entry payload."""
    try:
        raw_payload = base64.urlsafe_b64decode(encoded_payload.encode("ascii"))
        decoded: object = json.loads(raw_payload.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("The elevated operation payload is invalid.") from exc
    if not isinstance(decoded, dict):
        raise ValueError("The elevated operation payload must be an object.")

    payload: dict[str, str | list[int]] = {}
    for raw_key, raw_value in decoded.items():
        if not isinstance(raw_key, str):
            raise ValueError("The elevated operation payload has an invalid key.")
        if isinstance(raw_value, str):
            payload[raw_key] = raw_value
            continue
        if isinstance(raw_value, list) and all(
            isinstance(item, int) for item in raw_value
        ):
            payload[raw_key] = raw_value
            continue
        raise ValueError(f"The elevated operation field '{raw_key}' is invalid.")
    return payload


def _payload_string(payload: dict[str, str | list[int]], key: str) -> str:
    """Return one required string field from a decoded operation payload."""
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"The elevated operation field '{key}' is missing.")
    return value


def _encode_deletion_spec(spec: DeletionSpec) -> str:
    """Serialize one confirmed exact deletion request."""
    return _encode_payload({
        "extension": spec.extension,
        "source": spec.source,
        "scope": spec.scope.name,
        "view_flags": list(spec.view_flags),
        "kind": spec.kind.name,
        "path": spec.path,
        "value_name": spec.value_name if spec.value_name is not None else "",
        "handler_id": spec.handler_id,
    })


def _decode_deletion_spec(encoded_payload: str) -> DeletionSpec:
    """Deserialize and validate one elevated deletion request."""
    payload = _decode_payload(encoded_payload)
    raw_flags = payload.get("view_flags")
    if not isinstance(raw_flags, list) or not raw_flags:
        raise ValueError("The elevated deletion payload has no registry view.")
    delete_kind = DeleteKind[_payload_string(payload, "kind")]
    raw_value_name = _payload_string(payload, "value_name")
    spec = DeletionSpec(
        extension=_normalize_extension(_payload_string(payload, "extension")),
        source=_payload_string(payload, "source"),
        scope=RegistryScope[_payload_string(payload, "scope")],
        view_flags=tuple(raw_flags),
        kind=delete_kind,
        path=_payload_string(payload, "path"),
        value_name=raw_value_name if delete_kind is DeleteKind.VALUE else None,
        handler_id=_payload_string(payload, "handler_id"),
    )
    _validate_deletion_spec(spec)
    return spec


def _encode_add_spec(spec: AddSpec) -> str:
    """Serialize one fully confirmed file-handler registration request."""
    return _encode_payload({
        "extension": spec.extension,
        "method": spec.method.name,
        "executable_path": spec.executable_path,
        "app_name": spec.app_name,
        "app_id": spec.app_id,
        "progid": spec.progid,
        "arguments": spec.arguments,
        "scope": spec.scope.name,
    })


def _decode_add_spec(encoded_payload: str) -> AddSpec:
    """Deserialize and validate one elevated registration request."""
    payload = _decode_payload(encoded_payload)
    spec = AddSpec(
        extension=_normalize_extension(_payload_string(payload, "extension")),
        method=RegistrationMethod[_payload_string(payload, "method")],
        executable_path=os.path.abspath(_payload_string(payload, "executable_path")),
        app_name=_payload_string(payload, "app_name"),
        app_id=_payload_string(payload, "app_id"),
        progid=_payload_string(payload, "progid"),
        arguments=_payload_string(payload, "arguments"),
        scope=RegistryScope[_payload_string(payload, "scope")],
    )
    _validate_add_spec(spec)
    return spec


def _restart_elevated(operation_flag: str, encoded_payload: str) -> None:
    """Re-enter this script through the shared in-place elevation helper."""
    sys.argv = [os.path.abspath(sys.argv[0]), operation_flag, encoded_payload]
    System.restart_elevated()
    raise RuntimeError("The elevation helper returned without elevating the process.")


def _validate_deletion_spec(spec: DeletionSpec) -> None:
    """Reject malformed or over-broad registry deletion targets."""
    expected_targets: dict[str, tuple[DeleteKind, str, Optional[str]]] = {
        "Explorer UserChoice": (
            DeleteKind.KEY_TREE,
            rf"{EXPLORER_FILE_EXTS_PATH}\{spec.extension}\UserChoice",
            None,
        ),
        "Extension default ProgID": (
            DeleteKind.VALUE,
            rf"{CLASSES_PATH}\{spec.extension}",
            "",
        ),
        "Explorer OpenWithProgids": (
            DeleteKind.VALUE,
            rf"{EXPLORER_FILE_EXTS_PATH}\{spec.extension}\OpenWithProgids",
            spec.handler_id,
        ),
        "Classes OpenWithProgids": (
            DeleteKind.VALUE,
            rf"{CLASSES_PATH}\{spec.extension}\OpenWithProgids",
            spec.handler_id,
        ),
        "Explorer OpenWithList": (
            DeleteKind.VALUE,
            rf"{EXPLORER_FILE_EXTS_PATH}\{spec.extension}\OpenWithList",
            spec.value_name,
        ),
        "Applications / SupportedTypes": (
            DeleteKind.VALUE,
            rf"{CLASSES_PATH}\Applications",
            spec.extension,
        ),
    }
    expected = expected_targets.get(spec.source)
    if expected is not None:
        expected_kind, expected_path, expected_value_name = expected
        path_matches = (
            spec.path.casefold() == expected_path.casefold()
            if spec.source != "Applications / SupportedTypes"
            else len(spec.path[len(expected_path) + 1:].split("\\")) == 2
            and spec.path.casefold().startswith(f"{expected_path.casefold()}\\")
            and spec.path.casefold().endswith("\\supportedtypes")
        )
        if (
            spec.kind is not expected_kind
            or not path_matches
            or spec.value_name != expected_value_name
        ):
            raise ValueError("The deletion target does not match its association source.")
    elif spec.source == "Classes OpenWithList":
        base_path = rf"{CLASSES_PATH}\{spec.extension}\OpenWithList"
        is_value = spec.kind is DeleteKind.VALUE and spec.path.casefold() == base_path.casefold()
        is_child_key = (
            spec.kind is DeleteKind.KEY_TREE
            and spec.path.casefold().startswith(f"{base_path.casefold()}\\")
            and "\\" not in spec.path[len(base_path) + 1:]
        )
        if not (is_value or is_child_key):
            raise ValueError("The Classes OpenWithList deletion target is invalid.")
    elif spec.source == "RegisteredApplications / Capabilities":
        if not (
            spec.kind is DeleteKind.VALUE
            and spec.path.casefold().startswith("software\\")
            and spec.path.casefold().endswith("\\fileassociations")
            and spec.value_name == spec.extension
        ):
            raise ValueError("The Capabilities deletion target is invalid.")
    elif spec.source == "SystemFileAssociations shell verb":
        prefix = f"{SYSTEM_FILE_ASSOCIATIONS_PATH}\\"
        path_suffix = spec.path[len(prefix):] if spec.path.casefold().startswith(prefix.casefold()) else ""
        shell_parts = re.split(r"\\shell\\", path_suffix, maxsplit=1, flags=re.IGNORECASE)
        if not (
            spec.kind is DeleteKind.KEY_TREE
            and len(shell_parts) == 2
            and bool(shell_parts[0])
            and bool(shell_parts[1])
            and "\\" not in shell_parts[1]
        ):
            raise ValueError("The SystemFileAssociations deletion target is invalid.")
    else:
        raise ValueError(f"Deletion is not supported for source '{spec.source}'.")

    valid_view_flags = {view.access_flag for view in _registry_views()} | {0}
    if not spec.view_flags or any(flag not in valid_view_flags for flag in spec.view_flags):
        raise ValueError("The deletion target contains an invalid registry view.")


def _delete_registry_key_tree(
    scope: RegistryScope,
    view_flag: int,
    path: str,
) -> bool:
    """Delete one exact registry key tree and return whether it existed."""
    root = _root_for_scope(scope)
    access = winreg.KEY_READ | winreg.KEY_WRITE | view_flag
    try:
        key = winreg.OpenKey(root, path, 0, access)
    except FileNotFoundError:
        return False
    with key:
        child_names: list[str] = []
        index = 0
        while True:
            try:
                child_names.append(winreg.EnumKey(key, index))
            except OSError as exc:
                if getattr(exc, "winerror", None) == 259:
                    break
                raise
            index += 1
    for child_name in child_names:
        _delete_registry_key_tree(scope, view_flag, rf"{path}\{child_name}")
    winreg.DeleteKeyEx(root, path, view_flag, 0)
    return True


def _apply_deletion(spec: DeletionSpec) -> int:
    """Apply one validated exact deletion across its recorded registry views."""
    _validate_deletion_spec(spec)
    deleted_count = 0
    root = _root_for_scope(spec.scope)
    for view_flag in spec.view_flags:
        if spec.kind is DeleteKind.KEY_TREE:
            if _delete_registry_key_tree(spec.scope, view_flag, spec.path):
                deleted_count += 1
            continue
        try:
            with winreg.OpenKey(
                root,
                spec.path,
                0,
                winreg.KEY_SET_VALUE | view_flag,
            ) as key:
                winreg.DeleteValue(key, spec.value_name or "")
            deleted_count += 1
        except FileNotFoundError:
            continue
    if deleted_count:
        _notify_association_change()
    return deleted_count


def _notify_association_change() -> None:
    """Notify Explorer that file-association registry data changed."""
    ctypes.windll.shell32.SHChangeNotify(
        SHCNE_ASSOCCHANGED,
        SHCNF_IDLIST,
        None,
        None,
    )


def _validate_add_spec(spec: AddSpec) -> None:
    """Validate a confirmed registration request before registry writes."""
    if not os.path.isfile(spec.executable_path):
        raise ValueError(f"Executable does not exist: {spec.executable_path}")
    if os.path.splitext(spec.executable_path)[1].casefold() != ".exe":
        raise ValueError("The selected application must be an .exe file.")
    if not spec.app_name.strip() or not re.fullmatch(r"[A-Za-z0-9_]+", spec.app_id):
        raise ValueError("The application name or generated identifier is invalid.")
    expected_prefix = f"PersonalScripts.FileHandler.{spec.app_id}."
    if not spec.progid.startswith(expected_prefix):
        raise ValueError("The generated ProgID is invalid.")
    if not spec.arguments.strip():
        raise ValueError("The command arguments cannot be empty.")


def _shell_command(spec: AddSpec) -> str:
    """Build the registered shell command for one add request."""
    return f'"{spec.executable_path}" {spec.arguments.strip()}'


def _build_registration_writes(spec: AddSpec) -> list[RegistryWrite]:
    """Build the exact registry value plan for a registration method."""
    _validate_add_spec(spec)
    writes: list[RegistryWrite] = []
    command = _shell_command(spec)
    executable_name = os.path.basename(spec.executable_path)
    progid_path = rf"{CLASSES_PATH}\{spec.progid}"
    application_path = rf"{CLASSES_PATH}\Applications\{executable_name}"

    if spec.method in {RegistrationMethod.MODERN, RegistrationMethod.OPEN_WITH_PROGIDS}:
        writes.extend([
            RegistryWrite(progid_path, "", f"{spec.app_name} file"),
            RegistryWrite(rf"{progid_path}\DefaultIcon", "", f"{spec.executable_path},0"),
            RegistryWrite(rf"{progid_path}\shell\open\command", "", command),
            RegistryWrite(
                rf"{CLASSES_PATH}\{spec.extension}\OpenWithProgids",
                spec.progid,
                "",
            ),
        ])

    if spec.method in {
        RegistrationMethod.MODERN,
        RegistrationMethod.APPLICATION_SUPPORTED_TYPES,
    }:
        writes.extend([
            RegistryWrite(application_path, "FriendlyAppName", spec.app_name),
            RegistryWrite(rf"{application_path}\shell\open\command", "", command),
            RegistryWrite(rf"{application_path}\SupportedTypes", spec.extension, ""),
        ])

    if spec.method is RegistrationMethod.MODERN:
        capabilities_path = rf"{PERSONAL_FILE_HANDLERS_PATH}\{spec.app_id}\Capabilities"
        writes.extend([
            RegistryWrite(capabilities_path, "ApplicationName", spec.app_name),
            RegistryWrite(
                capabilities_path,
                "ApplicationDescription",
                f"{spec.app_name} file handler registered by PersonalScripts",
            ),
            RegistryWrite(
                rf"{capabilities_path}\FileAssociations",
                spec.extension,
                spec.progid,
            ),
            RegistryWrite(
                REGISTERED_APPLICATIONS_PATH,
                f"PersonalScripts.{spec.app_id}",
                capabilities_path,
            ),
        ])
    return writes


def _snapshot_registry_value(
    scope: RegistryScope,
    view_flag: int,
    write: RegistryWrite,
) -> RegistryValueSnapshot:
    """Capture one registry value before a transactional write attempt."""
    try:
        with winreg.OpenKey(
            _root_for_scope(scope),
            write.path,
            0,
            winreg.KEY_QUERY_VALUE | view_flag,
        ) as key:
            value, value_type = winreg.QueryValueEx(key, write.value_name)
    except FileNotFoundError:
        return RegistryValueSnapshot(write.path, write.value_name, False, None, winreg.REG_NONE)
    return RegistryValueSnapshot(write.path, write.value_name, True, value, value_type)


def _registration_view_flag() -> int:
    """Return the preferred registry view for new file-handler registrations."""
    return winreg.KEY_WOW64_64KEY if _is_64_bit_windows() else 0


def _apply_registration(spec: AddSpec) -> int:
    """Apply a registration plan with best-effort value rollback on failure."""
    writes = _build_registration_writes(spec)
    view_flag = _registration_view_flag()
    snapshots = [
        _snapshot_registry_value(spec.scope, view_flag, write)
        for write in writes
    ]
    applied: list[tuple[RegistryWrite, RegistryValueSnapshot]] = []
    root = _root_for_scope(spec.scope)
    try:
        for write, snapshot in zip(writes, snapshots, strict=True):
            if snapshot.existed and snapshot.value == write.value:
                continue
            with winreg.CreateKeyEx(
                root,
                write.path,
                0,
                winreg.KEY_SET_VALUE | view_flag,
            ) as key:
                winreg.SetValueEx(key, write.value_name, 0, winreg.REG_SZ, write.value)
            applied.append((write, snapshot))
    except OSError:
        for write, snapshot in reversed(applied):
            try:
                with winreg.OpenKey(
                    root,
                    write.path,
                    0,
                    winreg.KEY_SET_VALUE | view_flag,
                ) as key:
                    if snapshot.existed:
                        winreg.SetValueEx(
                            key,
                            snapshot.value_name,
                            0,
                            snapshot.value_type,
                            snapshot.value,
                        )
                    else:
                        winreg.DeleteValue(key, snapshot.value_name)
            except OSError:
                pass
        raise
    if applied:
        _notify_association_change()
    return len(applied)


def _prompt_extension() -> str:
    """Prompt repeatedly until the user enters a valid file extension."""
    while True:
        raw_extension = Input.prompt(f"{FLYellow}File extension{FGray} (for example, .txt){CRst}: ")
        try:
            return _normalize_extension(raw_extension)
        except ValueError as exc:
            print(f"{FLRed}{exc}{CRst}")


def _view_extension(extension_value: str) -> int:
    """Normalize, inspect, and print all handlers for one extension."""
    try:
        extension = _normalize_extension(extension_value)
    except ValueError as exc:
        print(f"{FLRed}Invalid extension:{CRst} {exc}", file=sys.stderr)
        return 2

    try:
        references = _collect_references(extension)
    except PermissionError as exc:
        print(f"{FLRed}Registry permission denied:{CRst} {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"{FLRed}Cannot read the Windows registry:{CRst} {exc}", file=sys.stderr)
        return 1

    _print_inspection(extension, references)
    return 0


def _collect_and_print(extension: str) -> Optional[list[AssociationReference]]:
    """Collect and display one extension, returning ``None`` on registry errors."""
    try:
        references = _collect_references(extension)
    except PermissionError as exc:
        print(f"{FLRed}Registry permission denied:{CRst} {exc}", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"{FLRed}Cannot read the Windows registry:{CRst} {exc}", file=sys.stderr)
        return None
    _print_inspection(extension, references)
    return references


def _deletion_spec_for_reference(
    extension: str,
    reference: AssociationReference,
) -> DeletionSpec:
    """Create a validated exact deletion request from one displayed reference."""
    if (
        reference.delete_kind is None
        or reference.delete_path is None
        or not reference.delete_view_flags
    ):
        raise ValueError("This association source cannot be deleted safely.")
    spec = DeletionSpec(
        extension=extension,
        source=reference.source,
        scope=reference.scope,
        view_flags=reference.delete_view_flags,
        kind=reference.delete_kind,
        path=reference.delete_path,
        value_name=reference.delete_value_name,
        handler_id=reference.handler_id,
    )
    _validate_deletion_spec(spec)
    return spec


def _confirm_delete(spec: DeletionSpec) -> bool:
    """Show the exact registry target and ask for destructive confirmation."""
    view_names = ", ".join(
        view.name
        for view in _registry_views()
        if view.access_flag in spec.view_flags
    ) or "native"
    print(f"\n  {FLYellow}Delete this exact association source?{CRst}")
    print(f"  {FLCyan}Source:{CRst}  {spec.source}")
    print(f"  {FLCyan}Handler:{CRst} {spec.handler_id}")
    print(
        f"  {FLCyan}Target:{CRst}  {FGray}{_scope_abbreviation(spec.scope)}\\"
        f"{spec.path} ({view_names}){CRst}"
    )
    if spec.kind is DeleteKind.VALUE:
        value_name = spec.value_name if spec.value_name else "(Default)"
        print(f"  {FLCyan}Value:{CRst}   {FGray}{value_name}{CRst}")
    print(f"  {FLRed}This deletion cannot be automatically undone.{CRst}")
    selected = Menu.select(
        [
            MenuOption(["Y"], "Delete this entry", value=True),
            MenuOption(["N"], "Cancel", value=False),
        ],
        prompt="Confirm deletion",
        default_key="N",
        inline=True,
        separator=False,
    )
    return selected is True


def _execute_deletion(spec: DeletionSpec) -> bool:
    """Elevate when needed, apply an exact deletion, and report its outcome."""
    if spec.scope is RegistryScope.MACHINE and not System.is_elevated():
        _restart_elevated("--apply-delete-spec", _encode_deletion_spec(spec))
    try:
        deleted_count = _apply_deletion(spec)
    except PermissionError:
        if not System.is_elevated():
            _restart_elevated("--apply-delete-spec", _encode_deletion_spec(spec))
        print(f"{FLRed}Deletion failed: the registry entry is protected.{CRst}")
        return False
    except OSError as exc:
        print(f"{FLRed}Deletion failed:{CRst} {exc}")
        return False
    if deleted_count == 0:
        print(f"{FLYellow}The selected registry entry no longer exists.{CRst}")
        return False
    print(f"{FLGreen}Deleted the selected association source.{CRst}")
    return True


def _manage_extension(extension_value: str) -> int:
    """List, optionally delete, and then relist entries for one extension."""
    try:
        extension = _normalize_extension(extension_value)
    except ValueError as exc:
        print(f"{FLRed}Invalid extension:{CRst} {exc}", file=sys.stderr)
        return 2

    while True:
        references = _collect_and_print(extension)
        if references is None:
            return 1
        selected = Menu.select(
            [MenuOption(["R"], "Return to main menu", value="return", desc_color=CRst)],
            prompt="Delete entry number",
            default_key="R",
            separator=False,
            accept_custom_string=True,
        )
        if selected in {None, "return"}:
            return 0
        if not isinstance(selected, str) or not selected.isdecimal():
            print(f"{FLRed}Enter a listed entry number, or press Enter to return.{CRst}")
            continue
        selected_index = int(selected)
        if not 1 <= selected_index <= len(references):
            print(f"{FLRed}Entry number must be between 1 and {len(references)}.{CRst}")
            continue
        try:
            deletion_spec = _deletion_spec_for_reference(
                extension,
                references[selected_index - 1],
            )
        except ValueError as exc:
            print(f"{FLRed}Cannot delete this entry safely:{CRst} {exc}")
            continue
        if not _confirm_delete(deletion_spec):
            continue
        _execute_deletion(deletion_spec)
        print()


def _prompt_registration_method() -> Optional[RegistrationMethod]:
    """Ask which supported Windows registration entry point to use."""
    selected = Menu.select(
        [
            MenuOption(
                ["1"],
                "Default Apps + Open With (recommended for Windows 10/11)",
                value=RegistrationMethod.MODERN,
            ),
            MenuOption(
                ["2"],
                "OpenWithProgids only",
                value=RegistrationMethod.OPEN_WITH_PROGIDS,
            ),
            MenuOption(
                ["3"],
                "Applications / SupportedTypes only",
                value=RegistrationMethod.APPLICATION_SUPPORTED_TYPES,
            ),
        ],
        prompt="Registration method",
        default_key="1",
        separator=False,
    )
    return selected if isinstance(selected, RegistrationMethod) else None


def _prompt_command_arguments() -> Optional[str]:
    """Confirm the default file argument or collect a custom argument string."""
    default_arguments = '"%1"'
    selected = Menu.select(
        [
            MenuOption(
                ["1"],
                f"Use default arguments: {default_arguments}",
                value="default",
            ),
            MenuOption(["2"], "Rewrite command arguments", value="custom"),
        ],
        prompt="Command arguments",
        default_key="1",
        separator=False,
    )
    if selected is None:
        return None
    if selected == "default":
        return default_arguments
    arguments = Input.prompt(
        f"{FLYellow}Command arguments {FGray}[{default_arguments}]"
        f"{CRst}{FLYellow} > {CRst}",
        default=default_arguments,
    )
    if "%1" in arguments.casefold() or "%l" in arguments.casefold():
        return arguments
    print(f"{FLYellow}Warning: the command does not contain a file placeholder.{CRst}")
    confirmed = Menu.select(
        [
            MenuOption(["Y"], "Keep these arguments", value=True),
            MenuOption(["N"], "Return to the main menu", value=False),
        ],
        prompt="Continue without %1",
        default_key="N",
        inline=True,
        separator=False,
    )
    return arguments if confirmed is True else None


def _prompt_registration_scope() -> Optional[RegistryScope]:
    """Ask whether the handler should be registered per-user or machine-wide."""
    selected = Menu.select(
        [
            MenuOption(["1"], "Current user", value=RegistryScope.USER),
            MenuOption(
                ["2"],
                "Local machine (administrator elevation required)",
                value=RegistryScope.MACHINE,
            ),
        ],
        prompt="Registration scope",
        default_key="1",
        separator=False,
    )
    return selected if isinstance(selected, RegistryScope) else None


def _build_add_spec_interactively() -> Optional[AddSpec]:
    """Collect and validate all inputs for one interactive registration."""
    extension = _prompt_extension()
    method = _prompt_registration_method()
    if method is None:
        return None

    default_executable = os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"),
        "System32",
        "notepad.exe",
    )
    executable_path = Input.resolve_input_path(
        default_executable,
        prompt="Executable path",
        path_type="file",
    )
    if os.path.splitext(executable_path)[1].casefold() != ".exe":
        print(f"{FLRed}The selected application must be an .exe file.{CRst}")
        return None

    default_app_name = os.path.splitext(os.path.basename(executable_path))[0]
    app_name = Input.prompt(
        f"{FLYellow}Application name {FGray}[{default_app_name}]"
        f"{CRst}{FLYellow} > {CRst}",
        default=default_app_name,
    ).strip()
    if not app_name:
        print(f"{FLRed}Application name cannot be empty.{CRst}")
        return None
    arguments = _prompt_command_arguments()
    if arguments is None:
        return None

    app_id = re.sub(r"[^A-Za-z0-9_]+", "_", app_name).strip("_") or "Application"
    extension_id = re.sub(r"[^A-Za-z0-9_]+", "_", extension.lstrip(".")) or "file"
    progid = f"PersonalScripts.FileHandler.{app_id}.{extension_id}"
    scope = _prompt_registration_scope()
    if scope is None:
        return None
    spec = AddSpec(
        extension=extension,
        method=method,
        executable_path=executable_path,
        app_name=app_name,
        app_id=app_id,
        progid=progid,
        arguments=arguments,
        scope=scope,
    )
    _validate_add_spec(spec)
    return spec


def _print_registration_preview(spec: AddSpec) -> None:
    """Print a concise preview of a fully collected registration request."""
    print(f"\n  {FLYellow}Registration preview{CRst}")
    print(f"  {FLCyan}Extension:{CRst}   {spec.extension}")
    print(f"  {FLCyan}Method:{CRst}      {spec.method.value}")
    print(f"  {FLCyan}Application:{CRst} {spec.app_name}")
    print(f"  {FLCyan}Executable:{CRst}  {FGray}{spec.executable_path}{CRst}")
    print(f"  {FLCyan}Command:{CRst}     {_shell_command(spec)}")
    print(f"  {FLCyan}Scope:{CRst}       {spec.scope.value}")
    if spec.method is not RegistrationMethod.APPLICATION_SUPPORTED_TYPES:
        print(f"  {FLCyan}ProgID:{CRst}      {spec.progid}")


def _confirm_registration_conflicts(spec: AddSpec) -> bool:
    """Show conflicting existing values and obtain overwrite confirmation."""
    view_flag = _registration_view_flag()
    conflicts: list[tuple[RegistryWrite, RegistryValueSnapshot]] = []
    for write in _build_registration_writes(spec):
        snapshot = _snapshot_registry_value(spec.scope, view_flag, write)
        if snapshot.existed and snapshot.value != write.value:
            conflicts.append((write, snapshot))
    if not conflicts:
        return True

    print(f"\n  {FLYellow}Existing registry values would be replaced:{CRst}")
    for write, snapshot in conflicts:
        value_name = write.value_name if write.value_name else "(Default)"
        print(
            f"  {FGray}{_scope_abbreviation(spec.scope)}\\{write.path} "
            f"[{value_name}]{CRst}"
        )
        print(f"    {FLCyan}Existing:{CRst} {snapshot.value}")
        print(f"    {FLCyan}New:{CRst}      {write.value}")
    selected = Menu.select(
        [
            MenuOption(["Y"], "Replace these values", value=True),
            MenuOption(["N"], "Cancel", value=False),
        ],
        prompt="Allow replacements",
        default_key="N",
        inline=True,
        separator=False,
    )
    return selected is True


def _execute_registration(spec: AddSpec) -> bool:
    """Elevate for machine scope, apply the plan, and report its outcome."""
    if spec.scope is RegistryScope.MACHINE and not System.is_elevated():
        _restart_elevated("--apply-add-spec", _encode_add_spec(spec))
    try:
        changed_count = _apply_registration(spec)
    except PermissionError as exc:
        print(f"{FLRed}Registration permission denied:{CRst} {exc}")
        return False
    except OSError as exc:
        print(f"{FLRed}Registration failed; prior values were restored where possible:{CRst} {exc}")
        return False
    if changed_count:
        print(f"{FLGreen}Registered the file handler ({changed_count} values changed).{CRst}")
    else:
        print(f"{FLGreen}The requested file handler is already registered.{CRst}")
    print(
        f"{FGray}Windows protects the default-app choice; use Settings or Open With "
        f"to select the new handler as the default.{CRst}"
    )
    return True


def _interactive_add() -> int:
    """Run the full interactive add flow and relist the affected extension."""
    try:
        spec = _build_add_spec_interactively()
    except (PermissionError, OSError, ValueError) as exc:
        print(f"{FLRed}Cannot prepare registration:{CRst} {exc}")
        return 1
    if spec is None:
        return 0
    _print_registration_preview(spec)
    try:
        if not _confirm_registration_conflicts(spec):
            return 0
    except (PermissionError, OSError) as exc:
        print(f"{FLRed}Cannot inspect existing registry values:{CRst} {exc}")
        return 1
    confirmed = Menu.select(
        [
            MenuOption(["Y"], "Register this handler", value=True),
            MenuOption(["N"], "Cancel", value=False),
        ],
        prompt="Confirm registration",
        default_key="N",
        inline=True,
        separator=False,
    )
    if confirmed is not True:
        return 0
    if not _execute_registration(spec):
        return 1
    print()
    return _manage_extension(spec.extension)


def _interactive_action() -> Optional[str]:
    """Display the first-level feature menu and return the chosen action."""
    selected = Menu.select(
        [
            MenuOption(
                ["1", "V"],
                "View all Open With entries for a file extension",
                value="view",
            ),
            MenuOption(
                ["2", "A"],
                "Add an Open With handler",
                value="add",
            ),
        ],
        prompt="Select action",
        separator=False,
    )
    return selected if isinstance(selected, str) else None


def main(argv: Optional[list[str]] = None) -> int:
    """Run direct management, elevated re-entry, or the interactive menu."""
    parser = _build_arg_parser()
    parser.add_argument(
        "--view",
        metavar="EXTENSION",
        help="manage all registry handler entries for one extension",
    )
    parser.add_argument("--apply-delete-spec", help=argparse.SUPPRESS)
    parser.add_argument("--apply-add-spec", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    deletion_payload = (
        args.apply_delete_spec
        if isinstance(args.apply_delete_spec, str)
        else None
    )
    add_payload = (
        args.apply_add_spec
        if isinstance(args.apply_add_spec, str)
        else None
    )
    view_extension = args.view if isinstance(args.view, str) else None

    if sys.platform != "win32":
        Console.print_error_and_exit(
            f"This script only runs on Windows. Current platform: {sys.platform}"
        )

    try:
        deletion_spec = (
            _decode_deletion_spec(deletion_payload)
            if deletion_payload is not None
            else None
        )
        add_spec = (
            _decode_add_spec(add_payload)
            if add_payload is not None
            else None
        )
    except (KeyError, ValueError) as exc:
        print(f"{FLRed}Invalid elevated operation:{CRst} {exc}", file=sys.stderr)
        return 2
    if deletion_spec is not None and add_spec is not None:
        print(f"{FLRed}Only one elevated operation may be applied at a time.{CRst}")
        return 2

    if deletion_spec is not None and not System.is_elevated():
        if deletion_payload is None:
            raise RuntimeError("The validated deletion payload is missing.")
        _restart_elevated("--apply-delete-spec", deletion_payload)
    if (
        add_spec is not None
        and add_spec.scope is RegistryScope.MACHINE
        and not System.is_elevated()
    ):
        if add_payload is None:
            raise RuntimeError("The validated registration payload is missing.")
        _restart_elevated("--apply-add-spec", add_payload)

    Console.print_banner("WINDOWS FILE ASSOCIATION")
    if deletion_spec is not None:
        _execute_deletion(deletion_spec)
        print()
        return _manage_extension(deletion_spec.extension)
    if add_spec is not None:
        if not _execute_registration(add_spec):
            return 1
        print()
        return _manage_extension(add_spec.extension)

    if view_extension is not None:
        return _manage_extension(view_extension)

    while True:
        action = _interactive_action()
        if action is None:
            Console.print_exit_message("Bye.")
            return 0
        if action == "add":
            _interactive_add()
        else:
            _manage_extension(_prompt_extension())
        print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
