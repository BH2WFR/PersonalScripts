# Personal Scripts

A collection of cross-platform utility scripts for daily tasks — PDF processing, file linking, video downloading, system utilities, and more.

Most scripts support both interactive mode and command-line arguments. Use `python <script>.py --help` for usage details.

## Quick Start

```bash
# Run any script via the launcher (resolves Python environment automatically)
./run-script.sh <script_name> [args...]      # Linux/macOS
.\run-script.ps1 <script_name> [args...]     # Windows
```

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

Each script declares its own dependencies at the top. Install with:

```bash
pip install pypdf boto3 opencv-python mss pynput Pillow
```

External tools (via package manager):
```bash
scoop install ffmpeg yt-dlp aria2 BBDown    # Windows
brew install ffmpeg yt-dlp aria2             # macOS
apt install ffmpeg yt-dlp                    # Linux
```

---

## Conventions

- All Python scripts support `--help` / `-h` for usage info
- Command-line arguments suppress interactive prompts (batch-friendly)
- Multi-line input uses EOF (`Ctrl+Z` on Windows, `Ctrl+D` on Linux/macOS)
- Color output via `my_utils` ANSI codes (`FLYellow`, `FLGreen`, `FLRed`, etc.)
