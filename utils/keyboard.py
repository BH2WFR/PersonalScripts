"""Keyboard names and platform key-code tables; no hooks or import-time OS calls.

Standard-library only. Use the Keyboard class through ``from utils import *``.

The scan table includes PC set-1 positions, F1-F24, ISO/JIS/Korean extras and
media keys. Scan words, Windows virtual keys and USB HID usages are separate
code spaces; none of these tables guarantees registry-remapping support.

Regional naming notes (all code values below are hexadecimal):
    - Hangul/Hanja use 0072/0071; F2/F1 are their legacy-message forms, kept
      as hangul_legacy/hanja_legacy rather than silently changing the bytes.
      Windows documents these language usages as release-only events.
    - JIS International1 (ro, also Brazilian /) is 0073; International3
      (yen) is 007D. Kana, convert and nonconvert are 0070, 0079 and 007B.
    - ISO's extra key is 0056, not the ANSI backslash/ISO hash position 002B.
      OEM_102 is a virtual-key identity, not a universal physical scan code.
    - JIS hankaku/zenkaku and eisu share the US grave/Caps Lock positions
      0029/003A. Name-to-scan aliases preserve the default reverse labels.
    - 0076 is F24 and also USB LANG5 (zenkaku_hankaku_usb). A scan word
      alone cannot distinguish those usages; reverse lookup defaults to f24.
    - VK 15 is shared by Kana/Hangul; VK 19 by Kanji/Hanja. Without a matching
      scan code, VK naming returns kana_or_hangul / kanji_or_hanja.

Sources (numeric facts, not copied implementation):
    https://learn.microsoft.com/windows/win32/inputdev/about-keyboard-input
    https://learn.microsoft.com/windows/win32/inputdev/virtual-key-codes
    https://www.usb.org/sites/default/files/hut1_21_0.pdf (section 10)
    https://github.com/microsoft/Windows-driver-samples/blob/main/input/layout/fe_kbds/jpn/106/kbd106.c
    https://github.com/microsoft/PowerToys/blob/main/src/common/interop/keyboard_layout.cpp

Intended for legitimate keyboard testing, custom hotkeys and authorized
automation. Do not use in covert surveillance, credential collection or other
unauthorized activity. Users are responsible for their use and its consequences.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from enum import IntEnum


class ScanCodePrefix(IntEnum):
    """Prefix byte of a Windows scan-code word (not a USB HID usage)."""

    NONE = 0
    E0 = 0xE0
    E1 = 0xE1


@dataclass(frozen=True)
class WindowsScanCode:
    """A scan-code byte and optional E0/E1 prefix, independent of virtual keys.

    Args:
        code: Unsigned byte, including zero for unknown/disabled representations.
        prefix: NONE, E0 or E1; defaults to NONE.

    Raises:
        ValueError: The code or prefix is invalid.

    This stores a code word, not a complete make/break sequence. In particular,
    Pause/PrintScreen special sequences need interpretation by the caller;
    having a word does not imply that registry remapping supports the key.
    """

    code: int
    prefix: ScanCodePrefix = ScanCodePrefix.NONE

    def __post_init__(self) -> None:
        if not isinstance(self.code, int) or isinstance(self.code, bool) or not 0 <= self.code <= 0xFF:
            raise ValueError("Scan code must be an integer byte (0..255).")
        if not isinstance(self.prefix, ScanCodePrefix):
            raise ValueError("Prefix must be a ScanCodePrefix member.")

    @property
    def value(self) -> int:
        """Return the 16-bit word with prefix in the high byte."""
        return (int(self.prefix) << 8) | self.code

    @classmethod
    def from_value(cls, value: int) -> WindowsScanCode:
        """Decode an unsigned word; reject unknown prefixes with ValueError.

        Args:
            value: Integer in 0..65535, with prefix 00, E0 or E1.

        Returns:
            Validated immutable scan-code value; no OS calls.
        """
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFF:
            raise ValueError("Scan-code word must be an integer in 0..65535.")
        return cls(value & 0xFF, ScanCodePrefix(value >> 8))

    @classmethod
    def from_hook(cls, scan_code: int, flags: int) -> WindowsScanCode:
        """Preserve a KBDLLHOOKSTRUCT byte and its LLKHF_EXTENDED flag.

        Args:
            scan_code: Native scanCode byte, 0..255.
            flags: Native flags; bit 0 indicates the E0 prefix.

        Returns:
            Code with E0 or NONE. E1 cannot be inferred from the extended flag.

        Raises:
            ValueError: scan_code is not a byte.
        """
        return cls(scan_code, ScanCodePrefix.E0 if flags & 1 else ScanCodePrefix.NONE)

    def __str__(self) -> str:
        return f"0x{self.value:04X}"


_X11_NORM: dict[str, str] = {
    "Shift_L": "shift",       "Shift_R": "shift",
    "Control_L": "ctrl",      "Control_R": "ctrl",
    "Alt_L": "alt",           "Alt_R": "alt",
    "Meta_L": "super",        "Meta_R": "super",
    "Super_L": "super",       "Super_R": "super",
    "Caps_Lock": "caps_lock", "Num_Lock": "num_lock",
    "Scroll_Lock": "scroll_lock",
    "Return": "enter",        "Escape": "esc",
    "BackSpace": "backspace", "Delete": "delete",
    "Tab": "tab",             "ISO_Left_Tab": "tab",
    "space": "space",
    "Home": "home",           "End": "end",
    "Page_Up": "page_up",     "Page_Down": "page_down",
    "Left": "left",           "Right": "right",
    "Up": "up",               "Down": "down",
    "Insert": "insert",       "Print": "print_screen",
    "Pause": "pause",         "Menu": "menu",
    "Multi_key": "compose",
    "KP_Enter": "kp_enter",   "KP_Add": "kp+",
    "KP_Subtract": "kp-",     "KP_Multiply": "kp*",
    "KP_Divide": "kp/",       "KP_Decimal": "kp.",
    "KP_0": "kp0", "KP_1": "kp1", "KP_2": "kp2", "KP_3": "kp3", "KP_4": "kp4",
    "KP_5": "kp5", "KP_6": "kp6", "KP_7": "kp7", "KP_8": "kp8", "KP_9": "kp9",
    "XF86AudioPlay": "media_play_pause",
    "XF86AudioStop": "media_stop",
    "XF86AudioPrev": "media_previous",
    "XF86AudioNext": "media_next",
    "XF86AudioMute": "media_volume_mute",
    "XF86AudioLowerVolume": "media_volume_down",
    "XF86AudioRaiseVolume": "media_volume_up",
    "XF86MonBrightnessDown": "brightness_down",
    "XF86MonBrightnessUp": "brightness_up",
}

_NAME_ALIASES: dict[str, str] = {
    "caps": "caps_lock", "scroll": "scroll_lock", "num": "num_lock",
    "pageup": "page_up", "pagedown": "page_down",
    "printscreen": "print_screen", "prtscn": "print_screen",
    "volup": "media_volume_up", "voldown": "media_volume_down",
    "volmute": "media_volume_mute",
    "volume_up": "media_volume_up", "volume_down": "media_volume_down",
    "volume_mute": "media_volume_mute",
    "media_prev": "media_previous",
    "next": "media_next", "prev": "media_previous",
    "play": "media_play_pause", "stop": "media_stop",
    "return": "enter",
    "lbutton": "left", "rbutton": "right", "mbutton": "middle",
    "lshift": "shift", "rshift": "shift",
    "lctrl": "ctrl", "rctrl": "ctrl",
    "lalt": "alt", "ralt": "alt",
    "lwin": "super", "rwin": "super",
    # Physical names stay distinct even when their Windows VK values coincide.
    "iso_extra": "non_us_backslash", "iso_backslash": "non_us_backslash",
    "ro": "international1", "jis_ro": "international1",
    "yen": "international3", "jis_yen": "international3",
    "international2": "kana", "katakana_hiragana": "kana",
    "international4": "convert", "henkan": "convert",
    "international5": "nonconvert", "muhenkan": "nonconvert",
    "non_convert": "nonconvert",
    "hangeul": "hangul", "hangul_english": "hangul",
    "lang1": "hangul", "lang2": "hanja",
    "lang3": "katakana", "lang4": "hiragana",
    "lang5": "zenkaku_hankaku_usb",
    "hankaku_zenkaku": "zenkaku_hankaku",
    "eisu_toggle": "eisu", "vk_oem_102": "oem_102",
}

_VK_MAP: dict[int, str] = {
    # Modifiers
    0x38: "shift",      0x3C: "shift_r",
    0x3B: "ctrl",       0x3E: "ctrl_r",
    0x3A: "alt",        0x3D: "alt_r",
    0x37: "cmd",        0x36: "cmd_r",
    0x39: "caps_lock",
    # Navigation
    0x7B: "left",       0x7C: "right",
    0x7D: "down",       0x7E: "up",
    0x73: "home",       0x77: "end",
    0x74: "page_up",    0x79: "page_down",
    # Editing
    0x33: "backspace",  0x75: "delete",
    0x24: "enter",      0x35: "esc",
    0x30: "tab",        0x31: "space",
    # Function keys
    0x7A: "F1",  0x78: "F2",  0x63: "F3",  0x76: "F4",
    0x60: "F5",  0x61: "F6",  0x62: "F7",  0x64: "F8",
    0x65: "F9",  0x6D: "F10", 0x67: "F11", 0x6F: "F12",
    0x69: "F13", 0x6B: "F14", 0x71: "F15", 0x6A: "F16",
    0x40: "F17", 0x4F: "F18", 0x50: "F19", 0x5A: "F20",
    # fn / globe
    63: "fn",           179: "fn/globe",
    # Keypad
    0x41: "kp.",        0x43: "kp*",        0x45: "kp+",
    0x47: "kp_clear",   0x4B: "kp/",        0x4C: "kp_enter",
    0x4E: "kp-",        0x51: "kp=",
    0x52: "kp0",        0x53: "kp1",        0x54: "kp2",
    0x55: "kp3",        0x56: "kp4",        0x57: "kp5",
    0x58: "kp6",        0x59: "kp7",        0x5B: "kp8",
    0x5C: "kp9",
    # Misc
    0x72: "help",       0x6E: "menu",
    0x4A: "fwd_del",
}

_HID_KEYBOARD_USAGE_MAP: dict[int, str] = {
    **{usage: chr(ord("a") + usage - 0x04) for usage in range(0x04, 0x1E)},
    **{
        usage: str((usage - 0x1D) % 10)
        for usage in range(0x1E, 0x28)
    },
    0x28: "enter", 0x29: "esc", 0x2A: "backspace", 0x2B: "tab",
    0x2C: "space", 0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]",
    0x31: "\\", 0x32: "non_us_hash", 0x33: ";", 0x34: "'",
    0x35: "`", 0x36: ",", 0x37: ".", 0x38: "/",
    0x39: "caps_lock",
    **{usage: f"F{usage - 0x39}" for usage in range(0x3A, 0x46)},
    0x46: "print_screen", 0x47: "scroll_lock", 0x48: "pause",
    0x49: "insert", 0x4A: "home", 0x4B: "page_up", 0x4C: "delete",
    0x4D: "end", 0x4E: "page_down", 0x4F: "right", 0x50: "left",
    0x51: "down", 0x52: "up", 0x53: "num_lock", 0x54: "kp/",
    0x55: "kp*", 0x56: "kp-", 0x57: "kp+", 0x58: "kp_enter",
    **{usage: f"kp{usage - 0x58}" for usage in range(0x59, 0x62)},
    0x62: "kp0", 0x63: "kp.", 0x64: "non_us_backslash", 0x65: "menu",
    0x66: "power", 0x67: "kp=",
    **{usage: f"F{usage - 0x5B}" for usage in range(0x68, 0x74)},
    0x85: "kp,",
    **{usage: f"international{usage - 0x86}" for usage in range(0x87, 0x90)},
    **{usage: f"lang{usage - 0x8F}" for usage in range(0x90, 0x99)},
    0xE0: "ctrl", 0xE1: "shift", 0xE2: "alt", 0xE3: "cmd",
    0xE4: "ctrl_r", 0xE5: "shift_r", 0xE6: "alt_r", 0xE7: "cmd_r",
}

_CHAR_TO_VK_US: dict[str, int] = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B,
    "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11,
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17,
    "=": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D,
    "]": 0x1E, "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23,
    "l": 0x25, "j": 0x26, "'": 0x27, "k": 0x28, ";": 0x29, "\\": 0x2A,
    ",": 0x2B, "/": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F,
    "`": 0x32,
}

_WIN_VK_MAP: dict[int, str] = {
    0x01: "lbutton", 0x02: "rbutton", 0x03: "cancel", 0x04: "mbutton",
    0x05: "xbutton1", 0x06: "xbutton2",
    0x08: "backspace", 0x09: "tab",
    0x0C: "clear", 0x0D: "enter",
    0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x13: "pause",
    0x14: "caps_lock",
    0x15: "kana_or_hangul", 0x16: "ime_on", 0x17: "junja", 0x18: "final",
    0x19: "kanji_or_hanja", 0x1A: "ime_off",
    0x1B: "esc",
    0x1C: "convert", 0x1D: "nonconvert", 0x1E: "ime_accept", 0x1F: "ime_mode_change",
    0x20: "space", 0x21: "page_up", 0x22: "page_down",
    0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x29: "select", 0x2A: "print", 0x2B: "execute",
    0x2C: "print_screen", 0x2D: "insert", 0x2E: "delete",
    0x2F: "help",
    0x5B: "lwin", 0x5C: "rwin", 0x5D: "apps",
    0x5F: "sleep",
    0x60: "kp0",   0x61: "kp1",   0x62: "kp2",   0x63: "kp3",
    0x64: "kp4",   0x65: "kp5",   0x66: "kp6",   0x67: "kp7",
    0x68: "kp8",   0x69: "kp9",
    0x6A: "kp*",   0x6B: "kp+",
    0x6C: "separator",
    0x6D: "kp-",   0x6E: "kp.",   0x6F: "kp/",
    0x70: "F1",  0x71: "F2",  0x72: "F3",  0x73: "F4",
    0x74: "F5",  0x75: "F6",  0x76: "F7",  0x77: "F8",
    0x78: "F9",  0x79: "F10", 0x7A: "F11", 0x7B: "F12",
    0x7C: "F13", 0x7D: "F14", 0x7E: "F15", 0x7F: "F16",
    0x80: "F17", 0x81: "F18", 0x82: "F19", 0x83: "F20",
    0x84: "F21", 0x85: "F22", 0x86: "F23", 0x87: "F24",
    0x90: "num_lock", 0x91: "scroll_lock",
    0xA0: "lshift",  0xA1: "rshift",
    0xA2: "lctrl",   0xA3: "rctrl",
    0xA4: "lalt",    0xA5: "ralt",
    0xA6: "browser_back", 0xA7: "browser_forward",
    0xA8: "browser_refresh", 0xA9: "browser_stop",
    0xAA: "browser_search", 0xAB: "browser_favorites",
    0xAC: "browser_home",
    0xAD: "volume_mute", 0xAE: "volume_down", 0xAF: "volume_up",
    0xB0: "media_next", 0xB1: "media_prev", 0xB2: "media_stop",
    0xB3: "media_play_pause",
    0xB4: "launch_mail", 0xB5: "launch_media_select",
    0xB6: "launch_app1", 0xB7: "launch_app2",
}

# These names intentionally share VKs, but must not share physical scan aliases.
_WIN_VK_ALIASES: dict[str, int] = {
    "kana": 0x15, "hangul": 0x15, "hangul_legacy": 0x15,
    "kanji": 0x19, "hanja": 0x19, "hanja_legacy": 0x19,
    "oem_102": 0xE2,
}
_VK_OEM_102 = _WIN_VK_ALIASES["oem_102"]
_WIN_IME_SCAN_NAMES: dict[tuple[int, int], str] = {
    (0x15, 0x0070): "kana", (0x15, 0x0072): "hangul",
    (0x15, 0x00F2): "hangul", (0x19, 0x0071): "hanja",
    (0x19, 0x00F1): "hanja",
}

_NX_KEYTYPE_SOUND_UP, _NX_KEYTYPE_SOUND_DOWN = 0, 1
_NX_KEYTYPE_MUTE, _NX_KEYTYPE_EJECT = 7, 14
_NX_KEYTYPE_PLAY, _NX_KEYTYPE_NEXT, _NX_KEYTYPE_PREVIOUS = 16, 17, 18
_NX_KEYTYPE_REWIND, _NX_KEYTYPE_FAST = 19, 20

_MEDIA_KEY_MAP: dict[int, str] = {
    _NX_KEYTYPE_SOUND_UP: "media_volume_up",
    _NX_KEYTYPE_SOUND_DOWN: "media_volume_down",
    _NX_KEYTYPE_MUTE: "media_volume_mute",
    _NX_KEYTYPE_EJECT: "media_eject",
    _NX_KEYTYPE_PLAY: "media_play_pause",
    _NX_KEYTYPE_NEXT: "media_next",
    _NX_KEYTYPE_PREVIOUS: "media_previous",
    _NX_KEYTYPE_REWIND: "media_rewind",
    _NX_KEYTYPE_FAST: "media_fast_forward",
}

_X11_SEND: dict[str, str] = {
    "enter": "Return", "esc": "Escape", "backspace": "BackSpace",
    "tab": "Tab", "space": "space",
    "caps_lock": "Caps_Lock", "num_lock": "Num_Lock",
    "scroll_lock": "Scroll_Lock",
    "page_up": "Page_Up", "page_down": "Page_Down",
    "home": "Home", "end": "End",
    "left": "Left", "right": "Right", "up": "Up", "down": "Down",
    "insert": "Insert", "delete": "Delete",
    "print_screen": "Print", "pause": "Pause",
    "shift": "Shift_L", "ctrl": "Control_L", "alt": "Alt_L",
    "super": "Super_L", "cmd": "Super_L",
    "kp_enter": "KP_Enter", "kp+": "KP_Add", "kp-": "KP_Subtract",
    "kp*": "KP_Multiply", "kp/": "KP_Divide", "kp.": "KP_Decimal",
    "media_play_pause": "XF86AudioPlay",
    "media_stop": "XF86AudioStop",
    "media_next": "XF86AudioNext",
    "media_previous": "XF86AudioPrev",
    "media_volume_mute": "XF86AudioMute",
    "media_volume_down": "XF86AudioLowerVolume",
    "media_volume_up": "XF86AudioRaiseVolume",
}


# Physical modifier identity is kept separately from generic hotkey matching.
_SIDED_NAMES: dict[str, str] = {
    "lshift": "left_shift", "shift_l": "left_shift", "shift_r": "right_shift", "rshift": "right_shift",
    "lctrl": "left_ctrl", "control_l": "left_ctrl", "ctrl_l": "left_ctrl",
    "rctrl": "right_ctrl", "control_r": "right_ctrl", "ctrl_r": "right_ctrl",
    "lalt": "left_alt", "alt_l": "left_alt", "ralt": "right_alt", "alt_r": "right_alt",
    "lwin": "left_super", "super_l": "left_super", "meta_l": "left_super", "cmd_l": "left_super",
    "rwin": "right_super", "super_r": "right_super", "meta_r": "right_super", "cmd_r": "right_super",
}
_GENERIC_MODIFIERS: dict[str, str] = {
    f"{side}_{name}": name for side in ("left", "right") for name in ("shift", "ctrl", "alt", "super")
}
_X11_LOWER: dict[str, str] = {name.lower(): value for name, value in _X11_NORM.items()}
_SIDE_TO_X11: dict[str, str] = {
    "left_shift": "Shift_L", "right_shift": "Shift_R",
    "left_ctrl": "Control_L", "right_ctrl": "Control_R",
    "left_alt": "Alt_L", "right_alt": "Alt_R",
    "left_super": "Super_L", "right_super": "Super_R",
}
_SCAN_NAMES: dict[int, str] = {
    0x01: "esc", **{i + 0x02: char for i, char in enumerate("1234567890-=")},
    0x0E: "backspace", 0x0F: "tab",
    **{i + 0x10: char for i, char in enumerate("qwertyuiop[]")},
    0x1C: "enter", 0x1D: "left_ctrl",
    **{i + 0x1E: char for i, char in enumerate("asdfghjkl;'`")},
    0x2A: "left_shift", 0x2B: "\\",
    **{i + 0x2C: char for i, char in enumerate("zxcvbnm,./")},
    0x36: "right_shift", 0x37: "kp*", 0x38: "left_alt", 0x39: "space", 0x3A: "caps_lock",
    **{i + 0x3B: f"f{i + 1}" for i in range(10)},
    0x45: "num_lock", 0x46: "scroll_lock", 0x47: "kp7", 0x48: "kp8", 0x49: "kp9",
    0x4A: "kp-", 0x4B: "kp4", 0x4C: "kp5", 0x4D: "kp6", 0x4E: "kp+",
    0x4F: "kp1", 0x50: "kp2", 0x51: "kp3", 0x52: "kp0", 0x53: "kp.",
    0x56: "non_us_backslash", 0x57: "f11", 0x58: "f12",
    0x59: "kp=", 0x5C: "international6",
    **{i + 0x64: f"f{i + 13}" for i in range(11)},
    0x70: "kana", 0x71: "hanja", 0x72: "hangul", 0x73: "international1",
    # F24 is not 006F. USB LANG5 shares 0076; see the name-only aliases below.
    0x76: "f24", 0x77: "hiragana", 0x78: "katakana",
    0x79: "convert", 0x7B: "nonconvert", 0x7D: "international3", 0x7E: "kp,",
    0xF1: "hanja_legacy", 0xF2: "hangul_legacy",
    0xE010: "media_previous", 0xE019: "media_next",
    0xE01C: "kp_enter", 0xE01D: "right_ctrl",
    0xE020: "media_volume_mute", 0xE021: "launch_app2",
    0xE022: "media_play_pause", 0xE024: "media_stop",
    0xE02E: "media_volume_down", 0xE030: "media_volume_up", 0xE032: "browser_home",
    0xE035: "kp/", 0xE037: "print_screen",
    0xE038: "right_alt", 0xE047: "home", 0xE048: "up", 0xE049: "page_up",
    0xE04B: "left", 0xE04D: "right", 0xE04F: "end", 0xE050: "down",
    0xE051: "page_down", 0xE052: "insert", 0xE053: "delete",
    0xE05B: "left_super", 0xE05C: "right_super", 0xE05D: "menu",
    0xE05E: "power", 0xE05F: "sleep", 0xE063: "wake",
    0xE065: "browser_search", 0xE066: "browser_favorites", 0xE067: "browser_refresh",
    0xE068: "browser_stop", 0xE069: "browser_forward", 0xE06A: "browser_back",
    0xE06B: "launch_app1", 0xE06C: "launch_mail", 0xE06D: "launch_media_select",
}
# Regional key legends / USB usages that share another key's scan word.
# Do not normalize them to the default label: their HID/VK meanings differ.
_SCAN_CODE_ALIASES: dict[str, int] = {
    "non_us_hash": 0x002B,
    "zenkaku_hankaku": 0x0029,
    "eisu": 0x003A,
    "zenkaku_hankaku_usb": 0x0076,
}

_TO_UNICODE_NO_STATE_CHANGE = 0x04
_KEYBOARD_STATE_SIZE = 256
_CHARACTER_BUFFER_SIZE = 8


def _windows_printable_name(vk: int, scan_code: WindowsScanCode | None) -> str | None:
    """Read an unshifted layout character without consuming Windows dead keys.

    Returns None outside Windows or when the key has no printable translation.
    Bit 2 of ToUnicode flags prevents keyboard-state mutation on Windows 10
    1607+: https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-tounicode
    """
    if sys.platform != "win32":
        return None
    try:
        function = ctypes.WinDLL("user32", use_last_error=True).ToUnicode
        function.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_ubyte),
                             ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint]
        function.restype = ctypes.c_int
        state = (ctypes.c_ubyte * _KEYBOARD_STATE_SIZE)()
        buffer = ctypes.create_unicode_buffer(_CHARACTER_BUFFER_SIZE)
        count = function(vk, scan_code.code if scan_code else 0, state, buffer,
                         len(buffer), _TO_UNICODE_NO_STATE_CHANGE)
        value = "".join(buffer[:abs(count)])
        return value if value and value.isprintable() else None
    except (OSError, AttributeError):
        return None


class Keyboard:
    """Shared, side-preserving key naming and platform-code conversions.

    Table lookups are portable and use the standard library. Printable
    character fallbacks in Windows name/VK lookup use the active Windows layout.
    Scan tables use US base-position labels plus regional keys, not text input.
    Shared regional positions have one default reverse label; see module notes.
    No method installs hooks, sends input, or modifies the registry.
    """

    @staticmethod
    def normalize_name(name: str, *, collapse_modifiers: bool = False) -> str:
        """Canonicalize an alias, retaining left/right identity by default.

        Args:
            name: Platform name or user alias; whitespace is stripped.
            collapse_modifiers: True maps sided modifiers to shift/ctrl/alt/super.

        Returns:
            Lowercase name, or '?' for empty input. Unknown names are retained.
        """
        lower = name.strip().lower()
        if name == " ":
            return "space"
        if not lower:
            return "?"
        result = _SIDED_NAMES.get(lower, _NAME_ALIASES.get(lower, _X11_LOWER.get(lower, lower)))
        result = {"cmd": "super", "win": "super", "windows": "super", "control": "ctrl", "apps": "menu"}.get(result, result)
        return _GENERIC_MODIFIERS.get(result, result) if collapse_modifiers else result

    @staticmethod
    def windows_key_name(vk: int, scan_code: WindowsScanCode | None = None) -> str:
        """Name a Windows virtual key, optionally resolving physical identity.

        Args:
            vk: Virtual-key integer.
            scan_code: Optional hook scan code, distinguishing keypad Enter and
                sided modifiers, plus known Kana/Hangul and Hanja scan pairs.
                Other scan identities are available separately.

        Returns:
            Canonical key name; unknown codes use 'key(number)'. On Windows,
            otherwise unmapped printable keys use the current layout. Shared
            IME VKs without a matching scan use kana_or_hangul/kanji_or_hanja.

        Side effects:
            Printable fallback queries Windows without changing keyboard state.
        """
        if scan_code is not None:
            regional = _WIN_IME_SCAN_NAMES.get((vk, scan_code.value))
            if regional is not None:
                return regional
        if scan_code is not None and vk in (0x0D, 0x10, 0x11, 0x12):
            physical = _SCAN_NAMES.get(scan_code.value)
            if physical is not None:
                return physical
        if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
            return chr(vk).lower()
        raw = _WIN_VK_MAP.get(vk)
        if raw is not None:
            return Keyboard.normalize_name(raw)
        fallback = "oem_102" if vk == _VK_OEM_102 else f"key({vk})"
        return _windows_printable_name(vk, scan_code) or fallback

    @staticmethod
    def windows_virtual_key(name: str) -> int | None:
        """Resolve a key name to a VK; unknown names return None.

        Args:
            name: Canonical name or alias. Generic modifiers choose generic VKs;
                kp_enter shares VK_RETURN with enter (use its scan code too).
                Kana/Hangul and Kanji/Hanja share VKs but not physical identity.
                OEM_102 identifies a VK, not a specific ISO/JIS position.

        Returns:
            VK integer or None. Single printable characters may use VkKeyScanW
            on Windows; its modifier bits are deliberately not returned.

        Side effects:
            Printable fallback queries the current Windows keyboard layout.
        """
        normalized = Keyboard.normalize_name(name)
        generic = {"shift": 0x10, "ctrl": 0x11, "alt": 0x12, "super": 0x5B, "kp_enter": 0x0D}
        if normalized in generic:
            return generic[normalized]
        if normalized in _WIN_VK_ALIASES:
            return _WIN_VK_ALIASES[normalized]
        for vk, raw in _WIN_VK_MAP.items():
            if Keyboard.normalize_name(raw) == normalized:
                return vk
        if len(normalized) == 1:
            char = ord(normalized.upper()) if len(normalized.upper()) == 1 else 0
            if 0x30 <= char <= 0x39 or 0x41 <= char <= 0x5A:
                return char
            if sys.platform == "win32" and ord(normalized) <= 0xFFFF:
                function = ctypes.WinDLL("user32", use_last_error=True).VkKeyScanW
                function.argtypes = [ctypes.c_wchar]
                function.restype = ctypes.c_short
                value = function(normalized)
                return None if value == -1 else value & 0xFF
        return None

    @staticmethod
    def windows_scan_name(scan_code: WindowsScanCode) -> str:
        """Return a default PC set-1 label or 'scan(0xNNNN)'.

        Args:
            scan_code: Validated scan-code word; independent of keyboard layout.

        Returns:
            Static label, not a layout-derived character. Regional collisions
            retain US base labels: 0029 is grave, 003A caps_lock, 0076 f24.
            Legacy F1/F2 language codes have distinct *_legacy labels. No OS
            calls or registry-support checks are performed.
        """
        return _SCAN_NAMES.get(scan_code.value, f"scan({scan_code})")

    @staticmethod
    def windows_scan_code(name: str) -> WindowsScanCode | None:
        """Resolve a common PC physical key to its scan-code word.

        Args:
            name: Name or alias; generic modifiers select their left-hand key.
                Hangul/Hanja select 0072/0071; *_legacy selects F2/F1.
                zenkaku_hankaku selects JIS 0029, while lang5 or
                zenkaku_hankaku_usb selects 0076 (also F24).

        Returns:
            Scan code or None for unsupported keys (including Pause's special
            sequence). This lookup does not validate registry-remapping support.
        """
        normalized = Keyboard.normalize_name(name)
        if normalized in ("shift", "ctrl", "alt", "super"):
            normalized = f"left_{normalized}"
        if normalized in _SCAN_CODE_ALIASES:
            return WindowsScanCode.from_value(_SCAN_CODE_ALIASES[normalized])
        for value, label in _SCAN_NAMES.items():
            if label == normalized:
                return WindowsScanCode.from_value(value)
        return None

    @staticmethod
    def windows_scan_entries() -> tuple[tuple[str, WindowsScanCode], ...]:
        """Enumerate known physical labels and regional aliases for selectors.

        Returns:
            Immutable (name, scan-code) pairs sorted by code then name. Multiple
            names may share a code (for example F24 and USB LANG5). Unknown
            words and the disabled value are not included. No OS calls occur;
            entries do not guarantee support by the registry mapper.
        """
        entries = [(name, value) for value, name in _SCAN_NAMES.items()]
        entries.extend(_SCAN_CODE_ALIASES.items())
        return tuple((name, WindowsScanCode.from_value(value))
                     for name, value in sorted(entries, key=lambda item: (item[1], item[0])))

    @staticmethod
    def macos_key_name(vk: int, chars: str | None = None) -> str:
        """Name a macOS virtual key; use printable event text as fallback.

        Args:
            vk: CGEvent virtual keycode, not a Windows VK or HID usage.
            chars: Optional printable text from the event.

        Returns:
            Canonical name preserving sided modifiers, or 'key(number)'.
        """
        raw = _VK_MAP.get(vk)
        if raw in ("shift", "ctrl", "alt", "cmd"):
            raw = f"left_{'super' if raw == 'cmd' else raw}"
        if raw is not None:
            return Keyboard.normalize_name(raw)
        return chars if chars and chars.isprintable() else f"key({vk})"

    @staticmethod
    def macos_virtual_key(name: str) -> int | None:
        """Return a macOS keycode or None, using US positions for characters.

        Args:
            name: Common name or alias; generic modifiers select the left key.
        """
        normalized = Keyboard.normalize_name(name)
        if normalized in ("shift", "ctrl", "alt", "super"):
            normalized = f"left_{normalized}"
        for vk in _VK_MAP:
            if Keyboard.macos_key_name(vk) == normalized:
                return vk
        return _CHAR_TO_VK_US.get(normalized)

    @staticmethod
    def macos_media_name(code: int) -> str | None:
        """Return a macOS system-defined media-key name or None for unknown code."""
        return _MEDIA_KEY_MAP.get(code)

    @staticmethod
    def hid_usage_name(usage: int) -> str:
        """Name a USB keyboard/keypad-page (0x07) usage, keeping modifier sides.

        Args:
            usage: Usage ID within page 0x07; not a platform scan code.

        Returns:
            Canonical label or 'hid_usage(0xNN)' for unknown usages.
        """
        if 0xE0 <= usage <= 0xE7:
            side = "left" if usage < 0xE4 else "right"
            return f"{side}_{('ctrl', 'shift', 'alt', 'super')[usage % 4]}"
        return Keyboard.normalize_name(_HID_KEYBOARD_USAGE_MAP.get(usage, f"hid_usage(0x{usage:02x})"))

    @staticmethod
    def x11_keysym_name(name: str) -> str:
        """Return the X11 keysym spelling for a common name, without loading Xlib.

        Args:
            name: Common key name or alias; unknown names pass through.
        """
        normalized = Keyboard.normalize_name(name)
        if normalized.startswith("f") and normalized[1:].isdigit():
            return normalized.upper()
        if len(normalized) == 3 and normalized.startswith("kp") and normalized[-1].isdigit():
            return f"KP_{normalized[-1]}"
        return _SIDE_TO_X11.get(normalized, _X11_SEND.get(normalized, normalized))
