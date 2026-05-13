from my_utils import *
# 基于 yt-dlp 的 m3u8 视频下载器
# 要求先使用 scoop 安装 yt-dlp, ffmpeg 和 deno 三个包



print(f"{FLYellow}=========== YT-DLP TOOL ==========={CRst}")


Utils.console_command_required("yt-dlp")
Utils.console_command_required("ffmpeg")



FFMPEG_PATH = "ffmpeg.exe" if os.name == 'nt' else "ffmpeg"
# ARIA2C_PATH = "aria2c.exe" if os.name == 'nt' else "aria2c"

#* 下载到哪里？
OUTPUT_DIR = input(f"{FLYellow}Enter output directory (default: ./downloads): {CRst}") or "./downloads"
if(not os.path.exists(OUTPUT_DIR)):
	print(f"{FLRed}Output directory does not exist. EXIT...{CRst}\n")
	sys.exit(1)
