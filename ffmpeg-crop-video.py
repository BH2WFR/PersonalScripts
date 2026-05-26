from my_utils import *
# 基于 ffmpeg 的视频裁剪工具
# 需要先安装 ffmpeg，推荐使用 `scoop install ffmpeg` 安装

print(f"{FLYellow}=========== BBDOWN TOOL ==========={CRst}")
Utils.console_command_required("ffmpeg")

# FFMPEG_PATH = "ffmpeg.exe" if os.name == 'nt' else "ffmpeg"

#* 要裁剪哪个文件？ （多行）
print(f"{FLYellow}Enter video file paths for cropping... (one per line){CRst}")
print(f"{FLCyan}End with a `EOF`, Windows: {FLYellow}Enter->Ctrl+Z{FLCyan}; Linux: {FLYellow}Enter->Ctrl+D{FLCyan}):{CRst}")
INPUT_PATHS_STR = sys.stdin.read().strip()
if(not INPUT_PATHS_STR):
	print(f"{FLRed}No paths provided. EXIT...{CRst}\n")
	sys.exit(1)
INPUT_PATHS : list = []
for line in INPUT_PATHS_STR.splitlines():
	line = line.strip()
	if(line):
		if(not os.path.exists(line)):
			print(f"{FLRed}Input file{CRst} \"{line}\" {FLRed}does not exist: {line}. EXIT...{CRst}\n")
			sys.exit(1)
		INPUT_PATHS.append(line)

#* 输出到哪里？
output_dir = input(f"{FLYellow}Enter output video file dir: {CRst}").strip()
if(not os.path.exists(output_dir) or not os.path.isdir(output_dir)):
	print(f"{FLRed}Output directory {CRst} \"{line}\" {FLRed} does not exist. EXIT...{CRst}\n")
	sys.exit(1)
	
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
