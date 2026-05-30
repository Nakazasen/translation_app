"""
Smart Provider & Model Health Checker for Phase 5J.
Allows testing of specific providers, models, or bulk auditing of all configurations.
"""

from __future__ import annotations

import time
import datetime
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable

from translation_app.core.ai_service import get_ai_service
from translation_app.core.provider_router import TranslationRequest, TranslationResult, classify_error
from translation_app.core.providers.profiles import ProviderProfile, build_provider_profiles
from translation_app.core.providers import (
    GeminiProvider,
    GoogleTranslateProvider,
    OpenAICompatibleProvider,
    CloudflareProvider,
    HuggingFaceProvider,
)
from translation_app.utils.logger import logger

STATUS_MESSAGES = {
    "ok": "Kết nối thành công! Hoạt động hoàn hảo.",
    "missing_key": "Thiếu API Key hoặc khóa chưa được dán vào ứng dụng.",
    "auth_error": "Lỗi xác thực (API Key không hợp lệ hoặc đã bị hủy).",
    "quota_or_rate_limited": "Hết hạn mức gọi API (Quota Exceeded / Rate Limited).",
    "model_not_found": "Mô hình (Model ID) không tồn tại hoặc không được hỗ trợ bởi tài khoản.",
    "endpoint_not_found": "Sai URL/Endpoint hoặc đường dẫn API của nhà cung cấp không khả dụng.",
    "payload_error": "Tham số hoặc dữ liệu gửi đi không được nhà cung cấp chấp nhận.",
    "timeout": "Thời gian phản hồi quá lâu (Timeout).",
    "network_error": "Lỗi mạng hoặc không thể kết nối tới máy chủ.",
    "provider_disabled": "Nhà cung cấp hiện đang bị tắt trong cài đặt.",
    "cancelled": "Yêu cầu kiểm tra đã bị dừng theo ý muốn của người dùng.",
    "unsupported": "Phương thức kiểm tra chưa được hỗ trợ cho nhà cung cấp này.",
    "unknown_error": "Lỗi không xác định."
}

SUGGESTIONS = {
    "ok": "Sẵn sàng sử dụng. Bạn có thể thêm vào Pool AI miễn phí.",
    "missing_key": "Vui lòng xem hướng dẫn lấy key phía dưới, sao chép key và dán vào cài đặt nhà cung cấp ở bảng trên.",
    "auth_error": "Kiểm tra lại xem API Key có bị thừa khoảng trắng không, hoặc tạo một API key mới.",
    "quota_or_rate_limited": "Đợi 1 phút để reset giới hạn RPM, hoặc thêm các nhà cung cấp khác để Smart Router tự xoay vòng.",
    "model_not_found": "Kiểm tra lại Model ID. Hãy sao chép model gợi ý từ hướng dẫn bên dưới.",
    "endpoint_not_found": "Kiểm tra lại độ chính xác của Base URL/Endpoint trong cấu hình của nhà cung cấp.",
    "payload_error": "Kiểm tra cấu hình hoặc tham số gửi đi xem có phù hợp với đặc tả của nhà cung cấp.",
    "timeout": "Kiểm tra lại đường truyền mạng hoặc cấu hình Proxy/VPN nếu có.",
    "network_error": "Kiểm tra lại kết nối internet hoặc tính chính xác của Base URL (nếu có cấu hình).",
    "provider_disabled": "Tích chọn 'Bật nhà cung cấp này trong hệ thống' ở bảng phía trên rồi lưu lại.",
    "cancelled": "Bạn đã dừng tiến trình kiểm tra thủ công.",
    "unsupported": "Hãy liên hệ tác giả để cập nhật adapter tương thích.",
    "unknown_error": "Kiểm tra chi tiết lỗi bên dưới hoặc thử lại sau vài giây."
}


@dataclass
class ProviderHealthResult:
    provider_id: str
    provider_name: str
    model_id: str
    status: str
    error_category: str
    message: str
    latency_ms: int = 0
    checked_at: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    suggestion: str = ""
    raw_error_sanitized: str = ""


def classify_provider_error(error_type_str: str) -> str:
    """Map string from provider_router's classify_error to ProviderHealthResult status."""
    mapping = {
        "auth_failure": "auth_error",
        "quota_rate_limit": "quota_or_rate_limited",
        "token_limit": "quota_or_rate_limited",
        "timeout": "timeout",
        "transport_error": "network_error",
        "unknown_transport_error": "network_error",
        "model_error": "model_not_found",
        "model_unavailable": "model_not_found",
        "provider_5xx": "network_error",
        "endpoint_not_found": "endpoint_not_found",
        "payload_error": "payload_error",
        "cancelled": "cancelled"
    }
    return mapping.get(error_type_str, "unknown_error")


class ProviderHealthChecker:
    """Core logic to check connection and model responsiveness."""

    def __init__(self, config_manager=None, provider_router=None, cancel_event=None):
        self.ai_service = get_ai_service()
        self.config_manager = config_manager or (self.ai_service.config_manager if self.ai_service else None)
        self.provider_router = provider_router
        self.cancel_event = cancel_event
        if not self.provider_router and self.ai_service and hasattr(self.ai_service, "translation_service"):
            self.provider_router = getattr(self.ai_service.translation_service, "_provider_router", None)

    def check_provider(self, provider_id: str, model_id: Optional[str] = None, on_result: Optional[Callable[[ProviderHealthResult], None]] = None) -> ProviderHealthResult:
        """Check connection for a provider using its default or specified model."""
        if self.cancel_event and self.cancel_event.is_set():
            res = self._create_cancelled_result(provider_id, model_id or "")
            if on_result:
                try:
                    on_result(res)
                except Exception:
                    pass
            return res

        if provider_id == "google":
            # Google Translate is checked using a lightweight translation request
            started = time.time()
            try:
                request = TranslationRequest(
                    text="Health check OK",
                    source_lang="en",
                    target_lang="vi"
                )
                provider = GoogleTranslateProvider()
                result = provider.translate(request)
                latency = round((time.time() - started) * 1000)

                if result.status == "success":
                    self._update_router_health(provider_id, "google-translate", result)
                    res = ProviderHealthResult(
                        provider_id=provider_id,
                        provider_name="Google Translate",
                        model_id="google-translate",
                        status="ok",
                        error_category="",
                        message=STATUS_MESSAGES["ok"],
                        latency_ms=latency,
                        suggestion=SUGGESTIONS["ok"]
                    )
                else:
                    err_cat = classify_provider_error(result.error_type)
                    self._update_router_health(provider_id, "google-translate", result)
                    res = ProviderHealthResult(
                        provider_id=provider_id,
                        provider_name="Google Translate",
                        model_id="google-translate",
                        status=err_cat,
                        error_category=result.error_type,
                        message=STATUS_MESSAGES.get(err_cat, STATUS_MESSAGES["unknown_error"]),
                        latency_ms=latency,
                        suggestion=SUGGESTIONS.get(err_cat, SUGGESTIONS["unknown_error"]),
                        raw_error_sanitized=result.error_message
                    )
            except Exception as e:
                latency = round((time.time() - started) * 1000)
                err_type = classify_error(e)
                err_cat = classify_provider_error(err_type)
                res = ProviderHealthResult(
                    provider_id=provider_id,
                    provider_name="Google Translate",
                    model_id="google-translate",
                    status=err_cat,
                    error_category=err_type,
                    message=STATUS_MESSAGES.get(err_cat, STATUS_MESSAGES["unknown_error"]),
                    latency_ms=latency,
                    suggestion=SUGGESTIONS.get(err_cat, SUGGESTIONS["unknown_error"]),
                    raw_error_sanitized=str(e)
                )

            if on_result:
                try:
                    on_result(res)
                except Exception:
                    pass
            return res

        if not self.config_manager:
            res = ProviderHealthResult(
                provider_id=provider_id,
                provider_name=provider_id.upper(),
                model_id=model_id or "",
                status="unknown_error",
                error_category="config_missing",
                message="Không thể tìm thấy cấu hình hệ thống.",
                suggestion=SUGGESTIONS["unknown_error"]
            )
            if on_result:
                try:
                    on_result(res)
                except Exception:
                    pass
            return res

        profiles = build_provider_profiles(self.config_manager)
        if provider_id not in profiles:
            res = ProviderHealthResult(
                provider_id=provider_id,
                provider_name=provider_id.upper(),
                model_id=model_id or "",
                status="unsupported",
                error_category="provider_unsupported",
                message=STATUS_MESSAGES["unsupported"],
                suggestion=SUGGESTIONS["unsupported"]
            )
            if on_result:
                try:
                    on_result(res)
                except Exception:
                    pass
            return res

        profile = profiles[provider_id]

        # Determine candidate model
        check_model = model_id or profile.default_model or (profile.model_pool[0] if profile.model_pool else "")
        if not check_model:
            # Fallback to catalog defaults just in case
            catalog = self.config_manager.get_provider_model_catalog_public()
            cat_entry = catalog.get("providers", {}).get(provider_id, {})
            check_model = cat_entry.get("default_model") or (cat_entry.get("models", [{}])[0].get("id") if cat_entry.get("models") else "")

        if not check_model:
            res = ProviderHealthResult(
                provider_id=provider_id,
                provider_name=profile.display_name,
                model_id="",
                status="model_not_found",
                error_category="no_model_configured",
                message=STATUS_MESSAGES["model_not_found"],
                suggestion=SUGGESTIONS["model_not_found"]
            )
            if on_result:
                try:
                    on_result(res)
                except Exception:
                    pass
            return res

        # Check for missing keys (unless local is allowed without key)
        if not profile.api_key_pool:
            if not (profile.allow_no_key_local and profile.base_url and "localhost" in profile.base_url.lower()):
                res = ProviderHealthResult(
                    provider_id=provider_id,
                    provider_name=profile.display_name,
                    model_id=check_model,
                    status="missing_key",
                    error_category="missing_key",
                    message=STATUS_MESSAGES["missing_key"],
                    suggestion=SUGGESTIONS["missing_key"]
                )
                if on_result:
                    try:
                        on_result(res)
                    except Exception:
                        pass
                return res

        # Construct a temporary normalized profile configured strictly for this check
        temp_profile = ProviderProfile(
            name=profile.name,
            display_name=profile.display_name,
            provider_type=profile.provider_type,
            enabled=True,  # Enforce active for validation
            base_url=profile.base_url,
            api_key_pool=profile.api_key_pool,
            model_pool=[check_model],
            timeout=10,  # Short timeout for diagnostics
            supports_glossary=profile.supports_glossary,
            allow_no_key_local=profile.allow_no_key_local,
            default_model=check_model
        ).normalized()

        # Build provider class instance
        provider_instance = None
        if provider_id == "gemini":
            provider_instance = GeminiProvider(profile=temp_profile)
        elif provider_id == "cloudflare":
            provider_instance = CloudflareProvider(profile=temp_profile)
        elif provider_id == "huggingface":
            provider_instance = HuggingFaceProvider(profile=temp_profile)
        else:
            provider_instance = OpenAICompatibleProvider(profile=temp_profile)

        # Light probe using a short completion prompt
        request = TranslationRequest(
            text="Health check OK",
            source_lang="en",
            target_lang="vi"
        )

        started = time.time()
        try:
            result = provider_instance.translate(request)
            latency = round((time.time() - started) * 1000)

            if self.cancel_event and self.cancel_event.is_set():
                res = self._create_cancelled_result(provider_id, check_model)
                if on_result:
                    try:
                        on_result(res)
                    except Exception:
                        pass
                return res

            if result.status == "success":
                self._update_router_health(provider_id, check_model, result)
                res = ProviderHealthResult(
                    provider_id=provider_id,
                    provider_name=profile.display_name,
                    model_id=check_model,
                    status="ok",
                    error_category="",
                    message=STATUS_MESSAGES["ok"],
                    latency_ms=latency,
                    suggestion=SUGGESTIONS["ok"]
                )
            else:
                # Custom HTTP status code check
                status_code = None
                if result.error_message:
                    # Parse status code if it's like "HTTP 404"
                    status_match = re.search(r"HTTP\s+(\d+)", result.error_message)
                    if status_match:
                        status_code = int(status_match.group(1))

                err_cat = classify_provider_error(result.error_type)

                # Refine 404/400 classification
                if status_code == 404:
                    err_msg_lower = (result.error_message or "").lower()
                    model_hints = ["model", "engine", "no endpoints found", "does not exist", "no such model", "unknown model"]
                    if any(h in err_msg_lower for h in model_hints):
                        err_cat = "model_not_found"
                    else:
                        err_cat = "endpoint_not_found"
                elif status_code == 400:
                    err_msg_lower = (result.error_message or "").lower()
                    model_hints = ["model", "engine", "not found", "does not exist", "no such model", "unknown model"]
                    if any(h in err_msg_lower for h in model_hints):
                        err_cat = "model_not_found"
                    else:
                        err_cat = "payload_error"

                self._update_router_health(provider_id, check_model, result)
                res = ProviderHealthResult(
                    provider_id=provider_id,
                    provider_name=profile.display_name,
                    model_id=check_model,
                    status=err_cat,
                    error_category=result.error_type,
                    message=STATUS_MESSAGES.get(err_cat, STATUS_MESSAGES["unknown_error"]),
                    latency_ms=latency,
                    suggestion=SUGGESTIONS.get(err_cat, SUGGESTIONS["unknown_error"]),
                    raw_error_sanitized=result.error_message
                )
        except Exception as e:
            latency = round((time.time() - started) * 1000)
            err_type = classify_error(e)
            err_cat = classify_provider_error(err_type)

            # Custom check for HTTPError with code 404 in exceptions
            status_code = getattr(e, "code", getattr(e, "status_code", None))
            if status_code == 404:
                err_msg_lower = str(e).lower()
                model_hints = ["model", "engine", "no endpoints found", "does not exist", "no such model", "unknown model"]
                if any(h in err_msg_lower for h in model_hints):
                    err_cat = "model_not_found"
                else:
                    err_cat = "endpoint_not_found"
            elif status_code == 400:
                err_msg_lower = str(e).lower()
                model_hints = ["model", "engine", "not found", "does not exist", "no such model", "unknown model"]
                if any(h in err_msg_lower for h in model_hints):
                    err_cat = "model_not_found"
                else:
                    err_cat = "payload_error"

            res = ProviderHealthResult(
                provider_id=provider_id,
                provider_name=profile.display_name,
                model_id=check_model,
                status=err_cat,
                error_category=err_type,
                message=STATUS_MESSAGES.get(err_cat, STATUS_MESSAGES["unknown_error"]),
                latency_ms=latency,
                suggestion=SUGGESTIONS.get(err_cat, SUGGESTIONS["unknown_error"]),
                raw_error_sanitized=str(e)
            )

        if on_result:
            try:
                on_result(res)
            except Exception:
                pass
        return res

    def check_model(self, provider_id: str, model_id: str, on_result: Optional[Callable[[ProviderHealthResult], None]] = None) -> ProviderHealthResult:
        """Check connection for a specific custom model."""
        return self.check_provider(provider_id, model_id=model_id, on_result=on_result)

    def check_provider_models(self, provider_id: str, model_ids: Optional[list[str]] = None, on_result: Optional[Callable[[ProviderHealthResult], None]] = None) -> list[ProviderHealthResult]:
        """Audit multiple model IDs for a single provider."""
        if not model_ids:
            if not self.config_manager:
                return []
            profiles = build_provider_profiles(self.config_manager)
            profile = profiles.get(provider_id)
            model_ids = list(profile.model_pool) if profile else []

        results = []
        if not model_ids:
            if self.cancel_event and self.cancel_event.is_set():
                res = self._create_cancelled_result(provider_id, "")
                if on_result:
                    try:
                        on_result(res)
                    except Exception:
                        pass
                results.append(res)
            else:
                results.append(self.check_provider(provider_id, on_result=on_result))
        else:
            for model_id in model_ids:
                if self.cancel_event and self.cancel_event.is_set():
                    res = self._create_cancelled_result(provider_id, model_id)
                    if on_result:
                        try:
                            on_result(res)
                        except Exception:
                            pass
                    results.append(res)
                else:
                    results.append(self.check_model(provider_id, model_id, on_result=on_result))
        return results

    def check_all_configured(self, limit_per_provider: Optional[int] = None, on_result: Optional[Callable[[ProviderHealthResult], None]] = None) -> list[ProviderHealthResult]:
        """Audit all enabled providers and their configured models simultaneously."""
        results = []
        if not self.config_manager:
            return results

        profiles = build_provider_profiles(self.config_manager)
        for provider_id, profile in profiles.items():
            if self.cancel_event and self.cancel_event.is_set():
                continue

            # Skip disabled providers as requested
            if not profile.enabled:
                continue

            models = list(profile.model_pool)
            if limit_per_provider and len(models) > limit_per_provider:
                models = models[:limit_per_provider]

            if not models:
                if self.cancel_event and self.cancel_event.is_set():
                    res = self._create_cancelled_result(provider_id, "")
                    if on_result:
                        try:
                            on_result(res)
                        except Exception:
                            pass
                    results.append(res)
                else:
                    results.append(self.check_provider(provider_id, on_result=on_result))
            else:
                for model_id in models:
                    if self.cancel_event and self.cancel_event.is_set():
                        res = self._create_cancelled_result(provider_id, model_id)
                        if on_result:
                            try:
                                on_result(res)
                            except Exception:
                                pass
                        results.append(res)
                    else:
                        results.append(self.check_model(provider_id, model_id, on_result=on_result))
        return results

    def _create_cancelled_result(self, provider_id: str, model_id: str) -> ProviderHealthResult:
        return ProviderHealthResult(
            provider_id=provider_id,
            provider_name=provider_id.upper(),
            model_id=model_id,
            status="cancelled",
            error_category="cancelled",
            message=STATUS_MESSAGES["cancelled"],
            suggestion=SUGGESTIONS["cancelled"]
        )

    def _update_router_health(self, provider_id: str, model_id: str, result: TranslationResult) -> None:
        """Update shared runtime router state to keep router and checks fully in sync."""
        if not self.provider_router:
            return

        try:
            # Find key index from result
            key_index = result.key_index if result.key_index >= 0 else None
            key_id = result.key_id if result.key_id else None

            if result.status == "success":
                self.provider_router.mark_success(
                    provider_id,
                    model_id,
                    result.latency_ms,
                    key_index=key_index,
                    key_id=key_id,
                    display_name=provider_id.upper()
                )
            else:
                self.provider_router.mark_failure(
                    provider_id,
                    model_id,
                    result.error_type or "health_check_failed",
                    result.latency_ms,
                    key_index=key_index,
                    key_id=key_id,
                    display_name=provider_id.upper()
                )
        except Exception as e:
            logger.debug(f"Failed to update ProviderRouter states: {e}")
