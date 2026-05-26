#* 文档（PDF）自动截图工具，适用于没有 DRM 保护的 PDF 文档，或已解密的 PDF 文档。
# 原理：通过发送 `PgDn` 键翻页，配合鼠标点击激活窗口，自动截图并保存到指定文件夹。
# 依赖库：mss、pynput、Pillow

from my_utils import *
import threading

import mss # pip install mss
import mss.tools

from pynput import keyboard # pip install pynput
from pynput import mouse

from PIL import Image # pip install Pillow


print(f"{FLYellow}======= Automatic Screen Capturing Tool for Document ======={CRst}")
if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
AUTOMATIC SCREEN CAPTURING TOOL FOR DOCUMENT
============================================

Usage:
  python {script_name}                进入交互
  python {script_name} --help         显示此帮助


功能：
  可用于对有 DRM 保护（或加密 U 盘）中的 PDF 文档进行自动截图。
  原理：通过发送 `PgDn` 键翻页，配合鼠标点击激活窗口，自动截图并保存到指定文件夹。
  依赖库： mss、pynput、Pillow
""")
    sys.exit(0)


class ImageCompressMode(enum.Enum):
    none = 0
    grayscale = 1
    binary = 2

class Region:
    left: int = 15
    top: int = 15
    width: int = 300
    height: int = 300
    
    center_x: int = 250
    center_y: int = 250

class Config:
    # monitor_index: int = 1 # monitors[0] is the virtual screen, monitors[1] is the primary monitor, monitors[2] is the secondary monitor, etc.
    capture_interval_s: float = 0.5 # seconds
    capture_count: int = 10
    output_dir: str = "./output"
    sleep_time_ms: int = 50 # 鼠标激活窗口后按 PgDn 键的间隔时间，单位毫秒
    compression_mode: ImageCompressMode = ImageCompressMode.none
    compression_level: int = 9 # PIL compression level, 0-9, where 0 is no compression and 9 is maximum compression


mouse_controller = mouse.Controller()
keyboard_controller = keyboard.Controller()
stop_event = threading.Event()


def start_stop_hotkey_listener(stop_key: keyboard.Key = keyboard.Key.f9) -> keyboard.Listener:
    """Listen for a stop hotkey in the background and set a shared stop flag."""
    listener: typing.Optional[keyboard.Listener] = None

    def on_press(key: typing.Any) -> None:
        nonlocal listener
        if key == stop_key:
            print(f"\n{FLRed}[STOP] F9 detected, stopping capture...{CRst}")
            stop_event.set()
            if listener is not None:
                listener.stop()

    listener = keyboard.Listener(on_press=on_press, suppress=False)
    listener.start()
    return listener


def interrupted_sleep(total_s: float, step_s: float = 0.05) -> bool:
    """Sleep in small chunks so F9 can interrupt long waits quickly."""
    end_time = time.time() + max(0.0, total_s)
    while time.time() < end_time:
        if stop_event.is_set():
            return False
        time.sleep(min(step_s, max(0.0, end_time - time.time())))
    return True

# 获取当前鼠标位置
def get_cursor_pos() -> typing.Optional[tuple[int, int]]:
    try:
        x, y = mouse_controller.position
        return int(x), int(y)
    except Exception:
        return None

# DPI 适应（Windows）
Utils.enable_dpi_awareness()

# 通过热键记录鼠标位置，避免真实点击触发下层窗口。
def get_click_pos(capture_key: keyboard.Key = keyboard.Key.f8):
    result: dict[str, typing.Optional[tuple[int, int]]] = {"pos": None}
    listener: typing.Optional[keyboard.Listener] = None

    def on_press(key: typing.Any) -> None:
        nonlocal listener
        if key == capture_key:
            result["pos"] = get_cursor_pos()
            if listener is not None:
                listener.stop()
            return
        if key == keyboard.Key.esc and listener is not None:
            listener.stop()

    with keyboard.Listener(on_press=on_press, suppress=True) as listener:
        listener.join()

    return result["pos"]




# print(f"{FLCyan}Select monitor index (default: {Config.monitor_index}, 0 is virtual screen (stitched all screens), 1 is the primary monitor, 2 is the secondary monitor, etc...): {CRst}", end="")
# Config.monitor_index = int(input() or Config.monitor_index)
print(f"{FLCyan}Enter capturing interval in seconds (default: {FLYellow}{Config.capture_interval_s}{FLCyan}): {CRst}", end="")
Config.capture_interval_s = float(input() or Config.capture_interval_s)
print(f"{FLCyan}Enter capturing count (default: {FLYellow}{Config.capture_count}{FLCyan}): {CRst}", end="")
Config.capture_count = int(input() or Config.capture_count)
print(f"{FLCyan}Enter Output Directory (default: {FLYellow}{Config.output_dir}{FLCyan}): {CRst}", end="")
Config.output_dir = input() or Config.output_dir
if not os.path.isdir(Config.output_dir):
    Config.output_dir = os.path.abspath(Config.output_dir)
    print(f"{FLRed}Output directory does not exist: {FLYellow}{Config.output_dir}{FLCyan}, create folder?{CRst}")
    confirm = input(f"{FLYellow}Confirm to create folder? (y/n, default: y): {CRst}") or "y"
    if confirm.lower() == "y":
        try:
            os.makedirs(Config.output_dir, exist_ok=True)
            print(f"{FLGreen}Folder created: {FLYellow}{Config.output_dir}{CRst}")
        except Exception as e:
            print(f"{FLRed}Failed to create folder: {e}{CRst}")
            exit(1)
    else:
        print(f"{FLRed}Output directory is required. Exiting.{CRst}")
        exit(1)
else:
    Config.output_dir = os.path.abspath(Config.output_dir)

# 鼠标点击位置，左键、右键、中键都可以，分别对应不同的功能：
print(f"{FLGreen}Move mouse to top-left corner, then press F8 to capture (Esc to cancel)...{CRst}")
click_pos = get_click_pos() # 左上角
if click_pos is not None:
    Region.left, Region.top = click_pos
    print(f"{FLBlue}  Selected region top-left corner: {click_pos}{CRst}")
else:
    raise Exception("No click detected. Exiting.")
print(f"{FLGreen}Move mouse to bottom-right corner, then press F8 to capture (Esc to cancel)...{CRst}")
click_pos = get_click_pos() # 右下角
if click_pos is not None:
    Region.width = click_pos[0] - Region.left
    Region.height = click_pos[1] - Region.top
    print(f"{FLBlue}  Selected region bottom-right corner: {click_pos}{CRst}")
else:
    raise Exception("No click detected. Exiting.")
print(f"{FLGreen}Move mouse to center point, then press F8 to capture (Esc to cancel)...{CRst}")
click_pos = get_click_pos() # 键盘发送 PageDn 键时，激活窗口时点击的位置
if click_pos is not None:
    Region.center_x, Region.center_y = click_pos
    print(f"{FLBlue}  Selected region center point: {click_pos}{CRst}")

# 图像压缩模式选择：
print(f"{FLCyan}Select image compression mode (default: {ImageCompressMode.none.name}): {CRst}")
for mode in ImageCompressMode:
    print(f"{FLMagenta}  {mode.value}. {mode.name}{CRst}")
mode_input = input() or str(ImageCompressMode.none.value)
try:
    image_compress_mode = ImageCompressMode(int(mode_input))
except ValueError:
    print(f"{FLRed}Invalid input for image compression mode. Using default: {ImageCompressMode.none.name}{CRst}")
    image_compress_mode = ImageCompressMode.none
Config.compression_mode = image_compress_mode

print(f"{FLCyan}Enter image compression level (0-9, default: {Config.compression_level}): {CRst}", end="")
compression_level_input = input() or str(Config.compression_level)
try:
    compression_level = int(compression_level_input)
    if 0 <= compression_level <= 9:
        Config.compression_level = compression_level
    else:
        raise ValueError
except ValueError:
    print(f"{FLRed}Invalid input for compression level. Using default: {Config.compression_level}{CRst}")

print(f"{FLYellow}WARNING: Please set the DPI scaling of the target monitor to 100% (96 DPI) to ensure correct capturing region. Current DPI scaling may cause incorrect capture results.{CRst}")

print(f"{FLCyan}Output Path: {CRst}{FLYellow}{Config.output_dir}{CRst}, "
        # f"{FLCyan}monitor index: {CRst}{FLYellow}{Config.monitor_index}{CRst}, "
        f"{FLCyan}capturing interval: {CRst}{FLYellow}{Config.capture_interval_s}s{CRst}, "
        f"{FLCyan}capturing count: {CRst}{FLYellow}{Config.capture_count}{CRst}")
print(f"{FLCyan}Final capturing region: left={CRst}{FLYellow}{Region.left}{CRst}, {FLCyan}top={CRst}{FLYellow}{Region.top}{CRst}, "
        f"{FLCyan}width={CRst}{FLYellow}{Region.width}{CRst}, {FLCyan}height={CRst}{FLYellow}{Region.height}{CRst}, "
        f"{FLCyan}center={CRst}{FLYellow}({Region.center_x}, {Region.center_y}){CRst}")
print(f"{FLYellow}Confirm to start capturing? (y/n, default: y): {CRst}", end="")
confirm = input() or "y"
if confirm.lower() != "y":
    print(f"{FLRed}Capture cancelled. Exiting.{CRst}")
    exit()




def image_color_processing(image: Image.Image, mode: ImageCompressMode) -> Image.Image:
    if mode == ImageCompressMode.grayscale:
        image = image.convert("L")
    elif mode == ImageCompressMode.binary:
        # Use a LUT to avoid callable typing ambiguity in PIL.Image.point.
        threshold_lut = [0 if i < 128 else 255 for i in range(256)]
        image = image.convert("L").point(threshold_lut, mode="1")
    else:
        image = image.copy()
    return image

def click_and_send_pagedown(x, y, sleep_time_s=0.05):
    if stop_event.is_set():
        return

    mouse_controller.position = (x, y)
    mouse_controller.click(mouse.Button.left, 1) # 点击窗口，激活窗口
    
    if not interrupted_sleep(sleep_time_s): # 确保鼠标位置更新后再发送按键
        return

    keyboard_controller.press(keyboard.Key.page_down)
    # time.sleep(sleep_time_s)
    keyboard_controller.release(keyboard.Key.page_down)
    interrupted_sleep(sleep_time_s)


print(f"{FLCyan}Hotkey enabled: press {FLYellow}F9{FLCyan} at any time to stop.{CRst}")
stop_listener = start_stop_hotkey_listener()


captured_count = 0
try:
    for i in range(Config.capture_count):
    # for i in range(1):
        # start_time = time.time()
        if stop_event.is_set():
            break

        with mss.mss() as sct:
            # monitor = sct.monitors[Config.monitor_index]
            region = {
                "left": Region.left,
                "top": Region.top,
                "width": Region.width,
                "height": Region.height,
            }
            img = sct.grab(region)
            path = os.path.join(Config.output_dir, f"screenshot_{i+1}.png")
            img_pil = Image.frombytes("RGB", img.size, img.rgb)
            img_processed = image_color_processing(img_pil, Config.compression_mode)
            img_processed.save(path, optimize=True, compress_level=Config.compression_level)

        captured_count += 1
        print(f"  idx: {FLYellow}{i+1}{CRst}/{Config.capture_count}, saved to: {FLGreen}{path}{CRst}")

        if i < (Config.capture_count - 1) and not stop_event.is_set():
            if not interrupted_sleep(Config.capture_interval_s):
                break
            click_and_send_pagedown(Region.center_x, Region.center_y, Config.sleep_time_ms / 1000)
finally:
    stop_listener.stop()
    
    



if stop_event.is_set():
    print(f"{FLYellow}Capture stopped by user. Saved {captured_count} images to: {Config.output_dir}{CRst}")
else:
    print(f"{FLGreen}Capture completed. Total {FLYellow}{captured_count}{FLGreen} images saved to: {FLYellow}{Config.output_dir}{CRst}")
