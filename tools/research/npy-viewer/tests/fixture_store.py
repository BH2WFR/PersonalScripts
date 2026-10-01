"""Keep automated viewer fixtures in the project's Git-ignored scratch tree.

Requirements: numpy. Usage: fixture_directory() for file-based fixtures;
preserve_array()/preserve_document() for inputs otherwise held only in memory.
Content-addressed NPY snapshots retain distinct variants without duplicating
identical data on subsequent test runs. The application's test-matrixes folder
is reserved for small, curated manual samples and is never written by tests.
"""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

FIXTURE_ROOT = Path(__file__).resolve().parents[4] / "tmp" / "npy-viewer-tests"


class ArrayDocument(Protocol):
    """Read-only source attributes required for preserving a viewer document."""

    @property
    def path(self) -> Path:
        """Return the source label used for naming its snapshot."""
        ...

    @property
    def array(self) -> NDArray[np.generic]:
        """Return the unchanged numeric source array."""
        ...


def fixture_directory(group: str) -> Path:
    """Create an automated fixture group below tmp/npy-viewer-tests.

    Args:
        group: Relative group path, such as gui or unit/test_mat_loading.

    Returns:
        Absolute directory path. Existing contents are retained.

    Raises:
        ValueError: The group escapes the fixture root.
        OSError: The directory cannot be created.
    """
    root = FIXTURE_ROOT.resolve()
    directory = (root / group).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("Fixture groups must stay inside the automated test scratch directory.")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def preserve_array[T: np.generic](values: NDArray[T], name: str, group: str) -> NDArray[T]:
    """Save an exact NPY snapshot and return the original, unmodified array.

    Args:
        values: Numeric test input, including deliberate empty/high-rank cases.
        name: Descriptive base filename; path components are discarded.
        group: Relative directory within the ignored automated fixture root.

    Returns:
        The same array object, so source identity and precision tests still work.

    Raises:
        ValueError: Object data would require pickle serialization.
        OSError: The fixture cannot be written.

    Side effects:
        Creates one content-addressed NPY file for each distinct input variant.
        Existing files are never replaced or deleted.
    """
    stream = BytesIO()
    np.save(stream, values, allow_pickle=False)
    payload = stream.getvalue()
    digest = sha256(payload).hexdigest()[:16]
    target = fixture_directory(group) / f"{Path(name).stem}-{digest}.npy"
    if not target.exists():
        with target.open("xb") as output:
            output.write(payload)
    elif target.read_bytes() != payload:
        raise ValueError(f"Fixture contents do not match their digest: {target}")
    return values


def preserve_document[T: ArrayDocument](document: T, group: str) -> T:
    """Persist an in-memory document without changing its path, values or type.

    Args:
        document: Viewer document constructed by a test.
        group: Relative scratch directory for the test's input matrices.

    Returns:
        The unchanged document, after preserving its source array as NPY.

    Raises:
        ValueError: Unsupported object serialization or an invalid group.
        OSError: The snapshot cannot be written.
    """
    preserve_array(document.array, document.path.name, group)
    return document
