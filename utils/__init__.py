import os
import sys
import typing
import string
import math
import json
import enum
import random
import time
import datetime
import copy
import shutil
import subprocess
import ctypes
import pathlib

#* 控制台颜色
# Foreground (text) colors
FBlack     = "\033[30m"
FRed       = "\033[31m"
FGreen     = "\033[32m"
FYellow    = "\033[33m"
FBlue      = "\033[34m"
FMagenta   = "\033[35m"
FCyan      = "\033[36m"
FWhite     = "\033[37m"

FLBlack    = "\033[90m"
FGray      = "\033[90m"
FLRed      = "\033[91m"
FLGreen    = "\033[92m"
FLYellow   = "\033[93m"
FLBlue     = "\033[94m"
FLMagenta  = "\033[95m"
FLCyan     = "\033[96m"
FLWhite    = "\033[97m"

# Background colors
BBlack     = "\033[40m"
BRed       = "\033[41m"
BGreen     = "\033[42m"
BYellow    = "\033[43m"
BBlue      = "\033[44m"
BMagenta   = "\033[45m"
BCyan      = "\033[46m"
BWhite     = "\033[47m"

BGray      = "\033[100m"
BLBlack    = "\033[100m"
BLRed      = "\033[101m"
BLGreen    = "\033[102m"
BLYellow   = "\033[103m"
BLBlue     = "\033[104m"
BLMagenta  = "\033[105m"
BLCyan     = "\033[106m"
BLWhite    = "\033[107m"

# styles
CBold       = "\033[1m"
CWeak       = "\033[2m"
CItalic     = "\033[3m"
CUnderline  = "\033[4m"
CFlash      = "\033[5m"
CQFlash     = "\033[6m"
CInverse    = "\033[7m"
CHidden     = "\033[8m"

# Reset
FDefault    = "\033[39m"
BDefault    = "\033[49m"
CRst        = "\033[0m"

# Cursor / screen control
CCursorHome             = f"\033[H"
CCursorSave             = "\0337"
CCursorRestore          = "\0338"
CCursorHide             = f"\033[?25l"
CCursorShow             = f"\033[?25h"

CEraseDisplay           = f"\033[2J"
CEraseDisplayToEnd      = f"\033[J"
CEraseDisplayToStart    = f"\033[1J"
CEraseDisplayAllScroll  = f"\033[3J"

CEraseLine              = f"\033[2K"
CEraseLineToEnd         = f"\033[K"
CEraseLineToStart       = f"\033[1K"





#* 轮子
class Utils:
    @staticmethod
    def get_time_str():
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    @staticmethod
    def print_error_and_exit(msg, code=1):
        print(f"{FLRed}Error: {msg}{CRst}")
        exit(code)
    
    @staticmethod
    def console_command_required(exe_name: str) -> str:
        p = shutil.which(exe_name)
        if not p:
            print(f"{FLRed}ERROR: `{exe_name}` not found in PATH. {CRst}"
                f"Please install it (scoop install {exe_name}) or add it to PATH.\033[0m")
            sys.exit(1)
        return p
    
    @staticmethod
    def set_locale_utf8():
        if os.name == 'nt':
            os.system('chcp 65001')  #* Windows 上设置控制台为 UTF-8 编码
            # Windows 上设置 UTF-8 locale (>= windows 10 1903)
            try:
                import locale
                locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
            except Exception as e:
                print(f"{FLRed}Warning: Failed to set locale to UTF-8: {str(e)}{CRst}")
    
    @staticmethod
    def print_argv_list():
        print(f"{FLYellow}Command line arguments:{CRst}")
        for i, arg in enumerate(sys.argv):
            print(f"  argv[{FLYellow}{i}{CRst}]: {FLCyan}{arg}{CRst}")
    
    
    @staticmethod
    def enable_dpi_awareness() -> None:
        if sys.platform != "win32":
            return

        user32 = ctypes.windll.user32
        # Windows 10+ 推荐：Per Monitor V2
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
            if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                return
        except Exception:
            pass

        # Win8.1 回退
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            return
        except Exception:
            pass

        # 更老系统回退
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


class Cursor:
    @staticmethod
    def up(count: int = 1) -> str:
        return f"\033[{max(1, count)}A"

    @staticmethod
    def down(count: int = 1) -> str:
        return f"\033[{max(1, count)}B"
        
    @staticmethod
    def forward(count: int = 1) -> str:
        return f"\033[{max(1, count)}C"
        
    @staticmethod
    def back(count: int = 1) -> str:
        return f"\033[{max(1, count)}D"
        
    @staticmethod
    def next_line(count: int = 1) -> str:
        return f"\033[{max(1, count)}E"
        
    @staticmethod
    def prev_line(count: int = 1) -> str:
        return f"\033[{max(1, count)}F"
        
    @staticmethod
    def column(column: int = 1) -> str:
        return f"\033[{max(1, column)}G"
        
    @staticmethod
    def position(row: int = 1, column: int = 1) -> str:
        return f"\033[{max(1, row)};{max(1, column)}H"
        
    @staticmethod
    def erase_display(mode: int = 2) -> str:
        return f"\033[{mode}J"
        
    @staticmethod
    def erase_line(mode: int = 2) -> str:
        return f"\033[{mode}K"
        
    @staticmethod
    def scroll_up(count: int = 1) -> str:
        return f"\033[{max(1, count)}S"
        
    @staticmethod
    def scroll_down(count: int = 1) -> str:
        return f"\033[{max(1, count)}T"
