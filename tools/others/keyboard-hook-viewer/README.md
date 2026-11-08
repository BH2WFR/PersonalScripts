# Keyboard hook viewer internals

**Responsible use:** Only for legitimate keyboard testing, custom hotkeys and
authorized automation. Obtain permission from affected users. Do not use for
covert surveillance, credential collection or other unauthorized activity.
Users are responsible for their use and its consequences.

Run `../keyboard-hook-viewer.py` directly or select it in `run-script.py`.
The entry loads this package as `personal_keyboard_hook_viewer`; the launcher
and compiler list only that entry. Nuitka/PyInstaller stage the package using
the same alias. No new dependencies are introduced by the split.

| Module | Responsibility |
| --- | --- |
| `app.py` | Help, device display and the interactive monitor lifecycle |
| `models.py` | Event/device/window dataclasses, hotkeys and backend protocols |
| `runtime.py` | Event dispatch, callback registration and held/toggled state |
| `ui.py` | Terminal formatting, device labels and foreground-window display |
| `devices.py` | Read-only input-device enumeration |
| `backend.py` | Lazy platform selection |
| `windows.py` | Windows hooks, input controller and foreground window |
| `macos.py` | CGEvent/IOHID hooks, input controller and foreground window |
| `x11.py` | XRecord hooks, XTest controller and foreground window |
| `api.py` | Programmatic monitoring and input-sending convenience functions |

Key-name aliases, Windows virtual keys and scan codes, macOS keycodes/media
codes, USB HID page-0x07 usages and X11 keysym spellings live in
`utils/keyboard.py`. These code spaces are distinct. Importing the utility
uses no native API and does not require Quartz or Xlib. Common PC scan-code
labels describe US physical positions; they are not keyboard-layout text.
Unknown mappings remain unknown. Pause's special sequence is not included in
the common scan table; an E1 word is representable but is not inferred from
the Windows hook's E0 flag. This package does not write the registry.

`KeyEvent.name` retains generic hotkey names such as `ctrl` for callbacks.
`raw_name` retains sided identity, `raw_vk` retains the backend's original code,
and Windows also supplies `scan_code` and `raw_flags`. On macOS the original
code is a HID usage for IOHID events or a CGEvent/media code for those sources.
The terminal displays sided names and Windows scan-code words. Existing
lock-key hotkeys keep their toggle-state behavior; callbacks for lock toggles
receive a logical press/release pair, rather than raw hardware transitions.

Windows scroll callbacks use integer `(dx, dy)` steps: positive
means right/up, negative means left/down. Nonzero deltas smaller than 120 native
units produce one signed step; larger magnitudes are truncated to whole steps
symmetrically. Zero deltas are ignored. This is per-event direction monitoring,
not accumulated high-resolution scrolling or a physical-distance measurement.
The terminal shows one `scroll (x, y)` pair. Windows uses the original signed
wheel units before step conversion (120 units per notch), for example
`scroll (0, -30) down`. macOS and X11 retain their backend values.
Every platform appends direction labels in cyan (`FCyan`): `up`, `down`, `left`,
or `right`; diagonal events include both, such as `up+right`. Zero movement is
labelled `none`. Direction labels account for the existing left-positive
horizontal values on macOS/X11 and right-positive values on Windows; vertical
values are up-positive everywhere. These describe scroll events, not finger
motion or an application's resulting content movement. Callback values remain
unchanged on every platform.
When monitoring a remote session from Windows App on a Mac, these values are
the wheel deltas received by Windows. Pinch is visible here only if translated
to wheel input; this hook cannot recover native macOS pinch deltas or zoom scale.

After loading the entry with `importlib.util`, call `entry.load_app()` to
register the package. Then import `personal_keyboard_hook_viewer.api` for
`setup`, `Hotkey`, `Key`, `press`, `release`, `tap`, `hotkey`, `send`, mouse
operations and `get_foreground_window`. The entry itself only exposes loading
and main; shared keyboard conversions should be imported from utils.

Requirements remain standard-library ctypes on Windows,
`pyobjc-framework-Quartz` on macOS, and `python-xlib` on Linux X11.
macOS needs Input Monitoring/Accessibility permission; Wayland is unsupported.
Import and `--help` do not start hooks or send input.

Run `conda run -n base python -m unittest discover -s test -p "test_keyboard*.py"`.
Tests exercise synthetic events, mapping distinctions, discovery and compiler
staging without capturing real keystrokes or generating input.
