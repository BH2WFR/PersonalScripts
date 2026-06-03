from utils import *
# 基于 yt-dlp 的 m3u8 流媒体视频下载器
# 要求先使用 scoop 安装 yt-dlp, ffmpeg


print(f"{FLYellow}=========== M3U8 DOWNLOAD TOOL ==========={CRst}")

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
M3U8 DOWNLOAD TOOL - m3u8 Stream Downloader
============================================

Usage:
  python {script_name} <url1> <url2> ...    specify URLs, skip URL input
  python {script_name}                       no arguments, interactive mode
  python {script_name} --help                show this help

{FLYellow}Description:{CRst}
  yt-dlp-based m3u8/HLS stream video downloader.
  Requires: yt-dlp, ffmpeg.

{FLYellow}Interactive Options:{CRst}
  Output directory, m3u8 URLs (multi-line EOF input), output filename template,
  custom referer/header.
""")
    sys.exit(0)


Utils.console_command_required("yt-dlp")
Utils.console_command_required("ffmpeg")


#* 下载到哪里？
OUTPUT_DIR = input(f"{FLYellow}Enter output directory (default: ./downloads): {CRst}") or "./downloads"
if not os.path.exists(OUTPUT_DIR):
    print(f"{FLRed}Output directory does not exist. EXIT...{CRst}\n")
    sys.exit(1)


#* 链接
if len(sys.argv) > 1:
    URLS = []
    for i in range(1, len(sys.argv)):
        u = sys.argv[i].strip()
        if not u.startswith("-") and u:
            URLS.append(u)
else:
    print(f"{FLYellow}Enter m3u8 URLs (one per line).{CRst}")
    print(f"{FLCyan}End with a `EOF`, Windows: {FLYellow}Enter->Ctrl+Z{FLCyan}; Linux: {FLYellow}Enter->Ctrl+D{FLCyan}):{CRst}")
    URLS_INPUT = sys.stdin.read().strip()
    if not URLS_INPUT:
        print(f"{FLRed}No URLs provided. EXIT...{CRst}\n")
        sys.exit(1)
    URLS = []
    for line in URLS_INPUT.splitlines():
        line = line.strip()
        if line:
            URLS.append(line)

if not URLS:
    print(f"{FLRed}No URLs provided. EXIT...{CRst}\n")
    sys.exit(1)


#* 文件名
FILENAME_TEMPLATE_DEFAULT = "%(title)s.%(ext)s"
FILENAME_TEMPLATE = input(f"{FLYellow}Enter output filename template (default: `{FILENAME_TEMPLATE_DEFAULT}`): {CRst}").strip() or FILENAME_TEMPLATE_DEFAULT
if not FILENAME_TEMPLATE:
    print(f"{FLRed}Invalid filename template. EXIT...{CRst}\n")
    sys.exit(1)

#* Referer / Headers（可选）
CUSTOM_HEADER = input(f"{FLYellow}Enter custom Referer or Header (e.g. 'Referer:https://example.com') (default: none): {CRst}").strip() or ""


#* 下载
print(f"{FLGreen}Starting downloads...{CRst}\n")
succeedCnt: int = 0
failedCnt: int = 0

for idx, url in enumerate(URLS):
    current_output_path = os.path.join(OUTPUT_DIR, FILENAME_TEMPLATE)
    args = [
        "yt-dlp",
        url,
        "--output", current_output_path,
        "--restrict-filenames",
        "--retries", "3",
        "--embed-metadata",
    ]
    if CUSTOM_HEADER:
        args += ["--add-header", CUSTOM_HEADER]

    print(f"{FLYellow}=====[ Downloading {idx + 1}/{len(URLS)} ]====={CRst}")
    print(f"{FLYellow}Executing command:{CRst} {' '.join(args)}\n")
    res = subprocess.run(args).returncode

    if res != 0:
        print(f"{FLRed}Download failed for URL: {url}{CRst}\n")
        failedCnt += 1
    else:
        print(f"{FLGreen}Download completed for URL: {url}{CRst}\n")
        succeedCnt += 1

print(f"{FLGreen}All downloads completed.{CRst} {FLGreen}Succeed: {succeedCnt}{CRst}, {FLRed}Failed: {failedCnt}{CRst}, {FLYellow}Total: {len(URLS)}{CRst}\n")
sys.exit(0 if failedCnt == 0 else 1)
