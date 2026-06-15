#!/usr/bin/env python3
import sys
from utils import *
# 基于 yt-dlp 的 m3u8 流媒体视频下载器
# 要求先使用 scoop 安装 yt-dlp, ffmpeg


def main() -> int:
    Utils.print_banner("M3U8 DOWNLOAD TOOL")

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

{FLYellow}Requirements:{CRst}
  Windows (scoop):  {FGray}scoop install yt-dlp ffmpeg{CRst}
  Linux (apt):      {FGray}sudo apt install yt-dlp ffmpeg{CRst}
  macOS (brew):     {FGray}brew install yt-dlp ffmpeg{CRst}

{FLYellow}Interactive Options:{CRst}
  Output directory, m3u8 URLs (multi-line EOF input), output filename template,
  custom referer/header.
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


    FILENAME_TEMPLATE_DEFAULT = "%(title)s.%(ext)s"

    first_iteration = True
    while True:
        #* 下载到哪里？
        OUTPUT_DIR = Input.resolve_output_path("./downloads", prompt="Enter output directory", path_type="dir")

        #* 链接
        if first_iteration and len(sys.argv) > 1:
            URLS = []
            for i in range(1, len(sys.argv)):
                u = sys.argv[i].strip()
                if not u.startswith("-") and u:
                    URLS.append(u)
        else:
            URLS = Input.read_stdin_multiline(prompt_text="Enter m3u8 URLs (one per line).")

        if not URLS:
            Utils.print_exit_message("Bye.")
            return 0
        first_iteration = False

        #* 文件名
        FILENAME_TEMPLATE = Input.prompt(
            f"{FLYellow}Enter output filename template (default: `{FILENAME_TEMPLATE_DEFAULT}`): {CRst}",
            default=FILENAME_TEMPLATE_DEFAULT,
        )

        #* Referer / Headers（可选）
        CUSTOM_HEADER = Input.prompt(
            f"{FLYellow}Enter custom Referer or Header (e.g. 'Referer:https://example.com') (default: none): {CRst}",
            default="",
        )

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
        Utils.print_separator()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
