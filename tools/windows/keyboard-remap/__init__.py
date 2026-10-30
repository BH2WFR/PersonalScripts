"""Private Windows registry keyboard remapper; importing it has no side effects.

Launch ../keyboard-remap.py. Requires PySide6 only for the GUI; the data model
and registry service use the standard library. No background input logging.
"""

USAGE_NOTICE: str = (
    "Only for legitimate keyboard testing, custom hotkeys and authorized automation. "
    "Capture listens only in the visible capture window; no background logging. "
    "Do not use for covert surveillance, credential collection or unauthorized activity."
)
