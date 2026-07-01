#!/usr/bin/env python3
"""Structured-light projector pattern generator."""

import enum
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import *  # noqa: E402

try:
    import cv2  # noqa: E402
    import numpy as np  # noqa: E402
except ImportError as e:
    print(f"{FLRed}ERROR: Missing dependency: {e.name}{CRst}")
    print(f"  Install with: {FGray}pip install opencv-python numpy{CRst}")
    sys.exit(1)


class PatternType(enum.Enum):
    SINUSOIDAL = "1"
    SPECKLE = "2"


class CoordinateSystem(enum.Enum):
    CARTESIAN = "1"
    DIAMOND = "2"


class FrequencyUnit(enum.Enum):
    TOTAL_CYCLES = "1"
    PERIOD_PIXELS = "2"


class StripeDirection(enum.Enum):
    HORIZONTAL_STRIPES = "1"
    VERTICAL_STRIPES = "2"
    CUSTOM_ANGLE = "3"


@dataclass(frozen=True)
class ProjectorSpec:
    width: int = 1920
    height: int = 1080
    coordinate_system: CoordinateSystem = CoordinateSystem.CARTESIAN


@dataclass(frozen=True)
class SinusoidalConfig:
    frequency_unit: FrequencyUnit
    frequency: float
    phase_rad: float
    stripe_direction: StripeDirection
    stripe_angle_deg: float


@dataclass(frozen=True)
class SinusoidalInputDefaults:
    frequency: float
    phase_rad: float = 0.0
    stripe_direction: StripeDirection = StripeDirection.VERTICAL_STRIPES
    stripe_angle_deg: float = 0.0


@dataclass(frozen=True)
class PatternRequest:
    pattern_type: PatternType
    projector: ProjectorSpec
    config: SinusoidalConfig
    output_path: str


@dataclass(frozen=True)
class DetachedPreview:
    process: subprocess.Popen[bytes]
    temp_path: str


class PatternStrategy(Protocol):
    def generate(self, request: PatternRequest) -> "np.ndarray":
        ...


class SinusoidalPatternStrategy:
    """Generate 8-bit grayscale sinusoidal stripe patterns."""

    def generate(self, request: PatternRequest) -> "np.ndarray":
        cfg = request.config
        width = request.projector.width
        height = request.projector.height

        if request.projector.coordinate_system is not CoordinateSystem.CARTESIAN:
            raise NotImplementedError("Only Cartesian coordinate system is implemented now.")

        x = np.arange(width, dtype=np.float64) + 0.5
        y = np.arange(height, dtype=np.float64) + 0.5
        xx, yy = np.meshgrid(x, y)

        nx, ny = self._distribution_vector(cfg)
        coord = xx * nx + yy * ny
        coord -= self._min_projected_corner(width, height, nx, ny)

        if cfg.frequency_unit is FrequencyUnit.TOTAL_CYCLES:
            extent = self._projected_extent(width, height, nx, ny)
            if extent <= 0:
                raise ValueError("Invalid projector size or stripe direction.")
            cycles = cfg.frequency
            phase = 2.0 * math.pi * cycles * coord / extent + cfg.phase_rad
        else:
            period_px = cfg.frequency
            phase = 2.0 * math.pi * coord / period_px + cfg.phase_rad

        image = (0.5 + 0.5 * np.sin(phase)) * 255.0
        return np.clip(np.rint(image), 0, 255).astype(np.uint8)

    @staticmethod
    def _distribution_vector(cfg: SinusoidalConfig) -> tuple[float, float]:
        if cfg.stripe_direction is StripeDirection.HORIZONTAL_STRIPES:
            return 0.0, 1.0
        if cfg.stripe_direction is StripeDirection.VERTICAL_STRIPES:
            return 1.0, 0.0

        theta = math.radians(cfg.stripe_angle_deg)
        # Angle is measured from vertical stripes clockwise; this vector is the
        # perpendicular direction along which intensity changes.
        # In image coordinates (y-down), cos(θ), −sin(θ) rotates clockwise from
        # the x-axis.
        return math.cos(theta), -math.sin(theta)

    @staticmethod
    def _min_projected_corner(width: int, height: int, nx: float, ny: float) -> float:
        corners = (
            0.0,
            width * nx,
            height * ny,
            width * nx + height * ny,
        )
        return min(corners)

    @staticmethod
    def _projected_extent(width: int, height: int, nx: float, ny: float) -> float:
        corners = (
            0.0,
            width * nx,
            height * ny,
            width * nx + height * ny,
        )
        return max(corners) - min(corners)


class PatternGenerator:
    def __init__(self) -> None:
        self._strategies: dict[PatternType, PatternStrategy] = {
            PatternType.SINUSOIDAL: SinusoidalPatternStrategy(),
        }

    def generate(self, request: PatternRequest) -> "np.ndarray":
        strategy = self._strategies.get(request.pattern_type)
        if strategy is None:
            raise NotImplementedError(f"Pattern type is not implemented: {request.pattern_type.name}")
        return strategy.generate(request)


def _imwrite_unicode(path: str, image: "np.ndarray") -> bool:
    suffix = Path(path).suffix or ".png"
    params: list[int] = []
    if suffix.lower() == ".png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 9]

    ok, buffer = cv2.imencode(suffix, image, params)
    if not ok:
        return False
    buffer.tofile(path)
    return True


def _fit_preview_image(image: "np.ndarray", max_width: int = 1280, max_height: int = 720) -> "np.ndarray":
    height, width = image.shape[:2]
    scale = min(max_width / width, max_height / height, 1.0)
    if scale >= 1.0:
        return image

    preview_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return cv2.resize(image, preview_size, interpolation=cv2.INTER_AREA)


_PREVIEW_CHILD_CODE = r"""
import os
import sys

import cv2
import numpy as np

path = sys.argv[1]
title = sys.argv[2]

try:
    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError("failed to read preview image")

    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.imshow(title, image)
    while True:
        key = cv2.waitKey(50)
        try:
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
        except cv2.error:
            break
        if key in (27, ord("q"), ord("Q")):
            break
finally:
    try:
        cv2.destroyAllWindows()
    except cv2.error:
        pass
    try:
        os.remove(path)
    except OSError:
        pass
"""


def _launch_detached_preview(image: "np.ndarray", title: str = "Pattern Preview") -> DetachedPreview | None:
    if Utils.is_headless():
        return None

    temp_path = ""
    try:
        preview = _fit_preview_image(image)
        with tempfile.NamedTemporaryFile(prefix="pattern_preview_", suffix=".png", delete=False) as temp_file:
            temp_path = temp_file.name
        if not _imwrite_unicode(temp_path, preview):
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return None

        if sys.platform == "win32":
            process = subprocess.Popen(
                [sys.executable, "-c", _PREVIEW_CHILD_CODE, temp_path, title],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            )
        else:
            process = subprocess.Popen(
                [sys.executable, "-c", _PREVIEW_CHILD_CODE, temp_path, title],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return DetachedPreview(process=process, temp_path=temp_path)
    except Exception as e:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        print(f"{FLYellow}Preview window unavailable: {e}{CRst}")
        return None


def _close_preview_process(preview: DetachedPreview | None) -> None:
    if preview is None:
        return
    process = preview.process
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=1)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
    try:
        os.remove(preview.temp_path)
    except OSError:
        pass


def _close_preview_window(title: str = "Pattern Preview") -> None:
    try:
        cv2.destroyWindow(title)
        cv2.waitKey(1)
    except cv2.error:
        pass


def _confirm_save_after_preview(image: "np.ndarray", preview_enabled: bool) -> bool:
    preview_process: DetachedPreview | None = None
    if preview_enabled:
        preview_process = _launch_detached_preview(image)
        if preview_process is not None:
            print(f"{FLCyan}Preview window opened in a detached process. Close it anytime; terminal input remains active.{CRst}")
        else:
            print(f"{FGray}Preview window was not opened; confirm from terminal instead.{CRst}")
    else:
        print(f"{FGray}Preview skipped; confirm from terminal.{CRst}")

    try:
        choice = Menu.select(
            [
                MenuOption(["Y"], "Save", True, FLGreen),
                MenuOption(["N"], "Discard", False, FLRed),
            ],
            prompt="Save this generated image?",
            required=True,
            default_key="Y",
            inline=True,
            separator_width=30,
        )
        return bool(choice)
    finally:
        _close_preview_process(preview_process)


def _select_pattern_type() -> PatternType:
    while True:
        choice = Menu.select(
            [
                MenuOption(["1", "S"], "Sinusoidal Stripes", PatternType.SINUSOIDAL),
                MenuOption(["2"], f"Speckle {FGray}(not implemented){CRst}", PatternType.SPECKLE),
            ],
            prompt="Select pattern type",
            required=True,
            default_key="1",
        )
        if choice is PatternType.SINUSOIDAL:
            return choice
        print(f"{FLRed}Speckle pattern is not yet implemented. Please choose sinusoidal stripes.{CRst}\n")


def _select_coordinate_system() -> CoordinateSystem:
    while True:
        choice = Menu.select(
            [
                MenuOption(["1", "C"], "Cartesian", CoordinateSystem.CARTESIAN),
                MenuOption(["2", "D"], f"Diamond {FGray}(not implemented){CRst}", CoordinateSystem.DIAMOND),
            ],
            prompt="Select projector coordinate system",
            required=True,
            default_key="1",
        )
        if choice is CoordinateSystem.CARTESIAN:
            return choice
        print(f"{FLRed}Diamond coordinate system is not yet implemented. Please choose Cartesian.{CRst}\n")


def _input_projector_spec(coordinate_system: CoordinateSystem) -> ProjectorSpec:
    width = Input.input_number(
        "Enter projector horizontal resolution",
        default=1920,
        min_value=1,
        allow_float=False,
        allow_negative=False,
    )
    height = Input.input_number(
        "Enter projector vertical resolution",
        default=1080,
        min_value=1,
        allow_float=False,
        allow_negative=False,
    )
    return ProjectorSpec(width=int(width), height=int(height), coordinate_system=coordinate_system)


def _select_frequency_unit() -> FrequencyUnit:
    return cast(FrequencyUnit, Menu.select(
        [
            MenuOption(["1", "C"], "Total cycles across projector", FrequencyUnit.TOTAL_CYCLES),
            MenuOption(["2", "P"], "Period in pixels", FrequencyUnit.PERIOD_PIXELS),
        ],
        prompt="Select frequency unit",
        required=True,
        default_key="1",
    ))


def _select_preview_enabled() -> bool:
    choice = Menu.select(
        [
            MenuOption(["Y"], "View preview before saving", True, FLGreen),
            MenuOption(["N"], "Skip preview", False, FLRed),
        ],
        prompt="View generated image before saving?",
        required=True,
        default_key="Y",
        inline=True,
        separator_width=44,
    )
    return bool(choice)


def _input_phase_rad(default_phase_rad: float = 0.0) -> float:
    value, unit = Input.input_number_with_unit(
        "Enter phase",
        default=(math.degrees(default_phase_rad), "deg"),
        default_unit="deg",
        allowed_units=("deg", "rad", "pi"),
        allow_float=True,
        allow_negative=True,
    )
    if unit == "deg":
        return math.radians(float(value))
    if unit == "rad":
        return float(value)
    if unit == "pi":
        return float(value) * math.pi
    raise ValueError(f"Unsupported phase unit: {unit}")


def _stripe_direction_default_key(direction: StripeDirection) -> str:
    return {
        StripeDirection.HORIZONTAL_STRIPES: "1",
        StripeDirection.VERTICAL_STRIPES: "2",
        StripeDirection.CUSTOM_ANGLE: "3",
    }[direction]


def _select_stripe_direction(default: StripeDirection = StripeDirection.VERTICAL_STRIPES) -> StripeDirection:
    return cast(StripeDirection, Menu.select(
        [
            MenuOption(["1", "H"], "Horizontal stripes (vertical variation) ▤", StripeDirection.HORIZONTAL_STRIPES),
            MenuOption(["2", "V"], "Vertical stripes (horizontal variation) ▥", StripeDirection.VERTICAL_STRIPES),
            MenuOption(["3", "A"], "Custom angle (clockwise from ▥)", StripeDirection.CUSTOM_ANGLE),
        ],
        prompt="Select stripe direction",
        required=True,
        default_key=_stripe_direction_default_key(default),
    ))


def _input_sinusoidal_config(
    frequency_unit: FrequencyUnit,
    defaults: SinusoidalInputDefaults,
) -> SinusoidalConfig:
    stripe_direction = _select_stripe_direction(defaults.stripe_direction)

    if stripe_direction is StripeDirection.HORIZONTAL_STRIPES:
        stripe_angle_deg = 90.0
    elif stripe_direction is StripeDirection.VERTICAL_STRIPES:
        stripe_angle_deg = 0.0
    else:
        angle_value, _angle_unit = Input.input_number_with_unit(
            "Enter stripe angle (clockwise from vertical stripes ▥)",
            default=(defaults.stripe_angle_deg, "deg"),
            default_unit="deg",
            allowed_units=("deg",),
            allow_float=True,
            allow_negative=True,
        )
        stripe_angle_deg = float(angle_value)

    frequency = Input.input_number(
        "Enter frequency" if frequency_unit is FrequencyUnit.TOTAL_CYCLES else "Enter period in pixels",
        default=defaults.frequency,
        min_value=0,
        min_value_allowed=False,
        allow_float=True,
        allow_negative=False,
    )
    phase_rad = _input_phase_rad(defaults.phase_rad)

    return SinusoidalConfig(
        frequency_unit=frequency_unit,
        frequency=float(frequency),
        phase_rad=phase_rad,
        stripe_direction=stripe_direction,
        stripe_angle_deg=stripe_angle_deg,
    )


def _phase_label_for_filename(phase_rad: float) -> str:
    phase_deg = math.degrees(phase_rad)
    label = f"{phase_deg:g}".replace("-", "neg").replace(".", "p")
    return f"phase_{label}deg"


def _default_output_path(projector: ProjectorSpec, cfg: SinusoidalConfig) -> str:
    direction = {
        StripeDirection.HORIZONTAL_STRIPES: "horizontal",
        StripeDirection.VERTICAL_STRIPES: "vertical",
        StripeDirection.CUSTOM_ANGLE: f"angle_{cfg.stripe_angle_deg:g}deg",
    }[cfg.stripe_direction]
    unit = "cycles" if cfg.frequency_unit is FrequencyUnit.TOTAL_CYCLES else "period_px"
    phase = _phase_label_for_filename(cfg.phase_rad)
    name = f"sinusoidal_{projector.width}x{projector.height}_{direction}_{cfg.frequency:g}_{unit}_{phase}.bmp"
    return os.path.join(os.getcwd(), "output/generated_patterns", name)


def _print_summary(request: PatternRequest) -> None:
    cfg = request.config
    phase_deg = math.degrees(cfg.phase_rad)
    freq_unit = "Total cycles" if cfg.frequency_unit is FrequencyUnit.TOTAL_CYCLES else "Period in pixels"
    direction_label = {
        StripeDirection.HORIZONTAL_STRIPES: "▤ Horizontal, vertical variation",
        StripeDirection.VERTICAL_STRIPES: "▥ Vertical, horizontal variation",
        StripeDirection.CUSTOM_ANGLE: f"Custom angle {cfg.stripe_angle_deg:g} deg from ▥",
    }[cfg.stripe_direction]

    print(f"\n{FLYellow}Generation parameters:{CRst}")
    print(f"  Pattern type:  {FLGreen}Sinusoidal stripes{CRst}")
    print(f"  Coordinates:   {FLGreen}Cartesian{CRst}")
    print(f"  Resolution:    {FLGreen}{request.projector.width} x {request.projector.height}{CRst}")
    print(f"  Frequency unit:{FLGreen}{freq_unit}{CRst}")
    print(f"  Frequency:     {FLGreen}{cfg.frequency:g}{CRst}")
    print(f"  Phase:         {FLGreen}{phase_deg:g} deg{CRst} {FGray}({cfg.phase_rad:g} rad){CRst}")
    print(f"  Stripe dir.:   {FLGreen}{direction_label}{CRst}")
    print(f"  Output path:   {FGray}{request.output_path}{CRst}")


def _confirm_generate() -> bool:
    choice = Menu.select(
        [
            MenuOption(["Y"], "Generate", True, FLGreen),
            MenuOption(["N"], "Cancel", False, FLRed),
        ],
        prompt="Confirm",
        required=True,
        default_key="Y",
        inline=True,
        separator_width=28,
    )
    return bool(choice)


def _initial_sinusoidal_defaults(frequency_unit: FrequencyUnit) -> SinusoidalInputDefaults:
    return SinusoidalInputDefaults(
        frequency=16.0 if frequency_unit is FrequencyUnit.TOTAL_CYCLES else 120.0,
    )


def _run_generation_loop(
    pattern_type: PatternType,
    projector: ProjectorSpec,
    frequency_unit: FrequencyUnit,
    preview_enabled: bool,
) -> None:
    generator = PatternGenerator()
    defaults = _initial_sinusoidal_defaults(frequency_unit)
    while True:
        print()
        Utils.print_separator(width=44, color_ansi_esc=FLCyan)
        cfg = _input_sinusoidal_config(frequency_unit, defaults)
        defaults = SinusoidalInputDefaults(
            frequency=cfg.frequency,
            phase_rad=cfg.phase_rad,
            stripe_direction=cfg.stripe_direction,
            stripe_angle_deg=cfg.stripe_angle_deg,
        )
        output_path = Input.resolve_output_path(
            _default_output_path(projector, cfg),
            prompt="Enter output file path",
            path_type="file",
        )
        request = PatternRequest(
            pattern_type=pattern_type,
            projector=projector,
            config=cfg,
            output_path=output_path,
        )
        _print_summary(request)

        if not _confirm_generate():
            print(f"{FGray}Canceled — skipping this round.{CRst}")
            continue

        try:
            image = generator.generate(request)
            if not _confirm_save_after_preview(image, preview_enabled):
                print(f"{FGray}Discarded — image was not saved.{CRst}")
                continue
            if not _imwrite_unicode(request.output_path, image):
                print(f"{FLRed}Generation failed: unable to write image file.{CRst}")
                continue
            print(f"{FLGreen}Generated successfully:{CRst} {FGray}{request.output_path}{CRst}")
        except Exception as e:
            print(f"{FLRed}Generation failed: {e}{CRst}")


def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
{FLYellow}STRUCTURED LIGHT PATTERN GENERATOR{CRst}
==================================

Usage:
  python {script_name}          interactive structured-light pattern generator
  python {script_name} --help   show this help

{FLYellow}Implemented:{CRst}
  Pattern:        sinusoidal stripes
  Coordinates:    Cartesian projector coordinates
  Preview:        optional detached OpenCV window; terminal confirms save/discard
  Output:         8-bit grayscale image; PNG uses lossless compression level 9

{FLYellow}Requirements:{CRst}
  Python: {FGray}pip install opencv-python numpy{CRst}
""")
        return 0

    Utils.print_banner("STRUCTURED LIGHT PATTERN GENERATOR")

    pattern_type = _select_pattern_type()
    coordinate_system = _select_coordinate_system()
    projector = _input_projector_spec(coordinate_system)
    frequency_unit = _select_frequency_unit()
    preview_enabled = _select_preview_enabled()
    _run_generation_loop(pattern_type, projector, frequency_unit, preview_enabled)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
