"""ANSI cursor movement and screen-control builders."""

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
