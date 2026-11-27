"""Shared editable vision API profiles, provider catalog, balance and connectivity test."""

from dataclasses import asdict, replace
from typing import Callable
from PySide6 import QtCore, QtWidgets
from utils import Llm, LlmProfile, LlmProfiles, LlmSettings, LlmReasoning
from utils.qt_styles import set_text_style
from .preferences import report_config_error
from .jobs import JobRunner
from .ui_api_form import Ui_ApiForm


class ApiSettingsForm(QtWidgets.QScrollArea):
    """Scrollable provider settings shared by document and image tools."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui = Ui_ApiForm()
        page = QtWidgets.QWidget()
        self.ui.setupUi(page)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setWidget(page)


class LlmWindow(QtWidgets.QMainWindow):
    """Shared API form for document windows with their own recognition workflow."""

    runner: JobRunner
    status: QtWidgets.QLabel
    balance_summary: QtWidgets.QLabel
    _running: bool
    _closing: bool
    _close_when_idle: bool
    _loading: bool

    @property
    def _api_busy(self) -> bool:
        return self._running or self._testing or self._fetching

    def _sync_api(self) -> None:
        """Allow a document session to mirror the current API settings."""

    def _api_edited(self) -> None:
        """Notify a host that tracks document-specific API drafts."""

    def _enabled(self, *_args: object) -> None:
        raise NotImplementedError

    def _recognized(self, text: str, tokens: int, error: str) -> None:
        raise NotImplementedError

    def _init_api_state(self) -> None:
        self._testing = False
        self._fetching = False
        self._test_elapsed = QtCore.QElapsedTimer()
        self._api_source_base = ""
        self._api_preferences_dirty = False
        self._api_source_dirty = False
        self._api_profiles = LlmProfiles()
        self._api_loaded = False

    def _init_api_clients(self) -> None:
        self.client = Llm.create_qt_client(self)
        self.balance_client = Llm.create_qt_client(self)
        self._balance_identity: tuple[str, str] | None = None
        self.balance_client.balanceCompleted.connect(self._balance_completed)
        self.client.completed.connect(self._client_completed)
        self.client.modelsCompleted.connect(self._models_completed)

    def _button(self, text: str, callback: Callable[[], object]) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.clicked.connect(callback)
        return button

    def _api_form(self, prompt: str) -> QtWidgets.QScrollArea:
        form = ApiSettingsForm()
        self._bind_api_form(form, prompt)
        return form

    def _bind_api_form(self, form: ApiSettingsForm, prompt: str) -> None:
        ui = form.ui
        self.save_api_button = ui.save_api_button
        self.save_api_button.clicked.connect(self._save_api_preferences)
        self.load_api_button = ui.load_api_button
        self.load_api_button.clicked.connect(self._load_api_preferences)
        self.save_api_button.setToolTip("Save all changed source settings to llm.yaml. Closing this window also saves them.")
        self.load_api_button.setToolTip("Reload llm.yaml, replacing unsaved API drafts for all sources.")
        self.api_config_status = ui.api_config_status
        self.api_url = ui.api_url
        self.api_url.setEditable(True)
        self.api_url.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.api_url.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.api_url.setMinimumContentsLength(20)
        for name, url in Llm.PRESETS:
            self.api_url.addItem(name, url)
        self.api_url.setEditText(LlmSettings().base_url)
        self.api_url.setToolTip("Select a provider or custom URL. Switching sources restores its in-memory draft; Save commits all changed sources.")
        self.api_model = ui.api_model
        self.api_model.setEditable(True)
        self.api_model.addItems(["deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"])
        self.api_model.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.api_model.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.api_model.setMinimumContentsLength(20)
        self.api_key = ui.api_key
        self.api_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Saved encrypted in user configuration")
        api_defaults = LlmSettings()
        self.temperature = ui.temperature
        self.temperature.setRange(0, 2)
        self.temperature.setSingleStep(.1)
        self.temperature.setValue(api_defaults.temperature)
        self.max_tokens = ui.max_tokens
        self.max_tokens.setRange(1, 65536)
        self.max_tokens.setValue(api_defaults.max_tokens)
        self.max_tokens.setKeyboardTracking(False)
        self.timeout = ui.timeout
        self.timeout.setRange(5, 1800)
        self.timeout.setValue(api_defaults.timeout_seconds)
        self.timeout.setKeyboardTracking(False)
        self.context_images = ui.context_images
        self.context_images.setRange(0, 10000)
        self.context_images.setValue(api_defaults.max_context_images)
        self.context_images.setKeyboardTracking(False)
        self.context_images.setSpecialValueText("0 — unlimited")
        self.context_images.setToolTip("Maximum images in each request, including the current page. Keeps the newest images; older image parts are omitted but text/replies remain. Use 5 for a five-image model, 1 for only the current image, or 0 for no limit.")
        self.reasoning_effort = ui.reasoning_effort
        self.reasoning_effort.setToolTip("Saved per API source. Enabled uses the provider's default effort (medium for generic compatible APIs). Server default sends no reasoning controls. Available levels vary by API and model; generic options are not a guarantee of model support. The API test uses this selected reasoning mode.")
        self._refresh_reasoning_options(api_defaults.reasoning_effort)
        self.skip_certificate_verification = ui.skip_certificate_verification
        self.skip_certificate_verification.setToolTip("Off by default. Applies to HTTPS recognition, API tests, model lists and balances for this source. HTTP local servers work without enabling this. Enabling skips certificate and hostname checks.")
        self.fetch_button = ui.fetch_button
        self.fetch_button.clicked.connect(self._fetch_models)
        self.fetch_button.setToolTip("Request the provider's model catalog with this key. No document content is sent; select a vision-capable model.")
        self.vision_models_only = ui.vision_models_only
        self.vision_models_only.setToolTip("Get models includes only models explicitly reporting image input. Unknown capabilities are excluded; image-generation-only models are excluded. Some APIs do not publish this metadata.")
        self.vision_models_only.toggled.connect(self._model_filter_changed)
        self.models_status = ui.models_status
        self.reset_api_parameters_button = ui.reset_api_parameters_button
        self.reset_api_parameters_button.clicked.connect(self._reset_api_parameters)
        self.reset_api_parameters_button.setToolTip("Restore default temperature, output-token limit, timeout, context-image limit and reasoning effort for this source. Save or close to persist.")
        self.balance_key = ui.balance_key
        self.balance_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.balance_key.setPlaceholderText("Optional; defaults to API key")
        self.balance_key.setToolTip("OpenRouter account balance requires a management key. Used only for balance queries; never for recognition.")
        self.balance_button = ui.balance_button
        self.balance_button.clicked.connect(self._refresh_balance)
        self.balance_status = ui.balance_status
        self.balance_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.usage = ui.usage
        self.test_button = ui.test_button
        self.test_button.clicked.connect(self._test_api)
        self.test_button.setToolTip("Send a generated color square to verify credentials, model and image input. No document content is sent.")
        self.test_status = ui.test_status
        self.test_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        ui.copy_prompt.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(prompt))
        self._previous_api_url = LlmSettings().base_url
        self.api_url.activated.connect(self._select_api_preset)
        self.api_url.currentTextChanged.connect(self._endpoint_changed)
        api_url_editor = self.api_url.lineEdit()
        assert api_url_editor is not None
        api_url_editor.editingFinished.connect(self._refresh_balance)
        for key_field in (self.api_key, self.balance_key):
            key_field.textChanged.connect(self._invalidate_balance)
            key_field.textChanged.connect(self._api_changed)
            key_field.editingFinished.connect(self._refresh_balance)
        self.api_model.currentTextChanged.connect(self._api_changed)
        self.temperature.valueChanged.connect(self._api_changed)
        self.max_tokens.valueChanged.connect(self._api_changed)
        self.timeout.valueChanged.connect(self._api_changed)
        self.context_images.valueChanged.connect(self._api_changed)
        self.reasoning_effort.currentIndexChanged.connect(self._api_changed)
        self.skip_certificate_verification.toggled.connect(self._api_changed)
        self.skip_certificate_verification.toggled.connect(self._invalidate_balance)

    @staticmethod
    def _api_source_id(base: str) -> str:
        try:
            return Llm.source_id(base)
        except ValueError:
            return ""

    def _api_config_feedback(self, text: str, error: Exception | None = None) -> None:
        self.api_config_status.setText(text)
        self.api_config_status.setToolTip(text)
        set_text_style(self.api_config_status, "red" if error else None)
        if error is not None:
            report_config_error(self.api_config_status, error)

    def _load_api_preferences(self, *_args: object) -> bool:
        try:
            profiles = Llm.load_profiles()
        except (OSError, ValueError) as exc:
            self._api_config_feedback(f"Load failed: {exc}", exc)
            return False
        self._api_profiles = profiles
        self._api_loaded = True
        self._show_api_profiles()
        self._api_config_feedback("LLM settings loaded. Editing and switching sources do not write to disk.")
        self._invalidate_balance()
        self._sync_api()
        return True

    def _show_api_profiles(self) -> None:
        self._loading = True
        self.api_url.clear()
        for name, base in self._api_profiles.providers():
            self.api_url.addItem(name, base)
        self.api_url.setEditText(self._api_profiles.active_source)
        self._loading = False
        self._load_api_source(self._api_base())
        self._api_preferences_dirty = bool(self._api_profiles.changed)

    def _add_api_source_option(self, base: str) -> None:
        source_id = self._api_source_id(base)
        if source_id and not any(self._api_source_id(str(self.api_url.itemData(index))) == source_id
                                 for index in range(self.api_url.count())):
            self.api_url.addItem(base, base)

    def _load_api_source(self, base: str) -> None:
        source_id = self._api_source_id(base)
        profile = self._api_profiles.get_api(base) if source_id else LlmProfile(LlmSettings(base_url=base))
        values = asdict(profile.settings)
        values.update(api_key=profile.api_key, balance_key=profile.balance_key)
        self._loading = True
        try:
            self.api_model.clear()
            fields = {"model": self.api_model, "api_key": self.api_key,
                      "balance_key": self.balance_key, "temperature": self.temperature,
                      "max_tokens": self.max_tokens, "timeout_seconds": self.timeout,
                      "max_context_images": self.context_images}
            for name, widget in fields.items():
                value = values[name]
                if isinstance(widget, QtWidgets.QComboBox) and isinstance(value, str):
                    widget.setCurrentText(value)
                elif isinstance(widget, QtWidgets.QLineEdit) and isinstance(value, str):
                    widget.setText(value)
                elif isinstance(widget, QtWidgets.QDoubleSpinBox) and type(value) in (int, float):
                    widget.setValue(value)
                elif isinstance(widget, QtWidgets.QSpinBox) and type(value) is int:
                    widget.setValue(value)
            self._refresh_reasoning_options(profile.settings.reasoning_effort)
            self.skip_certificate_verification.setChecked(profile.settings.skip_certificate_verification)
            self._api_source_base = base if source_id else ""
            self._previous_api_url = base
            self._api_source_dirty = False
        finally:
            self._loading = False

    def _capture_api_source(self, *, force: bool = False) -> None:
        """Keep outgoing fields in memory, even after the URL widget has changed."""
        if self._loading or not self._api_source_base or not (force or self._api_source_dirty):
            return
        settings = replace(self._read_api(), base_url=self._api_source_base)
        self._api_profiles.set_api(settings, self.api_key.text(), self.balance_key.text())

    def _save_api_preferences(self, *_args: object) -> bool:
        if self._loading:
            return False
        try:
            self._capture_api_source(force=True)
            self._api_profiles.active_source = self._api_base()
            Llm.save_profiles(self._api_profiles)
        except (OSError, ValueError) as exc:
            self._api_config_feedback(f"Save failed: {exc}", exc)
            return False
        self._api_loaded = True
        self._add_api_source_option(self._api_base())
        self._api_preferences_dirty = False
        self._api_source_dirty = False
        self._api_config_feedback("LLM settings saved to llm.yaml.")
        return True

    def _read_api(self) -> LlmSettings:
        return LlmSettings(self._api_base(), self.api_model.currentText().strip(),
                           self.temperature.value(), self.max_tokens.value(), self.timeout.value(), self.context_images.value(),
                           reasoning_effort=LlmReasoning(self.reasoning_effort.currentData() or LlmReasoning.AUTO),
                           skip_certificate_verification=self.skip_certificate_verification.isChecked())

    def _reset_api_parameters(self) -> None:
        """Restore generation defaults in the active source's in-memory draft."""
        if not self.reset_api_parameters_button.isEnabled():
            return
        defaults = LlmSettings()
        with (QtCore.QSignalBlocker(self.temperature), QtCore.QSignalBlocker(self.max_tokens),
              QtCore.QSignalBlocker(self.timeout), QtCore.QSignalBlocker(self.context_images)):
            self.temperature.setValue(defaults.temperature)
            self.max_tokens.setValue(defaults.max_tokens)
            self.timeout.setValue(defaults.timeout_seconds)
            self.context_images.setValue(defaults.max_context_images)
            self._refresh_reasoning_options(defaults.reasoning_effort)
        self._api_changed()

    def _refresh_reasoning_options(self, selected: LlmReasoning | None = None) -> None:
        """Rebuild API/model choices without silently changing a saved effort."""
        selected = selected or LlmReasoning(self.reasoning_effort.currentData() or LlmReasoning.AUTO)
        with QtCore.QSignalBlocker(self.reasoning_effort):
            self.reasoning_effort.clear()
            for label, value in Llm.reasoning_options(self._api_base(), self.api_model.currentText()):
                self.reasoning_effort.addItem(label, value.value)
            index = self.reasoning_effort.findData(selected.value)
            if index < 0:
                self.reasoning_effort.addItem(f"{selected.value} (not supported; choose another)", selected.value)
                index = self.reasoning_effort.count() - 1
            self.reasoning_effort.setCurrentIndex(index)

    def _api_base(self) -> str:
        index = self.api_url.currentIndex()
        if index >= 0 and self.api_url.currentText() == self.api_url.itemText(index):
            return str(self.api_url.itemData(index))
        return self.api_url.currentText().strip()

    def _select_api_preset(self, index: int) -> None:
        self.api_url.setEditText(str(self.api_url.itemData(index)))

    def _endpoint_changed(self, *_args: object) -> None:
        base = self._api_base()
        if not self._loading and base != self._previous_api_url:
            self._capture_api_source()
            self._load_api_source(base)
            if self._api_source_id(base):
                self._api_profiles.active_source = base
            self._api_preferences_dirty = True
            self.models_status.setText("Provider changed. Source draft restored; Get models or enter a model name.")
            self.test_status.setText("API not tested")
            set_text_style(self.test_status, None)
            self._invalidate_balance()
            self._sync_api()
        self._previous_api_url = base

    def _model_filter_changed(self) -> None:
        """Discard the old catalog until an explicit fetch applies the new filter."""
        current = self.api_model.currentText()
        with QtCore.QSignalBlocker(self.api_model):
            self.api_model.clear()
            self.api_model.setEditText(current)
        self.models_status.setText("Filter changed. Click Get models to refresh the list.")

    def _fetch_models(self) -> None:
        if self._api_busy or self.runner.busy:
            return
        self._fetching = True
        self.models_status.setText("Fetching models…")
        try:
            self.client.fetch_models(self._read_api(), self.api_key.text(), vision_only=self.vision_models_only.isChecked())
            self._enabled()
        except (ValueError, RuntimeError) as exc:
            self._models_completed([], str(exc))

    def _set_balance(self, summary: str, detail: str, *, error: bool = False,
                     available: bool = False) -> None:
        self.balance_summary.setText(f"API balance: {summary}")
        self.balance_summary.setToolTip(detail)
        self.balance_status.setText(detail)
        for label in (self.balance_summary, self.balance_status):
            set_text_style(label, "red" if error else "blue" if available else None, bold=available and not error)

    def _invalidate_balance(self, *_args: object) -> None:
        # Invalidate before abort: Qt may deliver cancellation synchronously.
        self._balance_identity = None
        self.balance_client.cancel("Balance credentials changed.")
        self._set_balance("not queried", "Credentials changed. Finish editing or refresh to query the current account.")

    def _refresh_balance(self) -> None:
        if self._closing or self._close_when_idle or self._api_busy or self.balance_client.reply is not None:
            return
        settings = self._read_api()
        key = self.balance_key.text() or self.api_key.text()
        try:
            Llm.balance_url(settings.base_url)
            if not key.strip():
                self._set_balance("not queried", "Enter an API key to display the account balance.")
                return
            self._balance_identity = (settings.base_url, key)
            self._set_balance("checking…", "Querying API account balance; no PDF or model request is sent.")
            self.balance_client.fetch_balance(settings, key)
            self._enabled()
        except NotImplementedError as exc:
            self._balance_identity = None
            self._set_balance("unsupported", str(exc))
        except (ValueError, RuntimeError) as exc:
            self._balance_identity = (settings.base_url, key)
            self._balance_completed([], str(exc))

    def _balance_completed(self, balances: list[tuple[str, str]], error: str) -> None:
        identity, self._balance_identity = self._balance_identity, None
        current = (self._api_base(), self.balance_key.text() or self.api_key.text())
        if identity is not None and identity == current:
            if error:
                hint = (" OpenRouter requires a management key in Balance key."
                        if QtCore.QUrl(identity[0]).host() == "openrouter.ai" else "")
                self._set_balance("unavailable", f"Balance query failed: {error}{hint}", error=True)
            else:
                value = "; ".join(f"{currency} {amount}" for currency, amount in balances)
                self._set_balance(value, f"API account balance: {value}", available=True)
        self._enabled()
        if self._close_when_idle:
            QtCore.QTimer.singleShot(0, self.close)

    def _models_completed(self, models: list[str], error: str) -> None:
        self._fetching = False
        if error:
            self.models_status.setText(f"Cannot fetch models: {error} You can still enter a model name manually.")
        else:
            current = self.api_model.currentText()
            with QtCore.QSignalBlocker(self.api_model):
                self.api_model.clear()
                self.api_model.addItems(models)
                if current and (not self.vision_models_only.isChecked() or current in models):
                    self.api_model.setCurrentText(current)
            self._api_changed()
            self.models_status.setText(
                f"{len(models)} confirmed image-input models. Unknown capabilities are excluded; API Test checks access."
                if self.vision_models_only.isChecked() and models else
                "No models explicitly report image input. This API may omit capability metadata; uncheck the filter or enter a model manually."
                if self.vision_models_only.isChecked() else
                f"{len(models)} models reported. Select one with image input; API Test checks vision access.")
        self._enabled()
        if self._close_when_idle:
            QtCore.QTimer.singleShot(0, self.close)

    def _begin_api_test(self) -> bool:
        """Let windows with an exchange viewer start capturing the test request."""
        return False

    def _test_api(self) -> None:
        if self._api_busy or self.runner.busy:
            return
        settings = self._read_api()
        self._testing = True
        self._test_elapsed.start()
        try:
            capture = self._begin_api_test()
            body = Llm.vision_test_request(settings)
            self.test_status.setText("Testing image input…")
            set_text_style(self.test_status, None)
            self.client.send(settings, self.api_key.text(), body, capture=capture)
            self._enabled()
        except (ValueError, RuntimeError) as exc:
            self._client_completed("", 0, str(exc))

    def _client_completed(self, text: str, tokens: int, error: str) -> None:
        if not self._testing:
            self._recognized(text, tokens, error)
            return
        self._testing = False
        elapsed = self._test_elapsed.elapsed() / 1000
        passed = not error and text.strip().strip('.!\"').lower() == "red"
        if error:
            message = f"API test failed ({elapsed:.2f}s): {error}"
        elif passed:
            message = f"API test passed: image recognized ({elapsed:.2f}s, {tokens} input tokens)."
        else:
            message = f"API connected ({elapsed:.2f}s), but unexpected image response: {text[:200]}"
        self.test_status.setText(message)
        set_text_style(self.test_status, "green" if passed else "red", bold=True)
        self.status.setText(message)
        self._enabled()
        self._refresh_balance()
        if self._close_when_idle:
            QtCore.QTimer.singleShot(0, self.close)

    def _api_changed(self, *_args: object) -> None:
        if not self._loading:
            self._refresh_reasoning_options()
            self._api_preferences_dirty = True
            self._api_source_dirty = True
            self._api_config_feedback("Unsaved API settings. Save or close this window to write changes.")
        if not self._loading:
            self._api_edited()
