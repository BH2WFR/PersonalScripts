#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import *

import cv2
import locale
from pathlib import Path
import numpy as np
import numpy.typing as npt
from dataclasses import dataclass
from typing import Any, cast, Optional


ImageArray = npt.NDArray[Any]

@dataclass
class Image:
	original_image: Optional[ImageArray] = None
	cropped_image: Optional[ImageArray] = None
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


def main() -> int:
    Utils.print_banner("BATCH IMAGE CROPPING TOOL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
BATCH IMAGE CROPPING TOOL
=========================

Usage:
  python {script_name} <dir1> <dir2> ...    specify directory paths, skip interaction
  python {script_name}                      no arguments, interactive mode
  python {script_name} --help               show this help

{FLYellow}Description:{CRst}
  Batch image cropping tool. Based on OpenCV (cv2).
  Interactively select input/output directories and crop region,
  then batch-crop all images.

{FLYellow}Requirements:{CRst}
  Python: {FGray}pip install opencv-python numpy{CRst}
""")
        return 0

    input_directory = "E:/!重建问题测试/HDR_金属件/HDR"
    output_directory = "E:/!重建问题测试/HDR_金属件/HDR_cropped"
    crop_rectangle: Region = Region(564, 960, 1533, 1743)

    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        input_directory = sys.argv[1]
    else:
        input_directory = input(f"Enter input directory path (default: {input_directory}): ") or input_directory
    if not input_directory or not os.path.exists(input_directory):
        print(f"{FLRed}Invalid input directory path. EXIT...{CRst}\n")
        return 1

    output_directory = input(f"Enter output directory path (default: {output_directory}): ") or output_directory
    if not output_directory:
        print(f"{FLRed}Invalid output directory path. EXIT...{CRst}\n")
        return 1
    if not os.path.exists(output_directory):
        print(f"{FLYellow}Output path does not exist, create it? (y/n, default: y): {CRst}")
        confirm = input().strip().lower() or "y"
        if confirm != "y":
            print(f"{FLRed}Output directory does not exist. EXIT...{CRst}\n")
            return 1
        else:
            try:
                os.makedirs(output_directory, exist_ok=True)
                print(f"{FLGreen}Output directory created successfully. ({output_directory}){CRst}\n")
            except Exception as e:
                print(f"{FLRed}Failed to create output directory: {e}. EXIT...{CRst}\n")
                return 1

    crop_x1 = Input.input_number(
        f"Enter crop rectangle {FLYellow}x1{CRst}",
        default=crop_rectangle.x1,
        allow_float=False,
    )
    crop_y1 = Input.input_number(
        f"Enter crop rectangle {FLYellow}y1{CRst}",
        default=crop_rectangle.y1,
        allow_float=False,
    )
    crop_x2 = Input.input_number(
        f"Enter crop rectangle {FLYellow}x2{CRst}",
        default=crop_rectangle.x2,
        allow_float=False,
    )
    crop_y2 = Input.input_number(
        f"Enter crop rectangle {FLYellow}y2{CRst}",
        default=crop_rectangle.y2,
        allow_float=False,
    )
    crop_rectangle = Region(crop_x1, crop_y1, crop_x2, crop_y2)

    # main execution
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
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
