#!/usr/bin/env python3
import sys
from utils import *
# 基于 yt-dlp 的 YouTube 视频下载器
# 要求先使用 scoop 安装 yt-dlp, ffmpeg 和 deno 三个包


def main() -> int:
    Utils.print_banner("YT-DLP TOOL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
YT-DLP TOOL - YouTube Video Downloader
=======================================

Usage:
  python {script_name} <url1> <url2> ...    specify URLs, skip URL input
  python {script_name}                       no arguments, interactive mode
  python {script_name} --help                show this help

{FLYellow}Description:{CRst}
  yt-dlp-based YouTube video downloader.

{FLYellow}Requirements:{CRst}
  Windows (scoop):  {FGray}scoop install yt-dlp ffmpeg deno{CRst}
  Linux (apt):      {FGray}sudo apt install yt-dlp ffmpeg{CRst}
  macOS (brew):     {FGray}brew install yt-dlp ffmpeg{CRst}
  (deno is optional)

{FLYellow}Interactive Options:{CRst}
  Output directory, video URLs (multi-line EOF input), download mode
  (quality/audio-only/subtitles only).
""")
        return 0


    if not Utils.check_commands(
        CmdCheck("yt-dlp", hints={
            "windows": f"{FGray}scoop install yt-dlp{CRst}",
            "macos": f"{FGray}brew install yt-dlp{CRst}",
            "linux": f"{FGray}sudo apt install yt-dlp{CRst}",
        }),
        CmdCheck("ffmpeg", hints={
            "windows": f"{FGray}scoop install ffmpeg{CRst}",
            "macos": f"{FGray}brew install ffmpeg{CRst}",
            "linux": f"{FGray}sudo apt install ffmpeg{CRst}",
        }),
    ):
        return 1

    #* 下载到哪里？
    OUTPUT_DIR = Input.resolve_output_path("./downloads", prompt="Enter output directory", path_type="dir")


    #* 链接
    if len(sys.argv) > 1:
        URLS = []
        for i in range(1, len(sys.argv)):
            u = sys.argv[i].strip()
            if not u.startswith("-") and u:
                URLS.append(u)
    else:
        URLS = Input.read_stdin_multiline(prompt_text="Enter YouTube video URLs (one per line).")

    if not URLS:
        print(f"{FLRed}No URLs provided. EXIT...{CRst}\n")
        return 1

    #* 码率、仅下载音频、仅下载字幕、仅下载弹幕
    class E_DOWNLOAD_TYPE(enum.Enum):
        SHOW_INFO_ONLY = 0
        VIDEO_1080P = 1
        VIDEO_720P = 2
        VIDEO_480P = 3
        VIDEO_360P = 4
        AUDIO_ONLY = 5
        SUBTITLE_ONLY = 6

    for item in E_DOWNLOAD_TYPE:
        print(f"  {FLMagenta}{item.value}{CRst}: {FLYellow}{item.name}{CRst}")
    BITRATE = Menu.select(
        Menu.from_enum(E_DOWNLOAD_TYPE),
        prompt="Select download mode",
    )
    if BITRATE is None:
        print(f"{FLGreen}Bye.{CRst}")
        return 0

    bitrate_option = []
    if(BITRATE == E_DOWNLOAD_TYPE.VIDEO_1080P):
        bitrate_option += ["-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"]
    elif(BITRATE == E_DOWNLOAD_TYPE.VIDEO_720P):
        bitrate_option += ["-f", "bestvideo[height<=720]+bestaudio/best[height<=720]"]
    elif(BITRATE == E_DOWNLOAD_TYPE.VIDEO_480P):
        bitrate_option += ["-f", "bestvideo[height<=480]+bestaudio/best[height<=480]"]
    elif(BITRATE == E_DOWNLOAD_TYPE.VIDEO_360P):
        bitrate_option += ["-f", "bestvideo[height<=360]+bestaudio/best[height<=360]"]
    elif(BITRATE == E_DOWNLOAD_TYPE.AUDIO_ONLY):
        bitrate_option += ["-f", "bestaudio"]
    elif(BITRATE == E_DOWNLOAD_TYPE.SUBTITLE_ONLY):
        bitrate_option += ["--skip-download"]
    #endif


    #* 分P
    PART_INPUT = input(f"{FLYellow}Parts, e.g. `1` `1,2` or range `[START]:[STOP][:STEP]` (negative = from end), example: `1:3,7,-5::2` (default: ALL): {CRst}").strip().upper() or ""

    #* 字幕
    # 默认 --write-subs --write-auto-subs --sub-langs en,zh-Hans,zh-Hant,ko --embed-subs --merge-output-format mkv
    IS_SUBTITLE_INPUT = input(f"{FLYellow}Download subtitles? (y/n, default y): {CRst}").strip().lower() or "y"
    if(IS_SUBTITLE_INPUT not in ['y','n']):
        print(f"{FLRed}Invalid input. EXIT...{CRst}\n")
        return 1
    IS_DOWNLOAD_SUBTITLE = (IS_SUBTITLE_INPUT == 'y')

    #* 字幕语言
    SUBTITLE_LANGS_DEFAULT = "en.*|zh-.*|ko.*|ja.*" # Regex pattern (Zh 右面有横杠, Zh-Hant, Zh-Hans)
    SUBTITLE_LANGS = input(f"{FLYellow}Enter subtitle languages, split by comma (default: {SUBTITLE_LANGS_DEFAULT}): {CRst}").strip() or SUBTITLE_LANGS_DEFAULT


    #* cookies
    COOKIE_PATH = input(f"{FLYellow}Enter path to cookies file (export cookies to txt by this chrome extension https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) (default: none): {CRst}").strip() or ""
    if(COOKIE_PATH and not os.path.exists(COOKIE_PATH)):
        print(f"{FLRed}Cookies file does not exist. reset to not using cookies.{CRst}\n")
        COOKIE_PATH = ""

    #* 文件名
    FILENAME_TEMPLATE_DEFAULT = "%(title)s-%(playlist_index)s.%(ext)s"
    FILENAME_TEMPLATE = input(f"{FLYellow}Enter output filename template (default: `{FILENAME_TEMPLATE_DEFAULT}`): {CRst}").strip() or FILENAME_TEMPLATE_DEFAULT
    if(not FILENAME_TEMPLATE):
        print(f"{FLRed}Invalid filename template. EXIT...{CRst}\n")
        return 1


    #* 下载
    print(f"{FLGreen}Starting downloads...{CRst}\n")
    succeedCnt : int = 0
    failedCnt : int = 0

    for(idx, url) in enumerate(URLS):
        current_output_path = os.path.join(OUTPUT_DIR, FILENAME_TEMPLATE)
        args = [
            'yt-dlp',
            url,
            '--output', current_output_path,
            '--restrict-filenames',
        ]
        args += bitrate_option
        if(COOKIE_PATH):
            args += ['--cookies', COOKIE_PATH]

        if(PART_INPUT):
            args += ['--playlist-items', PART_INPUT]

        if(IS_DOWNLOAD_SUBTITLE == False):
            pass
        else:
            args += ['--write-subs', '--write-auto-subs']
            if(BITRATE != E_DOWNLOAD_TYPE.SUBTITLE_ONLY):
                args += ['--embed-subs', '--merge-output-format', 'mkv']

        if(SUBTITLE_LANGS):
            args += ['--sub-langs', SUBTITLE_LANGS]

        args += ["--sleep-interval", "3", "--max-sleep-interval", "4"]
        args += ["--sleep-subtitles", "3"]
        args += ["--embed-metadata"]
        args += ["--embed-chapters"]
        args += ["--retries", "3"] # 重试次数

        print(f"{FLYellow}=====[ Downloading video {idx+1}/{len(URLS)} ]====={CRst}")
        print(f"{FLYellow}Executing command:{CRst} {' '.join(args)}\n")
        res = subprocess.run(args).returncode
        # 因参数中有 `[` `]` 等特殊字符，在 cmd 环境下会造成解析, 所以不能直接用 os.system(cmd)
        if(res != 0):
            print(f"{FLRed}Download failed for URL: {url}{CRst}\n")
            failedCnt += 1
        else:
            print(f"{FLGreen}Download completed for URL: {url}{CRst}\n")
            succeedCnt += 1
    #endloop



    print(f"{FLGreen}All downloads completed.{CRst} {FLGreen}Succeed: {succeedCnt}{CRst}, {FLRed}Failed: {failedCnt}{CRst}, {FLYellow}Total: {len(URLS)}{CRst}\n")
    return 0


if __name__ == "__main__":
    raise sys.exit(main())
