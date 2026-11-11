# Personal Scripts

[中文版（Chinese）](./README_zh.md)

**GitHub**: https://github.com/BH2WFR/PersonalScripts

**License: GPL v3**

**A collection of cross-platform utility scripts for personal use**, covering PDF processing, file links, video downloads, system tools, and more.

**Highlights** (see [Script List](#script-list) for the complete list; bold entries are key features):

> - **Research**
>   - **A powerful matrix viewer** for 1D arrays, 2D matrices (with 2D, 3D, 1D slice, and 1D slice derivative views), and point clouds; supports `.npy`/`.npz`/`.mat`/`.csv`/`.xls`/`.xlsx` formats, opens images as 2D matrices, displays the magnitude and phase of complex matrices, applies Fourier and Laplace transforms, opens multiple matrices for comparison, and exports cropped matrices or matrix slices
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
>   - **Scanned PDF binarization tool** (can further reduce file size)
>   - **PDF page-label editor**
>   - **Automated document screenshot tool** that turns pages and saves document screenshots
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

      `mss` (screenshots), `Pillow`/`matplotlib`/`numpy`/`opencv-python` (image processing), `PySide6` (GUI), `pyqtgraph`/`pyvista` (data visualization), `PyMuPDF` (PDF processing), `boto3` (S3 access and uploads), and `pynput` (keyboard input monitoring)

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
  - Some tools, such as `macos/display-manager`, support only Macs with Apple Silicon processors.

- **Linux:**

  - On systems without a graphical environment, some GUI- or screenshot-related tools cannot be launched.
  - Some keyboard-hook and screenshot scripts support X11 but not Wayland. The launcher hides them under Wayland.

- **Other:**

  - [**UniGetUI**](https://github.com/Devolutions/UniGetUI) is recommended for managing system package managers through a graphical interface. It makes software installed through package managers easy to find, install, and upgrade, and supports Scoop/WinGet on Windows and Homebrew on macOS.
  - If a script's purpose or implementation is unclear, use an AI coding agent to help you understand and operate it.

- **Environment variables:**

  - **Add this project directory to the `PATH` environment variable** so that the launcher can be started directly with `run-script.ps1` or `run-script.sh`.
  - See the launcher section below for personal launcher settings.

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

Core utility package: `utils/` — shared console, environment, system, path, interaction, PDF and model-API helpers, re-exported through `utils/__init__.py`. PDF and GUI dependencies load only when needed.

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
- When started **without arguments**, the launcher detects the operating system, platform, architecture, and the availability of Conda/Python/PowerShell/Bash; on Linux, it also shows the current graphical environment (`no-gui`/`x11`/`wayland`). It then **lists every script supported by the current environment** and lets you select and launch one interactively, with argument pass-through:
  - Select a script by **number** or **name**, such as `15`, `macos/ntfs-3g-mount-manager.py`, or `ntfs-3g-mount-manager`.
  - Scripts configured to be hidden on Linux without a GUI carry a yellow `[GUI]` suffix when listed.
  - Arguments after the number or name are passed to the target script, such as `15 --help`, `macos/display-manager --list`, or `display-manager --list`.
- When started **with arguments**, the launcher finds the requested script and **passes through all remaining arguments**. It runs the target directly without printing the supported-script list.
  For example, `run-script.sh ntfs-3g-mount-manager --list` finds `macos/ntfs-3g-mount-manager`, runs it, and passes `--list` to it.
- You may **omit parent directories and enter only a script name**. For example, `ntfs-3g-mount-manager` is found recursively and launches the same script as `macos/ntfs-3g-mount-manager`.
  If multiple directories contain scripts with the same name, the launcher asks you to select the target by number.
  - Note: omit the `tools` level because recursive search begins inside `./tools`.
- File extensions may also be omitted. For example, `macos/ntfs-3g-mount-manager.py` can be entered as `ntfs-3g-mount-manager` or `macos/ntfs-3g-mount-manager`.
  If scripts share the same name but use different extensions, the launcher asks you to select the target by number.
- **Scripts can be hidden from the list for selected platforms, environments, or architectures.** In `launcher-config.yaml`, filtering supports operating systems (`windows`/`linux`/`macos`), Linux graphical environments (`no-gui`/`x11`/`wayland`), and processor architectures (`x86`/`x86_64`/`armv7`/`arm64`).
  - To customize `launcher-config.yaml`, create `launcher-config.patch.yaml` in the project root and include only the settings that need to be overridden. The launcher loads it automatically at startup.
  - Interpreter-aware filtering hides `.sh` scripts when `bash` is unavailable and `.ps1` scripts when `pwsh` is unavailable.
- The **Test group is disabled by default**. Set `launcher.test.enabled` to `true` to show configured test directories as a separate `Test` group and include their scripts in bare-name searches. Use `test/<name>` or `@test:<name>` to target a test script explicitly.
- Python detection first checks `./deps/python` for a bundled interpreter, then attempts to derive the base-environment Python from the Conda command path, tries known installation paths and `conda info --base`, and finally falls back to `python3`.
  - Set **`conda-environment` in `~/.config/PersonalScripts/launcher.yaml`** to choose the Conda environment used to run scripts. The default is `base`.
- **`additional-paths` in the same user `launcher.yaml`** lists additional script directories.
  Use a YAML list of directories. Relative paths are resolved from the project root. Each directory appears as `─── Additional [N] ───`, where N starts at 1, and uses the same configurable ignore rules.
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

These tools support password-protected input and save new PDFs without password,
editing restrictions, or PDF/A identification. Source files are retained.

| Script | Description | Requirements |
|------|------|------|
| `tools/document-processing/ghostscript-pdf-compressor.py` | **PDF compressor** based on Ghostscript:<br />Compresses PDFs with standard or custom resolution and quality settings, including password-protected input. | `ghostscript`; **Python pkg:** `PyMuPDF` |
| `tools/document-processing/pdf-font-replacer.py` | **PDF font and text-color replacement tool:** Changes text fonts and colors while preserving text layout and line spacing. | **Python pkgs:** `PySide6`, `PyMuPDF`, `fonttools`, `tqdm` |
| `tools/document-processing/pdf-binarizer.py` | **Scanned PDF binarization and aggressive compression tool:**<br />Binarizes PDF image elements using adaptive grayscale thresholds, with separate handling for detected illustrations, text in black boxes, and vector elements. | **Python pkgs:** `PySide6`, `PyMuPDF`, `pypdf`, `Pillow` (with libtiff), `numpy`, `opencv-python`, `tqdm` |
| `tools/document-processing/pdf-decryptor.py` | **PDF protection and PDF/A identification removal:**<br />Removes encryption, permission restrictions, and PDF/A identification while retaining document structure and other metadata. | **Python pkg:** `PyMuPDF` |
| `tools/document-processing/pdf-bookmark-editor.py` | **Scanned PDF TOC recognition, bookmark and page-label editor:** Recognizes table-of-contents images page by page through cloud or local vision models and adds the results as PDF bookmarks. Supports editing **page labels** and bookmark trees. | **Python pkg:** `PySide6`, `PyMuPDF`, `PyYAML` |
| `tools/document-processing/pdf-page-splitter.py` | **Scanned PDF page-cropping tool:** Splits double-page scans into individual pages. | **Python pkgs:** `PySide6`, `PyMuPDF`, `tqdm` |
| `tools/document-processing/document-screenshot.py` | **Automated document screenshots:** Turns pages and saves screenshots of a selected screen region. Not recommended to infringe copyright | **Windows/macOS/Linux X11**; Wayland is not supported<br />macOS: Accessibility and Screen Recording permissions<br />**Python pkgs:** `mss`, `pynput`, `Pillow` |

### Video Download

| Script | Description | Requirements |
|------|------|------|
| `tools/download/bbdown-bilibili-downloader.py` | **Bilibili video downloader based on BBDown:**<br />(quality/audio only/subtitles/danmaku/multiple APIs)<br />Note: BBDown is no longer maintained; Bilibili downloads will be migrated to yt-dlp later. | `BBDown`, `ffmpeg`, `aria2` (optional) |
| `tools/download/yt-dlp-video-downloader.py` | **Video downloader based on yt-dlp:**<br />(quality/audio/subtitles/cookies/playlists) | `yt-dlp`, `ffmpeg`, `deno` (optional) |
| `tools/download/yt-dlp-hls-downloader.py` | **m3u8/HLS stream downloader based on yt-dlp** | `yt-dlp`, `ffmpeg` |

### Video/Image Editing

| Script | Description | Requirements |
|------|------|------|
| `tools/multimedia/ffmpeg-video-trimmer.py` | **Video trimming tool based on FFmpeg:**<br />Note: this trims **by time**; it does not crop the picture. | `ffmpeg` |
| `tools/research/image-cropper.py` | **Batch image-cropping tool based on OpenCV:**<br />Crops images to a selected ROI. | **Python pkgs:** `opencv-python`, `numpy` |

### File System/Disk Mounting

| Script | Description | Requirements |
|------|------|------|
| `tools/filesystem/disk-inventory.py` | **Disk and partition inventory:** Shows a device tree with mount points, drive letters, labels, capacities, and full native IDs. | Windows: `pwsh` 7; Linux: `lsblk`; macOS: `diskutil` |
| `tools/filesystem/path-in-use.py` | **File/directory usage query:** Lists the PIDs and executable paths of processes using a file or directory. Supports recursive directory checks, including drive roots and mount points. | `psutil`;<br />**Elevation required** |
| `tools/filesystem/openssl-file-hasher.py` | **File hash calculator based on OpenSSL:**<br />Processes files in batches and supports common algorithms provided by OpenSSL, including `md5` and `sha256`. | `openssl` |
| `tools/filesystem/filename-shortener.py` | **Automatic long-filename truncation tool:**<br />Counts the UTF-8 encoded byte length and truncates filenames that exceed a specified limit (143 bytes by default, for compatibility with Synology encrypted-folder limits).<br />Extensions are **preserved**, and collisions receive an automatic `_1`, `_2`, and so on before the extension. | |
| `tools/filesystem/file-timestamp-editor.py` | **File/directory timestamp editor:** Changes creation, modification, and access times, with optional random jitter. Supports timestamp backup and restore for all files and directories under a selected directory. | |
| `tools/macos/ntfs-3g-mount-manager.py` | macOS only. **NTFS read-write mounting tool based on ntfs-3g-mac:**<br />Automatically scans NTFS partitions and can unmount or eject them. | **macOS only**<br />**Elevation required**<br />Allow kernel extensions from identified developers in Safe Mode, then install the `macFUSE` kernel extension and the `ntfs-3g-mac` mounting tool. |

### File System/Symbolic Link Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/filesystem/link-creator.py` | **Symbolic-link/hard-link creation tool** (also supports directory symlinks, or SYMLINKD, and JUNCTION links on Windows):<br />Supports relative paths, mirror mode, and conflict handling. | |
| `tools/filesystem/link-scanner.py` | **Recursively detects and prints every symbolic link and hard link in a directory** (also prints SYMLINKD and JUNCTION directory links on Windows):<br />Automatically detects dead links whose targets no longer exist and can repair or delete them. On Windows, it can convert file symlinks that incorrectly point to directories back to SYMLINKD links. | |
| `tools/windows/directory-symlink-repair.py` | Windows-only tool that **repairs** file symlinks (SYMLINK) pointing to directories by converting them to proper **directory symlinks** (SYMLINKD):<br />Fixes links created by some file-sync tools that apply Linux symlink behavior on Windows without distinguishing file and directory symlinks, making linked directories inaccessible. | **Windows only** |

### File System/Permission Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/filesystem/executable-bit-setter.sh` | **Adds executable permission to script files in batches on Linux/macOS:**<br />Recursively finds files with selected extensions (`.py`/`.sh` by default) and applies `chmod +x`. | **Linux/macOS**<br />**Elevation required** |
| `tools/filesystem/git-executable-bit-setter.ps1` | **Marks script files as executable in a Git repository on Windows:**<br />Uses `git update-index --chmod=+x` on staged `.py`/`.sh` files so Windows commits retain `+x` permission when cloned on Linux/macOS. | **Windows**<br />`git` |
| `tools/macos/quarantine-remover.py` | macOS-only tool for **removing `quarantine` and `provenance` attributes from files in batches**, based on the `xattr` command. | **macOS only** |

### Network Tools

| Script | Description | Requirements |
|------|------|------|
| `tools/network/tailscale-refresh-routes.py` | **Tailscale subnet-route restart tool:**<br />Restores subnet routing on macOS when it stops working after a device returns home and then leaves again. | `tailscale` |
| [`tools/network/rclone-sync.py`](tools/network/rclone-sync/README.md) | **Manual runner for rclone tasks using your own YAML configuration:**<br />Uses reusable profiles and machine-specific subtasks to sync, copy, move, or compare directory/file pairs across cloud storage and local or removable drives. Supports locating removable drives by volume label. | `rclone`<br />**Python pkg:** `PyYAML`<br />Volume discovery: Windows `pwsh` 7; Linux `lsblk`; macOS `diskutil` |
| `tools/network/network-info-uploader.py` | **Local network-interface information collector and uploader:**<br />Collects network-interface information, especially IP addresses, and uploads it to an S3 bucket for remote access. | **Python pkg:** `boto3` |
| `tools/windows/firewall-app-blocker.py` | Windows-only tool for **configuring system firewall rules that block network access for `.exe`/`.com` files:**<br />Recursively finds every `.exe`/`.com` file under a selected path and can add blocking rules or remove those rules to restore access. | **Windows only**<br />**Elevation required** |
| `tools/network/http-server.py` | **Local HTTP server:** Serves files from a local directory or hosts a website containing `index.html`. | |

### Open With

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/windows/file-association-manager.py` | Windows-only tool that **registers a selected EXE as an Open With handler for specified file extensions:**<br />Useful for registering file associations for portable applications. | **Windows only**<br />**Elevation required** |
| `tools/others/script-to-app.py` | **Creates app-style launchers for Python scripts** without packaging them, with support for binding a Conda environment. Produces `.cmd` launchers on Windows, movable or renameable apps on macOS, and file handlers for specified MIME types or all files on Linux. | **Windows / macOS / Linux desktop**<br />Windows elevation or a writable directory; Linux Bash and a desktop terminal (`desktop-file-utils` optional); Linux all-files support depends on the file manager |

### Text Processing

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/others/unicode-inspector.py` | **Unicode character information viewer:**<br />Shows each character's position, hexadecimal and decimal code points, and description, with dedicated notation for spaces and control characters. | Linux clipboard access requires `wl-paste` or `xclip` |

### Display Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/windows/display-info.py` | Windows-only **screen resolution/scaling viewer:**<br />Shows the remote computer's current resolution and scaling in RDP sessions, where this information is unavailable in Windows Settings. | **Windows only** |
| `tools/macos/display-manager.py` | **Display management tool for Apple Silicon Macs:** Adjusts rotation, resolution, and brightness, diagnoses color modes, and forces RGB output on external displays. Can **disable a MacBook's built-in screen while an external display is connected**. | **macOS only** (Apple Silicon); verified on macOS 26.x Tahoe, compatibility with other versions is not guaranteed<br />**Optional Python pkg:** `pyobjc-framework-Cocoa` |

### Privacy and Cleanup

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/windows/recycle-bin-cleaner.py` | Windows-only **force-empty Recycle Bin tool:**<br />Removes **0 KB files/directories that remain in the Recycle Bin after it is emptied**.<br />When it encounters a symbolic link, it deletes only the link and does not traverse its target. | **Windows only**<br />**Elevation required** |
| `tools/windows/event-log-cleaner.py` | Windows-only **one-click event-log clearing tool**.<br />Warning: deletion cannot be undone. | **Windows only**<br />**Elevation required** |
| `tools/windows/privacy-cleaner.py` | Windows-only **privacy-trace cleanup tool:**<br />Covers File Explorer history, event logs, DNS cache, browser data, credentials, temporary files, and more.<br />Warning: **Use at your own risk.** | **Windows only**<br />**Elevation required** |
| `tools/macos/privacy-cleaner.py` | macOS-only **privacy-trace cleanup tool:**<br />Covers recent items, Finder state, shell history, browser data, caches, logs, and more.<br />Warning: **Use at your own risk.** | **macOS only**<br />Optional: `brew install trash`<br />**Elevation required** |
| `tools/filesystem/os-junk-cleaner.py` | **Recursive cleanup tool for OS-generated junk files:**<br />(`.DS_Store`, `__MACOSX__`, `Thumbs.db`, and others) | |
| `tools/windows/android-rndis-record-cleaner.py` | Windows-only tool for **removing stale Android USB tethering/RNDIS records from the registry:**<br />Prevents the network connection number from continually increasing each time USB tethering is enabled after connecting an Android device. | **Windows only**<br />**Elevation required** |

### System Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/windows/keyboard-remapper.py` | **Registry keyboard mapping editor:** Remaps or disables keys and supports backing up and restoring mappings. | **Windows 10+**<br />`PySide6`<br />Administrator privileges for writing; Windows restart required for changes to take effect |
| `tools/windows/device-ejection-history.py` | **Device ejection failure log viewer:** shows historical blocking process PIDs, executable paths and device IDs recorded by Windows. Helps identify which process is using a USB drive when it cannot be safely ejected. | **Windows 10+ only**;<br />**Elevation required** |
| `tools/windows/service-restarter.py` | Windows-only **force-restart tool for system services:**<br />Includes a `Windows Audio` preset that **can temporarily fix audio redirection failures in RDP sessions**. | **Windows only**<br />**Elevation required** |
| `tools/others/power-status-viewer.py` | **Charger and battery telemetry viewer:** Shows charging and battery information, including **the computer's current charging power on macOS**. | **Best on macOS**; other systems are also supported, with some fields unavailable because of firmware or driver limitations |
| `tools/others/power-event-viewer.py` | **Historical power-event log viewer:** Shows startup, shutdown, sleep, wake, and lock/unlock events. | **macOS / Windows 10+ / Linux desktop with systemd**; lock history support is limited on Linux<br />**Python pkg:** `PySide6` |
| `tools/others/disk-smart-info-viewer.py` | **Disk health information viewer based on smartmontools:**<br />Lists SMART-capable disks and displays detailed attributes such as total writes, power-on time, and remaining life. | `smartmontools` |
| `tools/macos/rdp-clipboard-image-repair.py` | **RDP clipboard image repair tool:** Fixes images that cannot be pasted correctly on macOS after being copied from a Windows device through Windows App (RDP). | **macOS only**; built-in `osascript` and AppKit |

### Software Launching

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| `tools/macos/run-pdf2zh.sh` | macOS-only launcher for **pdf2zh-next** ([PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next)). | **macOS only** |

### Command Presets

| Script | Description | Requirements |
|------|------|------|
| `tools/others/command-runner.py` | **Preset command runner:** Runs commands and scripts saved in your own configuration; see the [configuration sample](tools/others/run-commands-schema-sample.yaml). | **Python pkg:** `PyYAML`; programs or runtimes required by the selected preset |

### Research Tools

| Script | Description | Requirements |
|------|------|------|
| `tools/research/matrix-viewer.py` | **Matrix and signal viewer for scientific research:** Visualizes and compares 1D arrays, 2D matrices, images, and point clouds, including slices, derivatives, and complex magnitude/phase. Supports Fourier/Laplace transforms, decibel conversion, and cropped matrix or slice export. | **Python pkgs:** `numpy`, `opencv-python`, `Pillow`, `matplotlib`, `PySide6`, `pyqtgraph`, `pyvista`, `pyvistaqt`, `vtk`, `scipy`, `h5py`, `openpyxl`, `xlrd` |
| `tools/research/pattern-generator.py` | **Structured-light projection pattern generator:**<br />Generates sinusoidal stripes with selectable left/top-edge, center, or right/bottom-edge pixel sampling, plus standard Gray-code sequences.<br />Not intended for non-specialists. | **Python pkgs:** `opencv-python`, `numpy` |

### Test/Helper Scripts

| Script | Description | Requirements |
|------|------|------|
| `tools/others/keyboard-hook-viewer.py` | **Global keyboard and mouse hook monitor:** Shows key identities and scroll directions/deltas, including Windows scan codes and left/right modifiers, plus precise scrolling, pinch deltas, and available source device information on macOS.<br />**For legitimate keyboard testing, custom hotkeys and authorized automation only.** | **Windows/macOS/Linux X11**; Wayland is not supported<br />macOS: `pip install pyobjc-framework-Quartz`<br />Linux: `pip install python-xlib`<br />Windows: none (standard-library `ctypes`) |
| `test/print-argv.py`<br>`test/print-argv.sh`<br>`test/print-argv.ps1` | **Command-line argument printer:**<br />Prints every `argv` argument passed to the script, for checking whether arguments are being forwarded correctly. | |
