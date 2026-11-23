"""Win32 SendInput packet construction and balanced batch delivery."""

import ctypes as C
from ctypes import wintypes as W

KEYUP = 0x0002
SCANCODE = 0x0008
EXTENDED = 0x0001


class _KeyboardInput(C.Structure):
    _fields_ = [("vk", W.WORD), ("scan", W.WORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("extra", C.c_size_t)]


class _MouseInput(C.Structure):
    _fields_ = [("x", W.LONG), ("y", W.LONG), ("data", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("extra", C.c_size_t)]


class InputData(C.Union):
    _fields_ = [("keyboard", _KeyboardInput), ("mouse", _MouseInput)]


class InputPacket(C.Structure):
    _fields_ = [("kind", W.DWORD), ("data", InputData)]


def keyboard_packet(scan: int, flags: int, vk: int = 0) -> InputPacket:
    """Create a keyboard INPUT record with a scan word or a virtual key."""
    return InputPacket(1, InputData(keyboard=_KeyboardInput(vk, scan, flags, 0, 0)))


class WindowsInput:
    """Submit a batch in order and release accepted downs on a partial write."""

    def __init__(self) -> None:
        self.api = C.WinDLL("user32", use_last_error=True)
        self.api.SendInput.argtypes = [W.UINT, C.POINTER(InputPacket), C.c_int]
        self.api.SendInput.restype = W.UINT

    def send_packets(self, packets: list[InputPacket]) -> None:
        """Raise RuntimeError if Windows rejects any of the requested events."""
        events = (InputPacket * len(packets))(*packets)
        sent = self.api.SendInput(len(events), events, C.sizeof(InputPacket))
        if sent == len(events):
            return
        held: dict[tuple[int, int, int], None] = {}
        for packet in packets[:sent]:
            key = packet.data.keyboard
            identity = (key.scan, key.flags & ~KEYUP, key.vk)
            if key.flags & KEYUP:
                held.pop(identity, None)
            else:
                held[identity] = None
        for scan, flags, vk in reversed(held):
            up = keyboard_packet(scan, flags | KEYUP, vk)
            self.api.SendInput(1, C.byref(up), C.sizeof(InputPacket))
        raise RuntimeError("Windows rejected keyboard input. Check the target window's privilege level.")
