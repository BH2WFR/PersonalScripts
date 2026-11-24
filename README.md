# Personal Scripts

[中文版（Chinese）](./README_zh.md)

**GitHub**: https://github.com/BH2WFR/PersonalScripts

**License: GPL v3**

**A collection of cross-platform utility scripts for personal use**, covering PDF processing, file links, video downloads, system tools, and more.

Most tools run on the command line. Some have a graphical interface.

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
>   - Remap keyboard keys through the Windows registry
>   - Identify the process blocking USB drive ejection from the Windows event log
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
>   - Find which processes are using a file or directory
> - **Document tools**
>   - PDF decryption and editing-restriction removal
>   - **PDF table-of-contents (bookmark) injector** that uses a vision LLM to read a book's table of contents and adds the resulting entries to the PDF
>   - PDF compression using Ghostscript
>   - **Scanned PDF binarization tool** (can further reduce file size)
>   - **PDF page-label editor**
>   - Batch PDF font replacement
>   - Split double-page PDF scans down the middle
>   - Edit PDF metadata such as the author and title
>   - Run OCR on PDFs
>   - Convert images to text with OCR or transcribe formulas to LaTeX with a vision LLM
>   - **Automated document screenshot tool** that turns pages and saves document screenshots
> - **Network tools**
>   - **Interactive manual rclone synchronization tool** with reusable profile support
>   - Tool for serving a local website project containing `index.html` as a web service
> - **Video tools**
>   - Bilibili video downloader based on BBDown
>   - Web video downloader based on yt-dlp, including m3u8 streams
>   - Video time-trimming tool based on FFmpeg
> - **Symbol and keyboard tools**
>   - **Auto Typer** simulates keystrokes to enter text in web VNC sessions that do not support pasting
>   - On-screen keyboard
>   - **Text and path processor** extracts full paths from files copied in Explorer or Finder, handles environment-variable prefixes, converts Windows path separators and MSYS paths, joins lines and expands ligatures in text copied from PDFs, converts styled letters and digits, replaces or removes whitespace, and converts between full-width and half-width characters
>   - Unicode character inspector
>   - **Global keyboard and mouse hook tester**
> - **System tools**
>   - **System log viewer** for startup, shutdown, sleep, USB ejection, errors, updates and network authentication on Windows, Linux and macOS
>   - Run preset commands from a profile
>   - Network repair tools

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

  - Scripts marked `[SUDO]` run with administrator privileges in the current terminal. Windows first tries `gsudo`, then Windows sudo in inline mode, and finally the system UAC prompt. You can install [gsudo](https://github.com/gerardog/gsudo) with `scoop install gsudo`.

  - For Bash support, **install Git**. At startup, the launcher derives the Git Bash path from the location of the `git` command.

    - A future version may also search for Bash through Cygwin and prefer it over Git Bash.

- **macOS:**

  - Use **Homebrew** to install command-line tools (formulae) and GUI applications (casks).
  - Some tools, such as `macos/display-manager`, support only Macs with Apple Silicon processors.

- **Linux:**

  - On headless Linux systems, the launcher hides tools that require a graphical session, including GUI applications and screenshot tools.
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
  - The launcher marks tools listed in `gui-tools-list` in `launcher-config.yaml` with `[GUI]` and hides them on Linux without a desktop. It marks tools in `elevation-needed-list` with `[SUDO]`.
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

- **Application settings**

  Some scripts read and save their settings as `*.yaml` files in `~/.config/PersonalScripts/`.

  On Linux and macOS, tools you start with `sudo` from your own account still use that directory in your home folder. Only a direct root login uses root's configuration directory (typically `/root/.config/PersonalScripts` on Linux).

---

## Script List

### PDF Tools

These tools support password-protected input and save new PDFs without password,
editing restrictions, or PDF/A identification. Source files are retained.

| Script | Description | Requirements |
|------|------|------|
| [`tools/document-processing/ghostscript-pdf-compressor.py`](tools/document-processing/ghostscript-pdf-compressor.py) | **PDF compressor** based on Ghostscript:<br />Compresses PDFs with standard or custom resolution and quality settings, including password-protected input. | `ghostscript`<br />**Python pkg:** `PyMuPDF` |
| [`tools/document-processing/pdf-font-replacer.py`](tools/document-processing/pdf-font-replacer.py) | **(GUI) PDF font and text-color replacement**<br />Replace text fonts and colors throughout a PDF while preserving layout and line spacing. | **Python pkgs:** `PySide6`, `PyMuPDF`, `fonttools`, `tqdm` |
| [`tools/document-processing/image-to-text-and-formula.py`](tools/document-processing/image-to-text-and-formula.py) | **(GUI) Image to Text and Formula**<br />Run offline OCR on text or individual formulas in local files and clipboard images, singly or in batches. A vision API can transcribe screenshots containing text and formulas to Markdown or LaTeX, with separate conversations for text and formula recognition. | **Python pkgs:** `PySide6`, `Pillow`, `PyMuPDF`, `rapidocr`, `onnxruntime`, `numpy`, `opencv-python`, `litellm`, `openai`, `httpx`, `truststore`, `markdown-it-py`<br />**Optional Python pkgs:** `paddlepaddle` (CPU) and `tokenizers` (offline LaTeX)<br />**Optional components:** `LaTeX_OCR_rec` model (offline LaTeX), Qt WebEngine and local MathJax 2 assets (preview) |
| [`tools/document-processing/pdf-ocr.py`](tools/document-processing/pdf-ocr.py) | **(GUI) Local OCR for scanned PDFs** adds selectable, highlightable text while preserving the original page content. It uses lightweight local PaddleOCR models and supports downloadable language models. | **Python pkgs:** `PySide6`, `PyMuPDF`, `fonttools`, `rapidocr>=3.10,<4`, `onnxruntime`, `numpy`, OpenCV; extension languages require model downloads. |
| [`tools/document-processing/pdf-binarizer.py`](tools/document-processing/pdf-binarizer.py) | **(GUI) Scanned PDF binarization and compression**<br />Apply adaptive thresholding to embedded images and choose how to process detected illustrations, text on dark backgrounds and vector elements. | **Python pkgs:** `PySide6`, `PyMuPDF`, `pypdf`, `Pillow` (with libtiff), `numpy`, `opencv-python`, `tqdm` |
| [`tools/document-processing/pdf-decryptor.py`](tools/document-processing/pdf-decryptor.py) | **PDF protection and PDF/A identification removal:**<br />Removes encryption, permission restrictions, and PDF/A identification while retaining document structure and other metadata. | **Python pkg:** `PyMuPDF` |
| [`tools/document-processing/pdf-metadata-editor.py`](tools/document-processing/pdf-metadata-editor.py) | **(GUI) PDF properties, custom fields and XMP metadata editor**<br />Save a copy with optional PDF/A identification, permission restrictions or an opening password. | **Python pkgs:** `PySide6`, `PyMuPDF`, `PyYAML` |
| [`tools/document-processing/pdf-bookmark-editor.py`](tools/document-processing/pdf-bookmark-editor.py) | **(GUI) Scanned PDF table-of-contents recognition, bookmark and page-label editor**<br />Select a table-of-contents region and use a cloud or local vision model to read it page by page and add the entries as PDF bookmarks. Edit **page labels** and the bookmark tree. | **Python pkgs:** `PySide6`, `PyMuPDF`, `PyYAML` |
| [`tools/document-processing/pdf-page-splitter.py`](tools/document-processing/pdf-page-splitter.py) | **(GUI) Scanned PDF page splitter**<br />Split double-page scans into individual pages. | **Python pkgs:** `PySide6`, `PyMuPDF`, `tqdm` |
| [`tools/document-processing/document-screenshot.py`](tools/document-processing/document-screenshot.py) | **(GUI) Automatic page turning and screenshots**<br />Turn pages automatically and save screenshots of a selected screen region.<br />Avoid using this tool to bypass copyright protection. The project accepts no responsibility for disputes arising from such use. | **Windows/macOS/Linux X11**; Wayland is not supported<br />macOS: Accessibility and Screen Recording permissions<br />**Python pkgs:** `mss`, `pynput`, `Pillow` |

### Video Download

| Script | Description | Requirements |
|------|------|------|
| [`tools/download/bbdown-bilibili-downloader.py`](tools/download/bbdown-bilibili-downloader.py) | **Bilibili video downloader based on BBDown:**<br />(quality/audio only/subtitles/danmaku/multiple APIs)<br />Note: BBDown is no longer maintained; Bilibili downloads will be migrated to yt-dlp later. | `BBDown`, `ffmpeg`, `aria2` (optional) |
| [`tools/download/yt-dlp-video-downloader.py`](tools/download/yt-dlp-video-downloader.py) | **Video downloader based on yt-dlp:**<br />(quality/audio/subtitles/cookies/playlists) | `yt-dlp`, `ffmpeg`, `deno` (optional) |
| [`tools/download/yt-dlp-m3u8-downloader.py`](tools/download/yt-dlp-m3u8-downloader.py) | **m3u8/HLS stream downloader based on yt-dlp** | `yt-dlp`, `ffmpeg` |

### Video/Image Editing

| Script | Description | Requirements |
|------|------|------|
| [`tools/multimedia/ffmpeg-video-trimmer.py`](tools/multimedia/ffmpeg-video-trimmer.py) | **Video trimming tool based on FFmpeg:**<br />Note: this trims **by time**; it does not crop the picture. | `ffmpeg` |
| [`tools/research/image-cropper.py`](tools/research/image-cropper.py) | **Batch image-cropping tool based on OpenCV:**<br />Crops images to a selected ROI. | **Python pkgs:** `opencv-python`, `numpy` |

### File System/Disk Mounting

| Script | Description | Requirements |
|------|------|------|
| [`tools/filesystem/disk-inventory.py`](tools/filesystem/disk-inventory.py) | **Disk and partition inventory:** Shows a device tree with mount points, drive letters, labels, capacities, and full native IDs. | Windows: `pwsh` 7; Linux: `lsblk`; macOS: `diskutil` |
| [`tools/filesystem/path-in-use.py`](tools/filesystem/path-in-use.py) | **File/directory usage query:** Lists the PIDs and executable paths of processes using a file or directory. Supports recursive directory checks, including drive roots and mount points. | `psutil`;<br />**Elevation required** |
| [`tools/filesystem/openssl-file-hasher.py`](tools/filesystem/openssl-file-hasher.py) | **File hash calculator based on OpenSSL:**<br />Processes files in batches and supports common algorithms provided by OpenSSL, including `md5` and `sha256`. | `openssl` |
| [`tools/filesystem/filename-shortener.py`](tools/filesystem/filename-shortener.py) | **Automatic long-filename truncation tool:**<br />Counts the UTF-8 encoded byte length and truncates filenames that exceed a specified limit (143 bytes by default, for compatibility with Synology encrypted-folder limits).<br />Extensions are **preserved**, and collisions receive an automatic `_1`, `_2`, and so on before the extension. | |
| [`tools/filesystem/file-timestamp-editor.py`](tools/filesystem/file-timestamp-editor.py) | **File and folder timestamp editor**<br />Change creation, modification and access times with optional random jitter. Back up and restore timestamps for all files and folders under a selected directory. | |
| [`tools/macos/ntfs-3g-mount-manager.py`](tools/macos/ntfs-3g-mount-manager.py) | **macOS only. Read-write NTFS mounting with ntfs-3g-mac**<br />Scan for NTFS partitions automatically, then mount, unmount or eject them. | **macOS only**<br />**Elevation required**<br />Allow kernel extensions from identified developers in Safe Mode, then install the `macFUSE` kernel extension and the `ntfs-3g-mac` mounting tool. |

### File System/Symbolic Link Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| [`tools/filesystem/link-creator.py`](tools/filesystem/link-creator.py) | **Symbolic-link/hard-link creation tool** (also supports directory symlinks, or SYMLINKD, and JUNCTION links on Windows):<br />Supports relative paths, mirror mode, and conflict handling. | |
| [`tools/filesystem/link-scanner.py`](tools/filesystem/link-scanner.py) | **Recursive symbolic-link and hard-link scanner**<br />List links in a directory and repair or remove links whose targets no longer exist. On Windows, also list directory symlinks (SYMLINKD) and junctions, and convert file symlinks pointing to directories into directory symlinks. | |
| [`tools/windows/directory-symlink-repair.py`](tools/windows/directory-symlink-repair.py) | **Windows only.** Convert file symlinks (SYMLINK) that point to directories into **directory symlinks** (SYMLINKD). This repairs inaccessible links created by sync tools that handle file and directory symlinks alike on Linux and Windows. | **Windows only** |

### File System/Permission Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| [`tools/filesystem/executable-bit-setter.sh`](tools/filesystem/executable-bit-setter.sh) | **Linux/macOS only. Batch executable permissions for scripts**<br />Find files recursively by extension (default: `.py` and `.sh`) and apply `chmod +x`. | **Linux/macOS**<br />**Elevation required** |
| [`tools/filesystem/git-executable-bit-setter.ps1`](tools/filesystem/git-executable-bit-setter.ps1) | **Windows only. Batch executable permissions for scripts in Git**<br />Apply `git update-index --chmod=+x` to staged `.py` and `.sh` files so they are executable when cloned on Linux or macOS. | **Windows**<br />`git` |
| [`tools/macos/quarantine-remover.py`](tools/macos/quarantine-remover.py) | **macOS only**, a tool for **removing `quarantine` and `provenance` attributes from files in batches**, based on the `xattr` command. | **macOS only** |

### Network Tools

| Script | Description | Requirements |
|------|------|------|
| [`tools/network/tailscale-refresh-routes.py`](tools/network/tailscale-refresh-routes.py) | **Tailscale subnet-route restart tool:**<br />Restores subnet routing on macOS when it stops working after a device returns home and then leaves again. | `tailscale` |
| [`tools/network/rclone-sync.py`](tools/network/rclone-sync.py) | **Manual rclone task runner with personal YAML configurations**<br />Use reusable profiles and machine-specific subtasks to sync, copy, move or compare file and directory pairs across cloud storage and USB drives. Locate removable drives by volume label. | `rclone`<br />**Python pkg:** `PyYAML`<br />Volume discovery: Windows `pwsh` 7; Linux `lsblk`; macOS `diskutil` |
| [`tools/network/network-info-uploader.py`](tools/network/network-info-uploader.py) | **Local network-interface information collector and uploader:**<br />Collects network-interface information, especially IP addresses, and uploads it to an S3 bucket for remote access. | **Python pkg:** `boto3` |
| [`tools/windows/firewall-app-blocker.py`](tools/windows/firewall-app-blocker.py) | **Windows only. Firewall rules for blocking network access by `.exe` and `.com` files**<br />**Recursively find executables under a selected path**, then add blocking rules or remove them to restore access. | **Windows only**<br />**Elevation required** |
| [`tools/network/http-server.py`](tools/network/http-server.py) | **Local HTTP server:** Serves files from a local directory or hosts a website containing `index.html`. | |

### Open With

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| [`tools/windows/file-association-manager.py`](tools/windows/file-association-manager.py) | **Windows only. Register an executable as an Open With handler**<br />Associate selected file extensions with an application, including portable applications. | **Windows only**<br />**Elevation required** |
| [`tools/others/script-to-app.py`](tools/others/script-to-app.py) | **App-style launchers for Python scripts**<br />Launch an existing script in a chosen Conda environment without packaging it. Create a `.cmd` launcher on Windows, a movable or renameable app on macOS, or a Linux file handler for selected MIME types or all files. | **Desktop environment required**<br />Linux requires Bash and a desktop terminal (`desktop-file-utils` optional).<br />**Elevation required on all platforms** |

### Keyboard and Text

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| [`tools/input-and-text/auto-typer.py`](tools/input-and-text/auto-typer.py) | **(GUI) Auto Typer** simulates typing to enter clipboard or manually edited text into the foreground window one character at a time.<br />It uses simulated keystrokes to mimic pasting in web VNC sessions without paste support.<br />It sends ASCII characters as simulated keystrokes and attempts to send other characters as system Unicode events. | **Windows/macOS only**<br />**Python package:** `PySide6`.<br />macOS also requires `pyobjc-framework-Cocoa`, `pyobjc-framework-Quartz` and Accessibility permission.<br />**Elevation required on Windows only** |
| [`tools/input-and-text/screen-keyboard.py`](tools/input-and-text/screen-keyboard.py) | **(GUI) Screen Keyboard** supports one-shot modifiers, long-press locking and a numeric keypad.<br />Layer mode turns `CapsLock` into the layer key used by [custom-karabiner-config](https://github.com/BH2WFR/custom-karabiner-config) and [custom-autohotkey-config](https://github.com/BH2WFR/custom-autohotkey-config). | **Windows/macOS only**<br />**Python package:** `Tkinter`<br />macOS also requires PyObjC Cocoa/Quartz and Accessibility permission. In layer mode, Karabiner requires CGEventTap fallback.<br />**Elevation required on Windows only** |
| [`tools/input-and-text/keyboard-hook-viewer.py`](tools/input-and-text/keyboard-hook-viewer.py) | **Global keyboard and mouse hook monitor**<br />View scroll direction across platforms. Windows shows scan codes and raw scroll deltas and distinguishes left/right modifiers and keypad Enter. macOS reports precise scrolling, pinch deltas and source device details when available. Linux uses X11 XRecord.<br />For legitimate keyboard testing, custom hotkeys and authorized automation only. The project accepts no responsibility for misuse. | **Windows/macOS/Linux X11** only. Wayland is unsupported.<br />macOS: `pip install pyobjc-framework-Quartz`<br />Linux: `pip install python-xlib`<br />Windows: none (standard-library `ctypes`) |
| [`tools/input-and-text/text-processor.py`](tools/input-and-text/text-processor.py) | **(GUI) Text and Path Processor**<br />**1.** Extract full paths from files and folders copied in Explorer or Finder, then convert them line by line. Handle environment variables, change Windows path separators, convert to MSYS paths, or add and remove the `file://` prefix.<br />**2.** Replace line breaks with spaces and expand ligatures in text copied from PDFs.<br />**3.** Convert letters and digits to styled Unicode characters, adjust spacing and indentation, or switch between full-width and half-width characters. | **Python package:** `PySide6`.<br />On macOS, `pyobjc-framework-Cocoa` is optional for reading native Finder filename lists. |
| [`tools/input-and-text/unicode-inspector.py`](tools/input-and-text/unicode-inspector.py) | **(GUI) Unicode text inspector** displays code points, UTF-8 bytes, names and categories, highlights invisible characters, and provides text statistics and copyable reports. | **Python pkg:** `PySide6` |
| [`tools/windows/keyboard-remapper.py`](tools/windows/keyboard-remapper.py) | **Windows only. Registry-based keyboard mapping editor**<br />Remap or disable keys, with optional backup and restore of the mappings. | **Windows** only<br />**Python package:** `PySide6`<br />**Elevation required**. Changes take effect after a Windows restart. |

### Input Method Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| [`tools/IME/rime-aux-code-generator.py`](tools/IME/rime-aux-code-generator.py) | Extracts first or first/last codes from Rime shape dictionaries to build auxiliary-code schemes, with configurable single-code handling and character filters. The auxiliary codes are used with the Lua scripts provided by [https://github.com/HowcanoeWang/rime-lua-aux-code](https://github.com/HowcanoeWang/rime-lua-aux-code). | **Python pkgs:** `PyYAML`, `tqdm` |
| [`tools/IME/rime-userdict-to-dict.py`](tools/IME/rime-userdict-to-dict.py) | Converts Rime user dictionary text snapshots or exports into `.dict.yaml`, excluding deleted entries and supporting frequency-based weight scaling. | **Python pkgs:** `PyYAML`, `tqdm` |

### Display Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| [`tools/windows/display-info-viewer.py`](tools/windows/display-info-viewer.py) | **Windows only. Screen resolution and scaling viewer**<br />Check the remote computer’s resolution and scaling in an RDP session when Windows Settings does not show them. | **Windows only** |
| [`tools/macos/display-manager.py`](tools/macos/display-manager.py) | **Apple Silicon Macs only. Display manager**<br />Rotate displays, adjust built-in and external display brightness (via DDC/CI), diagnose color modes and force RGB output on external displays.<br />**Toggle the MacBook’s built-in display while an external monitor is connected** with `--toggle-built-in`. **Display rotation and external brightness adjustment are also supported.** Tested on macOS Tahoe 26.x. Compatibility with other versions depends on private macOS APIs. | **macOS only** (Apple Silicon)<br />**Optional Python pkg:** `pyobjc-framework-Cocoa` |

### Privacy and Cleanup

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| [`tools/windows/recycle-bin-cleaner.py`](tools/windows/recycle-bin-cleaner.py) | **Windows only. Force-empty the Recycle Bin**<br />Remove **0 KB files or folders that remain after emptying the Recycle Bin**. For symbolic links, remove only the link itself. | **Windows only**<br />**Elevation required** |
| [`tools/windows/event-log-cleaner.py`](tools/windows/event-log-cleaner.py) | **Windows only. One-click system event log cleanup**<br />Cleared logs cannot be recovered. | **Windows only**<br />**Elevation required** |
| [`tools/windows/privacy-cleaner.py`](tools/windows/privacy-cleaner.py) | **Windows only. Privacy cleanup**<br />Clear File Explorer history, event logs, DNS cache, browser data, credentials and temporary files, with confirmation for each category.<br />**Use at your own risk.** | **Windows only**<br />**Elevation required** |
| [`tools/macos/privacy-cleaner.py`](tools/macos/privacy-cleaner.py) | macOS-only **privacy-trace cleanup tool:**<br />Covers recent items, Finder state, shell history, browser data, caches, logs, and more.<br />Warning: **Use at your own risk.** | **macOS only**<br />Optional: `brew install trash`<br />**Elevation required** |
| [`tools/filesystem/os-junk-cleaner.py`](tools/filesystem/os-junk-cleaner.py) | **Recursive cleanup tool for OS-generated junk files:**<br />(`.DS_Store`, `__MACOSX__`, `Thumbs.db`, and others) | |
| [`tools/windows/android-rndis-record-cleaner.py`](tools/windows/android-rndis-record-cleaner.py) | Windows-only tool for **removing stale Android USB tethering/RNDIS records from the registry:**<br />Prevents the network connection number from continually increasing each time USB tethering is enabled after connecting an Android device. | **Windows only**<br />**Elevation required** |

### System Tools

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| [`tools/windows/device-ejection-history.py`](tools/windows/device-ejection-history.py) | **Windows only. Failed device ejection log viewer, primarily for USB devices**<br />Look up the process ID, executable path and device ID in Windows event logs to **identify the process preventing safe ejection of a USB drive**. | **Windows 10+ only**;<br />**Elevation required** |
| [`tools/windows/service-restarter.py`](tools/windows/service-restarter.py) | **Windows only. Force-restart system services**<br />Choose whether to wait for the restart. The `Windows Audio` preset **can temporarily restore sound redirection from the remote computer in an RDP session**. | **Windows only**<br />**Elevation required** |
| [`tools/others/power-status-viewer.py`](tools/others/power-status-viewer.py) | **Charger and battery information viewer**<br />**On macOS, see how much power the computer is drawing to charge.** Readings come from `ioreg` on macOS, PowerShell CIM/WMI on Windows and `/sys/class/power_supply` on Linux. Available fields depend on firmware and drivers. **macOS provides the most complete readings.** | **Best on macOS**; other systems are also supported, with some fields unavailable because of firmware or driver limitations |
| [`tools/others/system-event-viewer.py`](tools/others/system-event-viewer.py) | **(GUI) Cross-platform system log and event viewer**<br />Review power events, logins, faults, device and network changes, updates, and resource or service issues. Includes SSH and Windows RDP/SMB connection and authentication records, plus logs showing why a device could not be ejected. | **macOS / Windows 10+ / Linux with systemd**; coverage depends on retained logs/reports and OS services; Windows Security/share events require prior auditing; Linux lock and hang detection is limited<br />**Python pkg:** `PySide6` |
| [`tools/others/disk-smart-info-viewer.py`](tools/others/disk-smart-info-viewer.py) | **Disk health information viewer based on smartmontools:**<br />Lists SMART-capable disks and displays detailed attributes such as total writes, power-on time, and remaining life. | `smartmontools`<br />**Elevation required** |
| [`tools/macos/rdp-clipboard-image-repair.py`](tools/macos/rdp-clipboard-image-repair.py) | **macOS only. RDP clipboard image repair**<br />When an image copied from Windows through Windows App (RDP) will not paste on macOS, convert TIFF clipboard data mislabeled as PNG into a valid PNG. Use `--force` to repair without confirmation. | **macOS only**<br />Built-in `osascript` and AppKit |

### Software Launching

| Script | Description | Requirements |
| ------ | ----------- | ------------ |
| [`tools/macos/run-pdf2zh.sh`](tools/macos/run-pdf2zh.sh) | macOS-only launcher for **pdf2zh-next** ([PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next)). | **macOS only** |

### Command Presets

| Script | Description | Requirements |
|------|------|------|
| [`tools/others/command-runner.py`](tools/others/command-runner.py) | **Preset command runner**<br />Choose a configuration file, then select a saved command or script from its menu. See the [configuration sample](tools/others/run-commands-schema-sample.yaml) for details. | **Python pkg:** `PyYAML`; programs or runtimes required by the selected preset |

### Research Tools

| Script | Description | Requirements |
|------|------|------|
| [`tools/research/matrix-viewer.py`](tools/research/matrix-viewer.py) | **(GUI) Matrix and signal viewer for scientific research**<br />Explore 1D arrays, 2D matrices and point clouds from `.npy`, `.npz`, `.mat`, `.csv`, `.xls` and `.xlsx` files, or open images as matrices. Compare matrices side by side, switch between 2D, 3D, 1D slice and slice-derivative views, crop by coordinate or value range, and export matrices or slices. For complex data, inspect magnitude and phase, apply Fourier or Laplace transforms, and convert values to decibels. | **Python pkgs:** `numpy`, `opencv-python`, `Pillow`, `matplotlib`, `PySide6`, `pyqtgraph`, `pyvista`, `pyvistaqt`, `vtk`, `scipy`, `h5py`, `openpyxl`, `xlrd` |
| [`tools/research/pattern-generator.py`](tools/research/pattern-generator.py) | **Structured-light projection pattern generator:**<br />Generates sinusoidal stripes with selectable left/top-edge, center, or right/bottom-edge pixel sampling, plus standard Gray-code sequences.<br />Not intended for non-specialists. | **Python pkgs:** `opencv-python`, `numpy` |

### Test/Helper Scripts

| Script | Description | Requirements |
|------|------|------|
| [`test/print-argv.py`](test/print-argv.py)<br>[`test/print-argv.sh`](test/print-argv.sh)<br>[`test/print-argv.ps1`](test/print-argv.ps1) | **Command-line argument printer:**<br />Prints every `argv` argument passed to the script, for checking whether arguments are being forwarded correctly. | |
