"""Enumerate Windows regional settings and launch a selected executable."""

from __future__ import annotations

import _winapi
import ctypes as c
from ctypes import wintypes as w
from dataclasses import dataclass
import os
from pathlib import Path
import struct
import subprocess
import sys
import winreg

from utils._windows_elevation import start_elevated_executable

PREFERRED_REGIONS = ("zh-CN", "zh-TW", "ko-KR", "ja-JP")
EXECUTABLE_SUFFIXES = {".exe", ".com"}
CODE_PAGES = {
    936: "Simplified Chinese (GBK)", 950: "Traditional Chinese (Big5)",
    949: "Korean (UHC)", 932: "Japanese (Windows Shift-JIS)", 65001: "UTF-8",
    874: "Thai", 1250: "Central European", 1251: "Cyrillic",
    1252: "Western European", 1253: "Greek", 1254: "Turkish", 1255: "Hebrew",
    1256: "Arabic", 1257: "Baltic", 1258: "Vietnamese",
}
TIME_ZONES = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Time Zones"
kernel = c.WinDLL("kernel32", use_last_error=True)


@dataclass(frozen=True)
class Selection:
    """Empty strings and code page zero delegate the corresponding setting to Windows."""

    region: str = ""
    code_page: int = 0
    ui_language: str = ""
    time_zone: str = ""


@dataclass(frozen=True)
class HostSettings:
    """User and system defaults can differ on the same Windows installation."""

    user_region: str
    system_region: str
    ansi_page: int
    oem_page: int
    user_language: str
    system_language: str
    time_zone: str


def locale_name(lcid: int) -> str:
    """Return the Windows locale name for a language or locale ID."""
    name = c.create_unicode_buffer(85)
    if not kernel.LCIDToLocaleName(lcid, name, len(name), 0):
        raise c.WinError(c.get_last_error())
    return name.value


def locales() -> list[tuple[str, str]]:
    """List Windows specific locales, placing the preferred CJK regions first."""
    names: list[str] = []
    callback_type = c.WINFUNCTYPE(w.BOOL, w.LPWSTR, w.DWORD, w.LPARAM)

    @callback_type
    def collect(name: str, flags: int, parameter: int) -> bool:
        names.append(name)
        return True

    if not kernel.EnumSystemLocalesEx(collect, 0x20, 0, None):  # LOCALE_SPECIFICDATA
        raise c.WinError(c.get_last_error())
    choices = []
    for name in names:
        display = c.create_unicode_buffer(256)
        kernel.GetLocaleInfoEx(name, 0x72, display, len(display))  # English display name
        choices.append((f"{display.value or name} [{name}]", name))
    order = {name: index for index, name in enumerate(PREFERRED_REGIONS)}
    return sorted(choices, key=lambda item: (order.get(item[1], len(order)), item[0]))


class _CodePageInfo(c.Structure):
    _fields_ = [
        ("width", w.UINT), ("default", w.BYTE * 2), ("lead", w.BYTE * 12),
        ("unicode_default", w.WCHAR), ("page", w.UINT), ("name", w.WCHAR * 260),
    ]


def code_pages() -> list[tuple[str, str]]:
    """List installed legacy one/two-byte pages and UTF-8 in the requested order."""
    available: dict[int, str] = {}
    callback_type = c.WINFUNCTYPE(w.BOOL, w.LPWSTR)

    @callback_type
    def collect(text: str) -> bool:
        page = int(text)
        info = _CodePageInfo()
        if kernel.GetCPInfoExW(page, 0, c.byref(info)) and (info.width <= 2 or page == 65001):
            available[page] = info.name
        return True

    if not kernel.EnumSystemCodePagesW(collect, 1):  # CP_INSTALLED
        raise c.WinError(c.get_last_error())
    preferred = [(f"{name} · {page}", str(page))
                 for page, name in CODE_PAGES.items() if page in available]
    return preferred + [(available[page], str(page)) for page in sorted(available.keys() - CODE_PAGES.keys())]


def time_zones() -> list[tuple[str, str]]:
    """Return display labels and stable Windows time zone keys."""
    zones = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, TIME_ZONES) as root:
        for index in range(winreg.QueryInfoKey(root)[0]):
            key = winreg.EnumKey(root, index)
            with winreg.OpenKey(root, key) as zone:
                label = winreg.QueryValueEx(zone, "Display")[0]
                bias = struct.unpack_from("<i", winreg.QueryValueEx(zone, "TZI")[0])[0]
            zones.append((-bias, str(label), key))
    return [(label, key) for _, label, key in sorted(zones)]


class _SystemTime(c.Structure):
    _fields_ = [(name, w.WORD) for name in
                ("year", "month", "weekday", "day", "hour", "minute", "second", "millis")]


class _DynamicZone(c.Structure):
    _fields_ = [
        ("bias", w.LONG), ("standard", w.WCHAR * 32), ("standard_date", _SystemTime),
        ("standard_bias", w.LONG), ("daylight", w.WCHAR * 32), ("daylight_date", _SystemTime),
        ("daylight_bias", w.LONG), ("key", w.WCHAR * 128), ("disabled", c.c_ubyte),
    ]


def host_settings() -> HostSettings:
    """Read user and system locales, system code pages, UI languages and active zone."""
    name = c.create_unicode_buffer(85)
    system = c.create_unicode_buffer(85)
    zone = _DynamicZone()
    if not kernel.GetUserDefaultLocaleName(name, len(name)) or not kernel.GetSystemDefaultLocaleName(system, len(system)):
        raise c.WinError(c.get_last_error())
    if kernel.GetDynamicTimeZoneInformation(c.byref(zone)) == -1:
        raise c.WinError(c.get_last_error())
    # A packaged interpreter can opt into UTF-8 independently of the system ACP.
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Nls\CodePage") as key:
        ansi_page = int(winreg.QueryValueEx(key, "ACP")[0])
        oem_page = int(winreg.QueryValueEx(key, "OEMCP")[0])
    return HostSettings(name.value, system.value, ansi_page, oem_page,
                        locale_name(kernel.GetUserDefaultUILanguage()),
                        locale_name(kernel.GetSystemDefaultUILanguage()), zone.key or zone.standard)


def native_machine(target: Path) -> str:
    """Read the PE machine type used to select the matching locale runtime."""
    with target.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("The selected file is not a Windows executable.")
        stream.seek(60)
        offset = stream.read(4)
        if len(offset) == 4:
            stream.seek(int.from_bytes(offset, "little"))
            if stream.read(4) == b"PE\0\0":
                machine = int.from_bytes(stream.read(2), "little")
                if machine in (0x14C, 0x8664):
                    return "x86" if machine == 0x14C else "x64"
    raise ValueError("Locale overrides require a native x86 or x64 Windows executable.")


def launch(target: Path, settings: Selection, administrator: bool, arguments: str = "",
           working_directory: Path | None = None) -> None:
    """Start the executable in the given directory with the Windows command-line tail verbatim."""
    if target.suffix.lower() not in EXECUTABLE_SUFFIXES or not target.is_file():
        raise ValueError("Select an existing .exe or .com file.")
    target = target.resolve()
    target_cwd = os.path.abspath(working_directory or Path.cwd())
    if not os.path.isdir(target_cwd):
        raise ValueError(f"Select an existing working directory: {target_cwd}")
    program = target
    program_cwd = target_cwd
    parameters = arguments
    if settings != Selection():
        bundled = getattr(sys, "frozen", False) or "__compiled__" in globals()
        directory = (Path(sys.executable).parent / "locale-runtime" if bundled
                     else Path(__file__).resolve().parent / "bin")
        runtime = directory / native_machine(target)
        helper = runtime / "locale-start.exe"
        if not helper.is_file() or not (runtime / "locale-settings.dll").is_file():
            raise FileNotFoundError(f"Missing locale runtime in {runtime}. See locale_launcher/README.md.")
        program = helper
        program_cwd = str(helper.parent)
        # Keep the target directory separate from the verbatim argument tail and helper directory.
        fields = [str(target), settings.region, str(settings.code_page), settings.ui_language,
                  settings.time_zone, arguments, target_cwd]
        parameters = subprocess.list2cmdline(fields)
    if administrator:
        start_elevated_executable(str(program), parameters, program_cwd)
    else:
        command_line = f'"{program}"'
        if parameters:
            command_line += " " + parameters
        # The GUI only needs the creation result. Release both handles without waiting for the target.
        process, thread, _, _ = _winapi.CreateProcess(
            str(program), command_line, None, None, False, subprocess.CREATE_NEW_CONSOLE,
            dict(os.environ), program_cwd, subprocess.STARTUPINFO(),
        )
        _winapi.CloseHandle(thread)
        _winapi.CloseHandle(process)
