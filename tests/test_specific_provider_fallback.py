import pytest
from translation_app.core.translator import TranslationService
from translation_app.core.ai_service import get_ai_service
from translation_app.core.provider_router import ProviderRouter, TranslationResult
from translation_app.utils.error_handler import TranslationServiceError


def _set_enabled_providers(config_manager, enabled_set):
    providers = config_manager.providers_config
    for provider in ("gemini", "chatanywhere", "deepseek", "nvidia_nim", "openai_compatible", "google"):
        if provider in providers:
            providers[provider]["enabled"] = (provider in enabled_set)
    config_manager.providers_config = providers
    config_manager.save_config()


def test_gemini_only_never_falls_back_to_google(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    
    # Disable TM and enable gemini/google
    original_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    
    _set_enabled_providers(ai_service.config_manager, {"gemini", "google"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "gemini_only"

    # Mock router to fail gemini and assert it is the only one tried
    class MockRouter:
        def route(self, request, policy):
            assert policy["allowed_providers"] == ["gemini"]
            return TranslationResult(
                status="error",
                provider="gemini",
                error_type="api_error",
                error_message="Gemini mock failed",
                attempts=[{"provider": "gemini", "status": "failed", "reason": "api_error"}]
            )

    try:
        monkeypatch.setattr(service, "_get_provider_router", lambda *args: MockRouter())
        
        with pytest.raises(TranslationServiceError) as exc_info:
            service.translate_text("Hello unique gemini strict text", "en", "vi")
        
        assert "Gemini mock failed" in str(exc_info.value)
    finally:
        ai_service.config_manager.use_translation_memory = original_tm


def test_deepseek_only_never_falls_back_to_google_or_gemini(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    
    original_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    
    _set_enabled_providers(ai_service.config_manager, {"gemini", "deepseek", "google"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "deepseek_only"

    class MockRouter:
        def route(self, request, policy):
            assert policy["allowed_providers"] == ["deepseek"]
            return TranslationResult(
                status="error",
                provider="deepseek",
                error_type="quota_limit",
                error_message="DeepSeek mock failed",
                attempts=[{"provider": "deepseek", "status": "failed", "reason": "quota_limit"}]
            )

    try:
        monkeypatch.setattr(service, "_get_provider_router", lambda *args: MockRouter())
        
        with pytest.raises(TranslationServiceError) as exc_info:
            service.translate_text("Hello unique deepseek strict text", "en", "vi")
            
        assert "DeepSeek mock failed" in str(exc_info.value)
    finally:
        ai_service.config_manager.use_translation_memory = original_tm


def test_google_only_uses_google(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    
    original_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    
    _set_enabled_providers(ai_service.config_manager, {"google", "gemini"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "google"

    class MockRouter:
        def route(self, request, policy):
            assert policy["allowed_providers"] == ["google"]
            return TranslationResult(
                status="success",
                text="xin chào google",
                provider="google",
                model="google-translate",
                attempts=[{"provider": "google", "status": "success"}]
            )

    try:
        monkeypatch.setattr(service, "_get_provider_router", lambda *args: MockRouter())
        
        res = service.translate_text("Hello unique google strict text", "en", "vi")
        assert res == "xin chào google"
    finally:
        ai_service.config_manager.use_translation_memory = original_tm


def test_ai_only_never_uses_google_even_when_ai_fail(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    
    original_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    
    _set_enabled_providers(ai_service.config_manager, {"gemini", "google"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "ai"

    class MockRouter:
        def route(self, request, policy):
            assert "google" not in policy["allowed_providers"]
            return TranslationResult(
                status="error",
                provider="gemini",
                error_type="quota_limit",
                error_message="AI failed",
                attempts=[{"provider": "gemini", "status": "failed", "reason": "quota_limit"}]
            )

    try:
        monkeypatch.setattr(service, "_get_provider_router", lambda *args: MockRouter())
        
        with pytest.raises(TranslationServiceError):
            service.translate_text("Hello unique ai strict text", "en", "vi")
    finally:
        ai_service.config_manager.use_translation_memory = original_tm


def test_priority_mode_can_fallback_by_order_when_allowed(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    
    original_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    
    _set_enabled_providers(ai_service.config_manager, {"gemini", "google"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "ai_waterfall"

    class MockRouter:
        def route(self, request, policy):
            assert "gemini" in policy["allowed_providers"]
            assert "google" in policy["allowed_providers"]
            return TranslationResult(
                status="success",
                text="waterfall-ok",
                provider="google",
                model="google-translate",
                attempts=[
                    {"provider": "gemini", "status": "failed", "reason": "api_error"},
                    {"provider": "google", "status": "success"}
                ]
            )

    try:
        monkeypatch.setattr(service, "_get_provider_router", lambda *args: MockRouter())
        
        res = service.translate_text("Hello unique waterfall strict text", "en", "vi")
        assert res == "waterfall-ok"
        assert service.last_translation_metadata["fallback_count"] == 1
    finally:
        ai_service.config_manager.use_translation_memory = original_tm


def test_ui_strategy_mapping_gemini_only_sets_internal_gemini_only():
    service = TranslationService()
    service.set_strategy("chỉ dùng gemini")
    assert service.strategy == "gemini_only"


def test_text_translation_label_does_not_report_google_for_gemini_only_failure(monkeypatch):
    service = TranslationService()
    ai_service = get_ai_service()
    
    original_tm = ai_service.config_manager.use_translation_memory
    ai_service.config_manager.use_translation_memory = False
    
    _set_enabled_providers(ai_service.config_manager, {"gemini", "google"})
    ai_service.config_manager.use_provider_router = True
    service.strategy = "gemini_only"

    class MockRouter:
        def route(self, request, policy):
            return TranslationResult(
                status="error",
                provider="gemini",
                error_type="api_error",
                error_message="Gemini failed",
                attempts=[{"provider": "gemini", "status": "failed", "reason": "api_error"}]
            )

    try:
        monkeypatch.setattr(service, "_get_provider_router", lambda *args: MockRouter())
        
        try:
            service.translate_text("Hello unique telemetry strict text", "en", "vi")
        except Exception:
            pass
            
        meta = service.last_translation_metadata
        assert meta["provider"] == "gemini"
        assert meta["fallback_count"] == 1
        # Check that google is nowhere in attempts
        for attempt in meta["attempts"]:
            assert attempt["provider"] != "google"
    finally:
        ai_service.config_manager.use_translation_memory = original_tm
