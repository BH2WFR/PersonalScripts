# Personal Scripts

[中文版（Chinese）](./README_zh.md)

**GitHub**: https://github.com/BH2WFR/PersonalScripts

**License: GPL v3**

**A collection of cross-platform utility scripts for personal use**, covering PDF processing, file links, video downloads, system tools, and more.

**Highlights** (see [Script List](#script-list) for the complete list; bold entries are key features):

> - **Research**
>   - Interactive `.npy`/`.npz` viewer with line charts, heatmaps, 3D surfaces, and other visualizations
>   - Batch image cropping tool
> - **Windows**
>   - **One-click Windows event log clearing tool**
>   - **Android USB tethering history cleaner**, which stops local connection numbers from increasing each time USB tethering is enabled
>   - Force-restart `Windows Audio` or other system services, which can temporarily fix audio redirection failures in RDP sessions
>   - Force-**empty the Recycle Bin** to remove undeletable 0 KB items sometimes left there after deleting OneDrive files
>   - **Add every `.exe`/`.com` file under a specified directory to Windows Firewall blocking rules**
>   - Toolset for registering applications as Open With handlers for specified file extensions
>   - Wrap any Python script in a CMD launcher suitable for use as a file association
> - **macOS**
>   - **NTFS read-write mounting tool** based on ntfs-3g-mac
>   - Display utilities for **disabling a MacBook's built-in screen while an external display is connected**, rotating displays, and adjusting external-display brightness
>   - Wrap any Python script as a `.app` suitable for use as a file association
> - **File system**
>   - **Symbolic-link tools** for creating symbolic or hard links and recursively inspecting links in a directory
>   - Repair Windows file symlinks that incorrectly point to directories by converting them to directory symlinks (SYMLINKD)
>   - **Batch file timestamp editor** with timestamp backup and restore, plus per-file random jitter during modification
>   - **Batch truncation of overlong filenames** while preserving extensions
>   - **Batch file hash calculation**
>   - Recursive cleanup tool for files such as `Thumbs.db` and `.DS_Store`
> - **Document tools**
>   - PDF decryption and editing-restriction removal
>   - **PDF table-of-contents (bookmark) injector** that uses a vision LLM to read a book's table of contents and adds the resulting entries to the PDF
>   - PDF compression using Ghostscript
>   - **Automated document screenshot tool** that extracts documents unavailable for download or stored on encrypted media by automatically turning pages and taking screenshots
> - **Network tools**
>   - **Interactive manual rclone synchronization tool** with reusable profile support
>   - Tool for serving a local website project containing `index.html` as a web service
> - **Video tools**
>   - Bilibili video downloader based on BBDown
>   - Web video downloader based on yt-dlp, including m3u8 streams
>   - Video time-trimming tool based on FFmpeg
> - Unicode character inspector
> - Global keyboard and mouse hook tester

Most scripts support both interactive mode and command-line arguments. Run `python <script-name>.py --help` for usage details.



## Configuration and Launch Guide

- **Conda and Python environments:**

  - This project **uses Conda's Python by default**, with the **`base` environment**.

  - If Conda is not installed, **Miniconda is recommended** because it is much smaller than Anaconda.

  - Python **3.13+** is required.

  - Required Python packages:

    - **Launcher dependencies (required):**

      `PyYAML`, `pathspec`

    - Notable libraries used by some scripts (see [Script List](#script-list) for actual requirements; the following are examples only):

      `mss` (screenshots), `Pillow`/`matplotlib`/`numpy`/`opencv-python` (image processing), `plotly` (data visualization), `PyMuPDF`/`pypdf` (PDF processing), `boto3` (S3 access and uploads), and `pynput` (keyboard input monitoring)

  - **Install Python dependencies:**

    - Install most dependencies with:

      ```sh
      conda run -n base python -m pip install -r requirements.txt
      ```

    - To run scripts under `tools/research/`, install their dedicated dependencies with:

      ```sh
      conda run -n base python -m pip install -r requirements-research.txt
      ```

    - Do not install `requirements-internal.txt`; it is for internal project use only.

- **Windows:**

  - **Only Windows 10 and later are supported.**

  - Use **Scoop** to install command-line tools and **WinGet** to install GUI applications.

    > **Manually downloading executables and managing command-line tools through `PATH` is strongly discouraged.**
    > Package managers save considerable setup time and can check for updates automatically.

  - **PowerShell 7** is recommended instead of the built-in Windows PowerShell 5.

  - Some scripts need to **elevate within the current terminal**. Installing **`gsudo`** is recommended (`scoop install gsudo`; project: [https://github.com/gerardog/gsudo](https://github.com/gerardog/gsudo)). Otherwise, launch these scripts from an administrator terminal.

  - For Bash support, **install Git**. At startup, the launcher derives the Git Bash path from the location of the `git` command.

    - A future version may also search for Bash through Cygwin and prefer it over Git Bash.

- **macOS:**

  - Use **Homebrew** to install command-line tools (formulae) and GUI applications (casks).
  - Some tools, such as `macos/screen-utils`, support only Macs with Apple Silicon processors.

- **Linux:**

  - On systems without a graphical environment, some GUI- or screenshot-related tools cannot be launched.
  - Some keyboard-hook and screenshot scripts support X11 but not Wayland. The launcher hides them under Wayland.

- **Other:**

  - [**UniGetUI**](https://github.com/Devolutions/UniGetUI) is recommended for managing system package managers through a graphical interface. It makes software installed through package managers easy to find, install, and upgrade, and supports Scoop/WinGet on Windows and Homebrew on macOS.
  - If a script's purpose or implementation is unclear, use an AI coding agent to help you understand and operate it.

- **Environment variables:**

  - **Add this project directory to the `PATH` environment variable** so that the launcher can be started directly with `run-script.ps1` or `run-script.sh`.
  - See the launcher section below for other launcher-related environment variables.

- **Command-line tools and Python libraries required by individual scripts:**

  - See the tables in [Script List](#script-list). Install the listed command-line tools and Python libraries through a **package manager** where possible.

    **Reference installation commands (examples only; do not copy and run them blindly):**

    ```sh
    # Windows (Scoop)
    scoop install ffmpeg yt-dlp aria2 smartmontools ghostscript
    
    # macOS (Homebrew)
    brew install ffmpeg yt-dlp aria2 smartmontools ghostscript ntfs-3g
    brew install --cask macfuse
    
    # Linux (APT): commands may differ by distribution and release, and custom repositories may be required
    sudo apt install ffmpeg yt-dlp aria2 smartmontools ghostscript
    ```

### Project Structure

Core utility package: `utils/` — separates console, runtime environment, system, path, and interaction responsibilities into dedicated classes, with public utilities re-exported through `utils/__init__.py`.

- **All utility scripts** are stored under **`./tools/`**, including `./tools/network`, `./tools/research`, and `./tools/windows`.

  - Omit the `tools` level when searching for or launching a script. For example, launch `./tools/network/rclone-sync.py` as `network/rclone-sync.py` or `rclone-sync`.

- Every Python script **depends on the shared `./utils` package**, which provides interactive text and path input, interactive menus, path handling, privilege elevation, dependency checks, ANSI escape-code colors, and other shared functionality.

  > **Do not copy a utility script out of the project and run it by itself.** It will fail because the dependencies in `utils` cannot be found.

### Using the Launcher

```bash
# Interactive mode: list supported scripts and select one by number or name
./run-script.sh                                # Linux/macOS
.\run-script.ps1                               # Windows

# Run a named script directly and pass through arguments
./run-script.sh <script-name> [arguments...]   # Linux/macOS
.\run-script.ps1 <script-name> [arguments...]  # Windows

# List available scripts only
./run-script.sh --list                         # Linux/macOS
.\run-script.ps1 --list                        # Windows
```

**Launcher features:**

- Run `run-script.ps1` on Windows and `run-script.sh` on Linux/macOS. These wrapper scripts locate an available Python interpreter and then start the actual launcher, `run-script.py`.
- When started **without arguments**, the launcher detects the operating system, platform, architecture, and the availability of Conda/Python/PowerShell/Bash. It then **lists every script supported by the current environment** and lets you select and launch one interactively, with argument pass-through:
  - Select a script by **number** or **name**, such as `15`, `macos/ntfs-3g-utils.py`, or `ntfs-3g-utils`.
  - Arguments after the number or name are passed to the target script, such as `15 --help`, `macos/screen-utils --list`, or `screen-utils --list`.
- When started **with arguments**, the launcher finds the requested script and **passes through all remaining arguments**. It runs the target directly without printing the supported-script list.
  For example, `run-script.sh ntfs-3g-utils --list` finds `macos/ntfs-3g-utils`, runs it, and passes `--list` to it.
- You may **omit parent directories and enter only a script name**. For example, `ntfs-3g-utils` is found recursively and launches the same script as `macos/ntfs-3g-utils`.
  If multiple directories contain scripts with the same name, the launcher asks you to select the target by number.
  - Note: omit the `tools` level because recursive search begins inside `./tools`.
- File extensions may also be omitted. For example, `macos/ntfs-3g-utils.py` can be entered as `ntfs-3g-utils` or `macos/ntfs-3g-utils`.
  If scripts share the same name but use different extensions, the launcher asks you to select the target by number.
- **Scripts can be hidden from the list for selected platforms, environments, or architectures.** In `launcher-config.yaml`, filtering supports operating systems (`windows`/`linux`/`macos`), Linux graphical environments (`no-gui`/`x11`/`wayland`), and processor architectures (`x86`/`x86_64`/`armv7`/`arm64`).
  - To customize `launcher-config.yaml`, create `launcher-config.patch.yaml` in the project root and include only the settings that need to be overridden. The launcher loads it automatically at startup.
  - Interpreter-aware filtering hides `.sh` scripts when `bash` is unavailable and `.ps1` scripts when `pwsh` is unavailable.
- The **Test group is disabled by default**. Set `launcher.test.enabled` to `true` to show configured test directories as a separate `Test` group and include their scripts in bare-name searches. Use `test/<name>` or `@test:<name>` to target a test script explicitly.
- Python detection first checks `./deps/python` for a bundled interpreter, then attempts to derive the base-environment Python from the Conda command path, tries known installation paths and `conda info --base`, and finally falls back to `python3`.
  - Set the **`ZL_CONDA_ENV` system environment variable** to choose the Conda environment used to run scripts. The default is `base`.
- **`ZL_SCRIPT_ADDITIONAL_PATH`** discovers additional script directories; the environment variable's name is configurable.
  Separate multiple directories with the platform path separator (`;` on Windows and `:` on macOS/Linux). Relative paths are resolved from the project root. Each directory appears as `─── Additional [N] ───`, where N starts at 1, and uses the same configurable ignore rules.
  Use an **`@N:` prefix** to select the script source explicitly: `@0:` is the main directory, `@1:` is the first additional directory (`Additional [1]`), and so on. Bare-name searches cover all groups; `@N:` limits the same matching rules to one group. Multiple valid matches are displayed as numbered `@N:` paths. This syntax also works on the command line, for example `python run-script.py @1:test.py`.
- Script and dependency packaging has been reserved for future use by placing dependency executables under `./deps`, but it has **not been fully implemented or verified** and is not currently a priority.
  - Do not run `compile-script.py`.
  - At startup, the launcher reads the `extra-env-paths` key from `launcher-config.yaml`. It lists platform-specific paths to add to `PATH` when launching scripts, such as `./deps/python` and `./deps/bin`, with the aim of eventually removing the Conda and package-manager requirement. This feature has not yet been verified; use Conda and package managers for now.

### Other Features

- **Interactive input:**

  - End multiline input with EOF (Windows: `Ctrl+Z`, then `Enter`; Linux/macOS: `Ctrl+D`).
  - **Path input expands environment variables** (`$VAR`/`${VAR}` on Linux/macOS and `%VAR%` on Windows).
    Only defined variables are expanded; undefined variables remain unchanged.

  - Multiple-path prompts support glob patterns (`*`/`?`/`[abc]`) for batch matching.
    Patterns with no matches are treated as literal paths.

---

## Script List

### PDF Tools

| Script | Description | Requirements |
|------|------|------|
| `tools/document-processing/pdf-compress.py` | **PDF compressor** based on Ghostscript:<br />Supports Ebook (standard) and Custom (custom DPI/quality) modes | `ghostscript` |
| `tools/document-processing/pdf-decrypt.py` | **PDF decryption and editing-restriction removal tool:**<br />Decrypts PDF files that can be opened and read but have protected editing permissions. | **Python pkg:** `pypdf` |
| `tools/document-processing/pdf-bookmarks-add.py` | **Table-of-contents injector for scanned PDF books:**<br />Send each table-of-contents screenshot separately to a **vision LLM such as Qwen3-VL** to generate JSON containing the page, level, number, and title, then paste each JSON array into the script for immediate validation and ordered merging. Supports 1, 2, or 4 consecutive book pages per PDF page, configurable alignment of book page 1, and automatic root-level `Cover` and `Table of Contents` bookmarks. | **Python pkg:** `pypdf` |
| `tools/document-processing/document-screenshot.py` | **Automated screenshot capture for protected documents:**<br />Automatically turns pages by simulating PgDn and mouse clicks, then captures screenshots. Designed to **automatically capture and save content from DRM-protected PDFs or PDFs stored on encrypted USB media**.<br /><br />For best results, use a high-resolution display in portrait orientation, then adjust the document viewport so it remains within the screen while using as much screen area as possible.<br />On macOS, the appropriate Screen Recording permission is also required. | **Windows/macOS/Linux X11**; Wayland is not supported<br />**Python pkgs:** `mss`, `pynput`, `Pillow` |

### Video Download

| Script | Description | Requirements |
|------|------|------|
| `tools/download/download-bilibili.py` | **Bilibili video downloader based on BBDown:**<br />(quality/audio only/subtitles/danmaku/multiple APIs)<br />Note: BBDown is no longer maintained; Bilibili downloads will be migrated to yt-dlp later. | `BBDown`, `ffmpeg`, `aria2` (optional) |
| `tools/download/download-yt.py` | **Video downloader based on yt-dlp:**<br />(quality/audio/subtitles/cookies/playlists) | `yt-dlp`, `ffmpeg`, `deno` (optional) |
| `tools/download/download-m3u8.py` | **m3u8/HLS stream downloader based on yt-dlp** | `yt-dlp`, `ffmpeg` |

### Video/Image Editing

| Script | Description | Requirements |
|------|------|------|
| `tools/multimedia/ffmpeg-crop-video.py` | **Video trimming tool based on FFmpeg:**<br />Note: this trims **by time**; it does not crop the picture. | `ffmpeg` |
| `tools/research/batch-crop-images.py` | **Batch image-cropping tool based on OpenCV:**<br />Crops images to a selected ROI. | **Python pkgs:** `opencv-python`, `numpy` |

### File System/Disk Mounting

| Script | Description | Requirements |
|------|------|------|
| `tools/filesystem/openssl-file-hash.py` | **File hash calculator based on OpenSSL:**<br />Processes files in batches and supports common algorithms provided by OpenSSL, including `md5` and `sha256`. | `openssl` |
| `tools/filesystem/check-filename-overlong.py` | **Automatic long-filename truncation tool:**<br />Counts the UTF-8 encoded byte length and truncates filenames that exceed a specified limit (143 bytes by default, for compatibility with Synology encrypted-folder limits).<br />Extensions are **preserved**, and collisions receive an automatic `_1`, `_2`, and so on before the extension. | |
| `tools/filesystem/modify-file-time.py` | **File/directory timestamp editor** for creation, modification, and access times. Supports random jitter and backup/restore of timestamps for every file and directory under a selected directory. | |
| `tools/macos/ntfs-3g-utils.py` | macOS only. **NTFS read-write mounting tool based on ntfs-3g-mac:**<br />Automatically scans NTFS partitions and can unmount or eject them. | **macOS only**<br />**Elevation required**<br />Allow kernel extensions from identified developers in Safe Mode, then install the `macFUSE` kernel extension and the `ntfs-3g-mac` mounting tool. |

### File System/Symbolic Link Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/filesystem/link-create.py` | **Symbolic-link/hard-link creation tool** (also supports directory symlinks, or SYMLINKD, and JUNCTION links on Windows):<br />Supports relative paths, mirror mode, and conflict handling. | |
| `tools/filesystem/link-scan.py` | **Recursively detects and prints every symbolic link and hard link in a directory** (also prints SYMLINKD and JUNCTION directory links on Windows):<br />Automatically detects dead links whose targets no longer exist and can repair or delete them. On Windows, it can convert file symlinks that incorrectly point to directories back to SYMLINKD links. | |
| `tools/filesystem/link-fix-to-symlinkd-windows.py` | Windows-only tool that **repairs** file symlinks (SYMLINK) pointing to directories by converting them to proper **directory symlinks** (SYMLINKD):<br />Fixes links created by some file-sync tools that apply Linux symlink behavior on Windows without distinguishing file and directory symlinks, making linked directories inaccessible. | **Windows only** |

### File System/Permission Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/filesystem/batch-add-chmod-x.sh` | **Adds executable permission to script files in batches on Linux/macOS:**<br />Recursively finds files with selected extensions (`.py`/`.sh` by default) and applies `chmod +x`. | **Linux/macOS**<br />**Elevation required** |
| `tools/filesystem/git-batch-add-chmod-x.ps1` | **Marks script files as executable in a Git repository on Windows:**<br />Uses `git update-index --chmod=+x` on staged `.py`/`.sh` files so Windows commits retain `+x` permission when cloned on Linux/macOS. | **Windows**<br />`git` |
| `tools/filesystem/remove-quarantine.py` | macOS-only tool for **removing `quarantine` and `provenance` attributes from files in batches**, based on the `xattr` command. | **macOS only** |

### Network Tools

| Script | Description | Requirements |
|------|------|------|
| `tools/network/tailscale-restart-accept-routes.py` | **Quick restart tool for Tailscale subnet routes:**<br />Restarts Tailscale subnet routing by toggling `--accept-routes`.<br />Addresses an issue on macOS where subnet routes may be disabled automatically after a device returns home and then leaves again. | `tailscale` |
| `tools/network/rclone-sync.py` | **Manual runner for YAML-configured rclone synchronization tasks:**<br />Supports reusable profiles, machine-filtered subtasks, direction selection for sync/copy/move, comparison modes for sync/copy/move/bisync (`size_and_time`, `size_only`, `force`, and `checksum`), alternate remotes, modification-time checks, dry runs, pre-checks, and cancellation with Ctrl+C during rclone operations (returns to the task menu in interactive mode or exits with code 130 when using `--task`). | `rclone`<br />**Python pkg:** `PyYAML` |
| `tools/network/upload-ipaddress.py` | **Local network-interface information collector and uploader:**<br />Collects local network-interface information, especially IP addresses (using `ipconfig`/`ip addr`), and uploads it to an S3 bucket for remote access.<br />Credentials come from environment variables: `ZL-IP-ADDRESS-S3-BUCKET`, `ZL-IP-ADDRESS-S3-ENDPOINT`, `ZL-IP-ADDRESS-S3-ID`, and `ZL-IP-ADDRESS-S3-SECRET`. | **Python pkg:** `boto3` |
| `tools/windows/firewall-app-blocker.py` | Windows-only tool for **configuring system firewall rules that block network access for `.exe`/`.com` files:**<br />Recursively finds every `.exe`/`.com` file under a selected path and can add blocking rules or remove those rules to restore access. | **Windows only**<br />**Elevation required** |
| `tools/network/webserver-run.py` | **Maps a local directory, or a website directory containing `index.html`, to a local HTTP server:**<br />Uses a multithreaded server based on Python's built-in `http.server` and supports interactive setup (directory/bind address/port) or CLI options (`--dir`, `--bind`, and `--port`). | |

### Open With

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/windows/file-association.py` | Windows-only tool that **registers a selected EXE as an Open With handler for specified file extensions:**<br />Useful for registering file associations for portable applications. | **Windows only**<br />**Elevation required** |
| `tools/macos/script-to-app.py` | macOS-only tool that **packages any Python script as a macOS `.app`:**<br />Makes any Python script available as an Open With application and can automatically include Python dependencies. | **macOS only** |
| `tools/windows/script-to-app.py` | Windows-only tool that creates a CMD launcher for any Python script and places it under `Program Files`:<br />Makes any Python script available as an Open With application and can automatically include Python dependencies. | **Windows only**<br />**Elevation required** |

### Text Processing

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/parse-unicode-string.py` | **Unicode character information viewer:**<br />Shows each input character's index, character, hexadecimal value, decimal value, description, and other information. Special characters such as control characters and spaces use dedicated notation.<br />Read text from the clipboard with `--clip`, or use regular interactive multiline input. | Linux clipboard access requires `wl-paste` or `xclip` |

### Display Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/windows/show-screen-resolution.py` | Windows-only **screen resolution/scaling viewer:**<br />Shows the remote computer's current resolution and scaling in RDP sessions, where this information is unavailable in Windows Settings. | **Windows only** |
| `tools/macos/screen-utils.py` | Display management tool for Apple Silicon Macs: rotation, resolution, built-in and external-display brightness via DDC/CI, color-mode diagnostics, and forced RGB-output overrides for external displays.<br />**Highlight:** When a MacBook is connected to an external display, toggle its built-in screen with one command (`--toggle-built-in`). Also supports rotating display orientation and changing external-display brightness.<br />Verified working on macOS 26.x Tahoe. Because it uses private macOS APIs, compatibility with other macOS versions is not guaranteed. | **macOS only** (Apple Silicon)<br />**Optional Python pkg:** `pyobjc-framework-Cocoa` |

### Privacy and Cleanup

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/windows/clear-recycle-bin.py` | Windows-only **force-empty Recycle Bin tool:**<br />Removes **0 KB files/directories that remain in the Recycle Bin after it is emptied**.<br />When it encounters a symbolic link, it deletes only the link and does not traverse its target. | **Windows only**<br />**Elevation required** |
| `tools/windows/clear-all-event-logs.py` | Windows-only **one-click event-log clearing tool**.<br />Warning: deletion cannot be undone. | **Windows only**<br />**Elevation required** |
| `tools/windows/clear-privacy.py` | Windows-only **privacy-trace cleanup tool:**<br />Covers File Explorer history, event logs, DNS cache, browser data, credentials, temporary files, and more, with confirmation for each section.<br />Warning: **Use at your own risk.** | **Windows only**<br />**Elevation required** |
| `tools/macos/clear-privacy.py` | macOS-only **privacy-trace cleanup tool:**<br />Covers recent items, Finder state, shell history, browser data, caches, logs, and more, with confirmation for each section.<br />Warning: **Use at your own risk.** | **macOS only**<br />Optional: `brew install trash`<br />**Elevation required** |
| `tools/filesystem/remove-os-junk-files.py` | **Recursive cleanup tool for OS-generated junk files:**<br />(`.DS_Store`, `__MACOSX__`, `Thumbs.db`, and others) | |
| `tools/windows/clear-android-rndis-record.py` | Windows-only tool for **removing stale Android USB tethering/RNDIS records from the registry:**<br />Prevents the network connection number from continually increasing each time USB tethering is enabled after connecting an Android device. | **Windows only**<br />**Elevation required** |

### System Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/windows/restart-service.py` | Windows-only **force-restart tool for system services:**<br />Supports wait and no-wait modes and includes a `Windows Audio` preset, which **can temporarily fix failure to redirect audio from the remote computer in an RDP session**. | **Windows only**<br />**Elevation required** |
| `tools/power-current.py` | Charger and battery telemetry viewer that **shows the computer's current charging power on macOS**.<br />Uses `ioreg` on macOS, PowerShell CIM/WMI on Windows, and `/sys/class/power_supply` on Linux. Some fields may be unavailable because of firmware or driver limitations. (**The best experience is on macOS.**) | **Best on macOS**; other systems are also supported with incomplete data |
| `tools/disk-smart-info.py` | **Disk health information viewer based on smartmontools:**<br />Lists SMART-capable disks and displays detailed attributes such as total writes, power-on time, and remaining life. | `smartmontools` |

### Software Launching

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/macos/run-pdf2zh.sh` | macOS-only launcher for **pdf2zh-next** ([PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next)). | **macOS only** |

### Research Tools

| Script | Description | Requirements |
|------|------|------|
| `tools/research/npy-viewer.py` | **Interactive `.npy`/`.npz` viewer:**<br />1D line/bar/scatter plots and 2D heatmaps/surface plots. | **Python pkgs:** `numpy`, `matplotlib`, `plotly` |
| `tools/research/pattern-generator.py` | **Structured-light projection pattern generator:**<br />Not intended for non-specialists. | **Python pkgs:** `opencv-python`, `numpy` |

### Test/Helper Scripts

| Script | Description | Requirements |
|------|------|------|
| `tools/keyboard-hook-viewer.py` | **Global keyboard and mouse hook monitor:**<br />Uses CGEvent taps and IOHID on macOS (and can display the source device ID), `SetWindowsHookEx` through `ctypes` on Windows, and X11 XRecord on Linux. | **Windows/macOS/Linux X11**; Wayland is not supported<br />macOS: `pip install pyobjc-framework-Quartz`<br />Linux: `pip install python-xlib`<br />Windows: none (standard-library `ctypes`) |
| `test/print-argv.py`<br>`test/print-argv.sh`<br>`test/print-argv.ps1` | **Command-line argument printer:**<br />Prints every `argv` argument passed to the script, for checking whether arguments are being forwarded correctly. | |
