import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import pytest

from translation_app.core.ai_service import get_ai_service
from translation_app.core.provider_router import ProviderRouter, TranslationRequest, TranslationResult, classify_error
from translation_app.core.providers import GeminiProvider, GoogleTranslateProvider, OpenAICompatibleProvider, CloudflareProvider, HuggingFaceProvider, build_provider_profiles, get_default_provider_profiles
from translation_app.core.providers.base import BaseTranslationProvider, ProviderCandidate
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
            latency_ms=response.get("latency_ms", 100),
        )


def test_custom_adapters_cloudflare_instantiation():
    profile = build_provider_profiles(get_ai_service().config_manager)["cloudflare"]
    assert profile.provider_type == "cloudflare"
    assert "accounts/{account_id}/ai" in profile.base_url

    provider = CloudflareProvider(profile=profile)
    assert provider.name == "cloudflare"
    assert provider.default_model == "@cf/meta/llama-3-8b-instruct"


def test_custom_adapters_huggingface_instantiation():
    profile = build_provider_profiles(get_ai_service().config_manager)["huggingface"]
    assert profile.provider_type == "huggingface"
    assert "api-inference.huggingface.co" in profile.base_url

    provider = HuggingFaceProvider(profile=profile)
    assert provider.name == "huggingface"
    assert provider.default_model == "meta-llama/Meta-Llama-3-8B-Instruct"


def test_free_pool_routing_policy_sorting_auto():
    router = ProviderRouter(cooldown_seconds=60, max_retries=2)
    p_gemini = DummyProvider("gemini", [{"status": "success", "text": "gemini-ok"}])
    p_groq = DummyProvider("groq", [{"status": "success", "text": "groq-ok"}])
    p_google = DummyProvider("google", [{"status": "success", "text": "google-ok"}])

    router.register_provider(p_gemini)
    router.register_provider(p_groq)
    router.register_provider(p_google)

    # Under pool policy, we should sort by quality first: Gemini (9.0) > Groq (7.5) > Google (5.0)
    ordered = router._resolve_order(
        preferred=["google", "groq", "gemini"],
        allowed=["gemini", "groq", "google"],
        policy={"mode": "ai_pool_auto"}
    )

    assert ordered == ["gemini", "groq", "google"]


def test_free_pool_routing_policy_sorting_google_last_resort():
    router = ProviderRouter(cooldown_seconds=60, max_retries=2)
    p_gemini = DummyProvider("gemini", [{"status": "success", "text": "gemini-ok"}])
    p_groq = DummyProvider("groq", [{"status": "success", "text": "groq-ok"}])
    p_google = DummyProvider("google", [{"status": "success", "text": "google-ok"}])

    router.register_provider(p_gemini)
    router.register_provider(p_groq)
    router.register_provider(p_google)

    # Gemini (9) and Groq (7.5) are higher priority than Google Translate (5)
    # Even if Google Translate is preferred in the config list, with google_last_resort it's pushed to the absolute end
    ordered = router._resolve_order(
        preferred=["google", "gemini", "groq"],
        allowed=["gemini", "groq", "google"],
        policy={"mode": "ai_pool_with_google_last_resort"}
    )

    assert ordered == ["gemini", "groq", "google"]


def test_free_pool_routing_policy_sorting_with_failures_and_latency():
    router = ProviderRouter(cooldown_seconds=60, max_retries=2)
    p_gemini = DummyProvider("gemini", [{"status": "success", "text": "gemini-ok"}])
    p_groq = DummyProvider("groq", [{"status": "success", "text": "groq-ok"}])
    p_cerebras = DummyProvider("cerebras", [{"status": "success", "text": "cerebras-ok"}])

    router.register_provider(p_gemini)
    router.register_provider(p_groq)
    router.register_provider(p_cerebras)

    # Mark gemini on cooldown, cerebras degraded, groq healthy
    router.mark_failure("gemini", "gemini-model", "quota_rate_limit") # health_status -> cooldown, status_rank = 3

    # Mark groq healthy with latency 200
    router.mark_success("groq", "groq-model", latency_ms=200) # health_status -> healthy, quality = 7.5

    # Mark cerebras healthy with latency 100
    router.mark_success("cerebras", "cerebras-model", latency_ms=100) # health_status -> healthy, quality = 7.5

    # Both groq and cerebras are healthy AI (rank 0), so we sort by quality (both 7.5) and then latency: cerebras (100) > groq (200)
    # Gemini is on cooldown (rank 3) so it sits at the bottom
    ordered = router._resolve_order(
        preferred=["gemini", "groq", "cerebras"],
        allowed=["gemini", "groq", "cerebras"],
        policy={"mode": "ai_pool_auto"}
    )

    assert ordered == ["cerebras", "groq", "gemini"]


def test_provider_quota_fail_shifts_provider():
    router = ProviderRouter(cooldown_seconds=300, max_retries=2)
    first = DummyProvider("groq", [{"status": "error", "error_type": "quota_rate_limit"}])
    second = DummyProvider("cerebras", [{"status": "success", "text": "cerebras-ok"}])
    router.register_provider(first)
    router.register_provider(second)

    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi"),
        {"allowed_providers": ["groq", "cerebras"], "provider_order": ["groq", "cerebras"]}
    )

    assert result.status == "success"
    assert result.text == "cerebras-ok"
    assert first.calls == 1
    assert second.calls == 1

    # Check that groq is now on cooldown
    snapshot = router.get_health_snapshot()
    groq_state = next(item for item in snapshot if item["provider_name"] == "groq")
    assert groq_state["is_available"] is False
    assert groq_state["cooldown_until"] > 0


def test_no_google_mode_never_calls_google():
    router = ProviderRouter(cooldown_seconds=60, max_retries=2)
    failing_ai = DummyProvider("groq", [{"status": "error", "error_type": "timeout"}])
    google = DummyProvider("google", [{"status": "success", "text": "google-fallback"}])
    router.register_provider(failing_ai)
    router.register_provider(google)

    # If mode is ai_pool_no_google, allowed_providers does not include google
    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi"),
        {
            "mode": "ai_pool_no_google",
            "allowed_providers": ["groq"],
            "provider_order": ["groq"]
        }
    )

    assert result.status == "error"
    assert google.calls == 0


def test_google_last_resort_only_called_on_complete_failure():
    router = ProviderRouter(cooldown_seconds=60, max_retries=2)
    first_ai = DummyProvider("groq", [{"status": "error", "error_type": "timeout"}])
    second_ai = DummyProvider("cerebras", [{"status": "error", "error_type": "provider_5xx"}])
    google = DummyProvider("google", [{"status": "success", "text": "google-fallback-last-resort"}])
    router.register_provider(first_ai)
    router.register_provider(second_ai)
    router.register_provider(google)

    result = router.route(
        TranslationRequest(text="hello", source_lang="en", target_lang="vi"),
        {
            "mode": "ai_pool_with_google_last_resort",
            "allowed_providers": ["groq", "cerebras", "google"],
            "provider_order": ["groq", "cerebras", "google"]
        }
    )

    assert result.status == "success"
    assert result.text == "google-fallback-last-resort"
    assert first_ai.calls == 1
    assert second_ai.calls == 1
    assert google.calls == 1


def test_auth_failure_circuit_breaker_persistently_disables_provider(monkeypatch):
    ai_service = get_ai_service()
    config_mgr = ai_service.config_manager

    # Enable groq in config
    providers = config_mgr.providers_config
    providers["groq"]["enabled"] = True
    config_mgr.providers_config = providers
    assert config_mgr.providers_config["groq"]["enabled"] is True

    router = ProviderRouter(cooldown_seconds=60, max_retries=1)
    # We mock mark_failure call or classification
    router.mark_failure("groq", "llama3-8b-8192", "401 Unauthorized")

    # Groq should be persistently disabled in the configuration!
    assert config_mgr.providers_config["groq"]["enabled"] is False


def test_config_manager_deep_merge_preserves_5i_providers():
    from translation_app.core.ai_service import AIConfigManager
    # Mock loaded config data from an old JSON file containing only old providers
    old_loaded_data = {
        "providers": {
            "gemini": {"enabled": True, "api_keys": ["old-gemini-key"]},
            "google": {"enabled": True}
        }
    }

    config_mgr = AIConfigManager(config_path=None) # temporary in-memory instance
    merged = config_mgr._merge_with_defaults(old_loaded_data)

    # All 15 providers should be loaded and seeded correctly!
    assert "providers" in merged
    assert "groq" in merged["providers"]
    assert "cerebras" in merged["providers"]
    assert "openrouter" in merged["providers"]
    assert "cloudflare" in merged["providers"]
    assert "huggingface" in merged["providers"]

    # Existing loaded fields should be preserved
    assert merged["providers"]["gemini"]["enabled"] is True
    assert merged["providers"]["gemini"]["api_keys"] == ["old-gemini-key"]
    assert merged["providers"]["groq"]["enabled"] is False # default from profiles


def test_disabled_google_is_completely_excluded_from_pool_strategies():
    from translation_app.core.ai_service import get_ai_service
    from translation_app.core.translator import TranslationService

    ai_service = get_ai_service()
    config_mgr = ai_service.config_manager
    original_config = config_mgr.providers_config
    try:
        # 1. Enable google in settings
        providers = config_mgr.providers_config
        providers["google"]["enabled"] = True
        config_mgr.providers_config = providers

        ts = TranslationService()

        # Under pool strategy with Google, allowed should include Google
        ts.strategy = "ai_pool_with_google_last_resort"
        policy = ts._build_router_policy(config_mgr)
        assert "google" in policy["allowed_providers"]

        # 2. Now disable google in settings
        providers = config_mgr.providers_config
        providers["google"]["enabled"] = False
        config_mgr.providers_config = providers

        # Re-build policy under last-resort strategy
        policy = ts._build_router_policy(config_mgr)

        # Google MUST be completely excluded from allowed list because user explicitly disabled it
        assert "google" not in policy["allowed_providers"]

        # Re-build policy under auto pool strategy
        ts.strategy = "ai_pool_auto"
        policy = ts._build_router_policy(config_mgr)
        assert "google" not in policy["allowed_providers"]
    finally:
        config_mgr.providers_config = original_config
