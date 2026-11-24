#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import *

HELP = """ARGUMENT PRINTING TOOL

Show the interpreter, script path and arguments received by Python.

Requirements:
  Python 3.13+.

Usage:
  python print-argv.py [ARG ...]
"""

def main() -> int:
    Console.initialize_ansi_output()
    if sys.argv[1:] in (["--help"], ["-h"]):
        print(HELP)
        return 0
    Console.print_banner("ARGUMENT PRINTING TOOL")
    print(f"  {FLCyan}Interpreter:{CRst}  {FLGreen}Python{CRst}  {FGray}{sys.executable}{CRst}")
    Console.print_argv_list()
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
