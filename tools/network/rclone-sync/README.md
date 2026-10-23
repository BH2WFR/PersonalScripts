# Rclone sync implementation

Run the sibling `../rclone-sync.py` entry, directly or through the project
launcher. This directory is a private Python package loaded under the name
`personal_rclone_sync`; its modules are not standalone commands.

The YAML reference remains `../rclone-sync-schema-sample.yaml`. Existing
`path1`/`path2` configuration, CLI options, and interactive behavior are retained.
`{{script_dir}}` refers to the entry directory, including after this split.
Task groups, tasks, and sub-tasks follow schema order; the `ungrouped` section
keeps its written position rather than being moved to the top.
Above Quit, P shows the active rclone configuration file path and O
opens it with the system default application. These query `rclone config file`,
respecting `--rclone-config-file` / `RCLONE_CONFIG` and rclone's own defaults.
Missing files are not created. E continues to open the task YAML schema.
P and O exit the runner after the selected operation, including failure or
cancellation; neither returns to task selection.
C (Encrypt/Decrypt) opens the native `rclone config` menu with terminal input
and output inherited. Choose its `s) Set configuration password` entry to set,
change, or remove encryption. The runner exits when the native menu closes,
including cancellation or failure; restart it to use the resulting configuration.

## Module ownership

| Module | Responsibility |
| --- | --- |
| `models.py` | Enums, constants, immutable endpoint configurations and runtime bindings. |
| `schema.py` | YAML loading, strict validation, task settings, profile inheritance, and machine matching. |
| `endpoints.py` | Template/literal resolution, volume discovery and guards, remote prefixes, and address validation. |
| `rclone.py` | Command construction, comparison rules, cancellable subprocesses, metadata queries, and exact-file guards. |
| `ui.py` | Help, arguments, menus, address prompts, time notices, and shell-quoted command previews. |
| `execution.py` | Ordered batches, pre-checks, guarded transfers, retry boundaries, and post-transfer actions. |
| `app.py` | Application flow: configuration selection through confirmation and execution. |

Dependencies flow from `models` to `endpoints`/`schema`, then `rclone`, `ui`,
`execution`, and `app`. `endpoints` references task types only under
`TYPE_CHECKING`, so it does not import `schema` at runtime. Cross-module calls
use module references, keeping subprocess/discovery boundaries easy to mock.

`SyncTask` in `schema.py` holds shared options and task inheritance behavior.
Path resolution and command generation are functions in their owning modules;
they are no longer methods or re-exports of the entry script.

## Configuration and execution state

Each `PathPairConfig` owns both YAML endpoints and its optional custom-host
prompt. Resolution produces a separate immutable `ResolvedPathPair`, containing
resolved strings and both optional volume identity bindings. Host menus replace
runtime objects without rewriting configured paths. Failed resolution or
cancelled menus do not partially commit a batch.

`endpoints.path_tasks()` materializes independent tasks for command construction.
Retry keeps the selected addresses and volume identities; volume guards recheck
the mounted device before operations. A newly selected task resolves from its
configuration again. Low-level disk discovery remains shared in
`utils/system.py`; do not duplicate platform scanners in this package.

## Verification and packaging

From the repository root:

```text
conda run -n base python tools/network/rclone-sync.py --help
conda run -n base python -m unittest discover -s test -p "test_rclone*.py"
```

Tests are grouped by schema, paths, commands, workflow, and integration. Sync and
network operations use mocks. Integration checks exercise the source entry,
launcher filtering, and compiler staging without building or transferring data.

`launcher-config.yaml` excludes `network/rclone-sync/`, and `compile-script.py`
excludes this private directory from script selection. When compiling the entry,
the compiler stages Python modules in a temporary directory below `BUILD`, under
`personal_rclone_sync`, and explicitly includes that package. No new Python
dependency is introduced by the split. Source and executable entry points retain
the original CLI; there is no compatibility facade for old internal imports.
