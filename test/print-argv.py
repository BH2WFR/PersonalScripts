import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import *

def main() -> int:
    Utils.print_banner("ARGUMENT PRINTING TOOL")
    print(f"  {FLCyan}Interpreter:{CRst}  {FLGreen}Python{CRst}  {FGray}{sys.executable}{CRst}")
    Utils.print_argv_list()
    return 0

if __name__ == "__main__":
    raise sys.exit(main())
