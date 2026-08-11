#!/usr/bin/env python3
#* 文档（PDF）自动截图工具，适用于没有 DRM 保护的 PDF 文档，或已解密的 PDF 文档。
# 原理：通过发送 `PgDn` 键翻页，配合鼠标点击激活窗口，自动截图并保存到指定文件夹。
# 依赖库：mss、pynput、Pillow

import os
import sys
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

import mss # pip install mss
import mss.tools

from pynput import keyboard # pip install pynput
from pynput import mouse

from PIL import Image # pip install Pillow


def main() -> int:
    Console.print_banner("Automatic Screen Capturing Tool for Document")
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

    {FLYellow}Requirements:{CRst}
      macOS only (uses osascript for window activation).
      Python: {FGray}pip install mss pynput Pillow{CRst}
      Startup waits for Accessibility, Screen Recording, and the macOS
      direct-screen-capture confirmation before enabling input control.
    """)
        return 0


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
    System.enable_dpi_awareness()

    # macOS: check both Accessibility and Screen Recording permissions
    if not System.ensure_macos_permissions(
        accessibility=True,
        screen_recording=True,
    ):
        return 1

    def probe_screen_capture() -> None:
        """Perform a tiny capture without saving it to trigger macOS consent."""
        with mss.MSS() as screenshotter:
            monitors = screenshotter.monitors
            if len(monitors) < 2:
                raise RuntimeError("No physical display was detected.")
            display = monitors[1]
            screenshotter.grab({
                "left": display["left"],
                "top": display["top"],
                "width": 1,
                "height": 1,
            })

    if not System.wait_for_macos_screen_capture_approval(probe_screen_capture):
        return 1

    # Do not initialize input-control objects until every permission dialog is
    # complete, so no click or key event can race with a macOS consent prompt.
    mouse_controller = mouse.Controller()
    keyboard_controller = keyboard.Controller()

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




    Config.capture_interval_s = float(Input.input_number(
        "Enter capturing interval in seconds",
        default=Config.capture_interval_s,
        min_value=0,
        allow_float=True,
        allow_negative=False,
    ))
    Config.capture_count = int(Input.input_number(
        "Enter capturing count",
        default=Config.capture_count,
        min_value=1,
        allow_float=False,
        allow_negative=False,
    ))
    Config.output_dir = Input.resolve_output_path(
        os.path.abspath(Config.output_dir),
        prompt="Enter Output Directory",
        path_type="dir",
    )

    # 鼠标点击位置，左键、右键、中键都可以，分别对应不同的功能：
    print(f"{FLGreen}Move mouse to top-left corner, then press {FLYellow}F8{FLGreen} to set the coord (Esc to cancel)...{CRst}")
    click_pos = get_click_pos() # 左上角
    if click_pos is not None:
        Region.left, Region.top = click_pos
        print(f"{FLBlue}  Selected region top-left corner: {click_pos}{CRst}")
    else:
        raise Exception("No click detected. Exiting.")
    print(f"{FLGreen}Move mouse to bottom-right corner, then press {FLYellow}F8{FLGreen} to set the coord (Esc to cancel)...{CRst}")
    click_pos = get_click_pos() # 右下角
    if click_pos is not None:
        Region.width = click_pos[0] - Region.left
        Region.height = click_pos[1] - Region.top
        print(f"{FLBlue}  Selected region bottom-right corner: {click_pos}{CRst}")
    else:
        raise Exception("No click detected. Exiting.")
    print(f"{FLGreen}Move mouse to center point, then press {FLYellow}F8{FLGreen} to set the coord (Esc to cancel)...{CRst}")
    click_pos = get_click_pos() # 键盘发送 PageDn 键时，激活窗口时点击的位置
    if click_pos is not None:
        Region.center_x, Region.center_y = click_pos
        print(f"{FLBlue}  Selected region center point: {click_pos}{CRst}")

    Input.prompt(
        f"{FLYellow}Return focus to this terminal, then press Enter to "
        f"continue to compression settings...{CRst} "
    )

    # 图像压缩模式选择：
    selected_mode = Menu.select(
        Menu.from_enum(ImageCompressMode, desc_color=FLMagenta),
        prompt="Select image compression mode",
        required=True,
        default_key=str(ImageCompressMode.none.value),
    )
    if not isinstance(selected_mode, ImageCompressMode):
        raise RuntimeError("Compression mode selection returned an invalid value.")
    Config.compression_mode = selected_mode

    Config.compression_level = int(Input.input_number(
        "Enter image compression level",
        default=Config.compression_level,
        min_value=0,
        max_value=9,
        allow_float=False,
        allow_negative=False,
    ))

    print(f"{FLYellow}WARNING: Please set the DPI scaling of the target monitor to 100% (96 DPI) to ensure correct capturing region. Current DPI scaling may cause incorrect capture results.{CRst}")

    print(f"{FLCyan}Output Path: {CRst}{FLYellow}{Config.output_dir}{CRst}, "
            # f"{FLCyan}monitor index: {CRst}{FLYellow}{Config.monitor_index}{CRst}, "
            f"{FLCyan}capturing interval: {CRst}{FLYellow}{Config.capture_interval_s}s{CRst}, "
            f"{FLCyan}capturing count: {CRst}{FLYellow}{Config.capture_count}{CRst}")
    print(f"{FLCyan}Final capturing region: left={CRst}{FLYellow}{Region.left}{CRst}, {FLCyan}top={CRst}{FLYellow}{Region.top}{CRst}, "
            f"{FLCyan}width={CRst}{FLYellow}{Region.width}{CRst}, {FLCyan}height={CRst}{FLYellow}{Region.height}{CRst}, "
            f"{FLCyan}center={CRst}{FLYellow}({Region.center_x}, {Region.center_y}){CRst}")
    confirmed = Menu.select(
        [
            MenuOption(["Y"], "Start capturing", True, FLGreen),
            MenuOption(["N"], "Cancel", False, FLRed),
        ],
        prompt="Confirm to start capturing?",
        required=True,
        default_key="Y",
        inline=True,
        separator=False,
    )
    if not confirmed:
        print(f"{FLRed}Capture cancelled. Exiting.{CRst}")
        return 0




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
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
