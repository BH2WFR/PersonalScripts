"""Worker-side preview publishing without importing the Qt GUI framework."""

import base64
from multiprocessing.shared_memory import SharedMemory

from .protocol import Json


def preview_reply(metadata: dict[str, Json], pixels: bytes, request: dict[str, Json]) -> dict[str, Json]:
    """Publish RGB bytes to a shared slot, or base64 PNG for headless callers.

    Args:
        metadata: Preview dimensions, page number and tool-specific metadata.
        pixels: Packed RGB if pixel_buffer is set, otherwise encoded PNG bytes.
        request: Original request, optionally containing a shared-memory name.

    Returns:
        JSON-safe reply with transport information and the request revision.
    Raises:
        ValueError: Buffer name is invalid or the supplied slot is too small.
        OSError: The caller's shared-memory segment cannot be opened.
    """
    response = {**metadata, "revision": request.get("revision")}
    if name := request.get("pixel_buffer"):
        if not isinstance(name, str):
            raise ValueError("Preview buffer must be a shared-memory name.")
        memory = SharedMemory(name=name, track=False)
        try:
            if len(pixels) > memory.size:
                raise ValueError("Preview buffer is too small.")
            memory.buf[:len(pixels)] = pixels
        finally:
            memory.close()
        response["pixel_buffer"] = name
    else:
        response["png"] = base64.b64encode(pixels).decode("ascii")
    return response
