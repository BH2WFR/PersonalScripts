#!/usr/bin/env python3
import sys
import os
import ctypes
import plistlib
import re
import shutil
import subprocess
import tempfile
import time
import glob
import urllib.parse
from typing import Any, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import *

# macOS 显示器工具：旋转 / 亮度 / toggle 内建显示器

#============ 系统检查 ===========
if sys.platform != "darwin":
    print(f"{FLRed}ERROR: This script only runs on macOS. Current platform: {sys.platform}{CRst}\n")
    sys.exit(1)

if os.uname().machine != "arm64":
    print(f"{FLRed}ERROR: This script only runs on Apple Silicon Macs.{CRst}")
    print(f"{FLRed}       Current architecture: {os.uname().machine}{CRst}\n")
    sys.exit(1)

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
{FLYellow}SCREEN UTILS{CRst}
============

Usage:
  python {script_name}                    interactive display manager
  python {script_name} --list             list displays and exit
  python {script_name} --ddc-ci-info      show DDC/CI info and exit
  python {script_name} --toggle-built-in  toggle built-in display and exit
  python {script_name} --help             show this help

{FLYellow}Description:{CRst}
  macOS display management tool for Apple Silicon.
  Supports screen rotation, brightness control (built-in via
  DisplayServices, external via DDC/CI), resolution switching, and
  persistent external-display RGB output overrides.
  Highlight: toggle the MacBook built-in display on/off when external
  monitors are connected — refuses to disable if no external display
  is active, and auto-restores brightness when re-enabling.

{FLYellow}CLI options:{CRst}
  --list, --list-only       print display list and exit
  --info, --ddc-ci-info     dump DDC/CI capabilities and exit
  --toggle, --toggle-built-in
                            toggle built-in display on/off and exit

{FLYellow}Interactive menu:{CRst}
  [L] List displays    [R] Rotate (0/90/180/270)
  [S] Set resolution   [B] Brightness
  [D] DDC/CI info      [C] Color modes
  [F] RGB override     [T] Toggle built-in
  [Q] Quit

{FLYellow}Requirements:{CRst}
  macOS on Apple Silicon. Uses CoreGraphics / DisplayServices / IOKit (built-in).
  Optional PyObjC for NSScreen info: {FGray}pip install pyobjc{CRst}
""")
    sys.exit(0)

#============ 加载 API ===========
libc = ctypes.CDLL('/usr/lib/libSystem.dylib')
libc.dlopen.argtypes = [ctypes.c_char_p, ctypes.c_int]
libc.dlopen.restype = ctypes.c_void_p
libc.dlsym.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
libc.dlsym.restype = ctypes.c_void_p

_cgs_handle = libc.dlopen(
    b'/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics', 1)
if not _cgs_handle:
    print(f"{FLRed}ERROR: Cannot load CoreGraphics framework.{CRst}\n")
    sys.exit(1)

_RTLD_DEFAULT = -2

def _lookup(name: str):
    name_bytes = name.encode()
    ptr = libc.dlsym(_cgs_handle, name_bytes)
    if not ptr:
        ptr = libc.dlsym(_RTLD_DEFAULT, name_bytes)
    if not ptr:
        print(f"{FLRed}ERROR: symbol `{name}` not found.{CRst}\n")
        sys.exit(1)
    return ptr

def _lookup_optional(name: str, handles: Optional[list[int]] = None):
    name_bytes = name.encode()
    for handle in handles or [_cgs_handle, _RTLD_DEFAULT]:
        if not handle:
            continue
        ptr = libc.dlsym(handle, name_bytes)
        if ptr:
            return ptr
    return 0

# --- Display enumeration ---
_CGSGetDisplayList_ptr = _lookup_optional('CGSGetDisplayList')
CGSGetDisplayList = (
    ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
    )(_CGSGetDisplayList_ptr) if _CGSGetDisplayList_ptr else None
)
_CGGetOnlineDisplayList_ptr = _lookup_optional('CGGetOnlineDisplayList')
CGGetOnlineDisplayList = (
    ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
    )(_CGGetOnlineDisplayList_ptr) if _CGGetOnlineDisplayList_ptr else None
)

CGGetActiveDisplayList = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
)(_lookup('CGGetActiveDisplayList'))

CGDisplayIsBuiltin = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_uint32)(
    _lookup('CGDisplayIsBuiltin'))
CGDisplayPixelsWide = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.c_uint32)(
    _lookup('CGDisplayPixelsWide'))
CGDisplayPixelsHigh = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.c_uint32)(
    _lookup('CGDisplayPixelsHigh'))
CGDisplayRotation = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_uint32)(
    _lookup('CGDisplayRotation'))
CGDisplayModelNumber = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_uint32)(
    _lookup('CGDisplayModelNumber'))
CGDisplayVendorNumber = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_uint32)(
    _lookup('CGDisplayVendorNumber'))
CGDisplaySerialNumber = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_uint32)(
    _lookup('CGDisplaySerialNumber'))

# --- Config transaction (toggle built-in) ---
CGBeginDisplayConfiguration = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.POINTER(ctypes.c_void_p),
)(_lookup('CGBeginDisplayConfiguration'))
_CGSConfigureDisplayEnabled_ptr = _lookup_optional('CGSConfigureDisplayEnabled')
CGSConfigureDisplayEnabled = (
    ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_bool,
    )(_CGSConfigureDisplayEnabled_ptr) if _CGSConfigureDisplayEnabled_ptr else None
)
_CGSCompleteDisplayConfiguration_ptr = _lookup_optional('CGSCompleteDisplayConfiguration')
CGSCompleteDisplayConfiguration = (
    ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p,
    )(_CGSCompleteDisplayConfiguration_ptr) if _CGSCompleteDisplayConfiguration_ptr else None
)
CGConfigureDisplayWithDisplayMode = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p,
)(_lookup('CGConfigureDisplayWithDisplayMode'))
CGCompleteDisplayConfiguration = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_int32,
)(_lookup('CGCompleteDisplayConfiguration'))
CGCancelDisplayConfiguration = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p,
)(_lookup('CGCancelDisplayConfiguration'))

# --- Rotation ---
_SLSSetDisplayRotation_ptr = _lookup_optional('SLSSetDisplayRotation')
SLSSetDisplayRotation = (
    ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_uint32, ctypes.c_double,
    )(_SLSSetDisplayRotation_ptr) if _SLSSetDisplayRotation_ptr else None
)

# --- Rotation via MonitorPanel private framework ---
_objc_handle = libc.dlopen(b'/usr/lib/libobjc.A.dylib', 1)
_mp_handle = libc.dlopen(
    b'/System/Library/PrivateFrameworks/MonitorPanel.framework/MonitorPanel', 1)

def _objc_lookup(name: str):
    for handle in [_objc_handle, _mp_handle, _RTLD_DEFAULT]:
        ptr = libc.dlsym(handle, name.encode())
        if ptr:
            return ptr
    return 0

_objc_getClass_ptr = _objc_lookup('objc_getClass')
_sel_registerName_ptr = _objc_lookup('sel_registerName')
_objc_msgSend_ptr = _objc_lookup('objc_msgSend')

objc_getClass = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_char_p,
)(_objc_getClass_ptr) if _objc_getClass_ptr else None
sel_registerName = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_char_p,
)(_sel_registerName_ptr) if _sel_registerName_ptr else None

# --- Brightness (DisplayServices, works on Apple Silicon) ---
_ds_handle = libc.dlopen(
    b'/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices', 1)

def _ds_lookup(name: str):
    ptr = libc.dlsym(_ds_handle, name.encode()) if _ds_handle else 0
    if not ptr:
        ptr = libc.dlsym(_RTLD_DEFAULT, name.encode())
    if not ptr:
        print(f"{FLRed}ERROR: symbol `{name}` not found.{CRst}\n")
        sys.exit(1)
    return ptr

def _ds_lookup_optional(name: str):
    return _lookup_optional(name, [_ds_handle, _RTLD_DEFAULT])

_DSGetDisplayBrightness_ptr = _ds_lookup_optional('DisplayServicesGetBrightness')
DSGetDisplayBrightness = (
    ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_float),
    )(_DSGetDisplayBrightness_ptr) if _DSGetDisplayBrightness_ptr else None
)
_DSSetDisplayBrightness_ptr = _ds_lookup_optional('DisplayServicesSetBrightness')
DSSetDisplayBrightness = (
    ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_uint32, ctypes.c_float,
    )(_DSSetDisplayBrightness_ptr) if _DSSetDisplayBrightness_ptr else None
)

# --- DDC/CI (external display brightness via IOKit) ---
_iokit_handle = libc.dlopen(
    b'/System/Library/Frameworks/IOKit.framework/IOKit', 1)
_cf_handle = libc.dlopen(
    b'/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation', 1)
_cd_handle = libc.dlopen(
    b'/System/Library/PrivateFrameworks/CoreDisplay.framework/CoreDisplay', 1)

def _io_lookup(name: str):
    for handle in [_iokit_handle, _cd_handle, _cf_handle, _cgs_handle, _RTLD_DEFAULT]:
        ptr = libc.dlsym(handle, name.encode())
        if ptr:
            return ptr
    print(f"{FLRed}ERROR: symbol `{name}` not found.{CRst}\n")
    sys.exit(1)

def _io_lookup_optional(name: str):
    return _lookup_optional(name, [_iokit_handle, _cd_handle, _cf_handle, _cgs_handle, _RTLD_DEFAULT])

IOServiceGetMatchingServices = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
)(_io_lookup('IOServiceGetMatchingServices'))
IOServiceMatching = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_char_p,
)(_io_lookup('IOServiceMatching'))
IOIteratorNext = ctypes.CFUNCTYPE(
    ctypes.c_uint32, ctypes.c_uint32,
)(_io_lookup('IOIteratorNext'))
IOObjectRelease = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_uint32,
)(_io_lookup('IOObjectRelease'))
IORegistryEntryGetPath = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p,
)(_io_lookup('IORegistryEntryGetPath'))
IORegistryGetRootEntry = ctypes.CFUNCTYPE(
    ctypes.c_uint32, ctypes.c_uint32,
)(_io_lookup('IORegistryGetRootEntry'))
IORegistryEntryCreateIterator = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32),
)(_io_lookup('IORegistryEntryCreateIterator'))
IORegistryEntryGetName = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_uint32, ctypes.c_char_p,
)(_io_lookup('IORegistryEntryGetName'))
_IOAVServiceCreateWithService_ptr = _io_lookup_optional('IOAVServiceCreateWithService')
IOAVServiceCreateWithService = (
    ctypes.CFUNCTYPE(
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
    )(_IOAVServiceCreateWithService_ptr) if _IOAVServiceCreateWithService_ptr else None
)
_IOAVServiceReadI2C_ptr = _io_lookup_optional('IOAVServiceReadI2C')
IOAVServiceReadI2C = (
    ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32,
    )(_IOAVServiceReadI2C_ptr) if _IOAVServiceReadI2C_ptr else None
)
_IOAVServiceWriteI2C_ptr = _io_lookup_optional('IOAVServiceWriteI2C')
IOAVServiceWriteI2C = (
    ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32,
    )(_IOAVServiceWriteI2C_ptr) if _IOAVServiceWriteI2C_ptr else None
)
_CoreDisplayCreateInfoDict_ptr = _io_lookup_optional('CoreDisplay_DisplayCreateInfoDictionary')
CoreDisplayCreateInfoDict = (
    ctypes.CFUNCTYPE(
        ctypes.c_void_p, ctypes.c_uint32,
    )(_CoreDisplayCreateInfoDict_ptr) if _CoreDisplayCreateInfoDict_ptr else None
)
IORegistryEntryCreateCFProperty = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
)(_io_lookup('IORegistryEntryCreateCFProperty'))

# CF helpers for reading CoreFoundation types
_CFStringCreateWithCString = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32,
)(_io_lookup('CFStringCreateWithCString'))
_CFStringGetCString = ctypes.CFUNCTYPE(
    ctypes.c_bool, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32,
)(_io_lookup('CFStringGetCString'))
_CFDictionaryGetValue = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
)(_io_lookup('CFDictionaryGetValue'))
_CFDictionaryGetCount = ctypes.CFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p,
)(_io_lookup('CFDictionaryGetCount'))
_CFDictionaryGetKeysAndValues = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
)(_io_lookup('CFDictionaryGetKeysAndValues'))
_CFNumberGetValue = ctypes.CFUNCTYPE(
    ctypes.c_bool, ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p,
)(_io_lookup('CFNumberGetValue'))
_CFGetTypeID = ctypes.CFUNCTYPE(
    ctypes.c_ulong, ctypes.c_void_p,
)(_io_lookup('CFGetTypeID'))
_CFStringGetTypeID = ctypes.CFUNCTYPE(
    ctypes.c_ulong,
)(_io_lookup('CFStringGetTypeID'))
_CFDictionaryGetTypeID = ctypes.CFUNCTYPE(
    ctypes.c_ulong,
)(_io_lookup('CFDictionaryGetTypeID'))
_CFDataGetLength = ctypes.CFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p,
)(_io_lookup('CFDataGetLength'))
_CFDataGetBytePtr = ctypes.CFUNCTYPE(
    ctypes.POINTER(ctypes.c_uint8), ctypes.c_void_p,
)(_io_lookup('CFDataGetBytePtr'))
_CFDataGetTypeID = ctypes.CFUNCTYPE(
    ctypes.c_ulong,
)(_io_lookup('CFDataGetTypeID'))
_CFArrayGetCount = ctypes.CFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p,
)(_io_lookup('CFArrayGetCount'))
_CFArrayGetValueAtIndex = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long,
)(_io_lookup('CFArrayGetValueAtIndex'))
_CFDictionaryCreate = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
    ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p,
)(_io_lookup('CFDictionaryCreate'))
_CFURLGetTypeID = ctypes.CFUNCTYPE(
    ctypes.c_ulong,
)(_io_lookup('CFURLGetTypeID'))
_CFURLGetString = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_void_p,
)(_io_lookup('CFURLGetString'))

_colorsync_handle = libc.dlopen(
    b'/System/Library/Frameworks/ColorSync.framework/ColorSync', 1)

def _optional_symbol(handle, name: str):
    ptr = libc.dlsym(handle, name.encode()) if handle else 0
    if not ptr:
        ptr = libc.dlsym(_RTLD_DEFAULT, name.encode())
    return ptr

_CGDisplayCreateUUIDFromDisplayID_ptr = _optional_symbol(
    _cgs_handle, 'CGDisplayCreateUUIDFromDisplayID')
CGDisplayCreateUUIDFromDisplayID = (
    ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_uint32)(_CGDisplayCreateUUIDFromDisplayID_ptr)
    if _CGDisplayCreateUUIDFromDisplayID_ptr else None
)
_ColorSyncDeviceCopyDeviceInfo_ptr = _optional_symbol(
    _colorsync_handle, 'ColorSyncDeviceCopyDeviceInfo')
ColorSyncDeviceCopyDeviceInfo = (
    ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(_ColorSyncDeviceCopyDeviceInfo_ptr)
    if _ColorSyncDeviceCopyDeviceInfo_ptr else None
)

def _colorsync_constant(name: str) -> int:
    if not _colorsync_handle:
        return 0
    try:
        return ctypes.c_void_p.in_dll(
            ctypes.CDLL('/System/Library/Frameworks/ColorSync.framework/ColorSync'),
            name,
        ).value or 0
    except Exception:
        return 0

try:
    _cg_lib = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    _cf_lib = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    _kCGDisplayShowDuplicateLowResolutionModes = ctypes.c_void_p.in_dll(
        _cg_lib, 'kCGDisplayShowDuplicateLowResolutionModes').value
    _kCFBooleanTrue = ctypes.c_void_p.in_dll(_cf_lib, 'kCFBooleanTrue').value
except Exception:
    _kCGDisplayShowDuplicateLowResolutionModes = 0
    _kCFBooleanTrue = 0

def _cfstr(s: str):
    """Create a CFString from a Python string."""
    return _CFStringCreateWithCString(0, s.encode(), 0x08000100)

def _cfstring_to_py(cf) -> Optional[str]:
    """Convert a CFString to a Python string."""
    buf = ctypes.create_string_buffer(1024)
    if _CFStringGetCString(cf, buf, 1024, 0x08000100):
        return buf.value.decode()
    return None

def _cfdict_get_int(d, key) -> Optional[int]:
    """Get an integer value from a CFDictionary by CFString key."""
    v = _CFDictionaryGetValue(d, key)
    if not v:
        return None
    num = ctypes.c_int64(0)
    if _CFNumberGetValue(v, 10, ctypes.byref(num)):
        return num.value
    return None

def _cfdict_get_str(d, key: str) -> Optional[str]:
    """Get a string value from a CFDictionary (supports localized dicts)."""
    v = _CFDictionaryGetValue(d, _cfstr(key))
    if not v:
        return None
    # Check type to avoid crashing CFStringGetCString on non-strings
    if _CFGetTypeID(v) == _CFStringGetTypeID():
        return _cfstring_to_py(v)
    # If it's a localized dictionary, try en_US
    if _CFGetTypeID(v) != _CFDictionaryGetTypeID():
        return None
    en = _CFDictionaryGetValue(v, _cfstr("en_US"))
    if en:
        return _cfstring_to_py(en)
    return None

def _cfdata_to_bytes(cf) -> Optional[bytes]:
    """Convert a CFData object to Python bytes."""
    if not cf:
        return None
    if _CFGetTypeID(cf) != _CFDataGetTypeID():
        return None
    length = _CFDataGetLength(cf)
    ptr = _CFDataGetBytePtr(cf)
    if length <= 0 or not ptr:
        return None
    return bytes(ptr[i] for i in range(length))

def _cfurl_to_py(cf) -> Optional[str]:
    """Convert a CFURL/CFString URL value to a Python string."""
    if not cf:
        return None
    if _CFGetTypeID(cf) == _CFStringGetTypeID():
        return _cfstring_to_py(cf)
    if _CFGetTypeID(cf) == _CFURLGetTypeID():
        url_str = _CFURLGetString(cf)
        return _cfstring_to_py(url_str) if url_str else None
    return None

def _cfdict_get_data(d, key: str) -> Optional[bytes]:
    """Get bytes from a CFDictionary by CFString key."""
    if not d:
        return None
    v = _CFDictionaryGetValue(d, _cfstr(key))
    return _cfdata_to_bytes(v) if v else None

def _cfdict_get_by_cfkey(d, key_ptr: int):
    """Get a raw CFDictionary value by an exported CFString key constant."""
    if not d or not key_ptr:
        return None
    return _CFDictionaryGetValue(d, ctypes.c_void_p(key_ptr))

def _ioreg_cf_property(entry: int, key: str, recursive: bool = True):
    """Read a CF property from an IORegistry entry."""
    return IORegistryEntryCreateCFProperty(entry, _cfstr(key), 0, 1 if recursive else 0)

def _ioreg_get_name(entry: int) -> Optional[str]:
    """Get IORegistry entry name."""
    buf = ctypes.create_string_buffer(128)
    if IORegistryEntryGetName(entry, buf) == 0:
        return buf.value.decode(errors="replace")
    return None

def _ioreg_get_path(entry: int) -> str:
    """Get IORegistry service-plane path."""
    buf = ctypes.create_string_buffer(1024)
    if IORegistryEntryGetPath(entry, b"IOService", buf) == 0:
        return buf.value.decode(errors="replace")
    return ""

# DDC/CI constants
_DDC_7BIT_ADDR = 0x37
_DDC_DATA_ADDR = 0x51
_DDC_BRIGHTNESS_CMD = 0x10
_DDC_DEFAULT_MAX = 100
_DDC_DEBUG = False  # Set to True to trace raw DDC packets

DDC_DUMP_COMMANDS = [
    (0x10, "Brightness / luminance"),
    (0x12, "Contrast"),
    (0x13, "Backlight control legacy"),
    (0x14, "Color preset"),
    (0x52, "Active control"),
    (0x60, "Input select"),
    (0x62, "Audio speaker volume"),
    (0x6B, "Backlight level white"),
    (0x8D, "Audio mute / screen blank"),
    (0xAC, "Horizontal frequency"),
    (0xAE, "Vertical frequency"),
    (0xB6, "Display technology type"),
    (0xC0, "Display usage time"),
    (0xC8, "Display controller ID"),
    (0xC9, "Display firmware level"),
    (0xCC, "OSD language"),
    (0xD6, "Power mode"),
    (0xDF, "VCP version"),
]

def _ddc_checksum(chk: int, data: list[int]) -> int:
    for b in data:
        chk ^= b
    return chk & 0xFF

def _ddc_parse_reply(reply: list[int], command: int) -> Optional[Tuple[int, int]]:
    """Parse a standard DDC/CI VCP reply."""
    if len(reply) >= 11 and _ddc_checksum(0x50, reply[:10]) == reply[10]:
        if reply[2] == 0x02 and reply[4] == command:
            current = reply[8] * 256 + reply[9]
            maximum = reply[6] * 256 + reply[7]
            if 0 < maximum and 0 <= current <= maximum:
                return current, maximum

    return None

def _ddc_read(service, command: int) -> Optional[Tuple[int, int]]:
    """Read DDC/CI value. Returns (current, max) or None on failure."""
    if not (IOAVServiceReadI2C and IOAVServiceWriteI2C):
        return None
    send = [command]
    reply = [0] * 11
    # Packet: [addr_byte, length, ...data, checksum]
    packet = [0x80 | (len(send) + 1), len(send)] + send + [0]
    # Read (send.count==1): checksum starts from 7-bit addr << 1
    packet[-1] = _ddc_checksum(_DDC_7BIT_ADDR << 1, packet[:-1])
    packet_arr = (ctypes.c_uint8 * len(packet))(*packet)
    reply_arr = (ctypes.c_uint8 * len(reply))()

    for attempt in range(5):
        for _ in range(2):  # 2 write cycles, matching MonitorControl
            time.sleep(0.01)
            IOAVServiceWriteI2C(service, _DDC_7BIT_ADDR, _DDC_DATA_ADDR,
                                packet_arr, len(packet))
        time.sleep(0.05)
        err = IOAVServiceReadI2C(service, _DDC_7BIT_ADDR, 0, reply_arr, len(reply))
        if _DDC_DEBUG:
            r = list(reply_arr)
            print(f"  {FGray}DDC read attempt {attempt+1}/5: err={err}, "
                  f"reply={' '.join(f'{b:02X}' for b in r)}"
                  f"{', csum ok' if err==0 and _ddc_checksum(0x50, r[:-1])==r[-1] else ''}{CRst}")
        if err == 0:
            r = list(reply_arr)
            parsed = _ddc_parse_reply(r, command)
            if parsed:
                return parsed
        time.sleep(0.02)
    return None

def _ddc_raw_read(service, command: int, reply_len: int = 32) -> Tuple[int, list[int], Optional[Tuple[int, int]]]:
    """Read one raw DDC/CI VCP reply for diagnostics."""
    if not (IOAVServiceReadI2C and IOAVServiceWriteI2C):
        return -1, [], None
    send = [command]
    packet = [0x80 | (len(send) + 1), len(send)] + send + [0]
    packet[-1] = _ddc_checksum(_DDC_7BIT_ADDR << 1, packet[:-1])
    packet_arr = (ctypes.c_uint8 * len(packet))(*packet)
    reply_arr = (ctypes.c_uint8 * reply_len)()

    for _ in range(2):
        time.sleep(0.01)
        IOAVServiceWriteI2C(service, _DDC_7BIT_ADDR, _DDC_DATA_ADDR,
                            packet_arr, len(packet))
    time.sleep(0.05)

    err = IOAVServiceReadI2C(service, _DDC_7BIT_ADDR, 0, reply_arr, reply_len)
    reply = list(reply_arr)
    return err, reply, _ddc_parse_reply(reply[:11], command) if err == 0 else None

def _ddc_write(service, command: int, value: int) -> bool:
    """Write DDC/CI value. Returns True on success."""
    if not IOAVServiceWriteI2C:
        return False
    send = [command, (value >> 8) & 0xFF, value & 0xFF]
    packet = [0x80 | (len(send) + 1), len(send)] + send + [0]
    # Write (send.count>1): checksum starts from 7-bit addr << 1 ^ data addr
    # This matches MonitorControl's Arm64DDC.swift
    packet[-1] = _ddc_checksum(_DDC_7BIT_ADDR << 1 ^ _DDC_DATA_ADDR, packet[:-1])
    packet_arr = (ctypes.c_uint8 * len(packet))(*packet)

    for _ in range(5):
        for _ in range(2):
            time.sleep(0.01)
            if IOAVServiceWriteI2C(service, _DDC_7BIT_ADDR, _DDC_DATA_ADDR,
                                    packet_arr, len(packet)) == 0:
                return True
        time.sleep(0.02)
    return False

def _ddc_service_match_score(did: int, svc_info: dict) -> int:
    """Score an IORegistry DDC candidate against a CoreGraphics display."""
    score = 0
    edid = svc_info.get("edid_uuid") or ""
    if not CoreDisplayCreateInfoDict:
        return score
    display_info = CoreDisplayCreateInfoDict(did)
    if not display_info:
        return score

    vendor = _cfdict_get_int(display_info, _cfstr("DisplayVendorID"))
    product = _cfdict_get_int(display_info, _cfstr("DisplayProductID"))
    week = _cfdict_get_int(display_info, _cfstr("DisplayWeekOfManufacture"))
    year = _cfdict_get_int(display_info, _cfstr("DisplayYearOfManufacture"))
    h_size = _cfdict_get_int(display_info, _cfstr("DisplayHorizontalImageSize"))
    v_size = _cfdict_get_int(display_info, _cfstr("DisplayVerticalImageSize"))

    search_keys: list[tuple[str, int]] = []
    if vendor:
        search_keys.append((f"{vendor & 0xFFFF:04X}", 0))
    if product:
        search_keys.append((f"{product & 0xFF:02X}{(product >> 8) & 0xFF:02X}", 4))
    if week is not None and year is not None:
        search_keys.append((f"{week & 0xFF:02X}{max(0, year - 1990) & 0xFF:02X}", 19))
    if h_size is not None and v_size is not None:
        search_keys.append((f"{int(h_size / 10) & 0xFF:02X}{int(v_size / 10) & 0xFF:02X}", 30))

    for key, loc in search_keys:
        if key != "0000" and len(edid) >= loc + 4 and edid[loc:loc + 4].upper() == key:
            score += 1

    location = svc_info.get("io_display_location") or ""
    display_location = _cfdict_get_str(display_info, "IODisplayLocation")
    if location and display_location and location == display_location:
        score += 10

    product_name = svc_info.get("product_name") or ""
    display_name = _cfdict_get_str(display_info, "DisplayProductName") or ""
    if product_name and display_name and product_name.lower() == display_name.lower():
        score += 1

    serial = svc_info.get("serial_number") or 0
    display_serial = _cfdict_get_int(display_info, _cfstr("DisplaySerialNumber"))
    if serial and display_serial and serial == display_serial:
        score += 1

    return score

def _ioreg_next_object_of_interest(iterator: ctypes.c_uint32, interests: list[str]):
    """Mirror MonitorControl's recursive IORegistry scan order."""
    while True:
        entry = IOIteratorNext(iterator.value)
        if entry == 0:
            return None
        name = _ioreg_get_name(entry)
        if not name:
            IOObjectRelease(entry)
            continue
        for interest in interests:
            if interest in name:
                return name, entry
        IOObjectRelease(entry)

def _ioreg_framebuffer_info(entry: int, service_location: int) -> dict:
    display_attrs = _ioreg_cf_property(entry, "DisplayAttributes")
    product_attrs = _CFDictionaryGetValue(display_attrs, _cfstr("ProductAttributes")) if display_attrs else 0

    edid = _ioreg_cf_property(entry, "EDID UUID")
    return {
        "edid_uuid": _cfstring_to_py(edid) if edid else "",
        "io_display_location": _ioreg_get_path(entry),
        "product_name": _cfdict_get_str(product_attrs, "ProductName") if product_attrs else "",
        "serial_number": _cfdict_get_int(product_attrs, _cfstr("SerialNumber")) if product_attrs else 0,
        "service": None,
        "service_location": service_location,
    }

def _ioreg_attach_dcp_service(entry: int, svc_info: dict) -> None:
    if not IOAVServiceCreateWithService:
        return
    location = _ioreg_cf_property(entry, "Location")
    location_str = _cfstring_to_py(location) if location else ""
    if location_str == "External":
        svc_info["service"] = IOAVServiceCreateWithService(0, entry)

def _get_ioreg_services_for_matching() -> list[dict]:
    """Collect framebuffer/DDC service pairs using MonitorControl's IORegistry order."""
    root = IORegistryGetRootEntry(0)
    if not root:
        return []

    iterator = ctypes.c_uint32(0)
    services: list[dict] = []
    current_info: Optional[dict] = None
    service_location = 0
    keys_framebuffer = ["AppleCLCD2", "IOMobileFramebufferShim"]
    interests = ["DCPAVServiceProxy"] + keys_framebuffer

    try:
        if IORegistryEntryCreateIterator(root, b"IOService", 1, ctypes.byref(iterator)) != 0:
            return []

        while True:
            item = _ioreg_next_object_of_interest(iterator, interests)
            if not item:
                break
            name, entry = item
            try:
                if name in keys_framebuffer:
                    service_location += 1
                    current_info = _ioreg_framebuffer_info(entry, service_location)
                elif name == "DCPAVServiceProxy" and current_info is not None:
                    _ioreg_attach_dcp_service(entry, current_info)
                    services.append(current_info)
            finally:
                IOObjectRelease(entry)
    finally:
        if iterator.value:
            IOObjectRelease(iterator.value)
        IOObjectRelease(root)

    return services

def _match_ddc_services(displays: list[int]) -> dict[int, Any]:
    """Map CGDirectDisplayID -> IOAVService for DDC/CI.

    This follows MonitorControl's Apple Silicon path: recursively scan IORegistry
    in order, pair each framebuffer with the following DCPAVServiceProxy, then
    score candidates against CoreDisplay metadata.
    """
    external_ids = [did for did in displays if not CGDisplayIsBuiltin(did)]
    if not external_ids or not (IOAVServiceCreateWithService and IOAVServiceReadI2C and IOAVServiceWriteI2C):
        return {}

    candidates: list[tuple[int, int, dict]] = []
    for did in external_ids:
        for svc_info in _get_ioreg_services_for_matching():
            if not svc_info.get("service"):
                continue
            score = _ddc_service_match_score(did, svc_info)
            if score > 0:
                candidates.append((score, did, svc_info))

    result: dict[int, Any] = {}
    taken_locations: set[int] = set()
    for score, did, svc_info in sorted(candidates, key=lambda item: item[0], reverse=True):
        location = svc_info.get("service_location")
        if did in result or (location is not None and location in taken_locations):
            continue
        result[did] = svc_info["service"]
        if location is not None:
            taken_locations.add(location)

    return result

# Global DDC service map, populated on first use
_ddc_service_map: Optional[dict[int, Any]] = None

def _get_ddc_service(did: int) -> Optional[Any]:
    global _ddc_service_map
    if _ddc_service_map is None:
        all_displays = get_all_displays()
        _ddc_service_map = _match_ddc_services(all_displays)
    return _ddc_service_map.get(did)

# --- Display mode info ---
CGDisplayCopyDisplayMode = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_uint32,
)(_lookup('CGDisplayCopyDisplayMode'))
CGDisplayCopyAllDisplayModes = ctypes.CFUNCTYPE(
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
)(_lookup('CGDisplayCopyAllDisplayModes'))
CGDisplayModeGetRefreshRate = ctypes.CFUNCTYPE(
    ctypes.c_double, ctypes.c_void_p,
)(_lookup('CGDisplayModeGetRefreshRate'))
CGDisplayModeGetWidth = ctypes.CFUNCTYPE(
    ctypes.c_size_t, ctypes.c_void_p,
)(_lookup('CGDisplayModeGetWidth'))
CGDisplayModeGetHeight = ctypes.CFUNCTYPE(
    ctypes.c_size_t, ctypes.c_void_p,
)(_lookup('CGDisplayModeGetHeight'))
CGDisplayModeGetPixelWidth = ctypes.CFUNCTYPE(
    ctypes.c_size_t, ctypes.c_void_p,
)(_lookup('CGDisplayModeGetPixelWidth'))
CGDisplayModeGetPixelHeight = ctypes.CFUNCTYPE(
    ctypes.c_size_t, ctypes.c_void_p,
)(_lookup('CGDisplayModeGetPixelHeight'))
_CGDisplayModeGetIODisplayModeID_ptr = _lookup_optional('CGDisplayModeGetIODisplayModeID')
CGDisplayModeGetIODisplayModeID = (
    ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p,
    )(_CGDisplayModeGetIODisplayModeID_ptr) if _CGDisplayModeGetIODisplayModeID_ptr else None
)

#============ 数据获取 ===========
MAX_DISPLAYS = 64

VENDOR_MAP = {
    0x0610: "Apple", 0x10AC: "Dell", 0x1E6D: "LG",
    0x04B3: "IBM", 0x045E: "Microsoft", 0x05E3: "HP",
    0x10FA: "Apple", 0x38A3: "BenQ", 0x1B4F: "Acer",
    0x09D1: "AOC", 0x22F0: "HP", 0x0418: "ViewSonic",
    0x06B3: "EIZO", 0x05AC: "Apple",
}

def get_all_displays() -> list[int]:
    ids = (ctypes.c_uint32 * MAX_DISPLAYS)()
    count = ctypes.c_uint32(0)
    display_list_fn = CGSGetDisplayList or CGGetOnlineDisplayList
    if not display_list_fn:
        print(f"{FLRed}ERROR: No display-list API is available on this macOS version.{CRst}\n")
        sys.exit(1)
    err = display_list_fn(MAX_DISPLAYS, ids, ctypes.byref(count))
    if err != 0:
        print(f"{FLRed}ERROR: display list query failed with error code {err}{CRst}\n")
        sys.exit(1)
    return [ids[i] for i in range(count.value)]

def get_active_displays() -> set[int]:
    ids = (ctypes.c_uint32 * MAX_DISPLAYS)()
    count = ctypes.c_uint32(0)
    CGGetActiveDisplayList(MAX_DISPLAYS, ids, ctypes.byref(count))
    return {ids[i] for i in range(count.value)}

def find_builtin_display(displays: list[int]) -> int:
    # Method 1: scan given list (usually from CGSGetDisplayList)
    for did in displays:
        if CGDisplayIsBuiltin(did):
            return did

    # Method 2: Apple Silicon built-in display ID is always 1
    return 1

def _is_sidecar_display(product_name: str, display_location: str) -> bool:
    text = f"{product_name} {display_location}".lower()
    return "sidecar" in text or "ipad" in text

def _nsscreen_geometry(did: int) -> Optional[dict]:
    """Return AppKit screen geometry for the display, if PyObjC/AppKit is available."""
    try:
        from AppKit import NSScreen  # type: ignore[import-untyped]
    except Exception:
        return None

    try:
        for screen in NSScreen.screens():
            desc = screen.deviceDescription()
            screen_num = _safe_int(desc.get("NSScreenNumber"), 0) or 0
            if screen_num != did:
                continue

            frame = screen.frame()
            visible = screen.visibleFrame()
            frame_w = int(round(frame.size.width))
            frame_h = int(round(frame.size.height))
            visible_w = int(round(visible.size.width))
            visible_h = int(round(visible.size.height))

            left_inset = int(round(visible.origin.x - frame.origin.x))
            bottom_inset = int(round(visible.origin.y - frame.origin.y))
            right_inset = int(round((frame.origin.x + frame.size.width) -
                                    (visible.origin.x + visible.size.width)))
            top_inset = int(round((frame.origin.y + frame.size.height) -
                                  (visible.origin.y + visible.size.height)))

            return {
                "frame": (frame_w, frame_h),
                "visible": (visible_w, visible_h),
                "safe_below_menu": (frame_w, max(0, frame_h - max(0, top_inset))),
                "insets": {
                    "left": max(0, left_inset),
                    "right": max(0, right_inset),
                    "top": max(0, top_inset),
                    "bottom": max(0, bottom_inset),
                },
            }
    except Exception:
        return None
    return None

def _cf_value_to_text(cf) -> Optional[str]:
    if not cf:
        return None
    try:
        if _CFGetTypeID(cf) == _CFStringGetTypeID():
            return _cfstring_to_py(cf)
        num = ctypes.c_int64(0)
        if _CFNumberGetValue(cf, 10, ctypes.byref(num)):
            return str(num.value)
    except Exception:
        return None
    return None

def _first_cfdict_value(d):
    if not d:
        return None
    try:
        count = _CFDictionaryGetCount(d)
        if count <= 0:
            return None
        keys = (ctypes.c_void_p * count)()
        values = (ctypes.c_void_p * count)()
        _CFDictionaryGetKeysAndValues(d, keys, values)
        return values[0]
    except Exception:
        return None

def _profile_label_from_url(url: Optional[str]) -> str:
    if not url:
        return "N/A"
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(parsed.path if parsed.scheme else url)
    base = os.path.basename(path) if path else url
    if base.lower().endswith(".icc") or base.lower().endswith(".icm"):
        base = os.path.splitext(base)[0]
    return base or "N/A"

def _colorsync_profile_url(did: int) -> Optional[str]:
    if not (CGDisplayCreateUUIDFromDisplayID and ColorSyncDeviceCopyDeviceInfo):
        return None

    display_class = _colorsync_constant('kColorSyncDisplayDeviceClass')
    key_custom = _colorsync_constant('kColorSyncCustomProfiles')
    key_factory = _colorsync_constant('kColorSyncFactoryProfiles')
    key_default = _colorsync_constant('kColorSyncDeviceDefaultProfileID')
    key_profile_url = _colorsync_constant('kColorSyncDeviceProfileURL')
    if not (display_class and key_factory and key_default and key_profile_url):
        return None

    try:
        uuid = CGDisplayCreateUUIDFromDisplayID(did)
        if not uuid:
            return None
        info = ColorSyncDeviceCopyDeviceInfo(ctypes.c_void_p(display_class), uuid)
        if not info:
            return None

        factory_profiles = _cfdict_get_by_cfkey(info, key_factory)
        default_profile_id = _cfdict_get_by_cfkey(factory_profiles, key_default)
        custom_profiles = _cfdict_get_by_cfkey(info, key_custom)

        if custom_profiles and default_profile_id:
            custom_url = _CFDictionaryGetValue(custom_profiles, default_profile_id)
            url = _cfurl_to_py(custom_url)
            if url:
                return url

        if custom_profiles:
            url = _cfurl_to_py(_first_cfdict_value(custom_profiles))
            if url:
                return url

        if factory_profiles and default_profile_id:
            factory_profile = _CFDictionaryGetValue(factory_profiles, default_profile_id)
            url = _cfurl_to_py(_cfdict_get_by_cfkey(factory_profile, key_profile_url))
            if url:
                return url
    except Exception:
        return None

    return None

def _display_profile_from_files(product_name: str, display_uuid: str = "") -> str:
    if not product_name:
        return "N/A"
    roots = [
        "/Library/ColorSync/Profiles/Displays",
        os.path.expanduser("~/Library/ColorSync/Profiles/Displays"),
        os.path.expanduser("~/Library/ColorSync/Profiles"),
    ]
    patterns: list[str] = []
    if display_uuid:
        patterns.append(f"*-{display_uuid}.ic?")
    safe_name = product_name.replace("/", "_")
    patterns.append(f"{safe_name}*.ic?")

    for root in roots:
        for pattern in patterns:
            matches = glob.glob(os.path.join(root, pattern))
            if matches:
                return _profile_label_from_url(matches[0])
    return "N/A"

def _load_windowserver_display_configs() -> list[dict]:
    paths = glob.glob(os.path.expanduser(
        "~/Library/Preferences/ByHost/com.apple.windowserver.displays.*.plist"))
    paths.append("/Library/Preferences/com.apple.windowserver.displays.plist")

    for path in paths:
        try:
            with open(path, "rb") as f:
                data = plistlib.load(f)
            configs = data.get("DisplayAnyUserSets", {}).get("Configs", [])
            if configs:
                return configs
        except Exception:
            continue
    return []

_windowserver_configs_cache: Optional[list[dict]] = None

def _windowserver_configs() -> list[dict]:
    global _windowserver_configs_cache
    if _windowserver_configs_cache is None:
        _windowserver_configs_cache = _load_windowserver_display_configs()
    return _windowserver_configs_cache

def _refresh_to_int(refresh: str) -> Optional[int]:
    try:
        return int(round(float(refresh.rstrip("Hz"))))
    except Exception:
        return None

def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return default

def _windowserver_record_for_display(did: int, width: int, height: int, refresh: str) -> Optional[dict]:
    target_hz = _refresh_to_int(refresh)
    candidates: list[dict] = []
    for config in _windowserver_configs():
        for record in config.get("DisplayConfig", []):
            current = record.get("CurrentInfo", {})
            if _safe_int(current.get("Wide"), -1) != int(width):
                continue
            if _safe_int(current.get("High"), -1) != int(height):
                continue
            if target_hz is not None and _safe_int(current.get("Hz"), target_hz) != target_hz:
                continue
            candidates.append(record)
    if not candidates:
        return None

    # Prefer a record from a config that contains the current display count.
    active_count = len(get_active_displays())
    for config in _windowserver_configs():
        records = config.get("DisplayConfig", [])
        if len(records) != active_count:
            continue
        for record in records:
            current = record.get("CurrentInfo", {})
            if (_safe_int(current.get("Wide"), -1) == int(width)
                    and _safe_int(current.get("High"), -1) == int(height)):
                return record
    return candidates[0]

_ioreg_framebuffer_snapshots_cache: Optional[list[dict]] = None

def _ioreg_framebuffer_snapshots() -> list[dict]:
    global _ioreg_framebuffer_snapshots_cache
    if _ioreg_framebuffer_snapshots_cache is not None:
        return _ioreg_framebuffer_snapshots_cache

    try:
        result = subprocess.run(
            ["ioreg", "-arc", "IOMobileFramebufferShim", "-a"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        parsed = plistlib.loads(result.stdout)
        _ioreg_framebuffer_snapshots_cache = parsed if isinstance(parsed, list) else []
    except Exception:
        _ioreg_framebuffer_snapshots_cache = []
    return _ioreg_framebuffer_snapshots_cache

def _framebuffer_product_attrs(snapshot: dict) -> dict:
    attrs = snapshot.get("DisplayAttributes")
    if not isinstance(attrs, dict):
        return {}
    product_attrs = attrs.get("ProductAttributes")
    return product_attrs if isinstance(product_attrs, dict) else {}

def _framebuffer_match_score(did: int, snapshot: dict, product_name: str) -> int:
    product_attrs = _framebuffer_product_attrs(snapshot)
    if not product_attrs:
        return 0

    score = 0
    product = int(CGDisplayModelNumber(did))
    serial = int(CGDisplaySerialNumber(did))
    snap_product = product_attrs.get("ProductID")
    snap_serial = product_attrs.get("SerialNumber")
    snap_name = product_attrs.get("ProductName") or ""

    snap_product_int = _safe_int(snap_product)
    snap_serial_int = _safe_int(snap_serial)
    if snap_product_int is not None and snap_product_int == product:
        score += 10
    if serial and snap_serial_int is not None and snap_serial_int == serial:
        score += 20
    if product_name and snap_name and str(snap_name).lower() == product_name.lower():
        score += 5
    return score

def _framebuffer_snapshot_for_display(did: int, product_name: str = "") -> Optional[dict]:
    best: Optional[dict] = None
    best_score = 0
    for snapshot in _ioreg_framebuffer_snapshots():
        score = _framebuffer_match_score(did, snapshot, product_name)
        if score > best_score:
            best = snapshot
            best_score = score
    return best

def _timing_dimensions(timing: dict) -> tuple[Optional[int], Optional[int]]:
    h_attrs = timing.get("HorizontalAttributes")
    v_attrs = timing.get("VerticalAttributes")
    if not isinstance(h_attrs, dict) or not isinstance(v_attrs, dict):
        return None, None
    active_w = _safe_int(h_attrs.get("Active"))
    active_h = _safe_int(v_attrs.get("Active"))
    if active_w is None or active_h is None:
        return None, None
    return active_w, active_h

def _framebuffer_color_modes(snapshot: dict, width: int, height: int) -> tuple[list[dict], list[dict]]:
    top_modes = snapshot.get("ColorElements")
    available = top_modes if isinstance(top_modes, list) else []

    matching_modes: list[dict] = []
    timings = snapshot.get("TimingElements")
    if isinstance(timings, list):
        for timing in timings:
            if not isinstance(timing, dict):
                continue
            timing_w, timing_h = _timing_dimensions(timing)
            if timing_w != int(width) or timing_h != int(height):
                continue
            color_modes = timing.get("ColorModes")
            if isinstance(color_modes, list) and color_modes:
                matching_modes = color_modes
                break

    return available, matching_modes

def _color_mode_pixel_label(mode: dict) -> str:
    pixel_encoding = _safe_int(mode.get("PixelEncoding"))
    if pixel_encoding is None:
        return "PixelEncoding N/A"
    return PIXEL_ENCODING_MAP.get(pixel_encoding, f"PixelEncoding {pixel_encoding}")

def _format_ioreg_color_mode(mode: dict, include_id: bool = False) -> str:
    parts = []
    if include_id and "ID" in mode:
        parts.append(f"ID {mode['ID']}")
    parts.append(_color_mode_pixel_label(mode))
    if "DynamicRange" in mode:
        parts.append(f"DR {mode['DynamicRange']}")
    if "EOTF" in mode:
        parts.append(f"EOTF {mode['EOTF']}")
    if "Colorimetry" in mode:
        parts.append(f"colorimetry {mode['Colorimetry']}")
    if mode.get("IsVirtual"):
        parts.append("virtual")
    if include_id and "Score" in mode:
        parts.append(f"score {mode['Score']}")
    return ", ".join(parts)

def _available_color_mode_summary(did: int, product_name: str, width: int, height: int) -> str:
    snapshot = _framebuffer_snapshot_for_display(did, product_name)
    if not snapshot:
        return "N/A"

    available, matching = _framebuffer_color_modes(snapshot, width, height)
    source = matching or available
    if not source:
        return "N/A"

    labels: list[str] = []
    for mode in source:
        if not isinstance(mode, dict):
            continue
        label = _color_mode_pixel_label(mode)
        if label not in labels:
            labels.append(label)
    return ", ".join(labels) if labels else "N/A"

PIXEL_ENCODING_MAP = {
    0: "RGB",
    1: "YCbCr 4:2:2",
    2: "YCbCr 4:2:0",
    3: "YCbCr 4:4:4",
    4: "YCbCr 4:2:2",
    5: "YCbCr 4:2:0",
    6: "YCbCr 4:2:2",
}

def _format_color_mode(link: Optional[dict]) -> str:
    if not link:
        return "N/A"
    pixel_encoding = link.get("PixelEncoding")
    if pixel_encoding is None:
        return "N/A"
    try:
        pixel_encoding_int = int(pixel_encoding)
    except Exception:
        return "N/A"
    label = PIXEL_ENCODING_MAP.get(pixel_encoding_int, f"PixelEncoding {pixel_encoding_int}")
    details = []
    if "BitDepth" in link:
        details.append(f"{link['BitDepth']}-bit")
    if "Range" in link:
        details.append("full" if int(link["Range"]) == 1 else f"range {link['Range']}")
    return f"{label} ({', '.join(details)})" if details else label

def _display_color_details(did: int, product_name: str, width: int, height: int, refresh: str) -> tuple[str, str, str]:
    profile_url = _colorsync_profile_url(did)
    record = _windowserver_record_for_display(did, width, height, refresh)
    display_uuid = str(record.get("UUID", "")) if record else ""

    profile = _profile_label_from_url(profile_url)
    if profile == "N/A":
        profile = _display_profile_from_files(product_name, display_uuid)

    color_mode = _format_color_mode(record.get("LinkDescription") if record else None)
    available_modes = _available_color_mode_summary(did, product_name, width, height)
    return profile, color_mode, available_modes

def get_display_info(did: int) -> dict:
    active_set = get_active_displays()
    is_builtin = bool(CGDisplayIsBuiltin(did))
    is_active = did in active_set
    w = CGDisplayPixelsWide(did)
    h = CGDisplayPixelsHigh(did)
    rot = int(CGDisplayRotation(did))  # unreliable on Apple Silicon — may not reflect actual rotation
    vendor = CGDisplayVendorNumber(did)
    model = CGDisplayModelNumber(did)
    sn = CGDisplaySerialNumber(did)

    refresh_str = "?"
    mode = CGDisplayCopyDisplayMode(did)
    if mode:
        try:
            rr = CGDisplayModeGetRefreshRate(mode)
            refresh_str = f"{rr:.0f}Hz" if rr > 0 else "?"
        except Exception:
            pass

    # Read product/location from CoreDisplay info dictionary.
    product_name = ""
    display_location = ""
    try:
        info = CoreDisplayCreateInfoDict(did) if CoreDisplayCreateInfoDict else None
        if info:
            name = _cfdict_get_str(info, "DisplayProductName")
            location = _cfdict_get_str(info, "IODisplayLocation")
            if name:
                product_name = name
            if location:
                display_location = location
    except Exception:
        pass

    is_sidecar = (not is_builtin) and _is_sidecar_display(product_name, display_location)
    geometry = _nsscreen_geometry(did)
    color_profile, color_mode, available_color_modes = _display_color_details(
        did, product_name, int(w), int(h), refresh_str)

    brightness_str = "N/A"
    try:
        if not is_active:
            brightness_str = "inactive"
        elif is_builtin:
            b = ctypes.c_float(-1)
            err = DSGetDisplayBrightness(did, ctypes.byref(b)) if DSGetDisplayBrightness else -1
            if err == 0 and b.value >= 0:
                brightness_str = f"{int(b.value * 100)}%"
            elif not DSGetDisplayBrightness:
                brightness_str = "DisplayServices unavailable"
        elif is_sidecar:
            brightness_str = "Sidecar/iPad managed"
        else:
            ddc_svc = _get_ddc_service(did)
            if ddc_svc:
                result = _ddc_read(ddc_svc, _DDC_BRIGHTNESS_CMD)
                if result:
                    cur, mx = result
                    brightness_str = f"{int(cur / mx * 100)}% (DDC/CI)"
                else:
                    brightness_str = "DDC/CI write-only"
            else:
                brightness_str = "DDC/CI unavailable"
    except Exception:
        pass

    vendor_name = VENDOR_MAP.get(vendor, f"0x{vendor:04X}")

    return {
        'id': did, 'is_builtin': is_builtin, 'is_sidecar': is_sidecar,
        'is_active': is_active, 'width': w, 'height': h,
        'rotation': rot, 'vendor': vendor, 'vendor_name': vendor_name,
        'model': f"0x{model:04X}", 'serial': sn,
        'refresh': refresh_str, 'brightness': brightness_str,
        'color_profile': color_profile, 'color_mode': color_mode,
        'available_color_modes': available_color_modes,
        'product_name': product_name, 'display_location': display_location,
        'geometry': geometry,
    }

def print_display_list(displays: list[int]):
    active_set = get_active_displays()
    if not displays:
        print(f"  {FGray}(no displays found){CRst}")
        return
    
    print(f"{FLCyan}────────────────────────────────────────────────────{CRst}")
    print(f"\n{FLYellow}  All displays ({len(displays)} total, {len(active_set)} active):{CRst}\n")

    for idx, did in enumerate(displays):
        info = get_display_info(did)
        is_active = info["is_active"]
        status = f"{FLGreen}ACTIVE{CRst}" if is_active else f"{FGray}inactive{CRst}"
        tags = []
        if info['is_builtin']:
            tags.append(f"{FLGreen}[BUILT-IN]{CRst}")
        elif info['is_sidecar']:
            tags.append(f"{FLMagenta}[SIDECAR]{CRst}")
        else:
            tags.append(f"{FLCyan}[EXTERNAL]{CRst}")
        tag_str = " " + " ".join(tags)
        
        idx_str = f"{FLYellow if is_active else FGray}[{idx}]{CRst}"
        print(f"  {idx_str} Display ID: {FLYellow}{info['id']}{CRst}{tag_str}  {status}")
        if info['product_name']:
            print(f"      Name       : {FLGreen}{info['product_name']}{CRst}")
        print(f"      CGDisplay  : {FLCyan}{info['width']} x {info['height']}{CRst}  @ {FLCyan}{info['refresh']}{CRst}")
        if info['is_builtin'] and info.get('geometry'):
            geo = info['geometry']
            frame_w, frame_h = geo['frame']
            safe_w, safe_h = geo['safe_below_menu']
            visible_w, visible_h = geo['visible']
            insets = geo['insets']
            print(f"      NSScreen   : {FLCyan}{frame_w} x {frame_h}{CRst}"
                  f"  {FGray}(frame){CRst}")
            if (safe_w, safe_h) != (frame_w, frame_h):
                print(f"      Derived    : {FLCyan}{safe_w} x {safe_h}{CRst}"
                      f"  {FGray}(frame minus top inset {insets['top']}px){CRst}")
            if (visible_w, visible_h) != (frame_w, frame_h):
                print(f"      NSScreen   : {FLCyan}{visible_w} x {visible_h}{CRst}"
                      f"  {FGray}(visibleFrame; insets L/R/T/B "
                      f"{insets['left']}/{insets['right']}/{insets['top']}/{insets['bottom']}px){CRst}")
        print(f"      Vendor     : {info['vendor_name']} (0x{info['vendor']:04X})"
              f"  Model: {info['model']}  S/N: {info['serial']}")
        print(f"      Color      : profile={FLMagenta}{info['color_profile']}{CRst}")
        print(f"      Color I/O  : available={FLMagenta}{info['available_color_modes']}{CRst}")
        if (not info['is_builtin']) and (not info['is_sidecar']):
            rgb_status = _rgb_override_status(info['vendor'], int(info['model'], 16), info['id'])
            status_color = FLGreen if "loaded" in rgb_status and "not loaded" not in rgb_status else FGray
            print(f"      RGB force  : {status_color}{rgb_status}{CRst}")
        print(f"      Rotation   : {FLMagenta}{info['rotation']}°{CRst}")
        print(f"      Brightness : {FLMagenta}{info['brightness']}{CRst}")
        print()


def _hex_bytes(data: list[int]) -> str:
    return " ".join(f"{b:02X}" for b in data)

def _core_display_snapshot(did: int) -> dict:
    if not CoreDisplayCreateInfoDict:
        return {}
    info = CoreDisplayCreateInfoDict(did)
    if not info:
        return {}
    keys = [
        "DisplayVendorID", "DisplayProductID", "DisplaySerialNumber",
        "DisplayProductName", "DisplayYearOfManufacture",
        "DisplayWeekOfManufacture", "DisplayHorizontalImageSize",
        "DisplayVerticalImageSize", "IODisplayLocation",
    ]
    result = {}
    for key in keys:
        text_value = _cfdict_get_str(info, key)
        if text_value is not None:
            result[key] = text_value
            continue
        int_value = _cfdict_get_int(info, _cfstr(key))
        if int_value is not None:
            result[key] = int_value
    return result

def print_ddc_info(displays: list[int]) -> bool:
    """Print DDC/CI diagnostics for external displays."""
    external_ids = [did for did in displays if not CGDisplayIsBuiltin(did)]
    if not external_ids:
        print(f"{FGray}  No external displays found.{CRst}\n")
        return False

    services = _get_ioreg_services_for_matching()
    matched = _match_ddc_services(displays)
    print(f"\n{FLYellow}  DDC/CI diagnostic dump{CRst}")
    print(f"  I2C 7-bit addr: {FLCyan}0x{_DDC_7BIT_ADDR:02X}{CRst}"
          f"  Data addr: {FLCyan}0x{_DDC_DATA_ADDR:02X}{CRst}")
    print(f"  IORegistry candidate services: {FLCyan}{len(services)}{CRst}\n")

    for idx, svc_info in enumerate(services):
        svc_state = "yes" if svc_info.get("service") else "no"
        print(f"  {FLYellow}Candidate service #{idx}{CRst}")
        print(f"    Location index : {svc_info.get('service_location')}")
        print(f"    Has IOAVService: {svc_state}")
        print(f"    Product name   : {svc_info.get('product_name') or '(none)'}")
        print(f"    Serial number  : {svc_info.get('serial_number') or '(none)'}")
        print(f"    EDID UUID      : {svc_info.get('edid_uuid') or '(none)'}")
        print(f"    IO path        : {svc_info.get('io_display_location') or '(none)'}")
        scores = [
            f"display {did}: {_ddc_service_match_score(did, svc_info)}"
            for did in external_ids
        ]
        print(f"    Match scores   : {', '.join(scores)}")
        print()

    for did in external_ids:
        info = get_display_info(did)
        svc = matched.get(did)
        print(f"{FLCyan}{'─' * 52}{CRst}")
        print(f"  {FLYellow}Display ID {did}: {info['product_name'] or '(unnamed external display)'}{CRst}")
        print(f"    Vendor/model/serial: 0x{info['vendor']:04X} / {info['model']} / {info['serial']}")
        print(f"    Matched IOAVService: {svc if svc else '(none)'}")

        snapshot = _core_display_snapshot(did)
        if snapshot:
            print(f"    CoreDisplay:")
            for key, value in snapshot.items():
                print(f"      {key}: {value}")

        if not svc:
            print(f"    {FGray}No matched DDC service; raw VCP reads skipped.{CRst}\n")
            continue

        print(f"    VCP raw reads:")
        for command, name in DDC_DUMP_COMMANDS:
            err, reply, parsed = _ddc_raw_read(svc, command)
            csum_ok = (
                err == 0
                and len(reply) >= 11
                and _ddc_checksum(0x50, reply[:10]) == reply[10]
            )
            parsed_str = (
                f"current={parsed[0]} max={parsed[1]} pct={int(parsed[0] / parsed[1] * 100)}%"
                if parsed else "standard-parse=N/A"
            )
            print(f"      0x{command:02X} {name:<28} err={err:<3}"
                  f" checksum={'ok' if csum_ok else 'no'}  {parsed_str}")
            print(f"        raw: {_hex_bytes(reply)}")
        print()

    return True

def print_color_mode_info(displays: list[int]) -> bool:
    """Print current/available color mode diagnostics for one display."""
    try:
        choice = input(f"{FLYellow}  Select display index (or Enter to cancel): {CRst}").strip()
        if not choice:
            return False
        idx = int(choice)
        if idx < 0 or idx >= len(displays):
            print(f"{FLRed}  Invalid selection.{CRst}\n")
            return False
    except (ValueError, EOFError):
        return False

    did = displays[idx]
    info = get_display_info(did)
    print(f"\n{FLYellow}  Color mode diagnostics{CRst}")
    print(f"  Display       : {FLCyan}{info['product_name'] or f'Display {did}'}{CRst}")
    print(f"  Vendor/Product: {FLCyan}0x{info['vendor']:04X} / {info['model']}{CRst}")
    print(f"  Current mode  : {FLMagenta}{info['color_mode']}{CRst} {FGray}(WindowServer LinkDescription){CRst}")
    print(f"  Color profile : {FLMagenta}{info['color_profile']}{CRst}")

    snapshot = _framebuffer_snapshot_for_display(did, info["product_name"])
    if not snapshot:
        print(f"  Available     : {FGray}N/A{CRst}")
        print(f"{FGray}  No matching IOMobileFramebufferShim snapshot was found.{CRst}\n")
        return False

    product_attrs = _framebuffer_product_attrs(snapshot)
    if product_attrs:
        print(f"  IORegistry    : {FGray}{product_attrs.get('ProductName') or '(unnamed)'}"
              f"  ProductID={product_attrs.get('ProductID', 'N/A')}"
              f"  Serial={product_attrs.get('SerialNumber', 'N/A')}{CRst}")

    available, matching = _framebuffer_color_modes(
        snapshot, int(info["width"]), int(info["height"]))
    print(f"  Available     : {FLMagenta}{info['available_color_modes']}{CRst}")
    print(f"{FGray}  Note: IORegistry ColorElements/ColorModes expose available modes; they are not"
          f" guaranteed to identify the active link mode.{CRst}\n")

    if matching:
        print(f"{FLYellow}  Modes for current timing ({info['width']}x{info['height']}){CRst}")
        for mode in matching:
            if isinstance(mode, dict):
                print(f"    - {_format_ioreg_color_mode(mode, include_id=True)}")
        print()
    elif available:
        print(f"{FGray}  No timing-specific ColorModes matched current CGDisplay size; using top-level ColorElements.{CRst}\n")

    if available:
        print(f"{FLYellow}  Top-level ColorElements{CRst}")
        for mode in available:
            if isinstance(mode, dict):
                print(f"    - {_format_ioreg_color_mode(mode, include_id=True)}")
        print()
        return True

    print(f"{FGray}  No ColorElements were present for this display.{CRst}\n")
    return False


#============ 功能：强制 RGB 输出 ===========
RGB_OVERRIDE_ROOT = "/Library/Displays/Contents/Resources/Overrides"
RGB_BACKUP_SUFFIX = ".screen-utils-backup-"

def _edid_checksum_block(block: bytearray) -> None:
    """Update the checksum byte for one 128-byte EDID block."""
    block[127] = (-sum(block[:127])) & 0xFF

def _patch_edid_force_rgb(edid: bytes) -> tuple[Optional[bytes], list[str]]:
    """Return EDID with CTA YCbCr support flags cleared."""
    if len(edid) < 128 or len(edid) % 128 != 0:
        return None, [f"Invalid EDID length: {len(edid)} bytes"]

    patched = bytearray(edid)
    notes: list[str] = []
    declared_extensions = patched[126]
    available_extensions = max(0, len(patched) // 128 - 1)
    extension_count = min(declared_extensions, available_extensions)

    if extension_count == 0:
        return None, ["No EDID extension block found"]

    changed = False
    for ext_idx in range(extension_count):
        start = 128 * (ext_idx + 1)
        block = patched[start:start + 128]
        if len(block) != 128:
            continue
        if block[0] != 0x02:
            notes.append(f"Extension #{ext_idx + 1}: skipped non-CTA block tag 0x{block[0]:02X}")
            continue

        old_flags = block[3]
        new_flags = old_flags & ~0x30  # clear YCbCr 4:4:4 and YCbCr 4:2:2 support
        if new_flags != old_flags:
            block[3] = new_flags
            _edid_checksum_block(block)
            patched[start:start + 128] = block
            changed = True
            notes.append(
                f"CTA extension #{ext_idx + 1}: cleared YCbCr support flags "
                f"0x{old_flags:02X} -> 0x{new_flags:02X}"
            )
        else:
            notes.append(f"CTA extension #{ext_idx + 1}: YCbCr flags already clear")

    if not changed:
        return None, notes + ["No YCbCr capability flags needed patching"]
    return bytes(patched), notes

def _display_override_dir(vendor: int) -> str:
    return os.path.join(RGB_OVERRIDE_ROOT, f"DisplayVendorID-{vendor:x}")

def _display_override_path(vendor: int, product: int) -> str:
    return os.path.join(_display_override_dir(vendor), f"DisplayProductID-{product:x}")

def _rgb_backup_paths(vendor: int, product: int) -> list[str]:
    path = _display_override_path(vendor, product)
    parent = os.path.dirname(path)
    prefix = os.path.basename(path) + RGB_BACKUP_SUFFIX
    if not os.path.isdir(parent):
        return []
    return [
        os.path.join(parent, name)
        for name in sorted(os.listdir(parent))
        if name.startswith(prefix)
    ]

def _rgb_override_state(vendor: int, product: int) -> dict:
    path = _display_override_path(vendor, product)
    backups = _rgb_backup_paths(vendor, product)
    return {
        "installed": os.path.exists(path),
        "path": path,
        "backups": backups,
    }

def _read_rgb_override_edid(vendor: int, product: int) -> Optional[bytes]:
    path = _display_override_path(vendor, product)
    try:
        with open(path, "rb") as f:
            edid = plistlib.load(f).get("IODisplayEDID")
        return bytes(edid) if isinstance(edid, (bytes, bytearray)) else None
    except Exception:
        return None

def _edid_has_ycbcr_caps(edid: Optional[bytes]) -> Optional[bool]:
    if not edid or len(edid) < 128 or len(edid) % 128 != 0:
        return None

    declared_extensions = edid[126]
    available_extensions = max(0, len(edid) // 128 - 1)
    extension_count = min(declared_extensions, available_extensions)
    for ext_idx in range(extension_count):
        start = 128 * (ext_idx + 1)
        block = edid[start:start + 128]
        if len(block) == 128 and block[0] == 0x02 and (block[3] & 0x30):
            return True
    return False

def _rgb_override_status(vendor: int, product: int, did: Optional[int] = None) -> str:
    state = _rgb_override_state(vendor, product)
    if not state["installed"]:
        return "not installed"

    parts = ["installed"]
    if did is not None:
        current_has_ycbcr = _edid_has_ycbcr_caps(_display_edid_from_ioreg(did))
        override_has_ycbcr = _edid_has_ycbcr_caps(_read_rgb_override_edid(vendor, product))
        if override_has_ycbcr is False and current_has_ycbcr is True:
            parts.append("not loaded; reboot/replug")
        elif override_has_ycbcr is False and current_has_ycbcr is False:
            parts.append("loaded")
    if state["backups"]:
        parts.append(f"{len(state['backups'])} backup(s)")
    return ", ".join(parts)

def _core_display_edid(did: int) -> Optional[bytes]:
    if not CoreDisplayCreateInfoDict:
        return None
    info = CoreDisplayCreateInfoDict(did)
    if not info:
        return None
    for key in ("IODisplayEDID", "DisplayEDID", "EDID"):
        data = _cfdict_get_data(info, key)
        if data:
            return data
    return None

def _ioreg_display_connect_entries() -> list[dict]:
    try:
        result = subprocess.run(
            ["ioreg", "-r", "-c", "IODisplayConnect", "-a"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except Exception:
        return []

    try:
        parsed = plistlib.loads(result.stdout)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []

def _ioreg_metadata_edid_entries() -> list[dict]:
    """Read EDID entries from IORegistry Metadata dictionaries."""
    try:
        result = subprocess.run(
            ["ioreg", "-lw0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            check=True,
        )
    except Exception:
        return []

    entries: list[dict] = []
    pattern = re.compile(r'"Metadata"\s*=\s*\{(?P<body>.*?)\}', re.S)
    edid_pattern = re.compile(r'"EDID"\s*=\s*<(?P<edid>[0-9a-fA-F\s]+)>')
    int_keys = {
        "ProductID": r'"ProductID"\s*=\s*(\d+)',
        "SerialNumber": r'"SerialNumber"\s*=\s*(\d+)',
    }
    str_keys = {
        "ProductName": r'"ProductName"\s*=\s*"([^"]*)"',
        "ManufacturerName": r'"ManufacturerName"\s*=\s*"([^"]*)"',
    }

    for match in pattern.finditer(result.stdout):
        body = match.group("body")
        edid_match = edid_pattern.search(body)
        if not edid_match:
            continue
        try:
            edid = bytes.fromhex(re.sub(r"\s+", "", edid_match.group("edid")))
        except ValueError:
            continue

        entry: dict = {"EDID": edid}
        for key, key_pattern in int_keys.items():
            key_match = re.search(key_pattern, body)
            if key_match:
                entry[key] = int(key_match.group(1))
        for key, key_pattern in str_keys.items():
            key_match = re.search(key_pattern, body)
            if key_match:
                entry[key] = key_match.group(1)
        entries.append(entry)

    return entries

def _display_edid_from_ioreg(did: int) -> Optional[bytes]:
    vendor = int(CGDisplayVendorNumber(did))
    product = int(CGDisplayModelNumber(did))
    serial = int(CGDisplaySerialNumber(did))

    fallback: Optional[bytes] = None
    for entry in _ioreg_display_connect_entries():
        if _safe_int(entry.get("DisplayVendorID"), -1) != vendor:
            continue
        if _safe_int(entry.get("DisplayProductID"), -1) != product:
            continue

        edid = entry.get("IODisplayEDID")
        if not isinstance(edid, (bytes, bytearray)):
            continue
        edid_bytes = bytes(edid)
        if serial and _safe_int(entry.get("DisplaySerialNumber"), 0) == serial:
            return edid_bytes
        if fallback is None:
            fallback = edid_bytes

    for entry in _ioreg_metadata_edid_entries():
        if _safe_int(entry.get("ProductID"), -1) != product:
            continue
        edid = entry.get("EDID")
        if not isinstance(edid, (bytes, bytearray)):
            continue
        edid_bytes = bytes(edid)
        if serial and _safe_int(entry.get("SerialNumber"), 0) == serial:
            return edid_bytes
        if fallback is None:
            fallback = edid_bytes
    return fallback

def _get_display_edid(did: int) -> Optional[bytes]:
    return _core_display_edid(did) or _display_edid_from_ioreg(did)

def _run_sudo_command(cmd: list[str]) -> tuple[bool, str]:
    result = subprocess.run(cmd)
    if result.returncode == 0:
        return True, ""
    return False, f"Command failed: {' '.join(cmd)}"

def _write_rgb_override(vendor: int, product: int, product_name: str, edid: bytes) -> tuple[bool, str]:
    override_dir = _display_override_dir(vendor)
    override_path = _display_override_path(vendor, product)
    plist = {
        "DisplayVendorID": vendor,
        "DisplayProductID": product,
        "DisplayProductName": product_name or f"DisplayProductID-{product:x}",
        "IODisplayEDID": edid,
        "ForceRGBOutput": True,
    }

    fd, tmp_path = tempfile.mkstemp(prefix="force-rgb-", suffix=".plist", dir="/tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            plistlib.dump(plist, f)

        sudo = shutil.which("sudo")
        if not sudo:
            return False, "sudo not found; cannot write system display override"

        ok, detail = _run_sudo_command([sudo, "mkdir", "-p", override_dir])
        if not ok:
            return False, detail

        if os.path.exists(override_path):
            backup_path = override_path + RGB_BACKUP_SUFFIX + time.strftime("%Y%m%d-%H%M%S")
            ok, detail = _run_sudo_command([sudo, "cp", "-p", override_path, backup_path])
            if not ok:
                return False, detail

        for cmd in ([sudo, "cp", tmp_path, override_path],
                    [sudo, "chmod", "644", override_path]):
            ok, detail = _run_sudo_command(cmd)
            if not ok:
                return False, detail
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return True, override_path

def _select_external_display(displays: list[int]) -> Optional[int]:
    try:
        choice = input(f"{FLYellow}  Select external display index (or Enter to cancel): {CRst}").strip()
        if not choice:
            return None
        idx = int(choice)
        if idx < 0 or idx >= len(displays):
            print(f"{FLRed}  Invalid selection.{CRst}\n")
            return None
    except (ValueError, EOFError):
        return None

    did = displays[idx]
    info = get_display_info(did)
    if info["is_builtin"] or info.get("is_sidecar"):
        print(f"{FLRed}  Please select an external physical display.{CRst}\n")
        return None
    return did

def force_rgb_output(displays: list[int]) -> bool:
    did = _select_external_display(displays)
    return force_rgb_output_for_display(did) if did is not None else False

def force_rgb_output_for_display(did: int) -> bool:
    info = get_display_info(did)
    if info["is_builtin"] or info.get("is_sidecar"):
        print(f"{FLRed}  RGB override is only intended for external physical displays.{CRst}\n")
        return False

    vendor = int(info["vendor"])
    product = int(CGDisplayModelNumber(did))
    product_name = info["product_name"] or f"Display {did}"
    path = _display_override_path(vendor, product)

    print(f"\n{FLYellow}  Display: {product_name}{CRst}")
    print(f"  Vendor/Product : {FLCyan}0x{vendor:04X} / 0x{product:04X}{CRst}")
    print(f"  Override path  : {FGray}{path}{CRst}")

    edid = _get_display_edid(did)
    if not edid:
        print(f"{FLRed}  -> Could not read IODisplayEDID for this display.{CRst}\n")
        return False

    patched_edid, notes = _patch_edid_force_rgb(edid)
    for note in notes:
        print(f"  {FGray}{note}{CRst}")
    if not patched_edid:
        print(f"{FLRed}  -> EDID was not patched; no override written.{CRst}\n")
        return False

    print(f"\n{FLYellow}  This writes a persistent system display override and may ask for sudo.{CRst}")
    print(f"{FGray}  After writing, unplug/replug this display or reboot macOS so the override is loaded.{CRst}")
    try:
        confirm = input(f"  {FLYellow}Install force-RGB override? (y/N): {CRst}").strip().lower()
    except EOFError:
        print(f"{FGray}  Canceled.{CRst}\n")
        return False
    if confirm not in ("y", "yes"):
        print(f"{FGray}  Canceled.{CRst}\n")
        return False

    ok, detail = _write_rgb_override(vendor, product, product_name, patched_edid)
    if ok:
        print(f"{FLGreen}  -> RGB override installed.{CRst}")
        print(f"{FLGreen}     Written file :{CRst} {detail}")
        print(f"{FLGreen}     It should persist after reboot.{CRst}")
        print(f"{FLGreen}     Unplug/replug this display or reboot macOS to apply it.{CRst}\n")
        return True

    print(f"{FLRed}  -> Failed to install RGB override: {detail}{CRst}\n")
    return False

def restore_rgb_output(displays: list[int]) -> bool:
    did = _select_external_display(displays)
    return restore_rgb_output_for_display(did) if did is not None else False

def restore_rgb_output_for_display(did: int) -> bool:
    info = get_display_info(did)
    if info["is_builtin"] or info.get("is_sidecar"):
        print(f"{FLRed}  RGB override is only intended for external physical displays.{CRst}\n")
        return False

    vendor = int(info["vendor"])
    product = int(CGDisplayModelNumber(did))
    product_name = info["product_name"] or f"Display {did}"
    state = _rgb_override_state(vendor, product)
    path = state["path"]
    backups = state["backups"]

    print(f"\n{FLYellow}  Display: {product_name}{CRst}")
    print(f"  Vendor/Product : {FLCyan}0x{vendor:04X} / 0x{product:04X}{CRst}")
    print(f"  Override path  : {FGray}{path}{CRst}")

    if not state["installed"] and not backups:
        print(f"{FGray}  -> No RGB override or backup found for this display.{CRst}\n")
        return False

    if backups:
        latest_backup = backups[-1]
        action = f"restore backup {latest_backup}"
    else:
        latest_backup = ""
        action = "remove override file"

    print(f"{FLYellow}  This will {action} and may ask for sudo.{CRst}")
    print(f"{FGray}  After restoring, unplug/replug this display or reboot macOS so macOS reloads display overrides.{CRst}")
    try:
        confirm = input(f"  {FLYellow}Restore RGB override state? (y/N): {CRst}").strip().lower()
    except EOFError:
        print(f"{FGray}  Canceled.{CRst}\n")
        return False
    if confirm not in ("y", "yes"):
        print(f"{FGray}  Canceled.{CRst}\n")
        return False

    sudo = shutil.which("sudo")
    if not sudo:
        print(f"{FLRed}  -> sudo not found; cannot restore system display override.{CRst}\n")
        return False

    if latest_backup:
        ok, detail = _run_sudo_command([sudo, "cp", "-p", latest_backup, path])
    else:
        ok, detail = _run_sudo_command([sudo, "rm", "-f", path])

    if ok:
        print(f"{FLGreen}  -> RGB override restored.{CRst}")
        print(f"{FLGreen}     Unplug/replug this display or reboot macOS to apply it.{CRst}\n")
        return True

    print(f"{FLRed}  -> Failed to restore RGB override: {detail}{CRst}\n")
    return False

def print_rgb_override_status(displays: list[int]) -> bool:
    print(f"\n{FLYellow}  RGB output override status{CRst}\n")
    found_external = False
    for idx, did in enumerate(displays):
        info = get_display_info(did)
        if info["is_builtin"] or info.get("is_sidecar"):
            continue
        found_external = True
        vendor = int(info["vendor"])
        product = int(CGDisplayModelNumber(did))
        state = _rgb_override_state(vendor, product)
        status = _rgb_override_status(vendor, product, did)
        color = FLGreen if "loaded" in status and "not loaded" not in status else FGray
        print(f"  {FLYellow}[{idx}]{CRst} Display ID {did}: {info['product_name'] or '(unnamed external display)'}")
        print(f"      Vendor/Product : {FLCyan}0x{vendor:04X} / 0x{product:04X}{CRst}")
        print(f"      Status         : {color}{status}{CRst}")
        print(f"      Path           : {FGray}{state['path']}{CRst}")
        if state["backups"]:
            print(f"      Latest backup  : {FGray}{state['backups'][-1]}{CRst}")
        print()

    if not found_external:
        print(f"{FGray}  No external physical displays found.{CRst}\n")
        return False
    return True

def manage_rgb_override(displays: list[int]) -> bool:
    options = [
        MenuOption(["S"], "Show RGB override status"),
        MenuOption(["F"], "Install force RGB override"),
        MenuOption(["R"], "Restore/remove RGB override"),
        MenuOption(["Q"], "Back"),
    ]
    choice = Menu.select(options, prompt="RGB")
    if choice is None or choice == "Q":
        return False
    if choice == "S":
        return print_rgb_override_status(displays)
    if choice == "F":
        return force_rgb_output(displays)
    if choice == "R":
        return restore_rgb_output(displays)
    return False


#============ 功能：toggle 内建显示器 ===========
def toggle_builtin_display(displays: list[int], skip_confirm: bool = False) -> bool:
    """返回 True 表示执行了变更"""
    if not (CGSConfigureDisplayEnabled and CGSCompleteDisplayConfiguration):
        print(f"{FLRed}  Built-in display toggle is unavailable on this macOS version.{CRst}")
        print(f"{FGray}     Missing private CGS display enable/complete API.{CRst}\n")
        return False

    active_set = get_active_displays()
    builtin_id = find_builtin_display(displays)

    builtin_active = builtin_id in active_set
    external_active_count = sum(
        1 for did in displays
        if did != builtin_id and did in active_set
    )

    if external_active_count == 0 and builtin_active:
        print(f"{FLGreen}  -> Built-in display is the only active display.{CRst}")
        print(f"{FLGreen}     Disabling it would leave no screen. Canceled.{CRst}\n")
        return False

    if builtin_active:
        action = "Disable"
        target = False
    else:
        action = "Enable"
        target = True

    # 确认交互
    if not skip_confirm:
        print(f"\n{FLYellow}  About to {action.lower()} the built-in display.{CRst}")
        print(f"  Active external displays: {FLYellow}{external_active_count}{CRst}")
        try:
            confirm = input(f"  {FLYellow}Confirm? (y/N, default y): {CRst}").strip().lower() or "y"
        except EOFError:
            print(f"{FGray}  Canceled.{CRst}\n")
            return False
        if confirm != 'y' and confirm != 'yes':
            print(f"{FGray}  Canceled.{CRst}\n")
            return False

    print(f"{FLYellow}  -> {action} built-in display...{CRst}")
    config = ctypes.c_void_p(0)
    err = CGBeginDisplayConfiguration(ctypes.byref(config))
    if err != 0:
        print(f"{FLRed}  -> CGBeginDisplayConfiguration failed: error {err}{CRst}\n")
        return False
    err = CGSConfigureDisplayEnabled(config, builtin_id, target)
    if err != 0:
        print(f"{FLRed}  -> CGSConfigureDisplayEnabled failed: error {err}{CRst}\n")
        return False
    err = CGSCompleteDisplayConfiguration(config)
    if err == 0:
        status = "disabled" if not target else "enabled"
        print(f"{FLGreen}  -> Built-in display {status}.{CRst}\n")
        if target:
            # 检测内建显示器亮度，如果 <10% 则强制提高到 30%
            time.sleep(0.5)  # 等待显示器完全激活
            b = ctypes.c_float(-1)
            if DSGetDisplayBrightness and DSGetDisplayBrightness(builtin_id, ctypes.byref(b)) == 0 and b.value >= 0:
                if b.value < 0.10:
                    print(f"{FLYellow}  -> Brightness is {int(b.value * 100)}% (<10%), "
                          f"forcing to 30%...{CRst}")
                    if DSSetDisplayBrightness and DSSetDisplayBrightness(builtin_id, 0.30) == 0:
                        print(f"{FLGreen}  -> Brightness set to 30%.{CRst}\n")
                    else:
                        print(f"{FLRed}  -> Failed to set brightness.{CRst}\n")
                else:
                    print(f"{FGray}  -> Brightness is {int(b.value * 100)}%, no adjustment needed.{CRst}\n")
        return True
    else:
        print(f"{FLRed}  -> CGSCompleteDisplayConfiguration failed: error {err}{CRst}\n")
        return False


#============ 功能：旋转 ===========
ROTATION_OPTIONS = {0: "0° (normal)", 1: "90° (clockwise)", 2: "180° (upside down)", 3: "270° (counter-clockwise)"}
ROTATION_VALUES = [0.0, 90.0, 180.0, 270.0]
ROTATION_DIRECT_VALUES = {0, 90, 180, 270}

def _set_rotation_monitorpanel(did: int, target_rot: int) -> tuple[bool, str]:
    """Set display rotation through MonitorPanel private API."""
    if not (_mp_handle and objc_getClass and sel_registerName and _objc_msgSend_ptr):
        return False, "MonitorPanel Objective-C API is unavailable"

    mp_class = objc_getClass(b"MPDisplay")
    if not mp_class:
        return False, "MPDisplay class not found"

    msg_alloc = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(_objc_msgSend_ptr)
    msg_init = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)(_objc_msgSend_ptr)
    msg_set_orientation = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)(_objc_msgSend_ptr)
    msg_release = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(_objc_msgSend_ptr)

    sel_alloc = sel_registerName(b"alloc")
    sel_init = sel_registerName(b"initWithCGSDisplayID:")
    sel_set_orientation = sel_registerName(b"setOrientation:")
    sel_release = sel_registerName(b"release")

    display_obj = msg_alloc(mp_class, sel_alloc)
    if not display_obj:
        return False, "MPDisplay allocation failed"
    display_obj = msg_init(display_obj, sel_init, int(did))
    if not display_obj:
        return False, "MPDisplay initWithCGSDisplayID failed"

    try:
        msg_set_orientation(display_obj, sel_set_orientation, int(target_rot))
        deadline = time.time() + 10
        while time.time() < deadline:
            if int(CGDisplayRotation(did)) == int(target_rot):
                return True, "MonitorPanel MPDisplay.setOrientation"
            time.sleep(0.2)
        return False, "rotation command sent, but CGDisplayRotation did not confirm within 10s"
    finally:
        msg_release(display_obj, sel_release)

def set_rotation(displays: list[int]) -> bool:
    try:
        choice = input(f"{FLYellow}  Select display index (or Enter to cancel): {CRst}").strip()
        if not choice:
            return False
        idx = int(choice)
        if idx < 0 or idx >= len(displays):
            print(f"{FLRed}  Invalid selection.{CRst}\n")
            return False
    except (ValueError, EOFError):
        return False

    did = displays[idx]
    info = get_display_info(did)

    if not info['is_active']:
        print(f"{FLRed}  Display is inactive. Cannot rotate an inactive display.{CRst}\n")
        return False

    if info.get('is_sidecar'):
        print(f"{FLRed}  Rotation is not supported for Sidecar/iPad displays.{CRst}\n")
        return False

    current_rot = info['rotation']

    print(f"\n{FLYellow}  Displayed rotation: {FLMagenta}{current_rot}°{CRst} {FGray}(may not reflect actual rotation on Apple Silicon){CRst}")
    for k, v in ROTATION_OPTIONS.items():
        print(f"    {FLYellow}[{k}]{CRst}  {v}")

    try:
        choice = input(f"\n{FLYellow}  Select rotation (or Enter to cancel): {CRst}").strip()
        if not choice:
            return False
        rot_input = int(choice)
        if rot_input in ROTATION_OPTIONS:
            target_rot = int(ROTATION_VALUES[rot_input])
        elif rot_input in ROTATION_DIRECT_VALUES:
            target_rot = rot_input
        else:
            print(f"{FLRed}  Invalid rotation choice.{CRst}\n")
            return False
    except (ValueError, EOFError):
        return False

    print(f"{FLYellow}  -> Setting rotation to {target_rot}°...{CRst}")
    ok, detail = _set_rotation_monitorpanel(did, target_rot)
    if ok:
        print(f"{FLGreen}  -> Rotation set to {target_rot}° via MonitorPanel API.{CRst}")
        print(f"{FGray}     {detail}{CRst}\n")
        return True

    print(f"{FGray}     MonitorPanel API path failed: {detail}{CRst}")
    if not SLSSetDisplayRotation:
        print(f"{FLRed}  -> Rotation is unavailable on this macOS version/session.{CRst}")
        print(f"{FGray}     Missing SLSSetDisplayRotation fallback API.{CRst}\n")
        return False

    print(f"{FGray}     Falling back to SLSSetDisplayRotation...{CRst}")
    err = SLSSetDisplayRotation(did, float(target_rot))
    if err == 0:
        print(f"{FLGreen}  -> Rotation set to {target_rot}° via SLSSetDisplayRotation.{CRst}\n")
        return True
    else:
        print(f"{FLRed}  -> SLSSetDisplayRotation failed: error {err}{CRst}")
        if err == 1001:
            print(f"{FGray}     macOS rejected this private rotation call for this display/session.{CRst}")
        if err == 1010:
            print(f"{FGray}     This display does not support rotation.{CRst}")
        print(f"{FGray}     Also check System Settings > Displays > Rotation; some displays do not expose rotation on Apple Silicon.{CRst}\n")
        return False


#============ 功能：分辨率 ===========
_CG_CONFIGURE_FOR_SESSION = 1

def _mode_info(mode) -> dict:
    width = int(CGDisplayModeGetWidth(mode))
    height = int(CGDisplayModeGetHeight(mode))
    pixel_width = int(CGDisplayModeGetPixelWidth(mode))
    pixel_height = int(CGDisplayModeGetPixelHeight(mode))
    refresh = float(CGDisplayModeGetRefreshRate(mode))
    mode_id = int(CGDisplayModeGetIODisplayModeID(mode)) if CGDisplayModeGetIODisplayModeID else -1
    hidpi = pixel_width > width or pixel_height > height
    return {
        "mode": mode,
        "id": mode_id,
        "width": width,
        "height": height,
        "pixel_width": pixel_width,
        "pixel_height": pixel_height,
        "refresh": refresh,
        "hidpi": hidpi,
    }

def _get_display_modes(did: int) -> list[dict]:
    options = 0
    if _kCGDisplayShowDuplicateLowResolutionModes and _kCFBooleanTrue:
        keys = (ctypes.c_void_p * 1)(_kCGDisplayShowDuplicateLowResolutionModes)
        values = (ctypes.c_void_p * 1)(_kCFBooleanTrue)
        options = _CFDictionaryCreate(0, keys, values, 1, 0, 0)

    modes_arr = CGDisplayCopyAllDisplayModes(did, options)
    if not modes_arr:
        return []
    count = _CFArrayGetCount(modes_arr)
    modes: list[dict] = []
    for i in range(count):
        mode = _CFArrayGetValueAtIndex(modes_arr, i)
        if not mode:
            continue
        info = _mode_info(mode)
        if info["width"] > 0 and info["height"] > 0:
            modes.append(info)
    return modes

def _current_mode_id(did: int) -> Optional[int]:
    if not CGDisplayModeGetIODisplayModeID:
        return None
    mode = CGDisplayCopyDisplayMode(did)
    if not mode:
        return None
    return int(CGDisplayModeGetIODisplayModeID(mode))

def _mode_source_labels(did: Optional[int], mode: dict) -> str:
    labels = []
    if mode["hidpi"]:
        labels.append(f"{FLCyan}[HiDPI]{CRst}")
    if did is None or not CGDisplayIsBuiltin(did):
        return " ".join(labels)

    geo = _nsscreen_geometry(did)
    if not geo:
        return " ".join(labels)

    frame_w, frame_h = geo["frame"]
    safe_w, safe_h = geo["safe_below_menu"]
    top_inset = geo["insets"]["top"]

    if abs(mode["width"] - frame_w) <= 2 and abs(mode["height"] - frame_h) <= 2:
        labels.append(f"{FLMagenta}[matches NSScreen.frame]{CRst}")
    elif top_inset > 0 and abs(mode["width"] - safe_w) <= 2 and abs(mode["height"] - safe_h) <= max(2, top_inset):
        labels.append(f"{FLGreen}[near Derived safe]{CRst}")
    return " ".join(labels)

def _format_mode(mode: dict, did: Optional[int] = None) -> str:
    refresh = f"{mode['refresh']:.0f}Hz" if mode["refresh"] > 0 else "?Hz"
    pixel = ""
    if mode["pixel_width"] != mode["width"] or mode["pixel_height"] != mode["height"]:
        pixel = f"  pixels:{mode['pixel_width']}x{mode['pixel_height']}"
    labels = _mode_source_labels(did, mode)
    label_text = f" {labels}" if labels else ""
    return f"{mode['width']}x{mode['height']} @ {refresh}{label_text}{pixel}"

def print_resolution_modes(did: int) -> list[dict]:
    modes = _get_display_modes(did)
    if not modes:
        print(f"{FGray}  No display modes returned for this display.{CRst}\n")
        return []

    cur_id = _current_mode_id(did)
    print(f"{FLYellow}  Available resolution modes:{CRst}")
    for idx, mode in enumerate(modes):
        marker = f" {FLGreen}<-- current{CRst}" if cur_id is not None and mode["id"] == cur_id else ""
        print(f"    {FLYellow}[{idx:>2}]{CRst} mode:{mode['id']:<5} {_format_mode(mode, did)}{marker}")
    return modes

def _set_resolution_mode(did: int, mode) -> bool:
    config = ctypes.c_void_p(0)
    err = CGBeginDisplayConfiguration(ctypes.byref(config))
    if err != 0:
        print(f"{FLRed}  -> CGBeginDisplayConfiguration failed: error {err}{CRst}\n")
        return False

    err = CGConfigureDisplayWithDisplayMode(config, did, mode, 0)
    if err != 0:
        CGCancelDisplayConfiguration(config)
        print(f"{FLRed}  -> CGConfigureDisplayWithDisplayMode failed: error {err}{CRst}\n")
        return False

    err = CGCompleteDisplayConfiguration(config, _CG_CONFIGURE_FOR_SESSION)
    if err == 0:
        return True

    print(f"{FLRed}  -> CGCompleteDisplayConfiguration failed: error {err}{CRst}\n")
    return False

def set_resolution(displays: list[int]) -> bool:
    try:
        choice = input(f"{FLYellow}  Select display index (or Enter to cancel): {CRst}").strip()
        if not choice:
            return False
        idx = int(choice)
        if idx < 0 or idx >= len(displays):
            print(f"{FLRed}  Invalid selection.{CRst}\n")
            return False
    except (ValueError, EOFError):
        return False

    did = displays[idx]
    info = get_display_info(did)

    if not info['is_active']:
        print(f"{FLRed}  Display is inactive. Cannot set resolution on an inactive display.{CRst}\n")
        return False

    print(f"\n{FLYellow}  Display: {info['product_name'] or f'Display {did}'}{CRst}")
    print(f"  Current: {FLCyan}{info['width']}x{info['height']}{CRst} @ {FLCyan}{info['refresh']}{CRst}")
    print(f"{FGray}  Note: modes are for the current rotation; rotate first if needed.{CRst}")

    modes = print_resolution_modes(did)
    if not modes:
        return False

    try:
        choice = input(f"\n{FLYellow}  Select mode index (or Enter to cancel): {CRst}").strip()
        if not choice:
            return False
        mode_idx = int(choice)
        if mode_idx < 0 or mode_idx >= len(modes):
            print(f"{FLRed}  Invalid mode selection.{CRst}\n")
            return False
    except (ValueError, EOFError):
        return False

    target = modes[mode_idx]
    print(f"{FLYellow}  Target mode: {FLMagenta}{_format_mode(target, did)}{CRst}")
    try:
        confirm = input(f"  {FLYellow}Apply for current session? (y/N): {CRst}").strip().lower()
    except EOFError:
        print(f"{FGray}  Canceled.{CRst}\n")
        return False
    if confirm not in ("y", "yes"):
        print(f"{FGray}  Canceled.{CRst}\n")
        return False

    print(f"{FLYellow}  -> Setting resolution...{CRst}")
    if _set_resolution_mode(did, target["mode"]):
        print(f"{FLGreen}  -> Resolution set: {_format_mode(target, did)}{CRst}\n")
        return True
    return False


#============ 功能：亮度 ===========
def _brightness_get_builtin(did: int) -> Optional[Tuple[float, str]]:
    """Read built-in brightness. Returns (0.0-1.0, display_str) or None."""
    if not DSGetDisplayBrightness:
        return None
    b = ctypes.c_float(-1)
    err = DSGetDisplayBrightness(did, ctypes.byref(b))
    if err == 0 and b.value >= 0:
        return (b.value, f"{int(b.value * 100)}%")
    return None

def _brightness_set_builtin(did: int, target: float) -> bool:
    """Set built-in brightness (0.0-1.0)."""
    return bool(DSSetDisplayBrightness) and DSSetDisplayBrightness(did, target) == 0

def _brightness_get_ddc(did: int) -> Optional[Tuple[int, int, str]]:
    """Read DDC/CI brightness. Returns (current, max, display_str) or None."""
    ddc_svc = _get_ddc_service(did)
    if not ddc_svc:
        return None
    result = _ddc_read(ddc_svc, _DDC_BRIGHTNESS_CMD)
    if result:
        cur, mx = result
        return (cur, mx, f"{int(cur / mx * 100)}%")
    return None

def _brightness_set_ddc(did: int, target_pct: int) -> bool:
    """Set DDC/CI brightness (0-100 percentage)."""
    ddc_svc = _get_ddc_service(did)
    if not ddc_svc:
        return False
    result = _ddc_read(ddc_svc, _DDC_BRIGHTNESS_CMD)
    mx = result[1] if result else _DDC_DEFAULT_MAX
    target_val = int(mx * target_pct / 100)
    return _ddc_write(ddc_svc, _DDC_BRIGHTNESS_CMD, target_val)


def adjust_brightness(displays: list[int]) -> bool:
    try:
        choice = input(f"{FLYellow}  Select display index (or Enter to cancel): {CRst}").strip()
        if not choice:
            return False
        idx = int(choice)
        if idx < 0 or idx >= len(displays):
            print(f"{FLRed}  Invalid selection.{CRst}\n")
            return False
    except (ValueError, EOFError):
        return False

    did = displays[idx]
    info = get_display_info(did)

    if not info['is_active']:
        print(f"{FLRed}  Display is inactive. Cannot adjust brightness on an inactive display.{CRst}\n")
        return False

    if info['is_builtin']:
        print(f"{FLYellow}  Built-in display brightness:{CRst}")
        br = _brightness_get_builtin(did)
        if br:
            _current, disp_str = br
            print(f"{FLYellow}     Current: {FLMagenta}{disp_str}{CRst}")
        else:
            print(f"{FGray}     Reading unavailable.{CRst}")
            return False

        print(f"{FLYellow}  Enter new brightness (0-100, or Enter to cancel):{CRst} ", end="")
        try:
            choice = input().strip()
            if not choice:
                return False
            val = int(choice)
            if val < 0 or val > 100:
                print(f"{FLRed}  Value must be between 0 and 100.{CRst}\n")
                return False
        except (ValueError, EOFError):
            return False

        if _brightness_set_builtin(did, val / 100.0):
            print(f"{FLGreen}  -> Brightness set to {val}%.{CRst}")
            confirm = _brightness_get_builtin(did)
            if confirm:
                print(f"{FLGreen}     Verified: {confirm[1]}{CRst}")
            print()
            return True
        else:
            print(f"{FLRed}  -> Failed to set brightness.{CRst}\n")
            return False

    else:
        print(f"{FLYellow}  External display brightness (DDC/CI):{CRst}")
        br = _brightness_get_ddc(did)
        if br:
            cur, mx, disp_str = br
            print(f"{FLYellow}     Current: {FLMagenta}{disp_str}{CRst}  (raw: {cur}/{mx})")
        else:
            if not _get_ddc_service(did):
                print(f"{FGray}     DDC/CI not available for this display.{CRst}")
                return False
            print(f"{FGray}     Current brightness is not readable; write-only DDC/CI is available.{CRst}")

        print(f"{FLYellow}  Enter new brightness (0-100, or Enter to cancel):{CRst} ", end="")
        try:
            choice = input().strip()
            if not choice:
                return False
            val = int(choice)
            if val < 0 or val > 100:
                print(f"{FLRed}  Value must be between 0 and 100.{CRst}\n")
                return False
        except (ValueError, EOFError):
            return False

        if _brightness_set_ddc(did, val):
            print(f"{FLGreen}  -> Brightness set to {val}%.{CRst}")
            time.sleep(0.3)
            confirm = _brightness_get_ddc(did)
            if confirm:
                print(f"{FLGreen}     Verified: {confirm[2]}{CRst}")
            else:
                print(f"{FGray}     Verification skipped: this display does not report readable brightness.{CRst}")
            print()
            return True
        else:
            print(f"{FLRed}  -> DDC/CI write failed.{CRst}\n")
            return False


#============ 入口 ===========
def _pause():
    try:
        input(f"{FGray}  Press Enter to continue...{CRst}")
    except EOFError:
        print()

def _pause_before_list():
    try:
        input(f"{FGray}  Press Enter to return to the display list...{CRst}")
    except EOFError:
        print()

def main():
    Utils.print_banner("SCREEN UTILS TOOL")

    displays = get_all_displays()
    if not displays:
        print(f"{FLRed}ERROR: No displays found.{CRst}\n")
        sys.exit(1)

    # --list / --list-only: print display list and exit
    if "--list" in sys.argv or "--list-only" in sys.argv:
        print_display_list(displays)
        return

    # --info / --ddc-ci-info: dump DDC/CI info and exit
    if "--info" in sys.argv or "--ddc-ci-info" in sys.argv:
        print_display_list(displays)
        print_ddc_info(displays)
        return

    # --toggle / --toggle-built-in: toggle built-in display and exit (no listing)
    if "--toggle" in sys.argv or "--toggle-built-in" in sys.argv:
        toggle_builtin_display(displays, skip_confirm=True)
        return

    print(f"{FLCyan}{'─' * 52}{CRst}")
    print_display_list(displays)

    _MAIN_OPTIONS = [
        MenuOption(["L"], "List displays"),
        MenuOption(["R"], "Rotate display      (0°, 90°, 180°, 270°)"),
        MenuOption(["S"], "Set resolution"),
        MenuOption(["B"], "Adjust brightness"),
        MenuOption(["D"], "Dump DDC info"),
        MenuOption(["C"], "Color mode diagnostics"),
        MenuOption(["F"], "RGB output override"),
        MenuOption(["T"], "Toggle built-in display"),
        MenuOption(["Q"], "Quit"),
    ]

    while True:
        choice = Menu.select(_MAIN_OPTIONS, prompt="Choice")
        if choice is None:
            Utils.print_exit_message("Bye.")
            break

        if choice == 'L':
            print_display_list(displays)

        elif choice == 'R':
            changed = set_rotation(displays)
            _pause_before_list() if changed else _pause()

        elif choice == 'S':
            changed = set_resolution(displays)
            _pause_before_list() if changed else _pause()

        elif choice == 'B':
            changed = adjust_brightness(displays)
            _pause_before_list() if changed else _pause()

        elif choice == 'D':
            if print_ddc_info(displays) is False:
                _pause()

        elif choice == 'C':
            if print_color_mode_info(displays) is False:
                _pause()

        elif choice == 'F':
            changed = manage_rgb_override(displays)
            _pause_before_list() if changed else _pause()

        elif choice == 'T':
            changed = toggle_builtin_display(displays, skip_confirm=True)
            _pause_before_list() if changed else _pause()

        elif choice == 'Q':
            Utils.print_exit_message("Bye.")
            break

        # 操作完成后重新打印屏幕信息
        if choice in ('R', 'S', 'B', 'F', 'T'):
            displays = get_all_displays()
            print_display_list(displays)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
