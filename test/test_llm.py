"""Test shared model helpers without PDF/GUI state or external API requests.

Run: conda run -n base python -m unittest discover -s test -p test_llm.py.
Pillow decodes the synthetic probe for verification; runtime helpers use stdlib.
"""

import base64
from dataclasses import replace
import io
import json
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
            "('PySide6', 'pymupdf', 'fitz', 'PIL', 'numpy', 'litellm', 'openai', 'httpx', 'personal_pdf_tools') for name in sys.modules)"
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
        self.assertEqual(Llm.chat_request(LlmSettings(), messages)["thinking"], {"type": "enabled"})
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
        self.assertEqual(body["max_tokens"], LlmSettings().max_tokens)
        self.assertEqual(body["thinking"], {"type": "enabled"})
        disabled = Llm.vision_test_request(LlmSettings(reasoning_effort=LlmReasoning.NONE))
        self.assertEqual(disabled["max_tokens"], 32)
        self.assertEqual(disabled["thinking"], {"type": "disabled"})
        for settings in (LlmSettings(reasoning_effort=LlmReasoning.DEFAULT),
                         LlmSettings(base_url="https://api.moonshot.ai/v1", model="kimi-k3")):
            probe = Llm.vision_test_request(settings)
            self.assertNotIn("thinking", probe)
            self.assertNotIn("reasoning_effort", probe)
            self.assertEqual(probe["max_tokens"], settings.max_tokens)

    def test_openrouter_probe_preserves_selected_reasoning_instead_of_disabling_it(self) -> None:
        settings = LlmSettings(base_url="https://openrouter.ai/api/v1", model="google/gemini-3.8-flash")
        for effort, expected in ((LlmReasoning.AUTO, {"enabled": True}),
                                 (LlmReasoning.HIGH, {"effort": "high"}),
                                 (LlmReasoning.NONE, {"enabled": False})):
            probe = Llm.vision_test_request(replace(settings, reasoning_effort=effort))
            self.assertEqual(probe["reasoning"], expected)
            self.assertEqual(probe["max_tokens"], 32 if effort == LlmReasoning.NONE else settings.max_tokens)
        self.assertNotIn("reasoning", Llm.vision_test_request(replace(settings, reasoning_effort=LlmReasoning.DEFAULT)))

    def test_strict_vision_catalog_uses_input_metadata_not_names(self) -> None:
        catalog: dict[str, object] = {"data": [
            {"id": "reader", "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}},
            {"id": "image-generator", "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}},
            {"id": "image-editor", "architecture": {"input_modalities": ["image"], "output_modalities": ["image"]}},
            {"id": "vision-in-name-only"},
            {"id": "local", "capabilities": {"vision": True}},
            {"id": "false", "capabilities": {"vision": False}},
            {"id": "not-a-bool", "capabilities": {"vision": "true"}},
        ]}
        self.assertEqual(Llm.parse_models(catalog, vision_only=True), (["reader", "local"], None))
        self.assertEqual(len(Llm.parse_models(catalog)[0]), 7)

    def test_siliconflow_vision_catalog_uses_exact_official_metadata(self) -> None:
        for host in ("api.siliconflow.cn", "api.siliconflow.com"):
            self.assertEqual(Llm.vision_catalog_url(f"https://{host}/v1"), "https://www.siliconflow.cn/models")
        for host in ("api.siliconflow.cn.example.com", "proxy.example.com", "openrouter.ai"):
            self.assertIsNone(Llm.vision_catalog_url(f"https://{host}/v1"))
        rows = [
            {"modelName": "Pro/reader", "targetModelName": "reader", "vlm": True, "type": "text"},
            {"modelName": "vision-name-only", "vlm": False, "type": "text"},
            {"modelName": "string-bool", "vlm": "true", "type": "text"},
            {"modelName": "generator", "vlm": True, "type": "image"},
        ]
        flight = f'7:{json.dumps({"children": [None, {"models": rows}]})}\n'
        # A Flight record can span script tags; JavaScript is never evaluated.
        html = "".join(f'<script>self.__next_f.push({json.dumps([1, chunk])})</script>'
                       for chunk in (flight[:37], flight[37:]))
        self.assertEqual(Llm.parse_vision_catalog(html), {"Pro/reader"})
        text_only = 'self.__next_f.push(' + json.dumps([1, '1:' + json.dumps({"models": [rows[1]]}) + '\n']) + ')'
        self.assertEqual(Llm.parse_vision_catalog(text_only), set())
        for invalid in ("<html>Unavailable</html>", 'self.__next_f.push([1,"invalid"])'):
            with self.assertRaisesRegex(ValueError, "metadata is missing"):
                Llm.parse_vision_catalog(invalid)

    def test_reasoning_dialects_and_server_default(self) -> None:
        cases = (
            ("https://api.deepseek.com", "deepseek-flash", LlmReasoning.LOW,
             {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}),
            ("https://api.deepseek.com", "deepseek-flash", LlmReasoning.NONE,
             {"thinking": {"type": "disabled"}}),
            ("https://api.moonshot.ai/v1", "kimi-k2.6", LlmReasoning.AUTO,
             {"thinking": {"type": "enabled"}}),
            ("https://api.moonshot.ai/v1", "kimi-k3", LlmReasoning.MAX,
             {"reasoning_effort": "max"}),
            ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3", LlmReasoning.AUTO,
             {"enable_thinking": True}),
            ("https://api.siliconflow.cn/v1", "Qwen/Qwen3", LlmReasoning.NONE,
             {"enable_thinking": False}),
            ("https://openrouter.ai/api/v1", "provider/model", LlmReasoning.HIGH,
             {"reasoning": {"effort": "high"}}),
            ("https://openrouter.ai/api/v1", "provider/model", LlmReasoning.NONE,
             {"reasoning": {"enabled": False}}),
            ("https://example.com/v1", "custom", LlmReasoning.AUTO,
             {"reasoning_effort": "medium"}),
        )
        controls = {"thinking", "reasoning_effort", "enable_thinking", "reasoning"}
        for base, model, effort, expected in cases:
            with self.subTest(base=base, model=model, effort=effort):
                settings = LlmSettings(base_url=base, model=model, reasoning_effort=effort)
                body = Llm.chat_request(settings, [{"role": "user", "content": "test"}])
                self.assertEqual({key: body[key] for key in controls if key in body}, expected)
                default = Llm.chat_request(replace(settings, reasoning_effort=LlmReasoning.DEFAULT),
                                           [{"role": "user", "content": "test"}])
                self.assertFalse(controls.intersection(default))
        for model, effort in (("kimi-k3", LlmReasoning.NONE), ("kimi-k2.6", LlmReasoning.HIGH)):
            with self.assertRaisesRegex(ValueError, "not available"):
                Llm.chat_request(LlmSettings(base_url="https://api.moonshot.ai/v1", model=model,
                                             reasoning_effort=effort), [{"role": "user", "content": "test"}])

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

    def test_image_budget_keeps_latest_images_and_all_text_without_mutation(self) -> None:
        messages = [{"role": "user", "content": [{"type": "text", "text": f"Page {index}"},
                     Llm.image_content(str(index).encode())]} for index in range(7)]
        for maximum, expected in ((0, 7), (1, 1), (5, 5), (20, 7)):
            body = Llm.chat_request(LlmSettings(max_context_images=maximum), messages)
            limited = body["messages"]
            self.assertEqual(Llm.image_count(limited), expected)
            self.assertEqual(limited[-1]["content"][-1], messages[-1]["content"][-1])
            self.assertEqual([row["content"][0]["text"] for row in limited], [f"Page {index}" for index in range(7)])
            self.assertEqual(Llm.image_count(messages), 7)
        for invalid in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                Llm.chat_request(LlmSettings(max_context_images=invalid), messages)
        presets = dict(Llm.PRESETS)
        self.assertEqual(Llm.models_url(presets["Ollama (local)"]), "http://localhost:11434/v1/models")
        self.assertEqual(Llm.completion_url(presets["LM Studio (local)"]), "http://localhost:1234/v1/chat/completions")

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
