# Keyboard names and codes

[Utility index](../README.md)

Implementation: [keyboard.py](../keyboard.py).

## API reference

| Need | Use |
| --- | --- |
| Normalize keyboard names | `Keyboard.normalize_name(name, collapse_modifiers=False) -> str`; keeps left/right identity by default, True folds modifiers for hotkey matching; empty input becomes `?` |
| Windows key and scan-code lookup | `Keyboard.windows_key_name(vk, scan_code=None)`, `windows_virtual_key(name) -> int \| None`, `windows_scan_name(scan_code)`, `windows_scan_code(name) -> WindowsScanCode \| None`; PC set-1 US base labels plus F1-F24, ISO/JIS/Korean extras and media keys; retains E0/keypad and Korean *_legacy distinctions. Shared IME VKs return kana_or_hangul/kanji_or_hanja unless known scan pairs disambiguate them. Unknown scan names return None; labels do not imply registry support |
| Scan-code representation | `WindowsScanCode(code, prefix=ScanCodePrefix.NONE)`; immutable byte plus NONE/E0/E1 prefix, `.value` is the encoded word, `from_value(word)` validates it, `from_hook(scan_code, flags)` preserves the hook's E0 flag without inferring E1 |
| Keyboard selector catalog | `Keyboard.windows_scan_entries() -> tuple[tuple[str, WindowsScanCode], ...]`; immutable known physical labels and regional aliases sorted by code/name, no OS calls; multiple names may share a code, unknown words and Disable are not included |
| Other platform key codes | `Keyboard.macos_key_name(vk, chars=None)`, `macos_virtual_key(name) -> int \| None`, `macos_media_name(code) -> str \| None`, `hid_usage_name(usage)`, `x11_keysym_name(name)`; HID usages refer specifically to keyboard/keypad page 0x07, including International1-9 and LANG1-9; they are not Windows scan words |

## Code spaces and aliases

Windows virtual keys, Windows scan words, macOS codes and USB HID usages are
distinct code spaces. Labels describe physical keys, not keyboard-layout text
or guaranteed registry-remapping support. Importing utils does not load
Quartz/Xlib, install hooks or change the registry.

Internal `_SCAN_CODE_ALIASES` preserves regional names sharing a scan word:
JIS zenkaku_hankaku/eisu use 0029/003A; USB lang5 uses 0076, also F24. Reverse
lookup retains the default US label, so aliases need not round-trip by name.
`_WIN_VK_ALIASES` and `_WIN_IME_SCAN_NAMES` keep shared IME VKs separate from
physical identity. OEM_102 names a VK, not a fixed ISO/JIS position.
Never strip the high bit of Korean F1/F2 language scan bytes; see the module's
source references and release-only caveats. Run `test/test_keyboard*.py`.

Application internals live in the
[hook viewer README](../../tools/others/keyboard-hook-viewer/README.md) and
[remapper README](../../tools/windows/keyboard-remapper/README.md).
