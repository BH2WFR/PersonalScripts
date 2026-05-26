import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from my_utils import *

import cv2
import locale
from pathlib import Path
import numpy as np
import numpy.typing as npt
from dataclasses import dataclass
from typing import Any, cast


print(f"{FLYellow}=========== BATCH IMAGE CROPPING TOOL ==========={CRst}")

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
BATCH IMAGE CROPPING TOOL
=========================

Usage:
  python {script_name} <dir1> <dir2> ...    直接传入目录路径，跳过交互
  python {script_name}                      无参数，进入交互输入模式
  python {script_name} --help               显示此帮助

功能：
  批量裁剪图片工具。基于 OpenCV (cv2)。
  交互选择输入/输出目录和裁剪区域后，批量裁剪图片。
""")
    sys.exit(0)

ImageArray = npt.NDArray[Any]

@dataclass
class Image:
	original_image: ImageArray | None = None
	cropped_image: ImageArray | None = None
	image_name: str = ""

class Region:
	x1 : int = 0
	y1 : int = 0
	x2 : int = 0
	y2 : int = 0
	def __init__(self, x1:int, y1:int, x2:int, y2:int):
		self.x1 = x1
		self.y1 = y1
		self.x2 = x2
		self.y2 = y2
		pass
	# def __init__(self, coord1 : tuple[int, int], coord2 : tuple[int, int]):
	# 	self.x1 = coord1[0]
	# 	self.y1 = coord1[1]
	# 	self.x2 = coord2[0]
	# 	self.y2 = coord2[1]
	# 	pass


input_directory  = "E:/!重建问题测试/HDR_金属件/HDR"
output_directory = "E:/!重建问题测试/HDR_金属件/HDR_cropped"
crop_rectangle : Region = Region(564, 960, 1533, 1743)   # x, y, w, h
images : list[Image] = []

#============ 用户交互 ===========
if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
    input_directory = sys.argv[1]
else:
    input_directory = input(f"Enter input directory path (default: {input_directory}): ") or input_directory
if(not input_directory or os.path.exists(input_directory) == False):
	print(f"{FLRed}Invalid input directory path. EXIT...{CRst}\n")
	sys.exit(1)

output_directory = input(f"Enter output directory path (default: {output_directory}): ") or output_directory
if(not output_directory):
	print(f"{FLRed}Invalid output directory path. EXIT...{CRst}\n")
	sys.exit(1)
if(not os.path.exists(output_directory)):
	print(f"{FLYellow}Output path does not exist, create it? (y/n, default: y): {CRst}")
	confirm = input().strip().lower() or "y"
	if confirm != "y":
		print(f"{FLRed}Output directory does not exist. EXIT...{CRst}\n")
		sys.exit(1)
	else:
		try:
			os.makedirs(output_directory, exist_ok=True)
			print(f"{FLGreen}Output directory created successfully. ({output_directory}){CRst}\n")
		except Exception as e:
			print(f"{FLRed}Failed to create output directory: {e}. EXIT...{CRst}\n")
			sys.exit(1)

try:
	crop_x1 = int(input(f"Enter crop rectangle {FLYellow}x1{CRst} (default: {crop_rectangle.x1}): ") or crop_rectangle.x1)
	crop_y1 = int(input(f"Enter crop rectangle {FLYellow}y1{CRst} (default: {crop_rectangle.y1}): ") or crop_rectangle.y1)
	crop_x2 = int(input(f"Enter crop rectangle {FLYellow}x2{CRst} (default: {crop_rectangle.x2}): ") or crop_rectangle.x2)
	crop_y2 = int(input(f"Enter crop rectangle {FLYellow}y2{CRst} (default: {crop_rectangle.y2}): ") or crop_rectangle.y2)
	crop_rectangle = Region(crop_x1, crop_y1, crop_x2, crop_y2)
except ValueError:
	print(f"{FLRed}Invalid crop rectangle coordinates. EXIT...{CRst}\n")
	sys.exit(1)


#============ 代码主体部分 ===========
#* 为了支持 UTF-8 路径，（Python 的 OpenCv 不支持用locale强制支持utf-8）
def imread_unicode(path, flags=cv2.IMREAD_REDUCED_GRAYSCALE_8):
	p = Path(path)
	data = np.fromfile(p, dtype=np.uint8)   # 支持中文路径
	img = cv2.imdecode(data, flags)
	return img

def imwrite_unicode(path, img, params=None):
	p = Path(path)
	ok, buf = cv2.imencode(p.suffix, img, params or [])
	if not ok:
		return False
	buf.tofile(p)                          # 支持中文路径
	return True

def load_images_from_directory(directory : str) -> list[Image]:
	images: list[Image] = []
	if not os.path.isdir(directory):
		return images

	valid_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
	for name in sorted(os.listdir(directory)):
		_, ext = os.path.splitext(name)
		if ext.lower() not in valid_exts:
			continue
		path = os.path.join(directory, name)
		mat = imread_unicode(path, cv2.IMREAD_UNCHANGED)
		if mat is None:
			continue
		img = Image()
		img.original_image = cast(ImageArray, mat)
		img.image_name = name
		images.append(img)

	return images

def crop_image(img: Image, region: Region) -> None:
	if img.original_image is None:
		return
	original_image = cast(ImageArray, img.original_image)
	h, w = original_image.shape[:2]
	x1 = max(0, min(region.x1, w))
	y1 = max(0, min(region.y1, h))
	x2 = max(0, min(region.x2, w))
	y2 = max(0, min(region.y2, h))
	if x2 <= x1 or y2 <= y1:
		print(f"{FLRed}Invalid crop region for image {img.image_name}. Skipping cropping.{CRst}")
		return
	img.cropped_image = original_image[y1:y2, x1:x2].copy()
	print(f"  -> image: {FLCyan}{img.image_name}{CRst} cropped to region ({x1}, {y1}), ({x2}, {y2}), region size: ({x2-x1}, {y2-y1}), image size: ({w}, {h})")

def save_cropped_image(img: Image, output_dir: str) -> None:
	if img.cropped_image is None or not img.image_name:
		return
	if not os.path.isdir(output_dir):
		os.makedirs(output_dir, exist_ok=True)
	output_path = os.path.join(output_dir, img.image_name)
	# cv2.imwrite(output_path, img.cropped_image)
	imwrite_unicode(output_path, img.cropped_image)


#* 主程序
os.system("chcp 65001")
os.environ.setdefault("PYTHONUTF8", "1")
try:
	locale.setlocale(locale.LC_ALL, "C.UTF-8")
except locale.Error:
	pass

stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
if callable(stdout_reconfigure):
	try:
		cast(Any, stdout_reconfigure)(encoding="utf-8", errors="replace")
	except Exception:
		pass


images = load_images_from_directory(input_directory)
for img in images:
	crop_image(img, crop_rectangle)
	save_cropped_image(img, output_directory)

print(f"Processed {len(images)} images.")
