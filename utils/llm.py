"""Reusable LiteLLM text/vision requests with an optional Qt client.

Pure settings, payload builders and parsers use only the standard library.
Llm.acompletion() lazily loads LiteLLM, OpenAI, HTTPX and truststore for compatible endpoints.
TLS uses native system trust unless the source explicitly skips certificate verification.
Llm.create_qt_client() lazily imports PySide6; inference runs off the GUI thread.
No import sends requests or loads PDF/image libraries. Credentials are passed
per request and never included in LlmSettings.
Explicit profile persistence uses PyYAML and cryptography through ConfigStore;
LLM owns its filename and key. Loading/saving holds no lock during network work.

Usage: from utils import *; result = await Llm.acompletion(settings, key, prompt="Hello")
"""

import asyncio
import base64
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import math
import json
import os
import re
import struct
import ssl
import threading
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode, urlsplit, urlunsplit
import zlib
from .config import ConfigStore, EncryptedValue

LLM_CONFIG_FILE = "llm.yaml"
# Stable module-owned obfuscation key; retained for previously stored LLM keys.
LLM_ENCRYPTION_KEY = b"bH6YeY5u7IlYtgvldzZGCgk7kWg6IfcpS68tAHQhGxo="
_LITELLM_LOCK = threading.Lock()
_litellm: Any = None


def _load_litellm() -> Any:
    """Load inference dependencies on demand, without dotenv or price downloads."""
    global _litellm
    with _LITELLM_LOCK:
        if _litellm is None:
            # Library switches, not user configuration. No credentials enter env.
            os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
            os.environ["LITELLM_MODE"] = "PRODUCTION"
            import litellm
            litellm.suppress_debug_info = True
            litellm.turn_off_message_logging = True
            _litellm = litellm
    return _litellm

if TYPE_CHECKING:
    from PySide6 import QtCore
    from ._llm_qt import LlmQtClient


class LlmReasoning(StrEnum):
    """Reasoning intent; AUTO explicitly enables, DEFAULT leaves the server alone."""

    AUTO = "auto"
    DEFAULT = "default"
    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class _ReasoningAPI(StrEnum):
    DEEPSEEK = "deepseek"
    KIMI = "kimi"
    ALIBABA = "alibaba"
    SILICONFLOW = "siliconflow"
    OPENROUTER = "openrouter"
    COMPATIBLE = "compatible"


@dataclass
class LlmSettings:
    """Non-secret connection and generation settings.

    Attributes:
        base_url: Compatible API base URL or full chat-completions endpoint.
        model: Provider-specific model ID; may be empty during model discovery.
        temperature: Finite sampling temperature in [0, 2].
        max_tokens: Positive output-token limit.
        timeout_seconds: Positive timeout for one operation, including pagination.
        max_context_images: Maximum images per chat request, including the current
            image. Keeps newest images and historical text; 0 means unlimited.
        reasoning_effort: AUTO enables reasoning with provider-default effort
            (medium on generic compatible endpoints); DEFAULT omits controls.
            Other values request an explicit level or disable reasoning.
        skip_certificate_verification: False uses system trust and hostname checks;
            True disables TLS verification for this source. HTTP needs no TLS setting.

    Construction performs no I/O. Call Llm.validate_settings before requests.
    """

    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    temperature: float = .1
    max_tokens: int = 8192
    timeout_seconds: int = 180
    max_context_images: int = 5
    reasoning_effort: LlmReasoning = LlmReasoning.AUTO
    skip_certificate_verification: bool = False

    def __post_init__(self) -> None:
        self.reasoning_effort = LlmReasoning(self.reasoning_effort)


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


@dataclass
class LlmProfile:
    """One source's settings and private in-memory credentials."""

    settings: LlmSettings = field(default_factory=LlmSettings)
    api_key: str = field(default="", repr=False)
    balance_key: str = field(default="", repr=False)


@dataclass
class LlmProfiles:
    """Editable source drafts; switching/get/set do no disk or network I/O."""

    active_source: str = field(default_factory=lambda: LlmSettings().base_url)
    sources: dict[str, LlmProfile] = field(default_factory=dict)
    changed: set[str] = field(default_factory=set, repr=False)

    def get_api(self, base: str) -> LlmProfile:
        """Return a detached profile; unknown sources never inherit credentials."""
        profile = self.sources.get(Llm.source_id(base))
        return (LlmProfile(replace(profile.settings, base_url=base), profile.api_key, profile.balance_key)
                if profile else LlmProfile(LlmSettings(base_url=base)))

    def set_api(self, settings: LlmSettings, api_key: str = "", balance_key: str = "") -> None:
        """Update one in-memory draft and its active source; save_profiles commits it."""
        if not isinstance(api_key, str) or not isinstance(balance_key, str):
            raise ValueError("API keys must be strings.")
        source_id = Llm.source_id(settings.base_url)
        profile = LlmProfile(replace(settings), api_key, balance_key)
        if self.sources.get(source_id) != profile:
            self.sources[source_id] = profile
            self.changed.add(source_id)
        self.active_source = settings.base_url

    def providers(self) -> tuple[tuple[str, str], ...]:
        """Built-in providers plus saved/custom sources, deduplicated by endpoint."""
        rows = list(Llm.PRESETS)
        seen = {Llm.source_id(base) for _, base in rows}
        for profile in self.sources.values():
            base = profile.settings.base_url
            source_id = Llm.source_id(base)
            if source_id not in seen:
                rows.append((base, base))
                seen.add(source_id)
        return tuple(rows)


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
    The caller owns messages and image selection. Source drafts and explicit
    persistence use LlmProfiles plus load_profiles/save_profiles.
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
        ("Ollama (local)", "http://localhost:11434/v1"),
        ("LM Studio (local)", "http://localhost:1234/v1"),
    )

    @staticmethod
    def source_id(base: str) -> str:
        """Canonical source key shared by storage, provider lists and source switching."""
        parts = urlsplit(Llm.completion_url(base))
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))

    @staticmethod
    def _profiles_from_data(data: dict[str, Any]) -> LlmProfiles:
        """Decode and validate stored profiles with this module's encryption key."""
        active = data.get("active_source", LlmSettings().base_url)
        sources = data.get("sources", {})
        if not isinstance(active, str) or not isinstance(sources, dict):
            raise ValueError("Invalid LLM active source or source mapping.")
        Llm.source_id(active)
        result = LlmProfiles(active_source=active)
        defaults = asdict(LlmSettings())
        for identifier, values in sources.items():
            if not isinstance(values, dict):
                raise ValueError("Each LLM source must contain a settings mapping.")
            fields = {name: values.get(name, default) for name, default in defaults.items()}
            if "reasoning_effort" not in values and "reasoning_enabled" in values:
                enabled = values["reasoning_enabled"]
                if type(enabled) is not bool:
                    raise ValueError("Invalid legacy reasoning setting.")
                fields["reasoning_effort"] = LlmReasoning.AUTO if enabled else LlmReasoning.NONE
            for name, value in fields.items():
                expected = type(defaults[name])
                if expected is LlmReasoning:
                    fields[name] = LlmReasoning(value)
                    continue
                if not (type(value) is expected or expected is float and type(value) is int):
                    raise ValueError(f"Invalid LLM setting type: {name}")
            settings = LlmSettings(**fields)
            Llm.validate_settings(settings, require_model=False)
            source_id = Llm.source_id(settings.base_url)
            if identifier != source_id:
                raise ValueError("LLM source key does not match its API URL.")
            secrets: list[str] = []
            for name in ("api_key", "balance_key"):
                value = values.get(name, "")
                if isinstance(value, EncryptedValue):
                    value = value.decrypt(LLM_ENCRYPTION_KEY)
                elif isinstance(value, str) and value:
                    result.changed.add(source_id)  # Encrypt manually entered plaintext on the next Save.
                if not isinstance(value, str):
                    raise ValueError(f"Invalid LLM credential type: {name}")
                secrets.append(value)
            result.sources[source_id] = LlmProfile(settings, *secrets)
        return result

    @staticmethod
    def load_profiles() -> LlmProfiles:
        """Read llm.yaml under a short lock; errors leave callers' drafts untouched."""
        return Llm._profiles_from_data(ConfigStore(LLM_CONFIG_FILE).load())

    @staticmethod
    def save_profiles(profiles: LlmProfiles) -> None:
        """Commit changed sources and active URL atomically; conflicts raise immediately.

        Unmodified sources and unrelated YAML fields survive other applications'
        edits. Failed saves keep the changed set so the caller can retry.
        """
        Llm.source_id(profiles.active_source)
        sources = {}
        for identifier in profiles.changed:
            profile = profiles.sources[identifier]
            Llm.validate_settings(profile.settings, require_model=False)
            values = asdict(profile.settings)
            values["reasoning_effort"] = profile.settings.reasoning_effort.value
            values.update(api_key=EncryptedValue.encrypt(profile.api_key, LLM_ENCRYPTION_KEY),
                          balance_key=EncryptedValue.encrypt(profile.balance_key, LLM_ENCRYPTION_KEY))
            sources[identifier] = values
        ConfigStore(LLM_CONFIG_FILE).update({"active_source": profiles.active_source, "sources": sources})
        profiles.changed.clear()

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
    def vision_catalog_url(base: str) -> str | None:
        """Return an official supplemental vision catalog, or None.

        Args:
            base: Valid HTTP(S) API base or chat URL. Only official SiliconFlow
                API hosts use this adapter; proxies and lookalike hosts do not.
        Returns:
            Public SiliconFlow model-center URL. Both regions use these exact
            model IDs as capability metadata, intersected with account models.
            Never send API credentials to this URL. No I/O is performed here.
        Raises:
            ValueError: The API base URL is invalid.
        """
        host = urlsplit(Llm.completion_url(base)).hostname
        return "https://www.siliconflow.cn/models" if host in ("api.siliconflow.cn", "api.siliconflow.com") else None

    @staticmethod
    def parse_vision_catalog(html: str) -> set[str]:
        """Read exact vision model IDs from SiliconFlow's public SSR metadata.

        Args:
            html: HTML from vision_catalog_url, within MAX_RESPONSE bytes.
        Returns:
            Exact modelName values with boolean vlm=True and type=text. No
            aliases, Pro prefixes or model-name heuristics are inferred.
        Raises:
            ValueError: The page is oversized or recognized metadata is absent.
        Parses JSON only, never executes scripts. Website changes fail explicitly
        instead of silently returning an empty filtered catalog.
        """
        if len(html.encode("utf-8")) > Llm.MAX_RESPONSE:
            raise ValueError("Vision capability catalog exceeded the size limit.")
        decoder = json.JSONDecoder()
        chunks: list[str] = []
        for match in re.finditer(r"self\.__next_f\.push\(", html):
            try:
                value, _ = decoder.raw_decode(html, match.end())
            except ValueError:
                continue
            if isinstance(value, list) and len(value) == 2 and value[0] == 1 and isinstance(value[1], str):
                chunks.append(value[1])
        models: set[str] = set()
        recognized = False
        for line in "".join(chunks).splitlines():
            _, separator, payload = line.partition(":")
            if not separator:
                continue
            try:
                pending: list[object] = [json.loads(payload)]
            except ValueError:
                continue
            while pending:
                node = pending.pop()
                if isinstance(node, dict):
                    name = node.get("modelName")
                    if isinstance(name, str) and name.strip() and type(node.get("vlm")) is bool:
                        recognized = True
                        if node["vlm"] is True and node.get("type") == "text":
                            models.add(name.strip())
                    pending.extend(node.values())
                elif isinstance(node, list):
                    pending.extend(node)
        if not recognized:
            raise ValueError("SiliconFlow vision metadata is missing or its website format changed. Disable the vision filter to list all models.")
        return models

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
    def parse_models(data: dict[str, object], *, vision_only: bool = False) -> tuple[list[str], int | None]:
        """Validate compatible/native catalog rows and return IDs plus an optional total.

        Args:
            data: Decoded compatible data list or Alibaba output.models object.
            vision_only: Keep only explicit image-input metadata (modalities or
                capabilities.vision). Unknown capabilities are excluded, never
                guessed from names. Explicit non-text output models are excluded.
        Returns:
            Model IDs in response order and Alibaba's total, or None. The Qt
            client handles pagination, deduplication and sorting. The total is
            unfiltered; pagination must count the unfiltered catalog separately.
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
            if not isinstance(row, dict):
                raise ValueError("The model catalog contains an invalid model row.")
            identifier = row.get(field)
            if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 512:
                raise ValueError("The model catalog contains an invalid model ID.")
            if vision_only:
                architecture = row.get("architecture")
                metadata = architecture if isinstance(architecture, dict) else row
                inputs = metadata.get("input_modalities")
                outputs = metadata.get("output_modalities")
                capabilities = row.get("capabilities")
                image_input = (isinstance(inputs, list) and "image" in inputs
                               or isinstance(capabilities, dict) and capabilities.get("vision") is True)
                if not image_input or isinstance(outputs, list) and "text" not in outputs:
                    continue
            models.append(identifier.strip())
        return models, total

    @staticmethod
    def validate_settings(settings: LlmSettings, *, require_model: bool = True) -> None:
        """Validate a connection before sending or constructing a chat request.

        Args:
            settings: Connection/generation values; never modified.
            require_model: False permits an empty model for catalog requests.
        Raises:
            ValueError: URL, generation settings, timeout or TLS opt-out type is invalid.
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
        if type(settings.max_context_images) is not int or settings.max_context_images < 0:
            raise ValueError("The context image limit must be a nonnegative integer (0 = unlimited).")
        LlmReasoning(settings.reasoning_effort)
        if type(settings.skip_certificate_verification) is not bool:
            raise ValueError("Skip certificate verification must be a boolean.")

    @staticmethod
    def _reasoning_api(base: str) -> _ReasoningAPI:
        """Select payload dialect by exact provider host, without contacting it."""
        try:
            host = urlsplit(base).hostname or ""
        except ValueError:
            # Editable URL fields can be incomplete; request validation is separate.
            return _ReasoningAPI.COMPATIBLE
        if host == "api.deepseek.com":
            return _ReasoningAPI.DEEPSEEK
        if host in ("api.moonshot.cn", "api.moonshot.ai", "api.kimi.com"):
            return _ReasoningAPI.KIMI
        if host in ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com") or host.endswith(".maas.aliyuncs.com"):
            return _ReasoningAPI.ALIBABA
        if host in ("api.siliconflow.cn", "api.siliconflow.com"):
            return _ReasoningAPI.SILICONFLOW
        if host == "openrouter.ai":
            return _ReasoningAPI.OPENROUTER
        return _ReasoningAPI.COMPATIBLE

    @staticmethod
    def reasoning_options(base: str, model: str = "") -> tuple[tuple[str, LlmReasoning], ...]:
        """List conservative reasoning controls for a compatible endpoint/model.

        Args:
            base: API URL; never accessed over the network.
            model: Model ID, used for known always-on and effort-capable families.
        Returns:
            Ordered (UI label, enum) pairs. AUTO is enabled by default; DEFAULT
            sends no controls. Generic/OpenRouter levels still require model
            support; this is not live capability discovery. Token-budget-only
            providers expose on/off rather than invented effort conversions.
        """
        api = Llm._reasoning_api(base)
        name = model.lower()
        choices = [LlmReasoning.AUTO, LlmReasoning.DEFAULT, LlmReasoning.NONE]
        if api == _ReasoningAPI.DEEPSEEK or api == _ReasoningAPI.ALIBABA and name.startswith("deepseek-v4"):
            choices += [LlmReasoning.LOW, LlmReasoning.HIGH, LlmReasoning.MAX]
        elif api == _ReasoningAPI.KIMI:
            if name.startswith("kimi-k3"):
                choices.remove(LlmReasoning.NONE)
                choices += [LlmReasoning.LOW, LlmReasoning.HIGH, LlmReasoning.MAX]
            elif name.startswith("kimi-k2.7-code"):
                choices.remove(LlmReasoning.NONE)
        elif api in (_ReasoningAPI.COMPATIBLE, _ReasoningAPI.OPENROUTER):
            choices += [LlmReasoning.MINIMAL, LlmReasoning.LOW, LlmReasoning.MEDIUM,
                        LlmReasoning.HIGH, LlmReasoning.XHIGH, LlmReasoning.MAX]
        labels = {
            LlmReasoning.AUTO: "Enabled (medium)" if api == _ReasoningAPI.COMPATIBLE else "Enabled (default effort)",
            LlmReasoning.DEFAULT: "Server default (no override)", LlmReasoning.NONE: "Off",
        }
        return tuple((labels.get(choice, choice.value), choice) for choice in choices)

    @staticmethod
    def _reasoning_parameters(settings: LlmSettings) -> dict[str, object]:
        """Map reasoning intent to one dialect; never silently drop unsupported levels."""
        effort = LlmReasoning(settings.reasoning_effort)
        if effort not in {value for _, value in Llm.reasoning_options(settings.base_url, settings.model)}:
            raise ValueError(f"Reasoning effort {effort.value!r} is not available for this API/model. Choose a listed option or Server default.")
        if effort == LlmReasoning.DEFAULT:
            return {}
        api = Llm._reasoning_api(settings.base_url)
        enabled = effort != LlmReasoning.NONE
        explicit = effort not in (LlmReasoning.AUTO, LlmReasoning.NONE)
        parameters: dict[str, object] = {}
        if api == _ReasoningAPI.DEEPSEEK:
            parameters["thinking"] = {"type": "enabled" if enabled else "disabled"}
        elif api == _ReasoningAPI.KIMI:
            if not settings.model.lower().startswith(("kimi-k3", "kimi-k2.7-code")):
                parameters["thinking"] = {"type": "enabled" if enabled else "disabled"}
        elif api in (_ReasoningAPI.ALIBABA, _ReasoningAPI.SILICONFLOW):
            parameters["enable_thinking"] = enabled
        elif api == _ReasoningAPI.OPENROUTER:
            return {"reasoning": {"effort": effort.value} if explicit else {"enabled": enabled}}
        else:
            return {"reasoning_effort": LlmReasoning.MEDIUM.value if effort == LlmReasoning.AUTO else effort.value}
        if explicit:
            parameters["reasoning_effort"] = effort.value
        return parameters

    @staticmethod
    def image_count(messages: Sequence[Mapping[str, object]]) -> int:
        """Count Chat Completions image_url parts in ordered messages.

        Args:
            messages: System/user/assistant mappings with string or list content.
        Returns:
            Number of image parts, including the current input; no I/O or mutation.
        """
        count = 0
        for message in messages:
            content = message.get("content")
            if isinstance(content, list):
                count += sum(isinstance(part, Mapping) and part.get("type") == "image_url"
                             for part in content)
        return count

    @staticmethod
    def limit_images(messages: Sequence[Mapping[str, object]], maximum: int) -> list[dict[str, object]]:
        """Keep the newest image parts while retaining all messages and text.

        Args:
            messages: Chronological Chat Completions messages, current input last.
            maximum: Nonnegative count across the whole request; 0 is unlimited.
        Returns:
            New message/content containers. Older images become textual omission
            markers; the caller's history is untouched and can be resent later.
        Raises:
            ValueError: maximum is not a nonnegative integer.
        No I/O; nested retained content parts are read-only by convention.
        """
        if type(maximum) is not int or maximum < 0:
            raise ValueError("Image limit must be a nonnegative integer.")
        remove = max(0, Llm.image_count(messages) - maximum) if maximum else 0
        result: list[dict[str, object]] = []
        for message in messages:
            copied = dict(message)
            content = message.get("content")
            if isinstance(content, list):
                parts: list[object] = []
                for part in content:
                    if remove and isinstance(part, Mapping) and part.get("type") == "image_url":
                        parts.append({"type": "text", "text": "[Earlier image omitted by the context image limit.]"})
                        remove -= 1
                    else:
                        parts.append(part)
                copied["content"] = parts
            result.append(copied)
        return result

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
            A new body with newest images limited by max_context_images (0 means
            unlimited). Historical text remains. Nested content is read-only by convention.
            Reasoning follows the provider dialect and selected effort; DEFAULT
            omits controls. Unsupported levels fail before a request is sent.
        Raises:
            ValueError: Settings or token override is invalid, or messages are empty.
        """
        Llm.validate_settings(settings)
        limit = settings.max_tokens if max_tokens is None else max_tokens
        if not messages or type(limit) is not int or limit < 1:
            raise ValueError("Provide messages and a positive output-token limit.")
        body: dict[str, object] = {
            "model": settings.model, "temperature": settings.temperature, "max_tokens": limit,
            "stream": False, "messages": Llm.limit_images(messages, settings.max_context_images),
        }
        body.update(Llm._reasoning_parameters(settings))
        api = Llm._reasoning_api(settings.base_url)
        if api == _ReasoningAPI.KIMI or api == _ReasoningAPI.DEEPSEEK and settings.reasoning_effort not in (LlmReasoning.NONE, LlmReasoning.DEFAULT):
            body.pop("temperature")
        return body

    @staticmethod
    async def acompletion(settings: LlmSettings, key: str,
                          messages: Sequence[Mapping[str, object]] = (), *,
                          prompt: str = "", system_prompt: str = "",
                          images: Sequence[Mapping[str, object]] = ()) -> LlmResponse:
        """Send text/vision conversation through LiteLLM, without requiring Qt.

        Args:
            settings: Endpoint, model, generation settings and whole-request image limit.
            key: This source's API key; empty sends no Authorization header.
            messages: Caller-owned chronological history (including assistant replies).
            prompt: Optional new user text appended after history.
            system_prompt: Optional system instruction prepended before history.
            images: New image parts built by image_content, appended with prompt.
        Returns:
            Parsed text, prompt tokens and finish reason. A non-stop finish reason
            retains partial text; callers decide whether to accept it. History is
            never mutated and the returned reply is not automatically appended.
        Raises:
            ValueError: Invalid settings/payload or an API/protocol error (key redacted).
            TimeoutError: The operation exceeded timeout_seconds.
            asyncio.CancelledError: Caller cancelled the task; active HTTP I/O closes.
        Dependencies load lazily on first use. No automatic retries or redirects.
        Image limits include history and new images, keeping newest first; 0 = unlimited.
        """
        if not isinstance(prompt, str) or not isinstance(system_prompt, str):
            raise ValueError("Prompts must be strings.")
        conversation = list(messages)
        if system_prompt:
            conversation.insert(0, {"role": "system", "content": system_prompt})
        if images:
            if any(part.get("type") != "image_url" for part in images):
                raise ValueError("Images must be image_content items.")
            conversation.append({"role": "user", "content": [
                {"type": "text", "text": prompt}, *images]})
        elif prompt:
            conversation.append({"role": "user", "content": prompt})
        body = Llm.chat_request(settings, conversation)
        return await Llm._acompletion_body(settings, key, body)

    @staticmethod
    async def _acompletion_body(settings: LlmSettings, key: str,
                                body: Mapping[str, object]) -> LlmResponse:
        """Internal shared transport for coroutine and Qt callers; one owned HTTP client."""
        Llm.validate_settings(settings)
        # Snapshot and validate before third-party code can mutate caller containers.
        payload = json.loads(json.dumps(body, ensure_ascii=False, allow_nan=False))
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("Provide at least one message.")
        payload["messages"] = Llm.limit_images(messages, settings.max_context_images)
        if payload.get("stream", False) is not False:
            raise ValueError("Streaming is not supported by this client.")
        payload["stream"] = False
        base = Llm.completion_url(settings.base_url).removesuffix("/chat/completions")
        failure = ""
        original_reason = "unknown"
        try:
            async with asyncio.timeout(settings.timeout_seconds):
                library = _load_litellm()
                import httpx
                import truststore
                from openai import AsyncOpenAI
                # Deliver cancellation queued during the cold import before any I/O.
                await asyncio.sleep(0)

                async def prepare(request: httpx.Request) -> None:
                    # Do not inherit SDK organization/project headers or a local dummy key.
                    request.headers.pop("OpenAI-Organization", None)
                    request.headers.pop("OpenAI-Project", None)
                    if not key:
                        request.headers.pop("Authorization", None)

                def validate_response(response: httpx.Response) -> None:
                    nonlocal failure, original_reason
                    data = response.content
                    if response.status_code != 200:
                        detail = response.reason_phrase
                        try:
                            decoded = json.loads(data)
                            problem = decoded.get("error", decoded)
                            if isinstance(problem, dict):
                                detail = str(problem.get("message", detail))
                        except (ValueError, TypeError, AttributeError):
                            pass
                        failure = f"HTTP {response.status_code}: {detail}"
                        raise ValueError(failure)
                    try:
                        decoded = json.loads(data)
                        if not isinstance(decoded, dict):
                            raise ValueError("The API response must be an object.")
                        # Validate upstream fields before SDK defaults can mask omissions.
                        original_reason = Llm.parse_completion(decoded).finish_reason
                    except ValueError as exc:
                        failure = str(exc)
                        raise

                class BoundedClient(httpx.AsyncClient):
                    """Read a capped decoded body, then give the SDK a buffered response."""

                    async def send(self, request: httpx.Request, *, stream: bool = False,
                                   **kwargs: Any) -> httpx.Response:
                        nonlocal failure
                        kwargs["follow_redirects"] = False
                        data = bytearray()
                        stage = "sending request / waiting for response headers"
                        try:
                            incoming = await super().send(request, stream=True, **kwargs)
                            stage = f"reading HTTP {incoming.status_code} response"
                            try:
                                async for chunk in incoming.aiter_bytes():
                                    if len(data) + len(chunk) > Llm.MAX_RESPONSE:
                                        failure = "The API response exceeded the size limit."
                                        raise ValueError(failure)
                                    data.extend(chunk)
                            finally:
                                await incoming.aclose()
                        except Exception as exc:
                            # The SDK wraps arbitrary transport errors as "Connection
                            # error"; capture their causes before that loses detail.
                            if not failure:
                                causes: list[str] = []
                                cause: BaseException | None = exc
                                seen: set[int] = set()
                                while cause is not None and id(cause) not in seen:
                                    seen.add(id(cause))
                                    detail = str(cause)
                                    if key:
                                        detail = detail.replace(key, "[redacted]")
                                    causes.append(f"{type(cause).__name__}: {detail}")
                                    if isinstance(cause, ssl.SSLCertVerificationError):
                                        causes.append(f"TLS verify_code={cause.verify_code}; verify_message={cause.verify_message}")
                                    cause = cause.__cause__ or cause.__context__
                                failure = (f"Transport failed while {stage}. "
                                           f"Request body: {request.headers.get('Content-Length', 'unknown')} bytes; "
                                           f"response body received: {len(data)} bytes. "
                                           f"{' <- '.join(causes)}")
                            raise
                        # Fresh decoder state is essential for gzip/deflate responses.
                        headers = [(name, value) for name, value in incoming.headers.multi_items()
                                   if name.lower() not in ("content-encoding", "content-length")]
                        response = httpx.Response(incoming.status_code, headers=headers,
                                                  content=bytes(data), request=request,
                                                  extensions=incoming.extensions)
                        validate_response(response)
                        return response

                async with BoundedClient(
                    timeout=settings.timeout_seconds, follow_redirects=False,
                    verify=False if settings.skip_certificate_verification else truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                    event_hooks={"request": [prepare]},
                ) as http:
                    async with AsyncOpenAI(api_key=key or "local-no-key", base_url=base,
                                           http_client=http, max_retries=0,
                                           timeout=settings.timeout_seconds) as client:
                        parameters = {name: payload.pop(name) for name in
                                      ("model", "messages", "temperature", "max_tokens", "stream")
                                      if name in payload}
                        parameters["model"] = f"openai/{parameters.get('model', settings.model)}"
                        response = await library.acompletion(
                            **parameters, api_base=base, api_key=key or "local-no-key",
                            client=client, timeout=settings.timeout_seconds,
                            max_retries=0, num_retries=0, caching=False,
                            extra_body=payload, **{"no-log": True},
                        )
                        # LiteLLM schedules bookkeeping even with no-log=True.
                        # Drain it before a Qt request closes its asyncio loop;
                        # otherwise the library carries old tasks into later pages.
                        from litellm.litellm_core_utils.logging_worker import GLOBAL_LOGGING_WORKER
                        await asyncio.sleep(0)
                        await GLOBAL_LOGGING_WORKER.flush()
                        result = Llm.parse_completion(response.model_dump())
                        return replace(result, finish_reason=original_reason)
        except TimeoutError:
            raise TimeoutError("Request timed out.") from None
        except Exception as exc:
            error = failure or str(exc) or type(exc).__name__
            if key:
                error = error.replace(key, "[redacted]")
            raise ValueError(error) from None

    @staticmethod
    def vision_test_request(settings: LlmSettings) -> dict[str, object]:
        """Build a small image-input probe using a generated red square.

        Args:
            settings: Valid target model and API settings.
        Returns:
            A chat body with a 48x48 PNG; expected answer is the word "red".
            Uses the selected reasoning mode and output budget. Explicit Off
            caps output at 32 tokens; tests never force reasoning off on a
            model that may require it.
        Raises:
            ValueError: Settings are invalid.
        No user image, PDF, network access or image-library import is involved.
        """
        # A generic reasoning-options list is not evidence that this model can
        # disable reasoning. Preserve the user's mode, including Server default.
        budget = min(settings.max_tokens, 32) if settings.reasoning_effort == LlmReasoning.NONE else settings.max_tokens
        return Llm.chat_request(settings, [{"role": "user", "content": [
            {"type": "text", "text": "Name the solid background color of this test image in English. Reply with only the color name."},
            Llm.image_content(_probe_png(), mime_type="image/png", detail="low"),
        ]}], max_tokens=budget)

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
