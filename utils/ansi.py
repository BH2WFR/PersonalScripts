"""ANSI color, style, cursor, and screen-control escape constants."""


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



