"""Reusable OpenAI-compatible request helpers with an optional Qt HTTP client.

Pure settings, payload builders and parsers use only the standard library.
Llm.create_qt_client() lazily imports PySide6 for asynchronous GUI requests.
No import sends requests or loads PDF/image libraries. Credentials are passed
per request and never included in LlmSettings.

Usage: from utils import *; client = Llm.create_qt_client(parent)
"""

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import struct
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode, urlsplit, urlunsplit
import zlib

if TYPE_CHECKING:
    from PySide6 import QtCore
    from ._llm_qt import LlmQtClient


@dataclass
class LlmSettings:
    """Non-secret connection and generation settings.

    Attributes:
        base_url: Compatible API base URL or full chat-completions endpoint.
        model: Provider-specific model ID; may be empty during model discovery.
        temperature: Finite sampling temperature in [0, 2].
        max_tokens: Positive output-token limit.
        timeout_seconds: Positive timeout for one operation, including pagination.

    Construction performs no I/O. Call Llm.validate_settings before requests.
    """

    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    temperature: float = .1
    max_tokens: int = 8192
    timeout_seconds: int = 180


@dataclass(frozen=True)
class LlmResponse:
    """Parsed text response, including a possibly incomplete generation.

    Attributes:
        text: Nonempty generated text.
        prompt_tokens: Reported prompt usage, or zero when not available.
        finish_reason: Provider's termination reason; "stop" means complete.
    """

    text: str
    prompt_tokens: int
    finish_reason: str


def _probe_png() -> bytes:
    """Create a 48x48 red RGB PNG with stdlib only; no user image data."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))

    pixels = (b"\x00" + b"\xff\x00\x00" * 48) * 48
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 48, 48, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


class Llm:
    """Common request construction, provider discovery and optional Qt transport.

    These static helpers neither know about books nor manage conversation history.
    The caller owns messages, image selection, credentials and any persistence.
    """

    MAX_RESPONSE: int = 4 * 1024 * 1024
    MAX_MODELS: int = 10_000
    MAX_MODEL_PAGES: int = 100
    PRESETS: tuple[tuple[str, str], ...] = (
        ("DeepSeek", "https://api.deepseek.com"),
        ("Kimi", "https://api.moonshot.cn/v1"),
        ("Alibaba Model Studio (Beijing)", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("Alibaba Model Studio (Singapore)", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        ("OpenRouter", "https://openrouter.ai/api/v1"),
        ("SiliconFlow", "https://api.siliconflow.cn/v1"),
    )

    @staticmethod
    def completion_url(base: str) -> str:
        """Normalize a compatible API base or full chat-completions endpoint.

        Args:
            base: HTTP(S) base or endpoint, optionally ending in a slash.
        Returns:
            Full chat-completions URL on the same host and path prefix.
        Raises:
            ValueError: URL is missing a host or contains credentials/query/fragment.
        No network I/O is performed.
        """
        base = base.strip().rstrip("/")
        parts = urlsplit(base)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Enter an HTTP(S) API base URL without credentials, query or fragment.")
        return base if parts.path.endswith("/chat/completions") else f"{base}/chat/completions"

    @staticmethod
    def models_url(base: str, page: int = 1) -> str:
        """Resolve model discovery without changing host or forwarding a key elsewhere.

        Args:
            base: API base or full chat URL accepted by completion_url.
            page: One-based catalog page for official Alibaba hosts.
        Returns:
            Same-host model URL. Alibaba uses its native paginated catalog;
            other providers use /models, with SiliconFlow's chat filter.
        Raises:
            ValueError: Base URL or page number is invalid.
        No network I/O is performed.
        """
        if type(page) is not int or page < 1:
            raise ValueError("Catalog page must be a positive integer.")
        parts = urlsplit(Llm.completion_url(base).removesuffix("/chat/completions"))
        host = parts.hostname or ""
        query = ""
        path = f"{parts.path}/models"
        if host in ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "cn-hongkong.dashscope.aliyuncs.com") or host.endswith(".maas.aliyuncs.com"):
            path = "/api/v1/models"
            query = urlencode({"page_no": page, "page_size": 100})
        elif host in ("api.siliconflow.cn", "api.siliconflow.com"):
            query = "sub_type=chat"
        return urlunsplit((parts.scheme, parts.netloc, path, query, ""))

    @staticmethod
    def balance_url(base: str) -> str:
        """Resolve a documented account-balance endpoint on the configured host.

        Args:
            base: Official provider base or full chat-completions URL.
        Returns:
            Same-origin GET endpoint for DeepSeek, Kimi China or OpenRouter.
            OpenRouter requires a management key, unlike its inference API.
        Raises:
            ValueError: The base URL is invalid.
            NotImplementedError: No supported balance API exists for this base.
        Never probes guessed paths or forwards a proxy's key to an official host.
        """
        parts = urlsplit(Llm.completion_url(base).removesuffix("/chat/completions"))
        routes = {
            ("api.deepseek.com", ""): "/user/balance",
            ("api.deepseek.com", "/v1"): "/user/balance",
            ("api.moonshot.cn", "/v1"): "/v1/users/me/balance",
            ("openrouter.ai", "/api/v1"): "/api/v1/credits",
        }
        path = routes.get((parts.hostname or "", parts.path))
        if path:
            return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
        if parts.hostname in ("api.siliconflow.cn", "api.siliconflow.com"):
            raise NotImplementedError("SiliconFlow retired its balance endpoint; check the provider console.")
        if parts.hostname and (parts.hostname.endswith(".aliyuncs.com") or parts.hostname.endswith(".aliyun.com")):
            raise NotImplementedError("Alibaba account balance requires cloud billing credentials, not the model API key.")
        raise NotImplementedError("Balance lookup is not supported for this API URL.")

    @staticmethod
    def parse_balance(base: str, data: Mapping[str, object]) -> list[tuple[str, str]]:
        """Validate provider account balances without confusing them with key quotas.

        Args:
            base: Official API base supported by balance_url.
            data: Decoded balance response object.
        Returns:
            Currency/amount pairs, with finite fixed-point decimal strings.
            DeepSeek retains all returned currencies; Kimi China uses CNY;
            OpenRouter returns purchased credits minus usage in USD.
        Raises:
            ValueError: Required balance fields are missing or malformed.
            NotImplementedError: The base has no supported balance adapter.
        Zero and negative balances remain valid. No exchange rates are applied.
        """
        endpoint = Llm.balance_url(base)

        def amount(value: object) -> Decimal:
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise ValueError("Missing or invalid balance amount.")
            try:
                result = Decimal(str(value))
            except InvalidOperation as exc:
                raise ValueError("Invalid balance amount.") from exc
            if not result.is_finite() or result.copy_abs() > Decimal("1e15") or abs(int(result.as_tuple().exponent)) > 18:
                raise ValueError("Invalid balance amount or precision.")
            return result

        if endpoint.endswith("/user/balance"):
            rows = data.get("balance_infos")
            if not isinstance(rows, list) or not rows or len(rows) > 20:
                raise ValueError("Missing balance_infos list.")
            result: list[tuple[str, str]] = []
            for row in rows:
                if not isinstance(row, dict) or row.get("currency") not in ("CNY", "USD"):
                    raise ValueError("Invalid balance currency.")
                result.append((str(row["currency"]), format(amount(row.get("total_balance")), "f")))
            return result
        values = data.get("data")
        if not isinstance(values, dict):
            raise ValueError("Missing balance data.")
        if endpoint.endswith("/users/me/balance"):
            if data.get("status") is not True:
                raise ValueError("The provider did not confirm a successful balance query.")
            return [("CNY", format(amount(values.get("available_balance")), "f"))]
        remaining = amount(values.get("total_credits")) - amount(values.get("total_usage"))
        return [("USD", format(remaining, "f"))]

    @staticmethod
    def parse_models(data: dict[str, object]) -> tuple[list[str], int | None]:
        """Validate compatible/native catalog rows and return IDs plus an optional total.

        Args:
            data: Decoded compatible data list or Alibaba output.models object.
        Returns:
            Model IDs in response order and Alibaba's total, or None. The Qt
            client handles pagination, deduplication and sorting.
        Raises:
            ValueError: Response/IDs are malformed or the catalog exceeds limits.
        Discovery does not certify vision support or account inference access.
        """
        output = data.get("output")
        total = None
        if isinstance(output, dict):
            rows, field = output.get("models"), "model"
            total = output.get("total")
            if type(total) is not int or not 0 <= total <= Llm.MAX_MODELS:
                raise ValueError("Invalid or oversized model catalog total.")
        else:
            rows, field = data.get("data"), "id"
        if not isinstance(rows, list) or len(rows) > Llm.MAX_MODELS:
            raise ValueError("Expected a model list in data or output.models.")
        models: list[str] = []
        for row in rows:
            identifier = row.get(field) if isinstance(row, dict) else None
            if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 512:
                raise ValueError("The model catalog contains an invalid model ID.")
            models.append(identifier.strip())
        return models, total

    @staticmethod
    def validate_settings(settings: LlmSettings, *, require_model: bool = True) -> None:
        """Validate a connection before sending or constructing a chat request.

        Args:
            settings: Connection/generation values; never modified.
            require_model: False permits an empty model for catalog requests.
        Raises:
            ValueError: URL, model, temperature, token limit or timeout is invalid.
        """
        Llm.completion_url(settings.base_url)
        if require_model and not settings.model.strip():
            raise ValueError("Enter a model name.")
        if not math.isfinite(settings.temperature) or not 0 <= settings.temperature <= 2:
            raise ValueError("Temperature must be between 0 and 2.")
        if type(settings.max_tokens) is not int or settings.max_tokens < 1:
            raise ValueError("The output-token limit must be a positive integer.")
        if type(settings.timeout_seconds) is not int or settings.timeout_seconds < 1:
            raise ValueError("The timeout must be a positive integer.")

    @staticmethod
    def image_content(image: bytes, *, mime_type: str = "image/jpeg",
                      detail: Literal["auto", "low", "high"] = "high") -> dict[str, object]:
        """Build an inline image content item without reading files or sending data.

        Args:
            image: Nonempty encoded image bytes, not raw pixel samples.
            mime_type: image/jpeg, image/png, image/webp or image/gif.
            detail: Provider image-detail hint.
        Returns:
            A Chat Completions image_url item with a base64 data URL.
        Raises:
            ValueError: Image is empty or MIME/detail values are unsupported.
        """
        if not image or mime_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            raise ValueError("Provide encoded JPEG, PNG, WebP or GIF image data.")
        if detail not in ("auto", "low", "high"):
            raise ValueError("Image detail must be auto, low or high.")
        return {"type": "image_url", "image_url": {
            "url": f"data:{mime_type};base64,{base64.b64encode(image).decode('ascii')}", "detail": detail}}

    @staticmethod
    def chat_request(settings: LlmSettings, messages: Sequence[Mapping[str, object]], *,
                     max_tokens: int | None = None) -> dict[str, object]:
        """Build a non-streaming compatible chat body from caller-owned messages.

        Args:
            settings: Valid connection and generation settings.
            messages: Ordered system/user/assistant messages, with text or image content.
            max_tokens: Optional positive override, e.g. for a small connectivity probe.
        Returns:
            A new body. Nested content is read-only by convention, not deep-copied.
            Official DeepSeek requests disable thinking so temperature applies.
        Raises:
            ValueError: Settings or token override is invalid, or messages are empty.
        """
        Llm.validate_settings(settings)
        limit = settings.max_tokens if max_tokens is None else max_tokens
        if not messages or type(limit) is not int or limit < 1:
            raise ValueError("Provide messages and a positive output-token limit.")
        body: dict[str, object] = {
            "model": settings.model, "temperature": settings.temperature, "max_tokens": limit,
            "stream": False, "messages": [dict(message) for message in messages],
        }
        if urlsplit(settings.base_url).hostname == "api.deepseek.com":
            body["thinking"] = {"type": "disabled"}
        return body

    @staticmethod
    def vision_test_request(settings: LlmSettings) -> dict[str, object]:
        """Build a 32-token image-input probe using a generated red square.

        Args:
            settings: Valid target model and API settings.
        Returns:
            A chat body with a 48x48 PNG; expected answer is the word "red".
        Raises:
            ValueError: Settings are invalid.
        No user image, PDF, network access or image-library import is involved.
        """
        return Llm.chat_request(settings, [{"role": "user", "content": [
            {"type": "text", "text": "Name the solid background color of this test image in English. Reply with only the color name."},
            Llm.image_content(_probe_png(), mime_type="image/png", detail="low"),
        ]}], max_tokens=32)

    @staticmethod
    def parse_completion(data: Mapping[str, object]) -> LlmResponse:
        """Parse one non-streaming text completion without discarding partial text.

        Args:
            data: Decoded Chat Completions response object.
        Returns:
            Text, prompt usage and finish reason; callers decide how to handle
            incomplete generations instead of silently treating them as success.
            A missing/non-string termination reason becomes "unknown".
        Raises:
            ValueError: Choices, text or usage are malformed.
        """
        choices = data.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else None
        if not isinstance(choice, dict):
            raise ValueError("The API returned no completion choice.")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("The API returned no text content.")
        usage = data.get("usage") or {}
        if not isinstance(usage, dict):
            raise ValueError("Invalid API usage metadata.")
        tokens = usage.get("prompt_tokens")
        reason = choice.get("finish_reason")
        return LlmResponse(content, tokens if type(tokens) is int else 0,
                           reason if isinstance(reason, str) else "unknown")

    @staticmethod
    def create_qt_client(parent: "QtCore.QObject | None" = None) -> "LlmQtClient":
        """Create a serial, cancellable Qt client only when requested.

        Args:
            parent: Optional QObject owning the client's lifetime.
        Returns:
            Client with send/fetch_models/fetch_balance/cancel methods and
            completed(str, int, str), modelsCompleted(list, str),
            balanceCompleted(list, str) signals. Errors are signal strings;
            setup/validation errors raise before network I/O.
        Raises:
            ImportError: PySide6 is unavailable.
        Requires a running Qt event loop for requests. Importing utils alone does
        not load Qt, create a client, read a key, or perform network I/O.
        """
        from ._llm_qt import LlmQtClient
        return LlmQtClient(parent)
