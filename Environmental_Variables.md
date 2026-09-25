# Environment Variables

This project uses the following project-specific environment variables.

Project-specific environment variables must start with `ZL_` and be documented
here when added or changed. Standard system and third-party variables retain
their original names.

## Launcher

| Variable | Required | Purpose |
| --- | --- | --- |
| `ZL_SCRIPT_ADDITIONAL_PATH` | No | Adds directories for `run-script.py` to scan in addition to the primary directory configured in `launcher-config.yaml`. Separate multiple paths with `;` on Windows or `:` on macOS/Linux. Relative paths are resolved from the project root. |

## `tools/network/rclone-sync.py`

| Variable | Required | Purpose |
| --- | --- | --- |
| `ZL_RCLONE_SYNC_SCHEMA_FILE` | With `--task`, unless `--schema-file` is supplied | Selects the actual YAML configuration; `--schema-file` takes precedence. Interactive startup prompts for a path if neither is set. There is no bundled default configurZL_RUN_COMMANDS_SCHEMA_FILEation. |
| `ZL_RCLONE_CONFIG_PASSWORD` | Only for encrypted configurations | Supplies the password for an encrypted rclone configuration. |

Paths in the rclone YAML schema may also reference ordinary system environment
variables.

`tools/network/rclone-sync-schema-sample.yaml` is detailed configuration
documentation for agents and users, not a runtime configuration or fallback.

## `tools/run-commands.py`

| Variable | Required | Purpose |
| --- | --- | --- |
| `ZL_RUN_COMMANDS_SCHEMA_FILE` | With `--task` or redirected stdin, unless `--schema-file` is supplied | Path to the actual YAML configuration file. Interactive startup always prompts for a path, using `--schema-file` or this variable as the default; without either, enter a path. Non-interactive selection uses the supplied path directly. `--schema-file` takes precedence. |
| `ZL_RUN_COMMANDS_INTERNAL_PAYLOAD` | No; reserved for internal use | Temporary JSON payload set by the runner for a Conda Python child process and consumed by its bootstrap. Do not set it manually or persist it. |

Use an absolute configuration path for portability across working directories.
Relative configuration paths are resolved from the invocation directory.
`tools/run-commands-schema-sample.yaml` is documentation for agents and users,
not an actual runtime configuration or an automatic default/fallback.

## `tools/network/upload-ipaddress.py`

| Variable | Required | Purpose |
| --- | --- | --- |
| `ZL-IP-ADDRESS-S3-BUCKET` | Yes | S3-compatible bucket name. |
| `ZL-IP-ADDRESS-S3-ENDPOINT` | Yes | S3-compatible endpoint URL. |
| `ZL-IP-ADDRESS-S3-ID` | Yes | S3 access key ID. |
| `ZL-IP-ADDRESS-S3-SECRET` | Yes | S3 secret access key. |

Do not commit real passwords or access keys to this repository.
