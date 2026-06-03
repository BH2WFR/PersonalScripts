import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from my_utils import *

import numpy as np
import math
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.axes3d import Axes3D

import enum
import typing


help_message = f'''
{FLYellow}------------------ npy/npz Interactive File Viewer ------------------{CRst}
{FLYellow}Arguments:{CRst}
    Auto-detects 1D/2D arrays in npy/npz files and chooses display mode accordingly.
    For npz files, lists all array names and prompts to select which to display.
    Interactive loop:
        Enter `1,2,3` to open arrays at index 1, 2, 3
        Enter `1,2,3-5` to open arrays at index 1, 2, 3, 4, 5
        Enter `all` to open all arrays
        Enter `exit` to quit
    After opening, re-print the prompt until `exit` is entered.

{FLYellow}1D array{CRst}
    show_npy.py <npy_file_path> [--color <color_name>] [--mode <line|points|line+points>]
        [--line-shape <linear|spline>] [--max-display-size <int>]
        [--force-plt | --force-matplotlib]
    If --color is not specified, default: royalblue
    If --mode is not specified, default: line
    If --line-shape is not specified, default: linear
    If --max-display-size is not specified, prompts to show all data or sampled
    If --force-plt/--force-matplotlib not specified, defaults to plotly, falls back to matplotlib

{FLYellow}2D array{CRst}
    show_npy.py <npy_file_path> [--3d | --2d] [--color-scale <name>]
        [--max-display-size <int>] [--force-plt | --force-matplotlib]
    If --3d/--2d is not specified, default: 2d
    If --color-scale is not specified, default: cividis
    If --max-display-size is not specified, default: all
    If --force-plt/--force-matplotlib not specified, defaults to plotly, falls back to matplotlib
'''

class DisplayMode(enum.Enum):
    LINE = "line"
    POINTS = "points"
    LINE_POINTS = "line+points"
    
class LineShape(enum.Enum):
    LINEAR = "linear"
    SPLINE = "spline"
    
class LineColor(enum.Enum):
    ROYALBLUE = "royalblue"
    CRIMSON = "crimson"
    DARKGREEN = "darkgreen"
    ORANGE = "orange"
    PURPLE = "purple"
    OTHERS = "others"


DEFAULT_COLOR_SCALES = [
    "gray",
    "viridis",
    "plasma",
    "inferno",
    "magma",
    "cividis",
]
    



#* 交互式显示 一维 ndarray
# 点状、曲线、折线可切换
# 颜色可切换
def show_1d_array(
    array: np.ndarray,
    title: str = "Array",
    color: str = "royalblue",
    mode: str = "line",
    line_shape: str = "linear",
    max_display_size: int | None = None,
    force_plt: bool = False,
):
    converted = np.asarray(array).squeeze()
    if converted.ndim != 1:
        raise ValueError(f"Input array must be 1D, but got shape {array.shape}")
    
    if max_display_size is not None:
        step = max(1, math.ceil(converted.shape[0] / max_display_size))
        y = converted[::step]
        x = np.arange(0, converted.shape[0], step)
    else:
        y = converted
        x = np.arange(converted.shape[0])
    
    mode_map = {
        "line": "lines",
        "lines": "lines",
        "points": "markers",
        "point": "markers",
        "scatter": "markers",
        "markers": "markers",
        "line+points": "lines+markers",
        "lines+markers": "lines+markers",
        "both": "lines+markers",
    }
    plotly_mode = mode_map.get(mode.lower())
    if plotly_mode is None:
        raise ValueError("mode must be one of: line, points, line+points")
    
    line_shape_map = {
        "linear": "linear",
        "line": "linear",
        "spline": "spline",
        "curve": "spline",
    }
    plotly_line_shape = line_shape_map.get(line_shape.lower())
    if plotly_line_shape is None:
        raise ValueError("line_shape must be 'linear' or 'spline'")
    
    try:
        if force_plt:
            raise Exception("force plt")
        import plotly.graph_objects as go
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=x,
            y=y,
            mode=plotly_mode,
            line=dict(color=color, shape=plotly_line_shape),
            marker=dict(color=color),
            name=title,
        ))
        fig.update_layout(
            title=title,
            dragmode="pan",
            margin=dict(l=40, r=20, t=40, b=40),
            xaxis_title="Index",
            yaxis_title="Value",
        )
        fig.show(config={"scrollZoom": True})
        return
    except Exception as e:
        print(f"{FLYellow}WARNING{CRst}: plotly display failed, fallback to matplotlib: {e}")
    
    fig, ax = plt.subplots()
    if plotly_mode == "markers":
        ax.scatter(x, y, color=color, s=12)
    elif plotly_mode == "lines+markers":
        ax.plot(x, y, color=color, marker="o", markersize=3)
    else:
        ax.plot(x, y, color=color)
    
    ax.set_title(title)
    ax.set_xlabel("Index")
    ax.set_ylabel("Value")
    ax.grid(True, alpha=0.3)
    
    plt.show()

#* 交互式显示 2d ndarray 图像
# 优先使用 plotly, 如果失败则回退到 matplotlib.pyplot
def show_2d_array_3d(
    image_array: np.ndarray,
    title: str = "Image",
    color_scale: str = "cividis",
    max_display_size: int | None = None,
    force_plt: bool = False
):
    if(image_array.ndim != 2):
        raise ValueError(f"Input image_array must be 2D, but got shape {image_array.shape}")

    converted = np.asarray(image_array, dtype=np.float32)
    rows, cols = converted.shape
    
    # if max_display_size is None
    if max_display_size is not None:
        step = max(1, math.ceil(max(rows, cols) / max_display_size))
        converted_display = converted[::step, ::step]
    else:
        step = 1
        converted_display = converted
    
    try:
        if(force_plt):
            raise Exception("force plt")
        
        import plotly.graph_objects as go
        
        fig = go.Figure(data=[
            go.Surface(
                z=converted_display,
                x=np.arange(0, cols, step),
                y=np.arange(0, rows, step),
                colorscale=color_scale,
            )
        ])
        fig.update_layout(
            title=title,
            scene=dict(
                xaxis_title="X axis",
                yaxis_title="Y axis",
                zaxis_title="Pixel Value",
            ),
        )
        fig.show()
        return
    except Exception as e:
        print(f"{FLYellow}WARNING{CRst}: plotly display failed, fallback to matplotlib: {e}")
    
    display_rows, display_cols = converted_display.shape
    x, y = np.meshgrid(np.arange(display_cols) * step, np.arange(display_rows) * step)
    
    fig = plt.figure()
    ax = typing.cast(Axes3D, fig.add_subplot(111, projection='3d'))
    ax.plot_surface(x, y, converted_display, cmap=color_scale)
    
    ax.set_xlabel('X axis')
    ax.set_ylabel('Y axis')
    ax.set_zlabel('Pixel Value')
    
    plt.title(title)
    plt.show()

# 交互式显示 ndarray 图像，颜色可选择灰度或热力图
# 优先使用 plotly, 如果失败则回退到 matplotlib.pyplot
# cmap 可选 "gray", "viridis(黄-绿-蓝-紫)", "plasma(黄-橙-紫-蓝)", "inferno(黄-橙-红-黑)", "magma(白-粉-紫-黑)", "cividis(黄-蓝黑)" 等 matplotlib 支持的颜色映射方案
def show_2d_array_2d(
    image_array: np.ndarray,
    title: str = "Image",
    color_scale: str = "cividis",
    max_display_size: int | None = None,
    force_plt: bool = False
):
    if(image_array.ndim != 2):
        raise ValueError(f"Input image_array must be 2D, but got shape {image_array.shape}")
    
    converted = np.asarray(image_array)
    if max_display_size is not None:
        rows, cols = converted.shape[:2]
        step = max(1, math.ceil(max(rows, cols) / max_display_size))
        converted_display = converted[::step, ::step]
    else:
        converted_display = converted
    
    try:
        if(force_plt):
            raise Exception("force plt")
        import plotly.express as px
        
        fig = px.imshow(
            converted_display,
            color_continuous_scale=color_scale,
            title=title,
            aspect="equal",
        )
        fig.update_layout(
            dragmode="pan",
            margin=dict(l=0, r=0, t=40, b=0),
        )
        fig.update_xaxes(title_text="X axis")
        fig.update_yaxes(title_text="Y axis")
        fig.show(config={"scrollZoom": True})
        return
    except Exception as e:
        print(f"{FLYellow}WARNING{CRst}: plotly display failed, fallback to matplotlib: {e}")
    
    fig, ax = plt.subplots()
    im = ax.imshow(converted_display, cmap=color_scale)
    fig.colorbar(im, ax=ax)
    ax.set_title(title)
    ax.axis('off')
    
    plt.show()


def _prompt_choice(
    title: str,
    choices: list[str],
    allow_custom: bool = False,
    default: str | None = None,
) -> str:
    print(f"{FLYellow}{title}{CRst}")
    for index, choice in enumerate(choices, start=1):
        default_mark = f"{FLYellow} (默认){CRst}" if choice == default else ""
        print(f"  {FLGreen}{index}{CRst}. {FLCyan}{choice}{CRst}{default_mark}")
    if allow_custom:
        print(f"  {FLGreen}others. 输入自定义值{CRst}")
    
    while True:
        default_hint = f"，直接回车使用默认值 {FLCyan}{default}{CRst}" if default is not None else ""
        value = input(f"请选择序号或输入值{default_hint}: ").strip()
        if not value:
            if default is not None:
                return default
            continue
        if value.isdigit():
            selected_index = int(value) - 1
            if 0 <= selected_index < len(choices):
                return choices[selected_index]
            print(f"{FLRed}ERROR{CRst}: 序号超出范围")
            continue
        if value in choices:
            return value
        if allow_custom:
            if value.lower() == "others":
                custom = input("请输入自定义值: ").strip()
                if custom:
                    return custom
            else:
                return value
        print(f"{FLRed}ERROR{CRst}: 无效输入")


def _prompt_bool(title: str) -> bool:
    while True:
        value = input(f"{FLYellow}{title}{CRst} [y/n]: ").strip().lower()
        if value in ("y", "yes", "1", "true", "t"):
            return True
        if value in ("n", "no", "0", "false", "f"):
            return False
        print(f"{FLRed}ERROR{CRst}: 请输入 y 或 n")


def _prompt_max_display_size(default: int | None = None) -> int | None:
    print(f"{FLGreen}max-display-size{CRst} 说明:")
    print(f"  直接{FLCyan}回车{CRst}或输入 {FLCyan}all{CRst}: 显示所有数据点")
    print(f"  输入{FLCyan}正整数{CRst}: 长度超过该值时按步长抽样显示，可避免大数组绘图过慢")
    default_text = "all" if default is None else str(default)
    while True:
        value = input(f"请选择显示方式 [{FLCyan}all{CRst}/{FLCyan}<int>{CRst}]，直接{FLCyan}回车{CRst}使用默认值 {default_text}: ").strip().lower()
        if not value:
            return default
        if value in ("all", "none", "no"):
            return None
        try:
            max_display_size = int(value)
        except ValueError:
            print(f"{FLRed}ERROR{CRst}: 请输入正整数或 all")
            continue
        if max_display_size > 0:
            return max_display_size
        print(f"{FLRed}ERROR{CRst}: max-display-size 必须大于 0")


def _parse_max_display_size(value: str | None) -> int | None:
    if value is None:
        return None
    max_display_size = int(value)
    if max_display_size <= 0:
        raise ValueError("--max-display-size must be greater than 0")
    return max_display_size


def _squeeze_supported_array(array: np.ndarray) -> np.ndarray:
    converted = np.asarray(array).squeeze()
    if converted.ndim not in (1, 2):
        raise ValueError(f"Only 1D or 2D arrays are supported, but got shape {array.shape}")
    return converted


def _parse_array_selection(selection: str, max_index: int) -> list[int] | None:
    selection = selection.strip().lower()
    if selection == "all":
        return list(range(max_index))
    if selection == "exit":
        return None
    
    indexes: list[int] = []
    for part in selection.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            if not start_text.strip().isdigit() or not end_text.strip().isdigit():
                raise ValueError(f"Invalid range: {part}")
            start = int(start_text) - 1
            end = int(end_text) - 1
            if start > end:
                start, end = end, start
            indexes.extend(range(start, end + 1))
            continue
        if not part.isdigit():
            raise ValueError(f"Invalid index: {part}")
        indexes.append(int(part) - 1)
    
    unique_indexes: list[int] = []
    for index in indexes:
        if 0 <= index < max_index and index not in unique_indexes:
            unique_indexes.append(index)
    return unique_indexes


def _interactive_1d_options(args) -> dict[str, typing.Any]:
    color = args.color
    if color is None:
        color = _prompt_choice(
            "请选择 1D 数组颜色:",
            [item.value for item in LineColor if item != LineColor.OTHERS],
            allow_custom=True,
            default=LineColor.ROYALBLUE.value,
        )
    
    mode = args.mode
    if mode is None:
        mode = _prompt_choice(
            "请选择 1D 显示模式:",
            [item.value for item in DisplayMode],
            default=DisplayMode.LINE.value,
        )
    
    line_shape = args.line_shape
    if line_shape is None:
        line_shape = _prompt_choice(
            "请选择线条形状:",
            [item.value for item in LineShape],
            default=LineShape.LINEAR.value,
        )
    
    max_display_size = args.max_display_size
    if max_display_size is None:
        max_display_size = _prompt_max_display_size(default=None)
    
    return {
        "color": color,
        "mode": mode,
        "line_shape": line_shape,
        "max_display_size": max_display_size,
        "force_plt": args.force_plt,
    }


def _interactive_2d_options(args) -> dict[str, typing.Any]:
    view_mode = args.view_mode
    if view_mode is None:
        print("2D 显示方式说明:")
        print("  2d: 以图像/热力图方式查看数值分布")
        print("  3d: 以曲面方式查看数值起伏")
        view_mode = _prompt_choice(f"请选择 2D 显示方式:", ["2d", "3d"], default="2d")
    
    color_scale = args.color_scale
    if color_scale is None:
        print(f"{FLGreen}color-scale{CRst} 说明: {FLCyan}gray{CRst} 为灰度，{FLCyan}viridis{CRst}/{FLCyan}plasma{CRst}/{FLCyan}inferno{CRst}/{FLCyan}magma{CRst}/{FLCyan}cividis{CRst} 为常用色彩映射。")
        color_scale = _prompt_choice(
            "请选择颜色映射:",
            DEFAULT_COLOR_SCALES,
            allow_custom=True,
            default="cividis",
        )
    
    max_display_size = args.max_display_size
    if max_display_size is None:
        max_display_size = _prompt_max_display_size(default=None)
    
    return {
        "view_mode": view_mode,
        "color_scale": color_scale,
        "max_display_size": max_display_size,
        "force_plt": args.force_plt,
    }


def _show_array(array: np.ndarray, title: str, args) -> None:
    converted = _squeeze_supported_array(array)
    if converted.ndim == 1:
        options = _interactive_1d_options(args)
        show_1d_array(converted, title=title, **options)
        return
    
    options = _interactive_2d_options(args)
    view_mode = options.pop("view_mode")
    if view_mode == "3d":
        show_2d_array_3d(converted, title=title, **options)
    else:
        show_2d_array_2d(converted, title=title, **options)


def _print_npz_arrays(npz_data: np.lib.npyio.NpzFile) -> list[str]:
    names = list(npz_data.files)
    print("NPZ 文件包含以下数组:")
    for index, name in enumerate(names, start=1):
        array = npz_data[name]
        print(f"  {FLYellow}{index}{CRst}. {FLCyan}{name}{CRst} shape={array.shape} dtype={array.dtype}")
    return names


def _show_npz_interactive(file_path: str, args) -> None:
    with np.load(file_path, allow_pickle=False) as npz_data:
        names = _print_npz_arrays(npz_data)
        if not names:
            print(f"{FLYellow}WARNING{CRst}: NPZ 文件中没有数组")
            return
        
        while True:
            print(f"{FLYellow}请输入数组编号{CRst}，例如 {FLCyan}1,2,3{CRst} 或 {FLCyan}1,2,3-5{CRst}；输入 {FLCyan}all{CRst} 打开全部；输入 {FLCyan}exit{CRst} 退出。")
            selection = input("选择: ").strip()
            try:
                indexes = _parse_array_selection(selection, len(names))
            except ValueError as e:
                print(f"{FLRed}ERROR{CRst}: {e}")
                continue
            
            if indexes is None:
                return
            if not indexes:
                print(f"{FLYellow}WARNING{CRst}: 没有匹配到可显示的数组")
                continue
            
            for index in indexes:
                name = names[index]
                try:
                    _show_array(npz_data[name], title=f"{os.path.basename(file_path)}:{name}", args=args)
                except Exception as e:
                    print(f"{FLRed}ERROR{CRst}: 显示数组 {name} 失败: {e}")


def _build_arg_parser():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Display 1D/2D arrays from .npy or .npz files.",
        epilog=help_message,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("npy_file_path", nargs="?", help="Path to .npy or .npz file")
    parser.add_argument("--color", help="1D line/point color")
    parser.add_argument(
        "--mode",
        choices=[item.value for item in DisplayMode],
        help="1D display mode",
    )
    parser.add_argument(
        "--line-shape",
        dest="line_shape",
        choices=[item.value for item in LineShape],
        help="1D line shape",
    )
    parser.add_argument(
        "--max-display-size",
        dest="max_display_size",
        type=_parse_max_display_size,
        help="Maximum displayed length/edge before sampling",
    )
    parser.add_argument(
        "--force-plt",
        "--force-matplotlib",
        dest="force_plt",
        action="store_true",
        help="Use matplotlib directly instead of trying plotly first",
    )
    
    view_group = parser.add_mutually_exclusive_group()
    view_group.add_argument("--3d", dest="view_mode", action="store_const", const="3d", help="Show 2D array as 3D surface")
    view_group.add_argument("--2d", dest="view_mode", action="store_const", const="2d", help="Show 2D array as 2D image")
    parser.set_defaults(view_mode=None)
    
    parser.add_argument("--color-scale", dest="color_scale", help="2D color scale/cmap name")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    file_path = args.npy_file_path
    print(f"{FLYellow}================== NPY/NPZ Interactive Viewer =================={CRst}")
    if not file_path:
        file_path = input(f"{FLYellow}请输入 .npy/.npz 文件路径: {CRst}").strip().strip('"')
        if not file_path:
            print(f"{FLRed}ERROR{CRst}: 未输入文件路径")
            return 1
    
    if not os.path.isfile(file_path):
        print(f"{FLRed}ERROR{CRst}: 文件不存在: {file_path}")
        return 1
    
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".npz":
            _show_npz_interactive(file_path, args)
        elif ext == ".npy":
            array = np.load(file_path, allow_pickle=False)
            _show_array(array, title=os.path.basename(file_path), args=args)
        else:
            print(f"{FLRed}ERROR{CRst}: 仅支持 .npy 或 .npz 文件")
            return 1
    except Exception as e:
        print(f"{FLRed}ERROR{CRst}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    
    raise sys.exit(main())
