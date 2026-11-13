# Environment, system and paths

[Utility index](../README.md)

Implementation: [environment.py](../environment.py), [system.py](../system.py), [paths.py](../paths.py).

## API reference

| Need | Use |
| --- | --- |
| Admin / root detection | `System.is_elevated() -> bool` |
| Re-execute as admin (force) | `System.restart_elevated()` — supports source/bundled apps and paths containing spaces; gsudo uses a Windows PowerShell bootstrap |
| Re-execute as admin (soft, can fallback) | `System.try_restart_elevated() -> bool` — never re-runs after a helper starts |
| Check if a CLI tool is in PATH | `Environment.check_commands(*CmdCheck)` or `Environment.which(name)` |
| OS name / arch / hostname / Linux GUI | `System.get_os_name()`, `System.get_arch()`, `System.get_computer_name()`, `System.get_linux_gui() -> LinuxGui \| None` |
| Native disk inventory | `System.scan_disks() -> DiskScan`; returns `DiskInfo` trees with mounts, labels, filesystems, native IDs, platform details, and partial-query warnings. Windows uses PowerShell 7 Storage/CIM; Linux uses lsblk; macOS uses diskutil. Read-only, never mounts/elevates. Each query times out after 60 seconds. |
| Print env info (conda, python, shell) | `Environment.print_env_info(probe_versions=...)`; disabling probes avoids starting external tools; Python gets a yellow Conda tag only for an actual Conda interpreter, otherwise Conda details are hidden |
| Desktop notification | `System.notify(title, body)` |
| Open a file in the default app | `System.open_with_default_app(path)` |
| Open a URL safely (headless-safe) | `System.open_browser_safe(url)` |
| Resolve `$VAR` / `{{placeholders}}` in paths | `Paths.resolve_vars(path, schema_dir=..., script_dir=...)` |
| Suggest an unused filename | `Paths.available_path(path, start=1, limit=10000) -> Path`; retains a free path or tries `stem_1.ext`, `stem_2.ext`, etc.; does not reserve it, so writers must still check collisions |
| Resolve a path against an explicit base directory | `Paths.resolve_path(path, base_dir, expand_environment=True, resolve_symlinks=False) -> str`; native variable expansion preserves undefined references, False avoids re-expanding literal/template results |
| Resolve and deduplicate existing directories | `Paths.resolve_directories(paths, base_dir, on_missing=None) -> tuple[str, ...]`; first occurrence wins, optional callback reports each distinct missing directory once |
| DPI awareness (Windows) | `System.enable_dpi_awareness()` before creating windows; requests per-monitor V2 awareness, but does not resize existing widgets. Tk tools also use [TkDpi](tk_dpi.md); Qt retains its native DPI handling. |
| Find bash / pwsh / conda | `Environment.find_bash()`, `Environment.find_pwsh()`, `Environment.find_conda()` |
| Discover a strict runtime and verify its version | `Environment.resolve_runtime(RuntimeKind, executable=..., environment=..., cwd=...) -> tuple[str, str]`; `runtime_candidates(kind, environment, cwd=...)` discovers paths without probes; relative PATH uses cwd, launch paths preserve symlinks |
| Find a program using a child environment | `Environment.which(name, environment=..., cwd=...) -> str \| None`; explicit PATH/PATHEXT search relative to cwd, absolute result preserves symlinks; no options retains native shutil.which behavior |
| Expand templates using an explicit environment | `Paths.expand_template(text, environment, placeholders)`; one pass, undefined references are errors |
| Resolve dependent child environment values | `Paths.resolve_environment(inherited, overrides, literals, placeholders)`; cycles rejected, literal inputs win, self-reference reads inherited value |
| Conda environment name | `Environment.get_conda_env() -> Optional[str]`; checks current `sys.prefix/conda-meta`, not activation variables or path keywords; frozen apps return None; base is identified by its Conda package record, other prefixes use directory names |
| Actual running or selected Python | `Environment.get_python_environment(executable=None, timeout=15) -> PythonEnvironment`; immutable executable, prefix, version, frozen status and optional Conda label. No argument describes the current process without probes; an explicit executable is inspected in an isolated subprocess and invalid results raise ValueError. Prefix, not name, is the authoritative identity. Frozen executable paths are applications, not reusable Python interpreters |
| Interactive Python selection | `Environment.select_python_environment() -> tuple[PythonEnvironment, str \| None] \| None`; shared Windows/macOS current/custom-Conda/custom-Python menu. Validates the chosen installation and interpreter, returns identity plus optional Conda executable, retries invalid choices, and returns None on exit. Internal choice enums keep both menus identical |
| Native Conda launcher | `Environment.find_conda_executable(prefix=None) -> str \| None`; current or supplied prefix locations, then `CONDA_EXE` and PATH; resolves Windows batch wrappers to `Scripts/conda.exe`, searches `bin/conda` and `condabin/conda` on macOS/Linux and checks executability; discovery never classifies the running interpreter |
| Resolve a named Conda environment's Python | `Environment.resolve_conda_python(env_name, timeout=15, conda_executable=None) -> str`; current-environment fast path, otherwise Conda JSON discovery with ambiguity/existence checks. An explicit Conda executable bypasses the fast path and queries only that installation; resolves only, does not activate |
| Prepend literal directories to this process's PATH | `Environment.prepend_path(paths)`; preserves order and the previous PATH, no expansion/deduplication, no trailing empty entry for unset/empty PATH |
| Headless detection | `System.is_headless()` |
| macOS Accessibility permission | `System.check_macos_accessibility_permission(prompt=...)` |
| macOS Screen Recording permission | `System.check_macos_screen_recording_permission(request=...)` |
| Ensure required macOS permissions | `System.ensure_macos_permissions(accessibility=..., screen_recording=...)` |
| Wait for macOS direct-capture approval | `System.wait_for_macos_screen_capture_approval(capture_probe)` |

## Ownership and invariants

`Environment._conda_environment_name` is the internal metadata classifier shared
by current-process identity and external Python probes. Use public environment
methods instead of duplicating classification or executable discovery.

`system.py` owns the internal `_disk_*` native queries and parsers used by disk
inspection and volume-backed synchronization. `DiskInfo`/`DiskScan` preserve
unknown metadata and partial-scan warnings. Before writing to a volume, callers
must validate scan completeness and the current mount identity.

For scripts requiring privileges, use `System.restart_elevated()`; when a useful
unprivileged mode exists, use `System.try_restart_elevated()` and handle failure.
Keep help accessible without elevation; check privileges before protected work.
