# Keyboard Remapper

Windows 10+ registry keyboard remapping with PySide6 and the Fusion style.
Run `../keyboard-remapper.py` directly or select `keyboard-remapper` in the launcher.
Startup requests administrator privileges before opening the editor, including
with `--read-only`, which disables registry writes while allowing draft editing.
`--help` does not request elevation, load Qt or read registry data.

## Select keys

Both the source and destination have a searchable editable dropdown. Every
entry includes its hexadecimal scan word. Search by name or code; a raw word
such as `0xE01D` is accepted. The destination additionally offers Disable
(`0x0000`). Codes are Windows scan words, not VKs, characters or USB usages.
The catalog comes from `utils.Keyboard.windows_scan_entries()`; regional aliases
can share a code, so stored mappings use the code as identity, not the label.
Unknown words are retained and displayed, not silently discarded.

Click **Capture key** on either side to listen in a visible, focused dialog.
Capture stops after one key or 20 seconds, and closing/cancelling stops it too.
Release the key, then click **Use this key** with the mouse. The dialog displays
both the captured scan word and VK. It never installs a global hook, records
text or listens while another application has focus. It reads the native
WM_KEYDOWN/WM_SYSKEYDOWN scan byte and extended flag; Korean release-only
language messages are also supported. Pause's special sequence is rejected
rather than misidentified as Num Lock. System shortcuts are not suppressed;
Fn, disabled keys and some system/IME/media keys may not reach this window.
Use the dropdown or an explicit scan word when capture is unavailable.

Existing registry remapping can change what capture observes. For example,
after Caps Lock has become F24, capture may report F24, not the original Caps
Lock. Select the original physical source from the dropdown in that case.
Capture does not reverse-engineer or undo existing mappings.

## Row order and final hexadecimal view

Drag a whole mapping row above or below another row; the insertion line marks
its destination. Reordering changes the draft and its eventual stored byte order,
not the registry immediately. Dropping in place or cancelling keeps it unchanged.
The moved row stays selected. Read-only mode still permits draft experimentation.

Expand **Final hexadecimal view (draft)** to inspect the exact pending REG_BINARY
bytes, with offsets and total length. It updates after edits, reordering, reload
and backup restore. **Copy hex bytes** copies only the space-separated bytes,
without offsets or headings. An absent value explicitly indicates deletion;
it is distinct from an existing empty map's 16-byte payload. Invalid registry
data disables dragging/copying and marks the preview unavailable.

## Save, backup and restore

Opening the editor reads only
`HKLM\SYSTEM\CurrentControlSet\Control\Keyboard Layout\Scancode Map`.
Edits, deletes, Clear all and Load backup affect the draft only. Review changes
before **Write to registry**. Machine-wide mappings affect all users and
keyboards, including sign-in; ensure you can still enter your password.

The Save confirmation includes a backup checkbox, selected by default. Clear it
to save without a backup. When selected, choose a new JSON file for the original
state; cancelling file selection cancels the save, and existing files are never
overwritten. The saved value is checked against the loaded snapshot before any
backup and again before the write, then read back after writing. These
are optimistic checks, not an atomic Windows compare-and-swap; avoid simultaneous
edits from other remappers. Verification failure never triggers an automatic
rollback that could overwrite another writer. Keep any created backup on failure.
No other registry values or parent keys are changed.

The entry uses the project's shared elevation helper for every GUI launch.
Cancelling or failing elevation exits without opening a standard-user editor.
The internal administrator draft handoff remains available for embedded callers;
it only stages a draft and never applies changes during startup.

Backups are versioned UTF-8 JSON, not arbitrary `.reg` files. They preserve
exact valid bytes and distinguish an absent value from a present empty map.
Loading a backup stages a restore for review and confirmation, with an optional
fresh backup when saving.
Malformed maps, non-binary registry values and duplicate source entries block
editing rather than being repaired silently. Clearing all mappings deletes
only the Scancode Map value when explicitly applied.

Restart Windows to activate saved changes. The application never restarts the
computer automatically or claims that saved bytes are already active. Registry
remapping supports physical key substitutions, not shortcuts/macros or per-device
profiles; a listed scan word does not guarantee support by particular hardware.

Only use capture for legitimate keyboard testing, custom hotkeys and authorized
automation. Obtain permission from affected users. No covert surveillance,
credential collection or other unauthorized activity. Users are responsible for
their use and its consequences.

## Implementation and verification

| Module | Responsibility |
| --- | --- |
| `models.py` | Pure binary format, immutable mappings/snapshots and backup schema |
| `registry.py` | One-value native backend, backup and conflict/write verification |
| `catalog.py` | Shared-catalog labels and manual scan-word input |
| `capture.py` | Bounded focused-window capture and pure native-message decoding |
| `ui.py` | Draft editing, dropdowns, previews and explicit user actions |
| `app.py` | Fusion startup and draft-only administrator handoff |

The entry loads this folder as `personal_keyboard_remap`. Launcher/compiler
discovery ignores the folder; compiler staging uses the same import alias.
PySide6 is already a hard runtime dependency in the root requirements file;
everything else uses the standard library. `gsudo` is an optional elevation
helper through `System.restart_elevated()`; running from an administrator
terminal also works. No project-specific environment variables are introduced.

Run `conda run -n base python -m unittest discover -s test -p "test_keyboard*.py"`.
Tests use a mock registry and offscreen Qt. They do not change HKLM, request
elevation, install hooks or synthesize system input. Actual UAC, reboot effects
and hardware-specific capture/remapping require manual testing.

References: [Windows keyboard messages and scan codes](https://learn.microsoft.com/en-us/windows/win32/inputdev/about-keyboard-input),
[PowerToys comparison with registry mapping](https://github.com/microsoft/PowerToys/blob/main/doc/devdocs/modules/keyboardmanager/keyboardmanager.md),
[SharpKeys binary mapping implementation](https://github.com/randyrants/sharpkeys/blob/master/SharpKeys/Dialog_Main.cs).
This implementation uses documented format facts, not copied project source.
