"""Official small ONNX model catalog and cancellable, verified local storage."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

import httpx
import yaml
from utils import ConfigStore
from ..common.task_control import TaskControl

# Stable settings IDs map to RapidOCR's versioned recognition routes.
EXTENSIONS = {
    "korean": ("Korean", "korean"),
    "latin": ("Latin languages (v5)", "latin"),
    "east_slavic": ("East Slavic", "eslav"),
    "greek": ("Greek", "el"),
    "cyrillic": ("Cyrillic languages", "cyrillic"),
    "arabic": ("Arabic", "arabic"),
    "thai": ("Thai", "th"),
    "devanagari": ("Devanagari (Hindi, etc.)", "devanagari"),
    "tamil": ("Tamil", "ta"),
    "telugu": ("Telugu", "te"),
}


@dataclass(frozen=True)
class Model:
    """One trusted registry entry; URLs and hashes come from the installed package."""

    key: str
    title: str
    version: str
    url: str
    sha256: str
    bundled: bool = False

    @property
    def filename(self) -> str:
        name = urlsplit(self.url).path.rsplit("/", 1)[-1]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.onnx", name):
            raise ValueError("Invalid model filename in the RapidOCR registry.")
        return name


def cache_directory() -> Path:
    """Return the shared user model cache, independent of the Python installation."""
    return ConfigStore.directory() / "models" / "pdf-ocr"


def package_directory() -> Path:
    """Find package-owned metadata and read-only bundled ONNX files."""
    import rapidocr
    return Path(rapidocr.__file__).parent


def catalog() -> dict[str, Model]:
    """Read the installed RapidOCR registry offline; do not load inference sessions."""
    data = yaml.safe_load((package_directory() / "default_models.yaml").read_text(encoding="utf-8"))
    result: dict[str, Model] = {}

    def add(key: str, title: str, version: str, task: str, route: str, bundled: bool = False) -> None:
        entry = data["onnxruntime"][version][task][route]
        url, digest = str(entry["model_dir"]), str(entry["SHA256"]).lower()
        if urlsplit(url).scheme != "https" or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid model URL or checksum in the RapidOCR registry.")
        result[key] = Model(key, title, version, url, digest, bundled)

    add("detector", "Text detector (small)", "PP-OCRv6", "det", "multi_PP-OCRv6_det_small", True)
    add("cjk", "Chinese / English / Japanese / Latin (small)", "PP-OCRv6", "rec", "multi_PP-OCRv6_rec_small", True)
    add("classifier", "Text angle classifier", "PP-OCRv4", "cls", "ch_ppocr_mobile_v2.0_cls_mobile", True)
    for key, (title, route) in EXTENSIONS.items():
        add(key, title, "PP-OCRv5", "rec", f"{route}_PP-OCRv5_rec_mobile")
    return result


def model_path(model: Model) -> Path:
    """Reject redirected cache entries before reading, replacing or deleting them."""
    if model.bundled:
        return package_directory() / "models" / model.filename
    root = cache_directory()
    path = root / model.filename
    if root.is_symlink() or root.is_junction() or path.is_symlink() or path.is_junction():
        raise ValueError("Model cache entries must not be symbolic links or junctions.")
    if path.resolve().parent != root.resolve():
        raise ValueError("Model path is outside the model cache.")
    return path


def verify(model: Model, control: TaskControl) -> Path:
    """Return a local model only after checking the official SHA-256 checksum."""
    path = model_path(model)
    if not path.is_file():
        raise FileNotFoundError(f"Missing model: {model.title}. Open Manage models and download it first.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            control.checkpoint()
            digest.update(chunk)
    if digest.hexdigest() != model.sha256:
        raise ValueError(f"Checksum mismatch: {model.title}. " +
                         ("Repair the RapidOCR installation." if model.bundled else "Delete and download this model again in Manage models."))
    return path


def download(model: Model, control: TaskControl) -> Path:
    """Stage a download; publish atomically only after checksum and cancellation checks.

    Incomplete downloads are removed. Existing files survive failures and Stop.
    Network reads have a 10-second inactivity timeout; Pause/Stop act per chunk.
    """
    if model.bundled:
        raise ValueError("Bundled models are read-only; repair the RapidOCR installation instead.")
    destination = model_path(model)
    destination.parent.mkdir(parents=True, exist_ok=True)
    control.checkpoint()
    with tempfile.TemporaryDirectory(prefix=".download-", dir=destination.parent) as folder:
        staged = Path(folder) / model.filename
        digest = hashlib.sha256()
        received = 0
        with httpx.stream("GET", model.url, follow_redirects=True, timeout=10.,
                          headers={"Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            length = response.headers.get("content-length", "")
            total = int(length) if length.isdigit() else 0
            with staged.open("wb") as stream:
                for chunk in response.iter_bytes(64 * 1024):
                    control.checkpoint()
                    stream.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    control.progress({"kind": "progress", "stage": f"Downloading {model.title}: {received / 1048576:.1f} MiB",
                                      "done": min(100, received * 100 // total) if total else 0,
                                      "total": 100 if total else 0})
        if digest.hexdigest() != model.sha256:
            raise ValueError(f"Download checksum mismatch: {model.title}. The previous model was kept; retry the download.")
        control.checkpoint()
        model_path(model)  # Recheck before publication.
        staged.replace(destination)
    return destination


def delete(model: Model) -> None:
    """Delete only the selected extension's file, never package data or directories."""
    if model.bundled:
        raise ValueError("Bundled models are read-only.")
    model_path(model).unlink(missing_ok=True)


def inventory() -> list[dict[str, str | int | bool]]:
    """Report local sizes without network traffic or expensive hashing."""
    rows: list[dict[str, str | int | bool]] = []
    for model in catalog().values():
        try:
            path = model_path(model)
            size = path.stat().st_size if path.is_file() else 0
            state = "Bundled" if model.bundled and size else "Downloaded" if size else "Not installed"
        except (OSError, ValueError) as exc:
            path, size, state = Path(model.filename), 0, str(exc)
        rows.append({"key": model.key, "title": model.title, "version": model.version,
                     "bundled": model.bundled, "size": size, "status": state,
                     "path": str(path), "url": model.url, "sha256": model.sha256})
    return rows
