# Personal Scripts

[中文版 (Chinese)](./README_zh.md)

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

| Script | Description | Requires |
|--------|-------------|----------|
| `disk-smart-info.py` | Cross-platform SMART disk health viewer. Lists SMART-capable disks and displays detailed attributes | `smartmontools` |
| `tailscale-restart-accept-routes.py` | Restart Tailscale subnet routes by toggling `--accept-routes` off/on | `tailscale` |
| `upload-ipaddress.py` | Collect network info (`ipconfig`/`ip addr`) and upload to Tencent COS S3 for remote access. Credentials from environment variables | `boto3` |
| `macos/ntfs-3g-utils.py` | macOS-only: NTFS disk manager with read-write support via ntfs-3g (macFUSE). Mount, system-mount, eject | `ntfs-3g` |
| `macos/screen-utils.py` | macOS-only (Apple Silicon): Display management — rotation, brightness (built-in + DDC/CI), toggle internal display | — |
| `power-current.py` | Cross-platform charger and battery telemetry viewer. macOS uses `ioreg`; Windows uses PowerShell CIM/WMI battery classes; Linux uses `/sys/class/power_supply`. On some Windows devices, charger wattage and live power fields may be unavailable if the firmware/driver does not expose them. | — |
| `macos/remove-quarantine.py` | macOS-only: Remove quarantine attribute from files/folders (batch support) | — |
| `windows/clear-android-rndis-record.ps1` | Remove stale Android USB tethering/RNDIS network profiles from Windows registry | — |
| `windows/clear-privacy..py` | Clear Windows privacy traces (Explorer history, event logs, DNS cache, browser data, credentials, temp files, etc.) with per-section confirmation and helper-based elevation fallback (`sudo` -> `gsudo`). **Disclaimer: use at your own risk. The author assumes no responsibility for system damage or data loss.** | — |
| `windows/show-screen-resolution.ps1` | Display monitor resolution and screen info via Windows API | — |
| `macos/clear-privacy.py` | Clear macOS privacy traces (recent items, Finder state, shell history, browser data, caches, logs, etc.) with per-section confirmation. **Disclaimer: use at your own risk. The author assumes no responsibility for system damage or data loss.** | — |

### Utilities

| Script | Description |
|--------|-------------|
| `parse-unicode-string.py` | Parse and display Unicode character info (index, char, hex, dec, description) with color-coded special characters |
| `research/npy-viewer.py` | Interactive viewer for `.npy`/`.npz` files (1D line/bar/scatter, 2D heatmap/surface) |
| `research/npy-viewer.bat` | Windows: double-click/drag-and-drop launcher for npy viewer |
| `research/npy-viewer.sh` | Linux/macOS: double-click launcher for npy viewer |
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

Core utility module: `utils/` — provides ANSI color codes, cursor/screen control sequences, logging helpers, and platform utilities.

### Python Environment

**Windows / macOS / Linux:** install [Miniconda](https://docs.conda.io/en/latest/miniconda.html), then install packages into the base environment:

```bash
pip install pypdf boto3 opencv-python mss pynput Pillow matplotlib numpy
```

The launcher auto-detects conda Python at `~/miniconda3/bin/python`.

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
- Color output via `utils` ANSI codes (`FLYellow`, `FLGreen`, `FLRed`, etc.)
- Platform-specific scripts are in `windows/`, `linux/`, `macos/` subdirectories
- The `parse-unicode-string.py` script displays Unicode character info with color-coded control/whitespace/normal characters
