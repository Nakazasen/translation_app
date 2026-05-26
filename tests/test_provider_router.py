import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from deep_translator import GoogleTranslator

from translation_app.core.ai_service import get_ai_service
from translation_app.core.provider_router import ProviderRouter, TranslationRequest, TranslationResult
from translation_app.core.providers.base import BaseTranslationProvider
from translation_app.core.providers.openai_compatible_provider import OpenAICompatibleProvider
from translation_app.core.translation_memory import get_tm_manager
from translation_app.core.translator import TranslationService


@pytest.fixture(autouse=True)
def reset_singletons():
    import translation_app.core.ai_service
    import translation_app.core.translation_memory

    translation_app.core.ai_service._service_instance = None
    translation_app.core.translation_memory._tm_manager = None
    yield
    translation_app.core.ai_service._service_instance = None
    translation_app.core.translation_memory._tm_manager = None


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    yield path
    for _ in range(5):
        if not os.path.exists(path):
            break
        try:
            os.remove(path)
            break
        except PermissionError:
            time.sleep(0.1)


class DummyProvider(BaseTranslationProvider):
    supports_glossary = True
    supports_ai_prompt = True

    def __init__(self, name, responses, available=True):
        self.name = name
        self.default_model = f"{name}-model"
        self._responses = list(responses)
        self._available = available
        self.calls = 0
        self.requests = []

    def is_available(self) -> bool:
        return self._available

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls += 1
        self.requests.append(request)
        response = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(response, TranslationResult):
            return response
        return TranslationResult(
            status=response.get("status", "error"),
            text=response.get("text", ""),
            provider=self.name,
            model=response.get("model", self.default_model),
            error_type=response.get("error_type", ""),
            error_message=response.get("error_message", ""),
            latency_ms=response.get("latency_ms", 0),
        )


def test_router_uses_first_available_provider():
    router = ProviderRouter(cooldown_seconds=60, max_retries=2)
    first = DummyProvider("gemini", [{"status": "success", "text": "alpha"}])
    second = DummyProvider("google", [{"status": "success", "text": "beta"}])
    router.register_provider(first)
    router.register_provider(second)

    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi"),
        {"allowed_providers": ["gemini", "google"], "provider_order": ["gemini", "google"]},
    )

    assert result.status == "success"
    assert result.text == "alpha"
    assert first.calls == 1
    assert second.calls == 0


def test_router_skips_provider_on_cooldown():
    router = ProviderRouter(cooldown_seconds=300, max_retries=2)
    first = DummyProvider("gemini", [{"status": "success", "text": "alpha"}])
    second = DummyProvider("google", [{"status": "success", "text": "beta"}])
    router.register_provider(first)
    router.register_provider(second)
    router.mark_failure("gemini", "gemini-model", "429 quota exceeded")

    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi"),
        {"allowed_providers": ["gemini", "google"], "provider_order": ["gemini", "google"]},
    )

    assert result.status == "success"
    assert result.text == "beta"
    assert first.calls == 0
    assert second.calls == 1
    assert result.attempts[0]["reason"] == "cooldown"


def test_router_marks_quota_error_cooldown():
    router = ProviderRouter(cooldown_seconds=300, max_retries=2)
    failing = DummyProvider("gemini", [{"status": "error", "error_message": "429 quota exceeded"}])
    fallback = DummyProvider("google", [{"status": "success", "text": "ok"}])
    router.register_provider(failing)
    router.register_provider(fallback)

    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi"),
        {"allowed_providers": ["gemini", "google"], "provider_order": ["gemini", "google"]},
    )

    assert result.status == "success"
    snapshot = router.get_health_snapshot()
    gemini_state = next(item for item in snapshot if item["provider_name"] == "gemini")
    assert gemini_state["last_error_type"] == "quota_rate_limit"
    assert gemini_state["cooldown_until"] > 0


def test_strict_ai_policy_never_uses_google():
    router = ProviderRouter(cooldown_seconds=60, max_retries=2)
    gemini = DummyProvider("gemini", [{"status": "error", "error_message": "timeout"}])
    openai = DummyProvider("openai_compatible", [{"status": "success", "text": "ai-only"}])
    google = DummyProvider("google", [{"status": "success", "text": "wrong"}])
    router.register_provider(gemini)
    router.register_provider(openai)
    router.register_provider(google)

    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi", strategy="ai"),
        {"allowed_providers": ["gemini", "openai_compatible"], "provider_order": ["gemini", "openai_compatible"]},
    )

    assert result.status == "success"
    assert result.text == "ai-only"
    assert google.calls == 0


def test_ai_waterfall_can_fallback_to_google():
    router = ProviderRouter(cooldown_seconds=60, max_retries=2)
    gemini = DummyProvider("gemini", [{"status": "error", "error_message": "timeout"}])
    openai = DummyProvider("openai_compatible", [{"status": "error", "error_message": "503 upstream"}])
    google = DummyProvider("google", [{"status": "success", "text": "google-ok"}])
    router.register_provider(gemini)
    router.register_provider(openai)
    router.register_provider(google)

    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi", strategy="ai_waterfall"),
        {"allowed_providers": ["gemini", "openai_compatible", "google"], "provider_order": ["gemini", "openai_compatible", "google"]},
    )

    assert result.status == "success"
    assert result.text == "google-ok"
    assert [attempt["provider"] for attempt in result.attempts if attempt["status"] != "skipped"] == [
        "gemini",
        "openai_compatible",
        "google",
    ]


def test_provider_router_does_not_log_api_keys(caplog):
    secret = "sk-router-secret-12345"
    router = ProviderRouter(cooldown_seconds=60, max_retries=0)
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:9/v1",
        api_key=secret,
        model="mock-model",
        provider_name="openai_compatible",
    )
    router.register_provider(provider)

    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi"),
        {"allowed_providers": ["openai_compatible"], "provider_order": ["openai_compatible"]},
    )

    assert result.status == "error"
    assert secret not in caplog.text
    assert secret not in json.dumps(router.get_health_snapshot())
    assert secret not in json.dumps(result.attempts)


def test_openai_compatible_provider_builds_request_without_network_real_call():
    requests_seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            requests_seen.append(
                {
                    "path": self.path,
                    "auth": self.headers.get("Authorization", ""),
                    "body": json.loads(body),
                }
            )
            payload = {"choices": [{"message": {"content": "xin chao"}}]}
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        provider = OpenAICompatibleProvider(
            enabled=True,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="sk-test-abc123",
            model="gpt-mock",
            provider_name="mock-openai",
            timeout=5,
        )
        result = provider.translate(
            TranslationRequest(
                text="Hello",
                source_lang="en",
                target_lang="vi",
                glossary_terms=[{"source_term": "Hello", "target_term": "Xin chào"}],
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.status == "success"
    assert result.text == "xin chao"
    assert len(requests_seen) == 1
    assert requests_seen[0]["path"] == "/v1/chat/completions"
    assert requests_seen[0]["auth"] == "Bearer sk-test-abc123"
    assert requests_seen[0]["body"]["model"] == "gpt-mock"
    assert "Use this glossary strictly:" in requests_seen[0]["body"]["messages"][0]["content"]


def test_openai_compatible_provider_redacts_key_and_classifies_auth_http_error():
    secret = "sk-auth-secret-123"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.dumps({"error": f"invalid api key {secret}"}).encode("utf-8")
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        provider = OpenAICompatibleProvider(
            enabled=True,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key=secret,
            model="gpt-mock",
            provider_name="mock-openai",
            timeout=5,
        )
        result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.status == "error"
    assert result.error_type == "auth_failure"
    assert secret not in result.error_message
    assert "[REDACTED_API_KEY]" in result.error_message


def test_openai_compatible_provider_classifies_quota_http_error():
    secret = "sk-quota-secret-456"

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.dumps({"error": f"429 quota exceeded for {secret}"}).encode("utf-8")
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        provider = OpenAICompatibleProvider(
            enabled=True,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key=secret,
            model="gpt-mock",
            provider_name="mock-openai",
            timeout=5,
        )
        result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.status == "error"
    assert result.error_type == "quota_rate_limit"
    assert secret not in result.error_message


def test_openai_compatible_provider_classifies_403_as_auth_failure():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.dumps({"error": "forbidden"}).encode("utf-8")
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        provider = OpenAICompatibleProvider(
            enabled=True,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="sk-test-403",
            model="gpt-mock",
            provider_name="mock-openai",
            timeout=5,
        )
        result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.status == "error"
    assert result.error_type == "auth_failure"


def test_openai_compatible_provider_classifies_429_as_quota():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.dumps({"error": "too many requests"}).encode("utf-8")
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        provider = OpenAICompatibleProvider(
            enabled=True,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="sk-test-429",
            model="gpt-mock",
            provider_name="mock-openai",
            timeout=5,
        )
        result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.status == "error"
    assert result.error_type == "quota_rate_limit"


def test_openai_compatible_provider_classifies_timeout(monkeypatch):
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:1/v1",
        api_key="sk-timeout-test",
        model="gpt-mock",
        provider_name="mock-openai",
        timeout=5,
    )

    def raise_timeout(*args, **kwargs):
        raise TimeoutError("operation timed out")

    monkeypatch.setattr("urllib.request.urlopen", raise_timeout)
    result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))

    assert result.status == "error"
    assert result.error_type == "timeout"


def test_router_disabled_preserves_legacy_translation_path(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    ai_service.config_manager.use_provider_router = False
    service.strategy = "google"

    monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: (_ for _ in ()).throw(AssertionError("router should stay disabled")))
    monkeypatch.setattr(GoogleTranslator, "translate", lambda self, text: "legacy-path")

    result = service.translate_text("Hello", "en", "vi")

    assert result == "legacy-path"


def test_google_strategy_legacy_path_does_not_call_router_or_ai(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    ai_service.config_manager.use_provider_router = False
    original_use_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    service.strategy = "google"

    try:
        monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: (_ for _ in ()).throw(AssertionError("router should not be called")))
        monkeypatch.setattr(ai_service, "translate", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("AI service should not be called")))
        monkeypatch.setattr(GoogleTranslator, "translate", lambda self, text: "google-only")

        result = service.translate_text("Hello unique google legacy path", "en", "vi")
    finally:
        ai_service.config_manager.use_translation_memory = original_use_tm

    assert result == "google-only"


def test_google_strategy_router_policy_only_allows_google(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    ai_service.config_manager.use_provider_router = True
    original_use_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    service.strategy = "google"
    captured = {}

    class CaptureRouter:
        def route(self, request, policy):
            captured["policy"] = policy
            return TranslationResult(status="success", text="router-google", provider="google", model="google-translate")

    try:
        monkeypatch.setattr(ai_service, "translate", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("AI service should not be called")))
        monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: CaptureRouter())
        result = service.translate_text("Hello router google only", "en", "vi")
    finally:
        ai_service.config_manager.use_translation_memory = original_use_tm

    assert result == "router-google"
    assert captured["policy"]["allowed_providers"] == ["google"]
    assert captured["policy"]["provider_order"] == ["google"]


def test_tm_lookup_still_happens_before_router(temp_db_path, monkeypatch):
    tm = get_tm_manager(temp_db_path)
    tm.save_segment("en", "vi", "Hello", "cached", provider="tm", model="tm-model")

    service = TranslationService()
    ai_service = get_ai_service()
    ai_service.config_manager.use_provider_router = True

    class FailRouter:
        def route(self, request, policy):
            raise AssertionError("router should not be called on TM hit")

    monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: FailRouter())

    result = service.translate_text("Hello", "en", "vi")

    assert result == "cached"


def test_glossary_terms_passed_to_ai_provider_request(temp_db_path, monkeypatch):
    tm = get_tm_manager(temp_db_path)
    tm.add_glossary_term("Apple", "Táo", "en", "vi", "fruit", "", True)

    service = TranslationService()
    service.strategy = "ai"
    ai_service = get_ai_service()
    ai_service.config_manager.use_provider_router = True
    ai_service.config_manager.use_glossary = True
    ai_service.config_manager.glossary_enforcement_level = "prompt"

    captured = {}

    class CaptureRouter:
        def route(self, request, policy):
            captured["glossary_terms"] = request.glossary_terms
            captured["policy"] = policy
            return TranslationResult(status="success", text="Táo", provider="gemini", model="mock-model")

    monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: CaptureRouter())

    result = service.translate_text("Apple", "en", "vi")

    assert result == "Táo"
    assert captured["glossary_terms"]
    assert captured["glossary_terms"][0]["source_term"] == "Apple"
    assert captured["policy"]["allowed_providers"] == ["gemini", "openai_compatible"]


def test_provider_health_snapshot_has_no_raw_keys():
    router = ProviderRouter(cooldown_seconds=60, max_retries=1)
    secret = "sk-should-not-appear-999"
    router.register_provider(
        OpenAICompatibleProvider(
            enabled=True,
            base_url="http://127.0.0.1:9/v1",
            api_key=secret,
            model="gpt-test",
            provider_name="openai_compatible",
        )
    )
    router.mark_failure("openai_compatible", "gpt-test", "429 rate limit")

    snapshot = router.get_health_snapshot()

    assert secret not in json.dumps(snapshot)
    assert snapshot[0]["provider_name"] == "openai_compatible"
    assert "api_key" not in snapshot[0]


def test_openai_compatible_provider_unavailable_without_key_when_local_not_allowed():
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key="",
        model="local-model",
        allow_no_key_local=False,
    )

    assert provider.is_available() is False


def test_openai_compatible_provider_available_without_key_for_local_when_allowed():
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key="",
        model="local-model",
        allow_no_key_local=True,
    )

    assert provider.is_available() is True


def test_reset_cooldowns_does_not_mutate_provider_credentials():
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key="sk-keep-me-123",
        model="local-model",
        provider_name="openai_compatible",
    )
    router = ProviderRouter(cooldown_seconds=60, max_retries=1)
    router.register_provider(provider)
    router.mark_failure("openai_compatible", "local-model", "429 quota exceeded")

    router.reset_cooldowns()

    assert provider.api_key == "sk-keep-me-123"
    snapshot = router.get_health_snapshot()
    assert snapshot[0]["cooldown_until"] == 0.0
    assert "api_key" not in snapshot[0]


def test_router_skips_quota_cooled_provider_on_next_route():
    router = ProviderRouter(cooldown_seconds=300, max_retries=2)
    gemini = DummyProvider("gemini", [{"status": "error", "error_message": "429 quota exceeded"}])
    google = DummyProvider("google", [{"status": "success", "text": "fallback"}])
    router.register_provider(gemini)
    router.register_provider(google)

    first_result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi"),
        {"allowed_providers": ["gemini", "google"], "provider_order": ["gemini", "google"]},
    )
    second_result = router.route(
        TranslationRequest(text="hello again", source_lang="en", target_lang="vi"),
        {"allowed_providers": ["gemini", "google"], "provider_order": ["gemini", "google"]},
    )

    assert first_result.status == "success"
    assert second_result.status == "success"
    assert second_result.attempts[0]["provider"] == "gemini"
    assert second_result.attempts[0]["reason"] == "cooldown"
    assert gemini.calls == 1
