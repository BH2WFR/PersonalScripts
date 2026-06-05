from utils import *
# 基于 ffmpeg 的视频裁剪工具
# 需要先安装 ffmpeg，推荐使用 `scoop install ffmpeg` 安装

#============ 默认路径 (OS-aware) ===========
if sys.platform == "win32":
    DEFAULT_OUTPUT_DIR = os.path.join(os.environ.get("USERPROFILE", "C:\\"), "Videos", "cropped")
else:
    DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Videos/cropped")

print(f"{FLYellow}=========== FFMPEG VIDEO CROP TOOL ==========={CRst}")

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
FFMPEG VIDEO CROP TOOL
======================

Usage:
  python {script_name} <video1> <video2> ...    specify video paths, skip interaction
  python {script_name}                          no arguments, interactive mode
  python {script_name} --help                   show this help

{FLYellow}Description:{CRst}
  ffmpeg-based video time-cropping tool (time trimming, not frame cropping).

{FLYellow}Requirements:{CRst}
  Windows (scoop):  {FGray}scoop install ffmpeg{CRst}
  Linux (apt):      {FGray}sudo apt install ffmpeg{CRst}
  macOS (brew):     {FGray}brew install ffmpeg{CRst}
""")
    sys.exit(0)

Utils.console_command_required("ffmpeg")

#* 要裁剪哪个文件？
if len(sys.argv) > 1:
    INPUT_PATHS: list = []
    for i in range(1, len(sys.argv)):
        p = sys.argv[i].strip()
        if not p.startswith("-") and p:
            if not os.path.exists(p):
                print(f"{FLRed}Input file does not exist: {p}. EXIT...{CRst}\n")
                sys.exit(1)
            INPUT_PATHS.append(p)
else:
    INPUT_PATHS = Utils.resolve_input_paths_multi(
        prompt_text="Enter video file paths for cropping... (one per line)",
        path_type="file",
    )

#* 输出到哪里？
output_dir = Utils.resolve_output_path(DEFAULT_OUTPUT_DIR, prompt="Enter output video file dir", path_type="dir")
	
#* 编码是否变更？
is_change_codec_str = input(f"{FLYellow}Change codec? (y/n, default n): {CRst}").strip().lower() or "n"
if(is_change_codec_str not in ['y','n']):
	print(f"{FLRed}Invalid input. EXIT...{CRst}\n")
	sys.exit(1)
is_change_codec = (is_change_codec_str == 'y')

#* 开始时间
start_time = input(f"{FLYellow}Enter start time (format HH:MM:SS.mmm, default 00:00:00): {CRst}").strip() or "00:00:00"
#* 结束时间
end_time = input(f"{FLYellow}Enter end time (format HH:MM:SS.mmm): {CRst}").strip()


#* 开始裁剪
succeedCnt : int = 0
failedCnt : int = 0
for input_filepath in INPUT_PATHS:
	output_filename_splitted = os.path.splitext(os.path.basename(input_filepath))
	output_filename = f"{output_filename_splitted[0]}{output_filename_splitted[1]}" #* 新文件名
	output_path = os.path.join(output_dir, os.path.basename(input_filepath))
	cmd = f'ffmpeg -ss {start_time} -to {end_time} -i "{input_filepath}" '
	if(not is_change_codec):
		cmd += f' -c copy '
	cmd += f'"{output_path}" '
	print(f"{FLYellow}Executing command:{CRst} {cmd}\n")

	res = os.system(cmd)
	if(res != 0):
		print(f"{FLRed}Conversion failed. {CRst}\n")
		failedCnt += 1
	else:
		print(f"{FLGreen}Conversion succeeded. Output file: {output_path}{CRst}\n")
		succeedCnt += 1


print(f"{FLGreen}All conversions completed.{CRst} {FLGreen}Succeed: {succeedCnt}{CRst}, {FLRed}Failed: {failedCnt}{CRst}, {FLYellow}Total: {len(INPUT_PATHS)}{CRst}\n")
