#!/usr/bin/env python3
import sys
from utils import *

# 基于 BBDown 的 Bilibili 视频下载器
# 要求先使用 scoop 安装 BBDown, aria2 和 ffmpeg 三个包


def main() -> int:
    Utils.print_banner("BBDOWN TOOL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
BBDOWN TOOL - Bilibili Video Downloader
========================================

Usage:
  python {script_name} <url1> <url2> ...    specify URLs, skip URL input
  python {script_name}                       no arguments, interactive mode
  python {script_name} --help                show this help

{FLYellow}Description:{CRst}
  BBDown-based Bilibili video downloader.

{FLYellow}Requirements:{CRst}
  Windows (scoop):  {FGray}scoop install BBDown ffmpeg aria2{CRst}
  Linux (apt):      {FGray}sudo apt install ffmpeg aria2{CRst}
  macOS (brew):     {FGray}brew install ffmpeg aria2{CRst}
  (BBDown must be installed manually from GitHub on Linux/macOS; aria2 is optional for faster downloads)

{FLYellow}Interactive Options:{CRst}
  Output directory, video URLs (multi-line EOF input), download mode
  (quality/audio-only/subtitles/danmaku), part selection, API type
  (default/TV/APP/international).
""")
        return 0

    _ffmpeg = CmdCheck("ffmpeg", hints={
        "windows": f"{FGray}scoop install ffmpeg{CRst}",
        "macos": f"{FGray}brew install ffmpeg{CRst}",
        "linux": f"{FGray}sudo apt install ffmpeg{CRst}",
    })
    _aria2c = CmdCheck("aria2c", required=False, hints={
        "windows": f"{FGray}scoop install aria2{CRst}",
        "macos": f"{FGray}brew install aria2{CRst}",
        "linux": f"{FGray}sudo apt install aria2{CRst}",
    })
    if not Utils.check_commands(
        CmdCheck("BBDown", hints={
            "windows": f"{FGray}scoop install BBDown{CRst}",
            "macos": f"{FGray}Download from https://github.com/nilaoda/BBDown{CRst}",
            "linux": f"{FGray}Download from https://github.com/nilaoda/BBDown{CRst}",
        }),
        _ffmpeg,
        _aria2c,
    ):
        return 1

    USE_ARIA2C = _aria2c.path is not None
    FFMPEG_PATH = _ffmpeg.path
    ARIA2C_PATH = _aria2c.path

    #* 码率、仅下载音频、仅下载字幕、仅下载弹幕
    class E_DOWNLOAD_TYPE(enum.Enum):
        SHOW_INFO_ONLY = 0
        VIDEO_1080P = 1
        VIDEO_720P = 2
        VIDEO_480P = 3
        VIDEO_360P = 4
        AUDIO_ONLY = 5
        DANMAKU_ONLY = 6
        SUBTITLE_ONLY = 7

    #* 解析
    class E_API_TYPE(enum.Enum):
        DEFAULT = 0
        TV = 1
        APP = 2
        INTL = 3 # 国际版

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
            URLS = Input.read_stdin_multiline(prompt_text="Enter Bilibili video URLs (one per line).")

        if not URLS:
            Utils.print_exit_message("Bye.")
            return 0
        first_iteration = False

        BITRATE = Menu.select(
            Menu.from_enum(E_DOWNLOAD_TYPE),
            prompt="Select download mode",
            default_key="2",
        )
        if BITRATE is None:
            Utils.print_exit_message("Bye.")
            return 0

        #* 分P
        PART_INPUT = Input.prompt(
            f"{FLYellow}Part{CRst}, e.g. `{FLCyan}CURRENT{CRst}` `{FLCyan}1,2{CRst}` `{FLCyan}1,2-5{CRst}` `{FLCyan}3,LATEST{CRst}` `{FLCyan}LAST{CRst}` {FGray}(default: {FLCyan}ALL{FGray}){CRst}: {FLYellow}>{CRst}",
            default="ALL",
            transform=str.upper,
        )

        API_TYPE = Menu.select(
            Menu.from_enum(E_API_TYPE),
            prompt="Select API type",
            default_key="0",
        )
        if API_TYPE is None:
            Utils.print_exit_message("Bye.")
            return 0

        #* 下载
        print(f"{FLGreen}Starting downloads...{CRst}\n")
        succeedCnt: int = 0
        failedCnt: int = 0
        for idx, url in enumerate(URLS):
            print(f"{FLYellow}=====[ Downloading video {idx+1}/{len(URLS)} ]====={CRst}")
            cmd = f'BBDown "{url}" --work-dir "{OUTPUT_DIR}" --skip-ai false --ffmpeg-path "{FFMPEG_PATH}" -mt true --force-http true '
            if USE_ARIA2C:
                cmd += ' --use-aria2c'
                cmd += f' --aria2c-path "{ARIA2C_PATH}"'

            if API_TYPE == E_API_TYPE.TV:
                cmd += ' --use-tv-api'
            elif API_TYPE == E_API_TYPE.APP:
                cmd += ' --use-app-api'
            elif API_TYPE == E_API_TYPE.INTL:
                cmd += ' --use-intl-api'

            if BITRATE == E_DOWNLOAD_TYPE.SHOW_INFO_ONLY:
                cmd += ' --only-show-info'
            elif BITRATE == E_DOWNLOAD_TYPE.AUDIO_ONLY:
                cmd += ' --audio-only'
            elif BITRATE == E_DOWNLOAD_TYPE.DANMAKU_ONLY:
                cmd += ' --danmaku-only'
            elif BITRATE == E_DOWNLOAD_TYPE.SUBTITLE_ONLY:
                cmd += ' --sub-only'
            else:
                if BITRATE == E_DOWNLOAD_TYPE.VIDEO_1080P:
                    bitrate_arg = '1080P 高码率,1080P 高清,720P 高清,480P 清晰,360P 流畅'
                elif BITRATE == E_DOWNLOAD_TYPE.VIDEO_720P:
                    bitrate_arg = '720P 高清,480P 清晰,360P 流畅'
                elif BITRATE == E_DOWNLOAD_TYPE.VIDEO_480P:
                    bitrate_arg = '480P 清晰,360P 流畅'
                elif BITRATE == E_DOWNLOAD_TYPE.VIDEO_360P:
                    bitrate_arg = '360P 流畅'
                else:
                    print(f"{FLRed}Invalid bitrate option. EXIT...{CRst}\n")
                    return 1
                cmd += f' --dfn-priority "{bitrate_arg}"'

            if PART_INPUT == "CURRENT":
                part_arg = ''
            elif PART_INPUT == "ALL":
                part_arg = 'ALL'
            else:
                part_arg = PART_INPUT
            if part_arg:
                cmd += f' --select-page "{part_arg}"'

            #* 执行命令
            print(f"{FLCyan}Executing command:{CRst}\n{cmd}\n")
            res = os.system(cmd)

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
