"""Verify encrypted YAML, redirects, atomic failure and concurrent config writers."""

from pathlib import Path
import multiprocessing
from multiprocessing.synchronize import Event
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *

TEST_KEY = b"xCpV9hSbjhOUMC20VRuFO2wCnau5G-vPO_UpBoQejaY="


def increment(directory: str) -> None:
    """Exercise independent processes without touching a real user config."""
    with patch.object(ConfigStore, "directory", return_value=Path(directory)):
        for _ in range(15):
            deadline = time.monotonic() + 5
            while True:
                try:
                    ConfigStore().edit(lambda data: data.update(count=data.get("count", 0) + 1))
                    break
                except ConfigBusyError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.01)  # Explicit caller retry, never inside ConfigStore.


def hold_lock(directory: str, ready: Event, release: Event) -> None:
    """Hold a process lock so the parent can verify immediate read/write failures."""
    with patch.object(ConfigStore, "directory", return_value=Path(directory)):
        with ConfigStore._locked_path(ConfigStore().path):
            ready.set()
            release.wait(10)


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="config-test-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.enterContext(patch.object(ConfigStore, "directory", return_value=self.folder))
        self.store = ConfigStore()

    def test_empty_defaults_and_encrypted_nested_values(self) -> None:
        self.assertEqual(self.store.load(), {})
        self.assertFalse(self.store.path.exists())
        self.store.ensure()
        self.assertEqual(self.store.path.read_bytes(), b"")
        self.store.update({"provider": {"key": EncryptedValue.encrypt("sensitive-test-value", TEST_KEY), "model": "a"}})
        self.assertNotIn(b"sensitive-test-value", self.store.path.read_bytes())
        self.assertIn(b"!encrypted", self.store.path.read_bytes())
        self.assertEqual(self.store.load()["provider"]["key"].decrypt(TEST_KEY), "sensitive-test-value")
        self.store.update({"provider": {"model": "b"}, "unrelated": True})
        self.assertNotIn(b"sensitive-test-value", self.store.path.read_bytes())
        self.assertEqual(self.store.load()["provider"]["key"].decrypt(TEST_KEY), "sensitive-test-value")
        with self.assertRaises(ValueError):
            self.store.load()["provider"]["key"].decrypt(b"PwMoFseUfbszDg3JsbCkGEvKgvFbW9uWKOwmkD-sMZ8=")
        self.assertEqual(EncryptedValue.decrypt_tree(self.store.load(), TEST_KEY)["provider"]["key"], "sensitive-test-value")

    def test_initialize_preserves_existing_files(self) -> None:
        self.store.update({"custom": "keep"})
        before = self.store.path.read_bytes()
        ConfigStore.initialize()
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual([path.name for path in self.folder.glob("*.yaml")], [GENERAL_CONFIG])

    def test_redirects_use_each_containing_directory_and_reject_cycles(self) -> None:
        nested = self.folder / "nested"
        nested.mkdir()
        self.store.update({"redirect": "nested/next.yaml"})
        (nested / "next.yaml").write_text("redirect: final.yaml\n", encoding="utf-8")
        final = nested / "final.yaml"
        final.write_text("tasks: {}\n", encoding="utf-8")
        self.assertEqual(ConfigStore.resolve_file(self.store.path), final)
        final.write_text("redirect: ../config.yaml\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "cycle"):
            ConfigStore.resolve_file(self.store.path)
        final.write_text("redirect: missing.yaml\ntasks: {}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "only key"):
            ConfigStore.resolve_file(final)

    def test_malformed_files_are_not_overwritten_and_ciphertext_is_opaque(self) -> None:
        for text in ("items: [", "key: 1\nkey: 2\n",
                     "key: !encrypted [one, two]\n", "key: !encrypted {token: value}\n"):
            self.store.path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.store.update({"new": True})
            self.assertEqual(self.store.path.read_text(encoding="utf-8"), text)
        self.store.path.write_text("key: !encrypted broken\n", encoding="utf-8")
        self.store.update({"unrelated": True})
        with self.assertRaises(ValueError):
            self.store.load()["key"].decrypt(TEST_KEY)

    def test_busy_reads_and_writes_fail_immediately_and_release(self) -> None:
        self.store.update({"old": True})
        context = multiprocessing.get_context("spawn")
        ready, release = context.Event(), context.Event()
        child = context.Process(target=hold_lock, args=(str(self.folder), ready, release))
        child.start()
        try:
            self.assertTrue(ready.wait(10))
            started = time.monotonic()
            for action in (self.store.load, lambda: self.store.update({"new": True}),
                           lambda: ConfigStore.read_file(self.store.path)):
                with self.assertRaises(ConfigBusyError) as error:
                    action()
                self.assertEqual(error.exception.status, "busy")
            self.assertLess(time.monotonic() - started, .5)
            ConfigStore("other.yaml").update({"independent": True})
        finally:
            release.set()
            child.join(10)
            if child.is_alive():
                child.terminate()
                child.join()
        self.assertEqual(child.exitcode, 0)
        self.assertEqual(self.store.load(), {"old": True})
        self.store.update({"new": True})
        self.assertTrue(self.store.load()["new"])
        with ConfigStore._locked_path(self.store.path):
            with self.assertRaises(ConfigBusyError):
                self.store.load()

    def test_failed_publication_retains_old_config(self) -> None:
        self.store.update({"keep": True})
        original = self.store.path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("test failure")), self.assertRaises(OSError):
            self.store.update({"keep": False})
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(list(self.folder.glob(".config.yaml.*")), [])

    def test_concurrent_writers_merge_latest_values(self) -> None:
        processes = [multiprocessing.get_context("spawn").Process(target=increment, args=(str(self.folder),)) for _ in range(3)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(20)
            if process.is_alive():
                process.terminate()
                process.join()
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(self.store.load()["count"], 45)


if __name__ == "__main__":
    unittest.main()
