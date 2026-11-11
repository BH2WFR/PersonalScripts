# LLM utilities

[Utility index](../README.md)

Implementation: [llm.py](../llm.py), [_llm_qt.py](../_llm_qt.py) (private Qt adapter).

## API reference

| Need | Use |
| --- | --- |
| Strict visual model discovery | `Llm.parse_models(data, vision_only=True)` or Qt client `fetch_models(settings, key, vision_only=True)` excludes unknown capability metadata and explicit non-text-output models; requires image input via modalities or `capabilities.vision=True`, never name heuristics; pagination totals/counts remain unfiltered |
| SiliconFlow visual capabilities | `Llm.vision_catalog_url(base)` returns the public model-center URL for official SiliconFlow hosts or None; `Llm.parse_vision_catalog(html)` reads exact text-model IDs marked `vlm=True` from embedded JSON, raises if metadata is missing/changed. Qt strict discovery intersects these IDs with account models using an unauthenticated GET under the same timeout; never send credentials to the public catalog |
| Shared LLM settings and presets | `LlmSettings(base_url=..., model=..., temperature=.1, max_tokens=8192, timeout_seconds=180, max_context_images=5, reasoning_effort=LlmReasoning.AUTO, skip_certificate_verification=False)`; HTTP(S) supported; TLS opt-out is per source and also applies to Qt catalog/balance requests; no secrets; `Llm.PRESETS` includes cloud providers and local endpoints |
| Reasoning choices | `Llm.reasoning_options(base, model="")` returns ordered `(label, LlmReasoning)` pairs; AUTO explicitly enables, DEFAULT sends no controls, NONE disables, remaining enum values select effort. Known provider/model restrictions apply; generic options are not live capability guarantees |
| Validate/resolve LLM endpoints | `Llm.validate_settings(settings, require_model=True)`, `Llm.completion_url(base)`, `Llm.models_url(base, page=1)`; reject credentials/query/fragment in base URLs; same-host Alibaba catalog pagination and SiliconFlow chat filter |
| Construct chat/image requests | `Llm.chat_request(settings, messages, max_tokens=None)`, `Llm.image_content(image, mime_type="image/jpeg", detail="high")`; caller owns context; chat_request limits images across the entire request and maps reasoning to provider fields, rejecting known unsupported levels; no I/O |
| Count/limit context images | `Llm.image_count(messages)`, `Llm.limit_images(messages, maximum)`; 0 = unlimited, otherwise keep newest image_url parts including current input; omit older images with text markers, retain all text/replies, never mutate caller history |
| Construct a vision API probe | `Llm.vision_test_request(settings)`; generated 48x48 red PNG, preserves selected reasoning and output budget; only explicit Off caps output at 32 tokens; no user content or image-library dependency |
| Parse LLM responses/catalogs | `Llm.parse_completion(data) -> LlmResponse(text, prompt_tokens, finish_reason)` retains partial text; `Llm.parse_models(data) -> (ids, total_or_none)` validates compatible/native formats |
| Query API account balances | `Llm.balance_url(base)` resolves same-origin official DeepSeek/Kimi China/OpenRouter routes; unsupported bases raise NotImplementedError. `Llm.parse_balance(base,data) -> list[tuple[str,str]]` returns currency/finite decimal amount pairs; OpenRouter subtracts usage from credits and requires a management key; no guessed proxy routes or key-quota substitution |
| Send text/vision through LiteLLM | `await Llm.acompletion(settings, key, messages=(), prompt="", system_prompt="", images=()) -> LlmResponse`; append prompt/images to caller-owned history, prepend optional system prompt; images use `Llm.image_content`; newest image limit spans the whole conversation (0 = unlimited); returns text/prompt_tokens/finish_reason, including partial responses; no history mutation, retries, redirects or credential environment fallback |
| Create an asynchronous LLM client | `Llm.create_qt_client(parent=None)` lazily loads PySide6; send(settings,key,body), fetch_models(settings,key), fetch_balance(settings,key), cancel(reason); completed(text,tokens,error) / modelsCompleted(ids,error) / balanceCompleted(pairs,error); reply is an opaque busy marker; LiteLLM inference runs on a cancellable QThread, native catalog/balance GETs retain Qt; bounded pagination/size/timeout, key redaction, no automatic retry; balance timeout capped at 30 seconds |

## Profiles and persistence

`Llm.load_profiles()` reads llm.yaml; `Llm.save_profiles(profiles)` commits changed
sources. `LlmProfiles.get_api(base)` returns a detached profile;
`set_api(settings, api_key, balance_key)` changes an in-memory draft;
`providers()` includes built-in and custom sources. `Llm.source_id(base)`
canonicalizes base/full endpoint aliases. Failed saves retain drafts.

The module owns provider presets, request construction, balances, source profiles
and its encryption key. Reasoning is stored per source as an enum string; older
profiles default to AUTO. Optional balance-only keys never enter model requests.
Prompt/history construction belongs to callers; utilities do not import applications.

## Internal transport and validation

`_reasoning_api`/`_reasoning_parameters` map exact provider hosts and known model
families to payload dialects; token budgets are not converted to effort levels.
`_profiles_from_data` validates/decrypts stored mappings before replacing drafts.

`_acompletion_body` is shared by coroutine and Qt callers. It lazily loads
LiteLLM with bundled pricing and dotenv disabled, owns an OpenAI/HTTPX client per
request, enforces the image limit at send time and drains bookkeeping before a
worker loop closes. Transport diagnostics retain exception causes, send/read
stage and byte counts, redact submitted keys and omit image bodies.

`truststore.SSLContext(PROTOCOL_TLS_CLIENT)` uses native system trust and hostname
verification unless a source explicitly opts out. Proxy routing is unchanged.
Qt GETs ignore SSL errors only for opted-out requests and clear cached connections
when that policy changes. Catalog and balance GETs retain native provider adapters;
custom endpoint paths and discovery errors must survive transport handling.

`_llm_qt.py` is a private lazy adapter: use `Llm.create_qt_client()`, not direct
imports through the facade. Importing utils must not load Qt or application code.

Headless checks: `test/test_llm*.py`. The
[bookmarks README](../../tools/document-processing/pdf-tools/bookmarks/README.md)
documents application-specific queue, profile-saving and balance-refresh behavior.
