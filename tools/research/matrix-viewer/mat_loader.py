"""Read ordinary numeric MATLAB variables from legacy and v7.3 MAT files.

Requirements: numpy, scipy and h5py. Usage: read_mat(path, optional_variable).
Only the selected variable is read into memory. MATLAB row/column shapes,
numeric precision and complex components are preserved. Containers, sparse
arrays are rejected explicitly. Numeric rank 3 is accepted only for explicit
split import; nonempty 1D/2D MATLAB char arrays are exposed as raw-only strings.
MATLAB string objects/cells remain unsupported. v7.3 char storage retains UTF-16
code-unit positions; unpaired surrogate cells are escaped in the raw table.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import h5py
import numpy as np
from numpy.typing import NDArray
from scipy.io import loadmat, whosmat

from .array_validation import validate_shape, validate_source_array

MAT_DTYPES: dict[str, np.dtype[np.generic]] = {
    name: np.dtype(dtype) for name, dtype in (
        ("double", "float64"), ("single", "float32"), ("logical", "uint8"),
        ("int8", "int8"), ("uint8", "uint8"), ("int16", "int16"), ("uint16", "uint16"),
        ("int32", "int32"), ("uint32", "uint32"), ("int64", "int64"), ("uint64", "uint64"),
    )
}
MAX_ERROR_VARIABLES = 12


@dataclass(frozen=True)
class MatMember:
    """Top-level variable metadata; an error marks an unsupported member."""

    name: str
    shape: tuple[int, ...]
    kind: str
    error: str = ""


def inspect_mat(path: Path, *, allow_3d: bool = False) -> tuple[MatMember, ...]:
    """Read names/shapes/types without loading MATLAB variable arrays.

    Args:
        path: Legacy or v7.3 MAT file.
        allow_3d: Offer rank-3 variables for explicit channel splitting.

    Returns:
        Metadata for all top-level user variables, including unsupported ones.

    Raises:
        ValueError/OSError: Damaged or unreadable metadata.
    """
    if h5py.is_hdf5(path):
        with h5py.File(path, "r") as archive:
            return _hdf_members(archive, allow_3d=allow_3d)
    metadata = cast(list[tuple[str, tuple[int, ...], str]], whosmat(str(path), appendmat=False))
    return tuple(MatMember(name, shape, kind, _metadata_problem(name, shape, kind, allow_3d=allow_3d) or "")
                 for name, shape, kind in metadata)


@dataclass(frozen=True)
class MatData:
    """Selected array, all top-level variable names and the selected name."""

    values: NDArray[np.generic]
    keys: tuple[str, ...]
    key: str


def _choose_variable(problems: dict[str, str | None], key: str | None) -> str:
    if not problems:
        raise ValueError("The MAT file contains no variables.")
    if key is not None:
        if key not in problems:
            raise ValueError(f"MAT variable {key!r} does not exist. Available: {', '.join(problems)}")
        if problems[key] is not None:
            raise ValueError(problems[key])
        return key
    for name, problem in problems.items():
        if problem is None:
            return name
    reasons = "\n".join(str(problem) for problem in list(problems.values())[:MAX_ERROR_VARIABLES])
    remainder = len(problems) - MAX_ERROR_VARIABLES
    if remainder > 0:
        reasons = f"{reasons}\n... and {remainder} more unsupported variables."
    raise ValueError(f"The MAT file contains no supported nonempty 1D/2D numeric arrays.\n{reasons}")


def _metadata_problem(name: str, shape: tuple[int, ...], matlab_class: str, *, allow_3d: bool = False) -> str | None:
    label = f"MAT variable {name!r}"
    if matlab_class not in MAT_DTYPES and matlab_class != "char":
        return (f"{label}: unsupported MATLAB type {matlab_class!r}. "
                "Only dense numeric/logical arrays are supported; "
                "cell, struct, sparse, text and MATLAB objects are not supported.")
    try:
        validate_shape(shape, label, allow_3d=allow_3d and matlab_class != "char")
    except ValueError as exc:
        return str(exc)
    return None


def _matlab_class(node: h5py.Dataset | h5py.Group) -> str:
    value: object = node.attrs.get("MATLAB_class", "")
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace")
    return value if isinstance(value, str) else ""


def _hdf_problem(node: object, name: str, *, allow_3d: bool = False) -> str | None:
    label = f"MAT variable {name!r}"
    if not isinstance(node, (h5py.Dataset, h5py.Group)):
        return f"{label}: missing or unreadable HDF5 data."
    if "MATLAB_sparse" in node.attrs:
        return f"{label}: sparse matrices are not supported. Save a dense array with full(A)."
    matlab_class = _matlab_class(node)
    if not isinstance(node, h5py.Dataset):
        return f"{label}: unsupported MATLAB container/type {matlab_class or 'HDF5 group'!r}."
    empty_flag = np.asarray(node.attrs.get("MATLAB_empty", 0))
    if empty_flag.size != 1 or bool(empty_flag.reshape(-1)[0]):
        return f"{label}: empty arrays are not supported (MATLAB_empty)."
    if node.shape is None:
        return f"{label}: empty HDF5 dataset."
    shape = tuple(reversed(node.shape))
    problem = _metadata_problem(name, shape, matlab_class or "missing MATLAB_class metadata", allow_3d=allow_3d)
    if problem is not None:
        return problem
    dtype = np.dtype(node.dtype)
    if matlab_class == "char":
        return None if dtype.kind == "u" and dtype.itemsize == 2 else f"{label}: unsupported character storage {dtype}; expected UTF-16 code units."
    expected = MAT_DTYPES[matlab_class]
    if dtype.fields is not None:
        if (matlab_class not in ("single", "double") or dtype.names != ("real", "imag")
                or any(dtype.fields[field][0].newbyteorder("=") != expected for field in ("real", "imag"))):
            return f"{label}: unsupported complex/structured storage dtype={dtype}."
    elif dtype.newbyteorder("=") != expected:
        return f"{label}: storage dtype={dtype} does not match MATLAB type {matlab_class!r}."
    return None


def _hdf_members(archive: h5py.File, *, allow_3d: bool = False) -> tuple[MatMember, ...]:
    """Inspect local HDF5 nodes only; never follow external/soft links."""
    members: list[MatMember] = []
    for name in archive:
        if not isinstance(name, str):
            raise ValueError("The MAT file contains an invalid HDF5 variable name; expected text.")
        if name.startswith("#"):
            continue
        if not isinstance(archive.get(name, getlink=True), h5py.HardLink):
            members.append(MatMember(name, (), "linked", f"MAT variable {name!r}: linked HDF5 datasets are not supported."))
            continue
        node = archive[name]
        shape = tuple(reversed(node.shape)) if isinstance(node, h5py.Dataset) and node.shape is not None else ()
        kind = _matlab_class(node) if isinstance(node, (h5py.Dataset, h5py.Group)) else "unknown"
        members.append(MatMember(name, shape, kind, _hdf_problem(node, name, allow_3d=allow_3d) or ""))
    return tuple(members)


def _read_hdf(path: Path, key: str | None, *, allow_3d: bool = False) -> MatData:
    with h5py.File(path, "r") as archive:
        problems = {item.name: item.error or None for item in _hdf_members(archive, allow_3d=allow_3d)}
        selected = _choose_variable(problems, key)
        dataset = archive[selected]
        if not isinstance(dataset, h5py.Dataset):
            raise ValueError(f"MAT variable {selected!r} is not a numeric dataset.")
        values = np.asarray(dataset[()])
        matlab_class = _matlab_class(dataset)
        if values.dtype.fields is not None:
            # Assign components separately, avoiding precision changes and
            # spurious NaNs from arithmetic on infinite imaginary components.
            complex_dtype = np.complex64 if matlab_class == "single" else np.complex128
            complex_values = np.empty(values.shape, dtype=complex_dtype)
            complex_values.real = values["real"]
            complex_values.imag = values["imag"]
            values = complex_values
        elif matlab_class == "logical":
            values = values.astype(np.bool_)
        # MATLAB's HDF5 dimension order is reversed relative to NumPy. Keep
        # singleton axes, especially 1xN/Nx1 vectors, for raw-data fidelity.
        values = values.transpose()
        if matlab_class == "char":
            values = np.fromiter((chr(int(code)) for code in values.flat), dtype="U1", count=values.size).reshape(values.shape)
        return MatData(validate_source_array(values, f"MAT variable {selected!r}", allow_3d=allow_3d), tuple(problems), selected)


def read_mat(path: Path, key: str | None = None, *, allow_3d: bool = False) -> MatData:
    """Load one supported variable from a legacy or HDF5-based MAT file.

    Args:
        path: Existing MATLAB MAT file, including v7.3.
        key: Top-level variable name; None selects the first supported array.
        allow_3d: Accept rank 3 only when the caller will split it into matrices.

    Returns:
        Selected numeric data and names for the variable selector. Unsupported
        names remain selectable so the UI can explain why they cannot be read.

    Raises:
        ValueError: Unsupported variables, invalid shapes or malformed MAT data.
        OSError: File access or HDF5 decoding failure.

    Side effects:
        Reads file metadata and the selected variable; closes all file handles.
    """
    if h5py.is_hdf5(path):
        return _read_hdf(path, key, allow_3d=allow_3d)
    try:
        metadata = cast(list[tuple[str, tuple[int, ...], str]], whosmat(str(path), appendmat=False))
    except (ValueError, TypeError, IndexError, OSError, NotImplementedError) as exc:
        raise ValueError(f"Invalid, damaged or unsupported MAT file. MATLAB variable metadata could not be read.\n{exc}") from exc
    problems = {name: _metadata_problem(name, shape, matlab_class, allow_3d=allow_3d) for name, shape, matlab_class in metadata}
    selected = _choose_variable(problems, key)
    decoded = cast(dict[str, object], loadmat(str(path), appendmat=False, variable_names=[selected],
                                            squeeze_me=False, mat_dtype=False, chars_as_strings=False))
    values = validate_source_array(decoded.get(selected), f"MAT variable {selected!r}", allow_3d=allow_3d)
    matlab_class = next(kind for name, _, kind in metadata if name == selected)
    if matlab_class == "logical":
        values = values.astype(np.bool_)
    return MatData(values, tuple(problems), selected)
