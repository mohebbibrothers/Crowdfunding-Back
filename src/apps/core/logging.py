"""لاگ‌گیری ساخت‌یافتهٔ JSON همراه با پوشاندن خودکار داده‌های هویتی و مالی (PII Redaction)."""

from __future__ import annotations

from collections.abc import MutableMapping
import re
from typing import Any

import structlog

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "access",
        "refresh",
        "otp",
        "code",
        "national_code",
        "sheba",
        "iban",
        "authorization",
        "cookie",
        "csrftoken",
        "api_key",
    }
)
_IRAN_PHONE_RE = re.compile(r"(?<!\d)(?:\+98|0098|0)?9\d{9}(?!\d)")
_IBAN_RE = re.compile(r"\bIR\d{24}\b", re.IGNORECASE)


def redact_text(text: str) -> str:
    """پوشاندن خودکار شماره‌های موبایل و شبای بانکی درون رشته‌های متنی لاگ."""
    masked = _IRAN_PHONE_RE.sub(lambda m: f"{m.group(0)[:4]}***{m.group(0)[-2:]}", text)
    return _IBAN_RE.sub(lambda m: f"{m.group(0)[:4]}******************{m.group(0)[-4:]}", masked)


def redact_value(key: str, value: Any) -> Any:
    """پوشاندن بازگشتی کلیدها و مقادیر حساس پیش از خروج لاگ به کنسول یا فایل."""
    lowered = key.lower()
    if any(marker in lowered for marker in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if "phone" in lowered or "mobile" in lowered:
        if isinstance(value, str) and len(value) >= 7:
            return f"{value[:4]}***{value[-2:]}"
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(k): redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(key, item) for item in value]
    return value


def pii_redaction_processor(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """پردازشگر structlog برای پالایش تمام کلیدهای رخداد لاگ از داده‌های حساس."""
    del logger, method_name
    sanitized: dict[str, Any] = {}
    for key, val in event_dict.items():
        if key in {"level", "timestamp", "logger", "trace_id", "request_id"}:
            sanitized[key] = val
        else:
            sanitized[key] = redact_value(str(key), val)
    return sanitized


def configure_structlog() -> None:
    """پیکربندی سراسری structlog با پردازشگر حذف PII و خروجی JSON."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            pii_redaction_processor,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
