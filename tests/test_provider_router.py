import json
import os
import tempfile
import threading
import time
import io
import urllib.error
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from deep_translator import GoogleTranslator

from translation_app.core.ai_service import get_ai_service
from translation_app.core.provider_router import ProviderRouter, TranslationRequest, TranslationResult, classify_error
from translation_app.core.providers import GeminiProvider, build_provider_profiles, get_default_provider_profiles
from translation_app.core.providers.base import BaseTranslationProvider, ProviderCandidate
from translation_app.core.providers.openai_compatible_provider import OpenAICompatibleProvider
from translation_app.core.translation_memory import get_tm_manager
from translation_app.core.translator import TranslationService
from translation_app.utils.error_handler import TranslationServiceError


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


def _set_enabled_providers(config_manager, enabled_provider_names):
    providers = config_manager.providers_config
    enabled = set(enabled_provider_names)
    for provider_name in providers:
        providers[provider_name]["enabled"] = provider_name in enabled
    config_manager.providers_config = providers


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

    def translate(self, request: TranslationRequest, candidate: ProviderCandidate | None = None) -> TranslationResult:
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
            key_id=response.get("key_id", candidate.key_id if candidate else ""),
            key_index=response.get("key_index", candidate.key_index if candidate else -1),
            error_type=response.get("error_type", ""),
            error_message=response.get("error_message", ""),
            latency_ms=response.get("latency_ms", 0),
        )


@contextmanager
def serve_json_response(status_code, payload, capture=None):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            if capture is not None:
                capture.append(
                    {
                        "path": self.path,
                        "auth": self.headers.get("Authorization", ""),
                        "body": json.loads(body),
                    }
                )
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
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
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_provider_profiles_default_disabled_except_safe_defaults():
    config_manager = get_ai_service().config_manager
    original = config_manager.providers_config
    config_manager.providers_config = get_default_provider_profiles()
    try:
        profiles = build_provider_profiles(config_manager)

        assert profiles["gemini"].enabled is True
        assert profiles["google"].enabled is True
        assert profiles["chatanywhere"].enabled is False
        assert profiles["deepseek"].enabled is False
        assert profiles["nvidia_nim"].enabled is False
        assert profiles["openai_compatible"].enabled is False
    finally:
        config_manager.providers_config = original


def test_chatanywhere_profile_uses_openai_compatible_endpoint():
    profiles = build_provider_profiles(get_ai_service().config_manager)
    profile = profiles["chatanywhere"]

    assert profile.provider_type == "openai_compatible"
    assert profile.base_url == "https://api.chatanywhere.tech/v1"


def test_deepseek_profile_uses_openai_compatible_endpoint():
    profiles = build_provider_profiles(get_ai_service().config_manager)
    profile = profiles["deepseek"]

    assert profile.provider_type == "openai_compatible"
    assert profile.base_url == "https://api.deepseek.com/v1"


def test_nvidia_nim_profile_uses_openai_compatible_endpoint():
    profiles = build_provider_profiles(get_ai_service().config_manager)
    profile = profiles["nvidia_nim"]

    assert profile.provider_type == "openai_compatible"
    assert profile.base_url == "https://integrate.api.nvidia.com/v1"


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


def test_strict_ai_policy_uses_ai_providers_without_google(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    for provider in ("gemini", "chatanywhere", "deepseek", "nvidia_nim", "openai_compatible", "google"):
        monkeypatch.setitem(ai_service.config_manager._config["providers"][provider], "enabled", True)
    monkeypatch.setitem(ai_service.config_manager._config["openai_compatible"], "enabled", True)
    ai_service.config_manager.use_provider_router = True
    service.strategy = "ai"

    policy = service._build_router_policy(ai_service.config_manager)

    assert policy["allowed_providers"] == ["gemini", "chatanywhere", "deepseek", "nvidia_nim", "openai_compatible"]
    assert "google" not in policy["allowed_providers"]


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


def test_ai_waterfall_provider_order_before_google(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    for provider in ("gemini", "chatanywhere", "deepseek", "nvidia_nim", "openai_compatible", "google"):
        monkeypatch.setitem(ai_service.config_manager._config["providers"][provider], "enabled", True)
    monkeypatch.setitem(ai_service.config_manager._config["openai_compatible"], "enabled", True)
    ai_service.config_manager.use_provider_router = True
    service.strategy = "ai_waterfall"

    policy = service._build_router_policy(ai_service.config_manager)

    assert policy["provider_order"] == [
        "gemini",
        "chatanywhere",
        "deepseek",
        "nvidia_nim",
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


def test_provider_key_rotation_is_runtime_only():
    provider = OpenAICompatibleProvider(
        profile=build_provider_profiles(get_ai_service().config_manager)["openai_compatible"].normalized()
    )
    provider.enabled = True
    provider.base_url = "http://127.0.0.1:8080/v1"
    provider.model_pool = ["gpt-a"]
    provider.api_key_pool = ["sk-key-1", "sk-key-2"]
    original_keys = list(provider.api_key_pool)

    first = provider.iter_candidates()
    provider.mark_failure(first[0], "quota_rate_limit")
    second = provider.iter_candidates()

    assert original_keys == ["sk-key-1", "sk-key-2"]
    assert first[0].key_index == 0
    assert second[0].key_index == 1


def test_provider_model_fallback_runtime_only():
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_keys=["sk-test-model"],
        models=["model-a", "model-b"],
        provider_name="deepseek",
    )
    original_models = list(provider.model_pool)

    first = provider.iter_candidates()
    provider.mark_failure(first[0], "model_error")
    second = provider.iter_candidates()

    assert original_models == ["model-a", "model-b"]
    assert first[0].model == "model-a"
    assert second[0].model == "model-b"


def test_router_strict_provider_model_reports_pinned_default_model_failure(monkeypatch):
    router = ProviderRouter(cooldown_seconds=60, max_retries=3)
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_keys=["sk-nvidia-strict"],
        models=["z-ai/glm-5.1", "meta/llama-3.1-70b-instruct"],
        provider_name="nvidia_nim",
    )
    router.register_provider(provider)
    seen_models = []

    def fake_translate(request, candidate=None):
        seen_models.append(candidate.model)
        return TranslationResult(
            status="error",
            provider="nvidia_nim",
            model=candidate.model,
            error_type="timeout",
            error_message="upstream timed out",
        )

    monkeypatch.setattr(provider, "translate", fake_translate)
    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi", strategy="nvidia_nim_only"),
        {
            "allowed_providers": ["nvidia_nim"],
            "provider_order": ["nvidia_nim"],
            "strict_provider_models": {"nvidia_nim": "z-ai/glm-5.1"},
        },
    )

    assert result.status == "error"
    assert seen_models == ["z-ai/glm-5.1"]
    assert result.model == "z-ai/glm-5.1"
    assert "z-ai/glm-5.1" in result.error_message
    assert "meta/llama-3.1-70b-instruct" not in seen_models


def test_nvidia_nim_only_policy_pins_default_model_and_preserves_success_metadata(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    original_use_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    _set_enabled_providers(ai_service.config_manager, {"nvidia_nim", "google"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "nvidia_nim_only"

    catalog = ai_service.config_manager.provider_model_catalog
    catalog["providers"]["nvidia_nim"]["default_model"] = "z-ai/glm-5.1"
    catalog["providers"]["nvidia_nim"]["models"] = [
        {"id": "z-ai/glm-5.1", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
        {"id": "meta/llama-3.1-70b-instruct", "enabled": True, "source": "seed", "capabilities": {"text": True, "vision": False}},
    ]
    ai_service.config_manager.provider_model_catalog = catalog
    captured = {}

    class CaptureRouter:
        def route(self, request, policy):
            captured["policy"] = policy
            return TranslationResult(
                status="success",
                text="nim-strict-ok",
                provider="nvidia_nim",
                model="z-ai/glm-5.1",
                attempts=[
                    {
                        "provider": "nvidia_nim",
                        "display_name": "NVIDIA NIM",
                        "model": "z-ai/glm-5.1",
                        "status": "success",
                    }
                ],
            )

    try:
        monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: CaptureRouter())
        result = service.translate_text("Hello strict NVIDIA", "en", "vi")
    finally:
        ai_service.config_manager.use_translation_memory = original_use_tm

    assert result == "nim-strict-ok"
    assert captured["policy"]["allowed_providers"] == ["nvidia_nim"]
    assert "google" not in captured["policy"]["allowed_providers"]
    assert captured["policy"]["strict_provider_models"] == {"nvidia_nim": "z-ai/glm-5.1"}
    assert service.last_translation_metadata["provider"] == "nvidia_nim"
    assert service.last_translation_metadata["model"] == "z-ai/glm-5.1"


def test_nvidia_nim_only_surfaces_pinned_default_model_failure_without_google_fallback(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    original_use_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    _set_enabled_providers(ai_service.config_manager, {"nvidia_nim", "google"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "nvidia_nim_only"

    providers = ai_service.config_manager.providers_config
    providers["nvidia_nim"]["base_url"] = "http://127.0.0.1:8080/v1"
    providers["nvidia_nim"]["api_keys"] = ["sk-nvidia-strict"]
    ai_service.config_manager.providers_config = providers

    catalog = ai_service.config_manager.provider_model_catalog
    catalog["providers"]["nvidia_nim"]["default_model"] = "z-ai/glm-5.1"
    catalog["providers"]["nvidia_nim"]["models"] = [
        {"id": "z-ai/glm-5.1", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
        {"id": "meta/llama-3.1-70b-instruct", "enabled": True, "source": "seed", "capabilities": {"text": True, "vision": False}},
    ]
    ai_service.config_manager.provider_model_catalog = catalog

    router = ProviderRouter(cooldown_seconds=60, max_retries=3)
    provider = OpenAICompatibleProvider(profile=build_provider_profiles(ai_service.config_manager)["nvidia_nim"])
    google = DummyProvider("google", [{"status": "success", "text": "wrong-google-fallback"}])
    router.register_provider(provider)
    router.register_provider(google)
    seen_models = []

    def fake_translate(request, candidate=None):
        seen_models.append(candidate.model)
        return TranslationResult(
            status="error",
            provider="nvidia_nim",
            model=candidate.model,
            error_type="timeout",
            error_message="upstream timed out",
        )

    try:
        monkeypatch.setattr(provider, "translate", fake_translate)
        monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: router)
        with pytest.raises(TranslationServiceError) as exc_info:
            service.translate_text("Hello strict NVIDIA failure", "en", "vi")
    finally:
        ai_service.config_manager.use_translation_memory = original_use_tm

    assert "z-ai/glm-5.1" in str(exc_info.value)
    assert seen_models == ["z-ai/glm-5.1"]
    assert google.calls == 0
    assert "meta/llama-3.1-70b-instruct" not in seen_models
    assert service.last_translation_metadata["provider"] == "nvidia_nim"
    assert service.last_translation_metadata["model"] == "z-ai/glm-5.1"


def test_gemini_strict_default_model_is_not_skipped_as_model_unavailable(monkeypatch):
    ai_service = get_ai_service()
    config_manager = ai_service.config_manager
    _set_enabled_providers(config_manager, {"gemini"})

    config_manager.provider_model_catalog = {
        **config_manager.provider_model_catalog,
        "providers": {
            **config_manager.provider_model_catalog.get("providers", {}),
            "gemini": {
                "default_model": "gemini-3.5-flash",
                "models": [
                    {"id": "gemini-3.5-flash", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
                    {"id": "gemini-2.5-flash", "enabled": True, "source": "seed", "capabilities": {"text": True, "vision": False}},
                ],
            },
        },
    }

    provider = GeminiProvider(profile=build_provider_profiles(config_manager)["gemini"])
    router = ProviderRouter(cooldown_seconds=60, max_retries=0)
    router.register_provider(provider)
    seen_models = []

    monkeypatch.setattr(provider, "is_available", lambda: True)

    def fake_translate(request, candidate=None):
        seen_models.append(candidate.model)
        return TranslationResult(
            status="error",
            provider="gemini",
            model=candidate.model,
            error_type="timeout",
            error_message="upstream timed out",
        )

    monkeypatch.setattr(provider, "translate", fake_translate)
    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi", strategy="gemini_only"),
        {
            "allowed_providers": ["gemini"],
            "provider_order": ["gemini"],
            "strict_provider_models": {"gemini": "gemini-3.5-flash"},
        },
    )

    assert result.status == "error"
    assert seen_models == ["gemini-3.5-flash"]
    assert all(attempt.get("reason") != "model_unavailable" for attempt in result.attempts)
    assert result.model == "gemini-3.5-flash"
    assert "gemini-3.5-flash" in result.error_message


def test_gemini_provider_translate_uses_runtime_candidate_model(monkeypatch):
    ai_service = get_ai_service()
    config_manager = ai_service.config_manager
    _set_enabled_providers(config_manager, {"gemini"})

    config_manager.provider_model_catalog = {
        **config_manager.provider_model_catalog,
        "providers": {
            **config_manager.provider_model_catalog.get("providers", {}),
            "gemini": {
                "default_model": "gemini-3.5-flash",
                "models": [
                    {"id": "gemini-3.5-flash", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
                ],
            },
        },
    }

    provider = GeminiProvider(profile=build_provider_profiles(config_manager)["gemini"])
    captured = {}

    def fake_translate_with_glossary_terms(*args, **kwargs):
        captured["preferred_models"] = kwargs.get("preferred_models")
        return {
            "status": "success",
            "text": "xin chao",
            "model_used": kwargs.get("preferred_models", [""])[0],
        }

    monkeypatch.setattr(ai_service, "translate_with_glossary_terms", fake_translate_with_glossary_terms)
    result = provider.translate(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi"),
        ProviderCandidate(provider_name="gemini", model="gemini-3.5-flash"),
    )

    assert captured["preferred_models"] == ["gemini-3.5-flash"]
    assert result.status == "success"
    assert result.model == "gemini-3.5-flash"


def test_gemini_only_policy_pins_default_model_and_preserves_success_metadata(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    original_use_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    _set_enabled_providers(ai_service.config_manager, {"gemini", "google"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "gemini_only"

    catalog = ai_service.config_manager.provider_model_catalog
    catalog["providers"]["gemini"]["default_model"] = "gemini-3.5-flash"
    catalog["providers"]["gemini"]["models"] = [
        {"id": "gemini-3.5-flash", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
        {"id": "gemini-2.5-flash", "enabled": True, "source": "seed", "capabilities": {"text": True, "vision": False}},
    ]
    ai_service.config_manager.provider_model_catalog = catalog
    captured = {}

    class CaptureRouter:
        def route(self, request, policy):
            captured["policy"] = policy
            return TranslationResult(
                status="success",
                text="gemini-strict-ok",
                provider="gemini",
                model="gemini-3.5-flash",
                attempts=[
                    {
                        "provider": "gemini",
                        "display_name": "Gemini",
                        "model": "gemini-3.5-flash",
                        "status": "success",
                    }
                ],
            )

    try:
        monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: CaptureRouter())
        result = service.translate_text("Hello strict Gemini", "en", "vi")
    finally:
        ai_service.config_manager.use_translation_memory = original_use_tm

    assert result == "gemini-strict-ok"
    assert captured["policy"]["allowed_providers"] == ["gemini"]
    assert "google" not in captured["policy"]["allowed_providers"]
    assert captured["policy"]["strict_provider_models"] == {"gemini": "gemini-3.5-flash"}
    assert service.last_translation_metadata["provider"] == "gemini"
    assert service.last_translation_metadata["model"] == "gemini-3.5-flash"


def test_gemini_only_surfaces_pinned_default_model_failure_without_google_fallback(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    original_use_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    _set_enabled_providers(ai_service.config_manager, {"gemini", "google"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "gemini_only"

    catalog = ai_service.config_manager.provider_model_catalog
    catalog["providers"]["gemini"]["default_model"] = "gemini-3.5-flash"
    catalog["providers"]["gemini"]["models"] = [
        {"id": "gemini-3.5-flash", "enabled": True, "source": "user", "capabilities": {"text": True, "vision": False}},
        {"id": "gemini-2.5-flash", "enabled": True, "source": "seed", "capabilities": {"text": True, "vision": False}},
    ]
    ai_service.config_manager.provider_model_catalog = catalog

    router = ProviderRouter(cooldown_seconds=60, max_retries=0)
    provider = GeminiProvider(profile=build_provider_profiles(ai_service.config_manager)["gemini"])
    google = DummyProvider("google", [{"status": "success", "text": "wrong-google-fallback"}])
    router.register_provider(provider)
    router.register_provider(google)
    seen_models = []

    def fake_translate(request, candidate=None):
        seen_models.append(candidate.model)
        return TranslationResult(
            status="error",
            provider="gemini",
            model=candidate.model,
            error_type="timeout",
            error_message="upstream timed out",
        )

    try:
        monkeypatch.setattr(provider, "is_available", lambda: True)
        monkeypatch.setattr(provider, "translate", fake_translate)
        monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: router)
        with pytest.raises(TranslationServiceError) as exc_info:
            service.translate_text("Hello strict Gemini failure", "en", "vi")
    finally:
        ai_service.config_manager.use_translation_memory = original_use_tm

    assert "gemini-3.5-flash" in str(exc_info.value)
    assert seen_models == ["gemini-3.5-flash"]
    assert google.calls == 0
    assert service.last_translation_metadata["provider"] == "gemini"
    assert service.last_translation_metadata["model"] == "gemini-3.5-flash"


def test_openai_compatible_provider_redacts_key_and_classifies_auth_http_error(monkeypatch):
    secret = "sk-auth-secret-123"
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key=secret,
        model="gpt-mock",
        provider_name="mock-openai",
        timeout=5,
    )

    def raise_http_error(*args, **kwargs):
        payload = json.dumps({"error": f"invalid api key {secret}"}).encode("utf-8")
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8080/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(payload),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))

    assert result.status == "error"
    assert result.error_type == "auth_failure"
    assert secret not in result.error_message
    assert "[REDACTED_API_KEY]" in result.error_message


def test_provider_specific_auth_error_classification():
    with serve_json_response(401, {"error": {"message": "authentication failed", "code": "invalid_api_key"}}) as server:
        result = OpenAICompatibleProvider(
            enabled=True,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="sk-provider-auth",
            model="deepseek-v4-flash",
            provider_name="deepseek",
        ).translate(
            TranslationRequest(text="Hello", source_lang="en", target_lang="vi"),
            ProviderCandidate("deepseek", "deepseek-v4-flash", 0, "****auth"),
        )

    assert result.status == "error"
    assert result.error_type == "auth_failure"


def test_openai_compatible_provider_classifies_quota_http_error():
    secret = "sk-quota-secret-456"

    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key=secret,
        model="gpt-mock",
        provider_name="mock-openai",
        timeout=5,
    )

    def raise_http_error(*args, **kwargs):
        payload = json.dumps({"error": f"429 quota exceeded for {secret}"}).encode("utf-8")
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8080/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(payload),
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    try:
        result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))
    finally:
        monkeypatch.undo()

    assert result.status == "error"
    assert result.error_type == "quota_rate_limit"
    assert secret not in result.error_message


def test_generic_exception_with_response_429_classifies_quota():
    class FakeResponse:
        status_code = 429
        text = '{"error":"rate limit exceeded"}'

    class FakeError(Exception):
        def __init__(self):
            super().__init__("request failed")
            self.response = FakeResponse()

    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key="sk-generic-429",
        model="gpt-mock",
        provider_name="mock-openai",
        timeout=5,
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(FakeError()))
    try:
        result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))
    finally:
        monkeypatch.undo()

    assert result.status == "error"
    assert result.error_type == "quota_rate_limit"


def test_quota_error_sanitizes_authorization_header(monkeypatch):
    secret = "sk-quota-secret-auth-999"
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key=secret,
        model="gpt-mock",
        provider_name="mock-openai",
        timeout=5,
    )

    def raise_http_error(*args, **kwargs):
        payload = json.dumps({"error": f"Authorization: Bearer {secret} quota exceeded"}).encode("utf-8")
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8080/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(payload),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))

    assert result.status == "error"
    assert result.error_type == "quota_rate_limit"
    assert secret not in result.error_message
    assert "Authorization: Bearer" not in result.error_message
    assert "Authorization: [REDACTED_API_KEY]" in result.error_message


def test_provider_specific_quota_error_classification():
    with serve_json_response(429, {"error": {"message": "resource exhausted", "type": "rate_limit"}}) as server:
        result = OpenAICompatibleProvider(
            enabled=True,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="sk-provider-quota",
            model="meta/llama-3.1-405b-instruct",
            provider_name="nvidia_nim",
        ).translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))

    assert result.status == "error"
    assert result.error_type == "quota_rate_limit"


def test_openai_compatible_provider_classifies_403_as_auth_failure(monkeypatch):
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key="sk-test-403",
        model="gpt-mock",
        provider_name="mock-openai",
        timeout=5,
    )

    def raise_http_error(*args, **kwargs):
        payload = json.dumps({"error": "forbidden"}).encode("utf-8")
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8080/v1/chat/completions",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(payload),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))

    assert result.status == "error"
    assert result.error_type == "auth_failure"


def test_openai_compatible_provider_classifies_429_as_quota(monkeypatch):
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key="sk-test-429",
        model="gpt-mock",
        provider_name="mock-openai",
        timeout=5,
    )

    def raise_http_error(*args, **kwargs):
        payload = json.dumps({"error": "too many requests"}).encode("utf-8")
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8080/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(payload),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))

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


def test_classify_error_uses_status_code_even_if_body_is_empty():
    assert classify_error("plain failure", status_code=403, response_body="") == "auth_failure"
    assert classify_error("plain failure", status_code=429, response_body="") == "quota_rate_limit"


def test_classify_error_uses_body_when_status_missing():
    assert classify_error(Exception("request failed"), response_body="forbidden") == "auth_failure"
    assert classify_error(Exception("request failed"), response_body="too many requests") == "quota_rate_limit"


def test_http_error_body_is_sanitized_without_losing_error_type(monkeypatch):
    secret = "sk-sanitize-999"
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key=secret,
        model="gpt-mock",
        provider_name="mock-openai",
        timeout=5,
    )

    def raise_http_error(*args, **kwargs):
        payload = json.dumps({"error": f"forbidden token {secret}"}).encode("utf-8")
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8080/v1/chat/completions",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(payload),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))

    assert result.status == "error"
    assert result.error_type == "auth_failure"
    assert secret not in result.error_message
    assert "[REDACTED_API_KEY]" in result.error_message


def test_provider_result_does_not_leak_authorization_or_api_key_on_http_error(monkeypatch):
    secret = "sk-leak-check-0001"
    provider = OpenAICompatibleProvider(
        enabled=True,
        base_url="http://127.0.0.1:8080/v1",
        api_key=secret,
        model="gpt-mock",
        provider_name="mock-openai",
        timeout=5,
    )

    def raise_http_error(*args, **kwargs):
        payload = json.dumps({"error": f"Authorization: Bearer {secret}"}).encode("utf-8")
        raise urllib.error.HTTPError(
            url="http://127.0.0.1:8080/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(payload),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))

    assert result.status == "error"
    assert result.error_type == "auth_failure"
    assert secret not in result.error_message
    assert "Authorization: Bearer" not in result.error_message
    assert "Authorization: [REDACTED_API_KEY]" in result.error_message


def test_openai_compatible_provider_handles_nvidia_nim_mock():
    requests_seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            requests_seen.append(json.loads(body))
            payload = {"choices": [{"message": {"content": "nim-ok"}}]}
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
            api_key="sk-nvidia-mock",
            model="meta/llama-3.1-405b-instruct",
            provider_name="nvidia_nim",
        )
        result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.status == "success"
    assert result.text == "nim-ok"
    assert requests_seen[0]["model"] == "meta/llama-3.1-405b-instruct"


def test_openai_compatible_provider_handles_deepseek_mock():
    requests_seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            requests_seen.append(json.loads(body))
            payload = {"choices": [{"message": {"content": "deepseek-ok"}}]}
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
            api_key="sk-deepseek-mock",
            model="deepseek-v4-flash",
            provider_name="deepseek",
        )
        result = provider.translate(TranslationRequest(text="Hello", source_lang="en", target_lang="vi"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.status == "success"
    assert result.text == "deepseek-ok"
    assert requests_seen[0]["model"] == "deepseek-v4-flash"


def test_router_disabled_preserves_legacy_translation_path(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    ai_service.config_manager.use_provider_router = False
    service.strategy = "google"
    original_use_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False

    try:
        monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: (_ for _ in ()).throw(AssertionError("router should stay disabled")))
        monkeypatch.setattr(GoogleTranslator, "translate", lambda self, text: "legacy-path")

        result = service.translate_text("Hello", "en", "vi")

        assert result == "legacy-path"
    finally:
        ai_service.config_manager.use_translation_memory = original_use_tm


def test_google_strategy_legacy_path_does_not_call_router_or_ai(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    _set_enabled_providers(ai_service.config_manager, {"google"})
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
    _set_enabled_providers(ai_service.config_manager, {"google"})
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
    for provider in ("gemini", "chatanywhere", "deepseek", "nvidia_nim", "openai_compatible", "google"):
        monkeypatch.setitem(ai_service.config_manager._config["providers"][provider], "enabled", True)
    monkeypatch.setitem(ai_service.config_manager._config["openai_compatible"], "enabled", True)
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
    assert captured["policy"]["allowed_providers"] == [
        "gemini",
        "chatanywhere",
        "deepseek",
        "nvidia_nim",
        "openai_compatible",
    ]


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


def test_disabled_provider_is_skipped():
    router = ProviderRouter(cooldown_seconds=60, max_retries=3)
    disabled = DummyProvider("chatanywhere", [{"status": "success", "text": "wrong"}], available=False)
    fallback = DummyProvider("google", [{"status": "success", "text": "google-ok"}])
    router.register_provider(disabled)
    router.register_provider(fallback)

    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi"),
        {"allowed_providers": ["chatanywhere", "google"], "provider_order": ["chatanywhere", "google"]},
    )

    assert result.status == "success"
    assert result.text == "google-ok"
    assert disabled.calls == 0
    assert result.attempts[0]["provider"] == "chatanywhere"
    assert result.attempts[0]["reason"] == "unavailable"


def test_health_snapshot_redacts_all_provider_keys():
    profiles = build_provider_profiles(get_ai_service().config_manager)
    profiles["chatanywhere"].enabled = True
    profiles["chatanywhere"].api_key_pool = ["sk-chat-1111", "sk-chat-2222"]
    profiles["chatanywhere"].model_pool = ["gpt-4o-mini"]

    provider = OpenAICompatibleProvider(profile=profiles["chatanywhere"])
    router = ProviderRouter(cooldown_seconds=60, max_retries=2)
    router.register_provider(provider)
    for candidate in provider.iter_candidates():
        router.mark_failure(
            provider.name,
            candidate.model,
            "429 quota exceeded",
            key_index=candidate.key_index,
            key_id=candidate.key_id,
        )

    snapshot_json = json.dumps(router.get_health_snapshot())

    assert "sk-chat-1111" not in snapshot_json
    assert "sk-chat-2222" not in snapshot_json
    assert "****1111" in snapshot_json
    assert "****2222" in snapshot_json


def test_router_does_not_mutate_provider_config_on_cooldown():
    ai_service = get_ai_service()
    config_manager = ai_service.config_manager
    original = config_manager.providers_config
    updated = json.loads(json.dumps(original))
    updated["deepseek"]["enabled"] = True
    updated["deepseek"]["api_keys"] = ["sk-deepseek-1234", "sk-deepseek-5678"]
    updated["deepseek"]["models"] = ["deepseek-v4-flash", "deepseek-v4-pro"]
    config_manager.providers_config = updated

    try:
        profile_before = json.loads(json.dumps(config_manager.providers_config["deepseek"]))
        provider = OpenAICompatibleProvider(profile=build_provider_profiles(config_manager)["deepseek"])
        router = ProviderRouter(cooldown_seconds=60, max_retries=2)
        router.register_provider(provider)
        first_candidate = provider.iter_candidates()[0]
        router.mark_failure(
            provider.name,
            first_candidate.model,
            "429 quota exceeded",
            key_index=first_candidate.key_index,
            key_id=first_candidate.key_id,
        )
        provider.mark_failure(first_candidate, "quota_rate_limit")

        assert config_manager.providers_config["deepseek"] == profile_before
    finally:
        config_manager.providers_config = original


def test_google_can_be_disabled_from_router_candidates(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    _set_enabled_providers(ai_service.config_manager, {"gemini"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "ai_waterfall"

    policy = service._build_router_policy(ai_service.config_manager)
    assert "google" not in policy["allowed_providers"]


def test_waterfall_keeps_google_fallback_even_if_google_provider_toggle_is_off(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    _set_enabled_providers(ai_service.config_manager, {"deepseek"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "waterfall"

    policy = service._build_router_policy(ai_service.config_manager)

    assert policy["allowed_providers"] == ["deepseek", "google"]
    assert policy["provider_order"] == ["deepseek", "google"]


def test_waterfall_policy_passes_google_fallback_to_router_when_google_toggle_is_off(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    original_use_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    _set_enabled_providers(ai_service.config_manager, {"deepseek"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "waterfall"
    captured = {}

    class CaptureRouter:
        def route(self, request, policy):
            captured["policy"] = policy
            return TranslationResult(
                status="success",
                text="fallback-google-ok",
                provider="google",
                model="google-translate",
                attempts=[
                    {"provider": "deepseek", "display_name": "DeepSeek", "model": "deepseek-v4-flash", "status": "failed"},
                    {"provider": "google", "display_name": "Google Translate", "model": "google-translate", "status": "success"},
                ],
            )

    try:
        monkeypatch.setattr(TranslationService, "_get_provider_router", lambda self, _ai_service: CaptureRouter())
        result = service.translate_text("Hello fallback semantics", "en", "vi")
    finally:
        ai_service.config_manager.use_translation_memory = original_use_tm

    assert result == "fallback-google-ok"
    assert captured["policy"]["allowed_providers"] == ["deepseek", "google"]
    assert captured["policy"]["provider_order"] == ["deepseek", "google"]
    assert service.last_translation_metadata["provider"] == "google"
    assert service.last_translation_metadata["model"] == "google-translate"


def test_ai_only_strategy_never_uses_google(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    _set_enabled_providers(ai_service.config_manager, {"gemini", "google"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "ai"

    policy = service._build_router_policy(ai_service.config_manager)
    assert "google" not in policy["allowed_providers"]


def test_translation_result_exposes_provider_model_metadata(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    ai_service.config_manager.use_provider_router = True
    
    # 1. Test TM Lookup metadata
    # Fake lookups
    class DummyTM:
        def lookup_segment(self, src, dest, text):
            return "cached-text"
            
    from translation_app.core import translation_memory
    monkeypatch.setattr(translation_memory, "get_tm_manager", lambda *args: DummyTM())
    
    res = service.translate_text("hello", "en", "vi")
    assert res == "cached-text"
    assert service.last_translation_metadata["provider"] == "translation_memory"
    assert service.last_translation_metadata["model"] == "cache"
    
    # 2. Test active router metadata
    class FakeRouter:
        def route(self, request, policy):
            return TranslationResult(
                status="success",
                text="routed-text",
                provider="deepseek",
                model="deepseek-chat",
                attempts=[
                    {"provider": "gemini", "model": "gemini-flash", "status": "failed", "reason": "quota"},
                    {"provider": "deepseek", "model": "deepseek-chat", "status": "success"}
                ]
            )
            
    ai_service.config_manager.use_translation_memory = False
    monkeypatch.setattr(service, "_get_provider_router", lambda *args: FakeRouter())
    
    res2 = service.translate_text("hello", "en", "vi")
    assert res2 == "routed-text"
    assert service.last_translation_metadata["provider"] == "deepseek"
    assert service.last_translation_metadata["model"] == "deepseek-chat"
    assert service.last_translation_metadata["fallback_count"] == 1
    assert len(service.last_translation_metadata["attempts"]) == 2
