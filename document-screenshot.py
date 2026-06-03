#* 文档（PDF）自动截图工具，适用于没有 DRM 保护的 PDF 文档，或已解密的 PDF 文档。
# 原理：通过发送 `PgDn` 键翻页，配合鼠标点击激活窗口，自动截图并保存到指定文件夹。
# 依赖库：mss、pynput、Pillow

from utils import *
import threading
import platform

import mss # pip install mss
import mss.tools

from pynput import keyboard # pip install pynput
from pynput import mouse

from PIL import Image # pip install Pillow


def safe_input(prompt: str = "") -> str:
    """Read a line from stdin, flushing any stale pynput-injected events first."""
    # On macOS/Linux, pynput may leave terminal in a state where input() behaves oddly.
    # Use sys.__stdin__ directly as a fallback.
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        return input()
    except (EOFError, OSError):
        # Fallback: read directly from the real stdin fd
        real_stdin = getattr(sys, "__stdin__", sys.stdin)
        if real_stdin is not None:
            return real_stdin.readline().rstrip("\n")
        return ""


def check_macos_permissions(timeout_s: float = 60.0) -> bool:
    """Check both Accessibility and Screen Recording permissions on macOS.
    Accessibility is needed for mouse/keyboard simulation (pynput).
    Screen Recording is needed for screenshot capture (mss).
    """
    if platform.system() != "Darwin":
        return True

    accessibility_ok = _check_accessibility_permission()
    screen_recording_ok = _check_screen_recording_permission()

    if accessibility_ok and screen_recording_ok:
        return True

    missing = []
    if not accessibility_ok:
        missing.append("Accessibility (mouse/keyboard control)")
    if not screen_recording_ok:
        missing.append("Screen Recording (screenshot capture)")

    print(f"{FLYellow}============================================{CRst}")
    print(f"{FLYellow}⚠  Missing required permissions:{CRst}")
    for m in missing:
        print(f"{FLYellow}   - {m}{CRst}")
    print(f"{FLYellow}   Please grant them to your terminal in:{CRst}")
    print(f"{FLCyan}   System Settings → Privacy & Security{CRst}")
    print(f"{FLYellow}   Then re-launch this script.{CRst}")
    print(f"{FLYellow}============================================{CRst}")

    # Open Privacy & Security settings
    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security"],
        capture_output=True
    )

    print(f"{FLCyan}Waiting for permissions... (timeout: {timeout_s}s){CRst}")
    start = time.time()
    while time.time() - start < timeout_s:
        acc_ok = _check_accessibility_permission()
        scr_ok = _check_screen_recording_permission()
        if acc_ok and scr_ok:
            print(f"{FLGreen}✓ All permissions granted.{CRst}")
            return True
        time.sleep(1.0)

    print(f"{FLRed}✗ Permissions not granted within timeout. Exiting.{CRst}")
    return False


def _check_accessibility_permission() -> bool:
    """Check if Accessibility permission is granted via osascript."""
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to return UI elements enabled'],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "true"
    except Exception:
        return False


def _check_screen_recording_permission() -> bool:
    """Check if Screen Recording permission is granted.
    We test by attempting an actual screenshot capture via mss — if the
    captured image contains only the desktop wallpaper and menu bar
    (no window content), Screen Recording permission is missing.
    We detect this by checking if the screenshot is effectively empty
    of application windows: take a small test capture and verify it
    contains meaningful content beyond just the menu bar.
    """
    try:
        import mss as _mss
        with _mss.MSS() as sct:
            # Capture a small region in the center of the screen where windows
            # normally appear (not the menu bar at top). If we can capture at
            # all and get non-black pixels, screen recording is likely working.
            monitor = sct.monitors[1]
            test_w = min(400, monitor["width"])
            test_h = min(400, monitor["height"])
            test_left = (monitor["width"] - test_w) // 2
            # Skip top 30px (menu bar) to avoid false positives
            test_top = max(60, (monitor["height"] - test_h) // 2)
            region = {
                "left": test_left,
                "top": test_top,
                "width": test_w,
                "height": test_h,
            }
            img = sct.grab(region)
            # If we got here without an error, permission exists.
            # But also verify: if the entire capture is a single solid color
            # (desktop wallpaper as one flat color), it might be a false positive.
            # We check for variance: if >90% of pixels are the same color,
            # it's probably just desktop with no windows.
            raw = img.rgb
            first_pixel = raw[:3]
            same_count = 0
            total_pixels = len(raw) // 3
            # Sample every 100th pixel for performance
            sample_step = max(1, total_pixels // 500)
            sample_count = 0
            for i in range(0, len(raw), 3 * sample_step):
                if raw[i:i+3] == first_pixel:
                    same_count += 1
                sample_count += 1
            uniformity = same_count / max(sample_count, 1)
            # If >80% uniform, likely no window content visible
            return uniformity < 0.80
    except Exception:
        return False


print(f"{FLYellow}======= Automatic Screen Capturing Tool for Document ======={CRst}")
if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
AUTOMATIC SCREEN CAPTURING TOOL FOR DOCUMENT
============================================

Usage:
  python {script_name}                enter interactive mode
  python {script_name} --help         show this help

{FLYellow}Description:{CRst}
  Auto-capture screenshots of DRM-protected or encrypted-USB PDF documents.
  Works by sending PgDn key to flip pages, clicking to activate the window,
  and auto-saving screenshots to a folder.
  Dependencies: mss, pynput, Pillow
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
    sleep_time_ms: int = 200 # 鼠标激活窗口后按 PgDn 键的间隔时间，单位毫秒
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

# macOS: check both Accessibility and Screen Recording permissions
if not check_macos_permissions():
    sys.exit(1)

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
Config.capture_interval_s = float(safe_input() or Config.capture_interval_s)
print(f"{FLCyan}Enter capturing count (default: {FLYellow}{Config.capture_count}{FLCyan}): {CRst}", end="")
Config.capture_count = int(safe_input() or Config.capture_count)
print(f"{FLCyan}Enter Output Directory (default: {FLYellow}{Config.output_dir}{FLCyan}): {CRst}", end="")
Config.output_dir = safe_input() or Config.output_dir
# Expand ~ to home directory on Unix-like systems
Config.output_dir = os.path.expanduser(Config.output_dir)
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
print(f"{FLCyan}Select image compression mode (default: {FLYellow}{ImageCompressMode.none.name}{FLCyan}): {CRst}")
for mode in ImageCompressMode:
    print(f"{FLMagenta}  {mode.value}. {mode.name}{CRst}")
mode_input = safe_input() or str(ImageCompressMode.none.value)
try:
    mode_value = int(mode_input.strip())
    image_compress_mode = ImageCompressMode(mode_value)
except (ValueError, KeyError):
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

    # Move mouse to target and click to activate the window
    mouse_controller.position = (x, y)
    if not interrupted_sleep(0.05):
        return
    mouse_controller.click(mouse.Button.left, 1) # 点击窗口，激活窗口
    
    # On macOS, the window activation may take a moment;
    # give the system time to bring the window to front.
    if not interrupted_sleep(max(sleep_time_s, 0.15)):
        return

    keyboard_controller.press(keyboard.Key.page_down)
    keyboard_controller.release(keyboard.Key.page_down)
    interrupted_sleep(sleep_time_s)


def activate_window_before_first_capture(x, y) -> bool:
    """Click the target window to bring it to front before the first screenshot.
    Returns True if the activation likely succeeded."""
    if stop_event.is_set():
        return False
    mouse_controller.position = (x, y)
    interrupted_sleep(0.05)
    mouse_controller.click(mouse.Button.left, 1)
    # Wait longer for first activation — macOS may animate window transitions
    return interrupted_sleep(0.3)


print(f"{FLCyan}Hotkey enabled: press {FLYellow}F9{FLCyan} at any time to stop.{CRst}")
stop_listener = start_stop_hotkey_listener()

# Activate the target window before first capture
print(f"{FLCyan}Activating target window...{CRst}")
activate_window_before_first_capture(Region.center_x, Region.center_y)

captured_count = 0
try:
    for i in range(Config.capture_count):
    # for i in range(1):
        # start_time = time.time()
        if stop_event.is_set():
            break

        with mss.MSS() as sct:
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
