"""
Small checkpoint cache for resumable file translation.

The cache is intentionally file/segment scoped. It is used only while a file is
in progress, so a failed or cancelled run can continue without re-calling AI for
segments that already succeeded.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from translation_app.core.translation_job import iso_timestamp
from translation_app.core.translation_memory import get_segment_hash
from translation_app.utils.logger import logger

CACHE_SCHEMA_VERSION = 2
_CACHE_METADATA_FIELDS = {
    "provider_policy",
    "strategy",
    "provider_id",
    "model_id",
    "handler_version",
    "strict_provider_model",
}


def get_incremental_cache_dir() -> Path:
    cache_dir = Path(__file__).resolve().parent.parent / "data" / "incremental_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def build_file_fingerprint(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_cache_key(input_file: str, src_lang: str, dest_lang: str, handler_name: str) -> str:
    normalized = "|".join(
        [
            os.path.abspath(input_file),
            build_file_fingerprint(input_file),
            str(src_lang or ""),
            str(dest_lang or ""),
            str(handler_name or ""),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_cache_path(input_file: str, src_lang: str, dest_lang: str, handler_name: str) -> Path:
    return get_incremental_cache_dir() / f"{build_cache_key(input_file, src_lang, dest_lang, handler_name)}.json"


def build_cache_metadata(
    *,
    provider_policy: str = "",
    strategy: str = "",
    provider_id: str = "",
    model_id: str = "",
    handler_version: str = "",
    strict_provider_model: bool = False,
) -> dict[str, Any]:
    return {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "provider_policy": str(provider_policy or strategy or ""),
        "strategy": str(strategy or ""),
        "provider_id": str(provider_id or ""),
        "model_id": str(model_id or ""),
        "handler_version": str(handler_version or ""),
        "strict_provider_model": bool(strict_provider_model),
    }


def _normalize_cache_metadata(metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return build_cache_metadata(
        **{
            key: value
            for key, value in (metadata or {}).items()
            if key in _CACHE_METADATA_FIELDS
        }
    )


def _new_cache_payload(
    input_file: str,
    src_lang: str,
    dest_lang: str,
    handler_name: str,
    fingerprint: str,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    normalized_metadata = _normalize_cache_metadata(metadata)
    return {
        "cache_schema_version": normalized_metadata["cache_schema_version"],
        "input_file": os.path.abspath(input_file),
        "source_file_hash": fingerprint,
        "source_lang": src_lang,
        "target_lang": dest_lang,
        "handler": handler_name,
        "provider_policy": normalized_metadata["provider_policy"],
        "strategy": normalized_metadata["strategy"],
        "provider_id": normalized_metadata["provider_id"],
        "model_id": normalized_metadata["model_id"],
        "handler_version": normalized_metadata["handler_version"],
        "strict_provider_model": normalized_metadata["strict_provider_model"],
        "updated_at": iso_timestamp(),
        "segments": {},
    }


def _cache_provider_model_matches(
    payload: dict[str, Any],
    expected_metadata: Optional[dict[str, Any]],
    strict_provider_model: bool,
) -> bool:
    if not strict_provider_model:
        return True

    metadata = _normalize_cache_metadata(expected_metadata)
    expected_provider = metadata["provider_id"]
    expected_model = metadata["model_id"]

    # Strict provider/model invalidation should only be enabled by callers that
    # can provide stable provider/model identity for the whole resumable job.
    if expected_provider and str(payload.get("provider_id") or "") != expected_provider:
        return False
    if expected_model and str(payload.get("model_id") or "") != expected_model:
        return False
    return True


def load_incremental_cache(
    input_file: str,
    src_lang: str,
    dest_lang: str,
    handler_name: str,
    *,
    metadata: Optional[dict[str, Any]] = None,
    strict_provider_model: bool = False,
) -> dict[str, Any]:
    path = get_cache_path(input_file, src_lang, dest_lang, handler_name)
    fingerprint = build_file_fingerprint(input_file)
    effective_metadata = dict(metadata or {})
    if strict_provider_model:
        effective_metadata["strict_provider_model"] = True
    default_payload = _new_cache_payload(input_file, src_lang, dest_lang, handler_name, fingerprint, effective_metadata)

    if not path.exists():
        return default_payload

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        logger.warning(f"Ignoring unreadable incremental cache '{path}': {exc}")
        return default_payload

    if payload.get("source_file_hash") != fingerprint:
        return default_payload
    if payload.get("source_lang") != src_lang or payload.get("target_lang") != dest_lang:
        return default_payload
    if payload.get("handler") != handler_name:
        return default_payload
    if not _cache_provider_model_matches(payload, effective_metadata, strict_provider_model):
        return default_payload

    normalized_metadata = _normalize_cache_metadata(effective_metadata)
    payload.setdefault("cache_schema_version", 1)
    payload.setdefault("input_file", os.path.abspath(input_file))
    payload.setdefault("provider_policy", normalized_metadata["provider_policy"])
    payload.setdefault("strategy", normalized_metadata["strategy"])
    payload.setdefault("provider_id", normalized_metadata["provider_id"])
    payload.setdefault("model_id", normalized_metadata["model_id"])
    payload.setdefault("handler_version", normalized_metadata["handler_version"])
    payload.setdefault("strict_provider_model", normalized_metadata["strict_provider_model"])
    if not isinstance(payload.get("segments"), dict):
        payload["segments"] = {}
    return payload


def save_incremental_cache(
    input_file: str,
    src_lang: str,
    dest_lang: str,
    handler_name: str,
    payload: dict[str, Any],
    *,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    path = get_cache_path(input_file, src_lang, dest_lang, handler_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_metadata = _normalize_cache_metadata(metadata)
    payload.setdefault("cache_schema_version", CACHE_SCHEMA_VERSION)
    payload.setdefault("input_file", os.path.abspath(input_file))
    payload.setdefault("source_file_hash", build_file_fingerprint(input_file))
    payload.setdefault("source_lang", src_lang)
    payload.setdefault("target_lang", dest_lang)
    payload.setdefault("handler", handler_name)
    payload.setdefault("provider_policy", normalized_metadata["provider_policy"])
    payload.setdefault("strategy", normalized_metadata["strategy"])
    payload.setdefault("provider_id", normalized_metadata["provider_id"])
    payload.setdefault("model_id", normalized_metadata["model_id"])
    payload.setdefault("handler_version", normalized_metadata["handler_version"])
    payload.setdefault("strict_provider_model", normalized_metadata["strict_provider_model"])
    payload["updated_at"] = iso_timestamp()
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def clear_incremental_cache(input_file: str, src_lang: str, dest_lang: str, handler_name: str) -> None:
    path = get_cache_path(input_file, src_lang, dest_lang, handler_name)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug(f"Failed to clear incremental cache '{path}': {exc}")


def get_cached_translation(cache_payload: dict[str, Any], segment_id: str, src_lang: str, dest_lang: str, source_text: str) -> Optional[str]:
    segment = (cache_payload.get("segments") or {}).get(segment_id)
    if not isinstance(segment, dict):
        return None
    expected_hash = get_segment_hash(src_lang, dest_lang, source_text)
    if segment.get("source_hash") != expected_hash:
        return None
    translated_text = segment.get("translated_text")
    if translated_text is None:
        return None
    return str(translated_text)


def record_cached_translation(
    cache_payload: dict[str, Any],
    segment_id: str,
    src_lang: str,
    dest_lang: str,
    source_text: str,
    translated_text: str,
) -> None:
    segments = cache_payload.setdefault("segments", {})
    segments[segment_id] = {
        "source_hash": get_segment_hash(src_lang, dest_lang, source_text),
        "translated_text": translated_text,
        "updated_at": iso_timestamp(),
    }
