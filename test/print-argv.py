#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import *

def main() -> int:
    Console.print_banner("ARGUMENT PRINTING TOOL")
    print(f"  {FLCyan}Interpreter:{CRst}  {FLGreen}Python{CRst}  {FGray}{sys.executable}{CRst}")
    Console.print_argv_list()
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
