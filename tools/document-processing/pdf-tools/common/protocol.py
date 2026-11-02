"""JSON value type shared by project files and isolated worker messages."""

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]

MAX_PREVIEW_PIXELS = 16_000_000
PREVIEW_BUFFER_BYTES = MAX_PREVIEW_PIXELS * 3
