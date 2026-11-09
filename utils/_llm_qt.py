"""Lazy Qt facade for LiteLLM inference and provider-specific HTTP lookups.

Requires PySide6 and a running Qt event loop. Use Llm.create_qt_client().
Each inference owns a QThread/asyncio task and closes HTTP resources before
publishing completion. Catalog/balance GETs retain Qt's cancellable transport.
"""

import asyncio
from dataclasses import replace
import json
import threading
from PySide6 import QtCore, QtNetwork
from .llm import Llm, LlmResponse, LlmSettings


class _CompletionThread(QtCore.QThread):
    """One cancellable asyncio operation; completion is published only after exit."""

    def __init__(self, settings: LlmSettings, key: str, body: dict[str, object],
                 parent: QtCore.QObject) -> None:
        super().__init__(parent)
        self.settings, self.key, self.body = replace(settings), key, body
        self.result: LlmResponse | None = None
        self.error = ""
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None

    def cancel(self) -> None:
        self.requestInterruption()
        with self._lock:
            if self._loop is not None and self._task is not None:
                self._loop.call_soon_threadsafe(self._task.cancel)

    async def _execute(self) -> None:
        with self._lock:
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.current_task()
        try:
            if self.isInterruptionRequested():
                raise asyncio.CancelledError
            self.result = await Llm._acompletion_body(self.settings, self.key, self.body)
        finally:
            with self._lock:
                self._loop = self._task = None

    def run(self) -> None:
        try:
            asyncio.run(self._execute())
        except asyncio.CancelledError:
            self.error = "Request stopped."
        except Exception as exc:
            self.error = str(exc)
        finally:
            if self.key:
                self.error = self.error.replace(self.key, "[redacted]")
            self.key, self.body = "", {}


class LlmQtClient(QtCore.QObject):
    """Optional Qt transport for shared text/vision and model-catalog requests.

    Obtain through Llm.create_qt_client() so ordinary utility imports stay Qt-free.
    Signals:
        completed: Generated text, prompt tokens, and error (empty on success).
            Partial text is retained when a generation stops early.
        modelsCompleted: Sorted model IDs and error (empty on success).
        balanceCompleted: Currency/decimal-string pairs and error (empty on success).
    """

    completed = QtCore.Signal(str, int, str)  # raw text, prompt tokens, error
    modelsCompleted = QtCore.Signal(list, str)  # model IDs, error
    balanceCompleted = QtCore.Signal(list, str)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.manager = QtNetwork.QNetworkAccessManager(self)
        self._reply: QtNetwork.QNetworkReply | None = None
        self._completion: _CompletionThread | None = None
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.cancel("Request timed out."))
        self._data = bytearray()
        self._error = ""
        self._key = ""
        self._listing = False
        self._balance_base = ""
        self._model_base = ""
        self._model_page = 1
        self._models: set[str] = set()
        self._vision_models: set[str] = set()
        self._vision_only = False
        self._vision_catalog_url: str | None = None
        self._reading_vision_catalog = False
        self._skip_certificate_verification = False

    @property
    def reply(self) -> QtCore.QObject | None:
        """Active operation marker, retained until network/worker cleanup finishes."""
        return self._completion if self._completion is not None else self._reply

    def send(self, settings: LlmSettings, key: str, body: dict[str, object]) -> None:
        """Send one explicit chat/vision request asynchronously.

        Args:
            settings: Target URL/model, generation parameters and timeout.
            key: Bearer token, held only until this request finishes.
            body: JSON-serializable request, normally from Llm.chat_request.
        Raises:
            ValueError: Settings or payload are invalid.
            TypeError: The payload contains values that JSON cannot serialize.
            RuntimeError: Another request is already active.
        Returns through completed; failures redact the exact submitted key.
        """
        if self.reply is not None:
            raise RuntimeError("An API request is already running.")
        Llm.validate_settings(settings)
        payload = json.loads(json.dumps(body, ensure_ascii=False, allow_nan=False))
        self._listing = False
        self._balance_base = ""
        self._error = ""
        self._completion = _CompletionThread(settings, key, payload, self)
        self._completion.finished.connect(self._completion_finished)
        self.timer.start(settings.timeout_seconds * 1000)
        self._completion.start()

    @QtCore.Slot()
    def _completion_finished(self) -> None:
        worker = self._completion
        if worker is None:
            return
        self.timer.stop()
        error = self._error or worker.error
        text, tokens = "", 0
        if worker.result is not None and not error:
            text, tokens = worker.result.text, worker.result.prompt_tokens
            if worker.result.finish_reason != "stop":
                error = f"Incomplete response ({worker.result.finish_reason}); returned text is partial."
        self._completion = None
        self._error = ""
        worker.deleteLater()
        self.completed.emit(text, tokens, error)

    def fetch_models(self, settings: LlmSettings, key: str, *, vision_only: bool = False) -> None:
        """Fetch model IDs explicitly, without images or a selected model.

        Args:
            settings: Endpoint and overall timeout; model may be empty.
            key: Bearer token, held until the lookup finishes or is cancelled.
            vision_only: Require confirmed image-input capability. SiliconFlow
                supplements its API list with public model-center metadata,
                fetched without credentials under the same overall deadline.
        Raises:
            ValueError: Settings are invalid.
            RuntimeError: Another request is active.
        Shares recognition's single request, cancellation, timeout and size limits.
        Native Alibaba pagination is serial and bounded; redirects are not followed.
        vision_only=True excludes unknown/non-visual models using catalog metadata.
        Returns through modelsCompleted; no PDF or application context is involved.
        """
        if self.reply is not None:
            raise RuntimeError("An API request is already running.")
        Llm.validate_settings(settings, require_model=False)
        endpoint = Llm.models_url(settings.base_url)
        self._listing = True
        self._balance_base = ""
        self._model_base = settings.base_url
        self._set_certificate_policy(settings.skip_certificate_verification)
        self._model_page = 1
        self._models.clear()
        self._vision_models.clear()
        self._vision_only = vision_only
        self._vision_catalog_url = Llm.vision_catalog_url(settings.base_url) if vision_only else None
        self._reading_vision_catalog = False
        self._start(endpoint, key)
        self.timer.start(settings.timeout_seconds * 1000)

    def fetch_balance(self, settings: LlmSettings, key: str) -> None:
        """Query account balance asynchronously without sending model/PDF content.

        Args:
            settings: Supported provider base URL and request timeout; model may be empty.
            key: Bearer token; OpenRouter's endpoint requires a management key.
        Raises:
            ValueError: Settings or key are missing/invalid.
            NotImplementedError: No supported endpoint exists for this provider.
            RuntimeError: This client already has an active request.
        Emits balanceCompleted(pairs, error); shares timeout, cancellation, response
        limits and redirect protection with other operations. Does not retry.
        """
        if self.reply is not None:
            raise RuntimeError("An API request is already running.")
        Llm.validate_settings(settings, require_model=False)
        endpoint = Llm.balance_url(settings.base_url)
        if not key.strip():
            raise ValueError("Enter an API key to query its account balance.")
        self._listing = False
        self._balance_base = settings.base_url
        self._set_certificate_policy(settings.skip_certificate_verification)
        self._start(endpoint, key)
        self.timer.start(min(settings.timeout_seconds, 30) * 1000)

    def _set_certificate_policy(self, skip: bool) -> None:
        """Do not reuse connections established under a different verification policy."""
        if skip != self._skip_certificate_verification:
            self.manager.clearConnectionCache()
        self._skip_certificate_verification = skip

    def _start(self, endpoint: str, key: str) -> None:
        """Start one HTTP exchange; a paginated lookup retains its original deadline."""
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(endpoint))
        request.setHeader(QtNetwork.QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setAttribute(QtNetwork.QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QtNetwork.QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        if key:
            request.setRawHeader(b"Authorization", f"Bearer {key}".encode("utf-8"))
        self._key = key
        self._data.clear()
        self._error = ""
        self._reply = self.manager.get(request)
        if self._skip_certificate_verification:
            reply = self._reply
            reply.sslErrors.connect(lambda _errors: reply.ignoreSslErrors())
        self._reply.readyRead.connect(self._read)
        self._reply.finished.connect(self._finished)

    def cancel(self, reason: str = "Request stopped.") -> None:
        """Abort the active request and report interruption once.

        Args:
            reason: Error text delivered by the relevant completion signal.
        No effect when idle. Does not enqueue a retry or modify caller state.
        """
        if self.reply is not None:
            self._error = reason
            if self._completion is not None:
                self._completion.cancel()
            elif self._reply is not None:
                self._reply.abort()

    def _read(self) -> None:
        if self._reply is None:
            return
        self._data.extend(self._reply.readAll().data())
        if len(self._data) > Llm.MAX_RESPONSE:
            self.cancel("The API response exceeded the size limit.")

    def _finished(self) -> None:
        reply = self._reply
        if reply is None:
            return
        if reply.bytesAvailable():
            self._data.extend(reply.readAll().data())
        status = reply.attribute(QtNetwork.QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = self._error
        more_models = False
        balances: list[tuple[str, str]] = []
        if not error:
            try:
                if len(self._data) > Llm.MAX_RESPONSE:
                    raise ValueError("The API response exceeded the size limit.")
                if status != 200:
                    detail = reply.errorString()
                    try:
                        failure = json.loads(self._data)
                        if isinstance(failure, dict) and isinstance(failure.get("error"), dict):
                            detail = str(failure["error"].get("message", detail))
                        elif isinstance(failure, dict):
                            detail = str(failure.get("message", detail))
                    except (ValueError, TypeError):
                        pass
                    raise ValueError(f"HTTP {status or 'connection error'}: {detail}")
                data = {} if self._reading_vision_catalog else json.loads(self._data)
                if not isinstance(data, dict):
                    raise ValueError("The API response must be an object.")
                if self._reading_vision_catalog:
                    confirmed = Llm.parse_vision_catalog(self._data.decode("utf-8"))
                    self._vision_models.update(self._models.intersection(confirmed))
                elif self._balance_base:
                    balances = Llm.parse_balance(self._balance_base, data)
                elif self._listing:
                    models, total = Llm.parse_models(data)
                    previous = len(self._models)
                    self._models.update(models)
                    if self._vision_only:
                        self._vision_models.update(Llm.parse_models(data, vision_only=True)[0])
                    more_models = total is not None and len(self._models) < total
                    if len(self._models) > Llm.MAX_MODELS or more_models and (
                            len(self._models) == previous or self._model_page >= Llm.MAX_MODEL_PAGES):
                        raise ValueError("Model pagination stalled or exceeded its limit.")
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                error = str(exc)
        if self._key:
            error = error.replace(self._key, "[redacted]")
        self._reply = None
        reply.deleteLater()
        if not error and more_models:
            self._model_page += 1
            self._start(Llm.models_url(self._model_base, self._model_page), self._key)
            return
        if not error and self._listing and self._vision_catalog_url and not self._reading_vision_catalog:
            self._reading_vision_catalog = True
            # Public metadata is a separate, unauthenticated request. Preserve
            # the original lookup deadline and never forward the account key.
            self._start(self._vision_catalog_url, "")
            return
        if error and self._reading_vision_catalog:
            error = f"SiliconFlow vision capability lookup failed: {error}"
        self._reading_vision_catalog = False
        self._vision_catalog_url = None
        self.timer.stop()
        self._key = ""
        listing, self._listing = self._listing, False
        balancing, self._balance_base = bool(self._balance_base), ""
        if balancing:
            self.balanceCompleted.emit(balances if not error else [], error)
        elif listing:
            models = sorted(self._vision_models if self._vision_only else self._models, key=str.casefold) if not error else []
            self._models.clear()
            self._vision_models.clear()
            self.modelsCompleted.emit(models, error)
