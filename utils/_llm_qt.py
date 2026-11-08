"""Lazy PySide6 transport for Llm; contains no PDF or application state.

Requires PySide6 and a running Qt event loop. Use Llm.create_qt_client().
"""

import json
from PySide6 import QtCore, QtNetwork
from .llm import Llm, LlmSettings


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
        self.reply: QtNetwork.QNetworkReply | None = None
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
        endpoint = Llm.completion_url(settings.base_url)
        payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._listing = False
        self._balance_base = ""
        self._start(endpoint, key, payload)
        self.timer.start(settings.timeout_seconds * 1000)

    def fetch_models(self, settings: LlmSettings, key: str) -> None:
        """Fetch model IDs explicitly, without images or a selected model.

        Args:
            settings: Endpoint and overall timeout; model may be empty.
            key: Bearer token, held until the lookup finishes or is cancelled.
        Raises:
            ValueError: Settings are invalid.
            RuntimeError: Another request is active.
        Shares recognition's single request, cancellation, timeout and size limits.
        Native Alibaba pagination is serial and bounded; redirects are not followed.
        Returns through modelsCompleted; no PDF or application context is involved.
        """
        if self.reply is not None:
            raise RuntimeError("An API request is already running.")
        Llm.validate_settings(settings, require_model=False)
        endpoint = Llm.models_url(settings.base_url)
        self._listing = True
        self._balance_base = ""
        self._model_base = settings.base_url
        self._model_page = 1
        self._models.clear()
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
        self._start(endpoint, key)
        self.timer.start(min(settings.timeout_seconds, 30) * 1000)

    def _start(self, endpoint: str, key: str, payload: bytes | None = None) -> None:
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
        self.reply = (self.manager.get(request) if payload is None
                      else self.manager.post(request, QtCore.QByteArray(payload)))
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finished)

    def cancel(self, reason: str = "Request stopped.") -> None:
        """Abort the active request and report interruption once.

        Args:
            reason: Error text delivered by the relevant completion signal.
        No effect when idle. Does not enqueue a retry or modify caller state.
        """
        if self.reply is not None:
            self._error = reason
            self.reply.abort()

    def _read(self) -> None:
        if self.reply is None:
            return
        self._data.extend(self.reply.readAll().data())
        if len(self._data) > Llm.MAX_RESPONSE:
            self.cancel("The API response exceeded the size limit.")

    def _finished(self) -> None:
        reply = self.reply
        if reply is None:
            return
        if reply.bytesAvailable():
            self._data.extend(reply.readAll().data())
        status = reply.attribute(QtNetwork.QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        text, tokens, error = "", 0, self._error
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
                            detail = str(failure["error"].get("message", detail))[:1000]
                        elif isinstance(failure, dict):
                            detail = str(failure.get("message", detail))[:1000]
                    except (ValueError, TypeError):
                        pass
                    raise ValueError(f"HTTP {status or 'connection error'}: {detail}")
                data = json.loads(self._data)
                if not isinstance(data, dict):
                    raise ValueError("The API response must be an object.")
                if self._balance_base:
                    balances = Llm.parse_balance(self._balance_base, data)
                elif self._listing:
                    models, total = Llm.parse_models(data)
                    previous = len(self._models)
                    self._models.update(models)
                    more_models = total is not None and len(self._models) < total
                    if len(self._models) > Llm.MAX_MODELS or more_models and (
                            len(self._models) == previous or self._model_page >= Llm.MAX_MODEL_PAGES):
                        raise ValueError("Model pagination stalled or exceeded its limit.")
                else:
                    result = Llm.parse_completion(data)
                    text, tokens = result.text, result.prompt_tokens
                    if result.finish_reason != "stop":
                        raise ValueError(f"Incomplete response ({result.finish_reason}); returned text is partial.")
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                error = str(exc)
        if self._key:
            error = error.replace(self._key, "[redacted]")
        self.reply = None
        reply.deleteLater()
        if not error and more_models:
            self._model_page += 1
            self._start(Llm.models_url(self._model_base, self._model_page), self._key)
            return
        self.timer.stop()
        self._key = ""
        listing, self._listing = self._listing, False
        balancing, self._balance_base = bool(self._balance_base), ""
        if balancing:
            self.balanceCompleted.emit(balances if not error else [], error)
        elif listing:
            models = sorted(self._models, key=str.casefold) if not error else []
            self._models.clear()
            self.modelsCompleted.emit(models, error)
        else:
            self.completed.emit(text, tokens, error)
