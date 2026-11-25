# User Configuration and Native Environment Variables

Project settings use `utils.ConfigStore`, not custom environment variables.
All platforms use `~/.config/PersonalScripts`; the application directory name is
owned by `APP_DIRECTORY_NAME` in `utils/config.py`. Call `ConfigStore.directory()`
in code instead of reproducing that path. `ConfigStore.initialize()` creates only
a missing general config.yaml; each application owns its own filename and initialization.

On macOS and Linux, a process running as root under `sudo` uses `SUDO_UID` to
look up the invoking account's home directory. New configuration directories,
YAML files and lock files belong to that user. A direct root session without
`SUDO_UID` uses its own home directory.

| User file | Settings |
| --- | --- |
| `config.yaml` | General tool settings; empty initially. `rclone-sync.config-password` stores an optional encrypted rclone password. `network-info-uploader` retains the `upload-ipaddress` section, which contains `bucket`, `endpoint`, `access-id`, `secret`. |
| `text-processor.yaml` | Text and Path Processor saves each preference when changed. `use_result_for_next_operation` defaults to true. `variable_syntax` accepts `cmd`, `Bash` or `PowerShell` and defaults to `cmd` on Windows and `Bash` elsewhere. |
| `screen-mask.yaml` | Screen Mask saves `background_color` (default `#000000`), `border_color` (default `#0000ff`), and separate border widths in logical pixels. Solid blocks use `border_width` (0–32, default 2) and hollow frames use `hollow_border_width` (1–32, default 5). Changes become defaults for new windows and future launches. Each window starts at 100% opacity and remembers its width for each mode when switching. On Linux, the active display (`WAYLAND_DISPLAY` or `DISPLAY`) identifies the desktop session for repeated launches. |
| `screen-keyboard.yaml` | Prefs saves `windows_left_key` or `macos_left_key`. Both accept `native` (ordinary Caps Lock, the default), `CapsLock` and `F1`. Windows also accepts `F24`. In `windows_window` and `macos_window`, `remember_size` defaults to false. Enabling it saves the client size and expanded panels. Disabling it restores the default layout on the next launch. |
| `config-pdf-tools.yaml` | Shared PDF open/save directories. The `ocr` section stores recognition/language, tiling, anchor-margin and preprocessing settings, plus preview font/color; page exclusions and recognized text remain session-only. The `image-ocr` section stores batch recognition settings. Its `vision.text` and `vision.formula` mappings store transcription instructions, output format, document and math formatting, and per-request context reset. Conversations are session-only and scoped to mode and endpoint. The provider profile in `llm.yaml` sets the total images per request (default 5). The OCR model manager stores explicitly downloaded language extensions in the project directory `deps/ocr-models/`; its catalog and SHA-256 checksums come from the installed RapidOCR registry. Bundled models stay in the package. Image to Text and Formula stores its optional formula model in `deps/ocr-models/LaTeX_OCR_rec/`. |
| `llm.yaml` | `active_source` selects the last URL; `sources` maps canonical endpoints to model/parameters and encrypted `api_key` / `balance_key`. `reasoning_effort` defaults to `auto` (enabled); `default` omits controls, `none` disables, or select a supported `minimal`/`low`/`medium`/`high`/`xhigh`/`max` level. Owned by utils.Llm. Startup/Load reads; Save/window close writes. |
| `conda-env.txt` | One UTF-8 environment name for the shell wrappers when using Conda. Missing or blank selects `base`. Bundled and directly invoked Python bypass this file. |
| `launcher.yaml` | `additional-paths` lists extra script directories (default empty). Relative paths use the repository root. |
| `launcher-config.patch.yaml` | Optional overrides for the project's `launcher-config.yaml`. Mappings merge recursively, lists and scalar values replace the defaults, and relative paths use the project root. |
| `rclone-sync.yaml` | Actual task schema, or a redirect-only mapping to an external schema. |
| `run-commands.yaml` | `command-runner` task schema, or a redirect-only mapping to an external schema. |

Explicit command-line options override the relevant user configuration fields.
No custom environment-variable fallback is retained. Native `PATH`, Conda,
rclone, desktop and operating-system variables retain their existing meanings.

On macOS, Auto Typer sets Qt's `QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM`
while its panel is running so launching it preserves the target application's focus.

A redirect entry contains only `redirect: '/path/to/tasks.yaml'`. Relative paths
resolve against each redirect file's directory. Missing targets, cycles, mixed
redirect/task entries and chains longer than 16 files are rejected. Rclone's
`schema_dir` follows the final target; command-runner retains invocation/task cwd
semantics. Use single quotes for Windows paths in manually edited YAML.

The shared reader supports safe YAML, empty mappings, merge overrides and
opaque `!encrypted` values, rejecting duplicate explicit keys. Reads and writes
try a per-file lock once; contention raises ConfigBusyError with status `busy`,
without waiting/retrying. The caller reports it in the console or tooltip. Locks
are released before dialogs, PDF work or network requests. Updates reread and
merge changed fields before atomically replacing the file. Unknown fields are
retained; malformed files are not silently reset. Owning modules validate/decrypt their values. Automatic
writes may normalize YAML formatting and do not preserve comments.

Use `EncryptedValue.encrypt(text, module_key)` before ConfigStore.update and
`value.decrypt(module_key)` in the owning module. ConfigStore preserves ciphertext
without holding or guessing keys. LLM's key lives in utils/llm.py; network-info-uploader
and rclone-sync/command-runner own separate keys. Use `EncryptedValue.decrypt_tree`
for a module-owned nested schema/section. Application filenames also stay outside
config.py. This is obfuscation against casual inspection: the key ships with the
code and does not protect against someone with access to that code. Never commit
real user configuration, decrypted credentials or tokens.

## Runtime transport and native variables

- On macOS, launch a PySide6 tool with `QT_LOGGING_RULES='qt.text.font.db.info=true'`
  to see Qt's font database diagnostics during fallback selection.
- LLM inference uses native system certificate trust through `truststore`;
  Windows/macOS system stores replace HTTPX's environment CA-file override;
  Linux retains OpenSSL's `SSL_CERT_FILE` / `SSL_CERT_DIR` behavior.
  HTTPX proxy routing retains its ordinary environment/system behavior.
  Each `llm.yaml` source may set `skip_certificate_verification: true` to disable
  TLS certificate/hostname checks for inference, API tests, model lists and balances.
  The default is false, including older configurations. HTTP local endpoints need
  no TLS opt-out. GUI Save/window close persists the per-source checkbox.
- Text and Path Processor shortens paths using the longest matching directory in the current environment. The [path conversion reference](utils/docs/text_transforms.md) lists the native variables and shell forms.
- command-runner sends inline Conda Python payloads through a temporary JSON file
  removed after the child exits. No project environment variable carries it.
- Generated Windows script-to-app runners use local `_APP_*` bookkeeping inside
  `setlocal`; these are not user settings. The Bash exit-code variable is local.
- `RCLONE_CONFIG` / `RCLONE_CONFIG_PASS` remain native rclone integration variables;
  explicit command-line options and saved credentials supply the relevant values.
- After POSIX elevation, `script-to-app` uses `SUDO_UID` to resolve the desktop
  user's home and install per-user launchers with that user's ownership.
  The macOS privacy cleaner resolves user paths with `SUDO_USER`.
- `XDG_DATA_HOME`, `XDG_DATA_DIRS`, `DISPLAY` and `WAYLAND_DISPLAY` still affect
  Linux desktop entries and desktop detection. They do not relocate user config.
- Task YAML may explicitly define its own child environment and use ordinary
  environment placeholders. Such task data is not a project settings interface.
