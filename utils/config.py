"""Shared user YAML configuration, redirects and encrypted string values.

ConfigStore uses PyYAML; encrypted values additionally require cryptography.
Imports are lazy. Callers own filenames and encryption keys. EncryptedValue
keeps ciphertext opaque until its owning module explicitly decrypts it.
Reads and writes take a short nonblocking lock; contention raises ConfigBusyError.
"""

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Iterator, TextIO

APP_DIRECTORY_NAME = "PersonalScripts"
CONFIG_PARENT_NAME = ".config"
GENERAL_CONFIG = "config.yaml"
_THREAD_LOCKS: dict[str, threading.Lock] = {}


class ConfigBusyError(BlockingIOError):
    """The requested file is busy; no retry or partial operation was performed."""

    status = "busy"


@dataclass(frozen=True)
class EncryptedValue:
    """Opaque !encrypted ciphertext; the owning module supplies its own key."""

    token: str = field(repr=False)

    def __repr__(self) -> str:
        return "EncryptedValue(<redacted>)"

    @staticmethod
    def encrypt(text: str, key: bytes) -> "EncryptedValue":
        from cryptography.fernet import Fernet
        return EncryptedValue(Fernet(key).encrypt(text.encode("utf-8")).decode("ascii"))

    def decrypt(self, key: bytes) -> str:
        from cryptography.fernet import Fernet, InvalidToken
        try:
            return Fernet(key).decrypt(self.token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise ValueError("Cannot decrypt an encrypted configuration value.") from exc

    @staticmethod
    def decrypt_tree(value: Any, key: bytes) -> Any:
        """Decode a module-owned section/schema, preserving unrelated plain values."""
        if isinstance(value, EncryptedValue):
            return value.decrypt(key)
        if isinstance(value, dict):
            return {name: EncryptedValue.decrypt_tree(item, key) for name, item in value.items()}
        if isinstance(value, list):
            return [EncryptedValue.decrypt_tree(item, key) for item in value]
        return value


class ConfigStore:
    """Own one named user config; file locks exist only during individual I/O calls."""

    def __init__(self, name: str = GENERAL_CONFIG) -> None:
        if "/" in name or "\\" in name or Path(name).name != name or not name.endswith(".yaml"):
            raise ValueError("Configuration names must be plain .yaml filenames.")
        self.name = name

    @staticmethod
    def directory() -> Path:
        """Return the same ~/.config/application directory on every platform."""
        return Path.home() / CONFIG_PARENT_NAME / APP_DIRECTORY_NAME

    @staticmethod
    def initialize() -> None:
        """Create only the general config; application modules own their own files."""
        ConfigStore().ensure()

    @property
    def path(self) -> Path:
        return self.directory() / self.name

    @staticmethod
    def parse(stream: str | TextIO) -> Any:
        """Safe YAML with encrypted strings and duplicate explicit-key rejection.

        YAML merge-key overrides remain supported. Raises yaml.YAMLError for
        syntax/duplicate keys. Encrypted values remain opaque; no key is held here.
        """
        import yaml

        class Loader(yaml.SafeLoader):
            def __init__(self, source: str | TextIO) -> None:
                super().__init__(source)
                self.checked_mappings: set[yaml.MappingNode] = set()

            def flatten_mapping(self, node: yaml.MappingNode) -> None:
                if node not in self.checked_mappings:
                    self.checked_mappings.add(node)
                    marks: dict[object, yaml.error.Mark] = {}
                    for key_node, _ in node.value:
                        key = key_node.value if key_node.tag in {
                            "tag:yaml.org,2002:merge", "tag:yaml.org,2002:value"
                        } else self.construct_object(key_node, deep=True)
                        try:
                            first = marks.get(key)
                            if first is not None:
                                raise yaml.constructor.ConstructorError(
                                    "first key defined here", first,
                                    f"duplicate YAML key {key!r}", key_node.start_mark)
                            marks[key] = key_node.start_mark
                        except TypeError as exc:
                            raise yaml.constructor.ConstructorError(
                                "while reading a mapping", node.start_mark,
                                "mapping keys must be hashable", key_node.start_mark) from exc
                super().flatten_mapping(node)

        def encrypted_value(loader: yaml.SafeLoader, node: yaml.Node) -> EncryptedValue:
            if not isinstance(node, yaml.ScalarNode):
                raise yaml.constructor.ConstructorError(
                    None, None, "!encrypted requires a scalar value", node.start_mark)
            return EncryptedValue(loader.construct_scalar(node))

        Loader.add_constructor("!encrypted", encrypted_value)
        return yaml.load(stream, Loader=Loader)

    @staticmethod
    def read_file(path: Path) -> dict[str, Any]:
        """Read under a nonblocking lock. Empty YAML is {}; missing files raise."""
        if not path.parent.exists():
            raise FileNotFoundError(path)
        with ConfigStore._locked_path(path):
            return ConfigStore._read_file(path)

    @staticmethod
    def _read_file(path: Path) -> dict[str, Any]:
        """Parse while the caller owns the file lock; never acquire it recursively."""
        import yaml
        try:
            with path.open(encoding="utf-8") as source:
                data = ConfigStore.parse(source)
        except (yaml.YAMLError, UnicodeError) as exc:
            raise ValueError(f"Invalid YAML configuration: {path}") from exc
        if data is None:
            return {}
        if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
            raise ValueError(f"Configuration must contain a string-keyed mapping: {path}")
        return data

    @staticmethod
    def resolve_file(path: Path) -> Path:
        """Follow redirect-only mappings, resolving each relative path at its file.

        Reject missing targets, mixed redirect/data files, cycles and chains
        longer than 16 files. Returns the final path for schema_dir semantics.
        """
        seen: set[Path] = set()
        for _ in range(16):
            path = path.expanduser().resolve()
            if path in seen:
                raise ValueError(f"Configuration redirect cycle: {path}")
            seen.add(path)
            data = ConfigStore.read_file(path)
            if "redirect" not in data:
                return path
            target = data["redirect"]
            if len(data) != 1 or not isinstance(target, str) or not target.strip():
                raise ValueError(f"redirect must be the only key and name a nonempty path: {path}")
            destination = Path(os.path.expandvars(target)).expanduser()
            path = destination if destination.is_absolute() else path.parent / destination
        raise ValueError("Configuration redirect chain exceeds 16 files.")

    def load(self) -> dict[str, Any]:
        """Read this store; absent/empty configs are empty mappings. Never repair silently."""
        try:
            return self.read_file(self.path)
        except FileNotFoundError:
            return {}

    @staticmethod
    @contextmanager
    def _locked_path(path: Path) -> Iterator[None]:
        """Try once across threads/processes, releasing before any UI or processing."""
        path = path.resolve()
        thread_lock = _THREAD_LOCKS.setdefault(os.path.normcase(str(path)), threading.Lock())
        if not thread_lock.acquire(blocking=False):
            raise ConfigBusyError(f"Configuration is busy: {path}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.with_suffix(".yaml.lock").open("a+b") as lock:
                with ConfigStore._file_lock(lock, path):
                    yield
        finally:
            thread_lock.release()

    @staticmethod
    @contextmanager
    def _file_lock(lock: Any, path: Path) -> Iterator[None]:
        """Keep the stable sidecar inode; its existence never indicates occupancy."""
        try:
            if os.name == "nt":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ConfigBusyError(f"Configuration is busy: {path}") from exc
        try:
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b"\0")
                lock.flush()
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _write(self, data: dict[str, Any]) -> None:
        import yaml

        class Dumper(yaml.SafeDumper):
            pass

        def encrypt(dumper: Dumper, value: EncryptedValue) -> yaml.ScalarNode:
            return dumper.represent_scalar("!encrypted", value.token)

        Dumper.add_representer(EncryptedValue, encrypt)
        content = yaml.dump(data, Dumper=Dumper, allow_unicode=True, sort_keys=False) if data else ""
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                             dir=self.path.parent, prefix=f".{self.name}.", delete=False) as target:
                temporary = Path(target.name)
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def edit(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        """Lock, reread, mutate and atomically replace; failures retain the old file."""
        with self._locked_path(self.path):
            try:
                data = self._read_file(self.path)
            except FileNotFoundError:
                data = {}
            mutate(data)
            self._write(data)

    def update(self, changes: Mapping[str, Any]) -> None:
        """Deep-merge changed mapping fields; replace lists/scalars and preserve unknown keys."""
        def merge(target: dict[str, Any], values: Mapping[str, Any]) -> None:
            for key, value in values.items():
                if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                    merge(target[key], value)
                else:
                    target[key] = value
        self.edit(lambda data: merge(data, changes))

    def ensure(self, initial: Mapping[str, Any] | None = None) -> None:
        """Create a missing config only; preserve existing bytes, including malformed YAML."""
        with self._locked_path(self.path):
            if not self.path.exists():
                self._write(dict(initial or {}))
