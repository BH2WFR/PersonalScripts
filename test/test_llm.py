"""Test shared model helpers without PDF/GUI state or external API requests.

Run: conda run -n base python -m unittest discover -s test -p test_llm.py.
Pillow decodes the synthetic probe for verification; runtime helpers use stdlib.
"""

import base64
import io
from pathlib import Path
import subprocess
import sys
import unittest
from typing import cast

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *


class LlmTests(unittest.TestCase):
    """Verify general text/vision payloads, lazy imports and partial responses."""

    def test_utils_import_and_probe_do_not_load_gui_pdf_or_tool_packages(self) -> None:
        code = (
            "import sys; from utils import *; "
            "Llm.vision_test_request(LlmSettings()); "
            "assert not any(name.split('.')[0] in "
            "('PySide6', 'pymupdf', 'fitz', 'PIL', 'numpy', 'personal_pdf_tools') for name in sys.modules)"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_text_chat_and_image_payloads_have_no_book_coupling(self) -> None:
        settings = LlmSettings(base_url="https://example.com/v1", model="custom", max_tokens=100)
        messages: list[dict[str, object]] = [{"role": "user", "content": "Translate this sentence."}]
        body = Llm.chat_request(settings, messages)
        self.assertEqual(body["messages"], messages)
        self.assertEqual(body["max_tokens"], 100)
        self.assertNotIn("thinking", body)
        self.assertNotIn("api_key", body)
        self.assertEqual(Llm.chat_request(LlmSettings(), messages)["thinking"], {"type": "disabled"})
        content = Llm.image_content(b"encoded", mime_type="image/webp", detail="auto")
        self.assertEqual(content["image_url"], {"url": "data:image/webp;base64,ZW5jb2RlZA==", "detail": "auto"})
        with self.assertRaises(ValueError):
            Llm.image_content(b"")

    def test_vision_probe_is_red_png_and_uses_small_output_budget(self) -> None:
        body = Llm.vision_test_request(LlmSettings())
        messages = cast(list[dict[str, object]], body["messages"])
        content = cast(list[dict[str, object]], messages[0]["content"])
        image_url = cast(dict[str, str], content[1]["image_url"])
        url = image_url["url"]
        with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
            self.assertEqual(image.size, (48, 48))
            self.assertEqual(image.convert("RGB").getcolors(), [(48 * 48, (255, 0, 0))])
        self.assertEqual(body["max_tokens"], 32)

    def test_validation_and_partial_text_remain_independent_of_gui(self) -> None:
        for settings in (LlmSettings(model=""), LlmSettings(temperature=float("nan")),
                         LlmSettings(max_tokens=0), LlmSettings(timeout_seconds=0)):
            with self.assertRaises(ValueError):
                Llm.chat_request(settings, [{"role": "user", "content": "test"}])
        Llm.validate_settings(LlmSettings(model=""), require_model=False)
        result = Llm.parse_completion({"choices": [{"message": {"content": "Partial"}, "finish_reason": "length"}],
                                       "usage": {"prompt_tokens": 7}})
        self.assertEqual(result, LlmResponse("Partial", 7, "length"))
        for data in ({}, {"choices": []}, {"choices": [{"message": {"content": None}}]}):
            with self.assertRaises(ValueError):
                Llm.parse_completion(data)

    def test_balance_routes_do_not_send_proxy_keys_to_official_hosts(self) -> None:
        for base, expected in (
            ("https://api.deepseek.com/v1/chat/completions", "https://api.deepseek.com/user/balance"),
            ("https://api.moonshot.cn/v1", "https://api.moonshot.cn/v1/users/me/balance"),
            ("https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/credits"),
        ):
            self.assertEqual(Llm.balance_url(base), expected)
        for base in ("https://proxy.example.com/v1", "https://api.deepseek.com.example.com/v1",
                     "https://api.deepseek.com/proxy/v1", "https://api.siliconflow.cn/v1",
                     "https://dashscope.aliyuncs.com/compatible-mode/v1"):
            with self.subTest(base=base), self.assertRaises(NotImplementedError):
                Llm.balance_url(base)
        with self.assertRaises(ValueError):
            Llm.balance_url("https://secret@example.com")

    def test_balance_values_preserve_currency_zero_debt_and_decimal_precision(self) -> None:
        base = "https://api.deepseek.com"
        self.assertEqual(Llm.parse_balance(base, {"balance_infos": [
            {"currency": "CNY", "total_balance": "0.00001"},
            {"currency": "USD", "total_balance": "-0.01"}]}), [("CNY", "0.00001"), ("USD", "-0.01")])
        self.assertEqual(Llm.parse_balance("https://api.moonshot.cn/v1",
            {"status": True, "data": {"available_balance": 0}}), [("CNY", "0")])
        self.assertEqual(Llm.parse_balance("https://openrouter.ai/api/v1",
            {"data": {"total_credits": .3, "total_usage": .2}}), [("USD", "0.1")])
        for value in (None, True, "unknown", "NaN", "Infinity", "1e999999", "1e1000000", "0e999999", "1e-999999"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Llm.parse_balance(base, {"balance_infos": [{"currency": "CNY", "total_balance": value}]})
        for data in ({}, {"data": {"limit_remaining": 123}}):
            with self.assertRaises(ValueError):
                Llm.parse_balance("https://openrouter.ai/api/v1", data)
        with self.assertRaises(ValueError):
            Llm.parse_balance("https://api.moonshot.cn/v1", {"status": False, "data": {"available_balance": 123}})


if __name__ == "__main__":
    unittest.main()
