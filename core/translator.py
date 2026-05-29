"""
Translation service orchestration for TM, glossary, and provider routing.
"""

import concurrent.futures
import threading
from typing import Optional

from deep_translator import GoogleTranslator

from translation_app.config import config
from translation_app.core.ai_service import get_ai_service
from translation_app.core.file_translation_control import FileTranslationStopRequested
from translation_app.core.provider_router import ProviderRouter, TranslationRequest
from translation_app.core.providers import GeminiProvider, GoogleTranslateProvider, OpenAICompatibleProvider, build_provider_profiles
from translation_app.utils.error_handler import TranslationServiceError, handle_translation_error
from translation_app.utils.logger import logger


class TranslationService:
    """Translation service with optimized ThreadPoolExecutor usage."""

    def __init__(self, max_workers: Optional[int] = None, timeout: Optional[int] = None):
        self.max_workers = max_workers or config.max_workers
        self.timeout = timeout or config.translation_timeout
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        self.strategy = "waterfall"  # options: "google", "ai", "waterfall", "ai_waterfall"
        self._observer_lock = threading.RLock()
        self._runtime_observer = None
        self._file_translation_control = None
        self._provider_router = None
        self._provider_router_signature = None
        self.last_translation_metadata = {
            "provider": "",
            "model": "",
            "strategy": "",
            "fallback_count": 0,
            "attempts": []
        }
        logger.info(f"TranslationService initialized with {self.max_workers} workers. Strategy: {self.strategy}")

    def set_strategy(self, strategy: str):
        """Update translation strategy at runtime."""
        mapping = {
            "tự động chọn ai tốt nhất": "waterfall",
            "chỉ dùng ai, không dùng google translate": "ai",
            "chỉ dùng gemini": "gemini_only",
            "chỉ dùng chatanywhere": "chatanywhere_only",
            "chỉ dùng deepseek": "deepseek_only",
            "chỉ dùng nvidia nim": "nvidia_nim_only",
            "chỉ dùng openai tùy chỉnh": "openai_compatible_only",
            "chỉ dùng google translate": "google",
            "nâng cao: dùng thứ tự ưu tiên bên dưới": "ai_waterfall",
        }
        old_mapping = {
            "google translate (mặc định)": "google",
            "gemini ai (chỉ dùng ai)": "ai",
            "google translate -> gemini ai": "waterfall",
            "google -> gemini (waterfall)": "waterfall",
            "gemini ai -> google translate": "ai_waterfall",
            "nâng cao": "ai_waterfall",
        }
        self.strategy = mapping.get(str(strategy or "").lower(), old_mapping.get(str(strategy or "").lower(), "waterfall"))
        logger.info(f"Translation strategy changed to: {self.strategy}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()

    def shutdown(self, wait: bool = True):
        self.executor.shutdown(wait=wait)
        logger.info("TranslationService executor shut down")

    def set_runtime_observer(self, observer):
        with self._observer_lock:
            self._runtime_observer = observer

    def clear_runtime_observer(self):
        with self._observer_lock:
            self._runtime_observer = None

    def set_file_translation_control(self, control) -> None:
        with self._observer_lock:
            self._file_translation_control = control

    def clear_file_translation_control(self) -> None:
        with self._observer_lock:
            self._file_translation_control = None

    def raise_if_file_translation_stopped(self) -> None:
        with self._observer_lock:
            control = self._file_translation_control
        if control is not None:
            control.raise_if_stopped()

    def _emit_runtime_event(self, event: str, **metadata) -> None:
        with self._observer_lock:
            observer = self._runtime_observer
        if observer is None:
            return
        try:
            observer(event, metadata)
        except Exception as exc:
            logger.debug(f"Runtime observer error for event '{event}': {exc}")

    def _build_provider_router_signature(self, config_manager) -> tuple:
        providers_config = config_manager.providers_config
        catalog = config_manager.provider_model_catalog
        return (
            bool(config_manager.use_provider_router),
            config_manager.provider_cooldown_seconds,
            config_manager.provider_router_max_retries,
            tuple(config_manager.provider_order),
            repr(providers_config),
            repr(catalog),
        )

    def _get_provider_router(self, ai_service):
        config_manager = ai_service.config_manager
        signature = self._build_provider_router_signature(config_manager)
        if self._provider_router is not None and self._provider_router_signature == signature:
            return self._provider_router

        router = ProviderRouter(
            cooldown_seconds=config_manager.provider_cooldown_seconds,
            max_retries=config_manager.provider_router_max_retries,
        )
        profiles = build_provider_profiles(config_manager)
        router.register_provider(GeminiProvider(profile=profiles["gemini"]))
        for provider_name in ("chatanywhere", "deepseek", "nvidia_nim", "openai_compatible"):
            router.register_provider(OpenAICompatibleProvider(profile=profiles[provider_name]))
        router.register_provider(GoogleTranslateProvider())
        self._provider_router = router
        self._provider_router_signature = signature
        return router

    def _build_router_policy(self, config_manager) -> dict:
        order = list(config_manager.provider_order) or ["gemini", "chatanywhere", "deepseek", "nvidia_nim", "openai_compatible", "google"]
        ai_provider_order = ["gemini", "chatanywhere", "deepseek", "nvidia_nim", "openai_compatible"]
        non_optional_builtin_providers = set()
        strict_strategy_provider = {
            "gemini_only": "gemini",
            "chatanywhere_only": "chatanywhere",
            "deepseek_only": "deepseek",
            "nvidia_nim_only": "nvidia_nim",
            "openai_compatible_only": "openai_compatible",
        }
        if self.strategy == "ai":
            allowed = ai_provider_order
        elif self.strategy == "ai_waterfall":
            allowed = ai_provider_order + ["google"]
        elif self.strategy == "google":
            allowed = ["google"]
            non_optional_builtin_providers.add("google")
        elif self.strategy == "gemini_only":
            allowed = ["gemini"]
        elif self.strategy == "chatanywhere_only":
            allowed = ["chatanywhere"]
        elif self.strategy == "deepseek_only":
            allowed = ["deepseek"]
        elif self.strategy == "nvidia_nim_only":
            allowed = ["nvidia_nim"]
        elif self.strategy == "openai_compatible_only":
            allowed = ["openai_compatible"]
        else:
            allowed = [provider for provider in order if provider in set(ai_provider_order + ["google"])]
            if "google" not in allowed:
                allowed.append("google")
            non_optional_builtin_providers.add("google")
            if not allowed:
                allowed = ai_provider_order + ["google"]

        # Filter out disabled providers
        providers_config = config_manager.providers_config
        allowed = [
            p for p in allowed
            if p in non_optional_builtin_providers or bool(providers_config.get(p, {}).get("enabled", False))
        ]
        strict_provider_models = {}
        strict_provider_name = strict_strategy_provider.get(self.strategy)
        if strict_provider_name and strict_provider_name in allowed:
            profile = build_provider_profiles(config_manager).get(strict_provider_name)
            if profile and profile.default_model:
                strict_provider_models[strict_provider_name] = profile.default_model

        return {
            "mode": config_manager.provider_router_policy,
            "allowed_providers": allowed,
            "provider_order": [provider for provider in order if provider in allowed] or allowed,
            "strict_provider_models": strict_provider_models,
        }

    def _find_glossary_terms(self, text: str, src_lang: str, dest_lang: str, ai_service) -> list[dict]:
        config_manager = ai_service.config_manager
        if not config_manager.use_glossary or config_manager.glossary_enforcement_level != "prompt":
            return []
        try:
            from translation_app.core.translation_memory import get_tm_manager

            return get_tm_manager().find_relevant_terms(
                text,
                src_lang,
                dest_lang,
                max_terms=config_manager.max_glossary_terms_per_segment,
            )
        except Exception as exc:
            logger.warning(f"Failed to prepare glossary terms for router: {exc}")
            return []

    def _emit_router_attempt_events(self, result, src_lang: str, dest_lang: str) -> None:
        for attempt in result.attempts:
            if attempt.get("status") == "failed":
                self._emit_runtime_event(
                    "provider_call",
                    provider=attempt.get("provider", ""),
                    source_lang=src_lang,
                    target_lang=dest_lang,
                )
                self._emit_runtime_event(
                    "provider_fail",
                    provider=attempt.get("provider", ""),
                    model=attempt.get("model", ""),
                    key_index=attempt.get("key_index", -1),
                    error_type=attempt.get("reason", ""),
                    error_message=attempt.get("message", ""),
                    source_lang=src_lang,
                    target_lang=dest_lang,
                )
            elif attempt.get("status") == "success":
                self._emit_runtime_event(
                    "provider_call",
                    provider=attempt.get("provider", ""),
                    source_lang=src_lang,
                    target_lang=dest_lang,
                )
                self._emit_runtime_event(
                    "provider_success",
                    provider=attempt.get("provider", ""),
                    model=attempt.get("model", ""),
                    key_index=attempt.get("key_index", -1),
                    latency_ms=attempt.get("latency_ms", 0),
                    source_lang=src_lang,
                    target_lang=dest_lang,
                )

    def _translate_with_google(self, text: str, src_lang: str, dest_lang: str) -> str:
        logger.info(f"Mode: {self.strategy.upper()} - Attempting Google Translate...")
        normalized_src = "auto" if src_lang.lower() == "auto" else config.normalize_language_code(src_lang)
        normalized_dest = config.normalize_language_code(dest_lang)
        translator = GoogleTranslator(source=normalized_src, target=normalized_dest)

        max_length = config.max_text_length
        text_chunks = []
        start = 0
        while start < len(text):
            chunk = text[start:start + max_length]
            if chunk.strip():
                text_chunks.append(chunk)
            start += max_length

        translated_chunks = []
        for chunk in text_chunks:
            try:
                if len(chunk) > 5000:
                    sub_chunks = [chunk[i:i + 4000] for i in range(0, len(chunk), 4000)]
                    for sub_chunk in sub_chunks:
                        if sub_chunk.strip():
                            translated_chunks.append(translator.translate(sub_chunk))
                else:
                    translated_chunks.append(translator.translate(chunk))
            except Exception as exc:
                error_msg = str(exc).lower()
                if "text length" in error_msg or "5000" in error_msg:
                    logger.warning(f"Chunk too long ({len(chunk)} chars), splitting further...")
                    sub_chunks = [chunk[i:i + 4000] for i in range(0, len(chunk), 4000)]
                    for sub_chunk in sub_chunks:
                        if sub_chunk.strip():
                            try:
                                translated_chunks.append(translator.translate(sub_chunk))
                            except Exception as nested_exc:
                                logger.warning(f"Error translating sub-chunk: {nested_exc}. Keeping original.")
                                translated_chunks.append(sub_chunk)
                else:
                    logger.warning(f"Error translating chunk: {exc}. Keeping original.")
                    translated_chunks.append(chunk)

        return "".join(translated_chunks)

    def translate_text(self, text: str, src_lang: str, dest_lang: str) -> str:
        self.raise_if_file_translation_stopped()
        if text is None:
            return ""

        text = str(text)
        if not text.strip():
            return text

        from translation_app.core.translation_memory import get_tm_manager

        ai_service = get_ai_service()
        use_tm = ai_service.config_manager.use_translation_memory
        min_len = ai_service.config_manager.min_segment_length_to_cache
        tm_policy = ai_service.config_manager.translation_memory_policy

        if use_tm and tm_policy == "tm_disabled":
            use_tm = False

        if use_tm and len(text.strip()) >= min_len:
            tm = get_tm_manager()
            cached_translation = tm.lookup_segment(src_lang, dest_lang, text)
            if cached_translation is not None:
                if tm_policy == "tm_prefer_cache":
                    self._emit_runtime_event("tm_hit", source_lang=src_lang, target_lang=dest_lang)
                    self.last_translation_metadata = {
                        "provider": "translation_memory",
                        "model": "cache",
                        "strategy": self.strategy,
                        "fallback_count": 0,
                        "attempts": []
                    }
                    return cached_translation
                elif tm_policy == "tm_suggest_only":
                    from translation_app.core.translation_memory import get_segment_hash
                    text_hash = get_segment_hash(src_lang, dest_lang, text)
                    logger.info(f"💡 TM Suggestion (AI translation still runs): hash={text_hash[:8]}..., len={len(text)} chars")
                elif tm_policy == "tm_retranslate_and_update":
                    from translation_app.core.translation_memory import get_segment_hash
                    text_hash = get_segment_hash(src_lang, dest_lang, text)
                    logger.info(f"🔄 TM Retranslate and Update: hash={text_hash[:8]}..., len={len(text)} chars")

        def save_to_tm(translated: str, provider: str, model: str):
            if use_tm and len(text.strip()) >= min_len and translated and translated.strip():
                try:
                    get_tm_manager().save_segment(src_lang, dest_lang, text, translated, provider=provider, model=model)
                except Exception as exc:
                    logger.warning(f"Failed to save translation to TM: {exc}")

        def mark_provider_call(provider: str):
            self._emit_runtime_event("provider_call", provider=provider, source_lang=src_lang, target_lang=dest_lang)

        def mark_provider_success(provider: str, model: str = "", latency_ms: int = 0):
            self._emit_runtime_event(
                "provider_success",
                provider=provider,
                model=model,
                key_index=-1,
                latency_ms=latency_ms,
                source_lang=src_lang,
                target_lang=dest_lang,
            )

        def mark_provider_fail(provider: str, error_type: str = "", error_message: str = "", model: str = "", key_index: int = -1):
            self._emit_runtime_event(
                "provider_fail",
                provider=provider,
                model=model,
                key_index=key_index,
                error_type=error_type,
                error_message=error_message,
                source_lang=src_lang,
                target_lang=dest_lang,
            )

        if ai_service.config_manager.use_provider_router or self.strategy in {
            "gemini_only",
            "deepseek_only",
            "chatanywhere_only",
            "nvidia_nim_only",
            "openai_compatible_only",
        }:
            glossary_terms = self._find_glossary_terms(text, src_lang, dest_lang, ai_service)
            request = TranslationRequest(
                text=text,
                source_lang=src_lang,
                target_lang=dest_lang,
                glossary_terms=glossary_terms,
                strategy=self.strategy,
            )
            router = self._get_provider_router(ai_service)
            result = router.route(request, self._build_router_policy(ai_service.config_manager))
            self._emit_router_attempt_events(result, src_lang, dest_lang)
            if result.status == "success":
                save_to_tm(result.text, provider=result.provider, model=result.model or result.provider)
                failed_attempts = [a for a in result.attempts if a.get("status") == "failed"]
                self.last_translation_metadata = {
                    "provider": result.provider,
                    "model": result.model or result.provider,
                    "strategy": self.strategy,
                    "fallback_count": len(failed_attempts),
                    "attempts": result.attempts
                }
                return result.text
            self.last_translation_metadata = {
                "provider": result.provider or "none",
                "model": result.model or "none",
                "strategy": self.strategy,
                "fallback_count": len([a for a in result.attempts if a.get("status") == "failed"]),
                "attempts": result.attempts
            }
            raise TranslationServiceError(result.error_message or "Translation failed via provider router.")

        if self.strategy == "ai_waterfall":
            logger.info("Mode: AI -> GOOGLE - Attempting Gemini first...")
            try:
                if ai_service.is_available():
                    mark_provider_call("gemini")
                    result = ai_service.translate(text, src_lang, dest_lang, allow_google_fallback=False)
                    if result.get("status") == "success":
                        mark_provider_success("gemini", result.get("model_used", "gemini"))
                        save_to_tm(result["text"], provider="gemini", model=result.get("model_used", "gemini"))
                        self.last_translation_metadata = {
                            "provider": "gemini",
                            "model": result.get("model_used", "gemini"),
                            "strategy": self.strategy,
                            "fallback_count": 0,
                            "attempts": [{"provider": "gemini", "model": result.get("model_used", "gemini"), "status": "success"}]
                        }
                        return result["text"]
                    mark_provider_fail(
                        "gemini",
                        error_type="error",
                        error_message=result.get("error_message") or result.get("text", ""),
                        model=result.get("model_used", "gemini"),
                    )
                logger.warning("Gemini failed in AI->GOOGLE mode, falling back to Google Translate")
            except Exception as exc:
                mark_provider_fail("gemini", error_type="error", error_message=str(exc), model="gemini")
                logger.warning(f"Gemini error in AI->GOOGLE mode: {exc}. Falling back to Google Translate")

        if self.strategy == "ai":
            logger.info("Mode: AI ONLY - Using Gemini for translation...")
            if ai_service.is_available():
                mark_provider_call("gemini")
                result = ai_service.translate(text, src_lang, dest_lang, allow_google_fallback=False)
                if result.get("status") == "success":
                    mark_provider_success("gemini", result.get("model_used", "gemini"))
                    save_to_tm(result["text"], provider="gemini", model=result.get("model_used", "gemini"))
                    self.last_translation_metadata = {
                        "provider": "gemini",
                        "model": result.get("model_used", "gemini"),
                        "strategy": self.strategy,
                        "fallback_count": 0,
                        "attempts": [{"provider": "gemini", "model": result.get("model_used", "gemini"), "status": "success"}]
                    }
                    return result["text"]
                error_msg = result.get("error_message") or result.get("text") or "AI Translation failed"
                mark_provider_fail("gemini", error_type="error", error_message=error_msg, model=result.get("model_used", "gemini"))
                self.last_translation_metadata = {
                    "provider": "gemini",
                    "model": result.get("model_used", "gemini"),
                    "strategy": self.strategy,
                    "fallback_count": 0,
                    "attempts": [{"provider": "gemini", "model": result.get("model_used", "gemini"), "status": "failed", "reason": error_msg}]
                }
                raise TranslationServiceError(f"Gemini AI translation failed: {error_msg}")
            mark_provider_fail("gemini", error_type="unavailable", error_message="Gemini AI translation failed or not configured.", model="gemini")
            self.last_translation_metadata = {
                "provider": "gemini",
                "model": "gemini",
                "strategy": self.strategy,
                "fallback_count": 0,
                "attempts": [{"provider": "gemini", "model": "gemini", "status": "failed", "reason": "unavailable"}]
            }
            raise TranslationServiceError("Gemini AI translation failed or not configured.")

        if self.strategy == "google":
            try:
                mark_provider_call("google")
                translated_text = self._translate_with_google(text, src_lang, dest_lang)
                mark_provider_success("google", "google-translate")
                save_to_tm(translated_text, provider="google", model="google-translate")
                self.last_translation_metadata = {
                    "provider": "google",
                    "model": "google-translate",
                    "strategy": self.strategy,
                    "fallback_count": 0,
                    "attempts": [{"provider": "google", "model": "google-translate", "status": "success"}]
                }
                return translated_text
            except Exception as exc:
                mark_provider_fail("google", error_type="error", error_message=str(exc), model="google-translate")
                error_msg = handle_translation_error(exc, "Translation failed")
                raise TranslationServiceError(error_msg, original_error=exc) from exc

        try:
            mark_provider_call("google")
            translated_text = self._translate_with_google(text, src_lang, dest_lang)
            mark_provider_success("google", "google-translate")
            save_to_tm(translated_text, provider="google", model="google-translate")
            self.last_translation_metadata = {
                "provider": "google",
                "model": "google-translate",
                "strategy": self.strategy,
                "fallback_count": 0,
                "attempts": [{"provider": "google", "model": "google-translate", "status": "success"}]
            }
            return translated_text

        except Exception as exc:
            mark_provider_fail("google", error_type="error", error_message=str(exc), model="google-translate")
            logger.warning(f"Primary translation (Google) failed: {exc}. Attempting AI Waterfall...")
            try:
                if ai_service.is_available():
                    mark_provider_call("gemini")
                    result = ai_service.translate(text, src_lang, dest_lang, allow_google_fallback=False)
                    if result.get("status") == "success":
                        logger.info(f"AI Waterfall success using: {result.get('model_used')}")
                        mark_provider_success("gemini", result.get("model_used", "gemini"))
                        save_to_tm(result["text"], provider="gemini", model=result.get("model_used", "gemini"))
                        self.last_translation_metadata = {
                            "provider": "gemini",
                            "model": result.get("model_used", "gemini"),
                            "strategy": self.strategy,
                            "fallback_count": 1,
                            "attempts": [
                                {"provider": "google", "model": "google-translate", "status": "failed", "reason": str(exc)},
                                {"provider": "gemini", "model": result.get("model_used", "gemini"), "status": "success"}
                            ]
                        }
                        return result["text"]
                    mark_provider_fail(
                        "gemini",
                        error_type="error",
                        error_message=result.get("error_message") or result.get("text", ""),
                        model=result.get("model_used", "gemini"),
                    )

                self.last_translation_metadata = {
                    "provider": "gemini",
                    "model": "gemini",
                    "strategy": self.strategy,
                    "fallback_count": 1,
                    "attempts": [
                        {"provider": "google", "model": "google-translate", "status": "failed", "reason": str(exc)},
                        {"provider": "gemini", "model": "gemini", "status": "failed", "reason": "ai_waterfall_failed"}
                    ]
                }
                error_msg = handle_translation_error(exc, "Translation failed")
                logger.error(f"Translation error: {exc}")
                raise TranslationServiceError(error_msg, original_error=exc) from exc
            except Exception as ai_err:
                mark_provider_fail("gemini", error_type="error", error_message=str(ai_err), model="gemini")
                logger.error(f"AI fallback also failed: {ai_err}")
                error_msg = handle_translation_error(exc, "Translation failed")
                raise TranslationServiceError(error_msg, original_error=exc) from exc

    def translate_long_text(self, text: str, src_lang: str, dest_lang: str, max_length: Optional[int] = None) -> str:
        if text is None:
            return ""

        text = str(text)
        if not text.strip() or len(text.strip()) < 2:
            return text

        if max_length is None:
            max_length = config.max_text_length
        elif max_length > config.max_text_length:
            max_length = config.max_text_length

        result = []
        start = 0
        while start < len(text):
            self.raise_if_file_translation_stopped()
            chunk = text[start:start + max_length]
            if not chunk.strip() or len(chunk.strip()) < 2:
                result.append(chunk)
            else:
                try:
                    result.append(self.translate_text(chunk, src_lang, dest_lang))
                except Exception as exc:
                    error_msg = str(exc).lower()
                    if "text length" in error_msg or "5000" in error_msg:
                        logger.warning(f"Chunk too long ({len(chunk)} chars), splitting in translate_long_text...")
                        sub_chunks = [chunk[i:i + 4000] for i in range(0, len(chunk), 4000)]
                        for sub_chunk in sub_chunks:
                            self.raise_if_file_translation_stopped()
                            if sub_chunk.strip():
                                try:
                                    result.append(self.translate_text(sub_chunk, src_lang, dest_lang))
                                except FileTranslationStopRequested:
                                    raise
                                except Exception as nested_exc:
                                    logger.warning(f"Error translating sub-chunk: {nested_exc}. Keeping original.")
                                    result.append(sub_chunk)
                    elif isinstance(exc, FileTranslationStopRequested):
                        raise
                    else:
                        logger.warning(f"Error translating chunk (len={len(chunk)}): {exc}. Keeping original.")
                        result.append(chunk)
            start += max_length

        return "".join(result)

    def translate_batch(self, texts: list[str], src_lang: str, dest_lang: str) -> list[str]:
        if not texts:
            return []

        results_map: dict[int, str] = {}
        valid_texts_with_indices: list[tuple[int, str]] = []

        for index, text in enumerate(texts):
            if text is not None and isinstance(text, str) and text.strip():
                valid_texts_with_indices.append((index, text))
            else:
                results_map[index] = text if text is not None else ""

        futures_with_indices: list[tuple[int, concurrent.futures.Future]] = []
        for index, text in valid_texts_with_indices:
            self.raise_if_file_translation_stopped()
            future = self.executor.submit(self.translate_text, text, src_lang, dest_lang)
            futures_with_indices.append((index, future))

        for index, future in futures_with_indices:
            self.raise_if_file_translation_stopped()
            try:
                result = future.result(timeout=self.timeout)
                results_map[index] = result if result is not None else ""
            except FileTranslationStopRequested:
                raise
            except concurrent.futures.TimeoutError:
                logger.warning(f"Translation timeout for text at index {index}, keeping original")
                original_text = texts[index] if index < len(texts) else ""
                results_map[index] = original_text if original_text is not None else ""
            except Exception as exc:
                logger.error(f"Translation failed for text at index {index}: {exc}, keeping original")
                original_text = texts[index] if index < len(texts) else ""
                results_map[index] = original_text if original_text is not None else ""

        return [results_map[index] for index in range(len(texts))]


_translation_service: Optional[TranslationService] = None


def get_translation_service() -> TranslationService:
    global _translation_service
    if _translation_service is None:
        _translation_service = TranslationService()
    return _translation_service


def set_translation_service(service: TranslationService):
    global _translation_service
    _translation_service = service
