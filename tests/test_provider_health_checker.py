import pytest
from translation_app.core.provider_health_checker import ProviderHealthChecker, ProviderHealthResult
from translation_app.core.provider_router import ProviderRouter, TranslationResult
from translation_app.core.providers import OpenAICompatibleProvider, GoogleTranslateProvider, GeminiProvider
from translation_app.core.ai_service import get_ai_service


class MockConfigManager:
    def __init__(self, providers_config=None, api_keys=None):
        self.providers_config = providers_config or {
            "gemini": {"enabled": True, "type": "gemini", "api_keys": ["fake-key-1"]},
            "groq": {"enabled": True, "type": "openai_compatible", "api_keys": ["fake-key-2"], "models": ["llama-1"]},
            "openrouter": {"enabled": False, "type": "openai_compatible", "api_keys": [], "models": ["llama-2"]}
        }
        self.api_keys = api_keys or ["fake-key-1"]
        self.api_key = "fake-key-1"
        self.waterfall_strategy = [{"model_id": "gemini-3.5-flash", "is_active": True}]
        self.provider_order = ["gemini", "groq", "openrouter", "google"]
        self.use_glossary = False
        self.provider_cooldown_seconds = 300
        self.provider_router_max_retries = 2
        self.provider_router_policy = "ai_pool_auto"

    def get_provider_profiles_public(self):
        return {k: {"enabled": v["enabled"], "api_keys": ["[REDACTED_API_KEY]"]} for k, v in self.providers_config.items()}

    def get_provider_model_catalog_snapshot(self):
        return {"providers": {}}

    def get_provider_model_catalog_public(self):
        return {"providers": {}}


def test_health_checker_missing_key():
    """Verify that a provider with empty API key pool triggers a missing_key result."""
    cfg = MockConfigManager()
    cfg.providers_config["groq"]["api_keys"] = []

    checker = ProviderHealthChecker(config_manager=cfg)
    result = checker.check_provider("groq")

    assert result.status == "missing_key"
    assert "Thiếu API Key" in result.message
    assert "dán vào cài đặt" in result.suggestion


def test_health_checker_ok(monkeypatch):
    """Verify that a successful provider check returns status 'ok' and latency metrics."""
    cfg = MockConfigManager()
    checker = ProviderHealthChecker(config_manager=cfg)

    def mock_translate(self, request, candidate=None):
        return TranslationResult(
            status="success",
            text="OK",
            provider=self.name,
            model="llama-1",
            latency_ms=120
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "translate", mock_translate)

    result = checker.check_provider("groq", "llama-1")
    assert result.status == "ok"
    assert result.latency_ms >= 0
    assert "Kết nối thành công" in result.message


def test_health_checker_auth_error(monkeypatch):
    """Verify that a 401/403 auth failure is categorized and does not leak secret key details."""
    cfg = MockConfigManager()
    checker = ProviderHealthChecker(config_manager=cfg)

    def mock_translate(self, request, candidate=None):
        return TranslationResult(
            status="error",
            provider=self.name,
            model="llama-1",
            error_type="auth_failure",
            error_message="HTTP 401: Unauthorized API key Bearer sk-fake-key-2",
            latency_ms=80
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "translate", mock_translate)

    result = checker.check_provider("groq")
    assert result.status == "auth_error"
    assert result.error_category == "auth_failure"
    assert "Lỗi xác thực" in result.message


def test_health_checker_quota_rate_limited(monkeypatch):
    """Verify that a 429 rate limit or quota exceeded status is correctly captured."""
    cfg = MockConfigManager()
    checker = ProviderHealthChecker(config_manager=cfg)

    def mock_translate(self, request, candidate=None):
        return TranslationResult(
            status="error",
            provider=self.name,
            model="llama-1",
            error_type="quota_rate_limit",
            error_message="HTTP 429: Too many requests",
            latency_ms=100
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "translate", mock_translate)

    result = checker.check_provider("groq")
    assert result.status == "quota_or_rate_limited"
    assert "Hết hạn mức" in result.message


def test_health_checker_timeout(monkeypatch):
    """Verify that timeouts are classified accurately."""
    cfg = MockConfigManager()
    checker = ProviderHealthChecker(config_manager=cfg)

    def mock_translate(self, request, candidate=None):
        return TranslationResult(
            status="error",
            provider=self.name,
            model="llama-1",
            error_type="timeout",
            error_message="Connection timed out",
            latency_ms=10000
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "translate", mock_translate)

    result = checker.check_provider("groq")
    assert result.status == "timeout"
    assert "Thời gian phản hồi" in result.message


def test_health_checker_model_not_found(monkeypatch):
    """Verify that an invalid or missing model error is classified correctly."""
    cfg = MockConfigManager()
    checker = ProviderHealthChecker(config_manager=cfg)

    def mock_translate(self, request, candidate=None):
        return TranslationResult(
            status="error",
            provider=self.name,
            model="llama-invalid",
            error_type="model_error",
            error_message="HTTP 400: Model not found",
            latency_ms=90
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "translate", mock_translate)

    result = checker.check_provider("groq", "llama-invalid")
    assert result.status == "model_not_found"
    assert "Mô hình" in result.message


def test_health_checker_check_provider_models(monkeypatch):
    """Verify check_provider_models yields multiple model audit records."""
    cfg = MockConfigManager()
    cfg.providers_config["groq"]["models"] = ["llama-1", "llama-2"]

    checker = ProviderHealthChecker(config_manager=cfg)

    def mock_translate(self, request, candidate=None):
        return TranslationResult(status="success", text="OK")

    monkeypatch.setattr(OpenAICompatibleProvider, "translate", mock_translate)

    results = checker.check_provider_models("groq")
    assert len(results) == 2
    assert results[0].model_id == "llama-1"
    assert results[1].model_id == "llama-2"


def test_health_checker_check_all_configured_skips_disabled(monkeypatch):
    """Verify that disabled providers are skipped during bulk checks."""
    cfg = MockConfigManager()
    cfg.providers_config["groq"]["enabled"] = True
    cfg.providers_config["openrouter"]["enabled"] = False  # Disabled

    checker = ProviderHealthChecker(config_manager=cfg)

    def mock_translate(self, request, candidate=None):
        return TranslationResult(status="success", text="OK")

    monkeypatch.setattr(OpenAICompatibleProvider, "translate", mock_translate)
    monkeypatch.setattr(GeminiProvider, "translate", mock_translate)

    results = checker.check_all_configured()
    # openrouter is disabled, so we only expect gemini and groq
    provider_ids = [r.provider_id for r in results]
    assert "gemini" in provider_ids
    assert "groq" in provider_ids
    assert "openrouter" not in provider_ids


def test_health_checker_endpoint_not_found(monkeypatch):
    """Verify that a general HTTP 404 is categorized as endpoint_not_found."""
    cfg = MockConfigManager()
    checker = ProviderHealthChecker(config_manager=cfg)

    def mock_translate(self, request, candidate=None):
        return TranslationResult(
            status="error",
            provider=self.name,
            model="llama-1",
            error_type="transport_error",
            error_message="HTTP 404: Not Found",
            latency_ms=80
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "translate", mock_translate)

    result = checker.check_provider("groq")
    assert result.status == "endpoint_not_found"
    assert "Sai URL/Endpoint" in result.message


def test_health_checker_payload_error(monkeypatch):
    """Verify that a HTTP 400 general error is categorized as payload_error."""
    cfg = MockConfigManager()
    checker = ProviderHealthChecker(config_manager=cfg)

    def mock_translate(self, request, candidate=None):
        return TranslationResult(
            status="error",
            provider=self.name,
            model="llama-1",
            error_type="model_error",
            error_message="HTTP 400: Bad Request",
            latency_ms=80
        )

    monkeypatch.setattr(OpenAICompatibleProvider, "translate", mock_translate)

    result = checker.check_provider("groq")
    assert result.status == "payload_error"
    assert "Tham số hoặc dữ liệu" in result.message


def test_health_checker_cancelled():
    """Verify that setting the cancel event triggers a cancelled result."""
    import threading
    cfg = MockConfigManager()
    cancel_evt = threading.Event()
    cancel_evt.set()

    checker = ProviderHealthChecker(config_manager=cfg, cancel_event=cancel_evt)
    result = checker.check_provider("groq")

    assert result.status == "cancelled"
    assert "đã bị dừng" in result.message


def test_health_checker_model_id_no_truncation(monkeypatch):
    """Verify that model IDs with slashes and colons are passed without modification."""
    cfg = MockConfigManager()
    checker = ProviderHealthChecker(config_manager=cfg)

    captured_model = []

    def mock_translate(self, request, candidate=None):
        captured_model.append(self.default_model)
        return TranslationResult(status="success", text="OK")

    monkeypatch.setattr(OpenAICompatibleProvider, "translate", mock_translate)

    model_id = "google/gemini-2.5-flash:free"
    result = checker.check_provider("groq", model_id=model_id)

    assert result.status == "ok"
    assert len(captured_model) == 1
    assert captured_model[0] == model_id
