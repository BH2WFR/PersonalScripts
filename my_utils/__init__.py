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
BLYellow    = "\033[103m"
FLGreen     = "\033[32m"
FLCyan      = "\033[36m"
FLRed       = "\033[31m"
FLYellow    = "\033[33m"
FLMagenta   = "\033[35m"
FLBlue      = "\033[34m"
CRst        = "\033[0m"


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
