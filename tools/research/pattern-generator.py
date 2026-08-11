#!/usr/bin/env python3
"""Generate structured-light projector patterns.

This script provides an interactive terminal workflow for generating
structured-light projector images. It currently supports sinusoidal stripe
patterns and standard Gray-code patterns, including complementary inverse
Gray-code images for phase unwrapping workflows.

Requirements:
    - pip: opencv-python, numpy

Usage:
    python research/pattern-generator.py
    python research/pattern-generator.py --help
"""

import enum
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Sequence, cast

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
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
    GRAY_CODE = "2"
    SPECKLE = "3"


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


class GrayCodeAxes(enum.Enum):
    X_ONLY = "1"
    Y_ONLY = "2"
    X_AND_Y = "3"


class BitOrder(enum.Enum):
    MSB_FIRST = "1"
    LSB_FIRST = "2"


class BitCountMode(enum.Enum):
    AUTO = "1"
    MANUAL = "2"


class GrayCodeSegmentMode(enum.Enum):
    SEGMENT_WIDTH = "1"
    SEGMENT_COUNT = "2"


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
class GrayCodeConfig:
    axes: GrayCodeAxes
    bit_order: BitOrder
    bit_count_mode: BitCountMode
    segment_mode: GrayCodeSegmentMode
    include_inverse: bool
    x_bits: int | None = None
    y_bits: int | None = None
    x_segment_width: int | None = None
    y_segment_width: int | None = None
    x_segment_count: int | None = None
    y_segment_count: int | None = None
    black_level: int = 0
    white_level: int = 255


@dataclass(frozen=True)
class GrayCodeAxisPlan:
    axis: Literal["x", "y"]
    segment_count: int
    segment_width: int
    bit_count: int


@dataclass(frozen=True)
class GeneratedPattern:
    filename: str
    image: "np.ndarray"


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


class GrayCodePatternStrategy:
    """Generate standard Gray-code pattern sequences."""

    def generate_many(
        self,
        projector: ProjectorSpec,
        config: GrayCodeConfig,
        *,
        suffix: str = ".bmp",
    ) -> list[GeneratedPattern]:
        """Generate all Gray-code images described by ``config``.

        Args:
            projector: Projector resolution and coordinate-system descriptor.
            config: Gray-code generation settings. Only full-area Cartesian
                standard Gray code is supported.
            suffix: Output filename suffix, such as ``".bmp"`` or ``".png"``.

        Returns:
            Ordered list of generated filename/image pairs.

        Raises:
            NotImplementedError: If the projector coordinate system is not
                Cartesian.
            ValueError: If the segment configuration is invalid.

        Side effects:
            Allocates image arrays in memory; does not write files.
        """
        if projector.coordinate_system is not CoordinateSystem.CARTESIAN:
            raise NotImplementedError("Only Cartesian coordinate system is implemented now.")

        suffix = suffix if suffix.startswith(".") else f".{suffix}"
        plans = self._build_axis_plans(projector, config)
        patterns: list[GeneratedPattern] = []
        order_label = "msb" if config.bit_order is BitOrder.MSB_FIRST else "lsb"

        for plan in plans:
            bit_indices = self._bit_indices(plan.bit_count, config.bit_order)
            for output_index, bit_index in enumerate(bit_indices):
                image = self._generate_axis_bit_image(projector, config, plan, bit_index, inverse=False)
                filename = f"gray_{plan.axis}_period{plan.segment_count}_{order_label}_bit{output_index:02d}{suffix}"
                patterns.append(GeneratedPattern(filename=filename, image=image))

                if config.include_inverse:
                    inverse_image = self._generate_axis_bit_image(projector, config, plan, bit_index, inverse=True)
                    inverse_filename = f"gray_{plan.axis}_period{plan.segment_count}_{order_label}_bit{output_index:02d}_inv{suffix}"
                    patterns.append(GeneratedPattern(filename=inverse_filename, image=inverse_image))

        return patterns

    @staticmethod
    def _bit_indices(bit_count: int, bit_order: BitOrder) -> Sequence[int]:
        if bit_order is BitOrder.MSB_FIRST:
            return range(bit_count - 1, -1, -1)
        return range(bit_count)

    @staticmethod
    def _build_axis_plans(projector: ProjectorSpec, config: GrayCodeConfig) -> list[GrayCodeAxisPlan]:
        plans: list[GrayCodeAxisPlan] = []
        if config.axes in (GrayCodeAxes.X_ONLY, GrayCodeAxes.X_AND_Y):
            plans.append(GrayCodePatternStrategy._build_one_axis_plan("x", projector.width, config))
        if config.axes in (GrayCodeAxes.Y_ONLY, GrayCodeAxes.X_AND_Y):
            plans.append(GrayCodePatternStrategy._build_one_axis_plan("y", projector.height, config))
        return plans

    @staticmethod
    def _build_one_axis_plan(axis: Literal["x", "y"], length: int, config: GrayCodeConfig) -> GrayCodeAxisPlan:
        if config.segment_mode is GrayCodeSegmentMode.SEGMENT_COUNT:
            segment_count = config.x_segment_count if axis == "x" else config.y_segment_count
            if segment_count is None:
                raise ValueError(f"{axis.upper()} segment count is required.")
            if segment_count <= 0:
                raise ValueError(f"{axis.upper()} segment count must be positive.")
            if length % segment_count != 0:
                raise ValueError(f"{axis.upper()} segment count {segment_count} must divide {length}.")
            segment_width = length // segment_count
        else:
            segment_width = config.x_segment_width if axis == "x" else config.y_segment_width
            if segment_width is None:
                raise ValueError(f"{axis.upper()} segment width is required.")
            if segment_width <= 0:
                raise ValueError(f"{axis.upper()} segment width must be positive.")
            if length % segment_width != 0:
                raise ValueError(f"{axis.upper()} segment width {segment_width} must divide {length}.")
            segment_count = length // segment_width

        auto_bits = math.ceil(math.log2(segment_count)) if segment_count > 1 else 1
        manual_bits = config.x_bits if axis == "x" else config.y_bits
        bit_count = auto_bits if config.bit_count_mode is BitCountMode.AUTO else manual_bits
        if bit_count is None:
            raise ValueError(f"{axis.upper()} bit count is required.")
        if bit_count < auto_bits:
            raise ValueError(
                f"{axis.upper()} bit count {bit_count} is too small for {segment_count} segments; need at least {auto_bits}."
            )

        return GrayCodeAxisPlan(
            axis=axis,
            segment_count=segment_count,
            segment_width=segment_width,
            bit_count=bit_count,
        )

    @staticmethod
    def _generate_axis_bit_image(
        projector: ProjectorSpec,
        config: GrayCodeConfig,
        plan: GrayCodeAxisPlan,
        bit_index: int,
        *,
        inverse: bool,
    ) -> "np.ndarray":
        length = projector.width if plan.axis == "x" else projector.height
        coords = np.arange(length, dtype=np.int32)
        segment_index = coords * plan.segment_count // length
        gray = segment_index ^ (segment_index >> 1)
        bit = (gray >> bit_index) & 1
        if inverse:
            bit = 1 - bit

        values = np.where(bit == 1, config.white_level, config.black_level).astype(np.uint8)
        if plan.axis == "x":
            gray_image = np.tile(values, (projector.height, 1))
        else:
            gray_image = np.tile(values[:, np.newaxis], (1, projector.width))
        return cv2.cvtColor(gray_image, cv2.COLOR_GRAY2BGR)


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


def save_generated_patterns(output_dir: str | Path, patterns: Sequence[GeneratedPattern]) -> list[str]:
    """Write generated patterns to a directory.

    Args:
        output_dir: Directory where all images are written. It is created when
            missing.
        patterns: Ordered filename/image pairs to write.

    Returns:
        Absolute paths of written image files in the same order as ``patterns``.

    Raises:
        RuntimeError: If any image cannot be encoded or written.

    Side effects:
        Creates ``output_dir`` and writes image files.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for pattern in patterns:
        image_path = output_path / pattern.filename
        if not _imwrite_unicode(str(image_path), pattern.image):
            raise RuntimeError(f"Failed to write {image_path}")
        written.append(str(image_path))
    return written


def write_projector_sequence_txt(
    txt_path: str | Path,
    filenames: Sequence[str],
    *,
    display_time_ms: int = 8998,
    trigger_delay_us: int = 100000,
) -> None:
    """Write a projector sequence text file.

    Args:
        txt_path: Destination ``.txt`` path.
        filenames: Image filenames to list, without parent directories.
        display_time_ms: Display time value written to the third CSV column.
        trigger_delay_us: Trigger delay value written to the fourth CSV column.

    Returns:
        None.

    Side effects:
        Creates the parent directory and writes a UTF-8 text file.
    """
    path = Path(txt_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        file.write("Normal Mode\n")
        for filename in filenames:
            file.write(f"{filename},8,{display_time_ms},{trigger_delay_us},1,0,1\n")


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
                MenuOption(["2", "G"], "Gray Code", PatternType.GRAY_CODE),
                MenuOption(["3"], f"Speckle {FGray}(not implemented){CRst}", PatternType.SPECKLE),
            ],
            prompt="Select pattern type",
            required=True,
            default_key="1",
        )
        if choice in (PatternType.SINUSOIDAL, PatternType.GRAY_CODE):
            return choice
        print(f"{FLRed}Speckle pattern is not yet implemented. Please choose an implemented pattern.{CRst}\n")


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


def _select_gray_axes() -> GrayCodeAxes:
    return cast(GrayCodeAxes, Menu.select(
        [
            MenuOption(["1", "X"], "X only: vertical bars, encode projector X", GrayCodeAxes.X_ONLY),
            MenuOption(["2", "Y"], "Y only: horizontal bars, encode projector Y", GrayCodeAxes.Y_ONLY),
            MenuOption(["3", "B"], "X + Y", GrayCodeAxes.X_AND_Y),
        ],
        prompt="Select Gray-code axis",
        required=True,
        default_key="1",
    ))


def _select_bit_order() -> BitOrder:
    return cast(BitOrder, Menu.select(
        [
            MenuOption(["1", "M"], "MSB first", BitOrder.MSB_FIRST),
            MenuOption(["2", "L"], "LSB first", BitOrder.LSB_FIRST),
        ],
        prompt="Select bit order",
        required=True,
        default_key="1",
    ))


def _select_segment_mode() -> GrayCodeSegmentMode:
    return cast(GrayCodeSegmentMode, Menu.select(
        [
            MenuOption(["1", "W"], "Segment width in pixels", GrayCodeSegmentMode.SEGMENT_WIDTH),
            MenuOption(["2", "C"], "Segment count / sinusoidal cycle count", GrayCodeSegmentMode.SEGMENT_COUNT),
        ],
        prompt="Select Gray-code segment mode",
        required=True,
        default_key="2",
    ))


def _select_bit_count_mode() -> BitCountMode:
    return cast(BitCountMode, Menu.select(
        [
            MenuOption(["1", "A"], "Auto", BitCountMode.AUTO),
            MenuOption(["2", "M"], "Manual", BitCountMode.MANUAL),
        ],
        prompt="Select bit-count mode",
        required=True,
        default_key="1",
    ))


def _select_include_inverse() -> bool:
    choice = Menu.select(
        [
            MenuOption(["Y"], "Generate inverse patterns", True, FLGreen),
            MenuOption(["N"], "Do not generate inverse patterns", False, FLRed),
        ],
        prompt="Generate inverse Gray-code patterns?",
        required=True,
        default_key="Y",
        inline=True,
        separator_width=44,
    )
    return bool(choice)


def _axis_enabled(axes: GrayCodeAxes, axis: Literal["x", "y"]) -> bool:
    if axis == "x":
        return axes in (GrayCodeAxes.X_ONLY, GrayCodeAxes.X_AND_Y)
    return axes in (GrayCodeAxes.Y_ONLY, GrayCodeAxes.X_AND_Y)


def _default_segment_count(axis_length: int) -> int:
    return max(1, axis_length // 10)


def _input_gray_code_config(projector: ProjectorSpec) -> GrayCodeConfig:
    axes = _select_gray_axes()
    print(f"{FGray}Coordinate range: Full area{CRst}")
    print(f"{FGray}Gray-code type: Standard Gray code{CRst}")

    bit_order = _select_bit_order()
    segment_mode = _select_segment_mode()

    x_segment_width: int | None = None
    y_segment_width: int | None = None
    x_segment_count: int | None = None
    y_segment_count: int | None = None

    if segment_mode is GrayCodeSegmentMode.SEGMENT_COUNT:
        if _axis_enabled(axes, "x"):
            x_segment_count = int(Input.input_number(
                "Enter X segment count / sinusoidal cycle count",
                default=_default_segment_count(projector.width),
                min_value=1,
                allow_float=False,
                allow_negative=False,
            ))
            if projector.width % x_segment_count != 0:
                raise ValueError(f"X segment count {x_segment_count} must divide projector width {projector.width}.")
        if _axis_enabled(axes, "y"):
            y_segment_count = int(Input.input_number(
                "Enter Y segment count / sinusoidal cycle count",
                default=_default_segment_count(projector.height),
                min_value=1,
                allow_float=False,
                allow_negative=False,
            ))
            if projector.height % y_segment_count != 0:
                raise ValueError(f"Y segment count {y_segment_count} must divide projector height {projector.height}.")
    else:
        if _axis_enabled(axes, "x"):
            x_segment_width = int(Input.input_number(
                "Enter X segment width in pixels",
                default=10,
                min_value=1,
                allow_float=False,
                allow_negative=False,
            ))
            if projector.width % x_segment_width != 0:
                raise ValueError(f"X segment width {x_segment_width} must divide projector width {projector.width}.")
        if _axis_enabled(axes, "y"):
            y_segment_width = int(Input.input_number(
                "Enter Y segment width in pixels",
                default=10,
                min_value=1,
                allow_float=False,
                allow_negative=False,
            ))
            if projector.height % y_segment_width != 0:
                raise ValueError(f"Y segment width {y_segment_width} must divide projector height {projector.height}.")

    bit_count_mode = _select_bit_count_mode()
    x_bits: int | None = None
    y_bits: int | None = None

    probe_config = GrayCodeConfig(
        axes=axes,
        bit_order=bit_order,
        bit_count_mode=BitCountMode.AUTO,
        segment_mode=segment_mode,
        include_inverse=True,
        x_segment_width=x_segment_width,
        y_segment_width=y_segment_width,
        x_segment_count=x_segment_count,
        y_segment_count=y_segment_count,
    )
    auto_plans = GrayCodePatternStrategy._build_axis_plans(projector, probe_config)
    auto_bits = {plan.axis: plan.bit_count for plan in auto_plans}

    if bit_count_mode is BitCountMode.MANUAL:
        if _axis_enabled(axes, "x"):
            x_bits = int(Input.input_number(
                "Enter X bit count",
                default=auto_bits["x"],
                min_value=auto_bits["x"],
                allow_float=False,
                allow_negative=False,
            ))
        if _axis_enabled(axes, "y"):
            y_bits = int(Input.input_number(
                "Enter Y bit count",
                default=auto_bits["y"],
                min_value=auto_bits["y"],
                allow_float=False,
                allow_negative=False,
            ))

    include_inverse = _select_include_inverse()

    return GrayCodeConfig(
        axes=axes,
        bit_order=bit_order,
        bit_count_mode=bit_count_mode,
        segment_mode=segment_mode,
        include_inverse=include_inverse,
        x_bits=x_bits,
        y_bits=y_bits,
        x_segment_width=x_segment_width,
        y_segment_width=y_segment_width,
        x_segment_count=x_segment_count,
        y_segment_count=y_segment_count,
    )


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


def _gray_axes_label(axes: GrayCodeAxes) -> str:
    return {
        GrayCodeAxes.X_ONLY: "X only",
        GrayCodeAxes.Y_ONLY: "Y only",
        GrayCodeAxes.X_AND_Y: "X + Y",
    }[axes]


def _gray_segment_mode_label(mode: GrayCodeSegmentMode) -> str:
    return {
        GrayCodeSegmentMode.SEGMENT_WIDTH: "Segment width in pixels",
        GrayCodeSegmentMode.SEGMENT_COUNT: "Segment count / sinusoidal cycle count",
    }[mode]


def _default_gray_output_dir() -> str:
    return os.path.join(os.getcwd(), "output", "generated_patterns", "graycode")


def _default_gray_txt_path(output_dir: str, projector: ProjectorSpec, patterns: Sequence[GeneratedPattern]) -> str:
    name = f"graycode_{projector.width}x{projector.height}_{len(patterns)}pics.txt"
    return os.path.join(output_dir, name)


def _print_gray_summary(
    projector: ProjectorSpec,
    config: GrayCodeConfig,
    output_dir: str,
    txt_path: str,
    patterns: Sequence[GeneratedPattern],
) -> None:
    strategy = GrayCodePatternStrategy()
    plans = strategy._build_axis_plans(projector, config)
    print(f"\n{FLYellow}Generation parameters:{CRst}")
    print(f"  Pattern type:  {FLGreen}Standard Gray code{CRst}")
    print(f"  Coordinates:   {FLGreen}Cartesian, full area{CRst}")
    print(f"  Resolution:    {FLGreen}{projector.width} x {projector.height}{CRst}")
    print(f"  Axes:          {FLGreen}{_gray_axes_label(config.axes)}{CRst}")
    print(f"  Bit order:     {FLGreen}{'MSB first' if config.bit_order is BitOrder.MSB_FIRST else 'LSB first'}{CRst}")
    print(f"  Segment mode:  {FLGreen}{_gray_segment_mode_label(config.segment_mode)}{CRst}")
    for plan in plans:
        print(
            f"  {plan.axis.upper()} plan:       "
            f"{FLGreen}{plan.segment_count} segments, {plan.segment_width} px/segment, {plan.bit_count} bits{CRst}"
        )
    print(f"  Inverse:       {FLGreen}{'yes' if config.include_inverse else 'no'}{CRst}")
    print(f"  Image count:   {FLGreen}{len(patterns)}{CRst}")
    print(f"  Output dir:    {FGray}{output_dir}{CRst}")
    print(f"  Sequence txt:  {FGray}{txt_path}{CRst}")


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


def _run_gray_code_workflow(projector: ProjectorSpec) -> None:
    strategy = GrayCodePatternStrategy()
    while True:
        print()
        Utils.print_separator(width=44, color_ansi_esc=FLCyan)
        try:
            config = _input_gray_code_config(projector)
            output_dir = Input.resolve_output_path(
                _default_gray_output_dir(),
                prompt="Enter output directory",
                path_type="dir",
            )
            patterns = strategy.generate_many(projector, config, suffix=".bmp")
            txt_path = _default_gray_txt_path(output_dir, projector, patterns)
            _print_gray_summary(projector, config, output_dir, txt_path, patterns)

            if not _confirm_generate():
                print(f"{FGray}Canceled — skipping this round.{CRst}")
                continue

            save_generated_patterns(output_dir, patterns)
            write_projector_sequence_txt(txt_path, [pattern.filename for pattern in patterns])
            print(f"{FLGreen}Generated successfully:{CRst} {FGray}{output_dir}{CRst}")
            print(f"{FLGreen}Sequence file:{CRst} {FGray}{txt_path}{CRst}")
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

{FLYellow}Description:{CRst}
  Interactive generator for structured-light projector images. It can create
  single sinusoidal stripe patterns, or full standard Gray-code image sequences
  for projector-coordinate / sinusoidal-cycle indexing.

{FLYellow}Options:{CRst}
  -h, --help                    show this help

{FLYellow}Implemented:{CRst}
  Patterns:       sinusoidal stripes; standard Gray code
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

    if pattern_type is PatternType.GRAY_CODE:
        _run_gray_code_workflow(projector)
        return 0

    frequency_unit = _select_frequency_unit()
    preview_enabled = _select_preview_enabled()
    _run_generation_loop(pattern_type, projector, frequency_unit, preview_enabled)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
