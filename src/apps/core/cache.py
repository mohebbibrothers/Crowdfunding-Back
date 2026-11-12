"""کش نسخه‌دار مبتنی بر Epoch برای ابطال فوری و دقیق نماهای عمومی پس از هر تغییر مالی."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from django.core.cache import cache

logger = logging.getLogger(__name__)

EPOCH_TTL_SECONDS = 30 * 24 * 3600
DEFAULT_CACHE_TTL = 120


def _epoch_cache_key(namespace: str, scope: str) -> str:
    return f"epoch:{namespace}:{scope}"


def _safe_get(key: str) -> Any:
    try:
        return cache.get(key)
    except Exception:  # pragma: no cover
        logger.warning("cache_get_degraded", extra={"key": key})
        return None


def _safe_set(key: str, value: Any, timeout: int | None) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:  # pragma: no cover
        logger.warning("cache_set_degraded", extra={"key": key})


def get_epoch(namespace: str, scope: str = "global") -> int:
    """خواندن شمارهٔ نسخهٔ فعلی یک دامنهٔ کش (پیش‌فرض ۱)."""
    raw = _safe_get(_epoch_cache_key(namespace, scope))
    return int(raw) if raw is not None else 1


def bump_epoch(namespace: str, scope: str = "global") -> int:
    """افزایش اتمیک نسخهٔ یک دامنهٔ کش و بی‌اثر کردن فوری تمام کلیدهای قدیمی آن."""
    key = _epoch_cache_key(namespace, scope)
    try:
        if cache.add(key, 2, timeout=EPOCH_TTL_SECONDS):
            return 2
        new_val = int(cache.incr(key))
        cache.touch(key, EPOCH_TTL_SECONDS)
        return new_val
    except Exception:  # pragma: no cover
        next_val = get_epoch(namespace, scope) + 1
        _safe_set(key, next_val, EPOCH_TTL_SECONDS)
        return next_val


def versioned_cache_key(namespace: str, scope: str, suffix: str) -> str:
    """تولید کلید کش شامل شمارهٔ Epoch فعلی دامنه."""
    epoch = get_epoch(namespace, scope)
    return f"vcache:{namespace}:{scope}:e{epoch}:{suffix}"


def get_or_set_versioned[T](
    namespace: str,
    scope: str,
    suffix: str,
    producer: Callable[[], T],
    *,
    timeout: int = DEFAULT_CACHE_TTL,
) -> T:
    """واکشی داده از کش نسخه‌دار یا اجرای سازنده و ذخیرهٔ خروجی در کش."""
    key = versioned_cache_key(namespace, scope, suffix)
    cached = _safe_get(key)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    fresh = producer()
    _safe_set(key, fresh, timeout)
    return fresh
