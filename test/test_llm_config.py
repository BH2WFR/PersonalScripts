"""Verify reusable LLM profiles, explicit persistence and independent key ownership."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *


class LlmConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="llm-config-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.enterContext(patch.object(ConfigStore, "directory", return_value=self.folder))

    def test_drafts_are_isolated_and_saved_sources_merge(self) -> None:
        first, second = Llm.load_profiles(), Llm.load_profiles()
        a = LlmSettings(base_url="https://a.example/v1", model="a", reasoning_effort=LlmReasoning.HIGH,
                        skip_certificate_verification=True)
        b = LlmSettings(base_url="https://b.example/v1", model="b", reasoning_effort=LlmReasoning.DEFAULT)
        first.set_api(a, "secret-a", "balance-a")
        second.set_api(b, "secret-b")
        self.assertFalse(ConfigStore("llm.yaml").path.exists())
        self.assertEqual(first.get_api(b.base_url).api_key, "")
        detached = first.get_api(a.base_url + "/chat/completions")
        detached.settings.model = "detached"
        self.assertEqual(first.get_api(a.base_url).settings.model, "a")
        Llm.save_profiles(first)
        Llm.save_profiles(second)
        restored = Llm.load_profiles()
        self.assertEqual(restored.get_api(a.base_url).api_key, "secret-a")
        self.assertEqual(restored.get_api(b.base_url).api_key, "secret-b")
        self.assertIs(restored.get_api(a.base_url).settings.reasoning_effort, LlmReasoning.HIGH)
        self.assertIs(restored.get_api(b.base_url).settings.reasoning_effort, LlmReasoning.DEFAULT)
        self.assertTrue(restored.get_api(a.base_url).settings.skip_certificate_verification)
        self.assertFalse(restored.get_api(b.base_url).settings.skip_certificate_verification)
        self.assertEqual(restored.active_source, b.base_url)
        self.assertIn((a.base_url, a.base_url), restored.providers())
        content = ConfigStore("llm.yaml").path.read_text(encoding="utf-8")
        self.assertNotIn("secret-a", content)
        self.assertNotIn("balance-a", content)
        self.assertNotIn("secret-b", repr(restored))

    def test_old_profiles_default_to_enabled_and_legacy_toggle_is_retained(self) -> None:
        base = "https://example.com/v1"
        source = Llm.source_id(base)
        store = ConfigStore("llm.yaml")
        store.update({"sources": {source: {"base_url": base, "model": "custom"}}})
        self.assertIs(Llm.load_profiles().get_api(base).settings.reasoning_effort, LlmReasoning.AUTO)
        self.assertFalse(Llm.load_profiles().get_api(base).settings.skip_certificate_verification)
        store.update({"sources": {source: {"reasoning_enabled": False}}})
        self.assertIs(Llm.load_profiles().get_api(base).settings.reasoning_effort, LlmReasoning.NONE)
        store.update({"sources": {source: {"reasoning_effort": "high"}}})
        self.assertIs(Llm.load_profiles().get_api(base).settings.reasoning_effort, LlmReasoning.HIGH)

    def test_busy_save_keeps_pending_drafts_for_retry(self) -> None:
        profiles = LlmProfiles()
        profiles.set_api(LlmSettings(), "pending")
        store = ConfigStore("llm.yaml")
        with ConfigStore._locked_path(store.path):
            with self.assertRaises(ConfigBusyError):
                Llm.save_profiles(profiles)
            self.assertTrue(profiles.changed)
            with self.assertRaises(ConfigBusyError):
                Llm.load_profiles()
        Llm.save_profiles(profiles)
        self.assertFalse(profiles.changed)
        self.assertEqual(Llm.load_profiles().get_api(profiles.active_source).api_key, "pending")


if __name__ == "__main__":
    unittest.main()
