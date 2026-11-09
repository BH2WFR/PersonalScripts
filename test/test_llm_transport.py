"""Real LiteLLM text/vision requests against loopback only; no user credentials.

Run: conda run -n base python -m unittest discover -s test -p test_llm_transport.py
"""

import asyncio
import copy
import datetime
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import ssl
from pathlib import Path
import sys
import threading
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *


class TransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requests: list[dict] = []
        self.status = 200
        self.compress_response = False
        self.disconnect_response = False
        self.response: object = {
            "id": "test", "object": "chat.completion", "created": 1, "model": "org/custom",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Answer"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
        }
        self.gate = threading.Event()
        self.gate.set()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                payload = json.dumps({"data": [{"id": "local-model"}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append({"body": body, "path": self.path,
                                       "authorization": self.headers.get("Authorization"),
                                       "organization": self.headers.get("OpenAI-Organization")})
                owner.gate.wait(10)
                payload = json.dumps(owner.response).encode("utf-8")
                if owner.compress_response:
                    payload = gzip.compress(payload)
                try:
                    self.send_response(owner.status)
                    self.send_header("Content-Type", "application/json")
                    if owner.compress_response:
                        self.send_header("Content-Encoding", "gzip")
                    self.send_header("Content-Length", str(len(payload)))
                    if owner.status == 302:
                        self.send_header("Location", "/redirect-target")
                    self.end_headers()
                    if owner.disconnect_response:
                        self.wfile.write(payload[:10])
                        self.close_connection = True
                        return
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.handler_class = Handler
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(self.gate.set)
        self.settings = LlmSettings(base_url=f"http://127.0.0.1:{server.server_port}/custom/v1/chat/completions",
                                    model="org/custom", timeout_seconds=15, max_context_images=2)

    def test_prompt_history_images_and_explicit_source_credentials(self) -> None:
        history = [
            {"role": "user", "content": [{"type": "text", "text": "Old question"},
              Llm.image_content(b"older"), Llm.image_content(b"recent")]},
            {"role": "assistant", "content": "Old reply"},
        ]
        original = copy.deepcopy(history)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-inherit", "OPENAI_ORG_ID": "private-org"}):
            result = asyncio.run(Llm.acompletion(
                self.settings, "", history, prompt="New question", system_prompt="Translate",
                images=[Llm.image_content(b"new")]))
        self.assertEqual(result, LlmResponse("Answer", 7, "stop"))
        self.assertEqual(history, original)
        sent = self.requests[0]
        self.assertEqual(sent["path"], "/custom/v1/chat/completions")
        self.assertIsNone(sent["authorization"])
        self.assertIsNone(sent["organization"])
        self.assertEqual(sent["body"]["model"], "org/custom")
        messages = sent["body"]["messages"]
        self.assertEqual(messages[0], {"role": "system", "content": "Translate"})
        self.assertEqual(messages[2], history[1])
        self.assertEqual(Llm.image_count(messages), 2)
        self.assertIn("omitted", messages[1]["content"][1]["text"])
        self.assertEqual(messages[-1]["content"][0]["text"], "New question")
        self.assertEqual(sent["body"]["max_tokens"], self.settings.max_tokens)

    def test_raw_body_also_enforces_image_limit_and_keeps_extra_parameters(self) -> None:
        self.settings.max_context_images = 1
        body = Llm.vision_test_request(self.settings)
        body["messages"] *= 3
        body["thinking"] = {"type": "disabled"}
        asyncio.run(Llm._acompletion_body(self.settings, "test-key", body))
        sent = self.requests[0]
        self.assertEqual(sent["authorization"], "Bearer test-key")
        self.assertEqual(Llm.image_count(sent["body"]["messages"]), 1)
        self.assertEqual(sent["body"]["thinking"], {"type": "disabled"})
        self.assertEqual(Llm.image_count(body["messages"]), 3)

    def test_reasoning_selection_reaches_wire_without_changing_dialect(self) -> None:
        for base in ("https://api.deepseek.com", "https://openrouter.ai/api/v1", "https://example.com/v1"):
            settings = LlmSettings(base_url=base, reasoning_effort=LlmReasoning.HIGH)
            body = Llm.chat_request(settings, [{"role": "user", "content": "Test"}])
            asyncio.run(Llm._acompletion_body(self.settings, "", body))
            sent = self.requests[-1]["body"]
            for key in ("thinking", "reasoning_effort", "reasoning"):
                self.assertEqual(sent.get(key), body.get(key))
        self.settings.reasoning_effort = LlmReasoning.DEFAULT
        asyncio.run(Llm.acompletion(self.settings, "", prompt="Test"))
        self.assertNotIn("reasoning_effort", self.requests[-1]["body"])

    def test_partial_and_missing_finish_reason_are_not_silently_completed(self) -> None:
        for reason in ("length", None):
            self.response["choices"][0]["finish_reason"] = reason
            result = asyncio.run(Llm.acompletion(self.settings, "", prompt="Test"))
            self.assertEqual(result.text, "Answer")
            self.assertEqual(result.finish_reason, reason or "unknown")

    def test_http_errors_do_not_retry_redirect_or_expose_key(self) -> None:
        for status in (401, 429, 500, 302):
            with self.subTest(status=status):
                self.status = status
                self.response = {"error": {"message": "Rejected test-key"}}
                previous = len(self.requests)
                with self.assertRaises(ValueError) as failure:
                    asyncio.run(Llm.acompletion(self.settings, "test-key", prompt="Test"))
                self.assertIn(f"HTTP {status}", str(failure.exception))
                self.assertNotIn("test-key", str(failure.exception))
                self.assertEqual(len(self.requests), previous + 1)

    def test_response_limit_and_invalid_content(self) -> None:
        self.response["choices"][0]["message"]["content"] = "x" * 2048
        with patch.object(Llm, "MAX_RESPONSE", 1000), self.assertRaisesRegex(ValueError, "size limit"):
            asyncio.run(Llm.acompletion(self.settings, "", prompt="Test"))
        self.response = {"choices": []}
        with self.assertRaises(ValueError):
            asyncio.run(Llm.acompletion(self.settings, "", prompt="Test"))

    def test_gzip_response_is_decoded_once_and_limit_applies_after_decompression(self) -> None:
        self.compress_response = True
        result = asyncio.run(Llm.acompletion(self.settings, "", prompt="Test"))
        self.assertEqual(result.text, "Answer")
        self.response["choices"][0]["message"]["content"] = "x" * 5000
        with patch.object(Llm, "MAX_RESPONSE", 1000), self.assertRaisesRegex(ValueError, "size limit"):
            asyncio.run(Llm.acompletion(self.settings, "", prompt="Test"))

    def test_interrupted_response_reports_transport_stage_and_recovers(self) -> None:
        self.disconnect_response = True
        with self.assertRaises(ValueError) as caught:
            asyncio.run(Llm.acompletion(self.settings, "private-test-key", prompt="Test"))
        message = str(caught.exception)
        self.assertIn("reading HTTP 200 response", message)
        self.assertIn("RemoteProtocolError", message)
        self.assertIn("Request body:", message)
        self.assertIn("response body received: 10 bytes", message)
        self.assertNotIn("private-test-key", message)
        self.assertEqual(len(self.requests), 1)  # No hidden retry or duplicate billing.
        self.disconnect_response = False
        result = asyncio.run(Llm.acompletion(self.settings, "", prompt="Next page"))
        self.assertEqual(result.text, "Answer")

    def test_send_failure_preserves_underlying_cause_and_redacts_key(self) -> None:
        import httpx
        tail = "Complete diagnostic tail " + "detail " * 300

        async def fail_send(client: httpx.AsyncClient, request: httpx.Request,
                            **kwargs: object) -> httpx.Response:
            try:
                raise OSError(f"Underlying failure private-test-key\n{tail}")
            except OSError as exc:
                raise httpx.ConnectError("Connection failed", request=request) from exc

        with patch.object(httpx.AsyncClient, "send", fail_send), self.assertRaises(ValueError) as caught:
            asyncio.run(Llm.acompletion(self.settings, "private-test-key", prompt="Test"))
        message = str(caught.exception)
        self.assertIn("sending request / waiting for response headers", message)
        self.assertIn("ConnectError", message)
        self.assertIn("OSError: Underlying failure [redacted]", message)
        self.assertIn(tail, message)
        self.assertNotIn("private-test-key", message)
        self.assertEqual(self.requests, [])

    def test_transport_uses_system_trust_with_verification_and_ignores_ca_override(self) -> None:
        import httpx
        import truststore
        original = httpx.AsyncClient.__init__
        contexts: list[ssl.SSLContext] = []

        def capture(client: httpx.AsyncClient, **kwargs: Any) -> None:
            context = kwargs.get("verify")
            self.assertIsInstance(context, truststore.SSLContext)
            assert isinstance(context, ssl.SSLContext)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            contexts.append(context)
            original(client, **kwargs)

        # A nonexistent environment CA must not replace explicit system trust.
        with patch.dict(os.environ, {"SSL_CERT_FILE": str(ROOT / "tmp/nonexistent-test-ca.pem")}), \
                patch.object(httpx.AsyncClient, "__init__", capture):
            result = asyncio.run(Llm.acompletion(self.settings, "", prompt="System trust"))
        self.assertEqual(result.text, "Answer")
        self.assertEqual(len(contexts), 1)

    def test_timeout_and_task_cancel_leave_no_active_request(self) -> None:
        # Warm lazy imports before measuring network deadlines.
        asyncio.run(Llm.acompletion(self.settings, "", prompt="Warm up"))
        self.gate.clear()
        self.settings.timeout_seconds = 1
        with self.assertRaises(TimeoutError):
            asyncio.run(Llm.acompletion(self.settings, "", prompt="Timeout"))

        async def cancel() -> None:
            before = len(self.requests)
            task = asyncio.create_task(Llm.acompletion(self.settings, "", prompt="Cancel"))
            async with asyncio.timeout(3):
                while len(self.requests) == before:
                    await asyncio.sleep(.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(cancel())
        self.gate.set()
        result = asyncio.run(Llm.acompletion(self.settings, "", prompt="Next request"))
        self.assertEqual(result.text, "Answer")

    def test_self_signed_https_requires_explicit_opt_out_for_chat_and_catalog(self) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="llm-tls-")
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                       .public_key(key.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(now - datetime.timedelta(minutes=1))
                       .not_valid_after(now + datetime.timedelta(hours=1))
                       .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                       .sign(key, hashes.SHA256()))
        cert_path, key_path = folder / "cert.pem", folder / "key.pem"
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler_class)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.settings.base_url = f"https://localhost:{server.server_port}/v1"
        for skip in (False, True, False):
            self.settings.skip_certificate_verification = skip
            if skip:
                result = asyncio.run(Llm.acompletion(self.settings, "", prompt="TLS opt-out"))
                self.assertEqual(result.text, "Answer")
                self.assertNotIn("skip_certificate_verification", self.requests[-1]["body"])
            else:
                with self.assertRaises(ValueError):
                    asyncio.run(Llm.acompletion(self.settings, "", prompt="Verified TLS"))
        self.assertEqual(len(self.requests), 1)

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtCore, QtWidgets
        application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        assert isinstance(application, QtWidgets.QApplication)
        application.setStyle("Fusion")
        client = Llm.create_qt_client()
        loop = QtCore.QEventLoop()
        results: list[tuple[list[str], str]] = []

        def completed(models: list[str], error: str) -> None:
            results.append((models, error))
            loop.quit()

        client.modelsCompleted.connect(completed)
        timer = QtCore.QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        for skip in (False, True, False):
            self.settings.skip_certificate_verification = skip
            previous = len(results)
            client.fetch_models(self.settings, "")
            timer.start(5000)
            loop.exec()
            timer.stop()
            self.assertEqual(len(results), previous + 1)
            models, error = results[-1]
            if skip:
                self.assertEqual((models, error), (["local-model"], ""))
            else:
                self.assertTrue(error)
        client.deleteLater()


if __name__ == "__main__":
    unittest.main()
