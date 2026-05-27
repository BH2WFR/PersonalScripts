# Personal Scripts

A collection of cross-platform utility scripts for daily tasks — PDF processing, file linking, video downloading, system utilities, and more.

Most scripts support both interactive mode and command-line arguments. Use `python <script>.py --help` for usage details.

## Quick Start

```bash
# Interactive mode: lists supported scripts, select by number
./run-script.sh                                # Linux/macOS
.\run-script.ps1                               # Windows

# Run a specific script directly
./run-script.sh <script_name> [args...]        # Linux/macOS
.\run-script.ps1 <script_name> [args...]       # Windows

# List available scripts without running
./run-script.sh --list                         # Linux/macOS
.\run-script.ps1 --list                        # Windows
```

**Launcher Features:**
- Interactive script selection by number (root scripts first, then subfolders)
- Platform-aware filtering: Linux/macOS launcher hides `windows/` scripts; Windows launcher hides `linux/` and `macos/` scripts
- Auto-detects Python: prefers miniconda/anaconda, falls back to `python3`
- On Linux without conda, auto-creates `.venv` to bypass PEP 668 restrictions

---

## Scripts

### PDF Tools

| Script | Description | Requires |
|--------|-------------|----------|
| `pdf-decrypt.py` | Decrypt password-protected PDFs (including permission-only protection), preserving full document structure | `pypdf` |
| `pdf-bookmarks-add.py` | Add table-of-contents bookmarks to PDFs from LLM-generated JSON (page/level/index/title) | `pypdf` |
| `document-screenshot.py` | Auto-capture PDF screenshots (PgDn simulation + mouse clicks) | `mss`, `pynput`, `Pillow` |

### Video Downloaders

| Script | Description | Requires |
|--------|-------------|----------|
| `download-bilibili.py` | Bilibili video downloader (quality, audio-only, subtitles, danmaku, multi-API) | `BBDown`, `ffmpeg`, `aria2` (optional) |
| `download-yt.py` | YouTube video downloader (quality, audio, subtitles, cookies, playlist) | `yt-dlp`, `ffmpeg` |
| `download-m3u8.py` | m3u8/HLS stream downloader with custom headers support | `yt-dlp`, `ffmpeg` |

### Video / Image Editing

| Script | Description | Requires |
|--------|-------------|----------|
| `ffmpeg-crop-video.py` | Trim/cut videos by time range (not frame cropping) | `ffmpeg` |
| `research/batch-crop-images.py` | Batch crop images with interactive ROI selection | `cv2` |

### File System & Links

| Script | Description |
|--------|-------------|
| `link-create.py` | Cross-platform symlink/hardlink creation (Windows: SymlinkD, Junction; Linux/macOS: Symlink, Hardlink). Supports relative paths, mirror modes, conflict handling |
| `link-scan.py` | Recursively scan directories for symlinks, Junctions, hardlinks. Detect broken links, auto-fix or delete |
| `link-fix-symlinkd.py` | Windows-only: Convert broken directory symlinks to symlinkd |
| `check-filename-overlong.py` | Check and truncate overlong filenames by UTF-8 byte limit (e.g., Synology NAS 143-byte limit) |
| `remove-os-junk-files.py` | Recursively remove OS-generated junk files (`.DS_Store`, `__MACOSX__`, `Thumbs.db`, etc.) |
| `modify-file-time.py` | Modify file/folder timestamps (created, modified, accessed) with optional random jitter |
| `batch-add-chmod-x.sh` | Recursively add `chmod +x` to `.py`/`.sh` files via git (requires sudo) |
| `git-batch-add-chmod-x.ps1` | PowerShell version: mark `.py`/`.sh` files as executable in git index |

### System & Network

| Script | Description |
|--------|-------------|
| `upload-ipaddress.py` | Collect network info (`ipconfig`/`ip addr`) and upload to Tencent COS S3 for remote access. Credentials from environment variables |
| `macos/remove-quarantine.py` | macOS-only: Remove quarantine attribute from files/folders (batch support) |
| `windows/clear-android-rndis-record.ps1` | Remove stale Android USB tethering/RNDIS network profiles from Windows registry |
| `windows/show-screen-resolution.ps1` | Display monitor resolution and screen info via Windows API |

### Utilities

| Script | Description |
|--------|-------------|
| `parse-unicode-string.py` | Parse and display Unicode character info (index, char, hex, dec, description) with color-coded special characters |
| `research/show_npy.py` | Interactive viewer for `.npy`/`.npz` files with line chart rendering |
| `research/open-npy-viewer.bat` | Batch launcher for npy viewer (drag-and-drop support) |
| `run-script.sh` | Bash launcher for running any script in the repo |
| `run-script.ps1` | PowerShell launcher for running any script in the repo |

### Test Helpers

| Script | Description |
|--------|-------------|
| `test/print-argv.py` | Print all command-line arguments |
| `test/print-argv.ps1` | PowerShell: print all arguments with color |
| `test/print-argv.sh` | Bash: print all arguments with color |

---

## Dependencies

Core utility module: `my_utils/` — provides ANSI color codes, logging helpers, and platform utilities.

### Python Environment

**Windows / macOS with miniconda:** the launcher auto-detects conda Python.

**Ubuntu / Debian (PEP 668):** the launcher auto-creates `.venv` on first run. Install packages into it:

```bash
./run-script.sh                                      # creates .venv automatically
.venv/bin/python -m pip install pypdf boto3 ...      # install dependencies
```

If pip is missing in `.venv`, install system packages first:

```bash
sudo apt install python3-venv python3-pip
```

**Manual pip install** (if using system Python directly):

```bash
pip install pypdf boto3 opencv-python mss pynput Pillow matplotlib numpy unicodedata
```

External tools (via package manager):
```bash
scoop install ffmpeg yt-dlp aria2 BBDown    # Windows
brew install ffmpeg yt-dlp aria2             # macOS
apt install ffmpeg yt-dlp                    # Linux
```

---

## Conventions

- All Python scripts support `--help` / `-h` for usage info (English, with color)
- Command-line arguments suppress interactive prompts (batch-friendly)
- Multi-line input uses EOF (`Ctrl+Z` on Windows, `Ctrl+D` on Linux/macOS)
- Color output via `my_utils` ANSI codes (`FLYellow`, `FLGreen`, `FLRed`, etc.)
- Platform-specific scripts are in `windows/`, `linux/`, `macos/` subdirectories
- The `parse-unicode-string.py` script displays Unicode character info with color-coded control/whitespace/normal characters
