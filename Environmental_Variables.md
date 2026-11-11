# User Configuration and Native Environment Variables

Project settings use `utils.ConfigStore`, not custom environment variables.
All platforms use `~/.config/PersonalScripts`; the application directory name is
owned by `APP_DIRECTORY_NAME` in `utils/config.py`. Call `ConfigStore.directory()`
in code instead of reproducing that path. `ConfigStore.initialize()` creates only
a missing general config.yaml; each application owns its own filename and initialization.

| User file | Settings |
| --- | --- |
| `config.yaml` | General tool settings; empty initially. `rclone-sync.config-password` stores an optional encrypted rclone password. `network-info-uploader` retains the `upload-ipaddress` section, which contains `bucket`, `endpoint`, `access-id`, `secret`. |
| `config-pdf-tools.yaml` | Shared PDF open/save directories, used by all four tools during file actions. |
| `llm.yaml` | `active_source` selects the last URL; `sources` maps canonical endpoints to model/parameters and encrypted `api_key` / `balance_key`. `reasoning_effort` defaults to `auto` (enabled); `default` omits controls, `none` disables, or select a supported `minimal`/`low`/`medium`/`high`/`xhigh`/`max` level. Owned by utils.Llm. Startup/Load reads; Save/window close writes. |
| `launcher.yaml` | `conda-environment` (default `base`) and `additional-paths` (YAML list, default empty). Relative extra paths use the repository root. This is distinct from repository `launcher-config.yaml` and its optional patch. |
| `rclone-sync.yaml` | Actual task schema, or a redirect-only mapping to an external schema. |
| `run-commands.yaml` | `command-runner` task schema, or a redirect-only mapping to an external schema. |

Explicit command-line options override the relevant user configuration fields.
No custom environment-variable fallback is retained. Native `PATH`, Conda,
rclone, desktop and operating-system variables retain their existing meanings.

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

- LLM inference uses native system certificate trust through `truststore`;
  Windows/macOS system stores replace HTTPX's environment CA-file override;
  Linux retains OpenSSL's `SSL_CERT_FILE` / `SSL_CERT_DIR` behavior.
  HTTPX proxy routing retains its ordinary environment/system behavior.
  Each `llm.yaml` source may set `skip_certificate_verification: true` to disable
  TLS certificate/hostname checks for inference, API tests, model lists and balances.
  The default is false, including older configurations. HTTP local endpoints need
  no TLS opt-out. GUI Save/window close persists the per-source checkbox.
- command-runner sends inline Conda Python payloads through a temporary JSON file
  removed after the child exits. No project environment variable carries it.
- Generated Windows script-to-app runners use local `_APP_*` bookkeeping inside
  `setlocal`; these are not user settings. The Bash exit-code variable is local.
- `RCLONE_CONFIG` / `RCLONE_CONFIG_PASS` remain native rclone integration variables;
  explicit command-line options and saved credentials supply the relevant values.
- `XDG_DATA_HOME`, `XDG_DATA_DIRS`, `DISPLAY` and `WAYLAND_DISPLAY` still affect
  Linux desktop entries and desktop detection. They do not relocate user config.
- Task YAML may explicitly define its own child environment and use ordinary
  environment placeholders. Such task data is not a project settings interface.
